import operator
import logging
from typing import TypedDict, Annotated, List, Any
from datetime import datetime, timezone


from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from tools import search_events, scrape_event_page, add_lead_to_mailchimp, send_whatsapp_notification, send_email_notification
from database import repository
from dateutil import parser as date_parser
import config

logger = logging.getLogger(__name__)


# --- Models ---
class LeadData(BaseModel):
    name: str | None = Field(default=None, description="Name of the contact person or organization.")
    email: str = Field(description="Email address extracted.")
    phone: str | None = Field(default=None, description="Phone number extracted.")
    event_name: str | None = Field(default=None, description="Name of the event.")
    event_url: str | None = Field(default=None, description="URL of the event page.")
    event_start_date: str | None = Field(default=None, description="Start date of the event in ISO 8601 format.")
    event_end_date: str | None = Field(default=None, description="End date of the event in ISO 8601 format.")
    is_valid_date: bool = Field(default=True, description="False if event_start_date is securely known to be in the past relative to current_date.")

class SearchResultUrls(BaseModel):
    urls: List[str] = Field(description="List of URLs found for potential events.")

class ExtractedLeads(BaseModel):
    leads: List[LeadData] = Field(description="List of leads extracted from the page.")

# --- State ---
class GraphState(TypedDict):
    search_queries: list[str]
    start_date: str | None
    end_date: str | None
    current_date: str
    
    # State accumulators using operator.add to append across nodes
    urls_to_scrape: Annotated[list[str], operator.add]
    scraped_leads: Annotated[list[LeadData], operator.add]
    saved_leads: Annotated[list[dict], operator.add]
    marketed_leads: Annotated[list[str], operator.add]
    notifications_sent: bool



from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI

# --- LLM ---
def get_llm():
    provider = config.LLM_PROVIDER
    if provider == "ollama":
        logger.info(f"Using Ollama LLM with model: {config.OLLAMA_MODEL}")
        return ChatOllama(
            model=config.OLLAMA_MODEL,
            base_url=config.OLLAMA_BASE_URL,
            temperature=0,
            num_predict=config.OLLAMA_NUM_PREDICT,  # cap output tokens → faster
            timeout=config.OLLAMA_TIMEOUT,           # avoid hanging forever
        )
    elif provider == "openai":
        logger.info("Using OpenAI LLM (gpt-4o-mini)")
        return ChatOpenAI(model="gpt-4o-mini", temperature=0)
    else:
        logger.info("Using Google Gemini LLM (gemini-2.0-flash)")
        return ChatGoogleGenerativeAI(model="gemini-2.0-flash")

# Cache LLM singleton so it is not re-instantiated on every scheduler run
_llm_instance = None
_llm_structured = None

def get_structured_llm():
    """Returns a cached, structured-output LLM instance."""
    global _llm_instance, _llm_structured
    if _llm_structured is None:
        _llm_instance = get_llm()
        _llm_structured = _llm_instance.with_structured_output(ExtractedLeads)
        logger.info("LLM instance created and cached.")
    return _llm_structured


# --- Nodes ---
def searcher_node(state: GraphState):
    """Uses Tavily to search for the specific queries."""
    logger.info("--- SEARCHER NODE ---")
    urls = []
    
    for query in state.get("search_queries", []):
        try:
            results = search_events.invoke({
                "query": query, 
                "start_date": state.get("start_date"), 
                "end_date": state.get("end_date")
            })
            for res in results:
                if res.get("url") and res.get("url") not in urls:
                    urls.append(res["url"])
        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            
    return {"urls_to_scrape": urls}

