import os
import logging
import csv
import io
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError
from config import DATABASE_URL
from datetime import datetime

logger = logging.getLogger(__name__)

Base = declarative_base()

class Lead(Base):
    """
    Model representing a prospect/lead extracted from an event page.
    """
    __tablename__ = 'leads'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True) # Changed from nullable=False to support phone-only leads
    phone = Column(String(50), nullable=True)
    event_name = Column(String(255), nullable=True)
    event_url = Column(Text, nullable=True)
    event_start_date = Column(DateTime, nullable=True)
    event_end_date = Column(DateTime, nullable=True)
    website = Column(Text, nullable=True)

    # ProDev prospecting classification
    persona_type = Column(String(100), nullable=True)   # e.g. 'evinra_events', 'old_client'
    target_product = Column(String(100), nullable=True) # e.g. 'Evinra', 'TravelorHub'
    source_type = Column(String(50), default='web_search') # 'web_search', 'csv_import', 'manual'
    notes = Column(Text, nullable=True)

    # State tracking
    status = Column(String(50), default='new') # new, marketed, responded, invalid
    campaign_sent = Column(Boolean, default=False)
    response_detected = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('email', 'event_name', name='uix_email_event_name'),
    )


class LeadRepository:
    """
    Repository pattern to abstract database operations.
    Allows easy migration to PostgreSQL or others by just changing DATABASE_URL.
    """
    def __init__(self, db_url=DATABASE_URL):
        self.engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self.engine)
        self._run_migrations()
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def _run_migrations(self):
        from sqlalchemy import text
        try:
            with self.engine.connect() as conn:
                res = conn.execute(text("PRAGMA table_info(leads)")).fetchall()
                existing_cols = [row[1] for row in res]
                
                new_columns = {
                    "website": "TEXT",
                    "persona_type": "VARCHAR(100)",
                    "target_product": "VARCHAR(100)",
                    "source_type": "VARCHAR(50) DEFAULT 'web_search'",
                    "notes": "TEXT"
                }
                
                for col_name, col_type in new_columns.items():
                    if col_name not in existing_cols:
                        logger.info(f"Database Migration: Adding column '{col_name}' to table 'leads'")
                        conn.execute(text(f"ALTER TABLE leads ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
        except Exception as e:
            logger.error(f"Error running database migrations: {e}")

    def add_lead(self, lead_data: dict) -> tuple[Lead, bool]:
        """
        Adds a single lead to the database. Returns a tuple (Lead, is_new).
        is_new is True if the lead was freshly inserted, False if it already existed.
        Ignores duplicates based on the Unique Constraint on 'email'.
        """
        session = self.SessionLocal()
        try:
            # Enhanced existence check: handle cases where email might be None
            email = lead_data.get('email')
            phone = lead_data.get('phone')
            event_name = lead_data.get('event_name')

            query = session.query(Lead).filter(Lead.event_name == event_name)
            if email:
                existing_lead = query.filter(Lead.email == email).first()
            elif phone:
                existing_lead = query.filter(Lead.phone == phone).first()
            else:
                existing_lead = None

            if existing_lead:
                logger.debug(f"Lead already exists (email={email}, phone={phone}) for event {event_name}. Skipping.")
                return existing_lead, False
            
            new_lead = Lead(**lead_data)
            session.add(new_lead)
            session.commit()
            session.refresh(new_lead)
            logger.info(f"Successfully added lead: {new_lead.email}")
            return new_lead, True
        except IntegrityError:
            session.rollback()
            # Silently handle - we already checked but potentially a race condition or UniqueConstraint catch.
            # No need to log as warning if it was filtered out.
            existing = session.query(Lead).filter_by(email=lead_data.get('email'), event_name=lead_data.get('event_name')).first()
            return existing, False
        except Exception as e:
            session.rollback()
            logger.error(f"Error adding lead: {str(e)}")
            return None, False
        finally:
            session.close()

    def get_leads_by_status(self, status: str, limit: int = None):
        """
        Fetches leads with a specific status. Useful for Mailchimp sync.
        """
        session = self.SessionLocal()
        try:
            query = session.query(Lead).filter_by(status=status)
            if limit:
                query = query.limit(limit)
            return query.all()
        finally:
            session.close()

    def update_lead_status(self, lead_id: int, status: str, campaign_sent: bool = None, response_detected: bool = None):
        """
        Updates the status or flags of a lead.
        """
        session = self.SessionLocal()
        try:
            lead = session.query(Lead).filter_by(id=lead_id).first()
            if lead:
                lead.status = status
                if campaign_sent is not None:
                    lead.campaign_sent = campaign_sent
                if response_detected is not None:
                    lead.response_detected = response_detected
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating lead {lead_id}: {str(e)}")
            return False
        finally:
            session.close()

    def get_recent_leads(self, limit: int = None, persona_type: str = "All", target_product: str = "All"):
        """
        Fetches the most recently added leads, with optional filters for persona_type and target_product.
        """
        session = self.SessionLocal()
        try:
            query = session.query(Lead)
            if persona_type and persona_type != "All":
                if persona_type == "sin_clasificar":
                    query = query.filter((Lead.persona_type == None) | (Lead.persona_type == ""))
                else:
                    query = query.filter(Lead.persona_type == persona_type)
            
            if target_product and target_product != "All":
                if target_product == "sin_clasificar":
                    query = query.filter((Lead.target_product == None) | (Lead.target_product == ""))
                else:
                    query = query.filter(Lead.target_product == target_product)
            
            return query.order_by(Lead.created_at.desc()).limit(limit).all()
        finally:
            session.close()
            
    def get_stats(self):
        """
        Get counts of sent vs responded for the UI.
        """
        session = self.SessionLocal()
        try:
            sent_count = session.query(Lead).filter_by(campaign_sent=True).count()
            responded_count = session.query(Lead).filter_by(response_detected=True).count()
            total_leads = session.query(Lead).count()
            return {
                "total_leads": total_leads,
                "sent_count": sent_count,
                "responded_count": responded_count
            }
        finally:
            session.close()

    def clear_database(self):
        """
        Deletes all leads from the database.
        """
        session = self.SessionLocal()
        try:
            session.query(Lead).delete()
            session.commit()
            logger.info("Database cleared successfully.")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Error clearing database: {str(e)}")
            return False
        finally:
            session.close()

    def import_old_clients_csv(self, csv_content: str) -> dict:
        """
        Imports old clients from a CSV string (file upload or manual paste).
        Columns: Nombre, Empresa, Email, Telefono, Sitio Web, Ciudad, Pais,
                 Ultimo Contacto, Producto Usado, Notas
        Returns a dict with counts: inserted, skipped, errors.
        """
        counts = {"inserted": 0, "skipped": 0, "errors": 0, "details": []}
        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            for row in reader:
                try:
                    email = (row.get("Email") or row.get("email") or "").strip() or None
                    phone = (row.get("Telefono") or row.get("Phone") or row.get("phone") or "").strip() or None
                    name  = (row.get("Nombre") or row.get("Name") or row.get("name") or "").strip() or None
                    company = (row.get("Empresa") or row.get("Company") or row.get("company") or "").strip() or None
                    website = (row.get("Sitio Web") or row.get("Website") or row.get("website") or "").strip() or None
                    city    = (row.get("Ciudad") or row.get("City") or row.get("city") or "").strip()
                    country = (row.get("Pais") or row.get("Country") or row.get("country") or "").strip()
                    product = (row.get("Producto Usado") or row.get("Product Used") or row.get("product_used") or "").strip() or None
                    notes   = (row.get("Notas") or row.get("Notes") or row.get("notes") or "").strip() or None
                    last_contact_str = (row.get("Ultimo Contacto") or row.get("Last Contact") or row.get("last_contact") or "").strip()

                    if not email and not phone:
                        counts["errors"] += 1
                        counts["details"].append(f"Fila sin email ni teléfono: {row}")
                        continue

                    # Build a synthetic event_name to satisfy the unique constraint
                    event_name = f"[OLD CLIENT] {company or name or 'Unknown'}"

                    lead_data = {
                        "name": f"{name} ({company})" if company else name,
                        "email": email,
                        "phone": phone,
                        "website": website,
                        "event_name": event_name,
                        "event_url": website,
                        "persona_type": "old_client",
                        "target_product": product,
                        "source_type": "csv_import",
                        "notes": f"Ciudad: {city}, País: {country}. {notes or ''}".strip(". "),
                        "status": "new",
                    }

                    _, is_new = self.add_lead(lead_data)
                    if is_new:
                        counts["inserted"] += 1
                        counts["details"].append(f"✅ Importado: {name or email}")
                    else:
                        counts["skipped"] += 1
                        counts["details"].append(f"⏭️ Ya existe: {name or email}")
                except Exception as row_err:
                    counts["errors"] += 1
                    counts["details"].append(f"❌ Error en fila: {row_err}")
                    logger.error(f"Error importing row {row}: {row_err}")
        except Exception as e:
            logger.error(f"CSV parsing error: {e}")
            counts["errors"] += 1
            counts["details"].append(f"❌ Error parseando CSV: {e}")
        return counts

    def add_manual_contact(self, name: str, company: str, email: str, phone: str,
                           website: str, city: str, country: str,
                           product: str, notes: str) -> tuple:
        """
        Adds a single contact manually (from form input). Returns (Lead, is_new).
        """
        if not email and not phone:
            raise ValueError("Se requiere al menos email o teléfono.")

        event_name = f"[OLD CLIENT] {company or name or 'Unknown'}"
        lead_data = {
            "name": f"{name} ({company})" if company else name,
            "email": email or None,
            "phone": phone or None,
            "website": website or None,
            "event_name": event_name,
            "event_url": website or None,
            "persona_type": "old_client",
            "target_product": product or None,
            "source_type": "manual",
            "notes": f"Ciudad: {city}, País: {country}. {notes or ''}".strip(". "),
            "status": "new",
        }
        return self.add_lead(lead_data)

    def get_leads_by_persona(self, persona_type: str, limit: int = None):
        """Returns all leads for a given persona_type."""
        session = self.SessionLocal()
        try:
            q = session.query(Lead).filter_by(persona_type=persona_type).order_by(Lead.created_at.desc())
            if limit:
                q = q.limit(limit)
            return q.all()
        finally:
            session.close()

    def count_by_source(self, source_type: str) -> int:
        """Returns count of leads with a specific source_type."""
        session = self.SessionLocal()
        try:
            return session.query(Lead).filter_by(source_type=source_type).count()
        finally:
            session.close()

    def get_stats_by_persona(self):
        """Returns lead counts grouped by persona_type."""
        session = self.SessionLocal()
        try:
            from sqlalchemy import func
            rows = session.query(Lead.persona_type, func.count(Lead.id)).group_by(Lead.persona_type).all()
            return {r[0] or "sin_clasificar": r[1] for r in rows}
        finally:
            session.close()

    def import_persona_csv(self, csv_content: str, persona_key: str, persona_name: str = None) -> dict:
        """
        Imports leads from CSV for a specific persona_key.
        CSV columns: name, email, phone, event_name, event_url, notes (flexible headers).
        Returns dict with inserted, skipped, errors, details.
        """
        counts = {"inserted": 0, "skipped": 0, "errors": 0, "details": []}
        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            fieldnames_lower = [h.lower().strip() for h in reader.fieldnames or []]

            for row in reader:
                try:
                    email = (row.get("Email") or row.get("email") or "").strip().lower() or None
                    phone = (row.get("Phone") or row.get("phone") or row.get("Telefono") or row.get("telefono") or "").strip() or None
                    name  = (row.get("Name") or row.get("name") or row.get("Nombre") or row.get("nombre") or "").strip() or None
                    company = (row.get("Company") or row.get("company") or row.get("Empresa") or row.get("empresa") or "").strip() or None
                    website = (row.get("Website") or row.get("website") or row.get("Sitio Web") or row.get("Url") or row.get("url") or row.get("event_url") or "").strip() or None
                    event_url = website
                    event_name = (row.get("event_name") or row.get("Event") or row.get("event") or row.get("Event Name") or "").strip() or None
                    notes = (row.get("Notes") or row.get("notes") or row.get("Notas") or row.get("notas") or "").strip() or None

                    s_date = row.get("event_start_date") or row.get("Start Date") or ""
                    e_date = row.get("event_end_date") or row.get("End Date") or ""

                    if not email and not phone:
                        counts["errors"] += 1
                        counts["details"].append(f"Sin email ni telefono: {dict(row)}")
                        continue

                    lead_data = {
                        "name": name,
                        "email": email,
                        "phone": phone,
                        "website": website,
                        "event_url": event_url,
                        "event_name": event_name or f"[{persona_name or persona_key}] {company or name or 'Unknown'}",
                        "event_start_date": self._parse_date(s_date) if s_date else None,
                        "event_end_date": self._parse_date(e_date) if e_date else None,
                        "persona_type": persona_key,
                        "target_product": persona_name,
                        "source_type": "csv_import",
                        "notes": notes,
                        "status": "new",
                    }

                    _, is_new = self.add_lead(lead_data)
                    if is_new:
                        counts["inserted"] += 1
                        counts["details"].append(f"Insertado: {name or email}")
                    else:
                        counts["skipped"] += 1
                        counts["details"].append(f"Ya existe: {name or email}")
                except Exception as row_err:
                    counts["errors"] += 1
                    counts["details"].append(f"Error fila: {row_err}")
                    logger.error(f"Error importing persona CSV row {row}: {row_err}")
        except Exception as e:
            logger.error(f"CSV parsing error: {e}")
            counts["errors"] += 1
            counts["details"].append(f"Error parsing CSV: {e}")
        return counts

    def _parse_date(self, val: str):
        """Try to parse a date string, return None on failure."""
        from dateutil import parser as date_parser
        try:
            return date_parser.parse(val)
        except Exception:
            return None


# Global repository instance
repository = LeadRepository()
