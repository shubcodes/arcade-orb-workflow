#!/usr/bin/env python3
import asyncio
import argparse
import json
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

# Set arcadepy logger to DEBUG level for more detailed API interactions
logging.getLogger('arcadepy').setLevel(logging.DEBUG)

# Import the EmailWatcherAgent
from agents.email_watcher_agent import EmailWatcherAgent

async def main():
    """Test the EmailWatcherAgent's ability to detect invoices in attachments."""
    parser = argparse.ArgumentParser(description='Test EmailWatcherAgent with attachment analysis')
    parser.add_argument('--email', type=str, help='Email address to use for the test')
    parser.add_argument('--num_emails', type=int, default=20, 
                        help='Number of recent emails to check for invoice attachments')
    parser.add_argument('--clear_processed', action='store_true',
                        help='Temporarily clear the processed emails list')
    parser.add_argument('--debug', action='store_true',
                        help='Print detailed debug information about emails')
    args = parser.parse_args()
    
    # Load environment variables
    load_dotenv()
    
    # Use provided email or fallback to environment variable
    email_address = args.email or os.getenv("TEST_EMAIL_ADDRESS", "your_email@gmail.com")
    
    print(f"Testing EmailWatcherAgent for {email_address} with attachment analysis capability")
    print("This test will search for emails that might contain invoices in attachments")
    print("even if the email subject doesn't mention invoices")
    print("-" * 80)
    
    # Initialize the email watcher agent
    watcher = EmailWatcherAgent(user_id=email_address)
    
    # Save original processed emails if we need to restore them
    original_processed_emails = None
    if args.clear_processed:
        original_processed_emails = watcher.processed_emails.copy()
        print(f"Temporarily clearing {len(original_processed_emails)} processed email IDs for testing")
        watcher.processed_emails.clear()
    
    try:
        # Start the agent
        watcher.start()
        
        # Ensure authorization
        print("Authorizing Gmail access...")
        authorized = await watcher.ensure_authorization()
        if not authorized:
            print("Failed to authorize Gmail access")
            return
        
        # Check for invoice emails, specifying how many emails to check
        print(f"Checking {args.num_emails} recent emails for invoice content or attachments...")
        
        # Direct API call to get emails for debugging
        if args.debug:
            print("\n--- DEBUG: Direct API call to list emails ---")
            response = watcher.arcade_client.tools.execute(
                tool_name="Google.ListEmails",
                input={"n_emails": args.num_emails},
                user_id=email_address
            )
            if hasattr(response, 'output') and hasattr(response.output, 'value'):
                result = response.output.value
                if isinstance(result, dict) and "emails" in result:
                    all_emails = result["emails"]
                    print(f"Found {len(all_emails)} emails via direct API call")
                    
                    for i, email in enumerate(all_emails[:5]):  # Show first 5 for brevity
                        print(f"\nEmail {i+1}:")
                        print(f"  Subject: {email.get('subject', 'No subject')}")
                        print(f"  ID: {email.get('id', 'No ID')}")
                        print(f"  ThreadID: {email.get('threadId', 'No threadId')}")
                        print(f"  Has ID: {bool(email.get('id'))}")
                        print(f"  Has ThreadID: {bool(email.get('threadId'))}")
            
        # Now check for invoice emails
        invoice_emails = await watcher.check_for_invoice_emails(num_emails=args.num_emails)
        
        if not invoice_emails:
            print("No invoice-related emails found in the search range.")
            print("Try sending yourself a test email with an attachment named 'invoice.pdf' or similar")
            return
        
        print(f"Found {len(invoice_emails)} emails with potential invoice content or attachments")
        
        # Debug: Print details of the found invoice emails
        if args.debug:
            print("\n--- DEBUG: Found invoice emails details ---")
            for i, email in enumerate(invoice_emails):
                print(f"\nInvoice Email {i+1}:")
                print(f"  Subject: {email.get('subject', 'No subject')}")
                print(f"  ID: {email.get('id', 'No ID')}")
                print(f"  ThreadID: {email.get('threadId', 'No threadId')}")
                print(f"  Date: {email.get('date', 'No date')}")
                print(f"  Sender: {email.get('from', 'No sender')}")
                print(f"  All keys: {list(email.keys())}")
        
        # Process each invoice email
        for i, email in enumerate(invoice_emails, 1):
            print(f"\nProcessing email {i}/{len(invoice_emails)}: {email.get('subject', 'No subject')}")
            print(f"  Email ID: {email.get('id', 'None')}, Thread ID: {email.get('threadId', 'None')}")
            
            # Skip emails without both ID and threadId
            if not email.get('id') or not email.get('threadId'):
                print(f"  WARNING: Email missing ID or threadId - skipping...")
                continue
            
            # Process the email to a file
            file_path, metadata = await watcher.process_email(email)
            
            if file_path:
                print(f"Email saved to file: {file_path}")
                
                # Display key metadata
                print(f"Subject: {metadata.get('subject', 'Unknown')}")
                print(f"Sender: {metadata.get('sender', 'Unknown')}")
                print(f"Attachment count: {metadata.get('attachment_count', 0)}")
                print(f"Has invoice attachments: {metadata.get('has_invoice_attachments', False)}")
                
                # List saved attachments
                if metadata.get('saved_attachments'):
                    print("\nSaved attachments:")
                    for attachment in metadata['saved_attachments']:
                        invoice_indicator = "✓ POSSIBLE INVOICE" if attachment.get('possibly_invoice', False) else ""
                        print(f"  - {attachment['name']} ({attachment['type']}) {invoice_indicator}")
                        print(f"    Saved to: {attachment['path']}")
            else:
                print(f"Error processing email: {metadata.get('error', 'Unknown error')}")
    
    finally:
        # Restore the original processed emails list if we temporarily cleared it
        if args.clear_processed and original_processed_emails is not None:
            print(f"Restoring original {len(original_processed_emails)} processed email IDs")
            watcher.processed_emails = original_processed_emails
            
        # Stop the agent
        watcher.stop()
        print("\nTest completed. EmailWatcherAgent stopped.")

if __name__ == "__main__":
    asyncio.run(main()) 