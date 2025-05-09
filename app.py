# app.py
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
import logging
from slack_sdk import WebClient
import json
from slack_sdk.errors import SlackApiError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory store for conversation states (simple approach)
# Key: thread_ts, Value: dict containing state info (e.g., {'step': 'awaiting_summary', 'data': {...}})
# conversation_states = {} # Removed - Moved to state_manager.py

# Import state manager
from utils.state_manager import conversation_states

# Import action handlers
# from handlers.action_handler import (
#     handle_create_ticket_action, MOVED
#     handle_summarize_ticket_action,
#     handle_continue_after_ai, MOVED
#     handle_modify_after_ai, MOVED
#     handle_proceed_to_ai_title_suggestion, MOVED
#     handle_summarize_individual_duplicates_from_message,
#     handle_refine_description_after_duplicates, MOVED
#     handle_cancel_creation_at_message_duplicates, MOVED
#     handle_summarize_specific_duplicate_ticket
# )
# Import modal submission handler from its new location
from handlers.modals.interaction_handlers import handle_create_ticket_submission

# Import ticket creation flow handlers from their new location
from handlers.action_sequences.creation_handlers import (
    handle_create_ticket_action,
    handle_continue_after_ai,
    handle_modify_after_ai,
    handle_proceed_to_ai_title_suggestion,
    handle_cancel_creation_at_message_duplicates
    # handle_proceed_directly_to_modal_no_ai # This import will be an issue if the function is removed from creation_handlers.py
)

from handlers.my_tickets_handler import (
    handle_my_tickets_initial_action,
    handle_my_tickets_period_selection,
    handle_my_tickets_status_selection
)
# Import GenAI handler
# from genai_handler import generate_jira_details # Moved to message_handler
# Import Jira & Summarize handlers
# from jira_handler import extract_ticket_id_from_input, fetch_jira_ticket_data # Moved to message_handler
# from summarize_handler import summarize_jira_ticket # Moved to message_handler

# Import the message handler
from handlers.message_handler import handle_message

# Import Jira scraper functions
from utils.jira_scraper import scrape_and_store_tickets

# Import the ingestion pipeline runner
from pipelines.ingestion_pipeline import run_ingestion_pipeline

# Import summarization handlers from handlers.flows.summarization_handlers
from handlers.action_sequences.summarization_handlers import (
    handle_summarize_ticket_action,
    handle_summarize_individual_duplicates_from_message,
    handle_summarize_specific_duplicate_ticket
)

# Import mention handler
from handlers.mention_handler import handle_app_mention_event, fetch_conversation_context_for_mention, format_messages_for_summary, summarize_conversation

# Import mention flow handlers
from handlers.modals.interaction_handlers import build_create_ticket_modal
from services.jira_service import create_jira_ticket
from handlers.flows.ticket_creation_orchestrator import present_duplicate_check_and_options
# Import AI title/description generators
from services.genai_service import generate_suggested_title, generate_refined_description, generate_ticket_components_from_thread
# Import UI helpers
from utils.slack_ui_helpers import get_issue_type_emoji, get_priority_emoji, build_rich_ticket_blocks

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
                    "action_id": "create_ticket_action",
                    "style": "primary"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Summarize Ticket",
                        "emoji": True
                    },
                    "action_id": "summarize_ticket_action"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "My Tickets",
                        "emoji": True
                    },
                    "action_id": "my_tickets_action" # New action ID
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
def trigger_continue_after_ai(ack, body, client, logger):
    handle_continue_after_ai(ack, body, client, logger)

@app.action("modify_after_ai")
def trigger_modify_after_ai(ack, body, client, logger):
    handle_modify_after_ai(ack, body, client, logger)

# --- New Action Listeners for Duplicate Detection Flow ---
@app.action("proceed_to_ai_title_suggestion")
def trigger_proceed_to_ai_title(ack, body, client, logger):
    handle_proceed_to_ai_title_suggestion(ack, body, client, logger)

@app.action("summarize_individual_duplicates_message_step")
def trigger_summarize_individual_duplicates_msg_step(ack, body, client, logger):
    handle_summarize_individual_duplicates_from_message(ack, body, client, logger)

# @app.action("refine_description_after_duplicates")
# def trigger_refine_description_duplicates(ack, body, client, logger):
#     handle_refine_description_after_duplicates(ack, body, client, logger)

