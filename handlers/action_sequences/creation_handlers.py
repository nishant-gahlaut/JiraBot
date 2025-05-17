import logging
import json
import traceback
from slack_sdk.errors import SlackApiError
from utils.state_manager import conversation_states
from services.genai_service import generate_ticket_title_and_description_from_text
from handlers.modals.interaction_handlers import build_create_ticket_modal
from ..modals.modal_builders import build_description_capture_modal

logger = logging.getLogger(__name__)

def handle_create_ticket_action(ack, body, client, logger_param):
    """Handles the 'Create Ticket' button click from initial assistant CTAs."""
    ack()
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") # Might be None if button is not in a thread
    trigger_id = body["trigger_id"]

    logger_param.info(f"'Create Ticket' button clicked by user {user_id} in channel {channel_id}. Trigger ID: {trigger_id}")

    try:
        # Prepare private_metadata for the description capture modal
        initial_context = {
            "user_id": user_id,
            "channel_id": channel_id,
            "thread_ts": thread_ts, # Store even if None, for consistency
            "flow_origin": "create_ticket_button"
        }
        private_metadata_str = json.dumps(initial_context)

        description_modal_view = build_description_capture_modal(private_metadata=private_metadata_str)
        
        client.views_open(
            trigger_id=trigger_id,
            view=description_modal_view
        )
        logger_param.info(f"Opened description capture modal for user {user_id}.")

    except SlackApiError as e:
        logger_param.error(f"Slack API error opening description modal: {e.response['error']}", exc_info=True)
        # Try to send an ephemeral message if modal opening fails
        try:
            client.chat_postEphemeral(
                channel=channel_id, 
                user=user_id, 
                thread_ts=thread_ts, 
                text="Sorry, I couldn't open the form to create a ticket. Please try again."
            )
        except Exception as e_ephemeral:
            logger_param.error(f"Failed to send ephemeral error for description modal failure: {e_ephemeral}")
    except Exception as e:
        logger_param.error(f"Unexpected error in handle_create_ticket_action: {e}", exc_info=True)
        try:
            client.chat_postEphemeral(
                channel=channel_id, 
                user=user_id, 
                thread_ts=thread_ts, 
                text="An unexpected error occurred. Please try again."
            )
        except Exception as e_ephemeral:
            logger_param.error(f"Failed to send ephemeral error for unexpected error: {e_ephemeral}")

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
        
        # Robustly get thread_ts for logging, trying different locations in the body
        log_thread_ts = "N/A_in_action_value_parsing" # Default if not found earlier
        if body.get("message") and body["message"].get("thread_ts"):
            log_thread_ts = body["message"]["thread_ts"]
        elif body.get("container") and body["container"].get("thread_ts"):
            log_thread_ts = body["container"]["thread_ts"]
        
        logger.info(f"Thread {log_thread_ts}: Raw action_value string for handle_generate_ai_ticket_details_after_duplicates: {action_value_str}")
        parsed_button_payload = json.loads(action_value_str)
        logger.info(f"Thread {log_thread_ts}: Parsed button payload keys: {list(parsed_button_payload.keys())}")

        # --- Accessing keys using .get() and checking for None ---
        user_raw_initial_description = None
        thread_ts_from_action = None
        channel_id_from_action = None
        user_id_from_action = None
        critical_key_missing = False

        try:
            logger.info(f"Thread {log_thread_ts}: DEBUG: PRE-ACCESS parsed_button_payload.get('initial_description')")
            user_raw_initial_description = parsed_button_payload.get("initial_description")
            if user_raw_initial_description is None:
                logger.error(f"Thread {log_thread_ts}: CRITICAL: 'initial_description' is None after get(). Payload keys: {list(parsed_button_payload.keys())}")
                critical_key_missing = True
            logger.info(f"Thread {log_thread_ts}: DEBUG: POST-ACCESS parsed_button_payload.get('initial_description') - Value: {user_raw_initial_description[:50] if user_raw_initial_description else 'None'}...")
        except Exception as e_get_desc:
            logger.error(f"Thread {log_thread_ts}: UNEXPECTED error during .get('initial_description'): {str(e_get_desc)}")
            raise

        try:
            logger.info(f"Thread {log_thread_ts}: DEBUG: PRE-ACCESS parsed_button_payload.get('thread_ts')")
            thread_ts_from_action = parsed_button_payload.get("thread_ts")
            if thread_ts_from_action is None:
                logger.error(f"Thread {log_thread_ts}: CRITICAL: 'thread_ts' is None after get(). Payload keys: {list(parsed_button_payload.keys())}")
                critical_key_missing = True
            logger.info(f"Thread {log_thread_ts}: DEBUG: POST-ACCESS parsed_button_payload.get('thread_ts') - Value: {thread_ts_from_action}")
        except Exception as e_get_ts:
            logger.error(f"Thread {log_thread_ts}: UNEXPECTED error during .get('thread_ts'): {str(e_get_ts)}")
            raise

        try:
            logger.info(f"Thread {log_thread_ts}: DEBUG: PRE-ACCESS parsed_button_payload.get('channel_id')")
            channel_id_from_action = parsed_button_payload.get("channel_id")
            if channel_id_from_action is None:
                logger.error(f"Thread {log_thread_ts}: CRITICAL: 'channel_id' is None after get(). Payload keys: {list(parsed_button_payload.keys())}")
                critical_key_missing = True
            logger.info(f"Thread {log_thread_ts}: DEBUG: POST-ACCESS parsed_button_payload.get('channel_id') - Value: {channel_id_from_action}")
        except Exception as e_get_ch:
            logger.error(f"Thread {log_thread_ts}: UNEXPECTED error during .get('channel_id'): {str(e_get_ch)}")
            raise
        
        try:
            logger.info(f"Thread {log_thread_ts}: DEBUG: PRE-ACCESS parsed_button_payload.get('user_id')")
            user_id_from_action = parsed_button_payload.get("user_id")
            if user_id_from_action is None:
                logger.error(f"Thread {log_thread_ts}: CRITICAL: 'user_id' is None after get(). Payload keys: {list(parsed_button_payload.keys())}")
                critical_key_missing = True
            logger.info(f"Thread {log_thread_ts}: DEBUG: POST-ACCESS parsed_button_payload.get('user_id') - Value: {user_id_from_action}")
        except Exception as e_get_uid:
            logger.error(f"Thread {log_thread_ts}: UNEXPECTED error during .get('user_id'): {str(e_get_uid)}")
            raise
        
        if critical_key_missing:
            logger.error(f"Thread {log_thread_ts}: Aborting due to one or more critical keys missing from button payload.")
            # Consider how to handle this - perhaps post an error message to the user?
            return # Stop further processing

        # Assign to function-scoped variables after successful retrieval and type conversion (if needed)
        thread_ts = str(thread_ts_from_action) # Ensure string conversion
        channel_id = str(channel_id_from_action) # Ensure string conversion
        user_id = str(user_id_from_action) # Ensure string conversion
        
        assistant_id = str(parsed_button_payload.get("assistant_id")) if parsed_button_payload.get("assistant_id") else None
        pre_existing_title = parsed_button_payload.get("pre_existing_ai_title")
        pre_existing_description = parsed_button_payload.get("pre_existing_ai_description")

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
            logger.info(f"Thread {log_thread_ts}: DEBUG: About to call generate_ticket_title_and_description_from_text. Checking parsed_button_payload one last time: {list(parsed_button_payload.keys())}")
            ai_components = generate_ticket_title_and_description_from_text(user_raw_initial_description)
            logger.info(f"Thread {log_thread_ts}: DEBUG: Successfully called generate_ticket_title_and_description_from_text.")
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

    except json.JSONDecodeError as e_json: # Moved specific error type first
        logger.error(f"Thread {log_thread_ts}: Error decoding JSON from button value in handle_generate_ai_ticket_details_after_duplicates: {e_json}")
    except KeyError as e_key: # General KeyError if not caught by specific ones above
        logger.info(f"Thread {log_thread_ts}: DEBUG: Caught by GENERAL KeyError: {str(e_key)}") # DEBUG PRINT
        logger.error(f"Traceback for KeyError: {traceback.format_exc()}") # Log full traceback
        logger.error(f"Thread {log_thread_ts}: General KeyError in handle_generate_ai_ticket_details_after_duplicates (should have been caught by specific handlers above if related to primary keys): {e_key}. This indicates an unexpected key issue. Actual key that failed: '{str(e_key)}'")
    except Exception as e_exc:
        logger.error(f"Unexpected error in handle_generate_ai_ticket_details_after_duplicates: {e_exc}", exc_info=True)
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
                text=f"The ticket creation process has been cancelled."
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