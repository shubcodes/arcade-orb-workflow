#!/usr/bin/env python
import os
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def fix_pdf(pdf_path):
    """Fix a corrupted PDF by adding a proper header."""
    logger.info(f"Examining PDF file: {pdf_path}")
    
    # Check if file exists
    if not os.path.exists(pdf_path):
        logger.error(f"File not found: {pdf_path}")
        return None
    
    # Read the original file
    with open(pdf_path, 'rb') as f:
        content = f.read()
    
    # Check if it already has a PDF header
    if content.startswith(b'%PDF-'):
        logger.info("PDF already has a proper header")
        return pdf_path
    
    # Create a fixed PDF with proper header
    fixed_path = pdf_path + '.fixed.pdf'
    
    # Add proper PDF header
    fixed_content = b'%PDF-1.4\n' + content
    
    # Write the fixed content
    with open(fixed_path, 'wb') as f:
        f.write(fixed_content)
    
    logger.info(f"Created fixed PDF at {fixed_path}")
    
    # Verify the fixed PDF
    with open(fixed_path, 'rb') as f:
        header = f.read(5)
        if header == b'%PDF-':
            logger.info("Successfully repaired PDF header")
        else:
            logger.error("Failed to repair PDF header")
    
    # Try to inspect with PyPDF2 if available
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(fixed_path)
        logger.info(f"Successfully opened PDF with PyPDF2. Pages: {len(reader.pages)}")
        
        # Try to extract text from first page
        if len(reader.pages) > 0:
            text = reader.pages[0].extract_text()
            logger.info(f"First page text preview: {text[:100]}")
    except ImportError:
        logger.warning("PyPDF2 not available, skipping PDF content inspection")
    except Exception as e:
        logger.error(f"Error inspecting fixed PDF: {str(e)}")
    
    return fixed_path

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        # Use the default path if none provided
        pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                            "documents/email_temp/attachments_196365ccdd53bf92/comples.pdf")
    else:
        pdf_path = sys.argv[1]
    
    fixed_pdf = fix_pdf(pdf_path)
    
    if fixed_pdf:
        print(f"\nFixed PDF is available at: {fixed_pdf}")
    else:
        print("\nFailed to fix PDF") 