@app.action("cancel_creation_at_message_duplicates")
def trigger_cancel_creation_message_duplicates(ack, body, client, logger):
    handle_cancel_creation_at_message_duplicates(ack, body, client, logger)

# @app.action("proceed_directly_to_modal_no_ai")
# def trigger_proceed_directly_modal(ack, body, client, logger):
#     handle_proceed_directly_to_modal_no_ai(ack, body, client, logger)

# Handler for new individual ticket summarization button
@app.action("summarize_specific_duplicate_ticket")
def trigger_summarize_specific_duplicate(ack, body, client, logger):
    handle_summarize_specific_duplicate_ticket(ack, body, client, logger)

# --- My Tickets Flow Action Listeners ---
@app.action("my_tickets_action")
def trigger_my_tickets_initial(ack, body, client):
    handle_my_tickets_initial_action(ack, body, client, logger)

@app.action("my_tickets_period_1w")
def trigger_my_tickets_period_1w(ack, body, client):
    handle_my_tickets_period_selection(ack, body, client, logger, period_value="1w")

@app.action("my_tickets_period_2w")
def trigger_my_tickets_period_2w(ack, body, client):
    handle_my_tickets_period_selection(ack, body, client, logger, period_value="2w")

@app.action("my_tickets_period_1m")
def trigger_my_tickets_period_1m(ack, body, client):
    handle_my_tickets_period_selection(ack, body, client, logger, period_value="1m") # Will be converted to -4w in JQL

@app.action("my_tickets_status_open")
def trigger_my_tickets_status_open(ack, body, client):
    handle_my_tickets_status_selection(ack, body, client, logger, status_value="Open")

@app.action("my_tickets_status_indetailing")
def trigger_my_tickets_status_indetailing(ack, body, client):
    handle_my_tickets_status_selection(ack, body, client, logger, status_value="In Detailing") # Adjust status names if different in your Jira

@app.action("my_tickets_status_indev")
def trigger_my_tickets_status_indev(ack, body, client):
    handle_my_tickets_status_selection(ack, body, client, logger, status_value="In Dev")

@app.action("my_tickets_status_qa")
def trigger_my_tickets_status_qa(ack, body, client):
    handle_my_tickets_status_selection(ack, body, client, logger, status_value="QA") # Or "In QA"

@app.action("my_tickets_status_closed")
def trigger_my_tickets_status_closed(ack, body, client):
    handle_my_tickets_status_selection(ack, body, client, logger, status_value="Closed")

# Listener for modal submission
# Commenting out the old generic handler, as we want the specific one below to handle this view_id
# @app.view("create_ticket_modal_submission") 
# def handle_view_submission(ack, body, client, logger):
#     handle_create_ticket_submission(ack, body, client, logger)


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


# --- Event Handlers ---
@app.event("message")
def message_event(message, say, client, context, logger):
    logger.info(f"Received message event: {message}")
    handle_message(message=message, client=client, context=context, logger=logger)

@app.event("app_mention")
def app_mention_event_handler(event, client, context, logger):
    logger.info(f"Received app_mention event: {event}")
    # Add bot_user_id to context if not already present by Bolt
    # Bolt's context for events usually includes `bot_user_id` and `authorizations`
    # If context doesn't have bot_user_id, it might need to be fetched or passed during app init.
    # For now, assuming context['bot_user_id'] is available.
    if 'bot_user_id' not in context:
        logger.warning("bot_user_id not in context for app_mention event. Fetching auth.test...")
        try:
            auth_test_res = client.auth_test()
            context['bot_user_id'] = auth_test_res['user_id']
            logger.info(f"Fetched bot_user_id: {context['bot_user_id']}")
        except Exception as e:
            logger.error(f"Failed to fetch bot_user_id via auth.test: {e}")
            # Potentially critical, the mention handler might not work correctly without it
            # For now, we'll let it proceed, but mention_handler has a check
    
    handle_app_mention_event(event=event, client=client, logger_param=logger, context=context)


# --- Action Handlers ---
# Actions from duplicate detection flow
@app.action("proceed_with_description")
def handle_proceed_action(ack, body, client, logger):
    handle_proceed_with_description_action(ack, body, client, logger)

@app.action("summarize_individual_duplicates")
def handle_summarize_individual_action(ack, body, client, logger):
    handle_summarize_individual_duplicates_action(ack, body, client, logger)

