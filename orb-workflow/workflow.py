import os
import json
import httpx
import asyncio
import base64
from typing import TypedDict, List, Optional, Dict, Any
from uuid import uuid4
import jwt

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from fireworks.client import Fireworks
import openai

# --- Configuration & Setup ---
load_dotenv() # Load environment variables from .env

FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY")
ORB_API_URL = os.getenv("ORB_API_URL", "http://localhost:3201") # Mock Orb API (Still needed by tools)
ARCADE_WORKER_URL = os.getenv("ARCADE_WORKER_URL", "http://127.0.0.1:8002") # Arcade local worker
ARCADE_WORKER_SECRET = os.getenv("ARCADE_WORKER_SECRET")

if not FIREWORKS_API_KEY:
    raise ValueError("FIREWORKS_API_KEY environment variable not set.")
if not ARCADE_WORKER_SECRET:
    print("Warning: ARCADE_WORKER_SECRET not set in .env, worker calls may fail authentication.")

# Use OpenAI's client with Fireworks base URL for better compatibility with document inlining
openai_client = openai.OpenAI(
    base_url="https://api.fireworks.ai/inference/v1",
    api_key=FIREWORKS_API_KEY
)
fireworks_client = Fireworks(api_key=FIREWORKS_API_KEY)
FIREWORKS_MODEL = "accounts/fireworks/models/llama4-maverick-instruct-basic"

# --- Define Workflow State ---
class WorkflowState(TypedDict):
    document_path: str
    document_content: Optional[str]
    extracted_data: Optional[Dict[str, Any]]
    extraction_error: Optional[str]
    customer_id: Optional[str]
    subscription_id: Optional[str]
    configuration_result: Optional[Dict[str, Any]]
    configuration_error: Optional[str]
    error_message: Optional[str]

# --- Document Processing Node (Keep as is) ---
async def document_processor_node(state: WorkflowState) -> Dict[str, Any]:
    print(f"--- Document Processor Node --- Document: {state['document_path']}")
    document_path = state["document_path"]
    extracted_data = None
    extraction_error = None
    document_content = None
    
    try:
        # Check if the file is a text file or binary file
        if document_path.lower().endswith('.txt'):
            # Text file handling
            with open(document_path, 'r', encoding='utf-8') as f:
                document_content = f.read()
            # For text files, we don't need the document inlining, just include content directly
            print(f"Loaded text document: {document_path}")
            
            prompt_messages = [
                {
                    "role": "system",
                    "content": "You are an expert assistant specializing in extracting billing information... Ensure the output is only the JSON object."
                },
                {
                    "role": "user",
                    "content": f"Please extract the billing information from the following document:\n\n{document_content}"
                }
            ]
            
            print(f"Calling Fireworks AI ({FIREWORKS_MODEL}) for extraction...")
            response = fireworks_client.chat.completions.create(
                model=FIREWORKS_MODEL,
                messages=prompt_messages,
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
        else:
            # Binary file handling with document inlining using OpenAI Client for better compatibility
            with open(document_path, 'rb') as f:
                document_bytes = f.read()
            
            # Determine content type based on file extension
            if document_path.lower().endswith('.pdf'):
                content_type = "application/pdf"
            elif document_path.lower().endswith(('.jpg', '.jpeg')):
                content_type = "image/jpeg"
            elif document_path.lower().endswith('.png'):
                content_type = "image/png"
            elif document_path.lower().endswith('.gif'):
                content_type = "image/gif"
            elif document_path.lower().endswith('.tiff'):
                content_type = "image/tiff"
            else:
                content_type = "application/octet-stream"
            
            # Base64 encode the document
            document_content = base64.b64encode(document_bytes).decode('utf-8')
            print(f"Loaded binary document ({content_type}): {document_path}")
            
            # Create inline URL with transform parameter for document inlining
            inline_url = f"data:{content_type};base64,{document_content}#transform=inline"
            
            print(f"Calling Fireworks AI ({FIREWORKS_MODEL}) for extraction with document inlining...")
            response = openai_client.chat.completions.create(
                model=FIREWORKS_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert assistant specializing in extracting billing information from documents. Extract customer name, email/contact, subscription/plan type, number of seats/users, and any addons. Return the information in a JSON format."
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": inline_url
                                }
                            },
                            {
                                "type": "text",
                                "text": "Extract the billing information from this document and return it as a JSON object with keys such as customer/company name, email/contact, subscription/plan, seats/users, and addons if present."
                            }
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
        raw_json = response.choices[0].message.content
        print(f"Raw JSON response from Fireworks: {raw_json}")
        if raw_json:
            extracted_data = json.loads(raw_json)
            print(f"Extracted Data (Actual): {json.dumps(extracted_data, indent=2)}")
        else:
             extraction_error = "Fireworks AI returned empty content."
    except Exception as e:
        print(f"Error during document processing: {e}")
        import traceback
        traceback.print_exc()
        extraction_error = str(e)
    
    return {
        "document_content": "[content not stored in state]",
        "extracted_data": extracted_data,
        "extraction_error": extraction_error
    }

