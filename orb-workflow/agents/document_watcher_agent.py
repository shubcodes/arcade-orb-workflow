#!/usr/bin/env python3
import os
import time
import json
import logging
import queue
from typing import Set, Dict, List, Optional
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# File to store processed files
PROCESSED_FILES_LOG = "processed_files.json"
# Supported file extensions
SUPPORTED_EXTENSIONS = ('.txt', '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.tiff')

class DocumentQueue:
    """Thread-safe document queue for communication between agents"""
    def __init__(self):
        self.queue = queue.Queue()
        
    def add_document(self, file_path: str):
        """Add a document to the queue"""
        self.queue.put(file_path)
        logger.info(f"Added to processing queue: {file_path}")
        
    def get_document(self) -> Optional[str]:
        """Get the next document from the queue"""
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None
    
    def task_done(self):
        """Mark a document as processed"""
        self.queue.task_done()

class DocumentEventHandler(FileSystemEventHandler):
    """Handler for file system events in the documents directory."""
    
    def __init__(self, processed_files: Set[str], document_queue: DocumentQueue):
        self.processed_files = processed_files
        self.document_queue = document_queue
    
    def on_created(self, event):
        """Handle file creation events."""
        # Only process file events (not directories)
        if not event.is_directory:
            file_path = event.src_path
            # Check if file has supported extension
            if file_path.lower().endswith(SUPPORTED_EXTENSIONS):
                logger.info(f"New document detected: {file_path}")
                # Add to processing queue if not already processed
                if file_path not in self.processed_files:
                    # Give the file system a moment to finish writing
                    time.sleep(1)
                    # Add to queue
                    self.document_queue.add_document(file_path)
                else:
                    logger.info(f"File already processed, skipping: {file_path}")
    
    def on_modified(self, event):
        """Handle file modification events."""
        # For simplicity, treat modifications of already processed files as new files
        if not event.is_directory:
            file_path = event.src_path
            if file_path.lower().endswith(SUPPORTED_EXTENSIONS):
                if file_path in self.processed_files:
                    logger.info(f"Modified document detected: {file_path}")
                    # Remove from processed files to process it again
                    self.processed_files.remove(file_path)
                    # Add to processing queue
                    time.sleep(1)  # Give file system time to finish writing
                    self.document_queue.add_document(file_path)

class DocumentWatcherAgent:
    """Agent that watches a directory for new documents."""
    
    def __init__(self, docs_dir="documents"):
        self.docs_dir = docs_dir
        self.processed_files = self._load_processed_files()
        self.document_queue = DocumentQueue()
        
        # Create the directory if it doesn't exist
        if not os.path.exists(self.docs_dir):
            os.makedirs(self.docs_dir)
            logger.info(f"Created documents directory: {self.docs_dir}")
        
        # Initialize the observer
        self.event_handler = DocumentEventHandler(self.processed_files, self.document_queue)
        self.observer = Observer()
        self.observer.schedule(self.event_handler, self.docs_dir, recursive=False)
    
    def _load_processed_files(self) -> Set[str]:
        """Load the set of already processed files."""
        if os.path.exists(PROCESSED_FILES_LOG):
            try:
                with open(PROCESSED_FILES_LOG, 'r') as f:
                    data = json.load(f)
                    return set(data.get("files", []))
            except Exception as e:
                logger.error(f"Error loading processed files log: {e}")
        return set()
    
    def _save_processed_files(self):
        """Save the set of processed files."""
        try:
            with open(PROCESSED_FILES_LOG, 'w') as f:
                json.dump({
                    "files": list(self.processed_files),
                    "last_updated": datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving processed files log: {e}")
    
    def get_existing_unprocessed_files(self) -> List[str]:
        """Get list of existing files that haven't been processed."""
        unprocessed_files = []
        
        for filename in os.listdir(self.docs_dir):
            file_path = os.path.join(self.docs_dir, filename)
            if (os.path.isfile(file_path) and 
                file_path.lower().endswith(SUPPORTED_EXTENSIONS) and
                file_path not in self.processed_files):
                unprocessed_files.append(file_path)
                logger.info(f"Found unprocessed file: {file_path}")
        
        return unprocessed_files
    
    def queue_existing_files(self):
        """Add existing unprocessed files to the queue."""
        unprocessed_files = self.get_existing_unprocessed_files()
        for file_path in unprocessed_files:
            self.document_queue.add_document(file_path)
    
    def mark_as_processed(self, file_path: str):
        """Mark a file as processed."""
        self.processed_files.add(file_path)
        self._save_processed_files()
    
    def start(self):
        """Start watching for new documents."""
        logger.info(f"Starting document watcher agent")
        logger.info(f"Loaded {len(self.processed_files)} previously processed files")
        
        # Queue existing unprocessed files
        self.queue_existing_files()
        
        # Start the observer
        self.observer.start()
        logger.info(f"Started watching directory: {self.docs_dir}")
    
    def stop(self):
        """Stop watching for new documents."""
        logger.info("Stopping document watcher agent")
        self.observer.stop()
        self.observer.join()
    
    def get_next_document(self) -> Optional[str]:
        """Get the next document from the queue."""
        return self.document_queue.get_document()
    
    def document_processed(self):
        """Mark the current document as done."""
        self.document_queue.task_done()

# Example usage
if __name__ == "__main__":
    watcher = DocumentWatcherAgent()
    watcher.start()
    
    try:
        # Keep the main thread running
        while True:
            # Check for new documents
            next_doc = watcher.get_next_document()
            if next_doc:
                print(f"Processing: {next_doc}")
                # In a real implementation, you would pass this to the next agent
                # For now, just mark it as processed
                watcher.mark_as_processed(next_doc)
                watcher.document_processed()
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        watcher.stop() 