@app.action("refine_description")
def handle_refine_action(ack, body, client, logger):
    handle_refine_description_action(ack, body, client, logger)

@app.action("cancel_ticket_creation")
def handle_cancel_action(ack, body, logger):
    handle_cancel_ticket_creation_action(ack, body, logger)
    
@app.action("create_ticket_direct") # General "Create Ticket" button
def handle_create_ticket_direct(ack, body, client, logger):
    # This might be similar to handle_proceed_action or directly open modal
    # For now, let's assume it uses the existing logic for opening the modal.
    # It needs user_text. If this button is context-less, it might need a different flow.
    # Let's adapt this for the proceed_with_description use-case from mention, assuming summary is stored
    handle_proceed_with_description_action(ack, body, client, logger)


# --- Action Handlers for Mention Flow ---
@app.action("mention_flow_create_ticket")
def handle_mention_create_ticket_action(ack, body, client, logger):
    ack()
    user_id_who_clicked = body["user"]["id"] # User who clicked the button
    thread_ts = body["message"]["thread_ts"]
    channel_id = body["channel"]["id"]
    assistant_id_from_body = body.get("assistant", {}).get("id") # Get assistant_id if available
    
    logger.info(f"Mention flow: 'Create Ticket' clicked by {user_id_who_clicked} in thread {thread_ts}. Initiating duplicate check based on bot summary.")

    # Retrieve the bot-generated summary stored by post_summary_with_ctas in mention_handler
    mention_context_key_from_button = None
    try:
        if body.get("actions") and body["actions"][0].get("value"):
            button_value = json.loads(body["actions"][0]["value"])
            mention_context_key_from_button = button_value.get("mention_context_key")
    except json.JSONDecodeError as e:
        logger.warning(f"Could not parse button value JSON for mention_context_key: {e}. Value: {body.get('actions', [{}])[0].get('value')}")

    actual_mention_context_key = mention_context_key_from_button
    if not actual_mention_context_key:
        # Fallback might be needed if key is absolutely not in button value
        # For now, we rely on it being passed correctly. If not, the mention_context fetch will fail.
        logger.warning(f"mention_context_key not found in button value. Trying to retrieve context using a potentially incomplete key or logic.")
        # Attempting a reconstruction (might be fragile)
        # The key was f"{thread_ts}_{original_user_id_of_mention}_{channel_id}_mention_context"
        # original_user_id_of_mention is not directly available here without being in button_value.
        # This part needs to be robust; the orchestrator needs the correct user_id.
        # The orchestrator also expects an assistant_id, so try to pass that through as well.

    mention_context = conversation_states.get(actual_mention_context_key)
    
    bot_summary_as_description = "Could not retrieve conversation summary."
    original_user_id_for_context = user_id_who_clicked # User who triggered the original mention summary
    # The assistant_id for the orchestrator should be the one active during the mention, if available from context.
    # If not in mention_context, use the one from the button body as a fallback.
    assistant_id_for_orchestrator = assistant_id_from_body 

    if mention_context and "summary" in mention_context:
        bot_summary_as_description = mention_context["summary"]
        original_user_id_for_context = mention_context.get("user_id", user_id_who_clicked) 
        # Prefer assistant_id from the stored context if available, as it's more likely tied to the original event
        assistant_id_for_orchestrator = mention_context.get("assistant_id", assistant_id_from_body)
        logger.info(f"Retrieved bot summary for duplicate check: {bot_summary_as_description[:100]}... Original mention by {original_user_id_for_context}. Assistant ID for orchestrator: {assistant_id_for_orchestrator}")
    else:
        logger.error(f"Could not retrieve bot summary from conversation_states for key {actual_mention_context_key}. Cannot proceed with duplicate check.")
        try:
            client.chat_postEphemeral(channel=channel_id, thread_ts=thread_ts, user=user_id_who_clicked, text="Sorry, I couldn't retrieve the conversation summary to proceed. Please try mentioning me again.")
        except Exception as e_ephemeral:
            logger.error(f"Failed to send ephemeral error for missing summary: {e_ephemeral}")
        return

    # Call the orchestrator
    # The user_id passed to orchestrator should be original_user_id_for_context
    present_duplicate_check_and_options(
        client=client,
        channel_id=channel_id,
        thread_ts=thread_ts,
        user_id=original_user_id_for_context, 
        initial_description=bot_summary_as_description,
        assistant_id=assistant_id_for_orchestrator 
    )
    
    # Clean up the specific mention context state if it was successfully used
    # Note: The orchestrator itself does not manage conversation_states.
    # This state was specific to passing the summary from mention_handler to this action.
    if actual_mention_context_key and actual_mention_context_key in conversation_states:
        del conversation_states[actual_mention_context_key]
        logger.info(f"Thread {thread_ts}: Cleared mention context state '{actual_mention_context_key}' after calling orchestrator.")


