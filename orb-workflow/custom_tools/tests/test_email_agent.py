#!/usr/bin/env python3
import asyncio
import os
import logging
import sys
from dotenv import load_dotenv
from agents.email_watcher_agent import EmailWatcherAgent

# Enable more detailed logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - %(message)s',
                   datefmt='%Y-%m-%d %H:%M:%S',
                   stream=sys.stdout)

async def main():
    # Load environment variables
    load_dotenv()
    
    # Get email address from environment variable with fallback
    email = os.getenv("TEST_EMAIL_ADDRESS", "sargha@umich.edu")
    
    print(f"\n=== Testing Email Watcher Agent with: {email} ===\n")
    
    # Create the email watcher
    watcher = EmailWatcherAgent(user_id=email)
    
    # Start the agent
    watcher.start()
    
    # Check for invoice emails
    invoice_emails = await watcher.check_for_invoice_emails(num_emails=20)
    
    if not invoice_emails:
        print("No invoice-related emails found. This could be expected if there are no invoice emails in your inbox.")
        print("Try sending a test email with 'invoice' or 'billing' in the subject or attach an invoice-like document.")
    else:
        print(f"✅ Found {len(invoice_emails)} invoice-related emails!")
        
        # Process each invoice email
        for idx, email in enumerate(invoice_emails, 1):
            print(f"\n--- Processing Email {idx}/{len(invoice_emails)} ---\n")
            print(f"Subject: {email.get('subject', 'No subject')}")
            print(f"From: {email.get('from', 'Unknown sender')}")
            
            # Process the email to a file
            file_path, metadata = await watcher.process_email(email)
            
            if file_path:
                print(f"✅ Email saved to file: {file_path}")
                
                # Print a preview of the file contents
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        preview_lines = []
                        for i, line in enumerate(f):
                            if i >= 10:  # Show first 10 lines
                                break
                            preview_lines.append(line.strip())
                    
                    print("Preview:")
                    print("\n".join(preview_lines))
                except Exception as e:
                    print(f"Error reading file: {e}")
            else:
                print(f"❌ Error processing email: {metadata.get('error', 'Unknown error')}")
    
    # Stop the agent
    watcher.stop()
    
    print("\n=== Email Watcher Agent Test Complete ===\n")

if __name__ == "__main__":
    asyncio.run(main()) 