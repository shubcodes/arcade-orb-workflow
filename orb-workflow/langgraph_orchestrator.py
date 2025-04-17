#!/usr/bin/env python3
import os
import json
import time
import asyncio
import logging
from typing import Dict, Any, List, TypedDict, Optional
from dotenv import load_dotenv

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

# Import the existing agents
from agents.document_watcher_agent import DocumentWatcherAgent
from agents.document_processor_agent import DocumentProcessorAgent
from agents.billing_configurator_agent import BillingConfiguratorAgent
from agents.email_watcher_agent import EmailWatcherAgent
from agents.slack_human_verification_agent import SlackHumanVerificationAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Define the state for our workflow
class WorkflowState(TypedDict):
    document_path: Optional[str]
    document_data: Optional[Dict[str, Any]]
    extracted_data: Optional[Dict[str, Any]] # Data before verification
    extraction_error: Optional[str]
    verified_data: Optional[Dict[str, Any]] # Data after successful verification
    is_verified: Optional[bool] # Flag indicating verification status
    verification_error: Optional[str] # Error during verification process
    is_valid_for_billing: Optional[bool] # Flag indicating data passes pre-billing validation
    validation_error: Optional[str] # Error message from validation
    original_slack_thread_ts: Optional[str] # Store the TS of the initial verification message
    slack_channel_id: Optional[str] # Store the channel ID for replies
    customer_id: Optional[str]
    subscription_id: Optional[str]
    configuration_result: Optional[Dict[str, Any]]
    configuration_error: Optional[str]
    source: Optional[str]  # "email" or "file"
    email_data: Optional[Dict[str, Any]]  # Data about the email source
    status: str  # "pending", "processing", "success", "error"
    error_message: Optional[str]
    # Removed skip_email_check as the main loop handles timing
    # skip_email_check: Optional[bool]

# Initialize the agents
document_watcher = DocumentWatcherAgent()
document_processor = DocumentProcessorAgent()
billing_configurator = BillingConfiguratorAgent()
email_watcher = EmailWatcherAgent(user_id=os.getenv("TEST_EMAIL_ADDRESS", "shub.arcade@gmail.com"))
slack_verifier = SlackHumanVerificationAgent(user_id=os.getenv("SLACK_USER_ID", "default_slack_user"))

# Define the nodes for the processing pipeline
# (check_email_node and get_document_node are removed as their logic is in the main loop)

async def process_document_node_async(state: WorkflowState) -> Dict[str, Any]:
    """Node that processes the document specified in the state to extract information."""
    logger.info("Running process_document_node")
    
    document_path = state.get("document_path")
    if not document_path:
        logger.error("process_document_node called without document_path in state.")
        return {
            **state,
            "status": "error",
            "extraction_error": "Missing document_path",
            "error_message": "Internal error: process_document_node triggered without document_path."
        }
    
    logger.info(f"Processing document: {document_path}")
    try:
        result = await document_processor.process_document(document_path)
        
        if result.get("error"):
            logger.error(f"Error processing document {document_path}: {result['error']}")
            return {
                **state,
                "status": "error",
                "extraction_error": result["error"],
                "error_message": f"Document processing failed: {result['error']}"
            }
        
        logger.info(f"Successfully extracted data from: {document_path}")
        return {
            **state,
            "extracted_data": result["extracted_data"],
            "document_data": result,
            "status": "processing" # Keep status as "processing" - moving to next step
        }
    except Exception as e:
        logger.exception(f"Unhandled error processing document {document_path}: {e}")
        return {
            **state,
            "status": "error",
            "extraction_error": str(e),
            "error_message": f"Unhandled error during document processing: {str(e)}"
        }

