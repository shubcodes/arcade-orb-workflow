#!/usr/bin/env python3
import asyncio
import os
import logging
import sys
from dotenv import load_dotenv

# Configure logging to show detailed information
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Import the EmailWatcherAgent
from agents.email_watcher_agent import EmailWatcherAgent

async def main():
    """Test the EmailWatcherAgent's ability to process an email with known attachments."""
    # Load environment variables
    load_dotenv()
    
    # Use TEST_EMAIL_ADDRESS environment variable or default
    email_address = os.getenv("TEST_EMAIL_ADDRESS", "sargha@umich.edu")
    
    # Known email ID with attachment
    known_email_id = "196365ccdd53bf92"
    known_thread_id = "196365ccdd53bf92"
    
    print(f"Testing attachment processing for specific email (ID: {known_email_id})")
    print(f"User: {email_address}")
    print("-" * 80)
    
    # Initialize the email watcher agent
    watcher = EmailWatcherAgent(user_id=email_address)
    
    try:
        # Start the agent
        watcher.start()
        
        # Ensure authorization
        print("Authorizing Gmail access...")
        authorized = await watcher.ensure_authorization()
        if not authorized:
            print("Failed to authorize Gmail access")
            return
        
        # Create a mock email object with the known IDs
        test_email = {
            "id": known_email_id,
            "threadId": known_thread_id,
            "subject": "something money"
        }
        
        print(f"Processing email with ID {known_email_id} (something money)")
        
        # Get content and process the email
        email_content = await watcher.get_email_contents(test_email)
        
        if email_content:
            print(f"Successfully retrieved email content")
            print(f"Subject: {email_content.get('subject', 'Unknown')}")
            print(f"Sender: {email_content.get('sender', 'Unknown')}")
            
            # Check for attachments
            attachments = email_content.get('attachments', [])
            print(f"Found {len(attachments)} attachments")
            
            for i, attachment in enumerate(attachments, 1):
                print(f"\nAttachment {i}:")
                print(f"  Name: {attachment.get('filename', 'Unknown')}")
                print(f"  Type: {attachment.get('mimeType', 'Unknown')}")
                print(f"  Size: {attachment.get('size', 'Unknown')} bytes")
                print(f"  Downloaded: {attachment.get('downloaded', False)}")
            
            # Process the email to save attachments
            print("\nProcessing email to save attachments...")
            file_path, metadata = await watcher.process_email(test_email)
            
            if file_path:
                print(f"Email saved to file: {file_path}")
                
                # Display key metadata
                print(f"Attachment count: {metadata.get('attachment_count', 0)}")
                print(f"Has invoice attachments: {metadata.get('has_invoice_attachments', False)}")
                
                # List saved attachments
                if metadata.get('saved_attachments'):
                    print("\nSaved attachments:")
                    for attachment in metadata['saved_attachments']:
                        print(f"  - {attachment['name']} ({attachment['type']})")
                        print(f"    Saved to: {attachment['path']}")
                else:
                    print("No attachments were saved")
            else:
                print(f"Error processing email: {metadata.get('error', 'Unknown error')}")
        else:
            print("Failed to retrieve email content")
    
    finally:
        # Stop the agent
        watcher.stop()
        print("\nTest completed.")

if __name__ == "__main__":
    asyncio.run(main()) 