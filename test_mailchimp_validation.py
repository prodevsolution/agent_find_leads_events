import os
import hashlib
import logging
from mailchimp3 import MailChimp
from dotenv import load_dotenv

# Load env vars from .env if it exists
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAILCHIMP_API_KEY = os.getenv('MAILCHIMP_API_KEY')
MAILCHIMP_LIST_ID = os.getenv('MAILCHIMP_LIST_ID')

def test_sync(email, country_code):
    if not MAILCHIMP_API_KEY or not MAILCHIMP_LIST_ID:
        print("❌ Missing Mailchimp API Key or List ID in environment.")
        return

    print(f"Testing sync for {email} with country='{country_code}'...")
    client = MailChimp(mc_api=MAILCHIMP_API_KEY, mc_user='anystring')
    subscriber_hash = hashlib.md5(email.lower().encode()).hexdigest()
    
    data = {
        'email_address': email,
        'status_if_new': 'subscribed',
        'status': 'subscribed',
        'merge_fields': {
            'FNAME': 'Test',
            'LNAME': 'User',
            'ADDRESS': {
                'addr1': 'https://example.com/test-event',
                'city': '', 
                'state': '',
                'zip': '',
                'country': country_code
            }
        }
    }
    
    try:
        response = client.lists.members.create_or_update(
            list_id=MAILCHIMP_LIST_ID, 
            subscriber_hash=subscriber_hash, 
            data=data
        )
        print(f"✅ Success! Response status: {response.get('status')}")
    except Exception as e:
        print(f"❌ Failed! Error: {e}")

if __name__ == "__main__":
    test_sync("test_validate_empty@example.com", "")
    test_sync("test_validate_us@example.com", "US")
