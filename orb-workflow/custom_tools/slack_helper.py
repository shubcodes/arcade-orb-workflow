#!/usr/bin/env python3
import os
import logging
import time
import asyncio
from typing import Dict, Any, Optional, List
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError
from arcadepy import Arcade

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class SlackHelper:
    """Provides helper functions for specific Slack interactions using Arcade for auth."""

    def __init__(self, user_id: str, arcade_client: Arcade):
        """Initialize the Slack helper.

        Args:
            user_id: The user ID for whom to fetch the Slack token.
            arcade_client: The initialized Arcade client instance.
        """
        self.user_id = user_id
        self.arcade_client = arcade_client
        self._slack_token: Optional[str] = None
        self._token_fetched = False

    async def _get_slack_token(self) -> Optional[str]:
        """Fetches the Slack OAuth token for the user via Arcade's auth flow."""
        if self._token_fetched:
            # Return cached token if already fetched successfully
            return self._slack_token

        logger.info(f"Attempting to fetch Slack token for user {self.user_id} via Arcade Auth")
        # Define the scopes needed for conversations.replies
        required_scopes = [
            "channels:history",
            "groups:history",
            "im:history",
            "mpim:history"
        ]

        try:
            # Start the authorization process for Slack with the required scopes
            auth_response = self.arcade_client.auth.start(
                user_id=self.user_id,
                provider="slack", # Specify the Slack provider
                scopes=required_scopes
            )

            # Check if authorization is already completed for these scopes
            if auth_response.status != "completed":
                logger.info(f"Arcade requires authorization for Slack scopes: {required_scopes}. Please visit: {auth_response.url}")
                # Wait for user to complete the authorization flow
                auth_response = self.arcade_client.auth.wait_for_completion(auth_response)

            # Check final status after waiting
            if auth_response.status == "completed":
                if hasattr(auth_response, 'context') and hasattr(auth_response.context, 'token'):
                    self._slack_token = auth_response.context.token
                    logger.info(f"Successfully obtained Slack token for user {self.user_id} via Arcade.")
                else:
                    logger.error(f"Authorization completed for {self.user_id}, but token not found in response context.")
                    self._slack_token = None
            else:
                logger.error(f"Slack authorization failed or was not completed for user {self.user_id}. Status: {auth_response.status}")
                self._slack_token = None

        except Exception as e:
            logger.exception(f"An error occurred during Arcade Slack authorization for user {self.user_id}: {e}")
            self._slack_token = None

        # Mark as fetched even if failed, so we don't retry immediately
        self._token_fetched = True
        return self._slack_token

    async def get_thread_replies(self, channel_id: str, thread_ts: str) -> List[Dict[str, Any]]:
        """Fetches replies for a specific thread using the Slack API.

        Args:
            channel_id: The ID of the channel/conversation.
            thread_ts: The timestamp ('ts') of the parent message.

        Returns:
            A list of message dictionaries representing the replies, or empty list on error.
        """
        token = await self._get_slack_token()
        if not token:
            logger.error("Cannot fetch thread replies: Slack token not available.")
            return []

        client = AsyncWebClient(token=token)
        logger.info(f"Fetching replies for thread {thread_ts} in channel {channel_id}")
        try:
            # Use conversations.replies method
            result = await client.conversations_replies(
                channel=channel_id,
                ts=thread_ts,
                limit=200 # Get up to 200 replies
            )

            messages = result.get("messages", [])
            # The first message in the replies is usually the parent message, skip it.
            replies = messages[1:] if messages else []
            logger.info(f"Found {len(replies)} replies for thread {thread_ts}.")
            return replies

        except SlackApiError as e:
            logger.error(f"Error fetching Slack thread replies: {e.response['error']}")
            return []
        except Exception as e:
            logger.exception(f"An unexpected error occurred fetching Slack replies: {e}")
            return []

    async def send_reply_in_thread(self, channel_id: str, thread_ts: str, text: str) -> Optional[str]:
        """Sends a reply message within a specific thread using the Slack API.

        Args:
            channel_id: The ID of the channel/conversation.
            thread_ts: The timestamp ('ts') of the parent message to reply to.
            text: The message text to send.

        Returns:
            The timestamp ('ts') of the sent reply message, or None if sending failed.
        """
        token = await self._get_slack_token()
        if not token:
            logger.error("Cannot send threaded reply: Slack token not available.")
            return None

        client = AsyncWebClient(token=token)
        logger.info(f"Sending reply in thread {thread_ts} in channel {channel_id}")
        try:
            # Use chat.postMessage with thread_ts
            result = await client.chat_postMessage(
                channel=channel_id,
                text=text,
                thread_ts=thread_ts
            )
            reply_ts = result.get("ts")
            if reply_ts:
                logger.info(f"Successfully sent reply in thread. Reply TS: {reply_ts}")
                return reply_ts
            else:
                logger.error(f"Failed to get timestamp from successful chat.postMessage response: {result}")
                return None

        except SlackApiError as e:
            logger.error(f"Error sending Slack threaded reply: {e.response['error']}")
            return None
        except Exception as e:
            logger.exception(f"An unexpected error occurred sending Slack reply: {e}")
            return None

# Example usage placeholder (for testing this module directly)
# TEST CASE FOR SLACK HANDLER
# if __name__ == "__main__":
#     async def run_test():
#         user = "your_test_slack_user_id_for_arcade"
#         arcade_c = Arcade(api_key=os.getenv("ARCADE_API_KEY"))
#         # Ensure user has authorized Slack via Arcade first!
#         helper = SlackHelper(user_id=user, arcade_client=arcade_c)
#
#         channel = "your_test_channel_id" # e.g., C08NUA6PK88
#         parent_ts = "your_parent_message_ts" # e.g., 1744680680.188409
#
#         replies = await helper.get_thread_replies(channel, parent_ts)
#         print(f"Replies found ({len(replies)}):")
#         for reply in replies:
#             print(f"- {reply.get('user')}: {reply.get('text')}")
#
#     asyncio.run(run_test()) 