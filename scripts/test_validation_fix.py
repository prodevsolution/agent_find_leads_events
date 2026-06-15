import sys
import os

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from graph import LeadData, ExtractedLeads
from database import Lead, repository
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def test_leaddata_relaxation():
    print("--- Testing LeadData Relaxation ---")
    try:
        # This used to fail due to the validator requiring email or phone
        lead = LeadData(name="Partial Lead")
        print("SUCCESS: LeadData can now be instantiated without email/phone (for LLM extraction phase).")
    except Exception as e:
        print(f"FAILURE: LeadData still requiring contact info: {e}")

def test_db_nullability():
    print("\n--- Testing Database Nullability ---")
    # We use the real repository which points to the real DB (leads.db by default in config)
    # BE CAREFUL: This might add a test lead to the real DB. 
    # For a safe test, we could point to a temp DB.
    
    test_db = "sqlite:///test_leads.db"
    from database import LeadRepository
    temp_repo = LeadRepository(db_url=test_db)
    
    lead_data = {
        "name": "Phone Only Lead",
        "phone": "555-1234",
        "event_name": "Test Event",
        "status": "new"
    }
    
    try:
        db_lead, is_new = temp_repo.add_lead(lead_data)
        if db_lead and db_lead.phone == "555-1234" and db_lead.email is None:
            print("SUCCESS: Database successfully saved a lead without an email.")
        else:
            print(f"FAILURE: Saved lead didn't match or failed: {db_lead}")
            
        # Test deduplication by phone
        db_lead2, is_new2 = temp_repo.add_lead(lead_data)
        if not is_new2:
            print("SUCCESS: Deduplication by phone worked for phone-only leads.")
        else:
            print("FAILURE: Deduplication by phone failed (lead was added twice).")
            
    except Exception as e:
        print(f"FAILURE: Database operation failed: {e}")
    finally:
        # Dispose the engine to release the file lock
        temp_repo.engine.dispose()
        # Cleanup temp DB
        if os.path.exists("test_leads.db"):
            try:
                os.remove("test_leads.db")
            except Exception as e:
                print(f"Cleanup error (locked): {e}")

if __name__ == "__main__":
    test_leaddata_relaxation()
    test_db_nullability()
