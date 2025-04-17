#!/usr/bin/env python3
import os
import json
import base64
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

async def test_custom_gmail_tools():
    """Test the custom Gmail attachment tools."""
    # Get email address from environment or use default
    email_address = os.getenv("TEST_EMAIL_ADDRESS", "sargha@umich.edu")
    
    if not email_address:
        print("Please set TEST_EMAIL_ADDRESS environment variable in .env file")
        return
    
    # Initialize Arcade client
    arcade_client = Arcade()
    
    # Directory to save downloaded attachments
    attachment_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents", "attachments")
    os.makedirs(attachment_dir, exist_ok=True)
    
    print(f"\n=== Testing custom Gmail attachment tools for {email_address} ===\n")
    
    try:
        # Step 1: Authorize the Gmail.ListEmails tool (to get message IDs)
        print("Authorizing Gmail.ListEmails...")
        auth_response = arcade_client.tools.authorize(
            tool_name="Google.ListEmails",
            user_id=email_address
        )
        
        if auth_response.status != "completed":
            print(f"Please authorize access by visiting: {auth_response.url}")
            auth_response = arcade_client.auth.wait_for_completion(auth_response)
        
        print("✅ Successfully authorized Gmail.ListEmails")
        
        # Step 2: Get recent emails
        print("\nRetrieving recent emails...")
        emails_response = arcade_client.tools.execute(
            tool_name="Google.ListEmails",
            input={"n_emails": 20},
            user_id=email_address
        )
        
        if not hasattr(emails_response, 'output') or not hasattr(emails_response.output, 'value'):
            print("❌ Error: Invalid response from Gmail API")
            return
            
        result = emails_response.output.value
        
        # Extract emails from the response
        all_emails = []
        if isinstance(result, dict) and "emails" in result:
            all_emails = result["emails"]
        elif isinstance(result, list):
            all_emails = result
            
        if not all_emails:
            print("❌ No emails found")
            return
            
        print(f"Found {len(all_emails)} emails")
        
        # Find the email with subject containing "money" or the first "invoice" email
        target_email = None
        for email in all_emails:
            subject = email.get("subject", "").lower()
            if "money" in subject or "invoice" in subject:
                target_email = email
                print(f"✅ Found email with subject: '{email.get('subject')}'")
                break
        
        if not target_email:
            # Use the first email as a fallback
            target_email = all_emails[0]
            print(f"Using first email with subject: '{target_email.get('subject')}'")
        
        message_id = target_email.get("id")
        
        # Step 3: Authorize the custom Gmail.ListAttachments tool
        print("\nAuthorizing Gmail.ListAttachments...")
        try:
            auth_response = arcade_client.tools.authorize(
                tool_name="Gmail.ListAttachments",
                user_id=email_address
            )
            
            if auth_response.status != "completed":
                print(f"Please authorize access by visiting: {auth_response.url}")
                auth_response = arcade_client.auth.wait_for_completion(auth_response)
                
            print("✅ Successfully authorized Gmail.ListAttachments")
            
            # Step 4: List attachments for the target email
            print(f"\nListing attachments for email: {target_email.get('subject')} (ID: {message_id})...")
            try:
                attachments_response = arcade_client.tools.execute(
                    tool_name="Gmail.ListAttachments",
                    input={"message_id": message_id},
                    user_id=email_address
                )
                
                if not hasattr(attachments_response, 'output') or not hasattr(attachments_response.output, 'value'):
                    print("❌ Error: Invalid response from Gmail.ListAttachments")
                    return
                    
                attachments_result = attachments_response.output.value
                
                if isinstance(attachments_result, dict) and "error" in attachments_result:
                    print(f"❌ Error: {attachments_result.get('message', 'Unknown error')}")
                    print(f"Error details: {attachments_result.get('error', 'None')}")
                    return
                
                attachment_count = attachments_result.get("count", 0)
                attachments = attachments_result.get("attachments", [])
                
                print(f"Found {attachment_count} attachments")
                
                if attachment_count == 0:
                    print("No attachments to download")
                    return
                
                # Print attachment details
                for i, attachment in enumerate(attachments, 1):
                    print(f"  Attachment {i}:")
                    print(f"    ID: {attachment.get('id')}")
                    print(f"    Filename: {attachment.get('filename')}")
                    print(f"    MIME Type: {attachment.get('mimeType')}")
                    print(f"    Size: {attachment.get('size')} bytes")
                
                # Step 5: Authorize the custom Gmail.GetAttachment tool
                print("\nAuthorizing Gmail.GetAttachment...")
                auth_response = arcade_client.tools.authorize(
                    tool_name="Gmail.GetAttachment",
                    user_id=email_address
                )
                
                if auth_response.status != "completed":
                    print(f"Please authorize access by visiting: {auth_response.url}")
                    auth_response = arcade_client.auth.wait_for_completion(auth_response)
                    
                print("✅ Successfully authorized Gmail.GetAttachment")
                
                # Step 6: Download each attachment
                for attachment in attachments:
                    attachment_id = attachment.get("id")
                    filename = attachment.get("filename", f"attachment_{attachment_id}")
                    
                    print(f"\nDownloading attachment: {filename}...")
                    
                    try:
                        download_response = arcade_client.tools.execute(
                            tool_name="Gmail.GetAttachment",
                            input={
                                "message_id": message_id,
                                "attachment_id": attachment_id
                            },
                            user_id=email_address
                        )
                        
                        if not hasattr(download_response, 'output') or not hasattr(download_response.output, 'value'):
                            print(f"❌ Error: Invalid response when downloading {filename}")
                            continue
                            
                        attachment_data = download_response.output.value
                        
                        if isinstance(attachment_data, dict) and "error" in attachment_data:
                            print(f"❌ Error: {attachment_data.get('message', 'Unknown error')}")
                            print(f"Error details: {attachment_data.get('error', 'None')}")
                            continue
                        
                        # Save the attachment to file
                        output_path = os.path.join(attachment_dir, filename)
                        
                        # Decode base64 content
                        content = attachment_data.get("data", "")
                        if content:
                            try:
                                decoded_content = base64.urlsafe_b64decode(content)
                                
                                with open(output_path, 'wb') as f:
                                    f.write(decoded_content)
                                    
                                print(f"✅ Successfully downloaded and saved to: {output_path}")
                                print(f"  Size: {len(decoded_content)} bytes")
                            except Exception as e:
                                print(f"❌ Error decoding and saving attachment: {str(e)}")
                        else:
                            print("❌ No content data in the attachment response")
                    
                    except Exception as e:
                        print(f"❌ Error downloading attachment: {str(e)}")
            
            except Exception as e:
                print(f"❌ Error listing attachments: {str(e)}")
        
        except Exception as e:
            print(f"❌ Error authorizing Gmail.ListAttachments: {str(e)}")
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_custom_gmail_tools()) 