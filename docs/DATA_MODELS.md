# Data Models Reference

## 1. Pydantic Models (graph.py)

### LeadData
```python
class LeadData(BaseModel):
    name: str | None = None           # Contact person or organization
    email: str | None = None          # Email address
    phone: str | None = None          # Phone number
    event_name: str | None = None     # Event name
    event_url: str | None = None      # Page URL where found
    event_start_date: str | None = None  # ISO 8601 start date
    event_end_date: str | None = None    # ISO 8601 end date
    is_valid_date: bool = True        # False if event is securely in the past
```
- No strict validator - allows LLM to return partial leads without crashing
- Filtering handled at node level (email/phone required after extraction)

### SearchResultUrls
```python
class SearchResultUrls(BaseModel):
    urls: List[str]  # URLs found for potential events
```

### ExtractedLeads
```python
class ExtractedLeads(BaseModel):
    leads: List[LeadData]  # Leads extracted from a page
```

### EntityList
```python
class EntityList(BaseModel):
    entities: List[str]  # Company/venue/organization names from LLM knowledge
```

## 2. GraphState (graph.py)

```python
class GraphState(TypedDict):
    # Search configuration
    search_queries: list[str]
    search_criteria: str
    brainstormed_entities: Annotated[list[str], operator.add]
    start_date: str | None           # ISO 8601
    end_date: str | None             # ISO 8601 or "9999-12-31"
    current_date: str                # ISO 8601 today

    # Persona classification
    persona_type: str | None         # e.g. "evinra_events"
    target_product: str | None       # e.g. "Evinra"

    # Lead accumulators (each path produces leads)
    summarizer_leads: Annotated[list[LeadData], operator.add]
    scraper_leads: Annotated[list[LeadData], operator.add]
    agentic_leads: Annotated[list[LeadData], operator.add]
    urls_to_scrape: Annotated[list[str], operator.add]
    scraped_leads: Annotated[list[LeadData], operator.add]
    all_search_content: Annotated[list[str], operator.add]

    # Result accumulators
    saved_leads: Annotated[list[dict], operator.add]
    marketed_leads: Annotated[list[str], operator.add]  # Emails sent to Mailchimp
    notifications_sent: bool
    max_results: int
    sync_mailchimp: bool | None
```

## 3. SQLAlchemy Model (database.py)

### Lead
```python
class Lead(Base):
    __tablename__ = 'leads'
    __table_args__ = (UniqueConstraint('email', 'event_name', name='uix_email_event_name'),)

    id: Integer PK
    name: String(255) nullable        # Contact name
    email: String(255) nullable       # Nullable for phone-only leads
    phone: String(50) nullable        # Nullable for email-only leads
    event_name: String(255) nullable  # Event name
    event_url: Text nullable          # URL where found
    event_start_date: DateTime nullable
    event_end_date: DateTime nullable
    website: Text nullable            # From CSV import or manual entry
    persona_type: String(100) nullable   # e.g. evinra_events, old_client
    target_product: String(100) nullable # e.g. Evinra, TravelorHub
    source_type: String(50) default='web_search'  # web_search, csv_import, manual
    notes: Text nullable
    status: String(50) default='new'  # new, marketed, responded, invalid
    campaign_sent: Boolean default=False
    response_detected: Boolean default=False
    created_at: DateTime default=utcnow
    updated_at: DateTime default=utcnow, onupdate=utcnow
```

### LeadRepository Methods
| Method | Purpose | Input | Output |
|--------|---------|-------|--------|
| `add_lead(lead_data)` | Insert or skip duplicate | dict | tuple(Lead, is_new) |
| `get_leads_by_status(status, limit)` | Filter by status | str | list[Lead] |
| `update_lead_status(lead_id, status, campaign_sent, response_detected)` | Update flags | int + kwargs | bool |
| `get_recent_leads(limit, persona_type, target_product)` | Recent with filters | optional filters | list[Lead] |
| `get_stats()` | Count totals | none | dict |
| `clear_database()` | Delete all | none | bool |
| `import_old_clients_csv(csv_content)` | Bulk CSV import | str (CSV) | dict with counts |
| `add_manual_contact(...)` | Single manual entry | name, company, email, phone, etc. | tuple(Lead, is_new) |
| `get_leads_by_persona(persona_type, limit)` | Persona-filtered | str | list[Lead] |
| `get_stats_by_persona()` | Group counts | none | dict |

## 4. Persona Configuration (prodev_personas.json)

```json
{
  "<persona_key>": {
    "name": "Display Name",
    "product": "Target Product",
    "description": "Description",
    "target_roles": ["Role1", "Role2"],
    "queries": ["search query 1", "search query 2"],
    "criteria": "refinement criteria string",
    "geo_focus": "geographic region",
    "priority": "high|medium|low"
  }
}
```

### Predefined Personas
| Key | Name | Product | Priority |
|-----|------|---------|----------|
| `evinra_events` | Evinra — Operadores de Eventos | Evinra | high |
| `travelorhub_transport` | TravelorHub — Operadores de Transporte | TravelorHub | high |
| `custom_dev_smb` | Custom Dev — SMB Operacional | Custom Development | medium |
| `custom_dev_founders` | Custom Dev — Founders No-Técnicos | Custom Dev / MVP Build | low |
| `old_client` | Persona 5 — Clientes Antiguos | (varies) | N/A (import/manual) |

## 5. File-Based State

### active_niches.json
```json
["Circus productions", "County fairs", "Ice shows", "Magic shows",
 "State fairs", "Touring musical productions", "Touring theater"]
```
- Persisted list of user-managed search niches
- Auto-saved on add/remove operations

### CSV Template for Old Clients
```csv
Nombre,Empresa,Email,Telefono,Sitio Web,Ciudad,Pais,Ultimo Contacto,Producto Usado,Notas
```
- Flexible column matching: supports Spanish and English column names
- At least one of Email or Telefono required per row