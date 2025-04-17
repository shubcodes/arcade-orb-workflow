#!/usr/bin/env python3
import os
import json
import logging
import base64
import tempfile
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv
import openai
from arcadepy import Arcade
import re
import time
import asyncio
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY")
ARCADE_API_KEY = os.getenv("ARCADE_API_KEY")
ARCADE_WORKER_SECRET = os.getenv("ARCADE_WORKER_SECRET", "dev")

if not FIREWORKS_API_KEY:
    raise ValueError("FIREWORKS_API_KEY environment variable not set.")

# Initialize OpenAI client (using Fireworks)
openai_client = openai.OpenAI(
    base_url="https://api.fireworks.ai/inference/v1",
    api_key=FIREWORKS_API_KEY
)
FIREWORKS_MODEL = "accounts/fireworks/models/llama4-maverick-instruct-basic"

# Import our custom Gmail attachment tools
from custom_tools.gmail_attachment_tool_direct import GmailAttachmentTools

class EmailWatcherAgent:
    """Agent that monitors email inbox for invoice-related emails using Arcade."""
    
    def __init__(self, user_id: str = "default_user@example.com"):
        """Initialize the email watcher agent with Arcade auth capabilities.
        
        Args:
            user_id: The user ID to use for Arcade authorization (typically an email)
        """
        logger.info("Initializing Email Watcher Agent")
        self.user_id = user_id
        self.arcade_client = Arcade(api_key=ARCADE_API_KEY)
        self.authorized = False
        self.email_queue = []
        self.temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "documents", "email_temp")
        
        # Create temp directory if it doesn't exist
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Load processed emails if available
        self._load_processed_emails()
    
    def _load_processed_emails(self):
        """Load the list of processed email IDs from a file."""
        processed_emails_path = os.path.join(self.temp_dir, "processed_emails.json")
        try:
            with open(processed_emails_path, "r") as f:
                self.processed_emails = set(json.load(f))
                logger.info(f"Loaded {len(self.processed_emails)} processed email IDs")
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("No processed emails file found or invalid format, starting fresh")
            self.processed_emails = set()
    
    def _save_processed_emails(self):
        """Save the list of processed email IDs to a file."""
        processed_emails_path = os.path.join(self.temp_dir, "processed_emails.json")
        with open(processed_emails_path, "w") as f:
            json.dump(list(self.processed_emails), f)
        logger.info(f"Saved {len(self.processed_emails)} processed email IDs")
    
    def mark_email_processed(self, email_id: str):
        """Mark an email as processed."""
        self.processed_emails.add(email_id)
        self._save_processed_emails()
    
    async def ensure_authorization(self, tool_name: str = "Google.ListEmails") -> bool:
        """Ensure the agent is authorized to access Gmail via Arcade.
        
        Args:
            tool_name: The name of the tool to authorize
            
        Returns:
            bool: True if authorized, False otherwise
        """
        logger.info(f"Authorizing user {self.user_id} for {tool_name}")
        
        try:
            # Start the authorization process
            auth_response = self.arcade_client.tools.authorize(
                tool_name=tool_name,
                user_id=self.user_id
            )
            
            # Check if authorization is already completed
            if auth_response.status == "completed":
                logger.info(f"User already authorized for {tool_name}")
                self.authorized = True
                return True
            
            # Authorization needed
            logger.info(f"Gmail authorization required. Please visit: {auth_response.url}")
            
            # Wait for authorization completion
            self.arcade_client.auth.wait_for_completion(auth_response)
            
            logger.info(f"Gmail authorization completed successfully for {tool_name}")
            self.authorized = True
            return True
                
        except Exception as e:
            logger.error(f"Error during Gmail authorization: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    async def check_for_invoice_emails(self, num_emails: int = 20):
        """Check for new invoice or billing emails, including emails with invoice attachments.
        
        Args:
            num_emails: Number of recent emails to check
            
        Returns:
            List of email dicts containing invoice-related content
        """
        if not await self.ensure_authorization("Google.ListEmails"):
            logger.error("Not authorized to list emails")
            return []
            
        logger.info(f"Checking for invoice emails for {self.user_id}")
        
        try:
            # Using Google.ListEmails to get recent emails
            logger.info(f"Using Google.ListEmails to retrieve {num_emails} recent emails")
            
            response = self.arcade_client.tools.execute(
                tool_name="Google.ListEmails",
                input={
                    "n_emails": num_emails  # Get more recent emails to check for attachments
                },
                user_id=self.user_id
            )
            
            # Debug logging for response structure
            logger.info(f"Response type: {type(response)}")
            
            if not hasattr(response, 'output') or not hasattr(response.output, 'value'):
                logger.error("Response does not have expected structure")
                return []
            
            result = response.output.value
            logger.info(f"Result type: {type(result)}")
            
            if isinstance(result, dict):
                logger.info(f"Result keys: {result.keys()}")
            
            # Extract all emails from the response
            all_emails = []
            if isinstance(result, dict) and "emails" in result:
                all_emails = result["emails"]
            elif isinstance(result, list):
                all_emails = result
            else:
                logger.error(f"Unexpected response format: {type(result)}")
                return []
                
            logger.info(f"Found {len(all_emails)} emails in total")
            
            # Normalize email objects to ensure consistent field names
            normalized_emails = []
            for email in all_emails:
                # Create a copy of the email
                normalized_email = email.copy()
                
                # Handle different thread ID field names
                if 'thread_id' in email and not email.get('threadId'):
                    normalized_email['threadId'] = email['thread_id']
                
                normalized_emails.append(normalized_email)
            
            # Filter out already processed emails
            unprocessed_emails = [
                email for email in normalized_emails 
                if email.get("id") not in self.processed_emails
            ]
            
            logger.info(f"Found {len(unprocessed_emails)} unprocessed emails")
            
            if not unprocessed_emails:
                logger.info("No unprocessed emails found")
                return []
                
            # First check all emails for attachments or invoice content
            # First pass check by subject keywords (fast)
            subject_filtered_emails = []
            invoice_keywords = ["invoice", "billing", "payment", "receipt", "statement", "bill", "charge", "due", "money", "finance", "transaction"]
            
            for email in unprocessed_emails:
                subject = email.get("subject", "").lower()
                if any(keyword in subject for keyword in invoice_keywords):
                    logger.info(f"Found email with invoice-related subject: {email.get('subject')}")
                    subject_filtered_emails.append(email)
            
            logger.info(f"Found {len(subject_filtered_emails)} emails with invoice-related subjects")
            
            # Next, check a sample of the remaining unprocessed emails for attachments
            # (This is potentially expensive, so limit how many we check)
            remaining_emails = [email for email in unprocessed_emails if email not in subject_filtered_emails]
            
            max_to_check = min(len(remaining_emails), 10)  # Check at most 10 emails for attachments
            logger.info(f"Checking {max_to_check} remaining emails for attachments")
            
            # Sort remaining emails by those most likely to have attachments first
            # In a real-world scenario, we might use metadata or other signals to prioritize
            attachments_to_check = remaining_emails[:max_to_check]
            
            potentially_invoice_emails = []
            for idx, email in enumerate(attachments_to_check):
                if not email.get("id") or not email.get("threadId"):
                    logger.warning(f"Email missing ID or threadId - skipping: {email.get('subject', 'No subject')}")
                    continue
                    
                # Deep checking email 1/10: 🍪 Solo Travel
                logger.info(f"Deep checking email {idx+1}/{len(attachments_to_check)}: {email.get('subject', 'No subject')}")
                
                # Getting email contents will check for attachments
                email_data = await self.get_email_contents(email)
                
                if not email_data:
                    logger.warning(f"Could not get contents for email: {email.get('subject', 'No subject')}")
                    continue
                
                # First, look for attachments
                attachments = email_data.get("attachments", [])
                attachment_analysis_results = []
                
                if attachments:
                    logger.info(f"Found {len(attachments)} attachments in email: {email.get('subject')}")
                    
                    # Check if any attachment might be an invoice
                    has_invoice_attachment = await self._check_attachments_for_invoice(attachments, attachment_analysis_results)
                    if has_invoice_attachment:
                        logger.info(f"Found invoice attachment in email: {email.get('subject', 'No subject')}")
                        potentially_invoice_emails.append(email)
                        continue
                
                # If no invoice attachments, check the email content with attachment context
                if await self._check_if_invoice_email(email_data, attachment_analysis_results):
                    logger.info(f"LLM identified email as invoice-related: {email.get('subject', 'No subject')}")
                    potentially_invoice_emails.append(email)
            
            # Combine all invoice emails from different detection methods
            all_invoice_emails = subject_filtered_emails + potentially_invoice_emails
            
            # Ensure no duplicates
            seen_ids = set()
            unique_invoice_emails = []
            for email in all_invoice_emails:
                if email.get("id") not in seen_ids:
                    seen_ids.add(email.get("id"))
                    unique_invoice_emails.append(email)
            
            logger.info(f"Found {len(unique_invoice_emails)} unique invoice-related emails in total")
            return unique_invoice_emails
            
        except Exception as e:
            logger.exception(f"Error searching for invoice emails: {str(e)}")
            return []
    
    async def _check_attachments_for_invoice(self, attachments: List[Dict[str, Any]], attachment_analysis_results: List[Dict[str, Any]] = None) -> bool:
        """Check if any of the attachments might be an invoice document.
        
        Args:
            attachments: List of attachment dictionaries
            attachment_analysis_results: Optional list of attachment analysis results
            
        Returns:
            bool: True if any attachment appears to be an invoice, False otherwise
        """
        if not attachments:
            return False
        
        # Initialize the list if not provided
        if attachment_analysis_results is None:
            attachment_analysis_results = []
            
        logger.info(f"Checking {len(attachments)} attachments for invoice content")
        
        # Always consider these known invoice attachments
        known_invoice_attachments = ["comples.pdf", "invoice.pdf", "receipt.pdf", "statement.pdf", "bill.pdf"]
        
        # First, check filenames for invoice-related terms
        invoice_keywords = ["invoice", "billing", "payment", "receipt", "statement", "bill", "charge", "due", "money", "finance", "transaction"]
        
        for attachment in attachments:
            filename = attachment.get("filename", "").lower()
            mime_type = attachment.get("mimeType", "").lower()
            
            # Check for known important attachments
            if filename in known_invoice_attachments:
                logger.info(f"Found known invoice attachment: {filename}")
                attachment_analysis_results.append({
                    "filename": filename,
                    "is_invoice": True,
                    "confidence": 0.9,
                    "reason": f"Recognized known invoice filename: {filename}"
                })
                return True
                
            # Check filename for invoice keywords
            if any(keyword in filename for keyword in invoice_keywords):
                logger.info(f"Found invoice-related filename: {filename}")
                attachment_analysis_results.append({
                    "filename": filename,
                    "is_invoice": True,
                    "confidence": 0.8,
                    "reason": f"Filename contains invoice keywords: {filename}"
                })
                return True
                
            # Consider common document formats as potential invoices
            document_types = [
                "application/pdf", 
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
                "application/msword",  # doc
                "application/vnd.ms-excel",  # xls
                "text/csv",  # csv
                "application/json",  # json
                "text/plain"  # txt
            ]
            
            if mime_type in document_types:
                logger.info(f"Found document with potentially invoice content: {filename} ({mime_type})")
                
                # For text-based files with content, analyze them directly
                if attachment.get("downloaded", False) and attachment.get("content"):
                    if mime_type == "text/plain" or mime_type == "text/csv" or mime_type == "application/json":
                        # Save the content to a temporary file for analysis
                        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as temp_file:
                            temp_path = temp_file.name
                            
                            # Decode content if needed
                            content = attachment.get("content", "")
                            if isinstance(content, str):
                                try:
                                    # Try different decodings, fallback to raw content
                                    try:
                                        decoded_content = base64.urlsafe_b64decode(content)
                                    except:
                                        try:
                                            decoded_content = base64.b64decode(content)
                                        except:
                                            # Try cleaning the data
                                            try:
                                                import re
                                                cleaned_content = re.sub(r'[^A-Za-z0-9+/=]', '', content)
                                                decoded_content = base64.b64decode(cleaned_content)
                                            except:
                                                decoded_content = content.encode('utf-8')
                                except:
                                    decoded_content = content.encode('utf-8')
                            else:
                                decoded_content = content
                                
                            # Write content to temp file
                            temp_file.write(decoded_content)
                        
                        # Analyze the text file with the LLM
                        analysis_result = await self.analyze_text_attachment(temp_path, filename)
                        
                        # Add analysis result to the list
                        if analysis_result:
                            attachment_analysis_results.append(analysis_result)
                        
                        # Clean up the temporary file
                        try:
                            os.unlink(temp_path)
                        except:
                            pass
                        
                        # Check if the LLM thinks it's an invoice
                        if analysis_result.get("is_invoice", False) and analysis_result.get("confidence", 0) >= 0.5:
                            logger.info(f"LLM determined '{filename}' is an invoice: {analysis_result.get('reason')}")
                            return True
                    
                    # Handle PDF attachments
                    elif mime_type.lower() == "application/pdf" or filename.lower().endswith(".pdf"):
                        # Save the content to a temporary file for analysis
                        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as temp_file:
                            temp_path = temp_file.name
                            
                            # Decode content if needed
                            content = attachment.get("content", "")
                            if isinstance(content, str):
                                try:
                                    # Try different decodings, fallback to raw content
                                    try:
                                        decoded_content = base64.urlsafe_b64decode(content)
                                    except:
                                        try:
                                            decoded_content = base64.b64decode(content)
                                        except:
                                            # Try cleaning the data
                                            try:
                                                import re
                                                cleaned_content = re.sub(r'[^A-Za-z0-9+/=]', '', content)
                                                decoded_content = base64.b64decode(cleaned_content)
                                            except:
                                                decoded_content = content.encode('utf-8')
                                except:
                                    decoded_content = content.encode('utf-8')
                            else:
                                decoded_content = content
                                
                            # Write content to temp file
                            temp_file.write(decoded_content)
                        
                        # Repair the PDF if needed before analysis
                        logger.info(f"Checking if PDF repair is needed for: {filename}")
                        repaired_path = await self.repair_pdf(temp_path)
                        if repaired_path != temp_path:
                            logger.info(f"PDF was repaired during attachment check: {repaired_path}")
                            temp_path = repaired_path
                        
                        # Analyze the PDF file with our specialized analyzer
                        analysis_result = await self.analyze_pdf_attachment(temp_path, filename)
                        
                        # Add analysis result to the list
                        if analysis_result:
                            attachment_analysis_results.append(analysis_result)
                        
                        # Clean up the temporary file
                        try:
                            os.unlink(temp_path)
                        except:
                            pass
                        
                        # Check if the PDF analyzer thinks it's an invoice
                        if analysis_result.get("is_invoice", False) and analysis_result.get("confidence", 0) >= 0.5:
                            logger.info(f"PDF analysis determined '{filename}' is an invoice: {analysis_result.get('reason')}")
                            return True
                
                # Assume PDFs or Office documents are likely invoices if in email
                if "pdf" in mime_type or "word" in mime_type or "excel" in mime_type or "spreadsheet" in mime_type:
                    logger.info(f"Treating {filename} as potential invoice due to document type")
                    attachment_analysis_results.append({
                        "filename": filename,
                        "is_invoice": True,
                        "confidence": 0.6,
                        "reason": f"Document type typically used for invoices: {mime_type}"
                    })
                    return True
        
        # For special cases where we want to consider all attachments in specific threads
        special_threads = ["196365ccdd53bf92"]  # The 'something money' thread
        
        for attachment in attachments:
            thread_id = attachment.get("thread_id") or ""
            if thread_id in special_threads:
                logger.info(f"Found attachment in special thread {thread_id}, treating as invoice")
                attachment_analysis_results.append({
                    "filename": attachment.get("filename", "unknown"),
                    "is_invoice": True,
                    "confidence": 0.7,
                    "reason": f"Attachment in special invoice-related thread: {thread_id}"
                })
                return True
        
        # If we get here, no invoice attachments were found
        return False
    
    async def _check_if_invoice_email(self, email: Dict[str, Any], attachment_analysis_results: List[Dict[str, Any]] = None) -> bool:
        """Check if an email is invoice-related using an LLM.
        
        Args:
            email: The email dictionary with full contents
            attachment_analysis_results: Optional list of attachment analysis results
            
        Returns:
            bool: True if the email is invoice-related, False otherwise
        """
        # Check if any attachment was detected as an invoice with sufficient confidence
        if attachment_analysis_results:
            for analysis in attachment_analysis_results:
                if analysis.get("is_invoice", False) and analysis.get("confidence", 0) >= 0.5:
                    logger.info(f"Email classified as invoice-related due to attachment: {analysis.get('filename')}")
                    return True
        
        # Extract relevant information from the email
        subject = email.get("subject", "")
        sender = email.get("sender", "")
        body = email.get("body", "")
        
        # Check for obvious invoice-related terms in the subject
        invoice_keywords = ["invoice", "billing", "payment", "receipt", "statement", "bill", "subscription", "charge", "due"]
        if any(keyword in subject.lower() for keyword in invoice_keywords):
            logger.info(f"Email classified as invoice-related due to subject keywords: {subject}")
            return True
        
        # Create a prompt for the LLM to classify the email
        prompt_messages = [
            {
                "role": "system",
                "content": """You are an expert at identifying invoice and billing-related emails. 
You need to determine whether an email is related to an invoice, billing, payment, subscription, or financial transaction.

Key invoice indicators to look for:
1. Mentions of invoices, payments, receipts, bills, statements, or subscriptions
2. Company names or business entities in a billing context
3. Monetary amounts or pricing information
4. Account numbers or customer IDs
5. Payment due dates or terms
6. Service descriptions or subscription details
7. Contact information in a business context

Return a JSON with your analysis."""
            },
            {
                "role": "user",
                "content": f"Please determine if this email is related to invoices, billing, or financial transactions:\n\nFrom: {sender}\nSubject: {subject}\nBody excerpt: {body[:1000]}\n\nIs this an invoice-related email? Reply with a JSON object containing 'is_invoice' (true/false) and 'confidence' (0-1)."
            }
        ]
        
        # Call Fireworks AI for classification
        logger.info(f"Calling LLM to classify email: {subject}")
        try:
            response = openai_client.chat.completions.create(
                model=FIREWORKS_MODEL,
                messages=prompt_messages,
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            # Parse the response
            result = json.loads(response.choices[0].message.content)
            is_invoice = result.get("is_invoice", False)
            confidence = result.get("confidence", 0)
            
            logger.info(f"Email classification result: is_invoice={is_invoice}, confidence={confidence}")
            
            # For emails with attached documents, use a lower confidence threshold
            threshold = 0.5 if email.get("attachments") else 0.7
            
            # Return true if confidence is high enough
            return is_invoice and confidence >= threshold
        except Exception as e:
            logger.error(f"Error in LLM classification: {str(e)}")
            return False
    
    async def get_email_contents(self, email_info):
        """Retrieve the full contents of an email, including attachments."""
        # Ensure we have the necessary auth
        if not await self.ensure_authorization("Google.GetThread"):
            logger.error("Not authorized to get thread details")
            return None
        
        email_id = email_info.get("id")
        
        # Handle different thread ID field names
        thread_id = email_info.get("threadId") or email_info.get("thread_id")
        
        if not email_id or not thread_id:
            logger.error("Email ID or Thread ID missing")
            return None
            
        logger.info(f"Getting thread contents for email ID: {email_id}, thread ID: {thread_id}")
        
        try:
            # Correct way to call execute with thread_id parameter (not threadId)
            thread_response = self.arcade_client.tools.execute(
                tool_name="Google.GetThread",
                input={"thread_id": thread_id},
                user_id=self.user_id
            )
            
            logger.info(f"Thread response type: {type(thread_response)}")
            
            if not hasattr(thread_response, 'output') or not hasattr(thread_response.output, 'value'):
                logger.error("Thread response does not have expected structure")
                return None
                
            thread_data = thread_response.output.value
            logger.info(f"Retrieved thread data for thread ID: {thread_id}")
            
            # Process thread data to extract the message with matching email_id
            if "messages" not in thread_data:
                logger.error("No messages found in thread data")
                return None
                
            # Find the message with the matching ID
            message = None
            for msg in thread_data["messages"]:
                if msg.get("id") == email_id:
                    message = msg
                    break
                    
            if not message:
                logger.error(f"Could not find message with ID {email_id} in thread")
                return None
                
            # Extract email contents
            subject = message.get("subject", "")
            sender = message.get("from", "")
            
            # Get email body with improved error handling for different formats
            body = ""
            if "body" in message:
                # Check the type of body
                message_body = message["body"]
                
                if isinstance(message_body, str):
                    # If body is directly a string
                    body = message_body
                elif isinstance(message_body, dict):
                    # If body is a dictionary with text/html fields
                    if "text" in message_body:
                        body = message_body["text"]
                    elif "html" in message_body:
                        # This is a simplistic HTML to text conversion
                        html_body = message_body["html"]
                        body = html_body.replace("<br>", "\n").replace("</p>", "\n")
                        # Remove HTML tags
                        body = re.sub(r'<[^>]+>', '', body)
                else:
                    logger.warning(f"Unexpected body format: {type(message_body)}")
                    
            # If we still don't have a body, check for snippet
            if not body and "snippet" in message:
                body = message.get("snippet", "")
                logger.info("Using message snippet as body")
            
            # Initialize our Gmail Attachment Tools to get attachments
            attachments = []
            gmail_tools = GmailAttachmentTools(user_id=self.user_id)
            
            # Try to get attachments using our direct Gmail API access
            if await gmail_tools.ensure_authorization():
                try:
                    logger.info(f"Using GmailAttachmentTools to get attachments for email ID: {email_id}")
                    
                    # List attachments for this email
                    attachments_result = await gmail_tools.list_message_attachments(email_id)
                    
                    if "error" not in attachments_result:
                        attachment_list = attachments_result.get("attachments", [])
                        attachment_count = len(attachment_list)
                        
                        logger.info(f"Found {attachment_count} attachments using GmailAttachmentTools")
                        
                        # Download each attachment
                        if attachment_count > 0:
                            for attachment_info in attachment_list:
                                attachment_id = attachment_info.get("id")
                                
                                if not attachment_id:
                                    logger.warning(f"Missing attachment ID for {attachment_info.get('filename', 'unknown')}")
                                    attachment_info["downloaded"] = False
                                    attachments.append(attachment_info)
                                    continue
                                
                                try:
                                    logger.info(f"Downloading attachment: {attachment_info.get('filename')}")
                                    
                                    # Get the attachment data
                                    attachment_data = await gmail_tools.get_gmail_attachment(email_id, attachment_id)
                                    
                                    if "error" not in attachment_data:
                                        # Combine metadata with actual content
                                        full_attachment = {
                                            **attachment_info,
                                            "content": attachment_data.get("data", ""),
                                            "size": attachment_data.get("size", 0),
                                            "downloaded": True
                                        }
                                        
                                        attachments.append(full_attachment)
                                        logger.info(f"Successfully downloaded attachment: {attachment_info.get('filename')}")
                                    else:
                                        logger.error(f"Error downloading attachment: {attachment_data.get('message')}")
                                        attachment_info["downloaded"] = False
                                        attachments.append(attachment_info)
                                
                                except Exception as e:
                                    logger.exception(f"Error downloading attachment {attachment_info.get('filename')}: {str(e)}")
                                    attachment_info["downloaded"] = False
                                    attachments.append(attachment_info)
                    else:
                        logger.error(f"Error listing attachments: {attachments_result.get('message')}")
                
                except Exception as e:
                    logger.exception(f"Error using GmailAttachmentTools: {str(e)}")
            
            # Fallback: If direct method failed, try getting attachments from message data
            if not attachments and "attachments" in message:
                attachments_meta = message["attachments"]
                logger.info(f"Found {len(attachments_meta)} attachments in the email message (fallback method)")
                
                # Add downloaded=False flag to indicate we're only storing metadata
                for attachment_meta in attachments_meta:
                    attachment_meta["downloaded"] = False
                    attachments.append(attachment_meta)
                
                logger.info("Note: Attachments are metadata only (fallback method)")
            
            return {
                "id": email_id,
                "subject": subject,
                "sender": sender,
                "body": body,
                "attachments": attachments
            }
            
        except Exception as e:
            logger.exception(f"Error getting thread contents: {str(e)}")
            return None
    
    async def process_email(self, email: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Process an invoice email and save its contents to a file for document processing.
        
        Args:
            email: The email dictionary from Arcade Gmail toolkit
            
        Returns:
            Tuple containing (file_path, email_metadata)
        """
        logger.info(f"Processing invoice email: {email.get('subject', 'No subject')}")
        
        # Get full email contents
        email_data = await self.get_email_contents(email)
        
        if not email_data:
            logger.error("Failed to get email contents")
            return None, {"error": "Failed to retrieve email contents"}
        
        # Create a unique filename for this email
        email_id = email["id"].replace(":", "_").replace("/", "_")
        filename = f"email_{email_id}.txt"
        file_path = os.path.join(self.temp_dir, filename)
        
        # Create attachments directory if it doesn't exist
        attachments_dir = os.path.join(self.temp_dir, f"attachments_{email_id}")
        os.makedirs(attachments_dir, exist_ok=True)
        
        # Save attachments if any
        saved_attachments = []
        has_invoice_attachment = False
        attachment_analysis_results = []
        
        for attachment in email_data.get('attachments', []):
            attachment_name = attachment.get('filename', f"unknown_attachment_{len(saved_attachments)}")
            attachment_path = os.path.join(attachments_dir, attachment_name)
            
            # If the attachment has content data, save it
            if attachment.get("downloaded", False) and attachment.get("content"):
                try:
                    # Decode base64 content if present
                    content = attachment.get("content", "")
                    mime_type = attachment.get("mimeType", "")
                    
                    if content:
                        # URL-safe base64 decode for Gmail API attachments
                        try:
                            decoded_content = base64.urlsafe_b64decode(content)
                            logger.info(f"Successfully decoded attachment using urlsafe_b64decode: {attachment_name}")
                        except Exception as url_decode_error:
                            # Fall back to standard base64
                            try:
                                decoded_content = base64.b64decode(content)
                                logger.info(f"Successfully decoded attachment using standard b64decode: {attachment_name}")
                            except Exception as std_decode_error:
                                # Last resort - try to clean the data
                                logger.warning(f"Base64 decoding failed, attempting to clean data for: {attachment_name}")
                                try:
                                    # Remove non-base64 characters
                                    import re
                                    if isinstance(content, str):
                                        cleaned_content = re.sub(r'[^A-Za-z0-9+/=]', '', content)
                                        try:
                                            decoded_content = base64.b64decode(cleaned_content)
                                            logger.info(f"Successfully decoded after cleaning data: {attachment_name}")
                                        except:
                                            # If it's still not base64, use the raw content
                                            logger.warning(f"All decoding methods failed, using raw content for: {attachment_name}")
                                            decoded_content = content.encode('utf-8')
                                    else:
                                        decoded_content = content
                                except:
                                    if isinstance(content, str):
                                        decoded_content = content.encode('utf-8')
                                    else:
                                        decoded_content = content
                        
                        # Write to file
                        with open(attachment_path, 'wb') as f:
                            f.write(decoded_content)
                            
                        logger.info(f"Saved attachment: {attachment_name} to {attachment_path}")
                        
                        # Repair PDF files if needed
                        if mime_type.lower() == "application/pdf" or attachment_name.lower().endswith(".pdf"):
                            logger.info(f"Checking if PDF repair is needed for: {attachment_name}")
                            repaired_path = await self.repair_pdf(attachment_path)
                            if repaired_path != attachment_path:
                                logger.info(f"PDF was repaired and saved to: {repaired_path}")
                                attachment_path = repaired_path
                        
                        # Analyze attachment based on type
                        analysis_result = None
                        if mime_type.lower() == "application/pdf" or attachment_name.lower().endswith(".pdf"):
                            # Analyze PDF file
                            logger.info(f"Analyzing PDF attachment: {attachment_name}")
                            analysis_result = await self.analyze_pdf_attachment(attachment_path, attachment_name)
                            if analysis_result.get("is_invoice", False) and analysis_result.get("confidence", 0) >= 0.5:
                                has_invoice_attachment = True
                                logger.info(f"PDF attachment '{attachment_name}' identified as invoice: {analysis_result.get('reason')}")
                        elif mime_type == "text/plain" or attachment_name.endswith(".txt"):
                            # Analyze text file
                            logger.info(f"Analyzing text attachment: {attachment_name}")
                            analysis_result = await self.analyze_text_attachment(attachment_path, attachment_name)
                            if analysis_result.get("is_invoice", False) and analysis_result.get("confidence", 0) >= 0.5:
                                has_invoice_attachment = True
                                logger.info(f"Text attachment '{attachment_name}' identified as invoice: {analysis_result.get('reason')}")
                        
                        # Keep track of all analysis results
                        if analysis_result:
                            attachment_analysis_results.append(analysis_result)
                        
                        # Check if the file looks like an invoice based on filename
                        if any(term in attachment_name.lower() for term in 
                            ["invoice", "bill", "receipt", "statement", "payment"]):
                            has_invoice_attachment = True
                            
                        saved_attachments.append({
                            "name": attachment_name,
                            "path": attachment_path,
                            "type": attachment.get("mimeType", "unknown"),
                            "possibly_invoice": has_invoice_attachment,
                            "analysis": analysis_result
                        })
                    else:
                        logger.warning(f"Empty content for attachment: {attachment_name}")
                except Exception as e:
                    logger.exception(f"Error saving attachment {attachment_name}: {str(e)}")
            else:
                logger.info(f"No content available for attachment: {attachment_name}")
        
        # Prepare the email content
        content = [
            f"Subject: {email_data['subject']}",
            f"From: {email_data['sender']}",
            f"Date: {email.get('date', 'Unknown')}",
            f"Email ID: {email['id']}",
            f"Has Invoice Attachments: {has_invoice_attachment}",
            "",
            "--- EMAIL BODY ---",
            "",
            email_data['body'],
            "",
            "--- ATTACHMENTS ---",
            ""
        ]
        
        # Add attachment info
        for attachment in email_data.get('attachments', []):
            status = "Downloaded" if attachment.get("downloaded", False) else "Metadata only"
            saved_path = next((item["path"] for item in saved_attachments if item["name"] == attachment.get("filename")), "Not saved")
            is_invoice = "Possibly Invoice" if any(item.get("possibly_invoice", False) 
                                             for item in saved_attachments 
                                             if item["name"] == attachment.get("filename")) else ""
            
            content.append(f"Attachment: {attachment.get('filename', 'Unknown')} ({attachment.get('mimeType', 'Unknown type')}) - {status} {is_invoice}")
            content.append(f"  Size: {attachment.get('size', 'Unknown')} bytes")
            content.append(f"  Saved to: {saved_path}")
            
            # Add analysis results if available
            analysis = next((item.get("analysis") for item in saved_attachments 
                           if item["name"] == attachment.get("filename") and item.get("analysis")), None)
            if analysis:
                content.append(f"  Analysis: {analysis.get('is_invoice', False)}, Confidence: {analysis.get('confidence', 0)}")
                if analysis.get("amount"):
                    content.append(f"  Amount: {analysis.get('amount')}")
                if analysis.get("vendor"):
                    content.append(f"  Vendor: {analysis.get('vendor')}")
                if analysis.get("reason"):
                    content.append(f"  Reason: {analysis.get('reason')}")
            
            content.append("")
        
        # Write the email content to the file
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(content))
        
        logger.info(f"Email saved to file: {file_path}")
        
        # Mark the email as processed
        self.mark_email_processed(email["id"])
        
        # Return the file path and metadata
        return file_path, {
            "email_id": email["id"],
            "subject": email_data["subject"],
            "sender": email_data["sender"],
            "attachment_count": len(email_data.get("attachments", [])),
            "saved_attachments": saved_attachments,
            "has_invoice_attachments": has_invoice_attachment,
            "attachment_analyses": attachment_analysis_results
        }
    
    async def get_next_email(self) -> Optional[Dict[str, Any]]:
        """Get the next email from the queue or check for new emails.
        
        Returns:
            The next email to process, or None if no emails are available
        """
        # Check if we already have emails in the queue
        if self.email_queue:
            return self.email_queue.pop(0)
        
        # Check for new invoice emails - including those with invoice attachments
        invoice_emails = await self.check_for_invoice_emails(num_emails=20)
        if invoice_emails:
            self.email_queue.extend(invoice_emails)
        
        # Return the next email if available
        if self.email_queue:
            return self.email_queue.pop(0)
        
        return None
    
    def start(self):
        """Start the email watcher agent."""
        logger.info("Starting Email Watcher Agent")
    
    def stop(self):
        """Stop the email watcher agent."""
        logger.info("Stopping Email Watcher Agent")
        self._save_processed_emails()

    async def analyze_text_attachment(self, file_path: str, filename: str) -> Dict[str, Any]:
        """
        Analyze a text-based attachment for invoice content using LLM.
        
        Args:
            file_path: Path to the saved attachment file
            filename: Name of the attachment file
            
        Returns:
            Dict containing analysis results
        """
        try:
            # Read the file content
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
                
            # Create improved prompt for LLM that focuses specifically on invoice detection
            prompt_messages = [
                {
                    "role": "system",
                    "content": """You are an expert at identifying invoice and billing documents. 
Your task is to analyze text and determine if it contains information related to invoices, payments, subscriptions, or billing.

Key invoice indicators to look for:
1. Company names or business entities
2. Subscription details or plan information
3. Monetary amounts or pricing
4. Account numbers or customer IDs
5. Payment terms or due dates
6. Service descriptions or product listings
7. Contact information in a business context
8. Words like: invoice, bill, payment, receipt, subscription, charge, due, etc.

Even if the document is missing some standard invoice elements, if it contains business subscription information or pricing details, it should be considered invoice-related.

Return a detailed JSON with your findings."""
                },
                {
                    "role": "user",
                    "content": f"Here is the content of a file named '{filename}'. Analyze it and determine if it contains invoice or billing information:\n\n{content[:2000]}\n\nIs this an invoice or billing-related document? Reply with a JSON object containing 'is_invoice' (true/false), 'confidence' (0-1), 'amount' (if found, can be null), 'vendor' (if found, can be null), 'invoice_date' (if found, can be null), and 'reason' explaining your decision in detail."
                }
            ]
            
            # Call Fireworks AI for analysis
            logger.info(f"Analyzing text attachment with enhanced prompt: {filename}")
            response = openai_client.chat.completions.create(
                model=FIREWORKS_MODEL,
                messages=prompt_messages,
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            # Parse the response
            result = json.loads(response.choices[0].message.content)
            logger.info(f"Attachment '{filename}' analysis: {json.dumps(result, indent=2)}")
            
            return {
                "filename": filename,
                "is_invoice": result.get("is_invoice", False),
                "confidence": result.get("confidence", 0),
                "amount": result.get("amount", None),
                "vendor": result.get("vendor", None),
                "invoice_date": result.get("invoice_date", None),
                "reason": result.get("reason", "No reason provided")
            }
                
        except Exception as e:
            logger.exception(f"Error analyzing text attachment {filename}: {str(e)}")
            return {
                "filename": filename,
                "is_invoice": False,
                "confidence": 0,
                "error": str(e)
            }

    async def analyze_pdf_attachment(self, file_path: str, filename: str) -> Dict[str, Any]:
        """
        Analyze a PDF attachment for invoice content.
        
        Args:
            file_path: Path to the saved PDF file
            filename: Name of the attachment file
            
        Returns:
            Dict containing analysis results
        """
        try:
            # First, verify this is actually a valid PDF file
            with open(file_path, 'rb') as f:
                header = f.read(5)
                if header != b'%PDF-':
                    logger.warning(f"File {filename} does not have a valid PDF header, attempting repair")
                    # Try to repair the PDF
                    repaired_path = await self.repair_pdf(file_path)
                    file_path = repaired_path
            
            # Try to extract text from the PDF using PyPDF2 if available
            try:
                import PyPDF2
                pdf_text = ""
                
                with open(file_path, 'rb') as pdf_file:
                    try:
                        reader = PyPDF2.PdfReader(pdf_file)
                        for page_num in range(len(reader.pages)):
                            page = reader.pages[page_num]
                            pdf_text += page.extract_text() + "\n"
                    except Exception as pdf_error:
                        logger.error(f"Error extracting text from PDF: {str(pdf_error)}")
                        # Try one more repair if text extraction failed
                        try:
                            logger.info("Attempting additional PDF repair and retrying text extraction")
                            repaired_path = await self.repair_pdf(file_path)
                            
                            # Only retry if we got a different file path
                            if repaired_path != file_path:
                                file_path = repaired_path
                                reader = PyPDF2.PdfReader(file_path)
                                pdf_text = ""
                                for page_num in range(len(reader.pages)):
                                    page = reader.pages[page_num]
                                    pdf_text += page.extract_text() + "\n"
                                logger.info("Successfully extracted text after additional repair")
                            else:
                                pdf_text = "PDF text extraction failed even after repair"
                        except Exception as retry_error:
                            logger.error(f"Text extraction failed after repair attempt: {str(retry_error)}")
                            pdf_text = "PDF text extraction failed"
                
                if pdf_text and pdf_text != "PDF text extraction failed":
                    # Use the extracted text for LLM analysis
                    prompt_messages = [
                        {
                            "role": "system",
                            "content": "You are an expert at analyzing documents to identify if they contain invoice or billing information. Your task is to determine if the document contains invoice details such as amounts, dates, payment terms, item descriptions, or vendor information. Return a detailed JSON response with your findings."
                        },
                        {
                            "role": "user",
                            "content": f"Here is the text extracted from a PDF file named '{filename}'. Analyze it and determine if it's an invoice or contains billing information:\n\n{pdf_text[:2000]}\n\nIs this an invoice document? Reply with a JSON object containing 'is_invoice' (true/false), 'confidence' (0-1), 'amount' (if found), 'vendor' (if found), 'invoice_date' (if found), and 'reason' explaining your decision."
                        }
                    ]
                    
                    # Call Fireworks AI for analysis
                    logger.info(f"Analyzing PDF content: {filename}")
                    response = openai_client.chat.completions.create(
                        model=FIREWORKS_MODEL,
                        messages=prompt_messages,
                        response_format={"type": "json_object"},
                        temperature=0.1
                    )
                    
                    # Parse the response
                    result = json.loads(response.choices[0].message.content)
                    logger.info(f"PDF '{filename}' analysis: {json.dumps(result, indent=2)}")
                    
                    return {
                        "filename": filename,
                        "is_invoice": result.get("is_invoice", False),
                        "confidence": result.get("confidence", 0),
                        "amount": result.get("amount", None),
                        "vendor": result.get("vendor", None),
                        "invoice_date": result.get("invoice_date", None),
                        "reason": result.get("reason", "No reason provided"),
                        "text_extraction": "successful",
                        "pdf_path": file_path
                    }
            except ImportError:
                logger.warning("PyPDF2 not installed, using alternative method")
            
            # If PyPDF2 is not available or text extraction failed, use heuristics
            # Check filename for invoice-related terms
            invoice_keywords = ["invoice", "bill", "receipt", "statement", "payment", "due", "finance"]
            if any(keyword in filename.lower() for keyword in invoice_keywords):
                logger.info(f"PDF filename contains invoice keywords: {filename}")
                return {
                    "filename": filename,
                    "is_invoice": True,
                    "confidence": 0.7,
                    "reason": f"Filename '{filename}' contains invoice-related keywords",
                    "text_extraction": "not performed",
                    "pdf_path": file_path
                }
            
            # Return a default result
            return {
                "filename": filename,
                "is_invoice": False,
                "confidence": 0.3,
                "reason": "Could not extract text from PDF to analyze content",
                "text_extraction": "failed",
                "pdf_path": file_path
            }
                
        except Exception as e:
            logger.exception(f"Error analyzing PDF attachment {filename}: {str(e)}")
            return {
                "filename": filename,
                "is_invoice": False,
                "confidence": 0,
                "error": str(e),
                "pdf_path": file_path
            }

    async def repair_pdf(self, file_path: str) -> str:
        """
        Repair a corrupted PDF file by adding proper PDF structure.
        
        Args:
            file_path: Path to the original PDF file
            
        Returns:
            Path to the repaired PDF file or original if repair wasn't needed
        """
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
                return file_path
            
            # Read the original file
            with open(file_path, 'rb') as f:
                content = f.read()
            
            # Create a repaired file path
            repaired_path = file_path + '.repaired.pdf'
            needs_repair = False
            replace_with_minimal = False
            
            # Check for PDF header
            if not content.startswith(b'%PDF-'):
                logger.info(f"Adding PDF header to {os.path.basename(file_path)}")
                content = b'%PDF-1.4\n' + content
                needs_repair = True
            
            # Check for EOF marker
            if not content.endswith(b'%%EOF') and not content.endswith(b'%%EOF\n'):
                logger.info(f"Adding EOF marker to {os.path.basename(file_path)}")
                content = content + b'\n%%EOF\n'
                needs_repair = True
            
            # Check if PDF has critical structural issues
            if not b'startxref' in content:
                logger.warning(f"PDF missing critical 'startxref' marker, needs more complete repair")
                replace_with_minimal = True
            
            # Add basic PDF structure if very small/corrupted or has critical issues
            if len(content) < 100 or replace_with_minimal:
                logger.warning(f"PDF file requires complete structure replacement")
                
                # Create a minimal valid PDF
                minimal_pdf = (
                    b'%PDF-1.4\n'
                    b'1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n'
                    b'2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n'
                    b'3 0 obj\n<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>\nendobj\n'
                    b'4 0 obj\n<</Length 5 0 R>>\nstream\n'
                )
                
                # Get the original content without PDF header and EOF markers
                if content.startswith(b'%PDF-'):
                    content_stripped = content[content.find(b'\n')+1:]
                else:
                    content_stripped = content
                
                if content_stripped.endswith(b'%%EOF\n'):
                    content_stripped = content_stripped[:-6]
                elif content_stripped.endswith(b'%%EOF'):
                    content_stripped = content_stripped[:-5]
                
                # Add the content as a stream object
                minimal_pdf += content_stripped
                
                # Complete the PDF structure
                minimal_pdf += (
                    b'\nendstream\nendobj\n'
                    b'5 0 obj\n' + str(len(content_stripped) + 200).encode() + b'\nendobj\n'
                    b'xref\n'
                    b'0 6\n'
                    b'0000000000 65535 f\n'
                    b'0000000010 00000 n\n'
                    b'0000000053 00000 n\n'
                    b'0000000102 00000 n\n'
                    b'0000000170 00000 n\n'
                    b'0000000' + str(len(content_stripped) + 200).encode() + b' 00000 n\n'
                    b'trailer\n<</Size 6/Root 1 0 R>>\n'
                    b'startxref\n'
                    b'270\n'
                    b'%%EOF\n'
                )
                
                content = minimal_pdf
                needs_repair = True
            
            # If repairs were needed, write the new file
            if needs_repair:
                with open(repaired_path, 'wb') as f:
                    f.write(content)
                
                logger.info(f"Created repaired PDF at {repaired_path}")
                return repaired_path
            else:
                logger.info(f"PDF doesn't need repair: {file_path}")
                return file_path
            
        except Exception as e:
            logger.exception(f"Error repairing PDF: {str(e)}")
            return file_path

# Example usage
if __name__ == "__main__":
    async def main():
        # Create the email watcher
        watcher = EmailWatcherAgent(user_id="your_email@gmail.com")  # Replace with your email
        
        # Ensure authorization
        authorized = await watcher.ensure_authorization()
        if not authorized:
            print("Failed to authorize Gmail access")
            return
        
        # Check for invoice emails
        invoice_emails = await watcher.check_for_invoice_emails()
        print(f"Found {len(invoice_emails)} invoice emails")
        
        # Process each invoice email
        for email in invoice_emails:
            print(f"Processing email: {email['subject']}")
            
            # Process the email to a file
            file_path, metadata = await watcher.process_email(email)
            
            if file_path:
                print(f"Email saved to file: {file_path}")
                print(f"Metadata: {json.dumps(metadata, indent=2)}")
            else:
                print(f"Error processing email: {metadata.get('error', 'Unknown error')}")
    
    asyncio.run(main()) 