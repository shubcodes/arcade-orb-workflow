import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import logging
import time
import asyncio
from typing import Dict, Any, Optional, Tuple, List
from dotenv import load_dotenv
import openai
from arcadepy import Arcade
from custom_tools.slack_helper import SlackHelper # Import the new helper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# Set debug level for this specific logger if needed
# logging.getLogger(__name__).setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


# Load environment variables
load_dotenv()
FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY")
ARCADE_API_KEY = os.getenv("ARCADE_API_KEY")
SLACK_VERIFICATION_CHANNEL = os.getenv("SLACK_VERIFICATION_CHANNEL", "general") # Default to #general
SLACK_USER_ID = os.getenv("SLACK_USER_ID", "default_slack_user") # User ID for Arcade auth
# Get the bot's user ID if available (useful for filtering out bot's own messages)
# This might need to be retrieved via Slack API or set manually
SLACK_BOT_USER_ID = os.getenv("SLACK_BOT_USER_ID", None)


if not FIREWORKS_API_KEY:
    raise ValueError("FIREWORKS_API_KEY environment variable not set.")
if not ARCADE_API_KEY:
    raise ValueError("ARCADE_API_KEY environment variable not set.")

# Initialize OpenAI client (using Fireworks)
openai_client = openai.OpenAI(
    base_url="https://api.fireworks.ai/inference/v1",
    api_key=FIREWORKS_API_KEY
)
FIREWORKS_MODEL = "accounts/fireworks/models/llama4-maverick-instruct-basic"

