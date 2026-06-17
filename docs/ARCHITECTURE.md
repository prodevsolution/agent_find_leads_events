# Architecture: Event Prospecting Multi-Agent System

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Gradio UI (app.py)                       │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Event/Niche  │  │  ProDev      │  │   Old Clients        │   │
│  │ Prospecting  │  │  Personas    │  │   Manager (CSV/Manual)│   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                 │                      │               │
│         └────────┬────────┴──────────────────────┘               │
│                  │                                                │
│           ┌──────▼──────┐                                        │
│           │  Dashboard   │                                        │
│           │  (Status,    │                                        │
│           │   Stats,     │                                        │
│           │   Logs,      │                                        │
│           │   Table)     │                                        │
│           └─────────────┘                                        │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             │ run_agent_workflow()
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│              APScheduler (Background, every 6h)                  │
│                 or Manual Trigger (Thread)                        │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                 LangGraph Workflow (graph.py)                     │
│                                                                   │
│  ┌──────────────┐                                                 │
│  │ BRAINSTORMER  │ ◄── Entry Point (skipped for Persona)          │
│  └──────┬───────┘                                                 │
│         │                                                         │
│    ┌────┼────────────┐                                           │
│    │    │            │                                            │
│    ▼    ▼            ▼                                            │
│ ┌─────┐ ┌──────┐ ┌──────────────────┐                            │
│ │SUM- │ │SEARCH│ │ AGENTIC          │                            │
│ │MARI-│ │  │   │ │ RESEARCHER       │                            │
│ │ZER  │ │  ▼   │ │ (Deep Synthesis) │                            │
│ │(RAG)│ │SCRA- │ └──────────────────┘                            │
│ │     │ │PER   │                                                  │
│ └──┬──┘ └──┬───┘                                                  │
│    └───┬───┘                                                      │
│        ▼                                                          │
│  ┌─────────────┐                                                 │
│  │DEDUPLICATOR │──► SQLite DB                                     │
│  └──────┬──────┘──► Mailchimp (if enabled)                        │
│         │                                                          │
│         ▼                                                          │
│  ┌─────────────┐                                                 │
│  │  NOTIFIER   │──► Twilio / SMTP                                 │
│  └─────────────┘                                                 │
└──────────────────────────────────────────────────────────────────┘
```

## File Layout

```
agent_find_leads_events/
├── app.py                     # Gradio UI + Scheduler + Entry point
├── config.py                  # Environment configuration loader
├── graph.py                   # LangGraph workflow: nodes, state, graph
├── tools.py                   # LangChain tools: search, scrape, Mailchimp, Twilio, SMTP
├── database.py                # SQLAlchemy models + repository pattern
├── prodev_manager.py          # Persona JSON loader/manager + CSV helpers
├── prodev_personas.json       # Persona definitions (queries, criteria, products)
├── main.py                    # Minimal entry (placeholder)
├── debug.py                   # Debug utilities
├── verify_leaddata.py         # Pydantic model validation test
├── verify_mailchimp_payload.py# Mailchimp payload structure test
├── test_leads.db              # Test SQLite database
├── error.log / output.log / startup.log / agent.log  # Log files
├── trace.txt / startup_utf8.log                       # Trace logs
├── agent.log                  # Runtime agent log (created at startup)
├── active_niches.json         # Persisted user niche list (created at runtime)
├── leads.db                   # Production SQLite database (created at runtime)
├── docs/
│   ├── old_clients_template.csv
│   └── ProDev-Buyer-Personas-y-Prospeccion.docx
├── scripts/
│   ├── install_ollama_linux.sh
│   ├── install_ollama_windows.ps1
│   ├── test_mcp_integration.py
│   ├── test_validation_fix.py
│   └── trigger_workflow.py
├── .env.example               # Env variable template
├── pyproject.toml             # Dependencies + project metadata
├── README.md                  # Project setup & usage guide
├── uv.lock                    # Locked dependencies
└── .gitignore
```

## Component Responsibilities

### app.py (UI + Orchestrator)
- Gradio Blocks UI with 3 tabs + dashboard
- `run_agent_workflow()`: Builds initial GraphState, invokes LangGraph
- `start_scheduler()`: Starts APScheduler (6-hour interval)
- `manual_trigger()`: Validates dates, runs workflow in thread
- `refresh_dashboard()`: Reads DB, formats for Gradio components
- State: AGENT_STATUS, LAST_RUN, NEXT_RUN (thread-safe via Lock)
- Auto-refresh via gr.Timer while AGENT_STATUS == "Running"

### config.py (Configuration)
- Loads .env via python-dotenv
- API keys: GEMINI_API_KEY, OPENAI_API_KEY, TAVILY_API_KEY
- LLM selection: LLM_PROVIDER (openai/ollama), OLLAMA_* params
- Mailchimp, Twilio, SMTP credentials
- Database URL (default: sqlite:///leads.db)
- Excluded domains list (default: major ticketing/aggregator sites)
- Scraper content limit, summarizer result limit, extractor model

### graph.py (Multi-Agent Workflow)
- **GraphState**: TypedDict with all workflow state + operator.add accumulators
- **LLM Factory**: `get_llm()` returns ChatOpenAI/ChatOllama/ChatGoogleGenerativeAI
- **Structured LLM**: `get_structured_llm()` caches .with_structured_output(ExtractedLeads)
- **Nodes**:
  - `brainstormer_node()`: LLM suggests entities per niche
  - `summarizer_node()`: Tavily search → LLM extracts leads (RAG-style)
  - `searcher_node()`: Tavily search for URLs
  - `scraper_node()`: Scrape URLs → LLM extracts leads
  - `agentic_researcher_node()`: Holistic deep research from all sources
  - `deduplicator_node()`: Merge, dedup, save to DB, Mailchimp sync
  - `notifier_node()`: Send notifications
- **Edges**: Brainstormer → 3 parallel paths → Deduplicator → Notifier → END

### tools.py (Tools & Integrations)
- `search_events()`: @tool, Tavily API POST request (advanced depth, raw content, excluded domains)
- `scrape_event_page()`: @tool, Requests + BeautifulSoup (static pages, fallback to dynamic)
- `scrape_dynamic_mcp()`: @tool, Playwright (JS-rendered pages, LinkedIn/social)
- `add_lead_to_mailchimp()`: mailchimp3 PUT create_or_update
- `send_whatsapp_notification()`: Twilio REST API
- `send_email_notification()`: SMTP with starttls
- Helper functions: extract_emails(), extract_phones()

### database.py (Data Layer)
- **Lead model** (SQLAlchemy):
  - id, name, email, phone, event_name, event_url
  - event_start_date, event_end_date, website
  - persona_type, target_product, source_type, notes
  - status (new/marketed/responded/invalid), campaign_sent, response_detected
  - created_at, updated_at
  - UniqueConstraint: (email, event_name)
- **LeadRepository**: add_lead, get_leads_by_status, update_lead_status
  - get_recent_leads (with persona/product filters), get_stats, clear_database
  - import_old_clients_csv() - CSV parsing with column name flexibility
  - add_manual_contact(), get_leads_by_persona(), get_stats_by_persona()
  - Auto-migration: adds missing columns via ALTER TABLE

### prodev_manager.py (Persona Management)
- Load/save prodev_personas.json
- Functions: get_persona_names, get_persona_queries, get_persona_criteria, get_persona_product
- CSV template generation for old clients import
- UI helpers: queries_list_to_text, queries_text_to_list, build_gradio_persona_choices

## Data Flow Detail

### Input → Output
1. **User action**: Configure niches/persona, dates, criteria, click "Run"
2. **Validation** (app.py:277-323): Check dates not in past, end > start
3. **State construction** (app.py:147-167): Build GraphState with all params
4. **Graph execution** (graph.py:473-505): LangGraph compiles & invokes
5. **Lead extraction**: 3 parallel paths produce leads
6. **Deduplication**: Merge, phone-based dedup for email-less leads, save
7. **Sync**: New leads with email → Mailchimp (if enabled)
8. **Notification**: Count of marketed leads → Twilio/SMTP (if configured)
9. **Result**: Leads persisted, dashboard refreshes

### Database Schema (leads table)
| Column             | Type        | Notes                              |
|--------------------|-------------|-------------------------------------|
| id                 | Integer PK  | Auto-increment                      |
| name               | String(255) | Contact name                        |
| email              | String(255) | Nullable (phone-only leads allowed) |
| phone              | String(50)  | Nullable                            |
| event_name         | String(255) | Nullable                            |
| event_url          | Text        | Source URL                          |
| event_start_date   | DateTime    | Parsed from extraction              |
| event_end_date     | DateTime    | Parsed from extraction              |
| website            | Text        | CSV import / manual entry           |
| persona_type       | String(100) | e.g. evinra_events, old_client      |
| target_product     | String(100) | e.g. Evinra, TravelorHub            |
| source_type        | String(50)  | web_search, csv_import, manual      |
| notes              | Text        | Free text                           |
| status             | String(50)  | new, marketed, responded, invalid   |
| campaign_sent      | Boolean     | Mailchimp sync flag                 |
| response_detected  | Boolean     | Response tracking                   |
| created_at         | DateTime    | auto UTC                            |
| updated_at         | DateTime    | auto UTC on update                  |

## Integration Points

### Tavily Search
- Endpoint: POST https://api.tavily.com/search
- Payload: api_key, query, search_depth="advanced", include_raw_content=true, exclude_domains
- Returns: results[] with url, title, content, raw_content
- Time-aware query enhancement: appends date range context

### Mailchimp
- Library: mailchimp3 (PUT /lists/{id}/members/{hash})
- Data: email_address, status="subscribed", merge_fields (FNAME, LNAME, ADDRESS)
- Subscriber hash: MD5 of lowercase email

### Twilio WhatsApp
- Library: twilio.rest.Client
- Creates message from Twilio sandbox number to target phone
- Used for operational alerts

### SMTP Email
- Python smtplib with starttls
- Used for operational alerts

## LLM Provider Strategy

| Provider   | Model                  | Use Case                        |
|------------|------------------------|----------------------------------|
| OpenAI     | gpt-4o-mini            | Default fast/cheap (brainstorming)|
| OpenAI     | gpt-4o (EXTRACTOR_MODEL)| Extraction nodes (high quality)  |
| Ollama     | phi4-mini              | Local alternative                |
| Google     | gemini-2.0-flash       | Fallback if no API key configured|

- `get_llm()` selects based on config.LLM_PROVIDER + model_override
- `get_structured_llm()` uses EXTRACTOR_MODEL (default gpt-4o) for extraction
- `get_brainstorm_llm()` uses gpt-4o-mini for fast entity brainstorming