#!/usr/bin/env python3
import os
import base64
from typing import Dict, Any, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from arcadepy import Arcade

class GmailAttachmentTools:
    """
    Tools for handling Gmail attachments using Arcade's auth system.
    """
    
    def __init__(self, user_id: str):
        """
        Initialize with a user ID for authentication.
        
        Args:
            user_id: The user's email or unique identifier
        """
        self.user_id = user_id
        self.arcade_client = Arcade()  # Automatically uses ARCADE_API_KEY from env
        self.gmail_service = None
    
    async def ensure_authorization(self) -> bool:
        """
        Ensure the user is authorized to access their Gmail.
        
        Returns:
            bool: True if authorized, False otherwise
        """
        try:
            auth_response = self.arcade_client.tools.authorize(
                tool_name="Google.ListEmails",  # Use an existing Google tool for auth
                user_id=self.user_id
            )
            
            if auth_response.status != "completed":
                print(f"Please authorize access by visiting: {auth_response.url}")
                auth_response = self.arcade_client.auth.wait_for_completion(auth_response)
            
            if not hasattr(auth_response, 'context') or not hasattr(auth_response.context, 'token'):
                print("Authorization completed but no token received")
                return False
            
            # Create Gmail service with the token
            credentials = Credentials(auth_response.context.token)
            self.gmail_service = build("gmail", "v1", credentials=credentials)
            return True
            
        except Exception as e:
            print(f"Error during Gmail authorization: {str(e)}")
            return False
    
    async def list_message_attachments(self, message_id: str) -> Dict[str, Any]:
        """
        List all attachments in a Gmail message.
        
        Args:
            message_id: The ID of the Gmail message
            
        Returns:
            Dict containing attachment metadata
        """
        if not self.gmail_service:
            if not await self.ensure_authorization():
                return {"error": "Not authorized", "message": "Failed to authorize Gmail access"}
        
        try:
            # Get the email message
            message = self.gmail_service.users().messages().get(
                userId="me", 
                id=message_id
            ).execute()
            
            # Find attachments in the message payload
            attachments = []
            
            if "payload" in message and "parts" in message["payload"]:
                for part in message["payload"]["parts"]:
                    if part.get("body", {}).get("attachmentId"):
                        attachments.append({
                            "id": part["body"]["attachmentId"],
                            "filename": part.get("filename", f"attachment_{part['body']['attachmentId']}"),
                            "mimeType": part.get("mimeType", "application/octet-stream"),
                            "size": part["body"].get("size", 0)
                        })
            
            return {
                "messageId": message_id,
                "attachments": attachments,
                "count": len(attachments)
            }
            
        except HttpError as error:
            error_details = {
                "error": str(error),
                "message": f"Failed to retrieve attachments list for message {message_id}"
            }
            return error_details
    
    async def get_gmail_attachment(self, message_id: str, attachment_id: str) -> Dict[str, Any]:
        """
        Retrieve an attachment from a Gmail message.
        
        Args:
            message_id: The ID of the Gmail message
            attachment_id: The ID of the attachment to retrieve
            
        Returns:
            Dict containing the attachment data
        """
        if not self.gmail_service:
            if not await self.ensure_authorization():
                return {"error": "Not authorized", "message": "Failed to authorize Gmail access"}
        
        try:
            # Get the attachment from the message
            attachment = self.gmail_service.users().messages().attachments().get(
                userId="me",
                messageId=message_id,
                id=attachment_id
            ).execute()
            
            # Get the email message to get the attachment filename and other metadata
            message = self.gmail_service.users().messages().get(
                userId="me", 
                id=message_id
            ).execute()
            
            # Find the attachment metadata in the message payload
            attachment_metadata = None
            
            if "payload" in message and "parts" in message["payload"]:
                for part in message["payload"]["parts"]:
                    if part.get("body", {}).get("attachmentId") == attachment_id:
                        attachment_metadata = part
                        break
            
            # Gmail API returns data in URL-safe base64 format
            # Let's ensure it's valid by checking and padding if necessary
            data = attachment.get("data", "")
            size = attachment.get("size", 0)
            
            # Add proper base64 padding if needed
            if data:
                # Calculate padding needed (if any)
                padding_needed = 4 - (len(data) % 4) if len(data) % 4 else 0
                if padding_needed:
                    data += "=" * padding_needed
                    print(f"Added {padding_needed} padding characters to base64 data")
                
            # Build the response
            result = {
                "id": attachment_id,
                "messageId": message_id,
                "data": data,  # Base64-encoded attachment data
                "size": size,
            }
            
            # Add metadata if available
            if attachment_metadata:
                result["filename"] = attachment_metadata.get("filename", f"attachment_{attachment_id}")
                result["mimeType"] = attachment_metadata.get("mimeType", "application/octet-stream")
                
            return result
            
        except HttpError as error:
            error_details = {
                "error": str(error),
                "message": f"Failed to retrieve attachment {attachment_id} from message {message_id}"
            }
            return error_details

# Example usage:
async def main():
    # Set user ID
    user_id = os.getenv("TEST_EMAIL_ADDRESS")
    if not user_id:
        print("Please set TEST_EMAIL_ADDRESS environment variable")
        return
    
    print(f"Using email address: {user_id}")
    
    # Initialize the tools
    gmail_tools = GmailAttachmentTools(user_id=user_id)
    
    # Ensure authorization
    if not await gmail_tools.ensure_authorization():
        print("Failed to authorize Gmail access")
        return
    
    # Use a hardcoded message ID or take from command line
    import sys
    message_id = "196365ccdd53bf92"  # Default message ID (the "something money" email)
    if len(sys.argv) > 1:
        message_id = sys.argv[1]
        
    print(f"Using message ID: {message_id}")
    
    # List attachments
    print("Listing attachments...")
    attachments_result = await gmail_tools.list_message_attachments(message_id)
    
    if "error" in attachments_result:
        print(f"Error listing attachments: {attachments_result['message']}")
        return
    
    attachments = attachments_result.get("attachments", [])
    print(f"Found {len(attachments)} attachments")
    
    # Download each attachment
    for attachment in attachments:
        attachment_id = attachment["id"]
        filename = attachment["filename"]
        mime_type = attachment.get("mimeType", "unknown")
        
        print(f"Downloading attachment: {filename} ({mime_type})")
        
        attachment_data = await gmail_tools.get_gmail_attachment(message_id, attachment_id)
        
        if "error" in attachment_data:
            print(f"Error downloading attachment: {attachment_data['message']}")
            continue
        
        # Save the attachment
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "documents", "attachments")
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
                
                try:
                    # First try URL-safe base64 decoding (Gmail API standard)
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
                        # Last resort, just use the raw data if it's already bytes
                        if isinstance(data, bytes):
                            decoded_data = data
                        else:
                            decoded_data = data.encode('utf-8')
                        print("Using raw data as fallback")
                
                f.write(decoded_data)
                print(f"Saved attachment to: {output_path}")
                
                # Validate PDF if the attachment is a PDF
                if mime_type.lower() == "application/pdf" or filename.lower().endswith(".pdf"):
                    try:
                        with open(output_path, "rb") as pdf_file:
                            header = pdf_file.read(5)
                            if header != b"%PDF-":
                                print(f"WARNING: {filename} does not have a valid PDF header!")
                                print(f"First 20 bytes: {repr(pdf_file.read(20))}")
                            else:
                                print(f"Validated PDF file: {filename} has proper header")
                    except Exception as pdf_error:
                        print(f"Error validating PDF: {str(pdf_error)}")
                
            except Exception as e:
                print(f"Error saving attachment: {str(e)}")
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main()) 