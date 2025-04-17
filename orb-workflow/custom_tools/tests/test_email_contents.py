#!/usr/bin/env python3
import os
import json
import asyncio
import logging
from dotenv import load_dotenv
from agents.email_watcher_agent import EmailWatcherAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

async def test_find_emails_with_attachments():
    """Find and test emails with attachments."""
    # Get email address from environment or use default
    email_address = os.getenv("TEST_EMAIL_ADDRESS", "sargha@umich.edu")
    
    if not email_address:
        print("Please set TEST_EMAIL_ADDRESS environment variable in .env file")
        return
    
    print(f"\n=== Searching for emails with attachments for {email_address} ===\n")
    
    # Create the email watcher agent
    watcher = EmailWatcherAgent(user_id=email_address)
    
    # Start the watcher
    watcher.start()
    
    try:
        # Ensure we're authorized to list emails
        if not await watcher.ensure_authorization("Google.ListEmails"):
            print("Failed to authorize Gmail access")
            return
        
        # Retrieve the 20 most recent emails
        print("Retrieving the 20 most recent emails...")
        try:
            response = watcher.arcade_client.tools.execute(
                tool_name="Google.ListEmails",
                input={
                    "n_emails": 20  # Get more emails to increase chances of finding attachments
                },
                user_id=watcher.user_id
            )
            
            if not hasattr(response, 'output') or not hasattr(response.output, 'value'):
                print("❌ Error: Invalid response from Gmail API")
                return
                
            result = response.output.value
            
            # Extract emails from the response
            all_emails = []
            if isinstance(result, dict) and "emails" in result:
                all_emails = result["emails"]
            elif isinstance(result, list):
                all_emails = result
                
            print(f"Found {len(all_emails)} emails in total")
            
            # Check each email for attachments by retrieving thread data
            emails_with_attachments = []
            for email in all_emails:
                if not await watcher.ensure_authorization("Google.GetThread"):
                    print("Failed to authorize Gmail thread access")
                    return
                
                email_id = email.get("id")
                thread_id = email.get("threadId")
                
                if not email_id or not thread_id:
                    continue
                
                print(f"Checking email '{email.get('subject', 'No subject')}' for attachments...")
                
                # Get the thread data
                try:
                    thread_response = watcher.arcade_client.tools.execute(
                        tool_name="Google.GetThread",
                        input={"thread_id": thread_id},
                        user_id=watcher.user_id
                    )
                    
                    if not hasattr(thread_response, 'output') or not hasattr(thread_response.output, 'value'):
                        continue
                        
                    thread_data = thread_response.output.value
                    
                    # Check for None response
                    if thread_data is None:
                        print("❌ Thread data is None. The API couldn't find this thread.")
                        return
                        
                    # Check if the email has attachments by examining the thread data directly
                    has_attachments = False
                    attachment_count = 0
                    if "messages" in thread_data:
                        for message in thread_data["messages"]:
                            if message.get("id") == email_id:
                                print(f"Found message in thread with ID: {email_id}")
                                print(f"Subject: {message.get('subject', 'Unknown')}")
                                print(f"From: {message.get('from', 'Unknown')}")
                                
                                # Check for attachments in the message
                                if "attachments" in message and message["attachments"]:
                                    has_attachments = True
                                    attachment_count = len(message["attachments"])
                                    print(f"✅ Found {attachment_count} attachments in the email!")
                                    
                                    # Print attachment details
                                    for i, attachment in enumerate(message["attachments"], 1):
                                        print(f"  Attachment {i}: {attachment.get('filename', 'Unknown')} ({attachment.get('mimeType', 'Unknown type')})")
                                        print(f"    Size: {attachment.get('size', 'Unknown')} bytes")
                                        for key, value in attachment.items():
                                            print(f"    {key}: {value}")
                                else:
                                    print("❌ No attachments found in this email.")
                                
                                break
                    
                    if not has_attachments:
                        print("This email does not have any attachments in the Gmail API response.")
                        print("The email may appear to have attachments in Gmail but they are not accessible via the API.")
                    
                    # Now test the get_email_contents method
                    print("\n--- Using get_email_contents to check email ---\n")
                    email_contents = await watcher.get_email_contents(email)
                    
                    if not email_contents:
                        print(f"❌ Error: Failed to retrieve contents for email ID {email_id}")
                        return
                        
                    print(f"Subject: {email_contents.get('subject', 'Unknown')}")
                    print(f"From: {email_contents.get('sender', 'Unknown')}")
                    print(f"Body: {email_contents.get('body', '')[:100]}...")  # Show first 100 chars
                    
                    # Check attachments returned by get_email_contents
                    attachments = email_contents.get('attachments', [])
                    print(f"Attachments from get_email_contents: {len(attachments)}")
                    
                    # If there are attachments, print details
                    for i, attachment in enumerate(attachments, 1):
                        print(f"  Attachment {i}: {attachment.get('filename', 'Unknown')} ({attachment.get('mimeType', 'Unknown')})")
                        print(f"    Downloaded: {attachment.get('downloaded', False)}")
                        for key, value in attachment.items():
                            if key != 'content':  # Skip content which might be large
                                print(f"    {key}: {value}")
                    
                    # Process the email to a file
                    print("\n--- Processing email to file ---\n")
                    file_path, metadata = await watcher.process_email(email)
                    
                    if file_path:
                        print(f"✅ Email processed and saved to: {file_path}")
                        print(f"Email metadata: {json.dumps(metadata, indent=2)}")
                    else:
                        print(f"❌ Error processing email: {metadata.get('error', 'Unknown error')}")
                
                except Exception as e:
                    print(f"❌ Error checking email for attachments: {str(e)}")
            
            print(f"\nFound {len(emails_with_attachments)} emails with attachments")
            
            # Process each email with attachments
            for email in emails_with_attachments:
                print(f"\n--- Processing email with attachments: {email.get('subject')} ---\n")
                
                # Get the full email contents
                email_contents = await watcher.get_email_contents(email)
                
                if not email_contents:
                    print(f"❌ Error: Failed to retrieve contents for email {email.get('id')}")
                    continue
                    
                # Print the results
                print(f"Subject: {email_contents.get('subject')}")
                print(f"From: {email_contents.get('sender')}")
                print(f"Body Length: {len(email_contents.get('body', ''))}")
                
                # Show attachment details
                attachments = email_contents.get('attachments', [])
                print(f"Attachments: {len(attachments)}")
                
                for i, attachment in enumerate(attachments, 1):
                    print(f"  Attachment {i}: {attachment.get('filename')} ({attachment.get('mimeType')})")
                    print(f"    Size: {attachment.get('size', 'Unknown')} bytes")
                    
                # Process the email to save it to a file
                file_path, metadata = await watcher.process_email(email)
                
                if file_path:
                    print(f"✅ Email processed and saved to: {file_path}")
                    print(f"Attachment metadata saved")
                else:
                    print(f"❌ Error processing email: {metadata.get('error', 'Unknown error')}")
            
            if not emails_with_attachments:
                print("\nNo emails with attachments were found.")
                print("Try sending yourself a test email with an attachment.")
            
        except Exception as e:
            print(f"❌ Error: {str(e)}")
                
    finally:
        # Stop the watcher
        watcher.stop()

