import logging
import json
from slack_sdk.errors import SlackApiError
from utils.state_manager import conversation_states
from services.genai_service import generate_suggested_title, generate_refined_description
from handlers.modals.interaction_handlers import build_create_ticket_modal

logger = logging.getLogger(__name__)

def handle_create_ticket_action(ack, body, client, logger):
    """Handles the 'Create Ticket' button click by asking for initial summary/description."""
    ack() # Acknowledge the button click immediately
    logger.info("'Create Ticket' button clicked. Asking for initial description.")

    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]
    assistant_id = body.get("assistant", {}).get("id") # Get assistant_id if available

    # Set state to await the user's initial description
    conversation_states[thread_ts] = {
        "step": "awaiting_initial_summary",
        "user_id": user_id,
        "channel_id": channel_id,
        "assistant_id": assistant_id,
        "data": {}
    }
    logger.info(f"Set state for thread {thread_ts} to 'awaiting_initial_summary'")

    # Ask for the initial description
    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Okay, let's start creating a Jira ticket. Please describe the issue or request:"
        )
        if assistant_id:
            client.assistant_threads_setStatus(
                assistant_id=assistant_id,
                thread_ts=thread_ts,
                status=""
            )
    except Exception as e:
        logger.error(f"Error posting initial summary request: {e}")

def handle_continue_after_ai(ack, body, client, logger):
    """Handles the 'Continue' button click after AI suggestion. Opens the modal."""
    ack()
    logger.info("'Continue after AI' button clicked.")

    trigger_id = body["trigger_id"]
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]

    current_state = conversation_states.get(thread_ts)
    if not current_state or current_state["step"] != "awaiting_ai_confirmation":
        logger.warning(f"Received 'continue_after_ai' action for thread {thread_ts} but state is not awaiting_ai_confirmation: {current_state}")
        try:
             client.chat_postEphemeral(channel=channel_id, thread_ts=thread_ts, user=user_id, text="Sorry, something went wrong. Please try starting over.")
        except Exception as e:
             logger.error(f"Error posting ephemeral error message: {e}")
        return

    ai_refined_description = current_state["data"].get("ai_refined_description", "")
    suggested_title = current_state["data"].get("suggested_title", "")

    # This dictionary contains the context needed by handle_modal_submission
    context_to_store = {
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "user_id": user_id,
        # Include other details if needed by handle_modal_submission from this flow
        # For example, if the original description or AI suggestions are needed later:
        # "user_raw_initial_description": current_state["data"].get("user_raw_initial_description"),
        # "suggested_title_at_modal_open": suggested_title,
        # "ai_refined_description_at_modal_open": ai_refined_description
    }
    private_metadata_key_str = json.dumps(context_to_store)

    # Store this context in conversation_states using its JSON string as the key
    conversation_states[private_metadata_key_str] = context_to_store
    logger.info(f"Thread {thread_ts}: Stored modal context in conversation_states with key: {private_metadata_key_str}")

    try:
        logger.info(f"Modal pre-fill - Title: '{suggested_title}', Description: '{ai_refined_description}'")
        modal_view = build_create_ticket_modal(
            initial_summary=suggested_title,
            initial_description=ai_refined_description,
            private_metadata=private_metadata_key_str # Pass the string key
        )
        client.views_open(trigger_id=trigger_id, view=modal_view)
        logger.info(f"Opened create ticket modal for user {user_id} after AI confirmation (thread {thread_ts})")
    except SlackApiError as e:
        logger.error(f"Slack API Error opening modal after AI confirm: {e.response['error']}")
    except Exception as e:
        logger.error(f"Error opening create ticket modal after AI confirm: {e}")

def handle_modify_after_ai(ack, body, client, logger):
    """Handles the 'Modify' button click after AI suggestion. Opens the modal for editing."""
    ack()
    logger.info("'Modify after AI' button clicked. Opening modal for editing.")

    trigger_id = body["trigger_id"]
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]

    current_state = conversation_states.get(thread_ts)
    if not current_state or current_state["step"] != "awaiting_ai_confirmation":
        logger.warning(f"Received 'modify_after_ai' action for thread {thread_ts} but state is not awaiting_ai_confirmation: {current_state}")
        try:
             client.chat_postEphemeral(channel=channel_id, thread_ts=thread_ts, user=user_id, text="Sorry, something went wrong. Please try starting over.")
        except Exception as e:
             logger.error(f"Error posting ephemeral error message: {e}")
        return

    ai_refined_description = current_state["data"].get("ai_refined_description", "")
    suggested_title = current_state["data"].get("suggested_title", "")

    # This dictionary contains the context needed by handle_modal_submission
    context_to_store = {
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "user_id": user_id
        # Add other fields as in handle_continue_after_ai if necessary
    }
    private_metadata_key_str = json.dumps(context_to_store)

    # Store this context in conversation_states using its JSON string as the key
    conversation_states[private_metadata_key_str] = context_to_store
    logger.info(f"Thread {thread_ts}: Stored modal context (for modify) in conversation_states with key: {private_metadata_key_str}")

    try:
        logger.info(f"Modal pre-fill (modify) - Title: '{suggested_title}', Description: '{ai_refined_description}'")
        modal_view = build_create_ticket_modal(
            initial_summary=suggested_title,
            initial_description=ai_refined_description,
            private_metadata=private_metadata_key_str # Pass the string key
        )
        client.views_open(trigger_id=trigger_id, view=modal_view)
        logger.info(f"Opened create ticket modal for user {user_id} for modification (thread {thread_ts})")
    except SlackApiError as e:
        logger.error(f"Slack API Error opening modal for modification: {e.response['error']}")
    except Exception as e:
        logger.error(f"Error opening create ticket modal for modification: {e}")

