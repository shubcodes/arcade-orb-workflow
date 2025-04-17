#!/usr/bin/env python3
import os
import json
import logging
import httpx
import jwt
from typing import Dict, Any, Optional, Tuple
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
ORB_API_URL = os.getenv("ORB_API_URL", "http://localhost:3201")
ARCADE_WORKER_URL = os.getenv("ARCADE_WORKER_URL", "http://127.0.0.1:8002")
ARCADE_WORKER_SECRET = os.getenv("ARCADE_WORKER_SECRET")

if not ARCADE_WORKER_SECRET:
    logger.warning("ARCADE_WORKER_SECRET not set in .env, worker calls may fail authentication.")

class BillingConfiguratorAgent:
    """Agent that configures billing using Arcade worker tools."""
    
    def __init__(self, user_id="workflow_system@example.com"):
        """Initialize the agent."""
        logger.info("Initializing Billing Configurator Agent")
        self.user_id = user_id
        
        # Plan mapping
        self.plan_map = {
            "basic": "plan_basic_monthly", 
            "basic plan": "plan_basic_monthly",
            "pro": "plan_pro_monthly",
            "pro plan": "plan_pro_monthly", 
            "enterprise": "plan_enterprise_yearly", 
            "enterprise plan": "plan_enterprise_yearly"
        }
    
    async def configure_billing(self, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """Configure billing based on extracted data."""
        logger.info("Configuring billing based on extracted data")
        
        config_result = None
        config_error = None
        customer_id = None
        subscription_id = None
        
        if not extracted_data:
            logger.warning("No extracted data provided.")
            config_error = "No data extracted from document."
            return {
                "customer_id": None,
                "subscription_id": None,
                "configuration_result": None,
                "configuration_error": config_error
            }
        
        try:
            logger.info("Validating extracted data...")
            # Create a lowercased key dictionary for easier checking
            data_lower = {k.lower(): v for k, v in extracted_data.items()}
            
            # Extract the key fields with flexible matching
            customer_name = (
                data_lower.get("customer_name") or 
                data_lower.get("customername") or
                data_lower.get("company") or 
                data_lower.get("customer")
            )
            customer_email = (
                data_lower.get("customer_email") or 
                data_lower.get("customeremail") or 
                data_lower.get("contact_email") or
                data_lower.get("contact email") or 
                data_lower.get("contactemail") or
                data_lower.get("email") or
                data_lower.get("email/contact")
            )
            plan_type = (
                data_lower.get("plan_type") or 
                data_lower.get("subscriptionplan") or 
                data_lower.get("subscription plan") or
                data_lower.get("subscription_plan_type") or
                data_lower.get("subscription/plan_type") or
                data_lower.get("plan") or
                data_lower.get("subscription")
            )
            user_count = (
                data_lower.get("user_count") or 
                data_lower.get("numusers") or 
                data_lower.get("number_of_users") or
                data_lower.get("number_of_seats/users") or
                data_lower.get("seats") or
                data_lower.get("users") or
                1
            )
            addons = data_lower.get("addons", [])
            
            # Validation
            if not all([customer_name, customer_email, plan_type]):
                missing = []
                if not customer_name: missing.append("customer name")
                if not customer_email: missing.append("customer email")
                if not plan_type: missing.append("plan type")
                raise ValueError(f"Missing required fields (checked variations): {', '.join(missing)}. Extracted keys: {list(extracted_data.keys())}")
            
            logger.info("Mapping plan type...")
            plan_id = self.plan_map.get(str(plan_type).lower().strip())
            if not plan_id:
                raise ValueError(f"Could not map plan type: '{plan_type}'")
            
            try:
                user_count_int = int(user_count)
            except (ValueError, TypeError):
                user_count_int = 1
            
            # Call Arcade worker tools
            # 1. Create Customer
            logger.info(f"Creating customer: {customer_name} ({customer_email})")
            customer_args = {"name": customer_name, "email": customer_email}
            customer_data = await self._call_arcade_worker("CreateCustomer", customer_args)
            
            # Extract customer ID from the response
            if not isinstance(customer_data, dict) or not customer_data.get("success"):
                raise Exception(f"CreateCustomer tool failed: {customer_data}")
            
            # Extract customer ID from the nested structure
            if "output" in customer_data and "value" in customer_data["output"]:
                customer_value = customer_data["output"]["value"]
                customer_id = customer_value.get("id")
            else:
                logger.error(f"Unexpected response structure: {json.dumps(customer_data)}")
                raise ValueError("Cannot find output.value in the customer response")
                
            if not customer_id:
                raise ValueError("Failed to get customer ID from tool response.")
            logger.info(f"Customer created: {customer_id}")
            
            # 2. Create Subscription
            logger.info(f"Creating subscription for customer {customer_id}: {plan_id}, {user_count_int} seats")
            subscription_args = {
                "customer_id": customer_id,
                "plan_id": plan_id,
                "user_count": user_count_int,
                "addons": addons or []
            }
            subscription_data = await self._call_arcade_worker("CreateSubscription", subscription_args)
            
            # Extract subscription ID from the response
            if not isinstance(subscription_data, dict) or not subscription_data.get("success"):
                raise Exception(f"CreateSubscription tool failed: {subscription_data}")
                
            # Extract subscription ID from the nested structure
            if "output" in subscription_data and "value" in subscription_data["output"]:
                subscription_value = subscription_data["output"]["value"]
                subscription_id = subscription_value.get("id")
            else:
                logger.error(f"Unexpected response structure: {json.dumps(subscription_data)}")
                raise ValueError("Cannot find output.value in the subscription response")
                
            if not subscription_id:
                raise ValueError("Failed to get subscription ID from tool response.")
            logger.info(f"Subscription created: {subscription_id}")
            
            config_result = {
                "message": "Configuration successful via Arcade Worker",
                "customer": customer_data["output"]["value"],
                "subscription": subscription_data["output"]["value"]
            }
            
        except Exception as e:
            logger.error(f"Error during billing configuration: {e}")
            import traceback
            traceback.print_exc()
            config_error = str(e)
        
        return {
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "configuration_result": config_result,
            "configuration_error": config_error
        }
    
    async def _call_arcade_worker(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Call Arcade worker with the given tool and arguments."""
        if not ARCADE_WORKER_SECRET:
            raise ValueError("ARCADE_WORKER_SECRET is not set, cannot generate JWT.")
        
        # Prepare JWT payload
        jwt_payload = {
            'user': self.user_id,
            'aud': 'worker',
            'ver': '1'
        }
        encoded_jwt = jwt.encode(jwt_payload, ARCADE_WORKER_SECRET, algorithm='HS256')
        logger.info(f"Generated JWT for user {self.user_id}")
        
        # Prepare request payload
        worker_payload = {
            "tool": {
                "toolkit": "OrbToolkit",
                "name": tool_name
            },
            "inputs": args,
            "user_id": self.user_id
        }
        
        logger.info(f"Calling Arcade Worker ({ARCADE_WORKER_URL}) with tool: {tool_name}")
        logger.info(f"Arguments: {args}")
        
        async with httpx.AsyncClient(base_url=ARCADE_WORKER_URL, timeout=30.0) as client:
            try:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {encoded_jwt}"
                }
                
                response = await client.post("/worker/tools/invoke", json=worker_payload, headers=headers)
                response.raise_for_status()
                result = response.json()
                
                logger.info(f"Received from Arcade worker: {json.dumps(result)}")
                
                if isinstance(result, dict) and result.get("error"):
                    raise Exception(f"Tool execution failed: {result.get('details', result['error'])}")
                
                return result
            except httpx.HTTPStatusError as e:
                error_text = e.response.text
                logger.error(f"HTTP error calling Arcade worker: {e.response.status_code} - {error_text}")
                if e.response.status_code in [401, 403]:
                    logger.error("Authorization error (401/403). Check ARCADE_WORKER_SECRET and JWT claims.")
                raise Exception(f"Arcade Worker API Error {e.response.status_code}: {error_text}") from e
            except httpx.RequestError as e:
                logger.error(f"Request error calling Arcade worker: {e}")
                raise Exception(f"Arcade Worker Request Error: {e}") from e
            except Exception as e:
                logger.error(f"An unexpected error occurred calling Arcade worker: {e}")
                raise

    def _get_plan_id(self, plan_name: str) -> Optional[str]:
        # Simple mapping, could be dynamic
        # Normalize plan name input
        plan_name_lower = plan_name.strip().lower() if plan_name else ""

        # Try direct mapping first
        plan_map = {
            "basic": "plan_basic_monthly",
            "pro": "plan_pro_monthly",
            "enterprise": "plan_enterprise_yearly",
            "basic plan": "plan_basic_monthly", # Handle variations
            "pro plan": "plan_pro_monthly",
            "enterprise plan": "plan_enterprise_yearly"
        }
        plan_id = plan_map.get(plan_name_lower)

        # If not found, maybe it's already an ID?
        if not plan_id and plan_name_lower.startswith("plan_"):
            plan_id = plan_name_lower # Assume it's a valid ID

        if not plan_id:
            logger.warning(f"Could not map plan name '{plan_name}' to a known plan ID.")

        return plan_id

    def validate_data(self, extracted_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validates if the essential fields for billing configuration are present."""
        logger.info("Validating extracted data for billing...")
        required_fields = { # Fields absolutely needed to proceed
            "customer_name": ["company", "customer_name", "name"],
            "email": ["email", "contact", "email/contact"],
            "plan_type": ["subscription", "plan", "plan_type", "subscription/plan_type"]
            # 'seats' might be optional depending on the plan
        }
        missing_fields = []
        found_data = {} # Store the found data under canonical keys

        for canonical_field, variations in required_fields.items():
            field_found = False
            for variation in variations:
                if variation in extracted_data and extracted_data[variation] not in [None, "", "N/A", "null"]:
                    found_data[canonical_field] = extracted_data[variation]
                    field_found = True
                    break
            if not field_found:
                missing_fields.append(canonical_field)

        if missing_fields:
            error_msg = f"Missing required fields (checked variations): {', '.join(missing_fields)}. Extracted keys: {list(extracted_data.keys())}"
            logger.warning(f"Validation failed: {error_msg}")
            return False, error_msg

        # Additional check: Ensure plan_type can be mapped
        plan_type_value = found_data.get("plan_type")
        if not self._get_plan_id(plan_type_value):
             error_msg = f"Invalid or unmappable plan_type: '{plan_type_value}'. Expected Basic, Pro, or Enterprise."
             logger.warning(f"Validation failed: {error_msg}")
             return False, error_msg

        logger.info("Billing data validation successful.")
        return True, None

# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def main():
        configurator = BillingConfiguratorAgent()
        
        # Example extracted data
        example_data = {
            "company": "Test Company",
            "contact_email": "test@example.com",
            "subscription": "Basic Plan",
            "seats": 10,
            "addons": ["premium_support"]
        }
        
        result = await configurator.configure_billing(example_data)
        print("Configuration Result:", json.dumps(result, indent=2))
    
    asyncio.run(main()) 