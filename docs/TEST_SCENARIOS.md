# Test Scenarios Reference

## Unit & Integration Tests

### 1. Pydantic Validation (verify_leaddata.py)

**Test cases for LeadData model:**
- `TC-01`: Lead with email only → accepted
- `TC-02`: Lead with phone only → accepted
- `TC-03`: Lead with neither email nor phone → rejected
- `TC-04`: Lead with both email and phone → accepted

### 2. Mailchimp Payload (verify_mailchimp_payload.py)

**Test cases for add_lead_to_mailchimp structure:**
- `TC-05`: Valid payload has ADDRESS field with event_url in addr1
- `TC-06`: ADDRESS city/state/zip/country are empty strings
- `TC-07`: FNAME and LNAME merge fields populated correctly
- `TC-08`: create_or_update called with correct subscriber hash

### 3. Dynamic Scraper Selection (scripts/test_mcp_integration.py)

**Test cases for scraper routing:**
- `TC-09`: LinkedIn URL → detected as dynamic (Playwright)
- `TC-10`: Instagram URL → detected as dynamic (Playwright)
- `TC-11`: Google URL → NOT detected as dynamic (Requests)
- `TC-12`: scrape_dynamic_mcp returns correct structure (title, content, emails)

## Workflow Scenarios

### TC-100: Generic Niche Prospecting (Run All)
1. **Setup**: No persona selected, default niches, start_date = today+2d
2. **Execute**: manual_trigger with valid dates
3. **Verify**: 
   - AGENT_STATUS → "Running" then "Idle"
   - Brainstormer runs (entities generated per niche)
   - Summarizer path: Tavily results → leads extracted
   - Searcher path: URLs collected → scraped → leads extracted
   - Agentic researcher: holistic synthesis runs
   - Deduplicator: merges all 3 paths, saves to DB
   - Dashboard updates with new leads count

### TC-101: Persona Prospecting (Evinra Events)
1. **Setup**: Select "evinra_events" persona
2. **Execute**: prodev_trigger_wrapper
3. **Verify**:
   - Brainstormer SKIPPED (persona detected)
   - Summarizer uses persona-tailored prompt
   - Queries come from prodev_personas.json "evinra_events" section
   - Saved leads have persona_type = "evinra_events"
   - target_product = "Evinra"

### TC-102: Persona Prospecting (TravelorHub Transport)
1. **Setup**: Select "travelorhub_transport" persona
2. **Execute**: prodev_trigger_wrapper
3. **Verify**:
   - Queries target charter bus, airport shuttle, Caribbean tour operators
   - Criteria targets transportation/fleet management
   - target_product = "TravelorHub"

### TC-103: Persona Prospecting (Custom Dev SMB)
1. **Setup**: Select "custom_dev_smb" persona
2. **Execute**: prodev_trigger_wrapper
3. **Verify**:
   - Queries target Florida small business owners
   - Criteria targets manual operations needing automation
   - target_product = "Custom Development"

### TC-104: Persona Prospecting (Custom Dev Founders)
1. **Setup**: Select "custom_dev_founders" persona
2. **Execute**: prodev_trigger_wrapper
3. **Verify**:
   - Queries target non-technical founders
   - Criteria targets validated ideas needing dev partner
   - target_product = "Custom Development / MVP Build"

### TC-105: Old Clients CSV Import
1. **Setup**: Prepare CSV with proper headers
2. **Execute**: on_import_csv with file upload or text paste
3. **Verify**:
   - Rows with email or phone → inserted (inserted count > 0)
   - Rows without email AND phone → errors count incremented
   - Duplicate emails → skipped count incremented
   - persona_type = "old_client" for imported leads
   - source_type = "csv_import"

### TC-106: Manual Contact Entry
1. **Setup**: Fill all form fields (name, company, email, phone, website, city, country, product, notes)
2. **Execute**: on_add_manual_contact
3. **Verify**:
   - Lead created with persona_type = "old_client"
   - source_type = "manual"
   - Notes field contains "Ciudad: X, País: Y" format
   - Duplicate → "already exists" message

### TC-107: Date Validation
1. **Setup**: Past start_date, end_date <= start_date
2. **Execute**: manual_trigger
3. **Verify**:
   - Past start_date → "[ERROR] Start date ... cannot be in the past"
   - Invalid end_date → "[ERROR] End date ... must be strictly after Start date"
   - Empty dates → defaults applied

