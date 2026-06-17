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

    # Removed strict validator to allow LLM to return partial leads without crashing the extraction batch.
    # Filtering is now handled at the node level.

class SearchResultUrls(BaseModel):
    urls: List[str] = Field(description="List of URLs found for potential events.")

class ExtractedLeads(BaseModel):
    leads: List[LeadData] = Field(description="List of leads extracted from the page.")

class EntityList(BaseModel):
    entities: List[str] = Field(description="List of company names, venues, or organizations found in the LLM's knowledge for a niche.")

class GraphState(TypedDict):
    search_queries: list[str]
    search_criteria: str
    brainstormed_entities: Annotated[list[str], operator.add]
    start_date: str | None
    end_date: str | None
    current_date: str
    
    # ProDev Persona classification
    persona_type: str | None
    target_product: str | None
    
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
    # Accumulated raw content from all searches for deep synthesis
    all_search_content: Annotated[list[str], operator.add]
    agentic_leads: Annotated[list[LeadData], operator.add]
    sync_mailchimp: bool | None



from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI

# --- LLM Factory ---
def get_llm(model_override: str = None):
    """Returns an LLM. model_override takes priority over config settings."""
    provider = config.LLM_PROVIDER
    if model_override and provider == "openai":
        logger.info(f"Using OpenAI LLM ({model_override})")
        return ChatOpenAI(model=model_override, temperature=0)
    if provider == "ollama":
        logger.info(f"Using Ollama LLM with model: {config.OLLAMA_MODEL}")
        return ChatOllama(
            model=config.OLLAMA_MODEL,
            base_url=config.OLLAMA_BASE_URL,
            temperature=0,
            num_predict=config.OLLAMA_NUM_PREDICT,
            timeout=config.OLLAMA_TIMEOUT,
        )
    elif provider == "openai":
        logger.info("Using OpenAI LLM (gpt-4o-mini) [fast/cheap]")
        return ChatOpenAI(model="gpt-4o-mini", temperature=0)
    else:
        logger.info("Using Google Gemini LLM (gemini-2.0-flash)")
        return ChatGoogleGenerativeAI(model="gemini-2.0-flash")

# Singleton caches per model role
_extractor_structured = None  # For summarizer + scraper (uses EXTRACTOR_MODEL)

def get_structured_llm():
    """Returns a cached structured-output LLM using EXTRACTOR_MODEL (gpt-4o by default)."""
    global _extractor_structured
    if _extractor_structured is None:
        llm = get_llm(model_override=config.EXTRACTOR_MODEL)
        _extractor_structured = llm.with_structured_output(ExtractedLeads)
        logger.info(f"Extractor LLM created: {config.EXTRACTOR_MODEL}")
    return _extractor_structured

def get_brainstorm_llm():
    """Returns a structured-output LLM for brainstorming (fast, cheap gpt-4o-mini)."""
    return get_llm(model_override="gpt-4o-mini").with_structured_output(EntityList)


# --- Nodes ---
def brainstormer_node(state: GraphState):
    """Uses LLM internal knowledge to suggest specific entities for each niche."""
    logger.info("--- BRAINSTORMER NODE ---")
    persona = state.get("persona_type")
    if persona:
        logger.info(f"Brainstormer: ProDev Persona '{persona}' detected. Skipping generic brainstorming.")
        return {"brainstormed_entities": []}

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
    persona = state.get("persona_type")
    
    for niche in state.get("search_queries", []):
        limit = config.SUMMARIZER_RESULT_LIMIT
        if persona:
            # Query is already a complete tailored search query
            query = f"{niche} {criteria}".strip()
        else:
            query = f"list of {limit} {niche} events starting from {state['start_date']} {criteria} with contact information"
            
        try:
            results = search_events.invoke({
                "query": query, 
                "start_date": state.get("start_date"), 
                "end_date": state.get("end_date"),
                "max_results": state.get("max_results")
            })
            
            context = "\n\n".join([f"Source: {res['url']}\nContent: {res['content']}" for res in results[:20]]) 
            
            if persona:
                prompt = (
                    f"You are a professional lead extraction agent targeting business contacts for the product/persona: '{persona}'.\n"
                    f"Based on the following search results for the query '{niche}', "
                    f"extract a list of as many unique contacts as possible (emails, phone numbers, names, websites).\n"
                    f"Identify relevant business leads or upcoming event contacts as per the criteria: {criteria}.\n"
                    f"Do not skip any lead that has an email or phone number in the provided context.\n"
                    f"Current date is {state['current_date']}.\n\n"
                    f"Context:\n{context}"
                )
            else:
                prompt = (
                    f"You are a professional lead extraction agent. Based on the following search results about '{niche}', "
                    f"extract a list of as many unique contacts as possible (emails, names, events, phone numbers). "
                    f"Even if the contact information is partial, extract what you can find. "
                    f"The current date is {state['current_date']}. "
                    f"Identify upcoming events in 2026 or later as per the criteria: {criteria}. "
                    f"IMPORTANT: Do not skip any lead that has an email or phone number in the provided context."
                    f"\n\nContext:\n{context}"
                )
            
            extraction = llm.invoke(prompt)
            logger.info(f"Summarizer LLM returned {len(extraction.leads)} raw leads for: {niche}")
            for lead in extraction.leads:
                if lead.email or lead.phone:
                    if not lead.event_url:
                        lead.event_url = f"Found via Search: {niche}"
                    all_leads.append(lead)
                
            logger.info(f"Summarizer found {len(all_leads)} leads with contact info.")
        except Exception as e:
            logger.error(f"Summarizer failed for '{niche}': {e}")
            
    return {"summarizer_leads": all_leads}