@app.action("mention_flow_find_issues")
def handle_mention_find_similar_issues_action(ack, body, client, logger):
    ack()
    user_id = body["user"]["id"]
    thread_ts = body["message"]["thread_ts"]
    channel_id = body["channel"]["id"]

    logger.info(f"Mention flow: 'Find Similar Issues' clicked by {user_id} in thread {thread_ts}")

    # Construct the key to retrieve mention context, matching how it's set in mention_handler.py
    # It seems mention_handler uses a key like f"{event_thread_ts}_{event_user_id}_{channel_id}_mention_context"
    # We need to ensure this key is consistent or passed correctly. The button value might be more reliable if it stores it.
    mention_context_key_from_button = None
    original_user_id_for_context = user_id # Default to user who clicked if key not found
    try:
        if body.get("actions") and body["actions"][0].get("value"):
            button_value = json.loads(body["actions"][0]["value"])
            mention_context_key_from_button = button_value.get("mention_context_key")
            # If the original user_id was stored in the button value during its creation, use that for context key.
            original_user_id_for_context = button_value.get("original_user_id", user_id)
            logger.info(f"Retrieved mention_context_key '{mention_context_key_from_button}' and original_user_id '{original_user_id_for_context}' from button value.")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning(f"Could not parse button value JSON for mention_context_key or original_user_id: {e}. Value: {body.get('actions', [{}])[0].get('value')}")
        # Fallback: Try to construct the key if not in button. This is less robust.
        # This assumes the user_id in body["user"]["id"] is the one who originally triggered the mention.
        # This might not always be true if someone else clicks a button on a message generated for another user.
        # The original_user_id should ideally be part of the CTA that leads here.
        # For now, if not in button, we use user_id who clicked.
        # mention_context_key_from_button = f"{thread_ts}_{user_id}_mention_context"
        # logger.info(f"Falling back to constructed mention_context_key: {mention_context_key_from_button}")

    actual_mention_context_key = mention_context_key_from_button
    mention_context = None
    if actual_mention_context_key:
        mention_context = conversation_states.get(actual_mention_context_key)
    
    summary_to_search = ""
    if mention_context and "summary" in mention_context:
        summary_to_search = mention_context["summary"]
        logger.info(f"Retrieved summary for duplicate search using key '{actual_mention_context_key}': {summary_to_search[:100]}...")
    else:
        logger.warning(f"Could not retrieve summary from conversation_states for key '{actual_mention_context_key}'. Cannot find similar issues.")
        client.chat_postEphemeral(channel=channel_id, thread_ts=thread_ts, user=user_id, text="Sorry, I couldn't retrieve the conversation summary to search for similar issues. Please try mentioning me again.")
        return

    if not summary_to_search.strip():
        logger.warning("Summary to search is empty. Aborting find similar issues.")
        client.chat_postEphemeral(channel=channel_id, thread_ts=thread_ts, user=user_id, text="The conversation summary was empty, so I can't search for similar issues.")
        return
        
    try:
        client.chat_postEphemeral(
            channel=channel_id, 
            thread_ts=thread_ts, 
            user=user_id,
            text=f"Thanks, <@{user_id}>! Searching for JIRA tickets similar to the conversation summary..."
        )

        duplicate_results = find_and_summarize_duplicates(user_query=summary_to_search)
        top_tickets = duplicate_results.get("tickets", [])
        overall_summary = duplicate_results.get("summary", "Could not generate an overall summary for similar tickets.")

        response_blocks = []
        if top_tickets:
            response_blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Here are some existing JIRA tickets that might be related to the conversation:"}
            })
            if overall_summary and overall_summary != "Could not generate an overall summary for similar tickets.":
                 response_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"_{overall_summary}_"}})
            # response_blocks.append({"type": "divider"}) # Divider will be added by build_rich_ticket_blocks

            for ticket_info_dict in top_tickets:
                current_metadata = ticket_info_dict.get("metadata", {})
                # Ensure all necessary fields for build_rich_ticket_blocks are present
                ticket_data_for_blocks = {
                    'ticket_key': current_metadata.get('ticket_id', 'Unknown ID'),
                    'summary': current_metadata.get('summary', current_metadata.get('page_content', 'No summary')[:100]), # Fallback for summary
                    'url': current_metadata.get('url'),
                    'status': current_metadata.get('status', 'N/A'),
                    'priority': current_metadata.get('priority', 'N/A'),
                    'assignee': current_metadata.get('assignee', 'Unassigned'),
                    'issue_type': current_metadata.get('issue_type', 'N/A')
                }
                rich_ticket_blocks = build_rich_ticket_blocks(ticket_data_for_blocks) # No action elements needed here
                response_blocks.extend(rich_ticket_blocks)
        else:
            response_blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"I searched based on the conversation summary, but couldn't find any closely matching JIRA tickets."}
            })
            if summary_to_search:
                 response_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"_Summary I used for search:_\n>>> {summary_to_search}"}})
        
        response_blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "You can still choose to create a new ticket if needed from the mention options."}
        })

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=response_blocks,
            text="Here are the results of the similarity search."
        )
        logger.info(f"Posted similar tickets results for mention flow in thread {thread_ts}")

        # Clean up the specific mention context state if it was successfully used
        if actual_mention_context_key and actual_mention_context_key in conversation_states:
            del conversation_states[actual_mention_context_key]
            logger.info(f"Thread {thread_ts}: Cleared mention context state '{actual_mention_context_key}' after finding similar issues.")

    except Exception as e:
        logger.error(f"Error during mention_flow_find_issues: {e}", exc_info=True)
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, user=user_id, text="Sorry, I encountered an error while searching for similar issues.")


