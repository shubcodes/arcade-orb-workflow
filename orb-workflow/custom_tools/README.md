# Custom Tools and Helpers for Orb Workflow Agents

This directory contains custom Python classes designed to extend the capabilities of the agents within the Orb Workflow project, particularly where direct interaction with APIs using Arcade-managed authentication is needed beyond the standard Arcade toolset.

## 1. Gmail Attachment Tools (`gmail_attachment_tool_direct.py`)

**Purpose:** Provides functionality to list and retrieve Gmail attachments directly using the Google Gmail API, leveraging Arcade for user authentication and token management. This was necessary because the standard Arcade Gmail toolkit at the time of implementation did not expose attachment data.

**Class:** `GmailAttachmentTools`

**Key Methods:**
*   `list_message_attachments(message_id)`: Lists metadata for all attachments in a specific Gmail message.
*   `get_gmail_attachment(message_id, attachment_id)`: Downloads the content of a specific attachment.

**Authentication:**
*   Uses `arcadepy.Arcade` client instance passed during initialization.
*   Internally calls `arcade_client.auth.start(provider='google', scopes=[...])` to request necessary Gmail API permissions (like `gmail.readonly`).
*   Uses `arcade_client.auth.wait_for_completion` if authorization is required.
*   Retrieves the OAuth token from the Arcade authorization context to initialize the `googleapiclient` service.

**Usage:**
*   This class is **not deployed** as a standalone Arcade tool.
*   It is instantiated and used directly within the `EmailWatcherAgent` (`orb-workflow/agents/email_watcher_agent.py`).
*   The `EmailWatcherAgent` calls methods on an instance of `GmailAttachmentTools` to fetch attachment details and content after obtaining the relevant email message ID.

## 2. Slack Thread Helper (`slack_helper.py`)

**Purpose:** Provides reliable methods for fetching replies within a specific Slack thread and sending messages as replies to a thread. This was created because the standard Arcade `Slack.GetMessages...` tools proved unreliable for consistently fetching threaded replies based on a parent message timestamp, and the `Slack.SendMessageToChannel` tool might not correctly handle the `thread_ts` parameter for sending replies.

**Class:** `SlackHelper`

**Key Methods:**
*   `get_thread_replies(channel_id, thread_ts)`: Fetches all replies within a specific thread using the official Slack `conversations.replies` API method.
*   `send_reply_in_thread(channel_id, thread_ts, text)`: Sends a message specifically as a reply within an existing thread using the official Slack `chat.postMessage` API method with the `thread_ts` argument.

**Authentication:**
*   Uses `arcadepy.Arcade` client instance passed during initialization.
*   The internal `_get_slack_token` method calls `arcade_client.auth.start(provider='slack', scopes=[...])` to request necessary Slack API permissions (importantly `channels:history`, `groups:history`, etc., for reading replies, and `chat:write` for posting).
*   Uses `arcade_client.auth.wait_for_completion` if authorization is required.
*   Retrieves the Slack OAuth token from the Arcade authorization context.
*   Uses the fetched token to initialize the `slack_sdk.web.async_client.AsyncWebClient` for direct API calls.

**Usage:**
*   This class is **not deployed** as a standalone Arcade tool.
*   It is instantiated and used directly within the `SlackHumanVerificationAgent` (`orb-workflow/agents/slack_human_verification_agent.py`).
*   The `SlackHumanVerificationAgent` uses this helper for the core functions of waiting for replies (`get_thread_replies`) and posting update/clarification messages back into the correct thread (`send_reply_in_thread`). Standard Arcade tools (like `SendMessageToChannel`) are still used by the agent for sending the *initial* non-threaded message.

## Dependencies

These custom tools rely on external libraries specified in the main `orb-workflow/pyproject.toml` file, including:
*   `arcadepy`: For interacting with Arcade authentication.
*   `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`: For the Gmail helper.
*   `slack_sdk`: For the Slack helper.
*   `python-dotenv`: For loading environment variables.

Please ensure dependencies are installed via `poetry install` in the `orb-workflow` directory.

## Agent Integration

*   The `EmailWatcherAgent` utilizes `GmailAttachmentTools` to handle email attachments.
*   The `SlackHumanVerificationAgent` utilizes `SlackHelper` to reliably manage threaded conversations for human-in-the-loop verification.

## Testing

These helper classes are tested implicitly when running their respective agents. You can test the agents individually:
*   Run `python agents/email_watcher_agent.py` (after configuring Gmail access via Arcade).
*   Run `python agents/slack_human_verification_agent.py` (after configuring Slack access via Arcade, including necessary history scopes). 