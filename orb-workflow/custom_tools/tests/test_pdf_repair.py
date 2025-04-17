#!/usr/bin/env python3
import asyncio
import os
import logging
import sys
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Import the EmailWatcherAgent
from agents.email_watcher_agent import EmailWatcherAgent

async def test_pdf_repair_and_analysis():
    """Test the PDF repair and analysis functionality."""
    print("\n===== Testing PDF Repair and Analysis =====")
    
    # Load environment variables
    load_dotenv()
    
    # Get the email address from environment
    email_address = os.getenv("TEST_EMAIL_ADDRESS", "sargha@umich.edu")
    
    # Create EmailWatcherAgent instance
    agent = EmailWatcherAgent(user_id=email_address)
    
    # Define the path to the PDF
    pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                         "documents/email_temp/attachments_196365ccdd53bf92/comples.pdf")
    
    if not os.path.exists(pdf_path):
        print(f"Source PDF not found at {pdf_path}")
        print("Looking for any PDF file...")
        
        # Try to find any PDF file in the documents directory
        pdf_found = False
        for root, dirs, files in os.walk(os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents")):
            for file in files:
                if file.lower().endswith(".pdf"):
                    pdf_path = os.path.join(root, file)
                    pdf_found = True
                    print(f"Found PDF at: {pdf_path}")
                    break
            if pdf_found:
                break
        
        if not pdf_found:
            print("No PDF file found. Creating a test PDF...")
            
            # Create a simple test PDF
            test_pdf_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents/test_pdf")
            os.makedirs(test_pdf_dir, exist_ok=True)
            pdf_path = os.path.join(test_pdf_dir, "test_invoice.pdf")
            
            # Create a corrupted PDF file (missing proper header and structure)
            with open(pdf_path, "wb") as f:
                f.write(b"This is a corrupted PDF file with invoice information.\n")
                f.write(b"Invoice #12345\n")
                f.write(b"Date: April 15, 2025\n")
                f.write(b"Amount: $1,234.56\n")
            
            print(f"Created test PDF at: {pdf_path}")
    
    print(f"\nRepairing PDF: {pdf_path}")
    
    # Call the repair_pdf method
    repaired_path = await agent.repair_pdf(pdf_path)
    
    print(f"Original PDF: {pdf_path}")
    print(f"Repaired PDF: {repaired_path}")
    
    # Check if the PDF was actually repaired
    was_repaired = repaired_path != pdf_path
    print(f"PDF was repaired: {was_repaired}")
    
    # Analyze the repaired PDF
    print("\nAnalyzing PDF...")
    analysis_result = await agent.analyze_pdf_attachment(repaired_path, os.path.basename(repaired_path))
    
    print("\nAnalysis Results:")
    for key, value in analysis_result.items():
        print(f"  {key}: {value}")
    
    # Optional: If PyPDF2 is available, try to extract text
    try:
        import PyPDF2
        print("\nAttempting to extract text from PDF using PyPDF2...")
        
        with open(repaired_path, 'rb') as pdf_file:
            try:
                reader = PyPDF2.PdfReader(pdf_file)
                num_pages = len(reader.pages)
                print(f"Successfully opened PDF with PyPDF2. Pages: {num_pages}")
                
                # Try to extract text from first page
                if num_pages > 0:
                    try:
                        text = reader.pages[0].extract_text()
                        print(f"First page text preview: {text[:100]}")
                    except Exception as text_error:
                        print(f"Error extracting text: {str(text_error)}")
            except Exception as pdf_error:
                print(f"Error reading PDF: {str(pdf_error)}")
    except ImportError:
        print("PyPDF2 not available, skipping text extraction test.")
    
    return repaired_path, analysis_result

async def main():
    # Run the test
    repaired_path, analysis_result = await test_pdf_repair_and_analysis()
    
    print("\n===== Test Complete =====")
    print(f"Repaired PDF available at: {repaired_path}")
    print(f"Is invoice: {analysis_result.get('is_invoice', False)}, Confidence: {analysis_result.get('confidence', 0)}")

if __name__ == "__main__":
    asyncio.run(main()) 