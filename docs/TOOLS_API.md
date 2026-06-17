# Tools & API Reference

## LangChain Tools (tools.py)

### search_events
```python
@tool
def search_events(
    query: str,
    start_date: str = None,    # ISO 8601
    end_date: str = None,      # ISO 8601
    max_results: int = 30
) -> list[dict]
```
- **Purpose**: Searches for events via Tavily API (advanced depth)
- **URL**: POST https://api.tavily.com/search
- **Key params**: api_key, query, search_depth="advanced", include_raw_content=true
- **Excluded domains**: From config.EXCLUDE_DOMAINS (default: ticketmaster, seatgeek, etc.)
- **Input**: Query string with optional date range
- **Output**: `[{"url": str, "title": str, "content": str}, ...]`
- **Date cleanup**: Strips redundant date patterns from query to avoid confusing search engine
- **Time context**: Appends "starting from {date}" or "until {date}" to enhance search

### scrape_event_page
```python
@tool
def scrape_event_page(url: str) -> dict
```
- **Purpose**: Scrapes a static event URL using Requests + BeautifulSoup
- **Headers**: Comprehensive browser-like headers to avoid 403 blocks
- **Content extraction**: Removes script/style tags, extracts text, emails, phones
- **Fallback**: On 403/Timeout → retries with scrape_dynamic_mcp (Playwright)
- **Output**: `{"url": str, "content": str, "emails": list, "phones": list, "title": str}`
- **Content limit**: First 10,000 characters returned

### scrape_dynamic_mcp
```python
@tool
def scrape_dynamic_mcp(url: str) -> dict
```
- **Purpose**: Scrapes JS-rendered pages using Playwright (headless Chromium)
- **Use case**: LinkedIn, Instagram, Facebook, TikTok, Twitter domains
- **Wait strategy**: `wait_until="networkidle"` + 5s sleep for async content
- **User agent**: Chrome 122 Windows desktop
- **Output**: Same structure as scrape_event_page
- **Content limit**: config.SCRAPER_CONTENT_LIMIT * 2 characters

### add_lead_to_mailchimp
```python
def add_lead_to_mailchimp(
    email: str,
    first_name: str = "",
    last_name: str = "",
    event_url: str = ""
) -> bool
```
- **Library**: mailchimp3 (PUT /lists/{list_id}/members/{subscriber_hash})
- **Status**: `"subscribed"` (bypasses double opt-in and welcome emails)
- **Subscriber hash**: MD5 of lowercase email
- **Merge fields**: FNAME, LNAME, ADDRESS (from event_url)
- **Returns**: True/False

### send_whatsapp_notification
```python
def send_whatsapp_notification(message_body: str) -> bool
```
- **Library**: twilio.rest.Client
- **From**: config.TWILIO_PHONE_NUMBER (sandbox format: whatsapp:+14155238886)
- **To**: config.TO_PHONE_NUMBER
- **Returns**: True/False

### send_email_notification
```python
def send_email_notification(subject: str, message_body: str) -> bool
```
- **Protocol**: SMTP with STARTTLS
- **Config**: SMTP_SERVER, SMTP_PORT (587), SMTP_USER, SMTP_PASS, TO_EMAIL
- **Returns**: True/False

## Utility Functions

### extract_emails(text: str) -> list[str]
- **Regex**: `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`
- **Returns**: Unique email addresses found in text

### extract_phones(text: str) -> list[str]
- **Regex**: `\+?1?\s*\(?-*\.*(\d{3})\)?\.*-*\s*(\d{3})\.*-*\s*(\d{4})`
- **Returns**: Unique phone numbers (concatenated area+prefix+line)

## LangGraph Workflow API (graph.py)

### build_graph() -> CompiledStateGraph
```python
def build_graph() -> StateGraph
```
- **Nodes**: brainstormer, summarizer, searcher, scraper, agentic_researcher, deduplicator, notifier
- **Entry point**: brainstormer
- **Edges**:
  - brainstormer → summarizer (Path 1: Fast RAG extraction)
  - brainstormer → searcher (Path 2: Deep search)
  - brainstormer → agentic_researcher (Path 3: Holistic synthesis)
  - searcher → scraper
  - summarizer → deduplicator
  - scraper → deduplicator
  - agentic_researcher → deduplicator
  - deduplicator → notifier
  - notifier → END

### LLM Factory functions
```python
def get_llm(model_override: str = None) -> BaseChatModel
def get_structured_llm() -> BaseChatModel  # Cached, ExtractedLeads structured output
def get_brainstorm_llm() -> BaseChatModel  # EntityList structured output
```

### Node Descriptions

#### brainstormer_node(state)
- SKIPPED when persona_type is set (personas have predefined queries)
- For generic niches: asks LLM to list 10 representative entities per niche
- Input: search_queries, search_criteria
- Output: brainstormed_entities (append mode)

