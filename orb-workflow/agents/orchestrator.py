#!/usr/bin/env python3
import os
import json
import time
import asyncio
import logging
from typing import Dict, Any, List

# Import the agents
from .document_watcher_agent import DocumentWatcherAgent
from .document_processor_agent import DocumentProcessorAgent
from .billing_configurator_agent import BillingConfiguratorAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class OrbWorkflowOrchestrator:
    """Orchestrates the multi-agent workflow for processing documents and configuring billing."""
    
    def __init__(self):
        """Initialize the orchestrator with its agents."""
        logger.info("Initializing Orb Workflow Orchestrator")
        
        # Initialize agents
        self.watcher_agent = DocumentWatcherAgent()
        self.processor_agent = DocumentProcessorAgent()
        self.configurator_agent = BillingConfiguratorAgent()
        
        # Initialize state
        self.processing_status = {}
    
    async def start(self):
        """Start the orchestrator and all agents."""
        logger.info("Starting Orb Workflow Orchestrator")
        
        # Start the watcher agent
        self.watcher_agent.start()
        
        # Enter the main processing loop
        try:
            await self._main_loop()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, stopping orchestrator")
        finally:
            # Stop the watcher agent
            self.watcher_agent.stop()
    
    async def _main_loop(self):
        """Main processing loop of the orchestrator."""
        logger.info("Entering main processing loop")
        
        while True:
            # Get the next document from the watcher agent
            document_path = self.watcher_agent.get_next_document()
            
            if document_path:
                logger.info(f"Received document: {document_path}")
                
                try:
                    # Process the document
                    await self._process_document(document_path)
                finally:
                    # Mark the document as done in the queue
                    self.watcher_agent.document_processed()
            
            # Sleep a bit to avoid busy-waiting
            await asyncio.sleep(0.5)
    
    async def _process_document(self, document_path):
        """Process a single document through the agent pipeline."""
        try:
            # Step 1: Process document with the processor agent
            logger.info(f"Processing document: {document_path}")
            processor_result = await self.processor_agent.process_document(document_path)
            
            # Check for errors
            if processor_result.get("error"):
                logger.error(f"Error processing document: {processor_result['error']}")
                self.processing_status[document_path] = {
                    "status": "error",
                    "error": processor_result["error"],
                    "timestamp": time.time()
                }
                return
            
            # Step 2: Configure billing with the configurator agent
            logger.info(f"Configuring billing for document: {document_path}")
            billing_result = await self.configurator_agent.configure_billing(
                processor_result["extracted_data"]
            )
            
            # Check for errors
            if billing_result.get("configuration_error"):
                logger.error(f"Error configuring billing: {billing_result['configuration_error']}")
                self.processing_status[document_path] = {
                    "status": "error",
                    "error": billing_result["configuration_error"],
                    "timestamp": time.time()
                }
                return
            
            # Success - Update status and mark document as processed
            logger.info(f"Successfully processed document: {document_path}")
            self.processing_status[document_path] = {
                "status": "success",
                "extracted_data": processor_result["extracted_data"],
                "customer_id": billing_result["customer_id"],
                "subscription_id": billing_result["subscription_id"],
                "timestamp": time.time()
            }
            
            # Mark the document as processed in the watcher agent
            self.watcher_agent.mark_as_processed(document_path)
            
        except Exception as e:
            logger.error(f"Unhandled error processing document {document_path}: {e}")
            import traceback
            traceback.print_exc()
            self.processing_status[document_path] = {
                "status": "error",
                "error": str(e),
                "timestamp": time.time()
            }
    
    def get_processing_status(self) -> Dict[str, Dict[str, Any]]:
        """Get the current processing status for all documents."""
        return self.processing_status
    
    def get_processed_documents(self) -> List[str]:
        """Get the list of successfully processed documents."""
        return [
            doc_path for doc_path, status in self.processing_status.items()
            if status.get("status") == "success"
        ]
    
    def get_failed_documents(self) -> List[str]:
        """Get the list of documents that failed processing."""
        return [
            doc_path for doc_path, status in self.processing_status.items()
            if status.get("status") == "error"
        ]

if __name__ == "__main__":
    # Create and start the orchestrator
    orchestrator = OrbWorkflowOrchestrator()
    
    async def main():
        # Start the orchestrator
        await orchestrator.start()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, exiting")
    except Exception as e:
        logger.error(f"Unhandled error: {e}")
        import traceback
        traceback.print_exc() 