def process_document_node(state: WorkflowState) -> Dict[str, Any]:
    """Synchronous wrapper for process_document_node_async."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(process_document_node_async(state))
    finally:
        loop.close()

async def human_verification_node_async(state: WorkflowState) -> Dict[str, Any]:
    """Node that sends extracted data for human verification via Slack."""
    logger.info("Running human_verification_node")

    extracted_data = state.get("extracted_data")
    document_path = state.get("document_path", "Unknown document")
    if not extracted_data:
        logger.warning(f"No extracted data found for verification (document: {document_path}).")
        return {
            **state,
            "status": "error",
            "is_verified": False,
            "verification_error": "No extracted data to verify",
            "error_message": "Verification skipped: No extracted data."
        }

    try:
        logger.info(f"Calling Slack verification agent for document: {document_path}")
        # Use appropriate timeouts/retries for production
        # Agent now returns tuple: (verified_data, original_thread_ts, channel_id)
        verified_data_tuple = await slack_verifier.request_and_wait_for_verification(
            extracted_data, timeout_seconds=600, max_retries=5
        )

        if verified_data_tuple:
            verified_data, original_thread_ts, channel_id = verified_data_tuple
            logger.info(f"Slack verification successful for {document_path}. Original Ts: {original_thread_ts}")
            return {
                **state,
                "verified_data": verified_data,
                "is_verified": True,
                "original_slack_thread_ts": original_thread_ts, # Store thread info
                "slack_channel_id": channel_id, # Store channel info
                "verification_error": None,
                "status": "processing" # Keep status processing, moving to validation
            }
        else:
            logger.error(f"Slack verification failed or timed out for {document_path}.")
            return {
                **state,
                "is_verified": False,
                "verified_data": None, # Ensure verified data is cleared on failure
                "verification_error": "Verification failed or timed out in Slack",
                "status": "error",
                "error_message": f"Human verification via Slack failed or timed out for {document_path}."
            }
    except Exception as e:
        logger.exception(f"Unhandled error during Slack verification for {document_path}: {e}")
        return {
            **state,
            "is_verified": False,
            "verified_data": None,
            "verification_error": str(e),
            "status": "error",
            "error_message": f"Unhandled error during Slack verification: {str(e)}"
        }

def human_verification_node(state: WorkflowState) -> Dict[str, Any]:
    """Synchronous wrapper for human_verification_node_async."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(human_verification_node_async(state))
    finally:
        loop.close()

def validate_data_node(state: WorkflowState) -> Dict[str, Any]:
    """Node that validates the verified data before sending to billing."""
    logger.info("Running validate_data_node")
    verified_data = state.get("verified_data")
    document_path = state.get("document_path", "Unknown document")

    if not verified_data:
        logger.warning(f"No verified data to validate for {document_path}")
        return {
            **state,
            "is_valid_for_billing": False,
            "validation_error": "No verified data available for validation",
            "status": "error",
            "error_message": "Validation skipped: No verified data."
        }

    logger.info(f"Validating data for {document_path}.")
    # billing_configurator.validate_data is synchronous
    is_valid, error_msg = billing_configurator.validate_data(verified_data)

    if is_valid:
        logger.info(f"Data for {document_path} passed validation.")
        return {
            **state,
            "is_valid_for_billing": True,
            "validation_error": None,
            "status": "processing" # Still processing, next is configure_billing
        }
    else:
        logger.error(f"Data for {document_path} failed validation. Error: {error_msg}")
        return {
            **state,
            "is_valid_for_billing": False,
            "validation_error": error_msg,
            "status": "error", # Set status to error *if validation fails and we intend to stop*
                            # If looping back to user, keep status 'processing'? Let's set error for now.
            "error_message": f"Data validation failed: {error_msg}"
        }

# New node to inform user of validation errors via Slack
async def inform_user_of_validation_error_node_async(state: WorkflowState) -> Dict[str, Any]:
    """Sends the validation error back to the user in the Slack thread."""
    logger.info("Running inform_user_of_validation_error_node")
    validation_error = state.get("validation_error", "Unknown validation error")
    thread_ts = state.get("original_slack_thread_ts")
    channel_id = state.get("slack_channel_id")
    document_path = state.get("document_path", "Unknown document")

    if not thread_ts or not channel_id:
        logger.error(f"Cannot inform user of validation error for {document_path}: Missing original_slack_thread_ts or slack_channel_id in state.")
        # Cannot recover, move to mark processed
        return {
            **state,
            "status": "error", # Ensure status reflects the inability to inform user
            "error_message": "Internal error: Missing Slack thread details to report validation error."
         }

    error_message_to_user = f":warning: Validation failed for {os.path.basename(document_path)}: *{validation_error}*\nPlease provide the missing/correct information in the NEW THREAD so I can try again."

    try:
        logger.info(f"Sending validation error to user in thread {thread_ts}")
        reply_ts = await slack_verifier.slack_helper.send_reply_in_thread(channel_id, thread_ts, error_message_to_user)

        if not reply_ts:
            logger.error(f"Failed to send validation error message to Slack thread {thread_ts}.")
            # Still treat as an error state even if Slack message failed
            return {
                 **state,
                 "status": "error",
                 "error_message": "Failed to send validation error to Slack."
            }

        # Successfully informed user, reset state to loop back to verification
        logger.info(f"Validation error sent to user (Reply TS: {reply_ts}). Resetting state for re-verification.")
        return {
            **state,
            "verified_data": None, # Clear verified data
            "is_verified": None, # Reset verification flag
            "is_valid_for_billing": None, # Reset validation flag
            "status": "processing", # Keep processing, loop back to human_verification
            "validation_error": None, # Clear the error after sending
            # Keep original_slack_thread_ts and slack_channel_id for the loop
        }
    except Exception as e:
        logger.exception(f"Error sending validation error to Slack: {e}")
        return {
            **state,
            "status": "error",
            "error_message": f"Failed to send validation error to Slack: {e}"
        }