# --- View Handlers ---
@app.view("create_ticket_modal_submission") # Changed from "create_ticket_modal" to match the modal's callback_id
def handle_modal_submission(ack, body, client, view, logger):
    private_metadata_str = view.get("private_metadata")
    logger.info(f"Modal submitted with view_id 'create_ticket_modal_submission'. Private metadata: {private_metadata_str}")

    user_id = body["user"]["id"]
    state_data = conversation_states.get(private_metadata_str)

    if not state_data:
        ack_text = "Error: Couldn't find context for this submission. Please try starting over."
        logger.error(f"No state found for private_metadata_key: {private_metadata_str} in modal submission.")
        ack(response_action="errors", errors={"summary_block": ack_text}) # Error on a specific field (summary_block as an example)
        return

    submission_channel_id = state_data.get("channel_id")
    submission_thread_ts = state_data.get("thread_ts")
    
    submitted_values = view["state"]["values"]
    jira_title = submitted_values["summary_block"]["summary_input"]["value"]
    jira_description = submitted_values["description_block"]["description_input"]["value"]
    selected_issue_type = submitted_values.get("issue_type_block", {}).get("issue_type_select", {}).get("selected_option", {}).get("value")
    selected_priority = submitted_values.get("priority_block", {}).get("priority_select", {}).get("selected_option", {}).get("value")
    selected_assignee_id = submitted_values.get("assignee_block", {}).get("assignee_select", {}).get("selected_user")
    selected_labels_data = submitted_values.get("label_block", {}).get("label_select", {}).get("selected_options", [])
    selected_labels = [opt["value"] for opt in selected_labels_data] if selected_labels_data else []
    
    assignee_email_to_send = None
    if selected_assignee_id:
        try:
            user_info_response = client.users_info(user=selected_assignee_id)
            if user_info_response and user_info_response.get("ok"):
                assignee_email_to_send = user_info_response.get("user", {}).get("profile", {}).get("email")
                logger.info(f"Fetched email '{assignee_email_to_send}' for Slack user ID '{selected_assignee_id}'")
            else:
                logger.warning(f"Could not fetch profile or email for Slack user ID '{selected_assignee_id}'. API response: {user_info_response.get('error') if user_info_response else 'empty response'}")
        except SlackApiError as e_user:
            logger.error(f"Slack API error fetching user info for {selected_assignee_id}: {e_user.response['error']}")
        except Exception as e_user_generic:
            logger.error(f"Generic error fetching user info for {selected_assignee_id}: {e_user_generic}")

    team_option = submitted_values.get("team_block", {}).get("team_select", {}).get("selected_option")
    selected_team = team_option.get("value") if team_option else None
    brand_option = submitted_values.get("brand_block", {}).get("brand_select", {}).get("selected_option")
    selected_brand = brand_option.get("value") if brand_option else None
    environment_option = submitted_values.get("environment_block", {}).get("environment_select", {}).get("selected_option")
    selected_environment = environment_option.get("value") if environment_option else None
    product_option = submitted_values.get("product_block", {}).get("product_select", {}).get("selected_option")
    selected_product = product_option.get("value") if product_option else None
    selected_task_types_data = submitted_values.get("task_type_block", {}).get("task_type_select", {}).get("selected_options", [])
    selected_task_types = [opt["value"] for opt in selected_task_types_data] if selected_task_types_data else []
    selected_root_causes_data = submitted_values.get("root_cause_block", {}).get("root_cause_select", {}).get("selected_options", [])
    selected_root_causes = [opt["value"] for opt in selected_root_causes_data] if selected_root_causes_data else []

    logger.info(f"Modal submission by {user_id} for state key {private_metadata_str}: Title='{jira_title}', Desc='{jira_description[:50]}...'")
    ack() 

    project_key_from_env = os.environ.get("TICKET_CREATION_PROJECT_ID", "PROJ")
    issue_type_to_create = selected_issue_type if selected_issue_type else "Task"

    ticket_payload_data = {
        "summary": jira_title,
        "description": jira_description,
        "project_key": project_key_from_env, 
        "issue_type": issue_type_to_create,
        "priority": selected_priority,
        "assignee_slack_id": selected_assignee_id,
        "assignee_email": assignee_email_to_send,
        "labels": selected_labels,
        "team": selected_team,
        "brand": selected_brand,
        "environment": selected_environment,
        "product": selected_product,
        "task_types": selected_task_types,
        "root_causes": selected_root_causes
    }
    
    final_confirmation_blocks = []
    fallback_text = ""

    try:
        created_ticket_info = create_jira_ticket(ticket_payload_data)
        logger.info(f"Jira service call returned: {json.dumps(created_ticket_info, indent=2) if created_ticket_info else 'None'}")

        if created_ticket_info and created_ticket_info.get("key"):
            ticket_data_for_blocks = {
                'ticket_key': created_ticket_info["key"],
                'url': created_ticket_info["url"],
                'summary': created_ticket_info.get("title", jira_title),
                'status': created_ticket_info.get("status_name", "N/A"),
                'issue_type': created_ticket_info.get("issue_type_name", issue_type_to_create),
                'assignee': created_ticket_info.get("assignee_name", "Unassigned"),
                'priority': created_ticket_info.get("priority_name", selected_priority if selected_priority else "N/A")
            }
            logger.info(f"Successfully created Jira ticket {ticket_data_for_blocks['ticket_key']} with details: Status='{ticket_data_for_blocks['status']}', Type='{ticket_data_for_blocks['issue_type']}', Assignee='{ticket_data_for_blocks['assignee']}', Priority='{ticket_data_for_blocks['priority']}'")

            fallback_text = f"Ticket {ticket_data_for_blocks['ticket_key']} created: {ticket_data_for_blocks['summary']}"
            
            # Add the initial user message
            final_confirmation_blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<@{user_id}> created a {ticket_data_for_blocks['issue_type']} using Jira Bot"
                }
            })
            
            # Add the rich ticket display (without the divider, as it's the end of this specific display)
            rich_blocks = build_rich_ticket_blocks(ticket_data_for_blocks) # No actions, no divider needed from helper
            if rich_blocks and rich_blocks[-1].get("type") == "divider": # Remove default divider if present
                rich_blocks.pop()
            final_confirmation_blocks.extend(rich_blocks)

        else:
            logger.error(f"Failed to create Jira ticket or parse response. create_jira_ticket response: {created_ticket_info}")
            fallback_text = "⚠️ I tried to create the Jira ticket, but something went wrong. I didn't get all the ticket details back."
            final_confirmation_blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": fallback_text}}]

    except Exception as e:
        logger.error(f"Error creating Jira ticket from modal or building confirmation: {e}", exc_info=True)
        fallback_text = f"❌ Sorry, there was an error creating the Jira ticket: {str(e)}"
        final_confirmation_blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": fallback_text}}]

    if submission_channel_id:
        try:
            logger.info(f"Attempting to post to channel {submission_channel_id}, thread {submission_thread_ts}")
            logger.info(f"Fallback text to be sent: {fallback_text}")
            logger.info(f"Blocks to be sent: {json.dumps(final_confirmation_blocks, indent=2) if final_confirmation_blocks else 'None'}")
            client.chat_postMessage(
                channel=submission_channel_id,
                thread_ts=submission_thread_ts,
                blocks=final_confirmation_blocks,
                text=fallback_text
            )
        except Exception as e_post:
            logger.error(f"Failed to post ticket creation confirmation: {e_post}")
    else:
        logger.error("submission_channel_id missing in state_data, cannot post confirmation.")

    if private_metadata_str in conversation_states:
        del conversation_states[private_metadata_str]
        logger.info(f"Cleared state for modal key {private_metadata_str}")