def searcher_node(state: GraphState):
    """Uses Tavily to search for the specific queries for deep scraping."""
    logger.info("--- SEARCHER NODE ---")
    urls = []
    criteria = state.get("search_criteria", "")
    persona = state.get("persona_type")
    
    # If we are doing a persona run, the queries are already precise, so we run them directly
    if persona:
        queries_to_run = [f"{q} {criteria}".strip() for q in state.get("search_queries", [])]
    else:
        queries_to_run = []
        for niche in state.get("search_queries", []):
            queries_to_run.extend([
                f"{niche} events {criteria}",
                f"{niche} contact email {criteria}",
                f"upcoming {niche} venues {criteria}"
            ])
            entities = state.get("brainstormed_entities", [])
            for entity in entities[:10]:
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
            logger.info(f"Scraper LLM returned {len(extraction.leads)} raw leads for {url}")
            for lead in extraction.leads:
                # Filter: Valid date AND at least one contact method (email or phone)
                if lead.is_valid_date and (lead.email or lead.phone):
                    lead.event_url = url
                    valid_leads.append(lead)
                    
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")

    logger.info(f"Scraper node finished. Total valid leads found: {len(valid_leads)}")
    return {"scraper_leads": valid_leads}

def agentic_researcher_node(state: GraphState):
    """
    ChatGPT-style 'Deep Research' node.
    Collects ALL content gathered by the summarizer searches and the scraper pages,
    then performs ONE holistic synthesis pass using the best available model.
    """
    logger.info("--- AGENTIC RESEARCHER NODE (Deep Synthesis) ---")
    llm = get_structured_llm()
    criteria = state.get("search_criteria", "")
    current_date = state.get("current_date", "")
    start_date = state.get("start_date", "")
    persona = state.get("persona_type")
    
    all_content_pieces = []
    
    for niche in state.get("search_queries", []):
        try:
            if persona:
                query = f"{niche} contact details phone email {criteria}".strip()
            else:
                query = f"{niche} contact email phone {criteria}".strip()
                
            results = search_events.invoke({
                "query": query,
                "start_date": start_date,
                "max_results": min(state.get("max_results", 15), 20)
            })
            for res in results[:5]:  # Use top 5 deep results per query
                if res.get("content"):
                    all_content_pieces.append(
                        f"[SOURCE: {res['url']}]\n{res['content'][:config.SCRAPER_CONTENT_LIMIT]}"
                    )
        except Exception as e:
            logger.error(f"Agentic search failed for '{niche}': {e}")

    if not all_content_pieces:
        logger.info("Agentic researcher: no content to synthesize.")
        return {"agentic_leads": []}

    full_context = "\n\n---\n\n".join(all_content_pieces)
    
    if persona:
        prompt = (
            f"You are an expert lead extraction agent with deep research capabilities targeting business prospects for: '{persona}'.\n"
            f"Your task: extract EVERY business contact (name, email, phone, website, company) from the sources below.\n"
            f"Target product/service criteria: {criteria}\n"
            f"Current date: {current_date}\n"
            f"RULES:\n"
            f"- If it's an event, it must start after {start_date}.\n"
            f"- Include ALL contacts even if info is partial.\n"
            f"- Do NOT invent data.\n"
            f"- Extract every email and phone number you find.\n\n"
            f"SOURCES:\n{full_context}"
        )
    else:
        prompt = (
            f"You are an expert lead extraction agent with deep research capabilities.\n"
            f"Your task: extract EVERY contact (name, email, phone) for UPCOMING EVENTS from the sources below.\n"
            f"Niches: {', '.join(state.get('search_queries', []))}\n"
            f"Criteria: {criteria}\n"
            f"Current date: {current_date} | Events must start after: {start_date}\n"
            f"RULES:\n"
            f"- Only include events with start_date >= {start_date}. Set is_valid_date=False for past events.\n"
            f"- Include ALL contacts even if information is partial.\n"
            f"- Do NOT invent data. Only extract what is explicitly stated in the sources.\n"
            f"- Extract every email and phone number you find.\n\n"
            f"SOURCES:\n{full_context}"
        )
    
    try:
        extraction = llm.invoke(prompt)
        valid = [
            lead for lead in extraction.leads
            if lead.is_valid_date and (lead.email or lead.phone)
        ]
        logger.info(f"Agentic researcher found {len(valid)} valid leads from holistic synthesis.")
        return {"agentic_leads": valid}
    except Exception as e:
        logger.error(f"Agentic researcher synthesis failed: {e}")
        return {"agentic_leads": []}

