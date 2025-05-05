# actions_handler.py
import logging
from slack_sdk.errors import SlackApiError # Import SlackApiError

# Import state store from utils
# from state_manager import conversation_states # Old import
from utils.state_manager import conversation_states # Corrected import

logger = logging.getLogger(__name__)

def handle_create_ticket_action(ack, body, client, logger):
    """Handles the 'Create Ticket' button click."""
    ack() # Acknowledge the action immediately
    logger.info("'Create Ticket' button clicked.")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"] # Get thread_ts from the original message
    assistant_id = body.get("assistant", {}).get("id") # Get assistant_id

    # TODO: Implement the logic to start the create ticket flow
    # Example: Post a message asking for details
    try:
        # Set the state for this thread to indicate we're waiting for the summary
        conversation_states[thread_ts] = {
            "step": "awaiting_summary",
            "user_id": user_id,
            "channel_id": channel_id,
            "assistant_id": assistant_id,
            "data": {}
        }
        logger.info(f"Set state for thread {thread_ts} to 'awaiting_summary'")

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Okay, let's create a new Jira ticket. Please provide the issue/summary for the ticket."
        )
        if assistant_id:
            # Optionally clear status if needed, though posting a message might suffice
            client.assistant_threads_setStatus(
                assistant_id=assistant_id,
                thread_ts=thread_ts,
                status=""
            )
    except Exception as e:
        logger.error(f"Error posting create ticket prompt: {e}")


def handle_summarize_ticket_action(ack, body, client, logger):
    """Handles the 'Summarize Ticket' button click."""
    ack() # Acknowledge the action immediately
    logger.info("'Summarize Ticket' button clicked.")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"] # Get thread_ts from the original message
    assistant_id = body.get("assistant", {}).get("id") # Get assistant_id

    # Set state
    conversation_states[thread_ts] = {
        "step": "awaiting_summary_input",
        "user_id": user_id,
        "channel_id": channel_id,
        "assistant_id": assistant_id,
        "data": {}
    }
    logger.info(f"Set state for thread {thread_ts} to 'awaiting_summary_input'")

    # Ask for Ticket ID or URL
    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Okay, let's summarize a Jira ticket. Please provide the Ticket ID (e.g., PROJ-123) or the full Jira link."
        )
        if assistant_id:
             # Optionally clear status if needed
            client.assistant_threads_setStatus(
                assistant_id=assistant_id,
                thread_ts=thread_ts,
                status=""
            )
        logger.info(f"Asked for Ticket ID/URL for summarization in thread {thread_ts}")
    except SlackApiError as e:
        logger.error(f"Slack API Error posting summarize ticket prompt: {e.response['error']}")
    except Exception as e:
        logger.error(f"Error posting summarize ticket prompt: {e}")

def handle_continue_ticket_action(ack, body, client, logger):
    """Handles the 'Continue' button click after AI generation."""
    ack()
    logger.info("'Continue Ticket Creation' button clicked.")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]
    assistant_id = body.get("assistant", {}).get("id")

    # Retrieve state
    current_state = conversation_states.get(thread_ts)
    if not current_state or current_state["step"] != "awaiting_confirmation":
        logger.warning(f"Received continue action for thread {thread_ts} but state is not awaiting_confirmation: {current_state}")
        # TODO: Optionally post an error message back to the user
        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Sorry, something went wrong. Please try starting the process again."
            )
        except Exception as e:
            logger.error(f"Error posting state error message: {e}")
        return

    logger.info(f"Continuing ticket creation for thread {thread_ts}. Asking for priority.")

    # --- Ask for Priority --- 
    priority_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Great! Now, please select the priority for this ticket:"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Highest (P0)",
                        "emoji": True
                    },
                    "style": "danger", # Use styles to visually differentiate
                    "action_id": "select_priority_p0"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "High (P1)",
                        "emoji": True
                    },
                     "style": "primary",
                    "action_id": "select_priority_p1"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Medium (P2)",
                        "emoji": True
                    },
                    # Default style for Medium
                    "action_id": "select_priority_p2"
                }
            ]
        }
    ]

    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=priority_blocks,
            text="Please select the priority for this ticket:" # Fallback text
        )
        # Update state
        current_state["step"] = "awaiting_priority"
        conversation_states[thread_ts] = current_state
        logger.info(f"Updated state for thread {thread_ts} to 'awaiting_priority'")

    except Exception as e:
        logger.error(f"Error posting priority selection message: {e}")

def handle_modify_ticket_action(ack, body, client, logger):
    """Handles the 'Modify' button click after AI generation."""
    ack()
    logger.info("'Modify Ticket Details' button clicked.")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]
    assistant_id = body.get("assistant", {}).get("id")

    # Retrieve state
    current_state = conversation_states.get(thread_ts)
    if not current_state or current_state["step"] != "awaiting_confirmation":
        logger.warning(f"Received modify action for thread {thread_ts} but state is not awaiting_confirmation: {current_state}")
        return

    # TODO: Implement modification logic (e.g., ask user what to change)
    logger.info(f"User wants to modify ticket details for thread {thread_ts}. Data: {current_state['data']}")
    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Okay, what would you like to modify? (e.g., 'change title to ...', 'update description to ...')" # Placeholder
        )
        # Update state to reflect waiting for modification instructions
        # current_state["step"] = "awaiting_modification_details"
        # conversation_states[thread_ts] = current_state
        # logger.info(f"Updated state for thread {thread_ts} to {current_state['step']}")

    except Exception as e:
        logger.error(f"Error posting modify prompt: {e}")

def handle_select_priority_action(ack, body, client, logger, priority_level):
    """Handles the priority selection button clicks."""
    ack()
    logger.info(f"Priority '{priority_level}' button clicked.")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]
    assistant_id = body.get("assistant", {}).get("id")

    # Retrieve state
    current_state = conversation_states.get(thread_ts)
    if not current_state or current_state["step"] != "awaiting_priority":
        logger.warning(f"Received priority action ({priority_level}) for thread {thread_ts} but state is not awaiting_priority: {current_state}")
        # Optionally post an error message back to the user
        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Sorry, something went wrong while setting the priority. Please try starting again."
            )
        except Exception as e:
            logger.error(f"Error posting state error message for priority: {e}")
        return

    # Store the selected priority in the state data
    current_state["data"]["priority"] = priority_level
    # Update state to the next step (e.g., ready for creation or final confirmation)
    # current_state["step"] = "ready_to_create" # Or maybe "awaiting_project" if we add that step
    current_state["step"] = "awaiting_assignee" # Update state to ask for assignee next
    conversation_states[thread_ts] = current_state
    logger.info(f"Stored priority '{priority_level}' for thread {thread_ts}. Updated state to '{current_state['step']}'. Data: {current_state['data']}")

    # Ask for Assignee Name
    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Priority set to {priority_level}. Now, please enter the Jira username of the assignee for this ticket:"
        )
        logger.info(f"Asked for assignee for thread {thread_ts}")
    except SlackApiError as e:
        logger.error(f"Slack API Error posting assignee request message: {e.response['error']}")
        logger.error(f"Full Slack API Error details: {e.response}")
    except Exception as e:
        logger.error(f"Generic error posting assignee request message: {e}") 