def inform_user_of_validation_error_node(state: WorkflowState) -> Dict[str, Any]:
    """Sync wrapper for inform_user_of_validation_error_node_async."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(inform_user_of_validation_error_node_async(state))
    finally:
        loop.close()

async def configure_billing_node_async(state: WorkflowState) -> Dict[str, Any]:
    """Node that configures billing based on the *validated* data.""" # Docstring updated
    logger.info("Running configure_billing_node")
    document_path = state.get("document_path", "Unknown document")
    verified_data = state.get("verified_data")

    if not verified_data:
        logger.warning(f"No verified data in state for billing configuration (document: {document_path}).")
        return {
            **state,
            "status": "error",
            "configuration_error": "No verified data provided",
            "error_message": f"Billing configuration skipped: No verified data for {document_path}."
        }
    
    logger.info(f"Configuring billing for {document_path} with verified data.")
    try:
        result = await billing_configurator.configure_billing(verified_data)
        
        if result.get("configuration_error"):
            logger.error(f"Error configuring billing for {document_path}: {result['configuration_error']}")
            return {
                **state,
                "status": "error",
                "configuration_error": result["configuration_error"],
                "error_message": f"Billing configuration failed: {result['configuration_error']}"
            }
        
        logger.info(f"Billing configured successfully for {document_path}.")
        return {
            **state,
            "customer_id": result["customer_id"],
            "subscription_id": result["subscription_id"],
            "configuration_result": result["configuration_result"],
            "status": "success" # Mark as success after billing
        }
    except Exception as e:
        logger.exception(f"Unhandled error configuring billing for {document_path}: {e}")
        return {
            **state,
            "status": "error",
            "configuration_error": str(e),
            "error_message": f"Unhandled error during billing configuration: {str(e)}"
        }

def configure_billing_node(state: WorkflowState) -> Dict[str, Any]:
    """Synchronous wrapper for configure_billing_node_async."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(configure_billing_node_async(state))
    finally:
        loop.close()

def mark_document_processed_node(state: WorkflowState) -> Dict[str, Any]:
    """Node that marks the document as processed (synchronous version)."""
    # This node now primarily handles the side effect of marking as processed.
    # It receives the state after processing (success or error) and performs the action.
    # It no longer needs to return the full cleared state, as the graph ends here.
    logger.info("Running mark_document_processed_node")
    
    document_path = state.get("document_path")
    source = state.get("source")
    status = state.get("status") # Should be 'success' or 'error' if routed here
    
    if not document_path:
        logger.warning("mark_document_processed_node called without document_path.")
        # In the new graph structure, this might indicate an issue earlier, but return empty anyway.
        return {"status": "completed"}
    
    # Mark as processed if the pipeline ended in success OR error
    # (error could be from extraction, verification, validation, or billing)
    if status in ["success", "error"]:
        if source == "file":
            document_watcher.mark_as_processed(document_path)
            logger.info(f"File document marked as processed: {document_path}")
        elif source == "email":
            email_id = state.get("email_data", {}).get("email_id")
            if email_id:
                email_watcher.mark_email_processed(email_id)
                logger.info(f"Email document marked as processed (Email ID: {email_id}): {document_path}")
            else:
                logger.warning(f"Attempted to mark email source processed, but email_id not found in state.")
        else:
             logger.warning(f"Unknown source '{source}' in mark_document_processed_node.")
    else:
        # This case should ideally not be reached if conditional logic is correct
        logger.warning(f"mark_document_processed_node called with unexpected status '{status}'. Document: {document_path}")

    # Return a minimal state update to satisfy LangGraph
    return {"status": "completed"}