# Helper function to build a simple loading modal
def build_loading_modal_view(message="Processing your request..."):
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Jira Bot is Working..."},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            }
        ],
    }

# --- Message Shortcut Handler ---
@app.shortcut("create_ticket_from_thread_message_action")
def handle_create_ticket_from_thread(ack, shortcut, client, logger, context):
    ack()  # Acknowledge immediately

    trigger_id = shortcut["trigger_id"]
    user_id_invoked = shortcut["user"]["id"]
    channel_id = shortcut["channel"]["id"]
    message_data = shortcut["message"]
    original_message_ts = message_data["ts"]
    thread_parent_ts = message_data.get("thread_ts", original_message_ts)
    
    # Initial view_id for the loading modal
    view_id = None

    try:
        logger.info(f"'Create Ticket from Thread' shortcut: User {user_id_invoked} in channel {channel_id}, thread {thread_parent_ts}.")

        # 1. Open a loading modal immediately
        loading_view_response = client.views_open(
            trigger_id=trigger_id,
            view=build_loading_modal_view("🤖 Our AI is analyzing the thread and generating ticket details for you. This may take a few moments... ⏳")
        )
        view_id = loading_view_response["view"]["id"]
        logger.info(f"Opened loading modal with view_id: {view_id}")

        # 2. Fetch thread messages
        logger.info(f"Fetching replies for thread: {thread_parent_ts} in channel {channel_id}")
        all_thread_messages = []
        cursor = None
        while True:
            result = client.conversations_replies(
                channel=channel_id,
                ts=thread_parent_ts,
                limit=200,
                cursor=cursor
            )
            all_thread_messages.extend(result.get('messages', []))
            if not result.get('has_more'):
                break
            cursor = result.get('response_metadata', {}).get('next_cursor')
        
        logger.info(f"Fetched {len(all_thread_messages)} messages from thread {thread_parent_ts}.")

        if not all_thread_messages:
            logger.warning("No messages found in the thread.")
            error_view = build_loading_modal_view("Could not find any messages in this thread to process.")
            client.views_update(view_id=view_id, view=error_view)
            return

        formatted_conversation = format_messages_for_summary(all_thread_messages, client)
        if not formatted_conversation:
            logger.warning("Formatted conversation is empty.")
            error_view = build_loading_modal_view("Could not format the conversation for summary.")
            client.views_update(view_id=view_id, view=error_view)
            return

        # 3. Perform the single AI call to generate ticket components
        logger.info(f"Generating ticket components from formatted conversation (first 200 chars): {formatted_conversation[:200]}...")
        ticket_components = generate_ticket_components_from_thread(formatted_conversation)
        
        ai_title = ticket_components.get("suggested_title")
        ai_description = ticket_components.get("refined_description")
        # thread_summary = ticket_components.get("thread_summary") # Available if needed

        if not ai_title or ai_title.startswith("Error:") or not ai_description or ai_description.startswith("Error:"):
            error_message = "Sorry, I couldn't generate all ticket details from the thread."
            detailed_error = f"AI generation failed. Title: '{ai_title}', Description: '{ai_description}'"
            logger.error(detailed_error)
            final_error_view = build_loading_modal_view(f"{error_message}. Please try again. ({detailed_error[:100]})")
            client.views_update(view_id=view_id, view=final_error_view)
            return

        logger.info(f"AI Suggested Title: {ai_title}")
        logger.info(f"AI Refined Description: {ai_description[:200]}...")
        # if thread_summary and not thread_summary.startswith("Error:"):
        #      logger.info(f"Thread Summary (for context/debugging): {thread_summary[:200]}...")

        # 4. Build and Update Modal with the actual form
        # This dictionary itself contains the data we need to retrieve later.
        # The key to store it under will be its JSON string representation.
        context_to_store = {
            "channel_id": channel_id,
            "thread_ts": original_message_ts, 
            "user_id": user_id_invoked,
            "is_message_action": True 
            # Add any other data that handle_modal_submission might need from this specific flow
        }
        private_metadata_key_str = json.dumps(context_to_store)

        # Store the context in conversation_states using the string key
        conversation_states[private_metadata_key_str] = context_to_store
        logger.info(f"Stored context in conversation_states with key: {private_metadata_key_str}")

        final_modal_view = build_create_ticket_modal(
            initial_summary=ai_title, 
            initial_description=ai_description,
            private_metadata=private_metadata_key_str # Pass the string key to the modal
        )
        
        client.views_update(view_id=view_id, view=final_modal_view)
        logger.info(f"Updated modal {view_id} with Jira creation form for user {user_id_invoked}.")

    except SlackApiError as e:
        logger.error(f"Slack API error in handle_create_ticket_from_thread: {e.response['error']}", exc_info=True)
        error_text = f"A Slack API error occurred: {e.response['error']}. Please try again."
        if view_id: # If loading modal was opened, update it with error
            try:
                client.views_update(view_id=view_id, view=build_loading_modal_view(error_text))
            except Exception as e_update:
                 logger.error(f"Failed to update modal with Slack API error: {e_update}")
        else: # If loading modal failed to open, try ephemeral message
             try:
                client.chat_postEphemeral(channel=channel_id, user=user_id_invoked, thread_ts=original_message_ts, text=error_text)
             except Exception as e_ephemeral:
                logger.error(f"Failed to send ephemeral error for Slack API error: {e_ephemeral}")

    except Exception as e:
        logger.error(f"Unexpected error in handle_create_ticket_from_thread: {e}", exc_info=True)
        error_text = "An unexpected error occurred while processing your request."
        if view_id: # If loading modal was opened, update it
            try:
                client.views_update(view_id=view_id, view=build_loading_modal_view(error_text))
            except Exception as e_update:
                logger.error(f"Failed to update modal with general error: {e_update}")
        else: # Fallback if view_id not set (e.g., error before views.open)
            try:
                if channel_id and user_id_invoked: # Check if we have these to post an ephemeral
                    client.chat_postEphemeral(channel=channel_id, user=user_id_invoked, thread_ts=original_message_ts, text=error_text)
            except Exception as e_ephemeral:
                logger.error(f"Failed to send ephemeral error message: {e_ephemeral}")


