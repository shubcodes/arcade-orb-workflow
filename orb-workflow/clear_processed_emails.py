#!/usr/bin/env python3
import os
import json
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def clear_processed_emails():
    """Clear the processed emails memory file."""
    # Get the directory of the processed emails file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    email_temp_dir = os.path.join(script_dir, "documents", "email_temp")
    processed_emails_path = os.path.join(email_temp_dir, "processed_emails.json")
    
    # Check if the file exists
    if os.path.exists(processed_emails_path):
        # Backup the existing file (optional)
        backup_path = processed_emails_path + ".bak"
        try:
            with open(processed_emails_path, 'r') as f:
                existing_data = json.load(f)
                
            with open(backup_path, 'w') as f:
                json.dump(existing_data, f)
                logger.info(f"Backed up existing processed emails to {backup_path}")
        except Exception as e:
            logger.warning(f"Could not backup processed emails: {str(e)}")
        
        # Clear the file by writing an empty list
        with open(processed_emails_path, 'w') as f:
            json.dump([], f)
            logger.info(f"Cleared processed emails file at {processed_emails_path}")
    else:
        # Create the directory if it doesn't exist
        os.makedirs(email_temp_dir, exist_ok=True)
        
        # Create an empty processed emails file
        with open(processed_emails_path, 'w') as f:
            json.dump([], f)
            logger.info(f"Created empty processed emails file at {processed_emails_path}")
    
    return processed_emails_path

if __name__ == "__main__":
    cleared_path = clear_processed_emails()
    print(f"\n✅ Successfully cleared processed emails memory at: {cleared_path}")
    print("The agent will now process all emails as if they were new in the next run.") 