def handle_proceed_to_ai_title_suggestion(ack, body, client, logger):
    """Handles the 'Proceed with this Description' button after duplicate check. 
       Now generates AI title AND AI refined description.
    """
    ack()
    logger.info("'Proceed with this Description' button clicked. Generating AI title and description.")
    assistant_id = None
    thread_ts = None
    user_raw_initial_description = ""

    try:
        action_value = json.loads(body["actions"][0]["value"])
        user_raw_initial_description = action_value["initial_description"]
        thread_ts = str(action_value["thread_ts"])
        channel_id = str(action_value["channel_id"])
        user_id = str(action_value["user_id"])
        assistant_id = str(action_value.get("assistant_id")) if action_value.get("assistant_id") else None

        logger.info(f"Thread {thread_ts}: Proceeding with user's raw description: '{user_raw_initial_description[:100]}...'")

        if assistant_id:
            try:
                client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="Generating AI suggestions...")
                logger.info(f"Thread {thread_ts}: Set status to 'Generating AI suggestions...'")
            except Exception as e:
                logger.error(f"Thread {thread_ts}: Error setting status before GenAI: {e}")

        suggested_title = generate_suggested_title(user_raw_initial_description)
        logger.info(f"Thread {thread_ts}: GenAI suggested title: '{suggested_title}'")

        ai_refined_description = generate_refined_description(user_raw_initial_description)
        logger.info(f"Thread {thread_ts}: GenAI refined description: '{ai_refined_description[:150]}...'")

        conversation_states[thread_ts] = {
            "step": "awaiting_ai_confirmation",
            "user_id": user_id,
            "channel_id": channel_id,
            "assistant_id": assistant_id,
            "data": {
                "user_raw_initial_description": user_raw_initial_description,
                "suggested_title": suggested_title,
                "ai_refined_description": ai_refined_description
            }
        }
        logger.info(f"Thread {thread_ts}: Updated state to 'awaiting_ai_confirmation' with AI title and description.")

        ai_confirmation_blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (f"Thanks! Based on your input, I suggest the following details for the Jira ticket:\n\n"
                             f"*Suggested Title:* {suggested_title}\n\n"
                             f"*Suggested Description:*\n```{ai_refined_description}```\n\n"
                             f"Would you like to proceed with these AI-generated details, or modify them further?"
                            )
                }
            },
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Continue", "emoji": True}, "style": "primary", "action_id": "continue_after_ai"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Modify", "emoji": True}, "action_id": "modify_after_ai"}
                ]
            }
        ]

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=ai_confirmation_blocks,
            text=f"AI Suggested Title: {suggested_title}"
        )
        logger.info(f"Thread {thread_ts}: Posted AI title and description suggestion with Continue/Modify buttons.")

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from button value in handle_proceed_to_ai_title_suggestion: {e}")
    except KeyError as e:
        logger.error(f"Missing key in button value in handle_proceed_to_ai_title_suggestion: {e}")
    except SlackApiError as e:
        logger.error(f"Slack API error in handle_proceed_to_ai_title_suggestion: {e.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_proceed_to_ai_title_suggestion: {e}", exc_info=True)
    finally:
        if assistant_id and thread_ts:
            try:
                client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
                logger.info(f"Thread {thread_ts}: Cleared status after AI suggestion step.")
            except Exception as se:
                logger.error(f"Thread {thread_ts}: Error clearing status: {se}")

def handle_cancel_creation_at_message_duplicates(ack, body, client, logger):
    """Handles 'Cancel Ticket Creation' from the duplicate check message step."""
    ack()
    logger.info("'Cancel Ticket Creation' button clicked at duplicate message step.")
    try:
        action_value = json.loads(body["actions"][0]["value"])
        thread_ts = str(action_value.get("thread_ts")) # Make .get robust
        user_id = str(action_value.get("user_id"))
        channel_id = str(action_value.get("channel_id"))
        assistant_id = str(action_value.get("assistant_id")) if action_value.get("assistant_id") else None # from orchestrator

        # Attempt to clear any active step for this thread
        if thread_ts and thread_ts in conversation_states:
            del conversation_states[thread_ts]
            logger.info(f"Thread {thread_ts}: Cleared state due to cancellation at duplicate check.")
        
        # Post a confirmation message
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"<@{user_id}>, the ticket creation process has been cancelled."
        )
        logger.info(f"Thread {thread_ts}: Posted cancellation confirmation for user {user_id}.")

        # Clear assistant status if applicable
        if assistant_id and thread_ts:
            try:
                client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
                logger.info(f"Thread {thread_ts}: Cleared assistant status after cancellation.")
            except Exception as e_status:
                logger.error(f"Thread {thread_ts}: Error clearing assistant status after cancellation: {e_status}")

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from button value in handle_cancel_creation: {e}")
    except KeyError as e:
        logger.error(f"Missing key in button value in handle_cancel_creation: {e}")
    except SlackApiError as e:
        logger.error(f"Slack API error in handle_cancel_creation: {e.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_cancel_creation: {e}", exc_info=True) 