def scraper_node(state: GraphState):
    """
    Scrapes URLs and extracts leads using LLM.
    Each valid lead is immediately saved to DB and synced to Mailchimp
    so progress is visible in real-time.
    """
    logger.info("--- SCRAPER NODE ---")
    llm = get_structured_llm()  # use cached instance
    valid_leads = []
    saved_leads_info = []
    marketed_emails = []
    current_date_str = state.get("current_date")
    
    for url in state.get("urls_to_scrape", []):
        try:
            scraped_data = scrape_event_page.invoke({"url": url})
            if not scraped_data.get("content"):
                continue
                
            # If we found at least one email via regex, use LLM to extract context
            if scraped_data.get("emails"):
                content_limit = config.SCRAPER_CONTENT_LIMIT  # shorter = faster for local LLMs
                prompt = (
                    f"Analyze the following event page content and identify contact leads (email, phone, name). "
                    f"Also identify the event name and dates. The current date is {current_date_str}. "
                    f"If the event start date is already past compared to the current date, set is_valid_date to False. "
                    f"If you can't determine the date, assume it's valid (True). "
                    f"The page URL is: {url}\n\nContent:\n{scraped_data['content'][:content_limit]}"
                )
                
                extraction = llm.invoke(prompt)
                
                for lead in extraction.leads:
                    # Time-aware Validation: discard if event is in the past
                    if not (lead.is_valid_date and lead.email):
                        logger.info(f"Discarded lead due to past date: {lead.email} - {lead.event_start_date}")
                        continue
                    
                    # Ensure the URL is attached
                    lead.event_url = url
                    valid_leads.append(lead)
                    logger.info(f"Extracted valid lead: {lead.email} for event {lead.event_name}")
                    
                    # ------ IMMEDIATE SAVE: DB + Mailchimp ------
                    lead_dict = {
                        "name": lead.name,
                        "email": lead.email.lower(),
                        "phone": lead.phone,
                        "event_name": lead.event_name,
                        "event_url": lead.event_url,
                        "event_start_date": None,
                        "event_end_date": None
                    }
                    try:
                        if lead.event_start_date:
                            lead_dict["event_start_date"] = date_parser.parse(lead.event_start_date)
                        if lead.event_end_date:
                            lead_dict["event_end_date"] = date_parser.parse(lead.event_end_date)
                    except Exception as e:
                        logger.warning(f"Could not parse dates for {lead.email}: {e}")
                    
                    db_lead, is_new = repository.add_lead(lead_dict)
                    if db_lead:
                        saved_leads_info.append({"email": db_lead.email, "name": db_lead.name, "event_url": lead_dict["event_url"]})
                        
                        # Sync to Mailchimp right away ONLY IF IT'S A NEW LEAD
                        # This avoids redundant API calls and potential validation errors on every run
                        if is_new:
                            logger.info(f"Immediately saved lead to DB: {db_lead.email}")
                            if config.ENABLE_MAILCHIMP_SYNC:
                                name_parts = (lead.name or "").split(" ")
                                first_name = name_parts[0] if name_parts else ""
                                last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
                                success = add_lead_to_mailchimp(db_lead.email, first_name, last_name, lead.event_url or "")
                                if success:
                                    repository.update_lead_status(db_lead.id, status='marketed', campaign_sent=True)
                                    marketed_emails.append(db_lead.email)
                                    logger.info(f"Immediately synced to Mailchimp: {db_lead.email}")
                            else:
                                logger.info(f"Mailchimp sync bypass enabled. Lead {db_lead.email} stored as new.")
                        else:
                            logger.info(f"Lead {db_lead.email} already exists, skipping Mailchimp sync.")
                    # ------ END IMMEDIATE SAVE ------
                    
        except Exception as e:
            logger.error(f"Error scraping or extracting from {url}: {e}")

    return {
        "scraped_leads": valid_leads,
        "saved_leads": saved_leads_info,
        "marketed_leads": marketed_emails
    }

def db_manager_node(state: GraphState):
    """No-op node. Leads are now saved immediately in scraper_node."""
    logger.info("--- DB MANAGER NODE (pass-through, leads already saved) ---")
    return {}

def marketing_node(state: GraphState):
    """No-op node. Mailchimp sync is now done immediately in scraper_node."""
    logger.info("--- MARKETING NODE (pass-through, leads already synced) ---")
    return {}

def notifier_node(state: GraphState):
    """Sends notifications for the entire batch if any marketed leads exist."""
    logger.info("--- NOTIFIER NODE ---")
    marketed_count = len(state.get("marketed_leads", []))
    
    if marketed_count > 0:
        message = f"Event Prospecting Agent Update:\nFound, saved, and added {marketed_count} new leads to Mailchimp."
        logger.info(message)
        
        # send_whatsapp_notification(message)
        # send_email_notification("Eventra Leads Update", message)
        return {"notifications_sent": True}
    return {"notifications_sent": False}

# --- Graph Definition ---
def build_graph() -> StateGraph:
    workflow = StateGraph(GraphState)
    
    workflow.add_node("searcher", searcher_node)
    workflow.add_node("scraper", scraper_node)
    workflow.add_node("db_manager", db_manager_node)
    workflow.add_node("marketing", marketing_node)
    workflow.add_node("notifier", notifier_node)
    
    workflow.set_entry_point("searcher")
    
    workflow.add_edge("searcher", "scraper")
    workflow.add_edge("scraper", "db_manager")
    workflow.add_edge("db_manager", "marketing")
    workflow.add_edge("marketing", "notifier")
    workflow.add_edge("notifier", END)
    
    return workflow.compile()

# Global graph instance
app_graph = build_graph()
