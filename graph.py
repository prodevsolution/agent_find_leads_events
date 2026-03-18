import operator
import logging
from typing import TypedDict, Annotated, List, Any
from datetime import datetime, timezone


from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field
import pydantic

from tools import search_events, scrape_event_page, scrape_dynamic_mcp, add_lead_to_mailchimp, send_whatsapp_notification, send_email_notification
from database import repository
from dateutil import parser as date_parser
import config

logger = logging.getLogger(__name__)


# --- Models ---
class LeadData(BaseModel):
    name: str | None = Field(default=None, description="Name of the contact person or organization.")
    email: str | None = Field(default=None, description="Email address extracted.")
    phone: str | None = Field(default=None, description="Phone number extracted.")
    event_name: str | None = Field(default=None, description="Name of the event.")
    event_url: str | None = Field(default=None, description="URL of the event page.")
    event_start_date: str | None = Field(default=None, description="Start date of the event in ISO 8601 format.")
    event_end_date: str | None = Field(default=None, description="End date of the event in ISO 8601 format.")
    is_valid_date: bool = Field(default=True, description="False if event_start_date is securely known to be in the past relative to current_date.")

    @pydantic.model_validator(mode='after')
    def check_contact_info(self) -> 'LeadData':
        if not self.email and not self.phone:
            raise ValueError("Lead must have at least an email or a phone number.")
        return self

class SearchResultUrls(BaseModel):
    urls: List[str] = Field(description="List of URLs found for potential events.")

class ExtractedLeads(BaseModel):
    leads: List[LeadData] = Field(description="List of leads extracted from the page.")

class EntityList(BaseModel):
    entities: List[str] = Field(description="List of company names, venues, or organizations found in the LLM's knowledge for a niche.")

# --- State ---
class GraphState(TypedDict):
    search_queries: list[str]
    search_criteria: str
    brainstormed_entities: Annotated[list[str], operator.add]
    start_date: str | None
    end_date: str | None
    current_date: str
    
    # Path results
    summarizer_leads: Annotated[list[LeadData], operator.add]
    scraper_leads: Annotated[list[LeadData], operator.add]
    
    # State accumulators using operator.add to append across nodes
    urls_to_scrape: Annotated[list[str], operator.add]
    scraped_leads: Annotated[list[LeadData], operator.add]
    saved_leads: Annotated[list[dict], operator.add]
    marketed_leads: Annotated[list[str], operator.add]
    notifications_sent: bool
    max_results: int



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

def get_brainstorm_llm():
    """Returns a cached, structured-output LLM instance for brainstorming."""
    return get_llm().with_structured_output(EntityList)


# --- Nodes ---
def brainstormer_node(state: GraphState):
    """Uses LLM internal knowledge to suggest specific entities for each niche."""
    logger.info("--- BRAINSTORMER NODE ---")
    llm = get_brainstorm_llm()
    all_entities = []
    
    criteria = state.get("search_criteria", "")
    context_str = f" with criteria: {criteria}" if criteria else ""

    for niche in state.get("search_queries", []):
        prompt = (
            f"Think about the niche: '{niche}'{context_str}. "
            f"List 10 famous or representative companies, productions, circus troupes, theaters, or fairgrounds "
            f"associated with this niche that might have contact information online. "
            f"Return only the names."
        )
        try:
            result = llm.invoke(prompt)
            all_entities.extend(result.entities)
            logger.info(f"Brainstormed {len(result.entities)} entities for niche: {niche}")
        except Exception as e:
            logger.error(f"Brainstorming failed for niche '{niche}': {e}")
            
    return {"brainstormed_entities": all_entities}

