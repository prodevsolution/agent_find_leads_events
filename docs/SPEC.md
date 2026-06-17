# Project Specification: Event Prospecting Multi-Agent System

## Overview
Automated multi-agent system for discovering and building potential lead databases for events across various niches. Uses LangGraph-powered multi-agent architecture with OpenAI (gpt-4o-mini) or local LLM (Ollama Phi-4 Mini) to find events, scrape organizing entities' data, and send notifications.

## Core Features

### 1. Event & Niche Prospecting (Tab 1)
- Search for events by niche/category (circus, theater, fairs, etc.)
- Configurable date ranges (start date required, end date optional)
- Custom search criteria (e.g., "+ venues in Florida")
- Excluded domains list to filter out ticket aggregators
- Dynamic niche management (add/remove from defaults or custom)

### 2. ProDev Personas Prospecting (Tab 2)
- Four pre-defined buyer personas with tailored queries:
  - **Evinra Events**: Event venue operators in Florida (ticketing/POS)
  - **TravelorHub Transport**: Charter bus/tour operators in Florida & Caribbean
  - **Custom Dev SMB**: Small business owners in Florida needing automation
  - **Custom Dev Founders**: Non-technical SaaS founders seeking dev partners
- Each persona has: queries list, criteria, target product, geo focus, priority
- Editable queries via UI
- Persona-specific search execution

### 3. Old Clients Manager (Tab 3)
- Manual contact entry form
- CSV import with template (Nombre, Empresa, Email, Teléfono, Sitio Web, Ciudad, País, Último Contacto, Producto Usado, Notas)
- Stored with persona_type="old_client"

### 4. Dashboard & Monitoring
- Real-time status (Idle/Running)
- Lead statistics (total, sent, responded, by persona)
- Paginated leads table with filters (persona, product)
- Activity logs with level filtering
- Auto-refresh while agents running

### 5. Background Scheduler
- APScheduler runs workflow every 6 hours
- Manual trigger via UI

### 6. Notifications & Integrations
- **Mailchimp**: Sync new leads with email to audience list
- **Twilio WhatsApp**: Operational notifications
- **SMTP Email**: Alert notifications
- **Database**: SQLite (default) or PostgreSQL via DATABASE_URL

## Multi-Agent Workflow (LangGraph)

### Nodes (Parallel Paths from Brainstormer)
1. **Brainstormer**: Uses LLM internal knowledge to suggest entities per niche (skipped for personas)
2. **Summarizer** (Fast/RAG): Tavily search → LLM extracts leads from snippets
3. **Searcher → Scraper** (Deep): Tavily search → scrape URLs → LLM extracts leads
4. **Agentic Researcher** (Deep Synthesis): Collects ALL content → holistic synthesis pass
5. **Deduplicator**: Merge leads from 3 paths, save to DB, sync to Mailchimp
6. **Notifier**: Send notifications for new marketed leads

### State Management
- TypedDict GraphState with operator.add for accumulators
- Tracks: search_queries, criteria, dates, leads from each path, URLs, notifications

## Technology Stack
- **Python**: 3.13+
- **Dependencies**: uv package manager
- **LangChain/LangGraph**: Agent orchestration
- **LLM Providers**: OpenAI (gpt-4o-mini, gpt-4o), Ollama (phi4-mini), Google Gemini
- **Search**: Tavily API (advanced depth, raw content)
- **Scraping**: Requests + BeautifulSoup (static), Playwright (dynamic/JS sites)
- **Database**: SQLAlchemy + SQLite/PostgreSQL
- **UI**: Gradio (dashboard, forms, tables)
- **Scheduler**: APScheduler (background)
- **Config**: python-dotenv (.env file)

## Data Flow
1. User configures search (niche/persona, dates, criteria) via Gradio UI
2. Workflow triggered (manual or scheduled)
3. Brainstormer generates entities (generic niches only)
4. Three parallel extraction paths execute
5. Deduplicator merges, validates, saves to DB
6. New leads with emails → Mailchimp sync (if enabled)
7. Notifications sent
8. Dashboard updates with new leads

## Constraints & Requirements
- Python 3.13+
- uv for dependency management
- API keys required: OPENAI_API_KEY, TAVILY_API_KEY (minimum)
- Optional: Mailchimp, Twilio, SMTP credentials
- Ollama requires local installation (scripts provided)
- Playwright requires browser binaries (installed via playwright install)