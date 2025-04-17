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
from custom_tools.gmail_attachment_tool_direct import GmailAttachmentTools

async def test_text_attachment():
    """Test analysis of a sample text file"""
    print("\n===== Testing Text File Analysis =====")
    
    # Sample text with invoice-like content
    sample_text = """
    INVOICE #12345
    Date: April 15,, 2025
    
    From: ABC Company
    To: XYZ Corporation
    
    ITEMS:
    1. Cloud Services - $1,200.00
    2. Support Plan - $499.99
    
    Subtotal: $1,699.99
    Tax (8%): $136.00
    Total Due: $1,835.99
    
    Please remit payment by May 1, 2025
    Payment methods: Credit Card, Bank Transfer
    """
    
    # Create a temporary invoice-like text file
    temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents", "email_temp")
    os.makedirs(temp_dir, exist_ok=True)
    test_file_path = os.path.join(temp_dir, "test_invoice.txt")
    
    with open(test_file_path, "w") as f:
        f.write(sample_text)
    
    # Load environment variables
    load_dotenv()
    
    # Create email watcher agent
    email_address = os.getenv("TEST_EMAIL_ADDRESS", "sargha@umich.edu")
    watcher = EmailWatcherAgent(user_id=email_address)
    
    # Analyze the text file
    print("Analyzing text file with invoice content...")
    result = await watcher.analyze_text_attachment(test_file_path, "test_invoice.txt")
    
    print(f"Analysis result:")
    for key, value in result.items():
        print(f"  {key}: {value}")

async def test_contract_abc():
    """Test the contract_abc.txt file specifically"""
    print("\n===== Testing contract_abc.txt Analysis =====")
    
    # Load environment variables
    load_dotenv()
    
    # Email watcher with enhanced logging
    logging.getLogger('agents.email_watcher_agent').setLevel(logging.DEBUG)
    
    # Specify the email to test
    email_address = os.getenv("TEST_EMAIL_ADDRESS", "sargha@umich.edu")
    watcher = EmailWatcherAgent(user_id=email_address)
    
    # Look for the contract_abc.txt file
    temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents", "email_temp")
    
    # Search for contract_abc.txt in all attachment directories
    contract_path = None
    for root, dirs, files in os.walk(temp_dir):
        for file in files:
            if file == "contract_abc.txt":
                contract_path = os.path.join(root, file)
                break
        if contract_path:
            break
    
    if not contract_path:
        print("Could not find contract_abc.txt. Checking a specific email...")
        
        # Try to get the file from a specific email
        await watcher.ensure_authorization("Google.ListEmails")
        
        # Create a mock email with the known ID
        test_email = {
            "id": "196365d2a4c3587e",  # The test email with contract_abc.txt
            "threadId": "196365d2a4c3587e",
            "subject": "test"
        }
        
        # Get the email contents
        email_content = await watcher.get_email_contents(test_email)
        if email_content:
            print(f"Successfully retrieved email with subject: {email_content.get('subject')}")
            attachments = email_content.get('attachments', [])
            
            for attachment in attachments:
                if attachment.get('filename') == 'contract_abc.txt':
                    print(f"Found contract_abc.txt in the email!")
                    
                    # Process the email to save the attachment
                    file_path, metadata = await watcher.process_email(test_email)
                    
                    for saved_attachment in metadata.get('saved_attachments', []):
                        if saved_attachment['name'] == 'contract_abc.txt':
                            contract_path = saved_attachment['path']
                            print(f"Downloaded contract_abc.txt to {contract_path}")
                            break
    
    if contract_path:
        print(f"Found contract_abc.txt at {contract_path}")
        print("Analyzing file...")
        result = await watcher.analyze_text_attachment(contract_path, "contract_abc.txt")
        
        print(f"Analysis result:")
        for key, value in result.items():
            print(f"  {key}: {value}")
    else:
        print("Could not find contract_abc.txt")

