import logging
import json
from unittest.mock import MagicMock, patch
import sys
import os

# Add current directory to path so we can import tools and config
sys.path.append(os.path.abspath(os.curdir))

# Mock Mailchimp library before importing tools
sys.modules['mailchimp3'] = MagicMock()

import tools

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_add_lead_to_mailchimp_payload():
    # Setup mocks
    with patch('tools.MailChimp') as MockMailChimp:
        mock_client = MockMailChimp.return_value
        
        test_email = "test@example.com"
        test_fname = "John"
        test_lname = "Doe"
        test_url = "https://example.com/event"
        
        # Test call
        success = tools.add_lead_to_mailchimp(test_email, test_fname, test_lname, test_url)
        
        # Verify call to create_or_update
        # Get the 'data' argument from the call
        call_args = mock_client.lists.members.create_or_update.call_args
        if not call_args:
            print("❌ FAILURE: create_or_update was not called")
            return
            
        data = call_args.kwargs['data']
        print("\n--- Mailchimp Payload Structure ---")
        print(json.dumps(data, indent=2))
        
        # Assertions
        assert data['merge_fields']['ADDRESS']['addr1'] == test_url
        assert data['merge_fields']['ADDRESS']['city'] == ''
        assert data['merge_fields']['ADDRESS']['state'] == ''
        assert data['merge_fields']['ADDRESS']['zip'] == ''
        assert data['merge_fields']['ADDRESS']['country'] == ''
        assert data['merge_fields']['FNAME'] == test_fname
        assert data['merge_fields']['LNAME'] == test_lname
        
        print("\n✅ SUCCESS: Payload structure is correct and includes the URL in the Address field.")

if __name__ == "__main__":
    test_add_lead_to_mailchimp_payload()