def summarizer_node(state: GraphState):
    """
    Agente 'Fast Summarizer' (Estilo ChatGPT/Gemini).
    Uses Tavily to get snippets and LLM to extract multiple leads immediately (RAG).
    """
    logger.info("--- SUMMARIZER NODE (ChatGPT Style) ---")
    llm = get_structured_llm()
    all_leads = []
    criteria = state.get("search_criteria", "")
    
    for niche in state.get("search_queries", []):
        limit = config.SUMMARIZER_RESULT_LIMIT
        query = f"list of {limit} {niche} events starting from {state['start_date']} {criteria} with contact information"
        try:
            # We use search_events but specifically looking for many results/snippets
            results = search_events.invoke({
                "query": query, 
                "start_date": state.get("start_date"), 
                "end_date": state.get("end_date"),
                "max_results": state.get("max_results")
            })
            
            # Combine snippets into a context for the LLM
            context = "\n\n".join([f"Source: {res['url']}\nContent: {res['content']}" for res in results[:10]])
            
            prompt = (
                f"You are a lead extraction agent. Based on the following search results about '{niche}', "
                f"extract a list of as many contacts as possible (emails, names, events). "
                f"The current date is {state['current_date']}. "
                f"Identify events in 2026 or later as per the criteria: {criteria}. "
                f"\n\nContext:\n{context}"
            )
            
            extraction = llm.invoke(prompt)
            for lead in extraction.leads:
                lead.event_url = f"Found via Search: {niche}" # Attribution
                all_leads.append(lead)
                
            logger.info(f"Summarizer found {len(extraction.leads)} potential leads for niche: {niche}")
        except Exception as e:
            logger.error(f"Summarizer failed for niche '{niche}': {e}")
            
    return {"summarizer_leads": all_leads}

def searcher_node(state: GraphState):
    """Uses Tavily to search for the specific queries for deep scraping."""
    logger.info("--- SEARCHER NODE ---")
    urls = []
    criteria = state.get("search_criteria", "")
    
    for niche in state.get("search_queries", []):
        # Base queries for the niche
        queries_to_run = [
            f"{niche} events {criteria}",
            f"{niche} contact email {criteria}",
            f"upcoming {niche} venues {criteria}"
        ]
        
        # Add entity-specific queries from brainstorming
        entities = state.get("brainstormed_entities", [])
        for entity in entities[:10]: # Limit
             queries_to_run.append(f"{entity} official website contact {criteria}")
        
        for query in queries_to_run:
            try:
                results = search_events.invoke({
                    "query": query, 
                    "start_date": state.get("start_date"), 
                    "end_date": state.get("end_date"),
                    "max_results": state.get("max_results")
                })
                for res in results:
                    if res.get("url") and res.get("url") not in urls:
                        urls.append(res["url"])
            except Exception as e:
                logger.error(f"Search failed for query '{query}': {e}")
            
    return {"urls_to_scrape": urls}

def scraper_node(state: GraphState):
    """
    Scrapes high-value URLs (LinkedIn/Dynamic) identified by searcher.
    """
    logger.info("--- SCRAPER NODE (Deep Scraper) ---")
    llm = get_structured_llm()
    valid_leads = []
    current_date_str = state.get("current_date")
    
    for url in state.get("urls_to_scrape", []):
        try:
            dynamic_domains = ["linkedin.com", "instagram.com", "facebook.com", "tiktok.com", "twitter.com"]
            is_dynamic = any(domain in url.lower() for domain in dynamic_domains)
            
            if is_dynamic:
                logger.info(f"Using DYNAMIC scraper for: {url}")
                scraped_data = scrape_dynamic_mcp.invoke({"url": url})
            else:
                scraped_data = scrape_event_page.invoke({"url": url})
                
            if not scraped_data.get("content"):
                continue
                
            prompt = (
                f"Analyze the following event page content and identify contact leads (email, phone, name). "
                f"Also identify the event name and dates. The current date is {current_date_str}. "
                f"The page URL is: {url}\n\nContent:\n{scraped_data['content'][:config.SCRAPER_CONTENT_LIMIT]}"
            )
            
            extraction = llm.invoke(prompt)
            for lead in extraction.leads:
                if lead.is_valid_date and lead.email:
                    lead.event_url = url
                    valid_leads.append(lead)
                    
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")

    return {"scraper_leads": valid_leads}