class SlackHumanVerificationAgent:
    """Agent that handles human-in-the-loop verification via Slack."""

    def __init__(self, user_id: str = SLACK_USER_ID, channel_name: str = SLACK_VERIFICATION_CHANNEL):
        """Initialize the Slack verification agent.

        Args:
            user_id: The user ID to use for Arcade Slack authorization.
            channel_name: The default Slack channel name to send verification messages to.
        """
        logger.info(f"Initializing SlackHumanVerificationAgent for user {user_id} and channel #{channel_name}")
        self.user_id = user_id
        self.channel_name = channel_name
        self.arcade_client = Arcade(api_key=ARCADE_API_KEY)
        self.authorized_tools = set()
        # Initialize the Slack Helper
        self.slack_helper = SlackHelper(user_id=self.user_id, arcade_client=self.arcade_client)

    async def _ensure_tool_authorization(self, tool_name: str) -> bool:
        """Ensure the agent is authorized to use a specific Slack tool via Arcade.

        Args:
            tool_name: The name of the Slack tool (e.g., "Slack.SendMessageToChannel").

        Returns:
            bool: True if authorized, False otherwise.
        """
        # NOTE: This ensures Arcade *thinks* it's authorized for the specific TOOL.
        # The SlackHelper relies on the underlying TOKEN being available and having
        # the necessary scopes (like channels:history, groups:history for reads).
        # We ensure the helper can get the token first.

        # Ensure helper can potentially get token by authorizing read scopes first if needed
        # This call will trigger the auth flow in the helper if necessary scopes aren't granted
        if not await self.slack_helper._get_slack_token():
             logger.error(f"Could not get Slack token via Arcade auth for user {self.user_id}. Cannot proceed.")
             return False # Cannot proceed if token isn't available

        # Now check the requested tool using Arcade's standard flow
        if tool_name in self.authorized_tools:
            logger.debug(f"Arcade tool {tool_name} already authorized.")
            return True

        # Authorize the specific Arcade tool if needed (e.g., SendMessageToChannel)
        return await self._authorize_tool_internal(tool_name)

    async def _authorize_tool_internal(self, tool_name: str) -> bool:
        """Internal helper to authorize a single tool via Arcade."""
        if tool_name in self.authorized_tools:
            return True # Already checked

        logger.info(f"Authorizing user {self.user_id} for Arcade tool: {tool_name}")
        try:
            auth_response = self.arcade_client.tools.authorize(
                tool_name=tool_name,
                user_id=self.user_id
            )

            if auth_response.status == "completed":
                logger.info(f"User already authorized for Arcade tool: {tool_name}")
                self.authorized_tools.add(tool_name)
                return True

            logger.info(f"Arcade tool authorization required for {tool_name}. Please visit: {auth_response.url}")
            logger.info(f"Waiting for user authorization for Arcade tool: {tool_name}...")
            try:
                self.arcade_client.auth.wait_for_completion(auth_response)
                logger.info(f"Arcade tool authorization wait completed for {tool_name}. Assuming success.")
                self.authorized_tools.add(tool_name)
                return True
            except Exception as wait_error:
                 logger.error(f"Error or timeout during Arcade tool ({tool_name}) authorization wait: {wait_error}")
                 return False

        except Exception as e:
            logger.error(f"Error during Arcade tool ({tool_name}) authorization attempt: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    async def send_verification_request(self, extracted_data: Dict[str, Any], channel_name: Optional[str] = None) -> Optional[Tuple[str, str]]:
        """Sends the extracted data to Slack for verification and returns the message timestamp and channel ID.

        Args:
            extracted_data: The data extracted from the invoice/document.
            channel_name: Optional specific channel name override.

        Returns:
            Tuple containing (message_ts, channel_id) or (None, None) if sending failed.
        """
        target_channel = channel_name or self.channel_name
        tool_name = "Slack.SendMessageToChannel"

        # Ensure authorization for the SendMessage tool itself
        if not await self._ensure_tool_authorization(tool_name):
            logger.error(f"Not authorized to use Arcade tool {tool_name}")
            return None, None

        # Revert to simple threaded reply instruction
        message_text = f"Please verify the following extracted invoice data:\n```\n{json.dumps(extracted_data, indent=2)}\n```\nReply **in this thread** with 'approve' or 'verified' to confirm, or provide specific changes."

        logger.info(f"Sending verification request to channel #{target_channel}")
        try:
            # Use Arcade tool to send message
            response = self.arcade_client.tools.execute(
                tool_name=tool_name,
                input={
                    "channel_name": target_channel,
                    "message": message_text,
                },
                user_id=self.user_id
            )

            message_ts, channel_id = None, None
            if response and hasattr(response, 'output') and response.output:
                output_value = response.output.value
                if isinstance(output_value, dict):
                    # Parse response to get ts and channel_id
                    resp_dict = output_value.get("response", {})
                    message_dict = resp_dict.get("message", {})
                    # Prioritize ts/channel from the top-level or direct response dict if available
                    message_ts = output_value.get("ts") or resp_dict.get("ts") or message_dict.get("ts")
                    channel_id = output_value.get("channel") or resp_dict.get("channel") or message_dict.get("channel")


            if message_ts and channel_id:
                logger.info(f"Verification request sent successfully. Message Timestamp: {message_ts}, Channel ID: {channel_id}")
                return message_ts, channel_id
            else:
                logger.warning(f"Sent message but couldn't find 'ts' ({message_ts}) or 'channel' ({channel_id}) in response: {output_value}")
                return None, None

        except Exception as e:
            logger.exception(f"Error sending Slack message via Arcade tool {tool_name} to channel #{target_channel}: {str(e)}")
            return None, None

    async def wait_for_response(self, original_ts: str, channel_id: str, min_reply_ts: str, timeout_seconds: int = 300) -> Optional[Dict[str, Any]]:
        """Waits for a reply in the thread using SlackHelper, starting after min_reply_ts.

        Args:
            original_ts: The timestamp ('ts') of the parent message starting the thread.
            channel_id: The ID of the channel/conversation where the message resides.
            min_reply_ts: The timestamp after which to look for new replies.
            timeout_seconds: How long to wait for a response.

        Returns:
            The first valid human reply message dictionary newer than min_reply_ts, or None.
        """
        # SlackHelper handles token fetching internally using Arcade auth flow
        logger.info(f"Waiting for replies to thread {original_ts} in conversation {channel_id} after ts {min_reply_ts} (timeout: {timeout_seconds}s)")
        start_time = time.time()
        # No internal tracking needed, filter based on passed min_reply_ts

        while time.time() - start_time < timeout_seconds:
            try:
                # Use the helper to get replies
                replies = await self.slack_helper.get_thread_replies(channel_id, original_ts)

                if replies is None: # Check if token fetching failed in helper
                    logger.error("SlackHelper failed to get replies (likely token issue). Aborting wait.")
                    return None

                if replies:
                    replies.sort(key=lambda m: float(m.get('ts', 0)))

                    for reply in replies:
                        reply_ts_str = reply.get('ts')
                        if not reply_ts_str: continue

                        # *** Core Filter Logic Change ***
                        # Check if this reply is strictly newer than the minimum required timestamp
                        if float(reply_ts_str) > float(min_reply_ts):
                            user = reply.get('user')
                            text = reply.get('text', '').strip()

                            # Ignore replies from the bot itself
                            if SLACK_BOT_USER_ID and user == SLACK_BOT_USER_ID:
                                logger.debug(f"Ignoring bot's own reply (ts: {reply_ts_str}).")
                                # Don't return, but also don't update min_reply_ts here.
                                continue # Check next reply

                            if text: # Found a valid human reply newer than min_reply_ts
                                logger.info(f"Found valid reply via SlackHelper from user {user} (ts: {reply_ts_str}): {text}")
                                return reply
                            else:
                                logger.debug(f"Ignoring reply with no text content (ts: {reply_ts_str}).")
                                # Don't return, but also don't update min_reply_ts here.
                                continue # Check next reply
                        # else: # DEBUG: Log why a reply was skipped
                        #    logger.debug(f"Skipping reply ts {reply_ts_str} because it's not > min_reply_ts {min_reply_ts}")
                else:
                     logger.debug("No replies found in current poll by SlackHelper.")

            except Exception as e:
                logger.exception(f"Error polling for replies using SlackHelper: {str(e)}")

            await asyncio.sleep(10) # Poll every 10 seconds

        logger.warning(f"Timeout waiting for response to message {original_ts} after {min_reply_ts}")
        return None

    async def process_response(self, response_message: Dict[str, Any], original_data: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Processes the human response using keywords and LLM for changes.

        Args:
            response_message: The Slack message dictionary containing the response.
            original_data: The data that was originally sent for verification.

        Returns:
            Tuple containing:
                - status: "approved", "changes_requested", "unclear", "error"
                - updated_data: The modified data if changes were requested, otherwise the original data or None on error.
        """
        text = response_message.get('text', '').strip().lower()
        logger.info(f"Processing response text: '{text}'")

        # --- DEBUG: Log input data --- #
        logger.debug(f"Processing response against data: {json.dumps(original_data, indent=2)}")
        # --- END DEBUG --- #

        # Simple keyword check for approval
        approval_keywords = ["approve", "approved", "verified", "looks good", "lg", "yes", "confirm"]
        if any(keyword in text for keyword in approval_keywords):
            logger.info("Approval keywords detected.")
            return "approved", original_data

        # If not approved, use LLM to interpret changes
        logger.info("No approval keywords found. Attempting to interpret changes using LLM.")
        try:
            prompt = f"""Given the original JSON data:
```json
{json.dumps(original_data, indent=2)}
```
And the user's requested changes:
"{response_message.get('text', '')}"

Apply the changes to the JSON data. Only modify the fields explicitly mentioned or clearly implied by the user's request. Ensure the output is ONLY the updated JSON object, maintaining the original structure. If the request is unclear or cannot be applied, return the original JSON object and explain why in a separate 'error' field.

Respond with a JSON object containing:
- "updated_data": The modified JSON data (or original if no changes).
- "changes_applied": boolean indicating if any changes were made.
- "error": string description if the request was unclear or failed, otherwise null.

Example valid response format:
{{
  "updated_data": {{ ... updated json ... }},
  "changes_applied": true,
  "error": null
}}
Example unclear response format:
{{
  "updated_data": {{ ... original json ... }},
  "changes_applied": false,
  "error": "User request 'fix it' is too vague."
}}
"""
            # --- DEBUG: Log LLM Prompt --- #
            logger.debug(f"LLM Prompt for change interpretation:\n{prompt}")
            # --- END DEBUG --- #

            response = openai_client.chat.completions.create(
                model=FIREWORKS_MODEL,
                messages=[
                    {"role": "system", "content": "You are an AI assistant that updates JSON data based on user instructions."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )

            result_json = response.choices[0].message.content
            # --- DEBUG: Log Raw LLM Response --- #
            logger.debug(f"Raw LLM JSON response: {result_json}")
            # --- END DEBUG --- #

            llm_result = json.loads(result_json)

            updated_data = llm_result.get("updated_data")
            changes_applied = llm_result.get("changes_applied", False)
            error_msg = llm_result.get("error")

            if error_msg:
                logger.warning(f"LLM indicated unclear request or error: {error_msg}")
                return "unclear", original_data # Return unclear status and original data

            if changes_applied and updated_data:
                logger.info("LLM successfully interpreted and applied changes.")
                return "changes_requested", updated_data # Return changes_requested and the NEW data
            else:
                # LLM didn't apply changes, maybe the request wasn't a change instruction?
                logger.warning("LLM did not apply any changes. Treating response as unclear.")
                return "unclear", original_data # Treat as unclear if no changes applied

        except json.JSONDecodeError as json_err:
             logger.error(f"Failed to parse LLM JSON response: {json_err}. Response: {result_json}")
             return "error", None
        except Exception as e:
            logger.exception(f"Error during LLM processing for changes: {str(e)}")
            return "error", None

    async def request_and_wait_for_verification(
        self,
        initial_data: Dict[str, Any],
        channel_name: Optional[str] = None,
        timeout_seconds: int = 300, # 5 minutes total timeout per attempt
        max_retries: int = 3 # Max number of back-and-forth interactions
    ) -> Optional[Tuple[Dict[str, Any], str, str]]:
        """Orchestrates the human verification workflow using SlackHelper for replies.

        Sends data, waits for response, processes it, handles changes/retries,
        and returns the final verified data, original thread ts, and channel id,
        or None if failed/timed out.
        """
        logger.info("Starting human verification workflow...")
        current_data = initial_data.copy()
        target_channel_name = channel_name or self.channel_name # Use channel name for sending initially
        retries = 0

        # Initial request - this message starts the thread
        # send_verification_request uses Arcade tool and returns (message_ts, channel_id)
        message_ts, channel_id = await self.send_verification_request(current_data, target_channel_name)
        if not message_ts or not channel_id:
            logger.error("Failed to send initial verification request or get channel ID.")
            return None

        # to track the timestamp of the latest reply we processed to avoid duplicates.
        last_processed_interaction_ts = message_ts # Initialize with the TS of the first agent message

        while retries < max_retries:
            logger.info(f"Waiting for user reply in thread {message_ts} after ts {last_processed_interaction_ts} (Attempt {retries + 1}/{max_retries})...")
            # Pass the timestamp of the last processed interaction into wait_for_response
            response_message = await self.wait_for_response(message_ts, channel_id, last_processed_interaction_ts, timeout_seconds)

            if not response_message:
                logger.warning(f"No new user reply received within timeout for thread {message_ts}")
                logger.error("Verification timed out.")
                return None # Exit loop if timed out

            # ** Update Tracker **: Mark this user message as the latest interaction
            current_reply_ts = response_message.get('ts')
            if current_reply_ts:
                logger.debug(f"Updating last_processed_interaction_ts from {last_processed_interaction_ts} to {current_reply_ts} (user reply)")
                last_processed_interaction_ts = current_reply_ts
            else:
                 logger.warning("Received reply message missing timestamp, cannot update tracker reliably.")

            # Process the user's response
            status, processed_data = await self.process_response(response_message, current_data)

            if status == "approved":
                logger.info("Verification approved by human.")
                final_data = processed_data if processed_data else current_data
                # Return success: verified data, original thread ts, channel id
                return final_data, message_ts, channel_id # Modified return
            elif status == "changes_requested":
                logger.info("Changes requested by human. Applying changes and resending.")
                if not processed_data:
                     logger.error("Changes requested but LLM processing failed to return updated data.")
                     return None # Abort on error

                current_data = processed_data
                # Send the update as a reply using SlackHelper
                update_text = f"OK, I've updated the data based on your request. Please verify again:\\n```\\n{json.dumps(current_data, indent=2)}\\n```\\nReply 'approve'/'verified' or provide further changes."
                reply_ts = await self.slack_helper.send_reply_in_thread(channel_id, message_ts, update_text) # Use helper

                if not reply_ts:
                    logger.error("Failed to send updated verification request using SlackHelper.")
                    return None # Abort if we can't send the update

                # ** Update Tracker **: Mark the bot's update message as the latest interaction
                logger.debug(f"Updating last_processed_interaction_ts from {last_processed_interaction_ts} to {reply_ts} (bot update reply)")
                last_processed_interaction_ts = reply_ts
                retries += 1
            elif status == "unclear":
                logger.warning("Response was unclear. Sending clarification message.")
                # Send clarification using SlackHelper
                clarification_text = "Sorry, I didn't understand your request. Please clarify the changes needed or reply 'approve'/'verified'."
                clarification_ts = await self.slack_helper.send_reply_in_thread(channel_id, message_ts, clarification_text) # Use helper

                if not clarification_ts:
                     logger.error("Failed to send clarification message using SlackHelper.")
                     # If we can't send clarification, maybe best to abort? Or just wait again?
                     return None
                else:
                    logger.info(f"Sent clarification message (ts: {clarification_ts}).")
                    # ** Update Tracker **: Mark the bot's clarification message as the latest interaction
                    last_processed_interaction_ts = clarification_ts
                 # Don't increment retries, just wait for the next reply.
            elif status == "error":
                 logger.error("Error processing response.")
                 return None # Abort on error
            else:
                 logger.error(f"Unknown status from process_response: {status}")
                 return None # Unexpected state

        logger.error(f"Verification failed after {max_retries} attempts.")
        return None # Return None on failure/max_retries


# Example Usage (for testing)
# if __name__ == "__main__":
#     async def main():
#         # Example data to verify
#         test_data = {
#             "invoice_id": "INV-123",
#             "customer_name": "Test Customer Inc.",
#             "amount_due": 150.75,
#             "due_date": "2024-08-15",
#             "items": [
#                 {"description": "Widget A", "quantity": 2, "price": 50.0},
#                 {"description": "Service B", "quantity": 1, "price": 50.75},
#             ]
#         }
#
#         # Initialize the agent
#         agent = SlackHumanVerificationAgent()
#
#         print("Attempting to send verification request...")
#         # This call will orchestrate the entire verification process
#         verified_data = await agent.request_and_wait_for_verification(test_data, timeout_seconds=180, max_retries=3)
#
#         if verified_data:
#             print("\n--- Verification Successful ---")
#             print(json.dumps(verified_data, indent=2))
#         else:
#             print("\n--- Verification Failed or Timed Out ---")
#
#     # Run the async main function
#     print("Starting Slack Human Verification Agent test...")
#     print("NOTE: This requires manual Slack interaction in the thread.")
#     print(f"Agent will post to channel: #{SLACK_VERIFICATION_CHANNEL}")
#     print(f"Ensure user {SLACK_USER_ID} has authorized Arcade Slack tools (including history scopes).")
#     print("You may see an authorization URL printed below if needed.")
#
#     asyncio.run(main())
