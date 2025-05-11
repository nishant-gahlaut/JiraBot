import logging
import json
from slack_sdk.errors import SlackApiError
from utils.state_manager import conversation_states
from services.genai_service import generate_ticket_title_and_description_from_text
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

def handle_generate_ai_ticket_details_after_duplicates(ack, body, client, logger):
    """Handles the 'Proceed with this Description' button after duplicate check. 
       Uses a single LLM call to generate AI title AND AI refined description.
    """
    ack()
    logger.info("'Proceed with this Description' button clicked. Generating AI title and description via single call.")
    assistant_id = None
    thread_ts = None
    user_raw_initial_description = ""
    channel_id = None # Initialize channel_id
    user_id = None # Initialize user_id

    try:
        action_value_str = body["actions"][0]["value"]
        # Attempt to get thread_ts for logging from body if possible, before action_value is parsed
        log_thread_ts = body.get("message", {}).get("thread_ts")
        if not log_thread_ts and body.get("container"): # Fallback for modal submissions or other contexts
            log_thread_ts = body["container"].get("thread_ts")
        if not log_thread_ts: # Ultimate fallback
            log_thread_ts = "N/A_see_action_value"

        logger.info(f"Thread {log_thread_ts}: Raw action_value string for handle_generate_ai_ticket_details_after_duplicates: {action_value_str}")
        action_value = json.loads(action_value_str)
        logger.info(f"Thread {log_thread_ts}: Parsed action_value keys: {list(action_value.keys())}")
        # To avoid overly verbose logs, let's log specific important values or a truncated version if necessary.
        # For now, let's assume the keys and the raw string are most critical for this specific KeyError.
        # logger.info(f"Thread {log_thread_ts}: Full action_value content: {action_value}")

        user_raw_initial_description = action_value["initial_description"]
        thread_ts = str(action_value["thread_ts"])
        channel_id = str(action_value["channel_id"])
        user_id = str(action_value["user_id"])
        assistant_id = str(action_value.get("assistant_id")) if action_value.get("assistant_id") else None

        # Check for pre-existing AI details from mention flow
        pre_existing_title = action_value.get("pre_existing_ai_title")
        pre_existing_description = action_value.get("pre_existing_ai_description")

        if assistant_id:
            try:
                client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="Generating AI suggestions...")
                logger.info(f"Thread {thread_ts}: Set status to 'Generating AI suggestions...'")
            except Exception as e:
                logger.error(f"Thread {thread_ts}: Error setting status before GenAI: {e}")

        if pre_existing_title and pre_existing_description:
            logger.info(f"Thread {thread_ts}: Using pre-existing AI details from mention flow. Title: '{pre_existing_title}', Desc: '{pre_existing_description[:50]}...'")
            suggested_title = pre_existing_title
            ai_refined_description = pre_existing_description
        else:
            logger.info(f"Thread {thread_ts}: No pre-existing AI details found or they are incomplete. Proceeding with user's raw description for new AI generation: '{user_raw_initial_description[:100]}...'")
            # Single call to GenAI service
            ai_components = generate_ticket_title_and_description_from_text(user_raw_initial_description)
            suggested_title = ai_components.get("suggested_title", "Could not generate title")
            ai_refined_description = ai_components.get("refined_description", "Could not generate description. Original: " + user_raw_initial_description)

        # Check if generation failed (service methods return error strings in values)
        if "Could not generate title" in suggested_title or "Could not generate description" in ai_refined_description or \
           suggested_title.startswith("Error:") or ai_refined_description.startswith("Error:"):
            logger.error(f"Thread {thread_ts}: AI generation failed. Title: '{suggested_title}', Description: '{ai_refined_description}'")
            # Inform the user of the failure
            error_message = "Sorry, I couldn't generate AI suggestions for your ticket. You can try again, or proceed to create the ticket manually."
            if channel_id and user_id: # Ensure we have these before trying to post
                 client.chat_postEphemeral(channel=channel_id, thread_ts=thread_ts, user=user_id, text=error_message)
            # Potentially, we could offer to proceed without AI suggestions or retry.
            # For now, we stop this path and let the user decide (e.g. re-click a button or give up).
            return # Stop further processing in this handler on critical AI failure

        logger.info(f"Thread {thread_ts}: GenAI suggested title: '{suggested_title}'")
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

        if channel_id: # Ensure channel_id is available before posting
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                blocks=ai_confirmation_blocks,
                text=f"AI Suggested Title: {suggested_title}"
            )
            logger.info(f"Thread {thread_ts}: Posted AI title and description suggestion with Continue/Modify buttons.")
        else:
            logger.error(f"Thread {thread_ts}: channel_id is None. Cannot post AI suggestions.")

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from button value in handle_generate_ai_ticket_details_after_duplicates: {e}")
    except KeyError as e:
        logger.error(f"Missing key in button value in handle_generate_ai_ticket_details_after_duplicates: {e}")
    except SlackApiError as e:
        logger.error(f"Slack API error in handle_generate_ai_ticket_details_after_duplicates: {e.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_generate_ai_ticket_details_after_duplicates: {e}", exc_info=True)
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
            logger.info(f"Thread {thread_ts}: Cleared conversation state due to cancellation.")
        
        if channel_id and user_id: # Ensure we have these to post
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"<@{user_id}>, the ticket creation process has been cancelled."
            )
            logger.info(f"Thread {thread_ts}: Posted ticket creation cancellation confirmation to user {user_id}.")
        else:
            logger.warning(f"Thread {thread_ts}: Could not post cancellation message due to missing channel_id or user_id.")

        # Clear assistant status if applicable
        if assistant_id and thread_ts:
            client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
            logger.info(f"Thread {thread_ts}: Cleared assistant status after cancellation.")

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from button value in cancel_creation_at_message_duplicates: {e}")
    except KeyError as e:
        logger.error(f"Missing key in button value in cancel_creation_at_message_duplicates: {e}")
    except SlackApiError as e:
        logger.error(f"Slack API error in cancel_creation_at_message_duplicates: {e.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error in cancel_creation_at_message_duplicates: {e}", exc_info=True) 