# app.py
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory store for conversation states (simple approach)
# Key: thread_ts, Value: dict containing state info (e.g., {'step': 'awaiting_summary', 'data': {...}})
# conversation_states = {} # Removed - Moved to state_manager.py

# Import state manager
from utils.state_manager import conversation_states

# Import action handlers
from handlers.action_handler import (
    handle_create_ticket_action,
    handle_summarize_ticket_action,
    handle_create_ticket_submission,
    handle_continue_after_ai,
    handle_modify_after_ai
)
# Import GenAI handler
# from genai_handler import generate_jira_details # Moved to message_handler
# Import Jira & Summarize handlers
# from jira_handler import extract_ticket_id_from_input, fetch_jira_ticket_data # Moved to message_handler
# from summarize_handler import summarize_jira_ticket # Moved to message_handler

# Import the message handler
from handlers.message_handler import handle_message

# Load environment variables from .env file
load_dotenv()

# Initializes your app with your bot token and signing secret
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
)

# --- Event Listeners and Handlers ---

# 1 & 2: Listen and respond to assistant_thread_started
@app.event("assistant_thread_started")
def handle_assistant_thread_started(event, client, context, logger):
    """Handles the event when a user first opens the assistant container."""
    logger.info(f"Received assistant_thread_started event: {event}")

    # Extract information from the correct location in the event payload
    assistant_thread_data = event.get("assistant_thread", {})
    channel_id = assistant_thread_data.get("channel_id")
    user_id = assistant_thread_data.get("user_id")
    thread_ts = assistant_thread_data.get("thread_ts")
    assistant_id = context.get("assistant_id") # Get assistant_id from context (remains the same)

    # Log the extracted context (Team ID removed as it's not directly available here)
    logger.info(f"Context - Channel: {channel_id}, User: {user_id}, Thread: {thread_ts}, Assistant: {assistant_id}")

    # Check if essential info is missing
    if not channel_id or not thread_ts:
        logger.error(f"Could not extract channel_id ({channel_id}) or thread_ts ({thread_ts}) from event. Cannot proceed.")
        return # Stop processing if we can't post a message

    # Example: Check if app has access to the channel (optional)
    # try:
    #     info = client.conversations_info(channel=channel_id)
    #     logger.info(f"Channel info: {info}")
    # except Exception as e:
    #     logger.error(f"Error fetching channel info: {e}")

    # Example: Set initial status while generating prompts (can be removed if not needed)
    # try:
    #     client.assistant_threads_setStatus(
    #         assistant_id=assistant_id,
    #         thread_ts=thread_ts,
    #         status="Thinking..."
    #     )
    #     logger.info("Set initial status to 'Thinking...'")
    # except Exception as e:
    #     logger.error(f"Error setting status: {e}")


    # Display initial CTAs using Block Kit
    initial_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Hello! How can I help you with Jira today?"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Create Ticket",
                        "emoji": True
                    },
                    "action_id": "create_ticket_action", # Unique ID for this button
                    "style": "primary" # Make this button stand out
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Summarize Ticket",
                        "emoji": True
                    },
                    "action_id": "summarize_ticket_action" # Unique ID for this button
                }
            ]
        }
    ]

    try:
        # Post the initial message with buttons in the assistant thread
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts, # Post in the specific assistant thread
            blocks=initial_blocks,
            text="Hello! How can I help you with Jira today?" # Fallback text
        )
        logger.info(f"Posted initial CTAs to thread {thread_ts}")

        # Clear the status after posting message (if set previously)
        # if assistant_id:
        #     client.assistant_threads_setStatus(
        #         assistant_id=assistant_id,
        #         thread_ts=thread_ts,
        #         status="" # Empty string clears the status
        #     )
        #     logger.info("Cleared status after posting initial message.")

    except Exception as e:
        logger.error(f"Error posting initial message with buttons: {e}")


# Register Action Listeners for the buttons
@app.action("create_ticket_action")
def trigger_create_ticket(ack, body, client):
    handle_create_ticket_action(ack, body, client, logger)

@app.action("summarize_ticket_action")
def trigger_summarize_ticket(ack, body, client):
    handle_summarize_ticket_action(ack, body, client, logger)

# Action listeners for AI confirmation buttons
@app.action("continue_after_ai")
def trigger_continue_after_ai(ack, body, client):
    handle_continue_after_ai(ack, body, client, logger)

@app.action("modify_after_ai")
def trigger_modify_after_ai(ack, body, client):
    handle_modify_after_ai(ack, body, client, logger)

# Listener for modal submission
@app.view("create_ticket_modal_submission")
def handle_view_submission(ack, body, client, logger):
    handle_create_ticket_submission(ack, body, client, logger)


# Listen for context changes (Optional)
@app.event("assistant_thread_context_changed")
def handle_context_changed(event, logger):
    """Handles the event when a user changes channel while container is open."""
    logger.info(f"Received assistant_thread_context_changed event: {event}")
    # Track the user's active context if needed


# 3 & 4: Listen and respond to message.im
@app.event("message") # Catches Direct Messages (IMs) and potentially others
def handle_message_events(message, client, context, logger):
    """Handles messages sent directly to the bot by routing to message_handler."""
    # Route the event to the dedicated handler function
    handle_message(message, client, context, logger)


# --- Start the App ---
if __name__ == "__main__":
    try:
        # Use SocketModeHandler for development/testing without exposing a public URL
        # Requires SLACK_APP_TOKEN (App-Level Token with connections:write scope)
        handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
        logger.info("Starting Socket Mode handler...")
        handler.start()
    except KeyError as e:
        logger.error(f"Missing environment variable: {e}. Ensure SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, and SLACK_APP_TOKEN are set in .env")
    except Exception as e:
        logger.error(f"Error starting app: {e}") 