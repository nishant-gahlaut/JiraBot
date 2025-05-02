# app.py
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    channel_id = event.get("context", {}).get("channel_id")
    team_id = event.get("context", {}).get("team_id")
    user_id = event.get("user_id") # Assuming user_id might be available directly in the event

    logger.info(f"Context - Channel: {channel_id}, Team: {team_id}, User: {user_id}")

    # Example: Check if app has access to the channel (optional)
    # try:
    #     info = client.conversations_info(channel=channel_id)
    #     logger.info(f"Channel info: {info}")
    # except Exception as e:
    #     logger.error(f"Error fetching channel info: {e}")

    # Example: Set initial status while generating prompts
    try:
        client.assistant_threads_setStatus(
            assistant_id=context.get("assistant_id"), # Assuming assistant_id is in context
            thread_ts=event.get("thread_ts"),       # Assuming thread_ts is in the event payload
            status="Thinking..."
        )
        logger.info("Set initial status to 'Thinking...'")
    except Exception as e:
        logger.error(f"Error setting status: {e}")


    # Example: Set suggested prompts
    try:
        # Replace with your actual suggested prompts
        suggested_prompts = [
            {"prompt": "Create a new Jira issue"},
            {"prompt": "Show my assigned issues"},
            {"prompt": "Update issue status"}
        ]
        client.assistant_threads_setSuggestedPrompts(
           assistant_id=context.get("assistant_id"), # Assuming assistant_id is in context
           thread_ts=event.get("thread_ts"),       # Assuming thread_ts is in the event payload
           prompts=suggested_prompts
        )
        logger.info(f"Set suggested prompts: {suggested_prompts}")

        # Clear the status after setting prompts (if set previously)
        client.assistant_threads_setStatus(
            assistant_id=context.get("assistant_id"),
            thread_ts=event.get("thread_ts"),
            status="" # Empty string clears the status
        )
        logger.info("Cleared status after setting prompts.")

    except Exception as e:
        logger.error(f"Error setting suggested prompts or clearing status: {e}")


# Listen for context changes (Optional)
@app.event("assistant_thread_context_changed")
def handle_context_changed(event, logger):
    """Handles the event when a user changes channel while container is open."""
    logger.info(f"Received assistant_thread_context_changed event: {event}")
    # Track the user's active context if needed


# 3 & 4: Listen and respond to message.im
@app.event("message") # Catches Direct Messages (IMs) and potentially others
def handle_message_events(message, client, context, logger):
    """Handles messages sent directly to the bot."""
    # Check if it's a direct message (IM) and not from the bot itself
    if message.get("channel_type") == "im" and "bot_id" not in message:
        logger.info(f"Received message.im event: {message}")
        channel_id = message["channel"]
        user_id = message["user"]
        text = message.get("text", "")
        thread_ts = message.get("thread_ts") # Important for threading in assistant container
        assistant_id = context.get("assistant_id") # Get assistant_id from context

        # Set status immediately only if in an assistant thread
        if thread_ts and assistant_id:
             try:
                 client.assistant_threads_setStatus(
                     assistant_id=assistant_id,
                     thread_ts=thread_ts,
                     status="Responding..." # Simple status
                 )
                 logger.info("Set responding status.")
             except Exception as e:
                 # Log the error but continue, maybe assistant_id/thread_ts wasn't as expected
                 logger.error(f"Error setting status on message: {e}")


        # --- Simple Response Logic ---
        response_text = "hello"
        # --- End Simple Response Logic ---


        # Post the response back to the same thread if thread_ts exists
        if thread_ts:
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts, # Respond in the assistant thread
                    text=response_text
                )
                logger.info(f"Sent '{response_text}' response to thread {thread_ts}")
                # Status is automatically cleared by sending a message.
            except Exception as e:
                logger.error(f"Error posting message to thread: {e}")
        else:
            # Handle messages outside the assistant thread if necessary
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"Hi there! Please interact with me using the Assistant container."
                )
                logger.info(f"Sent non-threaded response to channel {channel_id}")
            except Exception as e:
                logger.error(f"Error posting non-threaded message: {e}")


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