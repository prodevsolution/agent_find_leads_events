import pydantic
from pydantic import BaseModel, Field
from typing import List, Optional

# Re-defining the modified LeadData for standalone test
class LeadData(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    
    @pydantic.model_validator(mode='after')
    def check_contact_info(self) -> 'LeadData':
        if not self.email and not self.phone:
            raise ValueError("Lead must have at least an email or a phone number.")
        return self

print("--- Testing LeadData Constraints ---")

# 1. Test Valid (Email only)
try:
    l1 = LeadData(email="test@example.com")
    print("SUCCESS: Lead with email only accepted.")
except Exception as e:
    print(f"FAILURE: Lead with email only rejected: {e}")

# 2. Test Valid (Phone only)
try:
    l2 = LeadData(phone="1234567890")
    print("SUCCESS: Lead with phone only accepted.")
except Exception as e:
    print(f"FAILURE: Lead with phone only rejected: {e}")

# 3. Test Invalid (Neither)
try:
    l3 = LeadData(name="No Contact")
    print("FAILURE: Lead with no contact information was accepted.")
except ValueError as e:
    print(f"SUCCESS: Lead with no contact information rejected as expected: {e}")

# 4. Test Valid (Both)
try:
    l4 = LeadData(email="both@example.com", phone="9876543210")
    print("SUCCESS: Lead with both accepted.")
except Exception as e:
    print(f"FAILURE: Lead with both rejected: {e}")