### TC-108: Concurrency Protection
1. **Setup**: Trigger workflow
2. **Execute**: Trigger again while AGENT_STATUS == "Running"
3. **Verify**: Second trigger returns "Agents are already running" without starting new thread

### TC-109: Niche Management
1. **Setup**: Default niches loaded
2. **Execute**: Add niche → Remove niche → Add from defaults
3. **Verify**:
   - New niche appears in dropdown
   - Duplicate niche → rejected with "already exists"
   - Removed niche no longer in list
   - active_niches.json persisted correctly

### TC-110: Database Clear
1. **Setup**: At least one lead in DB
2. **Execute**: clear_db_action
3. **Verify**:
   - All leads deleted
   - Stats show 0 total leads
   - Cannot clear while agents running

### TC-111: Mailchimp Sync (Integration)
1. **Setup**: ENABLE_MAILCHIMP_SYNC=true + valid Mailchimp credentials
2. **Execute**: Run workflow that finds new leads with emails
3. **Verify**:
   - New leads sent to Mailchimp via create_or_update
   - lead.campaign_sent → True
   - lead.status → "marketed"
   - marketed_leads list populated with email addresses

### TC-112: Mailchimp Sync Disabled
1. **Setup**: ENABLE_MAILCHIMP_SYNC=false (or unchecked checkbox)
2. **Execute**: Run workflow with sync_mailchimp=false
3. **Verify**: No Mailchimp API calls, marketed_leads empty

### TC-113: Deduplication Logic
1. **Setup**: Same lead returned by summarizer AND scraper AND agentic researcher
2. **Execute**: Run workflow
3. **Verify**:
   - Lead saved once to DB (is_new=True only first time)
   - Coincidences counter incremented
   - Prefers scraper data over summarizer for duplicate emails

### TC-114: Phone-Only Leads
1. **Setup**: Page with phone numbers but no emails
2. **Execute**: scraper_node
3. **Verify**:
   - Lead accepted (phone only) and saved
   - Dedup uses phone as key (prefix "phone_")

### TC-115: Agentic Researcher Deep Synthesis
1. **Setup**: Niches with multiple search results expected
2. **Execute**: agentic_researcher_node
3. **Verify**:
   - Searches each niche with contact-focused query
   - Takes top 5 results per query
   - Holistic extraction runs on accumulated content
   - Returns leads with is_valid_date=True and contact info

### TC-116: Scheduler Startup & Interval
1. **Setup**: Start app.py
2. **Execute**: start_scheduler()
3. **Verify**:
   - Job registered with id='event_prospecting_job'
   - Interval = 6 hours
   - NEXT_RUN updated with scheduled time
   - Job persists after dashboard refresh

## Edge Cases

### EC-001: Empty Search Results
- No Tavily results for a niche → node logs error, returns empty accumulator

### EC-002: URL Scrape Failure
- URL returns 403/Timeout → fallback to Playwright → if also fails → empty result

### EC-003: All Leads Past Dates
- LLM returns leads all with is_valid_date=False → deduplicator sees empty valid list

### EC-004: No API Keys Configured
- LLM provider with no key → fallback to Gemini or error logged
- Tavily with no key → search_events returns []

### EC-005: CSV Import Edge Cases
- BOM in CSV file → handled by utf-8-sig
- Empty file → counts["errors"] incremented
- Mixed delimiter (comma vs semicolon) → handled by csv.DictReader
- Missing optional columns → None defaults

### EC-006: Persona JSON File Missing
- prodev_personas.json not found → load_personas returns empty dict
- UI dropdown will have no persona choices

### EC-007: Database Migration
- Old schema missing columns (website, persona_type, etc.) → _run_migrations adds them via ALTER TABLE

## Current Test Files

| File | Type | Coverage |
|------|------|----------|
| `verify_leaddata.py` | Standalone unit test | LeadData Pydantic validation |
| `verify_mailchimp_payload.py` | Mock-based unit test | Mailchimp payload structure |
| `scripts/test_mcp_integration.py` | Integration test | Dynamic scraper detection + tool invoke |
| `scripts/test_validation_fix.py` | Integration test | Validation fix verification |
| `scripts/trigger_workflow.py` | Manual integration test | End-to-end graph execution |