import operator
import logging
from typing import TypedDict, Annotated, List, Any
from datetime import datetime, timezone


import json
import re
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field
import pydantic

from tools import search_events, scrape_event_page, scrape_dynamic_mcp, add_lead_to_mailchimp, send_whatsapp_notification, send_email_notification
from database import repository
from dateutil import parser as date_parser
import config

logger = logging.getLogger(__name__)

# ── Fake / placeholder data filters ──────────────────────────────────────────

FAKE_EMAIL_DOMAINS = {
    "example.com", "example.org", "example.net",
    "test.com", "test.org", "test.net",
    "yourdomain.com", "yourname.com", "yourname.net",
    "domain.com", "domain.net", "domain.org",
    "sample.com", "sample.org", "sample.net",
    "demo.com", "demo.org", "demo.net",
    "fake.com", "placeholder.com",
    "mailinator.com", "guerrillamail.com", "tempmail.com",
    "throwaway.com", "yopmail.com",
}

GENERIC_NAMES = {
    "lorem ipsum", "test user", "test name",
    "sample user", "sample name", "demo user",
    "first name", "last name",
    "not provided", "not specified",
}

# Email local-part patterns that indicate placeholder/example data
FAKE_EMAIL_LOCALPARTS = {
    "johndoe", "janedoe", "johnsmith", "janesmith",
    "test", "testing", "sample", "demo", "placeholder",
    "yourname", "youremail", "name", "email",
}

# Phone patterns that are clearly fake/staging
FAKE_PHONE_PREFIXES = {
    "555", "000", "123", "999",
}

# Content strings that indicate non-production pages
LOW_VALUE_CONTENT_SIGNALS = [
    "under construction", "coming soon", "landing page",
    "this page is not found", "page not found",
    "redirecting", "go to homepage",
    "lorem ipsum", "sample text", "placeholder",
]


def _is_fake_email(email: str | None) -> bool:
    """Check if email is from a known placeholder domain or has placeholder local-part."""
    if not email:
        return False
    email_lower = email.lower().strip()
    if "@" not in email_lower:
        return False
    domain = email_lower.split("@")[-1]
    local = email_lower.split("@")[0]

    # Remove digits for local-part checking
    local_clean = local.rstrip("0123456789")

    if domain in FAKE_EMAIL_DOMAINS:
        return True
    if local_clean in FAKE_EMAIL_LOCALPARTS:
        return True
    return False


def _is_fake_name(name: str | None) -> bool:
    """Check if the name is a known generic/placeholder name."""
    if not name:
        return False
    name_lower = name.strip().lower()
    if name_lower in GENERIC_NAMES:
        return True
    parts = [p.strip() for p in name_lower.replace(",", "").split() if p.strip()]
    generic_count = sum(1 for p in parts if p in GENERIC_NAMES)
    return generic_count == len(parts) and len(parts) > 0


def _is_fake_phone(phone: str | None) -> bool:
    """Check if phone number is clearly fake/staging.
    
    Checks if the phone contains reserved/staging number patterns
    (555 is reserved for fictional use in NANP).
    """
    if not phone:
        return False
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 7:
        return True  # Too short to be a real phone
    # 555 numbers are reserved for fictional use (NANP)
    if "555" in digits:
        return True
    # All same digits (0000000, 1111111, etc.)
    if len(set(digits)) == 1:
        return True
    return False


def _is_fake_lead(name: str | None, email: str | None, phone: str | None = None) -> bool:
    """Returns True if the lead appears to be fake/placeholder data.
    
    Rules:
      - If email has fake domain or placeholder local-part (johndoe@) → filter.
      - If phone is a staging prefix (555-, 000-, 123-) → filter.
      - If name is generic AND no real email → filter.
      - If ALL three (name, email, phone) are missing/empty → filter.
    """
    if _is_fake_email(email):
        return True
    if _is_fake_phone(phone):
        return True
    if not email and not phone and _is_fake_name(name):
        return True
    return False