async def test_specific_invoice_email():
    """Test a specific invoice email for attachments."""
    # Get email address from environment or use default
    email_address = os.getenv("TEST_EMAIL_ADDRESS", "sargha@umich.edu")
    
    if not email_address:
        print("Please set TEST_EMAIL_ADDRESS environment variable in .env file")
        return
    
    # Use the message ID we know has an attachment
    email_id = "196365ccdd53bf92"  # The "something money" email with attachment
    thread_id = email_id  # Using email ID as thread ID
    
    print(f"\n=== Testing email with known attachment (ID: {email_id}) for {email_address} ===\n")
    
    # Create the email watcher agent
    watcher = EmailWatcherAgent(user_id=email_address)
    
    # Start the watcher
    watcher.start()
    
    try:
        # Ensure we're authorized for both list emails and thread access
        if not await watcher.ensure_authorization("Google.ListEmails"):
            print("Failed to authorize Gmail list access")
            return
            
        if not await watcher.ensure_authorization("Google.GetThread"):
            print("Failed to authorize Gmail thread access")
            return
            
        # First, list emails to find the one with subject "something money"
        print("Searching for email with subject 'something money'...")
        
        # Using ListEmails to find the target email
        response = watcher.arcade_client.tools.execute(
            tool_name="Google.ListEmails",
            input={
                "n_emails": 20  # Get more emails to increase chances of finding it
            },
            user_id=watcher.user_id
        )
        
        if not hasattr(response, 'output') or not hasattr(response.output, 'value'):
            print("❌ Error: Invalid response from Gmail API")
            return
            
        result = response.output.value
        
        # Extract emails from the response
        all_emails = []
        if isinstance(result, dict) and "emails" in result:
            all_emails = result["emails"]
        elif isinstance(result, list):
            all_emails = result
            
        # Find the email with subject containing "money"
        target_email = None
        for email in all_emails:
            subject = email.get("subject", "").lower()
            if "money" in subject:
                target_email = email
                print(f"✅ Found email with subject: '{email.get('subject')}'")
                break
                
        if not target_email:
            print("❌ Could not find any email with subject containing 'money'")
            return
            
        email_id = target_email.get("id")
        thread_id = target_email.get("threadId")
        
        # If thread ID is missing, use email ID as thread ID (common in Gmail)
        if not thread_id:
            thread_id = email_id
            print(f"Thread ID was missing, using email ID instead: {thread_id}")
            # Add thread ID to the target_email object
            target_email["threadId"] = thread_id
        
        print(f"Checking email ID: {email_id}, Thread ID: {thread_id}")
        
        # Get the direct thread data to check for attachments
        try:
            thread_response = watcher.arcade_client.tools.execute(
                tool_name="Google.GetThread",
                input={"thread_id": thread_id},
                user_id=watcher.user_id
            )
            
            if not hasattr(thread_response, 'output') or not hasattr(thread_response.output, 'value'):
                print("❌ Error: Invalid thread response structure")
                return
                
            thread_data = thread_response.output.value
            
            # Check for None response
            if thread_data is None:
                print("❌ Thread data is None. The API couldn't find this thread.")
                return
                
            # Print thread data structure for debugging
            print("\n--- Thread Data Structure ---")
            if isinstance(thread_data, dict):
                print(f"Thread data keys: {list(thread_data.keys())}")
                if "messages" in thread_data:
                    print(f"Number of messages: {len(thread_data['messages'])}")
                    for i, msg in enumerate(thread_data["messages"]):
                        print(f"\n  Message {i+1} keys: {list(msg.keys())}")
                        
                        # Check for attachments-related fields
                        for key, value in msg.items():
                            if key in ["attachments", "files", "parts", "payload"]:
                                print(f"  Found potential attachment field '{key}': {value}")
                            
                        # Check body structure if it exists
                        if "body" in msg:
                            if isinstance(msg["body"], dict):
                                print(f"  Body keys: {list(msg['body'].keys())}")
                            else:
                                print(f"  Body is a {type(msg['body']).__name__}, content: {msg['body'][:100]}...")
                        
                        # Also check for snippet that might mention attachments
                        if "snippet" in msg:
                            snippet = msg.get("snippet", "")
                            if "attach" in snippet.lower():
                                print(f"  Snippet mentions attachment: {snippet}")
                        
                        # Look for any key that might contain "attach" in it
                        attach_related = {k: v for k, v in msg.items() if "attach" in k.lower()}
                        if attach_related:
                            print(f"  Attachment-related fields: {attach_related}")
            else:
                print(f"Thread data type: {type(thread_data)}")
                print(f"Thread data value: {thread_data}")
            print("--- End Thread Data Structure ---\n")
                
            # Check if the email has attachments by examining the thread data directly
            has_attachments = False
            attachment_count = 0
            if "messages" in thread_data:
                for message in thread_data["messages"]:
                    if message.get("id") == email_id:
                        print(f"Found message in thread with ID: {email_id}")
                        print(f"Subject: {message.get('subject', 'Unknown')}")
                        print(f"From: {message.get('from', 'Unknown')}")
                        
                        # Check for attachments in the message
                        if "attachments" in message and message["attachments"]:
                            has_attachments = True
                            attachment_count = len(message["attachments"])
                            print(f"✅ Found {attachment_count} attachments in the email!")
                            
                            # Print attachment details
                            for i, attachment in enumerate(message["attachments"], 1):
                                print(f"  Attachment {i}: {attachment.get('filename', 'Unknown')} ({attachment.get('mimeType', 'Unknown type')})")
                                print(f"    Size: {attachment.get('size', 'Unknown')} bytes")
                                for key, value in attachment.items():
                                    print(f"    {key}: {value}")
                        else:
                            print("❌ No attachments found in this email.")
                        
                        break
            
            if not has_attachments:
                print("This email does not have any attachments in the Gmail API response.")
                print("The email may appear to have attachments in Gmail but they are not accessible via the API.")
                
            # Now test the get_email_contents method
            print("\n--- Using get_email_contents to check email ---\n")
            email_contents = await watcher.get_email_contents(target_email)
            
            if not email_contents:
                print(f"❌ Error: Failed to retrieve contents for email ID {email_id}")
                return
                
            print(f"Subject: {email_contents.get('subject', 'Unknown')}")
            print(f"From: {email_contents.get('sender', 'Unknown')}")
            print(f"Body: {email_contents.get('body', '')[:100]}...")  # Show first 100 chars
            
            # Check attachments returned by get_email_contents
            attachments = email_contents.get('attachments', [])
            print(f"Attachments from get_email_contents: {len(attachments)}")
            
            # If there are attachments, print details
            for i, attachment in enumerate(attachments, 1):
                print(f"  Attachment {i}: {attachment.get('filename', 'Unknown')} ({attachment.get('mimeType', 'Unknown')})")
                print(f"    Downloaded: {attachment.get('downloaded', False)}")
                for key, value in attachment.items():
                    if key != 'content':  # Skip content which might be large
                        print(f"    {key}: {value}")
            
            # Process the email to a file
            print("\n--- Processing email to file ---\n")
            file_path, metadata = await watcher.process_email(target_email)
            
            if file_path:
                print(f"✅ Email processed and saved to: {file_path}")
                print(f"Email metadata: {json.dumps(metadata, indent=2)}")
            else:
                print(f"❌ Error processing email: {metadata.get('error', 'Unknown error')}")
            
        except Exception as e:
            print(f"❌ Error checking email: {str(e)}")
            import traceback
            traceback.print_exc()
                
    finally:
        # Stop the watcher
        watcher.stop()

if __name__ == "__main__":
    # asyncio.run(test_find_emails_with_attachments())
    asyncio.run(test_specific_invoice_email()) 