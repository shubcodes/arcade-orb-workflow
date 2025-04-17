#!/usr/bin/env python3
import os
import json
import asyncio
import logging
from dotenv import load_dotenv
from arcadepy import Arcade

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
ARCADE_API_KEY = os.getenv("ARCADE_API_KEY")
TEST_EMAIL = os.getenv("TEST_EMAIL_ADDRESS")

async def test_arcade_gmail():
    """Test the Arcade Gmail functionality directly."""
    if not ARCADE_API_KEY:
        print("❌ ARCADE_API_KEY is not set in your .env file")
        return
    
    if not TEST_EMAIL:
        print("❌ TEST_EMAIL_ADDRESS is not set in your .env file")
        return
    
    print(f"\n=== Testing Arcade Gmail API with: {TEST_EMAIL} ===\n")
    
    # Initialize Arcade client
    client = Arcade(api_key=ARCADE_API_KEY)
    
    try:
        # List Emails
        tool_name = "Google.ListEmails"
        print(f"\n--- Authorizing {tool_name} ---\n")
        
        auth_response = client.tools.authorize(
            tool_name=tool_name,
            user_id=TEST_EMAIL
        )
        
        if auth_response.status != "completed":
            print(f"Please authorize the application by visiting this URL:")
            print(f"\n{auth_response.url}\n")
            print("Waiting for authorization to complete...")
            
            client.auth.wait_for_completion(auth_response)
            print("✅ Authorization successful!")
        else:
            print("✅ Already authorized!")
        
        # Execute the ListEmails tool
        print("\n--- Listing Recent Emails ---\n")
        
        tool_input = {"n_emails": 5}
        
        response = client.tools.execute(
            tool_name=tool_name,
            input=tool_input,
            user_id=TEST_EMAIL
        )
        
        if "emails" in response and response["emails"]:
            print(f"✅ Successfully retrieved {len(response['emails'])} emails")
            
            # Print summary of emails
            for i, email in enumerate(response["emails"], 1):
                print(f"\nEmail {i}:")
                print(f"  Subject: {email.get('subject', 'No subject')}")
                print(f"  From: {email.get('sender', 'Unknown sender')}")
                print(f"  Date: {email.get('date', 'Unknown date')}")
                print(f"  ID: {email.get('id', 'No ID')}")
                print(f"  Thread ID: {email.get('threadId', 'No Thread ID')}")
        else:
            print("❌ No emails found or error retrieving emails")
            print(response)
        
        # Try to get thread details if we found emails
        if "emails" in response and response["emails"]:
            first_email = response["emails"][0]
            thread_id = first_email.get("threadId")
            
            if thread_id:
                # Get thread
                thread_tool = "Google.GetThread"
                print(f"\n--- Authorizing {thread_tool} ---\n")
                
                thread_auth = client.tools.authorize(
                    tool_name=thread_tool,
                    user_id=TEST_EMAIL
                )
                
                if thread_auth.status != "completed":
                    print(f"Please authorize the application by visiting this URL:")
                    print(f"\n{thread_auth.url}\n")
                    print("Waiting for authorization to complete...")
                    
                    client.auth.wait_for_completion(thread_auth)
                    print("✅ Authorization successful!")
                else:
                    print("✅ Already authorized!")
                
                print(f"\n--- Getting Thread Details (ID: {thread_id}) ---\n")
                
                thread_input = {"thread_id": thread_id}
                
                thread_response = client.tools.execute(
                    tool_name=thread_tool,
                    input=thread_input,
                    user_id=TEST_EMAIL
                )
                
                if "messages" in thread_response:
                    print(f"✅ Successfully retrieved thread with {len(thread_response['messages'])} messages")
                    # Print first message snippet
                    if thread_response["messages"]:
                        first_msg = thread_response["messages"][0]
                        print(f"  First message snippet: {first_msg.get('snippet', 'No snippet')}")
                else:
                    print("❌ Error retrieving thread")
                    print(thread_response)
                
                # Search for emails from same sender
                if "sender" in first_email:
                    sender = first_email["sender"]
                    search_tool = "Google.SearchThreads"
                    
                    print(f"\n--- Searching for Emails from {sender} ---\n")
                    
                    search_auth = client.tools.authorize(
                        tool_name=search_tool,
                        user_id=TEST_EMAIL
                    )
                    
                    if search_auth.status != "completed":
                        client.auth.wait_for_completion(search_auth)
                    
                    search_input = {
                        "sender": sender,
                        "max_results": 3
                    }
                    
                    search_response = client.tools.execute(
                        tool_name=search_tool,
                        input=search_input,
                        user_id=TEST_EMAIL
                    )
                    
                    if "threads" in search_response:
                        print(f"✅ Found {len(search_response['threads'])} threads from {sender}")
                    else:
                        print(f"❌ Error searching for emails from {sender}")
                        print(search_response)
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n=== Test Complete ===\n")

if __name__ == "__main__":
    asyncio.run(test_arcade_gmail()) 