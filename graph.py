import operator
import logging
from typing import TypedDict, Annotated, List, Any
from datetime import datetime, timezone


from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from tools import search_events, scrape_event_page, add_lead_to_mailchimp, send_whatsapp_notification, send_email_notification
from database import repository
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

# --- LLM ---
def get_llm():
    if config.LLM_PROVIDER == "ollama":
        logger.info(f"Using Ollama LLM with model: {config.OLLAMA_MODEL}")
        return ChatOllama(
            model=config.OLLAMA_MODEL,
            base_url=config.OLLAMA_BASE_URL,
            temperature=0
        )
    else:
        logger.info("Using OpenAI LLM (gpt-4o-mini)")
        return ChatOpenAI(model="gpt-4o-mini", temperature=0)


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
    """Scrapes URLs and extracts leads using LLM."""
    logger.info("--- SCRAPER NODE ---")
    llm = get_llm().with_structured_output(ExtractedLeads)
    valid_leads = []
    current_date_str = state.get("current_date")
    
    for url in state.get("urls_to_scrape", []):
        try:
            scraped_data = scrape_event_page.invoke({"url": url})
            if not scraped_data.get("content"):
                continue
                
            # If we found at least one email via regex, use LLM to extract context
            if scraped_data.get("emails"):
                prompt = (
                    f"Analyze the following event page content and identify contact leads (email, phone, name). "
                    f"Also identify the event name and dates. The current date is {current_date_str}. "
                    f"If the event start date is already past compared to the current date, set is_valid_date to False. "
                    f"If you can't determine the date, assume it's valid (True). "
                    f"The page URL is: {url}\n\nContent:\n{scraped_data['content'][:5000]}"
                )
                
                extraction = llm.invoke(prompt)
                
                for lead in extraction.leads:
                    # Time-aware Validation: discard if event is in the past
                    if lead.is_valid_date and lead.email:
                        # Ensure the URL is attached
                        lead.event_url = url
                        valid_leads.append(lead)
                        logger.info(f"Extracted valid lead: {lead.email} for event {lead.event_name}")
                    else:
                        logger.info(f"Discarded lead due to past date: {lead.email} - {lead.event_start_date}")
        except Exception as e:
            logger.error(f"Error scraping or extracting from {url}: {e}")

    return {"scraped_leads": valid_leads}

def db_manager_node(state: GraphState):
    """Saves leads to SQLite using the repository pattern."""
    logger.info("--- DB MANAGER NODE ---")
    saved_leads_info = []
    
    for lead in state.get("scraped_leads", []):
        lead_dict = {
            "name": lead.name,
            "email": lead.email.lower(),
            "phone": lead.phone,
            "event_name": lead.event_name,
            "event_url": lead.event_url,
            "event_start_date": None,
            "event_end_date": None
        }
        
        # safely parse dates
        from dateutil import parser as date_parser
        try:
            if lead.event_start_date:
                lead_dict["event_start_date"] = date_parser.parse(lead.event_start_date)
            if lead.event_end_date:
                lead_dict["event_end_date"] = date_parser.parse(lead.event_end_date)
        except Exception as e:
            logger.warning(f"Could not parse dates for {lead.email}: {e}")

        # Insert into DB
        db_lead = repository.add_lead(lead_dict)
        if db_lead:
            saved_leads_info.append({"email": db_lead.email, "name": db_lead.name})
            
    return {"saved_leads": saved_leads_info}

def marketing_node(state: GraphState):
    """Pushes new leads to Mailchimp."""
    logger.info("--- MARKETING NODE ---")
    marketed_emails = []
    
    for lead_info in state.get("saved_leads", []):
        email = lead_info["email"]
        name_parts = (lead_info["name"] or "").split(" ")
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        
        success = add_lead_to_mailchimp(email, first_name, last_name)
        if success:
            repository.update_lead_status(email, status='marketed', campaign_sent=True)
            marketed_emails.append(email)
            
    return {"marketed_leads": marketed_emails}

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
