# Configuration Schema Reference

## Environment Variables (.env)

### Required API Keys
| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | — |
| `TAVILY_API_KEY` | Tavily search API key | — |

### LLM Provider
| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDER` | LLM provider: `openai` or `ollama` | `openai` |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama model name | `phi4-mini` |
| `OLLAMA_TIMEOUT` | Max seconds per Ollama request | `60` |
| `OLLAMA_NUM_PREDICT` | Max output tokens (lower = faster) | `512` |

### Extraction Tuning
| Variable | Description | Default |
|----------|-------------|---------|
| `EXTRACTOR_MODEL` | Model for extraction nodes (summarizer, scraper, deep researcher) | `gpt-4o` |
| `SCRAPER_CONTENT_LIMIT` | Chars of page text sent to LLM per URL | `6000` |
| `SUMMARIZER_RESULT_LIMIT` | Number of search results per summarizer query | `50` |

### Search Configuration
| Variable | Description | Default |
|----------|-------------|---------|
| `EXCLUDE_DOMAINS` | Comma-separated domains to exclude from search results | `ticketmaster.com,seatgeek.com,vividseats.com,stubhub.com,eventbrite.com,facebook.com,10times.com,carnivalwarehouse.com,castatefair.com,sanjosetheaters.org,feverup.com` |

### Mailchimp
| Variable | Description | Default |
|----------|-------------|---------|
| `ENABLE_MAILCHIMP_SYNC` | Enable Mailchimp sync (`true`/`false`) | `false` |
| `MAILCHIMP_API_KEY` | Mailchimp API key | — |
| `MAILCHIMP_SERVER_PREFIX` | Mailchimp data center prefix (e.g., `us1`) | — |
| `MAILCHIMP_LIST_ID` | Mailchimp audience list ID | — |

### Twilio (WhatsApp/SMS)
| Variable | Description | Default |
|----------|-------------|---------|
| `TWILIO_ACCOUNT_SID` | Twilio account SID | — |
| `TWILIO_AUTH_TOKEN` | Twilio auth token | — |
| `TWILIO_PHONE_NUMBER` | Twilio phone number (sandbox: `whatsapp:+14155238886`) | — |
| `TO_PHONE_NUMBER` | Destination phone for notifications | — |

### SMTP (Email Notifications)
| Variable | Description | Default |
|----------|-------------|---------|
| `SMTP_SERVER` | SMTP server (e.g., `smtp.gmail.com`) | — |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USER` | SMTP username/email | — |
| `SMTP_PASS` | SMTP password/app password | — |
| `TO_EMAIL` | Destination email for notifications | — |

### Database
| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | SQLAlchemy database URL | `sqlite:///leads.db` |

### Optional
| Variable | Description | Default |
|----------|-------------|---------|
| `EXTRA_NICHES` | Comma-separated extra niches to add to default list | — |

## Persona Configuration (prodev_personas.json)

### Structure per persona key
| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name for Gradio dropdown |
| `product` | string | Target product (Evinra, TravelorHub, Custom Dev) |
| `description` | string | Persona description |
| `target_roles` | string[] | Array of target job titles |
| `queries` | string[] | Array of search queries (one per line in UI) |
| `criteria` | string | Search criteria refinement string |
| `geo_focus` | string | Geographic focus area |
| `priority` | string | `high`, `medium`, or `low` |

### Predefined Keys
- `evinra_events` — Event venue operators (Evinra product)
- `travelorhub_transport` — Transport/tour operators (TravelorHub product)
- `custom_dev_smb` — SMB operational owners (Custom Development)
- `custom_dev_founders` — Non-technical founders (Custom Dev / MVP Build)
- `old_client` — Imported CSV/manual contacts (special, no queries in JSON)

## Application Defaults

### Default Niches (active_niches.json at startup)
```json
[
  "Circus productions",
  "Touring theater",
  "Magic shows",
  "Ice shows",
  "Touring musical productions",
  "County fairs",
  "State fairs",
  "Agricultural shows"
]
```
- Merged with EXTRA_NICHES from .env
- Persisted to active_niches.json for runtime editing

### Excluded Domains (default)
```
ticketmaster.com, seatgeek.com, vividseats.com, stubhub.com,
eventbrite.com, facebook.com, 10times.com, carnivalwarehouse.com,
castatefair.com, sanjosetheaters.org, feverup.com
```
- Strips ticketing aggregators and social media from search results
- Configurable via EXCLUDE_DOMAINS env var

## Log Files

| File | Purpose | Location |
|------|---------|----------|
| `agent.log` | Main runtime log (INFO+) | Project root |

## Scheduler Defaults
- APScheduler interval: 6 hours
- UI auto-refresh interval: 5 seconds (while agents running)
- Gradio port: 7860 (0.0.0.0)