# --- Start the App ---
if __name__ == "__main__":
    try:
        # Scrape Jira tickets from the specified project
        # project_key_to_scrape = os.environ.get("JIRA_PROJECT_KEY_TO_SCRAPE")
        # if project_key_to_scrape:
        #     logger.info(f"Starting Jira scrape for project: {project_key_to_scrape} for up to 200 tickets...")
        #     # Parameters: project_key, total_tickets_to_scrape, api_batch_size
        #     scraped_count, total_available = scrape_and_store_tickets(
        #         project_key=project_key_to_scrape, 
        #         total_tickets_to_scrape=200, # Changed from 2000 to 200
        #         api_batch_size=100
        #     )
        #     logger.info(f"Jira scraping complete. Scraped/Updated {scraped_count} out of {total_available} available tickets for project {project_key_to_scrape}.")

        #     if scraped_count > 0:
        #         logger.info("Proceeding to Pinecone ingestion pipeline...")
        #         run_ingestion_pipeline() # Call the ingestion pipeline
        #     else:
        #         logger.info("No tickets were scraped. Skipping Pinecone ingestion pipeline.")

        # else:
        #     logger.warning("JIRA_PROJECT_KEY_TO_SCRAPE environment variable not set. Skipping Jira scraping and Pinecone ingestion on startup.")

        logger.info("Starting Socket Mode Handler...")
        # Use SocketModeHandler for development/testing without exposing a public URL
        # Requires SLACK_APP_TOKEN (App-Level Token with connections:write scope)
        handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
        handler.start()
    except KeyError as e:
        logger.error(f"Missing environment variable: {e}. Ensure SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, and SLACK_APP_TOKEN are set in .env")
    except Exception as e:
        logger.error(f"Error starting app: {e}") 