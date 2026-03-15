import os
import logging
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
    email = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    event_name = Column(String(255), nullable=True)
    event_url = Column(Text, nullable=True)
    event_start_date = Column(DateTime, nullable=True)
    event_end_date = Column(DateTime, nullable=True)
    
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
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def add_lead(self, lead_data: dict) -> tuple[Lead, bool]:
        """
        Adds a single lead to the database. Returns a tuple (Lead, is_new).
        is_new is True if the lead was freshly inserted, False if it already existed.
        Ignores duplicates based on the Unique Constraint on 'email'.
        """
        session = self.SessionLocal()
        try:
            # Check if lead already exists to avoid throwing IntegrityError repeatedly
            existing_lead = session.query(Lead).filter_by(email=lead_data.get('email'), event_name=lead_data.get('event_name')).first()
            if existing_lead:
                logger.debug(f"Lead with email {lead_data.get('email')} for event {lead_data.get('event_name')} already exists. Skipping.")
                return existing_lead, False
            
            new_lead = Lead(**lead_data)
            session.add(new_lead)
            session.commit()
            session.refresh(new_lead)
            logger.info(f"Successfully added lead: {new_lead.email}")
            return new_lead, True
        except IntegrityError:
            session.rollback()
            logger.warning(f"Integrity error (duplicate email & event): {lead_data.get('email')} @ {lead_data.get('event_name')}")
            # Try to fetch it again if it was a race condition
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

    def get_recent_leads(self, limit: int = None):
        """
        Fetches the most recently added leads.
        """
        session = self.SessionLocal()
        try:
            return session.query(Lead).order_by(Lead.created_at.desc()).limit(limit).all()
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

# Global repository instance
repository = LeadRepository()