#### summarizer_node(state)
- RAG-style: Tavily search → full context to LLM → ExtractedLeads
- Different prompt for persona vs generic (persona=professional targeting, generic=event-focused)
- Filters: only leads with email OR phone, sets event_url="Found via Search: {niche}" if missing
- Uses get_structured_llm() (EXTRACTOR_MODEL, default gpt-4o)

#### searcher_node(state)
- Builds targeted queries: 3 per niche + up to 10 per brainstormed entity
- Persona mode: runs precise queries directly
- Collects unique URLs from Tavily results

#### scraper_node(state)
- Iterates URLs: detects dynamic domains (LinkedIn, Instagram, etc.) → Playwright
- Static pages → Requests+BeautifulSoup (falls back to Playwright)
- Sends content to LLM for extraction
- Filters: is_valid_date=True AND (email OR phone)

#### agentic_researcher_node(state)
- Deep synthesis: searches each query again, takes top 5 results with raw content
- Builds full context from ALL sources
- Single holistic extraction pass with strict rules (past events filtered via is_valid_date=False)
- Uses get_structured_llm()

#### deduplicator_node(state)
- Merges summarizer_leads + scraper_leads + agentic_leads
- Dedup by email (prefers scraper data for duplicates)
- Phone-only leads: uses phone as key
- Saves to DB via repository.add_lead()
- Mailchimp sync for new leads with email (if enabled)
- Returns: saved_leads, marketed_leads, scraped_leads

#### notifier_node(state)
- Logs count of marketed leads
- Sends notifications if marketed > 0 (currently placeholder)

## Gradio UI API (app.py)

### Workflow Entry Points

#### run_agent_workflow()
```python
def run_agent_workflow(
    override_start: str = None,    # ISO 8601 date
    override_end: str = None,      # ISO 8601 date
    override_criteria: str = None, # Free text
    max_results: int = 15,
    persona_key: str = None,       # Persona key or None for niches
    sync_mailchimp: bool = None    # Override for Mailchimp sync
) -> None
```
- Runs in a thread (not blocking Gradio)
- Sets AGENT_STATUS="Running" / "Idle"
- Builds GraphState from parameters + defaults
- Invokes app_graph.invoke(initial_state)

#### manual_trigger()
```python
def manual_trigger(
    start_date_ui,        # Gradio DateTime component
    end_date_ui,          # Gradio DateTime or None
    search_criteria_ui,   # str
    max_results_ui,       # int
    sync_mailchimp=False
) -> str
```
- Validates: start_date not in past, end_date >= start_date
- Converts Gradio timestamp values to ISO strings
- Launches workflow in thread
- Returns status message

#### prodev_trigger_wrapper()
```python
def prodev_trigger_wrapper(
    persona_key, override_criteria, max_results,
    log_level, page, persona_filter, product_filter, sync_mailchimp
) -> tuple
```
- Persona-targeted trigger
- No date override (uses defaults)
- Returns UI update for all dashboard components

### Dashboard Refresh
```python
def refresh_dashboard(
    log_level="ALL",
    page=1,
    persona_filter="All",
    product_filter="All"
) -> tuple
```
- Returns: (status_markdown, stats_markdown, leads_table, logs, page_info, page, button_update)

### Persona UI
```python
def on_persona_select(persona_key) -> tuple
def on_save_queries(persona_key, queries_text) -> str
```

### Old Client Management
```python
def on_add_manual_contact(name, company, email, phone, website, city, country, product, notes) -> str
def on_import_csv(csv_text, file_obj) -> str
```

### Niche Management
```python
def add_niche(new_niche) -> tuple    # Returns (message, dropdown_update)
def remove_niche(selected_niche) -> tuple
def add_default_niche(niche) -> tuple
```

### Database Management
```python
def clear_db_action(log_level, page, persona_filter, product_filter) -> tuple
def clear_logs_action(log_level, page, persona_filter, product_filter) -> tuple
def stop_server_action() -> None  # os._exit(0)
```

## prodev_manager.py API

```python
def load_personas() -> dict                           # Load JSON
def save_personas(personas: dict) -> bool             # Save JSON
def get_persona_names() -> dict                       # Return {key: name}
def get_persona_queries(persona_key) -> list[str]     # Return queries array
def get_persona_criteria(persona_key) -> str           # Return criteria string
def get_persona_product(persona_key) -> str            # Return target product
def update_persona_queries(persona_key, new_queries) -> bool
def get_csv_template() -> str                         # CSV header + example
def queries_list_to_text(queries) -> str              # List → newline text
def queries_text_to_list(text) -> list[str]           # Newline text → list
def build_gradio_persona_choices() -> list[tuple]     # [(name, key)]
```