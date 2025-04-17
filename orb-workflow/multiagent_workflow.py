#!/usr/bin/env python3
"""
Multi-Agent Orb Billing Workflow

This script runs the multi-agent Orb billing workflow system, which:
1. Watches for documents in the 'documents' directory
2. Processes them using Fireworks document inlining
3. Configures billing using Arcade worker tools
"""

import asyncio
import logging
import os
import sys

# Add the current directory to the path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the orchestrator
from agents.orchestrator import OrbWorkflowOrchestrator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

async def main():
    """Main function that runs the multi-agent orchestrator."""
    logger.info("Starting Multi-Agent Orb Billing Workflow")
    
    # Create and start the orchestrator
    orchestrator = OrbWorkflowOrchestrator()
    
    try:
        # Start the orchestrator
        await orchestrator.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, exiting")
    except Exception as e:
        logger.error(f"Unhandled error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    try:
        # Run the main function
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, exiting")
    except Exception as e:
        logger.error(f"Unhandled error: {e}")
        import traceback
        traceback.print_exc() 