# Build the graph for the processing pipeline
def build_processing_graph():
    """Build and return the workflow graph for processing a document."""
    workflow = StateGraph(WorkflowState)
    
    # Add nodes for the processing steps
    workflow.add_node("process_document", process_document_node)
    workflow.add_node("human_verification", human_verification_node)
    workflow.add_node("validate_data_for_billing", validate_data_node) # Use renamed node func
    workflow.add_node("configure_billing", configure_billing_node)
    workflow.add_node("mark_document_processed", mark_document_processed_node)
    workflow.add_node("inform_user_of_validation_error", inform_user_of_validation_error_node) # Add new node
    
    # Set the entry point for processing
    workflow.set_entry_point("process_document")
    
    # Define transitions within the processing pipeline
    workflow.add_conditional_edges(
        "process_document",
        # Decide based on extraction result
        lambda state: "human_verification" if state.get("extracted_data") else "mark_document_processed"
    )
    workflow.add_conditional_edges(
        "human_verification",
        # On success, go to validation. On failure/timeout, mark processed.
        lambda state: "validate_data_for_billing" if state.get("is_verified") else "mark_document_processed"
    )
    workflow.add_conditional_edges(
        "validate_data_for_billing",
        # If valid -> configure billing. If invalid -> inform user.
        lambda state: "configure_billing" if state.get("is_valid_for_billing") else "inform_user_of_validation_error"
    )
    # Loop back edge: After informing user, go back to human verification
    workflow.add_edge("inform_user_of_validation_error", "human_verification")

    workflow.add_conditional_edges(
        "configure_billing",
        # Always go to mark processed after attempting billing (success or error handled there)
        lambda state: "mark_document_processed"
    )
    
    # Mark document processed node is the end of the pipeline for a single item
    workflow.add_edge("mark_document_processed", END)
        
    # Compile the graph
    # Checkpointer still useful for resuming interrupted processing of a single item
    return workflow.compile(checkpointer=MemorySaver())

async def invoke_graph_for_item(graph, input_state: Dict, config: Dict):
    """Helper function to invoke the graph for a single item and log results."""
    thread_id = config["configurable"]["thread_id"]
    logger.info(f"Invoking processing graph for thread {thread_id} with input: {input_state}")
    try:
        # Use astream to allow potential logging of intermediate steps if needed later
        async for event in graph.astream(input_state, config, stream_mode="values"):
             # More detailed logging of graph events
             # The event structure in 'values' mode is the state dict after a node runs
             last_state_update = event
             executed_node = list(last_state_update.keys())[-1] # Infer executed node
             node_output = last_state_update[executed_node]
             logger.info(f"Graph Event (Thread: {thread_id}): Node='{executed_node}' Output Keys={list(node_output.keys()) if isinstance(node_output, dict) else 'N/A'}")


        # Get final state to log outcome
        final_state = graph.get_state(config)
        # Check if final_state and final_state.values exist before accessing
        final_status = final_state.values.get('status', 'unknown') if final_state and final_state.values else 'unknown'
        logger.info(f"Graph processing finished for thread {thread_id}. Final Status: {final_status}")

        if final_state and final_state.values: # Check again before accessing values
            if final_status == "error":
                logger.error(f"Error details for thread {thread_id}: Error='{final_state.values.get('error_message', 'N/A')}', Extraction='{final_state.values.get('extraction_error', 'N/A')}', Verification='{final_state.values.get('verification_error', 'N/A')}', Validation='{final_state.values.get('validation_error', 'N/A')}', Config='{final_state.values.get('configuration_error', 'N/A')}'")
            elif final_status == "success":
                 logger.info(f"Success details for thread {thread_id}: Customer={final_state.values.get('customer_id')}, Sub={final_state.values.get('subscription_id')}")
        else:
             logger.warning(f"Could not retrieve final state details for thread {thread_id}.")


    except Exception as graph_exc:
        logger.exception(f"Exception occurred during graph execution for thread {thread_id}: {graph_exc}")
        # Attempt to mark the document/email as processed even if graph failed mid-way
        try:
            # Need to reconstruct state partially to call mark_document_processed
            mark_state = {
                "document_path": input_state.get("document_path"),
                "source": input_state.get("source"),
                "email_data": input_state.get("email_data"),
                "status": "error" # Mark as error since graph failed
            }
            mark_document_processed_node(mark_state) # Call synchronously
            logger.info(f"Attempted to mark item as processed after graph execution exception for thread {thread_id}.")
        except Exception as mark_err:
             logger.error(f"Failed to mark item as processed after graph exception for thread {thread_id}: {mark_err}")

