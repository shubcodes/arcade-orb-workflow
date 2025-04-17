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

async def test_email_watcher():
    """Test the email watcher agent functionality."""
    # Get email address from environment or use default
    email_address = os.getenv("TEST_EMAIL_ADDRESS", "")
    
    if not email_address:
        print("Please set TEST_EMAIL_ADDRESS environment variable or edit this script")
        print("Using default_user@example.com for demo purposes")
        email_address = "default_user@example.com"
    
    print(f"\n=== Testing Email Watcher Agent with: {email_address} ===\n")
    
    # Create the email watcher agent
    watcher = EmailWatcherAgent(user_id=email_address)
    
    # Start the watcher
    watcher.start()
    
    try:
        # Test authorization
        print("\n--- Testing Authorization ---\n")
        authorized = await watcher.ensure_authorization()
        
        if not authorized:
            print("❌ Authorization failed. Please check error logs and try again.")
            return
        
        print("✅ Successfully authorized with Gmail!")
        
        # Check for invoice emails
        print("\n--- Checking for Invoice Emails ---\n")
        invoice_emails = await watcher.check_for_invoice_emails(limit=10)
        
        if not invoice_emails:
            print("No invoice emails found. This could be normal if your inbox doesn't have any.")
            print("Try sending yourself a test email with 'invoice' or 'billing' in the subject.")
            
            # Try getting the next email through the queue interface
            print("\n--- Trying to get next email from queue ---\n")
            next_email = await watcher.get_next_email()
            
            if next_email:
                print(f"Found an email in the queue: {next_email.get('subject', 'No subject')}")
                invoice_emails = [next_email]
            else:
                print("No emails in queue either.")
        else:
            print(f"✅ Found {len(invoice_emails)} invoice-related emails!")
        
        # Process each invoice email
        for i, email in enumerate(invoice_emails, 1):
            print(f"\n--- Processing Invoice Email {i}/{len(invoice_emails)} ---\n")
            print(f"Subject: {email.get('subject', 'No subject')}")
            print(f"From: {email.get('sender', 'Unknown sender')}")
            
            # Process the email to a file
            file_path, metadata = await watcher.process_email(email)
            
            if file_path:
                print(f"✅ Email saved to file: {file_path}")
                print(f"Metadata: {json.dumps(metadata, indent=2)}")
                
                # Verify the file exists
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    print(f"File size: {file_size} bytes")
                    
                    # Read the first few lines of the file
                    with open(file_path, 'r', encoding='utf-8') as f:
                        first_lines = ''.join([f.readline() for _ in range(10)])
                    print(f"File preview:\n{first_lines}")
                else:
                    print("❌ File was not created properly")
            else:
                print(f"❌ Error processing email: {metadata.get('error', 'Unknown error')}")
        
        # Test email retrieval through the queue interface
        print("\n--- Testing Email Queue ---\n")
        # Get an email from the queue (should be empty now since we processed all)
        next_email = await watcher.get_next_email()
        if next_email:
            print(f"Got email from queue: {next_email.get('subject', 'No subject')}")
        else:
            print("Queue is empty, as expected after processing all emails.")
        
        print("\n=== Email Watcher Agent Test Complete ===\n")
    
    finally:
        # Stop the watcher
        watcher.stop()

if __name__ == "__main__":
    asyncio.run(test_email_watcher()) 