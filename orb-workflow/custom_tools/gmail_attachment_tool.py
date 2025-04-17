#!/usr/bin/env python3
import base64
from typing import Annotated, Dict, Any, Optional

from arcade.sdk import ToolContext, tool
from arcade.sdk.auth import Google

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


@tool(
    requires_auth=Google(
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
)
async def get_gmail_attachment(
    context: ToolContext,
    message_id: Annotated[str, "The ID of the Gmail message containing the attachment"],
    attachment_id: Annotated[str, "The ID of the attachment to retrieve"],
) -> Annotated[Dict[str, Any], "The attachment data including filename, content (base64), size, and mimeType"]:
    """
    Retrieve an attachment from a Gmail message.
    
    This tool accesses the Gmail API to download a specific attachment from a specified email.
    """
    if not context.authorization or not context.authorization.token:
        raise ValueError("No token found in context")
    
    try:
        # Create credentials from the token
        credentials = Credentials(context.authorization.token)
        
        # Build the Gmail service
        gmail_service = build("gmail", "v1", credentials=credentials)
        
        # Get the attachment from the message
        attachment = gmail_service.users().messages().attachments().get(
            userId="me",
            messageId=message_id,
            id=attachment_id
        ).execute()
        
        # Get the email message to get the attachment filename and other metadata
        message = gmail_service.users().messages().get(
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
                # We can't log with print in the tool, but return info about padding
                size_info = f"Original size: {len(data)-padding_needed}, Padded size: {len(data)}"
                
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


@tool(
    requires_auth=Google(
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
)
async def list_message_attachments(
    context: ToolContext,
    message_id: Annotated[str, "The ID of the Gmail message to check for attachments"],
) -> Annotated[Dict[str, Any], "Information about attachments in the message"]:
    """
    List all attachments in a Gmail message.
    
    This tool accesses the Gmail API to retrieve metadata about all attachments in a specific email.
    """
    if not context.authorization or not context.authorization.token:
        raise ValueError("No token found in context")
    
    try:
        # Create credentials from the token
        credentials = Credentials(context.authorization.token)
        
        # Build the Gmail service
        gmail_service = build("gmail", "v1", credentials=credentials)
        
        # Get the email message
        message = gmail_service.users().messages().get(
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