async def run_workflow():
    """Run the workflow continuously by checking sources and launching graph tasks."""
    logger.info("Starting LangGraph Orb Workflow - Concurrent Pipeline")
    
    # Initialize the watchers
    document_watcher.start()
    email_watcher.start()
    graph = build_processing_graph() # Build the processing graph

    last_email_check = time.time() - 60  # Initialize to check emails on first run
    active_tasks = set() # Keep track of running graph tasks

    try:
        while True:
            # --- Item Discovery --- #
            input_state = None
            thread_id = None

            # 1. Check for new documents
            document_path = document_watcher.get_next_document()
            if document_path:
                logger.info(f"Found document: {document_path}")
                # Create a unique ID for this processing run
                thread_id = f"file_{os.path.basename(document_path)}_{int(time.time())}"
                input_state = {
                    "document_path": document_path,
                    "source": "file",
                    # Initialize only necessary fields for the graph entry point (process_document)
                }
            else:
                # 2. If no document, check for emails (rate limited)
                current_time = time.time()
                should_check_email = (current_time - last_email_check >= 60)
                if should_check_email:
                    logger.info("Checking for emails...")
                    last_email_check = current_time
                    email = await email_watcher.get_next_email()
                    if email:
                        logger.info(f"Found potential invoice email: {email.get('subject')}")
                        file_path, metadata = await email_watcher.process_email(email)
                        if file_path and metadata:
                            email_id = metadata.get("email_id", f"unknown_{int(time.time())}")
                            thread_id = f"email_{email_id}" # Use consistent ID for potential retries
                            invoice_attachment_path = None
                            # --- Revised Attachment Prioritization --- #
                            logger.info(f"Searching for PDF attachment in email {email_id}...")
                            for attachment in metadata.get("saved_attachments", []):
                                attachment_name = attachment.get("name", "").lower()
                                attachment_type = attachment.get("type", "").lower()
                                if attachment_name.endswith(".pdf") or "pdf" in attachment_type:
                                     invoice_attachment_path = attachment.get("path")
                                     logger.info(f"Prioritizing PDF attachment found: {invoice_attachment_path}")
                                     break # Use the first PDF found

                            # If no PDF attachment, use the main email file path
                            document_to_process = invoice_attachment_path or file_path
                            logger.info(f"Final document selected for processing for email {email_id}: {document_to_process}")
                            # --- End Revised Prioritization --- #

                            input_state = {
                                "document_path": document_to_process,
                                "source": "email",
                                "email_data": metadata,
                            }
                        else:
                            logger.error(f"Failed to process email into a file/metadata: {email.get('subject')}")
                            email_id = email.get("id")
                            if email_id:
                                email_watcher.mark_email_processed(email_id)
                                logger.info(f"Marked email {email_id} as processed despite processing error.")
                    else:
                        logger.info("No new invoice emails found.")
                else:
                    logger.debug("Skipping email check due to rate limit.")

            # --- Task Launching --- #
            if input_state and thread_id:
                config = {"configurable": {"thread_id": thread_id}}
                # Launch the graph execution as a background task
                task = asyncio.create_task(invoke_graph_for_item(graph, input_state, config))
                active_tasks.add(task)
                # Remove task from set upon completion to prevent memory leak
                task.add_done_callback(active_tasks.discard)
                logger.info(f"Launched processing task for thread {thread_id}. Active tasks: {len(active_tasks)}")
                await asyncio.sleep(0.1) # Brief yield to allow task scheduling
            else:
                # No new item found, wait before polling again
                logger.info(f"No new documents or emails found, waiting... Active tasks: {len(active_tasks)}")
                await asyncio.sleep(5)

    
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down")
        # Optional: Wait for active tasks to finish?
        # if active_tasks:
        #     logger.info(f"Waiting for {len(active_tasks)} active tasks to complete...")
        #     await asyncio.wait(active_tasks)
    except Exception as e:
        logger.error(f"Unhandled error in main run function: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        # Stop the watchers
        logger.info("Stopping watchers...")
        document_watcher.stop()
        email_watcher.stop()
        logger.info("Watchers stopped.")

if __name__ == "__main__":
    # Run the workflow
    asyncio.run(run_workflow()) 