def _is_low_value_content(content: str) -> bool:
    """Check if page content is too thin or clearly a placeholder page."""
    if not content:
        return True
    stripped = content.strip()
    if len(stripped) < 150:
        return True
    # Check for non-production signals
    lower = stripped.lower()
    for signal in LOW_VALUE_CONTENT_SIGNALS:
        if signal in lower:
            return True
    return False


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

class LinkedInProfile(BaseModel):
    name: str | None = Field(default=None, description="Person's name from LinkedIn profile.")
    title: str | None = Field(default=None, description="Job title or headline from LinkedIn.")
    company: str | None = Field(default=None, description="Company or organization.")
    location: str | None = Field(default=None, description="Geographic location.")
    profile_url: str | None = Field(default=None, description="LinkedIn profile URL.")
    snippet: str | None = Field(default=None, description="Raw snippet text from search.")

class ExtractedLinkedInProfiles(BaseModel):
    profiles: List[LinkedInProfile] = Field(description="List of LinkedIn profiles extracted from search results.")

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
    # LinkedIn profiles found
    linkedin_profiles: Annotated[list[LinkedInProfile], operator.add]



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
            format="json",
        )
    elif provider == "openai":
        logger.info("Using OpenAI LLM (gpt-4o-mini) [fast/cheap]")
        return ChatOpenAI(model="gpt-4o-mini", temperature=0)
    else:
        logger.info("Using Google Gemini LLM (gemini-2.5-flash)")
        return ChatGoogleGenerativeAI(model="gemini-2.5-flash")