def deduplicator_node(state: GraphState):
    """
    Compares results from Summarizer and Scraper paths.
    Saves results to DB and identifies coincidences.
    """
    logger.info("--- DEDUPLICATOR NODE ---")
    sum_leads = state.get("summarizer_leads", [])
    scr_leads = state.get("scraper_leads", [])
    agt_leads = state.get("agentic_leads", [])
    
    all_leads = sum_leads + scr_leads + agt_leads
    logger.info(f"Deduplicator: Summarizer={len(sum_leads)}, Scraper={len(scr_leads)}, Agentic={len(agt_leads)}, Total={len(all_leads)}")
    unique_emails = {}
    marketed_emails = []
    saved_info = []
    
    coincidences = 0
    
    # Process all found leads
    for lead in all_leads:
        # Use email if available, otherwise just use None (but handle cautiously)
        email = lead.email.lower() if lead.email else None
        
        # If we have an email, use it for deduplication
        if email:
            if email not in unique_emails:
                unique_emails[email] = lead
            else:
                coincidences += 1
                # Prefer deep scraper data over summarizer if available
                if lead in scr_leads:
                    unique_emails[email] = lead
        elif lead.phone:
            # If no email but has phone, use phone as a temporary unique identifier for this batch
            phone_key = f"phone_{lead.phone}"
            if phone_key not in unique_emails:
                unique_emails[phone_key] = lead
            else:
                coincidences += 1

    logger.info(f"Deduplication: Total={len(all_leads)}, Unique={len(unique_emails)}, Coincidences={coincidences}")

    for item_key, lead in unique_emails.items():
        lead_dict = {
            "name": lead.name,
            "email": lead.email, # Use lead.email instead of the loop key (item_key)
            "phone": lead.phone,
            "event_name": lead.event_name,
            "event_url": lead.event_url,
            "status": "new",
            "persona_type": state.get("persona_type"),
            "target_product": state.get("target_product")
        }
        
        try:
            if lead.event_start_date:
                lead_dict["event_start_date"] = date_parser.parse(lead.event_start_date)
            if lead.event_end_date:
                lead_dict["event_end_date"] = date_parser.parse(lead.event_end_date)
        except: pass

        db_lead, is_new = repository.add_lead(lead_dict)
        if db_lead:
            saved_info.append({"email": db_lead.email or "Phone Lead", "name": db_lead.name})
            logger.info(f"Deduplicator: Lead processed: {db_lead.email or db_lead.phone} (is_new={is_new})")
            
            # Mailchimp sync REQUIRES an email. Skip if None.
            sync_enabled = state.get("sync_mailchimp")
            if sync_enabled is None:
                sync_enabled = config.ENABLE_MAILCHIMP_SYNC
            
            if is_new and sync_enabled and db_lead.email:
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
    workflow.add_node("agentic_researcher", agentic_researcher_node)  # NEW: ChatGPT-style deep synthesis
    workflow.add_node("deduplicator", deduplicator_node)
    workflow.add_node("notifier", notifier_node)
    
    workflow.set_entry_point("brainstormer")
    
    # Brainstormer starts three parallel paths
    workflow.add_edge("brainstormer", "summarizer")          # Path 1: Fast summarizer (snippets)
    workflow.add_edge("brainstormer", "searcher")             # Path 2: Deep search -> scrape
    workflow.add_edge("brainstormer", "agentic_researcher")  # Path 3: Holistic synthesis (ChatGPT-style)
    
    # Path 2: Search -> Scrape
    workflow.add_edge("searcher", "scraper")
    
    # All three paths converge at deduplicator
    workflow.add_edge("summarizer", "deduplicator")
    workflow.add_edge("scraper", "deduplicator")
    workflow.add_edge("agentic_researcher", "deduplicator")
    
    workflow.add_edge("deduplicator", "notifier")
    workflow.add_edge("notifier", END)
    
    return workflow.compile()

# Global graph instance
app_graph = build_graph()
