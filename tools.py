import os
import re
import smtplib
from email.message import EmailMessage
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from dateutil import parser as date_parser
import logging

from mailchimp3 import MailChimp
from twilio.rest import Client
from langchain_core.tools import tool

from config import (
    TAVILY_API_KEY, MAILCHIMP_API_KEY, MAILCHIMP_SERVER_PREFIX, MAILCHIMP_LIST_ID,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, TO_PHONE_NUMBER,
    SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS, TO_EMAIL
)

logger = logging.getLogger(__name__)

# --- Search Tool (Time-Aware) ---
@tool
def search_events(query: str, start_date: str = None, end_date: str = None) -> list[dict]:
    """
    Searches for events based on a query. Incorporates time-awareness.
    start_date and end_date should be in ISO 8601 format if provided.
    Returns a list of dictionaries with 'url', 'title', 'content'.
    """
    if not TAVILY_API_KEY:
        logger.error("TAVILY_API_KEY not found.")
        return []
    
    # Enhance query with date context if helpful for the search engine
    time_context = ""
    if start_date:
        time_context += f" starting from {start_date}"
    if end_date and end_date not in ("None", "9999-12-31"):
        time_context += f" until {end_date}"
        
    full_query = f"{query}{time_context}"
    logger.info(f"Executing search: {full_query}")

    # Use Tavily API REST endpoint directly for simplicity and control
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": full_query,
        "search_depth": "basic",
        "include_answer": False,
        "include_images": False,
        "include_raw_content": False,
        "max_results": 10
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return [{"url": res["url"], "title": res["title"], "content": res["content"]} for res in data.get("results", [])]
    except Exception as e:
        logger.error(f"Error during Tavily search: {e}")
        return []


# --- Scraper Tool ---
def extract_emails(text: str) -> list[str]:
    """Extracts unique emails from text using regex."""
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    return list(set(re.findall(email_pattern, text)))

def extract_phones(text: str) -> list[str]:
    """Extracts potential phone numbers from text using regex."""
    # This is a very basic phone regex, can be improved.
    phone_pattern = r'\+?1?\s*\(?-*\.*(\d{3})\)?\.*-*\s*(\d{3})\.*-*\s*(\d{4})'
    matches = re.findall(phone_pattern, text)
    phones = ["".join(match) for match in matches]
    return list(set(phones))

def extract_date_from_text(text: str) -> datetime:
    """Attempts to find and parse a date from the given text snippet."""
    # For a real production system, consider using an LLM to extract the exact date
    # from the raw text instead of relying strictly on heuristics.
    # Here, we will just use dateutil on promising looking strings or return None.
    # We will rely on the Scraper Node (Agent) to use OpenAI to extract the date from the text instead.
    pass # This will be handled by the LLM in the chain

@tool
def scrape_event_page(url: str) -> dict:
    """
    Scrapes an event URL to extract text content, emails, and phones.
    Returns a dictionary with 'url', 'content', 'emails', 'phones'.
    """
    logger.info(f"Scraping URL: {url}")
    try:
        # Use a more comprehensive set of headers to mimic a real browser and avoid 403 blocks
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.extract()
            
        text = soup.get_text(separator=' ', strip=True)
        emails = extract_emails(text)
        phones = extract_phones(text)
        
        # Limit text content returned to context window size (e.g. first 10,000 chars)
        content = text[:10000] 
        
        return {
            "url": url,
            "content": content,
            "emails": emails,
            "phones": phones,
            "title": soup.title.string if soup.title else ""
        }
    except Exception as e:
        logger.error(f"Failed to scrape {url}: {e}")
        return {"url": url, "content": "", "emails": [], "phones": [], "title": ""}


# --- Mailchimp Tool ---
def add_lead_to_mailchimp(email: str, first_name: str = "", last_name: str = "", event_url: str = "") -> bool:
    """
    Adds a lead to Mailchimp. In a real scenario, we might trigger a specific journey
    which contains the 'Eventra' template.
    Returns True if successfully added.
    """
    if not all([MAILCHIMP_API_KEY, MAILCHIMP_SERVER_PREFIX, MAILCHIMP_LIST_ID]):
        logger.warning("Mailchimp configuration is incomplete. Skipping Mailchimp integration.")
        return False
        
    try:
        import hashlib
        client = MailChimp(mc_api=MAILCHIMP_API_KEY, mc_user='anystring')
        # Setting server prefix directly is not supported in init of mailchimp3 sometimes, 
        # but depends on key format. Let's construct standard request if library fails.
        # Actually mailchimp3 figures out server from api key usually.
        
        subscriber_hash = hashlib.md5(email.lower().encode()).hexdigest()
        
        data = {
            'email_address': email,
            'status_if_new': 'subscribed',
            'status': 'subscribed',
            'merge_fields': {
                'FNAME': first_name,
                'LNAME': last_name,
            }
        }

        # If we have an event URL, add it to the Address field in Mailchimp
        # We use a safer approach for the ADDRESS field to avoid validation errors
        if event_url:
            data['merge_fields']['ADDRESS'] = {
                'addr1': event_url[:250], # Mailchimp has a limit of approx 255 chars
                'city': 'Remote', 
                'state': 'NA',
                'zip': '00000',
                'country': '' # Empty country often bypasses strict geographic field validation
            }
        
        # Add to list using PUT (create_or_update)
        # 1. 'subscribed' status bypasses double opt-in confirmation emails.
        # 2. Using PUT bypasses the default Mailchimp list Welcome Automation emails.
        # This acts as an "insert or index" operation.
        client.lists.members.create_or_update(
            list_id=MAILCHIMP_LIST_ID, 
            subscriber_hash=subscriber_hash, 
            data=data
        )
        logger.info(f"Successfully added/updated {email} in Mailchimp.")
        return True
    # Mailchimp3 throws generic Exception if it fails
    except Exception as e:
        logger.error(f"Mailchimp sync failed for {email}: {e}")
        return False

# --- Notification Tools ---
def send_whatsapp_notification(message_body: str) -> bool:
    """Sends a WhatsApp message via Twilio."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, TO_PHONE_NUMBER]):
        logger.warning("Twilio config incomplete. Skipping WhatsApp notification.")
        return False
        
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            from_=TWILIO_PHONE_NUMBER,
            body=message_body,
            to=TO_PHONE_NUMBER
        )
        logger.info(f"WhatsApp notification sent. SID: {message.sid}")
        return True
    except Exception as e:
        logger.error(f"Failed to send WhatsApp notification: {e}")
        return False

def send_email_notification(subject: str, message_body: str) -> bool:
    """Sends an email notification via SMTP."""
    if not all([SMTP_SERVER, SMTP_USER, SMTP_PASS, TO_EMAIL]):
        logger.warning("SMTP config incomplete. Skipping Email notification.")
        return False
        
    try:
        msg = EmailMessage()
        msg.set_content(message_body)
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = TO_EMAIL

        with smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT)) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
            
        logger.info(f"Email notification sent to {TO_EMAIL}.")
        return True
    except Exception as e:
        logger.error(f"Failed to send Email notification: {e}")
        return False
