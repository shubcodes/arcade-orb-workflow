import httpx
import asyncio
import os
import json
import jwt # Need jwt for auth token generation
from dotenv import load_dotenv

# Configuration (Should match workflow.py and your running worker)
load_dotenv()
ARCADE_WORKER_URL = os.getenv("ARCADE_WORKER_URL", "http://127.0.0.1:8002")
ARCADE_WORKER_SECRET = os.getenv("ARCADE_WORKER_SECRET") # Used for JWT signing

# Basic check for the secret
if not ARCADE_WORKER_SECRET:
    print("Error: ARCADE_WORKER_SECRET environment variable not set. Needed for JWT signing.")
    exit(1)

async def test_worker_tool(toolkit_id: str, tool_name: str, args: dict):
    """Calls a specific tool via the Arcade worker's /worker/tools/invoke endpoint.
    Sends the payload with the 'tool' field as an object {toolkit: ..., name: ...}.
    """
    user_id = "test-user@example.com" # User for JWT and payload
    
    # --- Generate JWT --- 
    jwt_payload = {'user': user_id, 'aud': 'worker', 'ver': '1'}
    try:
        encoded_jwt = jwt.encode(jwt_payload, ARCADE_WORKER_SECRET, algorithm='HS256')
        print(f"\n--- Testing Worker --- Tool: {toolkit_id}.{tool_name}")
        print(f"   (Generated JWT for user {user_id})")
    except Exception as e:
        print(f"\n--- Test for {toolkit_id}.{tool_name} FAILED (JWT Error) --- Error: {e}")
        return None

    # --- Prepare Payload (Trying different structure) ---
    payload = {
        "tool": {
            "toolkit": toolkit_id,
            "name": tool_name 
        },
        "inputs": args,  # Changed from "args" to "inputs" to match Arcade's expected format
        "user_id": user_id
    }
    print(f"Calling: {ARCADE_WORKER_URL}/worker/tools/invoke")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    async with httpx.AsyncClient(base_url=ARCADE_WORKER_URL, timeout=30.0) as client:
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {encoded_jwt}"
            }
            print("-> Sending request with JWT Authorization header")
            response = await client.post("/worker/tools/invoke", json=payload, headers=headers)
            response.raise_for_status() # Raise error for 4xx/5xx
            result = response.json()
            print("\nWorker Response:")
            print(json.dumps(result, indent=2))
            print(f"--- Test for {toolkit_id}.{tool_name} SUCCEEDED --- ")
            return result
        except Exception as e:
            print(f"\n--- Test for {toolkit_id}.{tool_name} FAILED --- Error: {e}")
            if isinstance(e, httpx.HTTPStatusError):
                print(f"Response Status: {e.response.status_code}")
                print(f"Response Body: {e.response.text}")
            return None

async def main():
    print("Starting Arcade Worker Test...")
    print("Ensure the Mock Orb API (port 3201) and Arcade Worker (port 8002 with secret 'dev') are running.")

    # Test 1: Create a customer using the correct payload structure
    # AND the correct PascalCase names for both toolkit AND tool from /worker/tools
    await test_worker_tool(
        toolkit_id="OrbToolkit", # Match toolkit name from GET /worker/tools
        tool_name="CreateCustomer", # Match tool name from GET /worker/tools
        args={"name": "Worker Test Correct Payload", "email": "workertest_correct@example.com"}
    )

    # Test 2: Create a customer (with prefix, just in case)
    # await test_worker_tool(
    #     tool_name="arcade_orb_toolkit.create_customer",
    #     args={"name": "Worker Test Cust Prefixed", "email": "workertest_prefix@example.com"}
    # )

    # Add more tests here if needed (e.g., for CreateSubscription)

    print("\nArcade Worker Test Finished.")

if __name__ == "__main__":
    asyncio.run(main()) 