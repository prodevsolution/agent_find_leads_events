import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# GEMINI 2.0 API KEY
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# OPENAI API KEY
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# TAVILY API KEY FOR SEARCH
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# SEARCH CONFIGURATION
_DEFAULT_EXCLUDE = "ticketmaster.com,seatgeek.com,vividseats.com,stubhub.com,eventbrite.com,facebook.com,10times.com,carnivalwarehouse.com,castatefair.com,sanjosetheaters.org,feverup.com"
EXCLUDE_DOMAINS_STR = os.getenv("EXCLUDE_DOMAINS", _DEFAULT_EXCLUDE)
EXCLUDE_DOMAINS = [d.strip() for d in EXCLUDE_DOMAINS_STR.split(",") if d.strip()]

# LLM CONFIGURATION
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL") or "phi4-mini"
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))       # seconds per request
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))  # max output tokens
SCRAPER_CONTENT_LIMIT = int(os.getenv("SCRAPER_CONTENT_LIMIT", "2000"))  # chars sent to LLM


# MAILCHIMP CONFIGURATION
ENABLE_MAILCHIMP_SYNC = os.getenv("ENABLE_MAILCHIMP_SYNC", "false").lower() in ("true", "1", "yes")
MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")

# TWILIO CONFIGURATION (WHATSAPP/SMS)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
TO_PHONE_NUMBER = os.getenv("TO_PHONE_NUMBER")

# SMTP CONFIGURATION (EMAIL NOTIFICATIONS)
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = os.getenv("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
TO_EMAIL = os.getenv("TO_EMAIL")

# DATABASE
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///leads.db")
