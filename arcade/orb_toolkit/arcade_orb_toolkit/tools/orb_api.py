import os
import httpx
import json # Added json
from typing import Annotated, List, Optional, Dict, Any
from pydantic import BaseModel, Field
from arcade.sdk import tool

# Configuration
# Use environment variable for the Orb API URL, defaulting to the new port
ORB_API_URL = os.getenv("ORB_API_URL", "http://localhost:3201")
HTTP_TIMEOUT = 10.0  # seconds

# --- Pydantic Models for API Data ---
class CustomerAddress(BaseModel):
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None

class Customer(BaseModel):
    id: str
    name: str
    email: str
    address: Optional[CustomerAddress] = None # Address is optional in creation
    created_at: str

class Subscription(BaseModel):
    id: str
    customer_id: str
    plan_id: str
    user_count: int
    addons: List[str]
    status: str
    created_at: str

# --- HTTP Client Setup ---
async def _make_orb_request(
    method: str,
    endpoint: str,
    json_data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Helper function to make requests to the Mock Orb API."""
    # Use the ORB_API_URL from environment/default
    async with httpx.AsyncClient(base_url=ORB_API_URL, timeout=HTTP_TIMEOUT) as client:
        try:
            print(f"Making {method} request to {client.base_url}{endpoint} with data: {json_data}")
            headers = {"Content-Type": "application/json"} # Explicitly set header
            response = await client.request(method, endpoint, json=json_data, params=params, headers=headers)

            # Check for non-JSON success responses (like 204 No Content)
            if response.status_code == 204:
                return {"success": True, "status_code": 204}

            # Attempt to parse JSON, handle potential errors
            try:
                response_json = response.json()
            except json.JSONDecodeError:
                print(f"Warning: Non-JSON response received ({response.status_code}). Body: {response.text[:100]}...")
                response_json = {"error": "Invalid response format", "details": response.text}
                # Still raise for status below if it's an error code

            # Raise error for bad status codes AFTER trying to parse body
            response.raise_for_status() # Raise HTTPStatusError for 4xx/5xx responses

            print(f"Received {response.status_code} from {response.url}")
            return response_json
        except httpx.HTTPStatusError as e:
            print(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
            # Try to parse error response body, default to raw text
            error_details = e.response.text
            try:
                error_json = e.response.json()
                error_details = error_json # Use parsed JSON if available
            except json.JSONDecodeError:
                pass # Keep raw text if not JSON
            return {"error": f"API Error: {e.response.status_code}", "details": error_details}
        except httpx.RequestError as e:
            print(f"Request error occurred: {e}")
            return {"error": "Request Error", "details": str(e)}
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            import traceback
            traceback.print_exc()
            return {"error": "Unexpected Error", "details": str(e)}

# --- ARCADE Tool Definitions --- 
@tool
async def create_customer(
    name: Annotated[str, "The full name of the customer."],
    email: Annotated[str, "The primary email address for the customer."],
    address_street: Annotated[Optional[str], "Street address line."] = None,
    address_city: Annotated[Optional[str], "City name."] = None,
    address_state: Annotated[Optional[str], "State or province."] = None,
    address_zip_code: Annotated[Optional[str], "Postal or ZIP code."] = None,
    address_country: Annotated[Optional[str], "Country."] = None,
) -> Annotated[Dict[str, Any], "Result of the customer creation, containing customer details or an error."]:
    """Creates a new customer record in the Orb billing system."""
    address_dict = {
        "street": address_street,
        "city": address_city,
        "state": address_state,
        "zip_code": address_zip_code,
        "country": address_country,
    }
    # Only include address field if at least one subfield is provided
    customer_data = {"name": name, "email": email}
    if any(v is not None for v in address_dict.values()):
         customer_data["address"] = {k: v for k, v in address_dict.items() if v is not None}

    result = await _make_orb_request("POST", "/customers", json_data=customer_data)
    return result

@tool
async def get_customer(
    customer_id: Annotated[str, "The unique identifier of the customer to retrieve."]
) -> Annotated[Dict[str, Any], "Customer details or an error message if not found."]:
    """Retrieves the details for a specific customer by their ID."""
    result = await _make_orb_request("GET", f"/customers/{customer_id}")
    return result

@tool
async def create_subscription(
    customer_id: Annotated[str, "The ID of the customer to create the subscription for."],
    plan_id: Annotated[str, "The ID of the plan to subscribe the customer to (e.g., 'plan_basic_monthly', 'plan_pro_monthly')."],
    user_count: Annotated[int, "The number of users or seats for this subscription."] = 1,
    addons: Annotated[Optional[List[str]], "A list of addon IDs to include with the subscription."] = None
) -> Annotated[Dict[str, Any], "Result of the subscription creation, containing subscription details or an error."]:
    """Creates a new subscription for a customer on a specific plan."""
    subscription_data = {
        "customer_id": customer_id,
        "plan_id": plan_id,
        "user_count": user_count,
        "addons": addons or []
    }
    result = await _make_orb_request("POST", "/subscriptions", json_data=subscription_data)
    return result

@tool
async def get_subscription(
    subscription_id: Annotated[str, "The unique identifier of the subscription to retrieve."]
) -> Annotated[Dict[str, Any], "Subscription details or an error message if not found."]:
    """Retrieves the details for a specific subscription by its ID."""
    result = await _make_orb_request("GET", f"/subscriptions/{subscription_id}")
    return result 