async def test_pdf_repair():
    """Test downloading and repairing the PDF file"""
    print("\n===== Testing PDF Repair =====")
    
    # Load environment variables
    load_dotenv()
    
    # Get the email address from environment
    email_address = os.getenv("TEST_EMAIL_ADDRESS", "sargha@umich.edu")
    
    # Initialize the Gmail attachment tools
    gmail_tools = GmailAttachmentTools(user_id=email_address)
    
    # Ensure authorization
    if not await gmail_tools.ensure_authorization():
        print("Failed to authorize Gmail access")
        return
    
    # Use the known message ID with PDF attachment
    message_id = "196365ccdd53bf92"  # The "something money" email
    
    # List attachments
    print(f"Listing attachments for message {message_id}...")
    attachments_result = await gmail_tools.list_message_attachments(message_id)
    
    if "error" in attachments_result:
        print(f"Error listing attachments: {attachments_result['message']}")
        return
    
    attachments = attachments_result.get("attachments", [])
    print(f"Found {len(attachments)} attachments")
    
    # Find and download the PDF attachment
    for attachment in attachments:
        attachment_id = attachment["id"]
        filename = attachment["filename"]
        mime_type = attachment.get("mimeType", "unknown")
        
        if filename.lower().endswith(".pdf") or mime_type.lower() == "application/pdf":
            print(f"Found PDF attachment: {filename}")
            
            # Download the attachment
            print(f"Downloading attachment...")
            attachment_data = await gmail_tools.get_gmail_attachment(message_id, attachment_id)
            
            if "error" in attachment_data:
                print(f"Error downloading attachment: {attachment_data['message']}")
                continue
            
            # Save the attachment with extra validation
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents", "repaired_pdf")
            os.makedirs(output_dir, exist_ok=True)
            
            output_path = os.path.join(output_dir, filename)
            
            with open(output_path, "wb") as f:
                try:
                    # Gmail API uses URL-safe base64 encoding
                    data = attachment_data["data"]
                    
                    # Add padding if necessary
                    padding_needed = 4 - (len(data) % 4) if len(data) % 4 else 0
                    if padding_needed:
                        data += "=" * padding_needed
                        print(f"Added {padding_needed} padding characters to base64 data")
                    
                    # Try URL-safe base64 decoding (Gmail API standard)
                    try:
                        decoded_data = base64.urlsafe_b64decode(data)
                        print(f"Successfully decoded using URL-safe base64")
                    except Exception as url_error:
                        print(f"URL-safe decoding failed: {str(url_error)}")
                        try:
                            # Fallback to standard base64
                            decoded_data = base64.b64decode(data)
                            print(f"Successfully decoded using standard base64")
                        except Exception as std_error:
                            print(f"Standard decoding also failed: {str(std_error)}")
                            # Last resort, try to fix the data
                            print("Attempting to repair the base64 data...")
                            
                            # Remove non-base64 characters
                            import re
                            cleaned_data = re.sub(r'[^A-Za-z0-9+/=]', '', data)
                            
                            try:
                                decoded_data = base64.b64decode(cleaned_data)
                                print("Successfully decoded after cleaning the data")
                            except:
                                print("All decoding methods failed")
                                if isinstance(data, bytes):
                                    decoded_data = data
                                else:
                                    decoded_data = data.encode('utf-8')
                    
                    # Ensure PDF starts with correct header
                    if not decoded_data.startswith(b"%PDF-"):
                        print("PDF header missing, adding it...")
                        decoded_data = b"%PDF-1.4\n" + decoded_data
                    
                    f.write(decoded_data)
                    print(f"Saved repaired PDF to: {output_path}")
                    
                    # Validate the PDF
                    with open(output_path, "rb") as pdf_file:
                        header = pdf_file.read(5)
                        if header != b"%PDF-":
                            print(f"WARNING: {filename} still does not have a valid PDF header!")
                            print(f"First 20 bytes: {repr(pdf_file.read(20))}")
                        else:
                            print(f"Validated PDF file: {filename} has proper header")
                    
                except Exception as e:
                    print(f"Error saving attachment: {str(e)}")
                    import traceback
                    traceback.print_exc()

async def main():
    # Run all tests
    await test_text_attachment()
    await test_contract_abc()
    await test_pdf_repair()

if __name__ == "__main__":
    # Import here to avoid circular imports
    import base64
    asyncio.run(main()) 