def deduplicator_node(state: GraphState):
    """
    Compares results from Summarizer and Scraper paths.
    Saves results to DB and identifies coincidences.
    """
    logger.info("--- DEDUPLICATOR NODE ---")
    sum_leads = state.get("summarizer_leads", [])
    scr_leads = state.get("scraper_leads", [])
    
    all_leads = sum_leads + scr_leads
    unique_emails = {}
    marketed_emails = []
    saved_info = []
    
    coincidences = 0
    
    # Process all found leads
    for lead in all_leads:
        email = lead.email.lower()
        if email not in unique_emails:
            unique_emails[email] = lead
        else:
            coincidences += 1
            # Prefer deep scraper data over summarizer if available
            if lead in scr_leads:
                unique_emails[email] = lead

    logger.info(f"Deduplication: Total={len(all_leads)}, Unique={len(unique_emails)}, Coincidences={coincidences}")

    for email, lead in unique_emails.items():
        lead_dict = {
            "name": lead.name,
            "email": email,
            "phone": lead.phone,
            "event_name": lead.event_name,
            "event_url": lead.event_url,
            "status": "new"
        }
        
        try:
            if lead.event_start_date:
                lead_dict["event_start_date"] = date_parser.parse(lead.event_start_date)
            if lead.event_end_date:
                lead_dict["event_end_date"] = date_parser.parse(lead.event_end_date)
        except: pass

        db_lead, is_new = repository.add_lead(lead_dict)
        if db_lead:
            saved_info.append({"email": db_lead.email, "name": db_lead.name})
            
            if is_new and config.ENABLE_MAILCHIMP_SYNC:
                name_parts = (lead.name or "").split(" ")
                first_name = name_parts[0] if name_parts else ""
                last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
                
                success = add_lead_to_mailchimp(db_lead.email, first_name, last_name, lead.event_url or "")
                if success:
                    repository.update_lead_status(db_lead.id, status='marketed', campaign_sent=True)
                    marketed_emails.append(db_lead.email)

    return {
        "saved_leads": saved_info,
        "marketed_leads": marketed_emails,
        "scraped_leads": list(unique_emails.values())
    }

def notifier_node(state: GraphState):
    """Sends notifications."""
    logger.info("--- NOTIFIER NODE ---")
    marketed_count = len(state.get("marketed_leads", []))
    if marketed_count > 0:
        message = f"Event Prospecting Agent Update:\nParallel run finished. Found {marketed_count} new leads."
        logger.info(message)
        # Notifications here...
        return {"notifications_sent": True}
    return {"notifications_sent": False}

# --- Graph Definition ---
def build_graph() -> StateGraph:
    workflow = StateGraph(GraphState)
    
    workflow.add_node("brainstormer", brainstormer_node)
    workflow.add_node("summarizer", summarizer_node)
    workflow.add_node("searcher", searcher_node)
    workflow.add_node("scraper", scraper_node)
    workflow.add_node("deduplicator", deduplicator_node)
    workflow.add_node("notifier", notifier_node)
    
    workflow.set_entry_point("brainstormer")
    
    # Brainstormer starts both paths
    workflow.add_edge("brainstormer", "summarizer")
    workflow.add_edge("brainstormer", "searcher")
    
    # Path 1: Search -> Scrape
    workflow.add_edge("searcher", "scraper")
    
    # Both paths converge at deduplicator
    workflow.add_edge("summarizer", "deduplicator")
    workflow.add_edge("scraper", "deduplicator")
    
    workflow.add_edge("deduplicator", "notifier")
    workflow.add_edge("notifier", END)
    
    return workflow.compile()

# Global graph instance
app_graph = build_graph()
