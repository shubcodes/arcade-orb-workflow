#!/usr/bin/env python3
import os
import time
import json
import asyncio
import logging
import threading
import queue
from typing import Set, Dict
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Import the workflow
from workflow import app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Directory to monitor
DOCS_DIR = "documents"
# Supported file extensions
SUPPORTED_EXTENSIONS = ('.txt', '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.tiff')
# File to store processed files
PROCESSED_FILES_LOG = "processed_files.json"

# Define our own run_workflow_for_file function based on the one in workflow.py
async def run_workflow_for_file(file_path):
    """Run the workflow for a specific file."""
    initial_input = {"document_path": file_path}
    config = {"recursion_limit": 10}
    logger.info(f"Running workflow for: {file_path}")
    try:
        final_state = await app.ainvoke(initial_input, config=config)
        logger.info(f"Workflow finished for: {file_path}")
        logger.info(f"Final State: {json.dumps(final_state, indent=2, default=str)}")
        return final_state
    except Exception as e:
        logger.error(f"Workflow FAILED for: {file_path} --- Error: {e}")
        raise

class DocumentEventHandler(FileSystemEventHandler):
    """Handler for file system events in the documents directory."""
    
    def __init__(self, processed_files: Set[str], thread_queue):
        self.processed_files = processed_files
        # Use a thread-safe queue for communication between threads
        self.thread_queue = thread_queue
    
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
                    # Use thread-safe queue instead of asyncio queue directly
                    self.thread_queue.put(file_path)
                    logger.info(f"Added to processing queue: {file_path}")
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
                    # Use thread-safe queue
                    self.thread_queue.put(file_path)
                    logger.info(f"Added modified file to processing queue: {file_path}")

async def process_files(asyncio_queue, processed_files):
    """Process files in the asyncio queue."""
    while True:
        file_path = await asyncio_queue.get()
        try:
            logger.info(f"Processing document: {file_path}")
            # Run workflow for the file
            await run_workflow_for_file(file_path)
            # Mark as processed
            processed_files.add(file_path)
            # Save processed files log
            save_processed_files(processed_files)
            logger.info(f"Completed processing: {file_path}")
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
        finally:
            asyncio_queue.task_done()

def load_processed_files() -> Set[str]:
    """Load the set of already processed files."""
    if os.path.exists(PROCESSED_FILES_LOG):
        try:
            with open(PROCESSED_FILES_LOG, 'r') as f:
                data = json.load(f)
                return set(data.get("files", []))
        except Exception as e:
            logger.error(f"Error loading processed files log: {e}")
    return set()

def save_processed_files(processed_files: Set[str]):
    """Save the set of processed files."""
    try:
        with open(PROCESSED_FILES_LOG, 'w') as f:
            json.dump({
                "files": list(processed_files),
                "last_updated": datetime.now().isoformat()
            }, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving processed files log: {e}")

async def initialize_queue(asyncio_queue, docs_dir, processed_files):
    """Initialize queue with existing files that haven't been processed."""
    if not os.path.exists(docs_dir):
        os.makedirs(docs_dir)
        logger.info(f"Created documents directory: {docs_dir}")
    
    # Check existing files
    for filename in os.listdir(docs_dir):
        file_path = os.path.join(docs_dir, filename)
        if os.path.isfile(file_path) and file_path.lower().endswith(SUPPORTED_EXTENSIONS):
            if file_path not in processed_files:
                logger.info(f"Adding existing file to queue: {file_path}")
                await asyncio_queue.put(file_path)

async def queue_monitor(thread_queue, asyncio_queue):
    """Monitor the thread queue and move items to the asyncio queue."""
    while True:
        try:
            # Non-blocking check to avoid blocking the event loop
            while not thread_queue.empty():
                file_path = thread_queue.get_nowait()
                await asyncio_queue.put(file_path)
                thread_queue.task_done()
        except queue.Empty:
            pass  # Queue is empty, that's fine
        except Exception as e:
            logger.error(f"Error in queue monitor: {e}")
        
        # Wait a bit before checking again
        await asyncio.sleep(0.1)

async def main():
    """Main function to start the file watcher."""
    # Load processed files
    processed_files = load_processed_files()
    logger.info(f"Loaded {len(processed_files)} previously processed files")
    
    # Create queues
    thread_queue = queue.Queue()  # Thread-safe queue for the watchdog events
    asyncio_queue = asyncio.Queue()  # Asyncio queue for actual processing
    
    # Create event handler and observer
    event_handler = DocumentEventHandler(processed_files, thread_queue)
    observer = Observer()
    observer.schedule(event_handler, DOCS_DIR, recursive=False)
    
    try:
        # Start the observer
        observer.start()
        logger.info(f"Started watching directory: {DOCS_DIR}")
        
        # Initialize processing queue with existing files
        await initialize_queue(asyncio_queue, DOCS_DIR, processed_files)
        
        # Start processing task
        processing_task = asyncio.create_task(process_files(asyncio_queue, processed_files))
        
        # Start queue monitor task
        queue_monitor_task = asyncio.create_task(queue_monitor(thread_queue, asyncio_queue))
        
        # Keep the main task running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping file watcher (Ctrl+C pressed)")
    finally:
        # Clean up
        observer.stop()
        observer.join()

if __name__ == "__main__":
    logger.info("Starting document processing file watcher")
    asyncio.run(main())
