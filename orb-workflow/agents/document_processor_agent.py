#!/usr/bin/env python3
import os
import json
import base64
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import openai
from fireworks.client import Fireworks

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

if not FIREWORKS_API_KEY:
    raise ValueError("FIREWORKS_API_KEY environment variable not set.")

# Use OpenAI's client with Fireworks base URL for better compatibility with document inlining
openai_client = openai.OpenAI(
    base_url="https://api.fireworks.ai/inference/v1",
    api_key=FIREWORKS_API_KEY
)
fireworks_client = Fireworks(api_key=FIREWORKS_API_KEY)
FIREWORKS_MODEL = "accounts/fireworks/models/llama4-maverick-instruct-basic"

class DocumentProcessorAgent:
    """Agent that processes documents using Fireworks document inlining."""
    
    def __init__(self):
        """Initialize the agent with the Fireworks API key."""
        logger.info("Initializing Document Processor Agent")
        
        # Ensure API key is set
        if not FIREWORKS_API_KEY:
            raise ValueError("FIREWORKS_API_KEY environment variable not set.")
    
    async def process_document(self, document_path: str) -> Dict[str, Any]:
        """Process a document and extract structured information."""
        logger.info(f"Processing document: {document_path}")
        
        try:
            # Check if the file is a text file or binary file
            if document_path.lower().endswith('.txt'):
                extracted_data = await self._process_text_document(document_path)
            else:
                extracted_data = await self._process_binary_document(document_path)
            
            logger.info(f"Extracted data: {json.dumps(extracted_data, indent=2)}")
            return {
                "document_path": document_path,
                "extracted_data": extracted_data,
                "error": None
            }
        except Exception as e:
            logger.error(f"Error processing document {document_path}: {e}")
            import traceback
            traceback.print_exc()
            return {
                "document_path": document_path,
                "extracted_data": None,
                "error": str(e)
            }
    
    async def _process_text_document(self, document_path: str) -> Dict[str, Any]:
        """Process a text document and extract information."""
        logger.info(f"Processing text document: {document_path}")
        
        # Read the file content
        with open(document_path, 'r', encoding='utf-8') as f:
            document_content = f.read()
        
        # Create prompt for text document
        prompt_messages = [
            {
                "role": "system",
                "content": "You are an expert assistant specializing in extracting billing information from documents. Extract customer name, email/contact, subscription/plan type, number of seats/users, and any addons. Return the information in a JSON format."
            },
            {
                "role": "user",
                "content": f"Please extract the billing information from the following document:\n\n{document_content}"
            }
        ]
        
        # Call Fireworks AI for extraction
        logger.info(f"Calling Fireworks AI ({FIREWORKS_MODEL}) for text extraction")
        response = fireworks_client.chat.completions.create(
            model=FIREWORKS_MODEL,
            messages=prompt_messages,
            response_format={"type": "json_object"},
            temperature=0.1
        )
        
        # Parse the JSON response
        raw_json = response.choices[0].message.content
        if raw_json:
            return json.loads(raw_json)
        else:
            raise ValueError("Fireworks AI returned empty content.")
    
    async def _process_binary_document(self, document_path: str) -> Dict[str, Any]:
        """Process a binary document (PDF, image) using document inlining."""
        logger.info(f"Processing binary document: {document_path}")
        
        # Read the file content and determine content type
        with open(document_path, 'rb') as f:
            document_bytes = f.read()
        
        # Determine content type based on file extension
        if document_path.lower().endswith('.pdf'):
            content_type = "application/pdf"
        elif document_path.lower().endswith(('.jpg', '.jpeg')):
            content_type = "image/jpeg"
        elif document_path.lower().endswith('.png'):
            content_type = "image/png"
        elif document_path.lower().endswith('.gif'):
            content_type = "image/gif"
        elif document_path.lower().endswith('.tiff'):
            content_type = "image/tiff"
        else:
            content_type = "application/octet-stream"
        
        # Base64 encode the document
        document_content = base64.b64encode(document_bytes).decode('utf-8')
        
        # Create inline URL with transform parameter for document inlining
        inline_url = f"data:{content_type};base64,{document_content}#transform=inline"
        
        # Call Fireworks AI for extraction with document inlining
        logger.info(f"Calling Fireworks AI ({FIREWORKS_MODEL}) for document inlining")
        response = openai_client.chat.completions.create(
            model=FIREWORKS_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert assistant specializing in extracting billing information from documents. Extract customer name, email/contact, subscription/plan type, number of seats/users, and any addons. Return the information in a JSON format."
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": inline_url
                            }
                        },
                        {
                            "type": "text",
                            "text": "Extract the billing information from this document and return it as a JSON object with keys such as customer/company name, email/contact, subscription/plan, seats/users, and addons if present."
                        }
                    ]
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        
        # Parse the JSON response
        raw_json = response.choices[0].message.content
        if raw_json:
            return json.loads(raw_json)
        else:
            raise ValueError("Fireworks AI returned empty content.")

# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def main():
        processor = DocumentProcessorAgent()
        
        # Example text document
        text_result = await processor.process_document("documents/contract_abc.txt")
        print("Text Document Result:", json.dumps(text_result, indent=2))
        
        # Example PDF document - if you have one
        try:
            pdf_result = await processor.process_document("documents/mock_customer_single.pdf")
            print("PDF Document Result:", json.dumps(pdf_result, indent=2))
        except FileNotFoundError:
            print("PDF document not found. Skipping test.")
    
    asyncio.run(main()) 