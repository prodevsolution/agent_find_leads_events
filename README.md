# Event Prospecting Multi-Agent System

Automatically search, discover, and build a potential lead database for specific events across various niches. This project uses a LangGraph-powered multi-agent system combined with OpenAI (gpt-4o-mini) or local LLM (Ollama with Phi-4 Mini) to find events, scrape organizing entities' data, and send updates and notifications.


It includes an automated scheduler (APScheduler) for recurrent executions and a Gradio web interface for tracking campaign performance and status.

## Prerequisites

- Python ^3.13
- Ensure you have [`uv`](https://docs.astral.sh/uv/) installed (a versatile Python dependency manager).

## Getting Started

1. **Clone the repository** (or navigate to your working directory).

2. **Setup Dependencies**  
   Use `uv` to install dependencies and prepare your environment. Running `uv sync` sets up the virtual environment automatically securely fetching dependencies declared in `pyproject.toml`.
   ```bash
   uv sync
   ```

3. **Configure the Environment**  
   Copy the `.env.example` file to create your own configuration file `.env`.
   ```bash
   cp .env.example .env
   ```

## Configuration Data

The system needs various keys and parameters to function properly. Configure the following variables in your `.env` file:

### API Keys
- `OPENAI_API_KEY`: The API key for OpenAI's models (mandatory if `LLM_PROVIDER=openai`).
- `TAVILY_API_KEY`: API key for Tavily search (used by agents to run web searches).

### LLM Options (OpenAI vs. Ollama)
You can choose between using OpenAI's cloud API or a local LLM via Ollama.
- `LLM_PROVIDER`: Set to `openai` (default) or `ollama`.
- `OLLAMA_BASE_URL`: The URL where Ollama is running (default: `http://localhost:11434`).
- `OLLAMA_MODEL`: The model name to use (recommended: `phi4-mini`).


### Mailchimp (For marketing outreach)
- `MAILCHIMP_API_KEY`: Your Mailchimp marketing API key.
- `MAILCHIMP_SERVER_PREFIX`: Mailchimp data center (e.g., `us1`).
- `MAILCHIMP_LIST_ID`: Unique Audience List ID where new contacts should be added.

### Twilio (For WhatsApp/SMS notifications)
- `TWILIO_ACCOUNT_SID`: The Account SID from Twilio console.
- `TWILIO_AUTH_TOKEN`: Twilio Auth Token.
- `TWILIO_PHONE_NUMBER`: Provided Twilio phone number (e.g., sandbox `whatsapp:+14155238886`).
- `TO_PHONE_NUMBER`: Target phone number to receive operational notifications directly.

### Email Notifications (SMTP for alerts)
- `SMTP_SERVER`: Outbound email server (e.g., `smtp.gmail.com`).
- `SMTP_PORT`: Port assigned by the server (usually `587`).
- `SMTP_USER`: Email account username.
- `SMTP_PASS`: App password or account password for sending emails.
- `TO_EMAIL`: Destination email address for the notifications.

### Database
- `DATABASE_URL`: Connection string for SQLAlchemy (defaults to `sqlite:///leads.db`).

## Using Local LLM (Ollama)

This project supports using [Ollama](https://ollama.com/) with the **Phi-4 Mini** Small Language Model (SLM) as an alternative to OpenAI.

### Installation

To set up Ollama and pull the required model, we provide automated scripts in the `scripts/` directory:

**For Linux:**
```bash
chmod +x scripts/install_ollama_linux.sh
./scripts/install_ollama_linux.sh
```

**For Windows (PowerShell):**
```powershell
.\scripts\install_ollama_windows.ps1
```

Once installed, ensure your `.env` file reflects the change:
```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=phi4-mini
```


## Running the Application

To start the monitoring dashboard and background scheduler, simply run `app.py`:

```bash
uv run app.py
```

The system will:
1. Initialize the SQLite database if it doesn't already exist.
2. Start the internal background task (APScheduler) that executes the Multi-Agent Pipeline every 6 hours.
3. Start the Gradio dashboard locally, accessible by navigating to: **http://0.0.0.0:7860**. From there, you can view recent leads, see runtime status, and manually override query date ranges by triggering agent runs.