def _extract_json(text: str):
    """Extract JSON array or object from LLM text response."""
    # Try to find JSON block ```json ... ``` or {...}
    block = re.search(r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```", text, re.DOTALL)
    if block:
        text = block.group(1)
    # Try parsing as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find first { ... } or [ ... ] in text
    for delim in ("{", "["):
        start = text.find(delim)
        if start == -1:
            continue
        end = text.rfind("}" if delim == "{" else "]")
        if end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                continue
    return None

def _invoke_structured(llm, prompt, pydantic_model):
    """
    Call LLM and parse structured output.
    - OpenAI/Gemini: uses with_structured_output() (native tool calling).
    - Ollama: uses format='json' + manual JSON extraction (Grammar-Constrained).
    """
    provider = config.LLM_PROVIDER
    if provider == "ollama":
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        data = _extract_json(raw)
        if data is None:
            logger.warning(f"LLM returned non-JSON output:\n{raw[:300]}")
            raise ValueError("Invalid json output")
        if isinstance(data, dict) and pydantic_model.__name__ == "ExtractedLeads":
            if "leads" not in data:
                data = {"leads": [data]}
        if isinstance(data, dict) and pydantic_model.__name__ == "EntityList":
            if "entities" not in data:
                data = {"entities": data.get("entities", list(data.values())[0] if data else [])}
        return pydantic_model.model_validate(data)
    else:
        structured = llm.with_structured_output(pydantic_model)
        return structured.invoke(prompt)

# Singleton caches per model role
_extractor_llm = None

def get_structured_llm():
    """Returns a cached LLM instance for extraction (not using with_structured_output)."""
    global _extractor_llm
    if _extractor_llm is None:
        _extractor_llm = get_llm(model_override=config.EXTRACTOR_MODEL)
        logger.info(f"Extractor LLM created: {config.EXTRACTOR_MODEL}")
    return _extractor_llm

def get_brainstorm_llm():
    """Returns an LLM for brainstorming."""
    return get_llm(model_override="gemini-2.5-flash")


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
            result = _invoke_structured(llm, prompt, EntityList)
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
            
            # Filter out low-value or empty content (prevents LLM hallucination)
            valid_results = []
            for res in results[:20]:
                content = res.get("content") or ""
                if _is_low_value_content(content):
                    logger.debug(f"Skipping low-value content: {res.get('url')} ({len(content)} chars)")
                    continue
                valid_results.append(res)
            context = "\n\n".join([f"Source: {res['url']}\nContent: {res['content']}" for res in valid_results]) 
            
            if persona:
                prompt = (
                    f"You are a professional lead extraction agent targeting business contacts for the product/persona: '{persona}'.\n"
                    f"Based on the following search results for the query '{niche}', "
                    f"extract a list of as many unique contacts as possible (emails, phone numbers, names, websites).\n"
                    f"Identify relevant business leads or upcoming event contacts as per the criteria: {criteria}.\n"
                    f"Do not skip any lead that has an email or phone number in the provided context.\n"
                    f"Current date is {state['current_date']}.\n"
                    f"CRITICAL: Only extract data explicitly present in the context above. "
                    f"Never invent names, emails, phones, or any other information. "
                    f"If a field is not found in the context, leave it empty (null).\n\n"
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
                    f"CRITICAL: Only extract data explicitly present in the context. "
                    f"Never invent names, emails, phones, or any other information. "
                    f"If a field is not found in the context, leave it empty (null)."
                    f"\n\nContext:\n{context}"
                )
            
            extraction = _invoke_structured(llm, prompt, ExtractedLeads)
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
                
            content = scraped_data.get("content") or ""
            if _is_low_value_content(content):
                logger.debug(f"Skipping low-content scrape: {url} ({len(content)} chars)")
                continue
                
            prompt = (
                f"Analyze the following event page content and identify contact leads (email, phone, name). "
                f"Also identify the event name and dates. The current date is {current_date_str}. "
                f"The page URL is: {url}\n"
                f"CRITICAL: Only extract data explicitly visible in the content below. "
                f"Never invent names, emails, phones, event names, or any other information. "
                f"If a field is not found, leave it empty (null).\n\n"
                f"Content:\n{scraped_data['content'][:config.SCRAPER_CONTENT_LIMIT]}"
            )
            
            extraction = _invoke_structured(llm, prompt, ExtractedLeads)
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
        extraction = _invoke_structured(llm, prompt, ExtractedLeads)
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
    Compares results from Summarizer, Scraper, Agentic, and LinkedIn paths.
    Saves results to DB and identifies coincidences.
    """
    logger.info("--- DEDUPLICATOR NODE ---")
    sum_leads = state.get("summarizer_leads", [])
    scr_leads = state.get("scraper_leads", [])
    agt_leads = state.get("agentic_leads", [])
    linkedin = state.get("linkedin_profiles", [])
    
    all_leads = sum_leads + scr_leads + agt_leads
    logger.info(f"Deduplicator: Summarizer={len(sum_leads)}, Scraper={len(scr_leads)}, Agentic={len(agt_leads)}, LinkedIn={len(linkedin)}, Total={len(all_leads)}")
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
        # Skip fake / placeholder data
        if _is_fake_lead(lead.name, lead.email, lead.phone):
            logger.debug(f"Skipping fake lead: name={lead.name!r}, email={lead.email!r}, phone={lead.phone!r}")
            continue

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

        lead_dict["source_type"] = "web_search"

        db_lead, is_new = repository.add_lead(lead_dict)
        if db_lead:
            logger.info(f"Deduplicator: Lead processed: {db_lead.email or db_lead.phone} (is_new={is_new})")

            # Build a richer entry for downstream consumers (GDrive sync)
            entry = {
                "name": db_lead.name,
                "email": db_lead.email,
                "phone": db_lead.phone,
                "event_name": db_lead.event_name,
                "event_url": db_lead.event_url,
                "event_start_date": db_lead.event_start_date,
                "event_end_date": db_lead.event_end_date,
                "persona_type": db_lead.persona_type or state.get("persona_type"),
                "target_product": db_lead.target_product or state.get("target_product"),
                "source_type": db_lead.source_type or "web_search",
                "notes": db_lead.notes,
                "status": db_lead.status,
            }
            saved_info.append(entry)

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

    # Process LinkedIn profiles as leads
    persona_type = state.get("persona_type")
    target_product = state.get("target_product")
    for prof in linkedin:
        profile_url = prof.profile_url or ""
        if not profile_url:
            continue
        # Check not already in saved leads
        already = any(
            entry.get("event_url") == profile_url
            for entry in saved_info
        )
        if already:
            continue

        linkedin_note_parts = []
        if prof.title:
            linkedin_note_parts.append(f"Title: {prof.title}")
        if prof.company:
            linkedin_note_parts.append(f"Company: {prof.company}")
        if prof.location:
            linkedin_note_parts.append(f"Location: {prof.location}")
        if prof.snippet:
            linkedin_note_parts.append(f"Snippet: {prof.snippet[:200]}")

        lead_dict = {
            "name": prof.name or f"LinkedIn: {profile_url.split('/in/')[-1].rstrip('/')}",
            "email": None,
            "phone": None,
            "event_name": f"[LINKEDIN] {prof.title or 'Profile'}",
            "event_url": profile_url,
            "status": "new",
            "persona_type": persona_type,
            "target_product": target_product,
            "source_type": "linkedin_search",
            "notes": " | ".join(linkedin_note_parts) if linkedin_note_parts else None,
        }

        db_lead, is_new = repository.add_lead(lead_dict)
        if db_lead:
            logger.info(f"Deduplicator: LinkedIn lead processed: {db_lead.name} ({profile_url}) is_new={is_new}")
            entry = {
                "name": db_lead.name,
                "email": db_lead.email,
                "phone": db_lead.phone,
                "event_name": db_lead.event_name,
                "event_url": db_lead.event_url,
                "event_start_date": db_lead.event_start_date,
                "event_end_date": db_lead.event_end_date,
                "persona_type": db_lead.persona_type or persona_type,
                "target_product": db_lead.target_product or target_product,
                "source_type": db_lead.source_type or "linkedin_search",
                "notes": db_lead.notes,
                "status": db_lead.status,
            }
            saved_info.append(entry)

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
        return {"notifications_sent": True}
    return {"notifications_sent": False}


def linkedin_searcher_node(state: GraphState):
    """
    Searches LinkedIn profiles for each persona query using Tavily.
    Extracts name, title, company, location from search snippets without scraping full profiles.
    """
    logger.info("--- LINKEDIN SEARCHER NODE ---")
    persona = state.get("persona_type")
    criteria = state.get("search_criteria", "")

    if not persona or persona == "old_client":
        logger.info("LinkedIn searcher: no active persona, skipping.")
        return {"linkedin_profiles": []}

    queries = state.get("search_queries", [])
    if not queries:
        return {"linkedin_profiles": []}

    linkedin_queries = [
        f'{q} LinkedIn profile {criteria}'.strip()
        for q in queries
    ]
    if criteria:
        linkedin_queries.append(f'{persona} LinkedIn {criteria}')

    all_snippets: list[dict] = []
    seen_urls: set[str] = set()

    for query in linkedin_queries:
        try:
            results = search_events.invoke({
                "query": query,
                "max_results": min(state.get("max_results", 15), 20)
            })
            for res in results:
                url = res.get("url", "")
                content = res.get("content", "")
                if "linkedin.com/in/" in url and url not in seen_urls:
                    seen_urls.add(url)
                    all_snippets.append({"url": url, "content": content[:800]})
        except Exception as e:
            logger.error(f"LinkedIn search failed for '{query}': {e}")

    if not all_snippets:
        logger.info("LinkedIn searcher: no profiles found.")
        return {"linkedin_profiles": []}

    # Use LLM to extract profiles from snippets
    from langchain_core.prompts import ChatPromptTemplate
    llm = get_llm(model_override="gpt-4o-mini")

    context = "\n\n".join(
        f"URL: {s['url']}\nSnippet: {s['content']}"
        for s in all_snippets
    )

    prompt = (
        "Extract LinkedIn profile information from the following search results.\n"
        f"Target persona: {persona}\n"
        f"Target product: {state.get('target_product', '')}\n"
        "For each result, extract: name, job title, company, location, and profile URL.\n"
        "If a field is not available, leave it empty.\n"
        "Return ALL results, do not skip any.\n"
        "Return as a JSON object with a 'profiles' array.\n"
        "CRITICAL: Never invent data. Only extract what is explicitly present in the snippets.\n\n"
        f"Results:\n{context}"
    )

    try:
        extraction = _invoke_structured(llm, prompt, ExtractedLinkedInProfiles)
        logger.info(f"LinkedIn searcher extracted {len(extraction.profiles)} profiles")
        return {"linkedin_profiles": extraction.profiles}
    except Exception as e:
        logger.error(f"LinkedIn profile extraction failed: {e}")
        # Fallback: return raw snippets as basic profiles
        fallback = []
        for s in all_snippets[:20]:
            fallback.append(LinkedInProfile(
                profile_url=s["url"],
                snippet=s["content"][:300],
            ))
        return {"linkedin_profiles": fallback}


def gdrive_sync_node(state: GraphState):
    """
    Syncs all newly saved leads to their corresponding Google Drive CSV
    (one CSV per persona type). Creates the CSV if it doesn't exist yet.
    """
    logger.info("--- GDRIVE SYNC NODE ---")
    saved_leads = state.get("saved_leads", [])
    if not saved_leads:
        logger.info("No new leads to sync to Google Drive.")
        return {}

    try:
        from gdrive_manager import sync_leads_to_drive as _gdrive_sync
        total = _gdrive_sync(saved_leads)
        if total:
            logger.info(f"Google Drive sync complete: {total} leads written.")
        else:
            logger.info("Google Drive sync: no new rows (all duplicates or skipped).")
    except ImportError:
        logger.info("Google Drive dependencies not installed. Skipping GDrive sync.")
    except Exception as e:
        logger.error(f"Google Drive sync failed: {e}")

    return {}


# --- Graph Definition ---
def build_graph() -> StateGraph:
    workflow = StateGraph(GraphState)
    
    workflow.add_node("brainstormer", brainstormer_node)
    workflow.add_node("summarizer", summarizer_node)
    workflow.add_node("searcher", searcher_node)
    workflow.add_node("scraper", scraper_node)
    workflow.add_node("agentic_researcher", agentic_researcher_node)
    workflow.add_node("linkedin_searcher", linkedin_searcher_node)
    workflow.add_node("deduplicator", deduplicator_node)
    workflow.add_node("notifier", notifier_node)
    workflow.add_node("gdrive_sync", gdrive_sync_node)
    
    workflow.set_entry_point("brainstormer")
    
    # Brainstormer starts four parallel paths
    workflow.add_edge("brainstormer", "summarizer")          # Path 1: Fast summarizer (snippets)
    workflow.add_edge("brainstormer", "searcher")             # Path 2: Deep search -> scrape
    workflow.add_edge("brainstormer", "agentic_researcher")  # Path 3: Holistic synthesis
    workflow.add_edge("brainstormer", "linkedin_searcher")   # Path 4: LinkedIn profiles
    
    # Path 2: Search -> Scrape
    workflow.add_edge("searcher", "scraper")
    
    # All four paths converge at deduplicator
    workflow.add_edge("summarizer", "deduplicator")
    workflow.add_edge("scraper", "deduplicator")
    workflow.add_edge("agentic_researcher", "deduplicator")
    workflow.add_edge("linkedin_searcher", "deduplicator")
    
    # Post-processing chain
    workflow.add_edge("deduplicator", "notifier")
    workflow.add_edge("notifier", "gdrive_sync")
    workflow.add_edge("gdrive_sync", END)
    
    return workflow.compile()

# Global graph instance
app_graph = build_graph()