# --- Re-add Arcade Worker Helper (using /worker/tools/invoke) --- 
async def _call_arcade_worker(tool_name: str, args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Helper function to call the Arcade worker's /worker/tools/invoke endpoint with JWT auth."""
    if not ARCADE_WORKER_SECRET:
        raise ValueError("ARCADE_WORKER_SECRET is not set, cannot generate JWT.")

    # Prepare JWT payload
    jwt_payload = {
        'user': user_id, 
        'aud': 'worker', 
        'ver': '1'
    }
    encoded_jwt = jwt.encode(jwt_payload, ARCADE_WORKER_SECRET, algorithm='HS256')
    print(f"Generated JWT for user {user_id}")

    # Prepare request payload for the worker endpoint
    # Match the structure that worked in test_arcade_worker.py
    worker_payload = {
        "tool": {
            "toolkit": "OrbToolkit",  # Use PascalCase toolkit name as registered by worker
            "name": tool_name         # PascalCase tool name will be used in billing_configurator_node
        },
        "inputs": args,               # Change from "args" to "inputs" based on successful test
        "user_id": user_id 
    }
    print(f"--> Calling Arcade Worker ({ARCADE_WORKER_URL}) endpoint: /worker/tools/invoke")
    print(f"    Tool: {tool_name}, Args: {args}, UserID: {user_id}")
    async with httpx.AsyncClient(base_url=ARCADE_WORKER_URL, timeout=30.0) as client:
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {encoded_jwt}"
            }
            print("    (Including JWT Authorization header)")
            
            response = await client.post("/worker/tools/invoke", json=worker_payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            print(f"<-- Received from Arcade worker: {json.dumps(result)}")
            if isinstance(result, dict) and result.get("error"):
                raise Exception(f"Tool execution failed: {result.get('details', result['error'])}")
            return result 
        except httpx.HTTPStatusError as e:
            error_text = e.response.text
            print(f"HTTP error calling Arcade worker: {e.response.status_code} - {error_text}")
            if e.response.status_code in [401, 403]:
                print("Authorization error (401/403). Check ARCADE_WORKER_SECRET and JWT claims.")
            raise Exception(f"Arcade Worker API Error {e.response.status_code}: {error_text}") from e
        except httpx.RequestError as e:
            print(f"Request error calling Arcade worker: {e}")
            raise Exception(f"Arcade Worker Request Error: {e}") from e
        except Exception as e:
            print(f"An unexpected error occurred calling Arcade worker: {e}")
            raise

# --- Billing Configurator Node (Using Direct Worker Call) ---
async def billing_configurator_node(state: WorkflowState) -> Dict[str, Any]:
    """Node responsible for configuring billing via direct calls to the Arcade worker."""
    print("--- Billing Configurator Node --- Calling Worker Directly (with JWT) --- ")
    extracted_data = state.get("extracted_data")
    config_result = None
    config_error = None
    customer_id = None
    subscription_id = None
    user_id_for_arcade = "workflow_system@example.com" # Define user_id for tool call

    if not extracted_data:
        print("Skipping configuration, no extracted data.")
        config_error = "No data extracted from document."
        return {
            "customer_id": None, "subscription_id": None,
            "configuration_result": None, "configuration_error": config_error
        }

    try:
        print("Validating extracted data...")
        # --- Case-Insensitive Flexible Data Access --- 
        # Create a lowercased key dictionary for easier checking
        data_lower = {k.lower(): v for k, v in extracted_data.items()}

        customer_name = (
            data_lower.get("customer_name") or 
            data_lower.get("customername") or # Handle potential no-space version
            data_lower.get("company") or 
            data_lower.get("customer")
        )
        customer_email = (
            data_lower.get("customer_email") or 
            data_lower.get("customeremail") or 
            data_lower.get("contact_email") or # Added underscore version
            data_lower.get("contact email") or 
            data_lower.get("contactemail") or
            data_lower.get("email")
        )
        plan_type = (
            data_lower.get("plan_type") or 
            data_lower.get("subscriptionplan") or 
            data_lower.get("subscription plan") or # Handle space
            data_lower.get("subscription_plan_type") or
            data_lower.get("plan") or
            data_lower.get("subscription")
        )
        user_count = (
            data_lower.get("user_count") or 
            data_lower.get("numusers") or 
            data_lower.get("number_of_users") or 
            data_lower.get("seats") or
            data_lower.get("users") or
            1
        )
        addons = data_lower.get("addons", [])

        # Validation remains the same, checks the variables derived above
        if not all([customer_name, customer_email, plan_type]):
             missing = []
             if not customer_name: missing.append("customer name")
             if not customer_email: missing.append("customer email")
             if not plan_type: missing.append("plan type")
             # Update error message slightly for clarity
             raise ValueError(f"Missing required fields (checked variations): {', '.join(missing)}. Extracted keys: {list(extracted_data.keys())}")

        print("Mapping plan type...")
        plan_map = {
            "basic": "plan_basic_monthly", 
            "basic plan": "plan_basic_monthly",
            "pro": "plan_pro_monthly",
            "pro plan": "plan_pro_monthly", 
            "enterprise": "plan_enterprise_yearly", 
            "enterprise plan": "plan_enterprise_yearly"
        }
        plan_id = plan_map.get(str(plan_type).lower().strip()) 
        if not plan_id:
            raise ValueError(f"Could not map plan type: '{plan_type}'")
        try: user_count_int = int(user_count)
        except (ValueError, TypeError): user_count_int = 1

        # --- Call Tools via Worker --- 
        # 1. Create Customer
        tool_name_customer = "CreateCustomer" # Use PascalCase name as registered by worker
        customer_args = {"name": customer_name, "email": customer_email}
        customer_data = await _call_arcade_worker(tool_name_customer, customer_args, user_id_for_arcade)
        # Note: Worker returns nested response with output.value containing the actual tool result
        if not isinstance(customer_data, dict) or not customer_data.get("success"):
             raise Exception(f"CreateCustomer tool failed: {customer_data}")
        
        # Extract customer ID from the nested structure
        if "output" in customer_data and "value" in customer_data["output"]:
            customer_value = customer_data["output"]["value"]
            customer_id = customer_value.get("id")
        else:
            print(f"Unexpected response structure: {json.dumps(customer_data)}")
            raise ValueError("Cannot find output.value in the customer response. Got: " + json.dumps(customer_data))
            
        if not customer_id:
            raise ValueError("Failed to get customer ID from tool response.")
        print(f"Customer created via Worker: {customer_id}")

        # 2. Create Subscription
        tool_name_sub = "CreateSubscription" # Use PascalCase name as registered by worker
        subscription_args = {"customer_id": customer_id, "plan_id": plan_id, "user_count": user_count_int, "addons": addons or []}
        subscription_data = await _call_arcade_worker(tool_name_sub, subscription_args, user_id_for_arcade)
        
        # Extract subscription ID from the nested structure
        if not isinstance(subscription_data, dict) or not subscription_data.get("success"):
             raise Exception(f"CreateSubscription tool failed: {subscription_data}")
             
        # Extract subscription ID from the nested structure
        if "output" in subscription_data and "value" in subscription_data["output"]:
            subscription_value = subscription_data["output"]["value"]
            subscription_id = subscription_value.get("id")
        else:
            print(f"Unexpected response structure: {json.dumps(subscription_data)}")
            raise ValueError("Cannot find output.value in the subscription response")
            
        if not subscription_id:
            raise ValueError("Failed to get subscription ID from tool response.")
        print(f"Subscription created via Worker: {subscription_id}")

        config_result = {
            "message": "Configuration successful via Worker", 
            "customer": customer_data["output"]["value"], 
            "subscription": subscription_data["output"]["value"]
        }

    except Exception as e:
        print(f"Error during billing configuration (Worker Call): {e}")
        config_error = str(e)

    return {
        "customer_id": customer_id, "subscription_id": subscription_id,
        "configuration_result": config_result, "configuration_error": config_error
    }

# --- Define Graph (Keep as is) ---
workflow_builder = StateGraph(WorkflowState)
workflow_builder.add_node("document_processor", document_processor_node)
workflow_builder.add_node("billing_configurator", billing_configurator_node)
workflow_builder.set_entry_point("document_processor")
workflow_builder.add_edge("document_processor", "billing_configurator")
workflow_builder.add_edge("billing_configurator", END)
app = workflow_builder.compile()

# --- Graph Visualization (Keep as is) ---
try:
    from IPython.display import Image, display
    graph_png = app.get_graph().draw_png()
    with open("orb_workflow_graph.png", "wb") as f:
        f.write(graph_png)
    print("Workflow graph saved to orb_workflow_graph.png")
except ImportError:
    print("Could not generate graph visualization...")

# --- Main Execution Block (Keep as is) ---
if __name__ == "__main__":
    # ... (Existing main function to find files and run workflow) ...
    async def run_workflow_for_file(file_path):
        # ... (calls app.ainvoke) ...
        initial_input = {"document_path": file_path}
        config = {"recursion_limit": 10}
        print(f"\n--- Running workflow for: {file_path} ---")
        try:
            final_state = await app.ainvoke(initial_input, config=config)
            print(f"\n--- Workflow finished for: {file_path} ---")
            print("\nFinal State:")
            print(json.dumps(final_state, indent=2, default=str))
        except Exception as e:
            print(f"\n--- Workflow FAILED for: {file_path} --- Error: {e}")

    async def main():
        # Look for documents in the documents directory
        docs_dir = "documents"
        if not os.path.exists(docs_dir):
            print(f"Error: Directory '{docs_dir}' not found.")
            return
            
        # Create a sample document if none exists
        dummy_file = os.path.join(docs_dir, "sample_invoice.txt")
        if not os.path.exists(dummy_file):
            f=open(dummy_file, "w")
            f.write("dummy")
            f.close()
            
        # Find all supported document files (.txt, .pdf, .jpg, .jpeg, .png, .gif, .tiff)
        supported_extensions = ('.txt', '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.tiff')
        files_to_process = [
            os.path.join(docs_dir, f) for f in os.listdir(docs_dir) 
            if os.path.isfile(os.path.join(docs_dir, f)) and f.lower().endswith(supported_extensions)
        ]
        
        if not files_to_process:
            print(f"No supported documents found in '{docs_dir}'.")
            print(f"Supported formats: {', '.join(supported_extensions)}")
            return
            
        print(f"Found documents to process: {files_to_process}")
        await asyncio.gather(*(run_workflow_for_file(f) for f in files_to_process))

    asyncio.run(main())
