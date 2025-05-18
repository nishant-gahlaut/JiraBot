# app.py
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
import logging
from slack_sdk import WebClient
import json
from slack_sdk.errors import SlackApiError
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import time  # Added time module import

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
# from handlers.modals.interaction_handlers import handle_create_ticket_submission # This was already commented
from handlers.modals.interaction_handlers import handle_modal_submission as imported_handle_modal_submission # Ensuring this is the one we use AND aliased

# Import ticket creation flow handlers from their new location
from handlers.action_sequences.creation_handlers import (
    handle_create_ticket_action,
    handle_continue_after_ai,
    handle_modify_after_ai,
    handle_generate_ai_ticket_details_after_duplicates,
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

# Import mention handler (updated import)
from handlers.mention_handler import handle_app_mention_event

# Import mention flow handlers
from handlers.modals.interaction_handlers import build_create_ticket_modal
from services.jira_service import create_jira_ticket, get_jira_ticket, update_jira_ticket
from handlers.flows.ticket_creation_orchestrator import present_duplicate_check_and_options
# Import AI title/description generators
from services.genai_service import generate_suggested_title, generate_refined_description, generate_ticket_components_from_thread, generate_ticket_components_from_description, summarize_thread
# Import UI helpers
from utils.slack_ui_helpers import get_issue_type_emoji, get_priority_emoji, build_rich_ticket_blocks

# Import the duplicate detection service
from services.duplicate_detection_service import find_and_summarize_duplicates,find_and_summarize_duplicates_mention_flow
from handlers.modals.modal_builders import build_similar_tickets_modal, build_loading_modal_view, build_description_capture_modal

# Import the unified query processor
from handlers.unified_query_handler import process_user_query

# Import common handler utilities including the newly added format_messages_for_summary
from handlers.common_handler_utils import format_messages_for_summary

# Load environment variables from .env file
load_dotenv()

# Initialize a ThreadPoolExecutor for background tasks
app_executor = ThreadPoolExecutor(max_workers=10)

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
                "text": "You can describe an issue, and I'll help you create a Jira ticket or check for similar ones."
            }
        }
    ]

    try:
        # Post the initial message
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            attachments=[
                {
                    "color": "#439FE0",
                    "blocks": initial_blocks
                }
            ],
            text="👋 Hello.I'm your conversational AI Jira Assistant 🤖: " # MODIFIED: Generic fallback text
        )
        logger.info(f"Posted initial conversational message to thread {thread_ts}")

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
@app.action("generate_ai_ticket_details_after_duplicates_action")
def trigger_generate_ai_ticket_details_after_duplicates(ack, body, client, logger):
    handle_generate_ai_ticket_details_after_duplicates(ack, body, client, logger)

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


# Combined message event handler
@app.event("message")
def route_all_message_events(event, client, context, logger):
    """
    Primary router for all 'message' events.
    Handles direct messages by routing to process_user_query.
    Handles other channel messages by routing to the generic handle_message.
    """
    if event.get("channel_type") == "im":
        logger.info(f"Received direct message event for unified processing: {json.dumps(event, indent=2)}")

        bot_user_id = context.get("bot_user_id")
        user_id = event.get("user")
        channel_id = event.get("channel") 
        message_ts = event.get("ts")
        user_message_text = event.get("text", "")
        thread_ts_for_context = event.get("thread_ts")

        if user_id == bot_user_id:
            logger.info("Ignoring message from self in DM.")
            return

        if not all([bot_user_id, user_id, channel_id, message_ts]):
            logger.error("Missing critical information from DM event. Cannot proceed with unified_query_handler.")
            return

        # Call the unified query processor for DMs
        process_user_query(
            client=client,
            bot_user_id=bot_user_id,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts_for_context,
            message_ts=message_ts,
            user_message_text=user_message_text,
            is_direct_message=True,
            assistant_id=context.get("assistant_id")
        )
    else:
        # For non-DM messages, route to the original generic message handler
        logger.info(f"Received non-DM message event, routing to generic handle_message: {json.dumps(event, indent=2)}")
        handle_message(event, client, context, logger)


# --- Event Handlers (app_mention specifically) ---
@app.event("app_mention")
def app_mention_event_handler(event, client, context, logger):
    logger.info(f"Received app_mention event: {event}")
    if 'bot_user_id' not in context:
        logger.warning("bot_user_id not in context for app_mention event. Fetching auth.test...")
        try:
            auth_test_res = client.auth_test()
            context['bot_user_id'] = auth_test_res['user_id']
            logger.info(f"Fetched bot_user_id: {context['bot_user_id']}")
        except Exception as e:
            logger.error(f"Failed to fetch bot_user_id via auth.test: {e}")
    
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
    pre_existing_title = None # Initialize
    pre_existing_description = None # Initialize

    if mention_context and "summary" in mention_context:
        bot_summary_as_description = mention_context["summary"]
        pre_existing_title = mention_context.get("ai_suggested_title") # Retrieve pre-existing title
        pre_existing_description = mention_context.get("ai_refined_description") # Retrieve pre-existing description
        original_user_id_for_context = mention_context.get("user_id", user_id_who_clicked) 
        # Prefer assistant_id from the stored context if available, as it's more likely tied to the original event
        assistant_id_for_orchestrator = mention_context.get("assistant_id", assistant_id_from_body)
        logger.info(f"Retrieved bot summary for duplicate check: {bot_summary_as_description[:100]}... Original mention by {original_user_id_for_context}. Assistant ID for orchestrator: {assistant_id_for_orchestrator}. Pre-existing title: '{pre_existing_title}', Pre-existing desc (preview): '{pre_existing_description[:50] if pre_existing_description else 'N/A'}'")
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
        assistant_id=assistant_id_for_orchestrator,
        pre_existing_title=pre_existing_title,       # Pass pre_existing_title
        pre_existing_description=pre_existing_description # Pass pre_existing_description
    )
    
    # Clean up the specific mention context state if it was successfully used
    # Note: The orchestrator itself does not manage conversation_states.
    # This state was specific to passing the summary from mention_handler to this action.
    if actual_mention_context_key and actual_mention_context_key in conversation_states:
        del conversation_states[actual_mention_context_key]
        logger.info(f"Thread {thread_ts}: Cleared mention context state '{actual_mention_context_key}' after calling orchestrator.")


# Helper function to get sort key for tickets
def get_ticket_sort_key(ticket_result):
    metadata = ticket_result.get("metadata", {})
    
    # 1. Primary Sort: LLM Similarity Score (descending)
    # Default to a very low score if not present, so these go to the bottom if mixed with scored items.
    llm_score = metadata.get('llm_similarity_score', -1.0) # Use -1.0 to ensure unscored are last
    
    # For descending sort on score, we typically use score directly with reverse=True in sorted(),
    # or negate the score if we want to use it in a tuple for ascending sort.
    # Since we are returning a tuple for multi-level sort, we'll negate it.
    primary_sort_key = -float(llm_score) # Negate for ascending sort based on this tuple element

    # Secondary Sort Criteria (existing logic)
    status = metadata.get('status', '')
    priority_val = metadata.get('priority', '') # e.g., "Highest-P0"
    environment_val = metadata.get('environment', '') # e.g., "Prod"
    updated_at_str = metadata.get('updated_at') # ISO format string

    # 2. Status: 'Closed' tickets first (after LLM score)
    status_sort_key = 0 if status and status.lower() == 'closed' else 1

    # 3. Priority Order (maps to "Highest-P0":0, "High-P1":1, etc.)
    priority_order_map = {"Highest-P0": 0, "High-P1": 1, "Medium-P2": 2, "Low-P3": 3}
    priority_sort_key = priority_order_map.get(priority_val, 4) # Default to last if not found

    # 4. Environment Order
    environment_order_map = {"Prod": 0, "Go-Live": 1, "UAT": 2, "Staging": 3, "Nightly": 4, "Demo": 5}
    environment_sort_key = environment_order_map.get(environment_val, 6) # Default to last

    # 5. Recency (updated_at) - newest first
    recency_sort_key = float('inf') # Default for missing/invalid dates (goes last)
    if updated_at_str:
        try:
            # Ensure timezone-aware datetime objects for proper comparison
            # Replace 'Z' with '+00:00' if present, for fromisoformat
            if updated_at_str.endswith('Z'):
                dt_obj = datetime.fromisoformat(updated_at_str[:-1] + '+00:00')
            else:
                dt_obj = datetime.fromisoformat(updated_at_str)
            
            # If dt_obj is naive, assume UTC (or make this configurable if needed)
            if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None:
                dt_obj = dt_obj.replace(tzinfo=timezone.utc)
            
            recency_sort_key = -dt_obj.timestamp() # Negative timestamp for newest first
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not parse updated_at_str '{updated_at_str}' for sorting: {e}")
            pass # Keep default recency_sort_key if parsing fails

    return (primary_sort_key, status_sort_key, priority_sort_key, environment_sort_key, recency_sort_key)


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
            text=f"Thanks. Searching for JIRA tickets similar to the conversation summary..."
        )

        duplicate_results = find_and_summarize_duplicates_mention_flow(user_query=summary_to_search)
        top_tickets_raw = duplicate_results.get("tickets", [])
        overall_summary = duplicate_results.get("summary", "Could not generate an overall summary for similar tickets.")

        # Sort the tickets based on the defined criteria
        sorted_tickets = sorted(top_tickets_raw, key=get_ticket_sort_key)
        
        response_blocks = []
        if sorted_tickets:
            response_blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Here are some existing JIRA tickets that might be related to the conversation (sorted by relevance and your criteria):"}
            })
            if overall_summary and overall_summary != "Could not generate an overall summary for similar tickets.":
                 response_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"_{overall_summary}_"}})
            # response_blocks.append({"type": "divider"}) # Divider will be added by build_rich_ticket_blocks

            for ticket_result in sorted_tickets: # Iterate over sorted_tickets
                metadata = ticket_result.get("metadata", {})
                # TEMP LOG to check owned_by_team value from metadata
                logger.info(f"DEBUG METADATA ({metadata.get('ticket_id')}): owned_by_team raw value = '{metadata.get('owned_by_team')}', type = {type(metadata.get('owned_by_team'))}")
                
                # Explicitly prioritize metadata.retrieved_problem_statement
                problem_statement_for_display = metadata.get("retrieved_problem_statement")

                # If that's empty, try page_content (which should ideally be the same)
                if not problem_statement_for_display:
                    problem_statement_for_display = ticket_result.get("page_content")
                
                # If both are empty, fall back to the original ticket summary
                if not problem_statement_for_display:
                    problem_statement_for_display = metadata.get("summary", "_(Problem details not found)_")

                # For solution, keep existing logic
                solution_summary_for_display = metadata.get("retrieved_solution_summary", "_(Resolution details not found)_")
                
                transformed_ticket = {
                    'key': metadata.get('ticket_id', 'N/A'),
                    'url': metadata.get('url'), # UI helper will construct if this is missing/nan
                    'summary': metadata.get('summary', '_(Original summary missing)_'), # Original summary for title/link text
                    'status': metadata.get('status', '_Status N/A_'),
                    'priority': metadata.get('priority', ''),
                    'assignee': metadata.get('assignee', ''),
                    'owned_by_team': metadata.get('owned_by_team', 'N/A'),
                    'retrieved_problem_statement': problem_statement_for_display,
                    'retrieved_solution_summary': solution_summary_for_display
                }
                rich_ticket_blocks = build_rich_ticket_blocks(transformed_ticket)
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


@app.action("mention_confirm_open_create_form")
def handle_mention_confirm_open_create_form(ack, body, client, logger):
    ack()
    trigger_id = body["trigger_id"]
    action_details_str = body["actions"][0]["value"]
    user_id_who_clicked = body["user"]["id"]

    try:
        action_details = json.loads(action_details_str)
        title = action_details.get("title")
        description = action_details.get("description")
        original_channel_id = action_details.get("channel_id")
        original_thread_ts = action_details.get("thread_ts") # Where the bot should post confirmation after modal
        # user_id_of_mentioner = action_details.get("user_id") # User who originally mentioned the bot
        summary_for_confirmation = action_details.get("summary_for_confirmation")

        logger.info(f"'mention_confirm_open_create_form' action by {user_id_who_clicked}. AI Title: '{title}', AI Desc (preview): '{description[:50]}...'")

        if not title or not description:
            logger.error("Missing title or description in action_details for mention_confirm_open_create_form.")
            # Post an ephemeral message to the user who clicked
            client.chat_postEphemeral(
                channel=original_channel_id, # Post in the original channel
                user=user_id_who_clicked,
                thread_ts=original_thread_ts, # In the original thread context
                text="Sorry, I couldn't retrieve the generated title or description to pre-fill the form. Please try the mention again."
            )
            return

        # Prepare private_metadata for the modal
        # This will be used by handle_modal_submission to know where to post the confirmation
        private_metadata_payload = {
            "channel_id": original_channel_id,
            "thread_ts": original_thread_ts,
            "user_id": user_id_who_clicked, # User who will be associated with ticket creation if not overridden in modal
            "flow_origin": "mention_confirmed_create", # To identify the source
            "ai_summary_for_context": summary_for_confirmation # If needed later
        }
        private_metadata_str = json.dumps(private_metadata_payload)
        
        # Store in conversation_states, as this seems to be the pattern for modal context
        conversation_states[private_metadata_str] = private_metadata_payload
        logger.info(f"Stored modal context for 'mention_confirm_open_create_form' in conversation_states with key: {private_metadata_str}")

        modal_view = build_create_ticket_modal(
            initial_summary=title,
            initial_description=description,
            private_metadata=private_metadata_str
        )

        client.views_open(trigger_id=trigger_id, view=modal_view)
        logger.info(f"Opened Jira creation modal for user {user_id_who_clicked} (from mention flow) with pre-filled AI content.")

    except json.JSONDecodeError as e_json:
        logger.error(f"Failed to parse action_details JSON for 'mention_confirm_open_create_form': {e_json}. Value: {action_details_str}")
        # Notify user of the error if possible (channel_id might not be available if JSON parsing fails catastrophically)
    except SlackApiError as e_slack:
        logger.error(f"Slack API error in 'mention_confirm_open_create_form': {e_slack.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error in 'mention_confirm_open_create_form': {e}", exc_info=True)


# --- View Handlers ---
@app.view("create_ticket_modal_submission") # Changed from "create_ticket_modal" to match the modal's callback_id
def handle_modal_submission(ack, body, client, view, logger): # This is the app's view handler
    # This now calls the imported and aliased handler
    imported_handle_modal_submission(ack, body, client, view, logger)

# --- NEW View Submission Handler for Description Capture Modal ---
@app.view("description_capture_modal_submission")
def handle_description_capture_submission(ack, body, client, view, logger):
    logger.info("Received description_capture_modal_submission.")
    
    view_id = view["id"]
    user_id = body["user"]["id"]

    try:
        user_provided_description = view["state"]["values"]["issue_description_block"]["issue_description_input"]["value"]
        initial_private_metadata_str = view.get("private_metadata", "{}")
        initial_metadata = json.loads(initial_private_metadata_str)

        channel_id = initial_metadata.get("channel_id")
        thread_ts = initial_metadata.get("thread_ts")

        if not user_provided_description or user_provided_description.isspace():
            logger.warning("User submitted empty description in description_capture_modal.")
            error_view_payload = build_description_capture_modal(private_metadata=initial_private_metadata_str)
            error_view_payload["blocks"].append({"type": "section", "text": {"type": "mrkdwn", "text": ":warning: Description cannot be empty."}})
            ack({"response_action": "update", "view": error_view_payload}) # Ack with update for error
            return

        logger.info(f"User {user_id} submitted description: '{user_provided_description[:100]}...'")

        # --- Update to Loading State via ack with response_action --- 
        loading_view_payload = build_loading_modal_view("🤖 Generating AI suggestions for your ticket... please wait.")
        ack({
            "response_action": "update",
            "view": loading_view_payload
        })
        logger.info(f"Ack'd and updated modal {view_id} to loading state.")

        # --- Call GenAI Service (ack has already happened) ---
        ai_components = generate_ticket_components_from_description(user_provided_description)
        
        ai_suggested_title = ai_components.get("suggested_title", "")
        ai_refined_description = ai_components.get("refined_description", user_provided_description)
        ai_issue_summary = ai_components.get("issue_summary", "")

        if not ai_issue_summary or ai_issue_summary.startswith("Error:") or ai_issue_summary.startswith("Could not"):
            logger.warning(f"AI failed to generate a usable issue_summary. Fallback used. Summary: {ai_issue_summary}")
            ai_issue_summary = ai_refined_description if (not ai_issue_summary or ai_issue_summary.startswith("Error:")) and ai_refined_description else user_provided_description

        final_private_metadata = initial_metadata.copy()
        final_private_metadata["thread_summary"] = ai_issue_summary
        final_private_metadata_str = json.dumps(final_private_metadata)

        final_jira_modal_view = build_create_ticket_modal(
            initial_summary=ai_suggested_title,
            initial_description=ai_refined_description,
            private_metadata=final_private_metadata_str
        )
        
        # --- Second update uses client.views_update --- 
        client.views_update(view_id=view_id, view=final_jira_modal_view)
        logger.info(f"Updated modal {view_id} to full Jira creation form for user {user_id} with AI suggestions.")

    except SlackApiError as e:
        logger.error(f"Slack API error in handle_description_capture_submission: {e.response['error']}", exc_info=True)
        # Don't try to ack again here. If the first ack with update failed, or if error is after, 
        # we might not be able to update the view if the view_id is truly gone.
        # Just log the error. The user might see a generic error on Slack or the modal might be stuck.
        # If the error was 'not_found' on the ack(update), it's tricky.
    except Exception as e:
        logger.error(f"Unexpected error in handle_description_capture_submission: {e}", exc_info=True)
        # Similar to above, updating the view here might fail if view_id is not_found.
        # A simple log is the safest if we can't guarantee view_id validity after an error.


# --- Shortcut Handler for "Check Similar Issues" ---
@app.shortcut("check_similar_issues_shortcut")
def handle_check_similar_issues_shortcut(ack, shortcut, client, logger):
    ack()  # Acknowledge immediately

    trigger_id = shortcut["trigger_id"]
    user_id = shortcut["user"]["id"]
    channel_id = shortcut["channel"]["id"]
    message_data = shortcut["message"]
    message_context_ts = message_data["ts"] 
    thread_parent_ts = message_data.get("thread_ts", message_context_ts)
    
    logger.info(f"'Check Similar Issues' shortcut: User {user_id} in channel {channel_id}, on message {message_context_ts}, for thread {thread_parent_ts}.")
    loading_view_id = None

    try:
        loading_view_payload = build_loading_modal_view("⏳ Analyzing thread and AI is searching for similar issues...")
        loading_modal_response = client.views_open(
            trigger_id=trigger_id,
            view=loading_view_payload
        )
        loading_view_id = loading_modal_response["view"]["id"]
        logger.info(f"Opened loading modal {loading_view_id} for 'Check Similar Issues' for user {user_id}.")

        # Phase 2: Submit to Executor (UNCOMMENTED)
        app_executor.submit(
            _task_check_similar_from_thread_and_display, # Target function for background task
            client=client,
            logger=logger,
            loading_view_id=loading_view_id,
            channel_id=channel_id, # Pass for fetching replies
            thread_parent_ts=thread_parent_ts, # Pass for fetching replies
            user_id=user_id # For logging or context if needed by the task
        )
        logger.info(f"Submitted background task for {loading_view_id} to check similar issues from thread.")

    except SlackApiError as e:
        logger.error(f"Slack API error in handle_check_similar_issues_shortcut: {e.response['error']}", exc_info=True)
        if loading_view_id:
            try:
                error_view = build_loading_modal_view(f"A Slack API error occurred: {e.response['error']}. Please try again.")
                client.views_update(view_id=loading_view_id, view=error_view)
            except Exception as e_update:
                logger.error(f"Failed to update loading modal with Slack API error: {e_update}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_check_similar_issues_shortcut: {e}", exc_info=True)
        if loading_view_id:
            try:
                error_view = build_loading_modal_view("An unexpected error occurred. Please try again.")
                client.views_update(view_id=loading_view_id, view=error_view)
            except Exception as e_update:
                logger.error(f"Failed to update loading modal with general error: {e_update}")

# --- Shortcut Handler for "Check Similar Issues" ---
@app.action("check_similar_issues_button_action")
def handle_check_similar_issues_button_action(ack, body, client, logger):
    # This is a button action, not a shortcut.
    # It's triggered by a button in a modal, not a shortcut.
    # It's triggered by a button in a modal, not a shortcut.  
    ack()  # Acknowledge immediately
    trigger_id = body["trigger_id"]
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    message_context_ts = body["message"]["ts"] 
    thread_parent_ts = body["message"].get("thread_ts", message_context_ts)
    
    logger.info(f"'Check Similar Issues' shortcut: User {user_id} in channel {channel_id}, on message {message_context_ts}, for thread {thread_parent_ts}.")
    loading_view_id = None

    try:
        loading_view_payload = build_loading_modal_view("⏳ Analyzing thread and AI is searching for similar issues...")
        loading_modal_response = client.views_open(
            trigger_id=trigger_id,
            view=loading_view_payload
        )
        loading_view_id = loading_modal_response["view"]["id"]
        logger.info(f"Opened loading modal {loading_view_id} for 'Check Similar Issues' for user {user_id}.")

        # Phase 2: Submit to Executor (UNCOMMENTED)
        app_executor.submit(
            _task_check_similar_from_thread_and_display, # Target function for background task
            client=client,
            logger=logger,
            loading_view_id=loading_view_id,
            channel_id=channel_id, # Pass for fetching replies
            thread_parent_ts=thread_parent_ts, # Pass for fetching replies
            user_id=user_id # For logging or context if needed by the task,
        )
        logger.info(f"Submitted background task for {loading_view_id} to check similar issues from thread.")

    except SlackApiError as e:
        logger.error(f"Slack API error in handle_check_similar_issues_shortcut: {e.response['error']}", exc_info=True)
        if loading_view_id:
            try:
                error_view = build_loading_modal_view(f"A Slack API error occurred: {e.response['error']}. Please try again.")
                client.views_update(view_id=loading_view_id, view=error_view)
            except Exception as e_update:
                logger.error(f"Failed to update loading modal with Slack API error: {e_update}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_check_similar_issues_shortcut: {e}", exc_info=True)
        if loading_view_id:
            try:
                error_view = build_loading_modal_view("An unexpected error occurred. Please try again.")
                client.views_update(view_id=loading_view_id, view=error_view)
            except Exception as e_update:
                logger.error(f"Failed to update loading modal with general error: {e_update}")


# Phase 3: Implement the Background Task Function
def _task_check_similar_from_thread_and_display(client, logger, loading_view_id, channel_id, thread_parent_ts, user_id):
    logger.info(f"Background task started for {loading_view_id}: Checking similar issues from thread {thread_parent_ts} for user {user_id}.")
    final_view_payload = None
    try:
        # 1. Fetch Thread Content
        all_thread_messages = []
        cursor = None
        while True:
            result = client.conversations_replies(
                channel=channel_id,
                ts=thread_parent_ts,
                limit=200, # Max limit per call
                cursor=cursor
            )
            all_thread_messages.extend(result.get('messages', []))
            if not result.get('has_more'):
                break
            cursor = result.get('response_metadata', {}).get('next_cursor')
        
        continue_thread_info = {"channel_id": channel_id, "thread_ts": thread_parent_ts}
        current_source = "check_similar_from_thread_flow" # Specific source for this flow

        if not all_thread_messages:
            logger.warning(f"No messages found in thread {thread_parent_ts} for similarity check.")
            final_view_payload = build_similar_tickets_modal(
                similar_tickets_details=[], 
                channel_id=channel_id,
                source=current_source,
                add_continue_creation_button=True,
                continue_creation_thread_info=continue_thread_info
            )
            client.views_update(view_id=loading_view_id, view=final_view_payload)
            return

        # 2. Format Messages
        # Assuming format_messages_for_summary expects client as an argument if it needs to fetch user names
        formatted_conversation = format_messages_for_summary(all_thread_messages, client)
        if not formatted_conversation:
            logger.warning(f"Formatted conversation is empty for thread {thread_parent_ts}.")
            final_view_payload = build_similar_tickets_modal(
                similar_tickets_details=[],
                channel_id=channel_id,
                source=current_source,
                add_continue_creation_button=True,
                continue_creation_thread_info=continue_thread_info
            )
            client.views_update(view_id=loading_view_id, view=final_view_payload)
            return

        # 3. Generate AI Summary of the Thread
        logger.info(f"Generating AI summary for thread {thread_parent_ts} (first 100 chars of formatted: '{formatted_conversation[:100]}...')")
        start_time = time.time()
        thread_ai_summary = summarize_thread(formatted_conversation)
        end_time = time.time()
        logger.info(f"AI summary generation took {end_time - start_time:.2f} seconds for thread {thread_parent_ts}")

        if not thread_ai_summary or thread_ai_summary.startswith("Error:"):
            logger.error(f"Failed to generate AI summary for thread {thread_parent_ts}. AI response: {thread_ai_summary}")
            error_message_for_modal = "Sorry, I couldn't summarize the thread to find similar issues." 
            if thread_ai_summary: # Append AI's error if available
                error_message_for_modal += f" (Details: {thread_ai_summary[:100]})"
            final_view_payload = build_loading_modal_view(error_message_for_modal)
            client.views_update(view_id=loading_view_id, view=final_view_payload)
            return
        
        logger.info(f"AI summary for thread {thread_parent_ts}: '{thread_ai_summary[:100]}...'")

        # 4. Find Similar Tickets
        start_time = time.time()
        duplicate_results = find_and_summarize_duplicates(user_query=thread_ai_summary)
        end_time = time.time()
        logger.info(f"Duplicate detection took {end_time - start_time:.2f} seconds for thread {thread_parent_ts}")
        top_similar_tickets_raw = duplicate_results.get("tickets", [])

        # Sort the tickets based on the defined criteria
        sorted_tickets = sorted(top_similar_tickets_raw, key=get_ticket_sort_key)

        # 5. Prepare and Display Results
        similar_tickets_details_for_modal = []
        for ticket_result in sorted_tickets: # Iterate over sorted_tickets
            metadata = ticket_result.get("metadata", {})
            
            # TEMP LOG to check owned_by_team value from metadata
            logger.info(f"DEBUG METADATA ({metadata.get('ticket_id')}): owned_by_team raw value = '{metadata.get('owned_by_team')}', type = {type(metadata.get('owned_by_team'))}")
            
            # Explicitly prioritize metadata.retrieved_problem_statement
            problem_statement_for_display = metadata.get("retrieved_problem_statement")

            # If that's empty, try page_content (which should ideally be the same)
            if not problem_statement_for_display:
                problem_statement_for_display = ticket_result.get("page_content")
            
            # If both are empty, fall back to the original ticket summary
            if not problem_statement_for_display:
                problem_statement_for_display = metadata.get("summary", "_(Problem details not found)_")

            # For solution, keep existing logic
            solution_summary_for_display = metadata.get("retrieved_solution_summary", "_(Resolution details not found)_")
            
            transformed_ticket = {
                'key': metadata.get('ticket_id', 'N/A'),
                'url': metadata.get('url'), # UI helper will construct if this is missing/nan
                'summary': metadata.get('summary', '_(Original summary missing)_'), # Original summary for title/link text
                'status': metadata.get('status', '_Status N/A_'),
                'priority': metadata.get('priority', ''),
                'assignee': metadata.get('assignee', ''),
                'owned_by_team': metadata.get('owned_by_team', 'N/A'),
                'retrieved_problem_statement': problem_statement_for_display,
                'retrieved_solution_summary': solution_summary_for_display
            }
            similar_tickets_details_for_modal.append(transformed_ticket)
        
        # Store detailed ticket info for later retrieval in submission handler
        if loading_view_id and similar_tickets_details_for_modal:
            conversation_states[f"{loading_view_id}_displayed_tickets"] = similar_tickets_details_for_modal
            logger.info(f"Stored {len(similar_tickets_details_for_modal)} displayed ticket details in conversation_states for {loading_view_id}")

        final_view_payload = build_similar_tickets_modal(
            similar_tickets_details_for_modal,
            channel_id=channel_id, # For modal's own context
            source=current_source,
            original_ticket_key=None, # No original ticket context in this specific flow
            add_continue_creation_button=True,
            continue_creation_thread_info=continue_thread_info,
            loading_view_id=loading_view_id # Pass loading_view_id
        )
        client.views_update(view_id=loading_view_id, view=final_view_payload)
        logger.info(f"Updated modal {loading_view_id} with {len(similar_tickets_details_for_modal)} similar tickets found for thread {thread_parent_ts}.")

    except Exception as e:
        logger.error(f"Error in background task _task_check_similar_from_thread_and_display for {loading_view_id}: {e}", exc_info=True)
        try:
            error_view = build_loading_modal_view("Sorry, an unexpected error occurred while checking for similar issues.")
            client.views_update(view_id=loading_view_id, view=error_view)
        except Exception as e_update:
            logger.error(f"Failed to update modal {loading_view_id} with error from background task: {e_update}")


# --- Existing handler for Create Ticket from Thread ---
@app.shortcut("create_ticket_from_thread_message_action")
def handle_create_ticket_from_thread(ack, shortcut, client, logger, context):
    ack()  # Acknowledge immediately

    trigger_id = shortcut["trigger_id"]
    user_id_invoked = shortcut["user"]["id"]
    channel_id = shortcut["channel"]["id"]
    message_data = shortcut["message"]
    original_message_ts = message_data["ts"]
    thread_parent_ts = message_data.get("thread_ts", original_message_ts)
    
    view_id = None

    try:
        logger.info(f"'Create Ticket from Thread' shortcut: User {user_id_invoked} in channel {channel_id}, thread {thread_parent_ts}.")

        loading_view_response = client.views_open(
            trigger_id=trigger_id,
            view=build_loading_modal_view("🤖 Our AI is analyzing the thread and generating ticket details for you. This may take a few moments... ⏳")
        )
        view_id = loading_view_response["view"]["id"]
        logger.info(f"Opened loading modal with view_id: {view_id}")

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

        logger.info(f"Generating ticket components from formatted conversation (first 200 chars): {formatted_conversation[:200]}...")
        ticket_components = generate_ticket_components_from_thread(formatted_conversation)
        
        ai_title = ticket_components.get("suggested_title")
        ai_description = ticket_components.get("refined_description")
        thread_summary = ticket_components.get("thread_summary") # Get the thread summary
        ai_priority = ticket_components.get("priority") # <-- New
        ai_issue_type = ticket_components.get("issue_type") # <-- New

        if not ai_title or ai_title.startswith("Error:") or not ai_description or ai_description.startswith("Error:"):
            error_message = "Sorry, I couldn't generate all ticket details from the thread."
            # Include new fields in error logging if needed
            detailed_error = f"AI generation failed. Title: '{ai_title}', Description: '{ai_description}', Priority: '{ai_priority}', Issue Type: '{ai_issue_type}'"
            logger.error(detailed_error)
            final_error_view = build_loading_modal_view(f"{error_message}. Please try again. ({detailed_error[:100]})" )
            client.views_update(view_id=view_id, view=final_error_view)
            return

        logger.info(f"AI Suggested Title: {ai_title}")
        logger.info(f"AI Description: {ai_description[:200]}...")
        logger.info(f"AI Predicted Priority: {ai_priority}") # <-- New log
        logger.info(f"AI Predicted Issue Type: {ai_issue_type}") # <-- New log
        if thread_summary and not thread_summary.startswith("Error:"):
             logger.info(f"AI Thread Summary (for context/debugging): {thread_summary[:200]}...")
        else:
             logger.warning(f"AI Thread Summary was not generated or had an error: {thread_summary}")
             thread_summary = "" # Ensure it's an empty string if problematic

        context_to_store = {
            "channel_id": channel_id,
            "thread_ts": original_message_ts, 
            "user_id": user_id_invoked,
            "is_message_action": True, 
            "thread_summary": thread_summary  # --- ADDED thread_summary --- 
        }
        private_metadata_key_str = json.dumps(context_to_store)

        # conversation_states[private_metadata_key_str] = context_to_store # This line seems to store the context in conversation_states using the JSON string AS THE KEY. Ensure this is intended for retrieval in modal submission.
        # Typically, private_metadata in the modal itself carries the context directly.

        final_modal_view = build_create_ticket_modal(
            initial_summary=ai_title, 
            initial_description=ai_description,
            initial_priority=ai_priority, # <-- New
            initial_issue_type=ai_issue_type, # <-- New
            private_metadata=private_metadata_key_str 
        )
        
        client.views_update(view_id=view_id, view=final_modal_view)
        logger.info(f"Updated modal {view_id} with Jira creation form for user {user_id_invoked}.")

    except SlackApiError as e:
        logger.error(f"Slack API error in handle_create_ticket_from_thread: {e.response['error']}", exc_info=True)
        error_text = f"A Slack API error occurred: {e.response['error']}. Please try again."
        if view_id:
            try:
                client.views_update(view_id=view_id, view=build_loading_modal_view(error_text))
            except Exception as e_update:
                 logger.error(f"Failed to update modal with Slack API error: {e_update}")

    except Exception as e:
        logger.error(f"Unexpected error in handle_create_ticket_from_thread: {e}", exc_info=True)
        error_text = "An unexpected error occurred while processing your request."
        if view_id:
            try:
                client.views_update(view_id=view_id, view=build_loading_modal_view(error_text))
            except Exception as e_update:
                logger.error(f"Failed to update modal with general error: {e_update}")
        else:
            try:
                if channel_id and user_id_invoked:
                    client.chat_postEphemeral(channel=channel_id, user=user_id_invoked, thread_ts=original_message_ts, text=error_text)
            except Exception as e_ephemeral:
                logger.error(f"Failed to send ephemeral error message: {e_ephemeral}")



# --- Existing handler for Create Ticket from Thread --- (Now primarily for shortcut)
@app.action("create_ticket_from_thread_from_shortcut_continue_create_ticket")
def create_ticket_from_thread_from_shortcut_continue_create_ticket(ack, body, client, logger, context):
    ack()  # Acknowledge shortcut immediately

    trigger_id = body["trigger_id"]
    user_id_invoked = body["user"]["id"]
    
    # This handler is now only for direct shortcut, so parse channel/message info directly
    target_channel_id = body.get("channel", {}).get("id")
    message_data = body.get("message", {})
    original_message_ts_from_shortcut = message_data.get("ts")
    target_thread_ts = message_data.get("thread_ts", original_message_ts_from_shortcut)
    
    view_id_to_process = None # Will be set after opening the new loading modal

    logger.info(f"'Create Ticket from Thread' shortcut (via create_ticket_from_thread_from_shortcut_continue_create_ticket action): User {user_id_invoked} in channel {target_channel_id}, thread {target_thread_ts}.")

    if not target_channel_id or not target_thread_ts:
        logger.error("Shortcut: Critical error: target_channel_id or target_thread_ts could not be determined.")
        try:
            client.views_open(
                trigger_id=trigger_id,
                view=build_loading_modal_view("Error: Missing crucial information to locate the thread from shortcut. Please try again.")
            )
        except Exception as e_modal_open:
            logger.error(f"Failed to open error modal for missing thread info (shortcut path): {e_modal_open}")
        return
    
    try:
        # Open a NEW loading modal for the shortcut flow
        loading_view_response = client.views_open(
            trigger_id=trigger_id,
            view=build_loading_modal_view("🤖 Our AI is analyzing the thread and generating ticket details for you. This may take a few moments... ⏳")
        )
        view_id_to_process = loading_view_response["view"]["id"]
        logger.info(f"Opened new loading modal with view_id: {view_id_to_process} for shortcut path.")
        
        logger.info(f"Processing thread: {target_channel_id}/{target_thread_ts} for user {user_id_invoked} on new view {view_id_to_process}")

        all_thread_messages = []
        cursor = None
        while True:
            result = client.conversations_replies(
                channel=target_channel_id, # Use determined target_channel_id
                ts=target_thread_ts,       # Use determined target_thread_ts
                limit=200,
                cursor=cursor
            )
            all_thread_messages.extend(result.get('messages', []))
            if not result.get('has_more'):
                break
            cursor = result.get('response_metadata', {}).get('next_cursor')
        
        logger.info(f"Fetched {len(all_thread_messages)} messages from thread {target_thread_ts}.")

        if not all_thread_messages:
            logger.warning("No messages found in the thread.")
            error_view = build_loading_modal_view("Could not find any messages in this thread to process.")
            client.views_update(view_id=view_id_to_process, view=error_view)
            return

        formatted_conversation = format_messages_for_summary(all_thread_messages, client)
        if not formatted_conversation:
            logger.warning("Formatted conversation is empty.")
            error_view = build_loading_modal_view("Could not format the conversation for summary.")
            client.views_update(view_id=view_id_to_process, view=error_view)
            return

        logger.info(f"Generating ticket components from formatted conversation (first 200 chars): {formatted_conversation[:200]}...")
        ticket_components = generate_ticket_components_from_thread(formatted_conversation)
        
        ai_title = ticket_components.get("suggested_title")
        ai_description = ticket_components.get("refined_description")
        thread_summary = ticket_components.get("thread_summary") # Get the thread summary
        ai_priority = ticket_components.get("priority") # <-- New
        ai_issue_type = ticket_components.get("issue_type") # <-- New

        if not ai_title or ai_title.startswith("Error:") or not ai_description or ai_description.startswith("Error:"):
            error_message = "Sorry, I couldn't generate all ticket details from the thread."
            # Include new fields in error logging if needed
            detailed_error = f"AI generation failed. Title: '{ai_title}', Description: '{ai_description}', Priority: '{ai_priority}', Issue Type: '{ai_issue_type}'"
            logger.error(detailed_error)
            final_error_view = build_loading_modal_view(f"{error_message}. Please try again. ({detailed_error[:100]})" )
            client.views_update(view_id=view_id_to_process, view=final_error_view)
            return

        logger.info(f"AI Suggested Title: {ai_title}")
        logger.info(f"AI Description: {ai_description[:200]}...")
        logger.info(f"AI Predicted Priority: {ai_priority}") # <-- New log
        logger.info(f"AI Predicted Issue Type: {ai_issue_type}") # <-- New log
        if thread_summary and not thread_summary.startswith("Error:"):
             logger.info(f"AI Thread Summary (for context/debugging): {thread_summary[:200]}...")
             thread_summary_for_context = thread_summary # Store for private_metadata
        else:
             logger.warning(f"AI Thread Summary was not generated or had an error: {thread_summary}")
             thread_summary_for_context = "" # Ensure it's an empty string if problematic

        context_to_store = {
            "channel_id": target_channel_id,    # Use determined target_channel_id
            "thread_ts": target_thread_ts,      # Use determined target_thread_ts
            "user_id": user_id_invoked,
            "is_message_action": True, # Retain this, as it still pertains to a message thread context
            "thread_summary": thread_summary_for_context 
        }
        private_metadata_key_str = json.dumps(context_to_store)

        # conversation_states[private_metadata_key_str] = context_to_store # This line seems to store the context in conversation_states using the JSON string AS THE KEY. Ensure this is intended for retrieval in modal submission.
        # Typically, private_metadata in the modal itself carries the context directly.

        final_modal_view = build_create_ticket_modal(
            initial_summary=ai_title, 
            initial_description=ai_description,
            initial_priority=ai_priority, # <-- New
            initial_issue_type=ai_issue_type, # <-- New
            private_metadata=private_metadata_key_str 
        )
        
        client.views_update(view_id=view_id_to_process, view=final_modal_view)
        logger.info(f"Updated modal {view_id_to_process} with Jira creation form for user {user_id_invoked} (shortcut path).")

    except SlackApiError as e:
        logger.error(f"Slack API error in shortcut flow (create_ticket_from_thread_from_shortcut_continue_create_ticket): {e.response['error']}", exc_info=True)
        error_text = f"A Slack API error occurred: {e.response['error']}. Please try again."
        if view_id_to_process:
            try:
                client.views_update(view_id=view_id_to_process, view=build_loading_modal_view(error_text))
            except Exception as e_update:
                 logger.error(f"Failed to update modal {view_id_to_process} with Slack API error (shortcut path): {e_update}")
        elif trigger_id: # If view_id_to_process was not set, try to open a new error modal
            try:
                client.views_open(trigger_id=trigger_id, view=build_loading_modal_view(error_text))
            except Exception as e_open_err:
                logger.error(f"Failed to open new error modal for shortcut after SlackApiError: {e_open_err}")

    except Exception as e:
        logger.error(f"Unexpected error in shortcut flow (create_ticket_from_thread_from_shortcut_continue_create_ticket): {e}", exc_info=True)
        error_text = "An unexpected error occurred while processing your request."
        if view_id_to_process:
            try:
                client.views_update(view_id=view_id_to_process, view=build_loading_modal_view(error_text))
            except Exception as e_update:
                logger.error(f"Failed to update modal {view_id_to_process} with general error (shortcut path): {e_update}")
        elif trigger_id: # Fallback for shortcut path
            try:
                client.views_open(trigger_id=trigger_id, view=build_loading_modal_view(error_text))
            except SlackApiError as e_modal_open_final:
                logger.error(f"Failed to open final error modal for shortcut: {e_modal_open_final}")
                if target_channel_id and user_id_invoked:
                    try:
                        client.chat_postEphemeral(channel=target_channel_id, user=user_id_invoked, thread_ts=target_thread_ts, text=error_text)
                    except Exception as e_ephemeral:
                        logger.error(f"Failed to send ephemeral error message for shortcut: {e_ephemeral}")

@app.action("create_ticket_from_Bot_from_Looks_Good_Create_Ticket_Button_Action")
def create_ticket_from_Bot_from_Looks_Good_Create_Ticket_Button_Action(ack, body, client, logger, context):
    ack()  # Acknowledge the button press immediately

    trigger_id = body["trigger_id"]
    user_id_who_clicked = body["user"]["id"]
    action_details_str = body["actions"][0]["value"]

    logger.info(f"'Looks Good, Create Ticket' button pressed by {user_id_who_clicked}. Action value: {action_details_str}")

    try:
        action_details = json.loads(action_details_str)
        title = action_details.get("title")
        description = action_details.get("description")
        original_channel_id = action_details.get("channel_id")
        original_thread_ts = action_details.get("thread_ts")
        summary_for_confirmation = action_details.get("summary_for_confirmation") # This is the AI summary
        ai_priority = action_details.get("priority") # NEW: Get priority from button value
        ai_issue_type = action_details.get("issue_type") # NEW: Get issue_type from button value

        if not title or not description:
            logger.error("Missing title or description in action_details for 'Looks Good, Create Ticket' button.")
            if original_channel_id and original_thread_ts: # Try to post ephemeral if context is available
                client.chat_postEphemeral(
                    channel=original_channel_id,
                    user=user_id_who_clicked,
                    thread_ts=original_thread_ts,
                    text="Sorry, I couldn't retrieve the generated title or description to pre-fill the form. Please try again."
                )
            return

        # Prepare private_metadata for the Jira creation modal
        # This will be used by handle_modal_submission to know where to post confirmation
        # and to get the thread_summary for the 'View Similar Tickets' button.
        private_metadata_payload = {
            "channel_id": original_channel_id,  # Channel for confirmation message post-ticket creation
            "thread_ts": original_thread_ts,    # Thread for confirmation message
            "user_id": user_id_who_clicked,     # User who initiated
            "flow_origin": "bot_looks_good_create", # Identifier for this flow
            "thread_summary": summary_for_confirmation, # CRITICAL: This is the AI summary for 'View Similar Tickets'
            "ai_priority": ai_priority, # NEW: Pass to modal builder
            "ai_issue_type": ai_issue_type, # NEW: Pass to modal builder
            # "original_ticket_key" will be added by handle_modal_submission after ticket is created
        }
        private_metadata_str = json.dumps(private_metadata_payload)
        
        # Store in conversation_states if your handle_modal_submission relies on it.
        # However, directly passing it via private_metadata in the modal is more common.
        # For now, let's assume handle_modal_submission primarily uses the modal's private_metadata.
        # conversation_states[private_metadata_str] = private_metadata_payload 
        # logger.info(f"Stored modal context for 'bot_looks_good_create' in conversation_states with key: {private_metadata_str}")

        modal_view = build_create_ticket_modal(
            initial_summary=title,
            initial_description=description,
            initial_priority=ai_priority, # NEW: Pass to modal builder
            initial_issue_type=ai_issue_type, # NEW: Pass to modal builder
            private_metadata=private_metadata_str
        )

        client.views_open(trigger_id=trigger_id, view=modal_view)
        logger.info(f"Opened Jira creation modal for user {user_id_who_clicked} (from 'Looks Good' button) with pre-filled AI content.")

    except json.JSONDecodeError as e_json:
        logger.error(f"Failed to parse action_details JSON for 'Looks Good, Create Ticket' button: {e_json}. Value: {action_details_str}")
        if body.get("channel",{}).get("id") and body.get("message",{}).get("thread_ts") :
            client.chat_postEphemeral(channel=body["channel"]["id"], user=user_id_who_clicked, thread_ts=body["message"]["thread_ts"], text="Error processing your request due to invalid data.")
    except SlackApiError as e_slack:
        logger.error(f"Slack API error in 'Looks Good, Create Ticket' button action: {e_slack.response['error']}", exc_info=True)
        if body.get("channel",{}).get("id") and body.get("message",{}).get("thread_ts"):
            client.chat_postEphemeral(channel=body["channel"]["id"], user=user_id_who_clicked, thread_ts=body["message"]["thread_ts"], text=f"A Slack API error occurred: {e_slack.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error in 'Looks Good, Create Ticket' button action: {e}", exc_info=True)
        if body.get("channel",{}).get("id") and body.get("message",{}).get("thread_ts"):
            client.chat_postEphemeral(channel=body["channel"]["id"], user=user_id_who_clicked, thread_ts=body["message"]["thread_ts"], text="An unexpected error occurred.")


# --- Helper for background task ---
def _task_find_and_display_similar_tickets(client, logger, view_id, thread_summary, user_id, channel_id, source, original_ticket_key):
    logger.info(f"Background task started for view_id: {view_id}, finding similar tickets for user: {user_id}")
    final_view = None
    try:
        logger.info(f"Finding duplicates based on thread summary (first 100 chars): {thread_summary[:100]}...")
        duplicate_results = find_and_summarize_duplicates(user_query=thread_summary)
        top_similar_tickets_raw = duplicate_results.get("tickets", [])
        
        # Sort the tickets based on the defined criteria
        sorted_tickets = sorted(top_similar_tickets_raw, key=get_ticket_sort_key)

        similar_tickets_details_for_modal = []
        for ticket_result in sorted_tickets: # Iterate over sorted_tickets
            metadata = ticket_result.get("metadata", {})
            problem_statement = ticket_result.get("page_content") 
            solution_summary = metadata.get("retrieved_solution_summary")
            if not problem_statement:
                problem_statement = metadata.get("retrieved_problem_statement", "_(Problem details not found)_")
            if not solution_summary:
                solution_summary = "_(Resolution details not found)_";
            transformed_ticket = {
                'key': metadata.get('ticket_id', 'N/A'),
                'url': metadata.get('url'),
                'summary': metadata.get('summary', '_(Original summary missing)_'),
                'status': metadata.get('status', '_Status N/A_'),
                'priority': metadata.get('priority', ''),
                'assignee': metadata.get('assignee', ''),
                'owned_by_team': metadata.get('owned_by_team', 'N/A'),
                'retrieved_problem_statement': problem_statement,
                'retrieved_solution_summary': solution_summary
            }
            similar_tickets_details_for_modal.append(transformed_ticket)

        # Store detailed ticket info for later retrieval in submission handler
        if view_id and similar_tickets_details_for_modal: # view_id is the loading_view_id here
            conversation_states[f"{view_id}_displayed_tickets"] = similar_tickets_details_for_modal
            logger.info(f"Stored {len(similar_tickets_details_for_modal)} displayed ticket details in conversation_states for {view_id}")

        if not similar_tickets_details_for_modal:
            logger.info(f"No similar tickets found based on the thread summary for view_id: {view_id}.")
            final_view = build_similar_tickets_modal([])
        else:
            final_view = build_similar_tickets_modal(
                similar_tickets_details_for_modal,
                channel_id,
                source, 
                original_ticket_key,
                loading_view_id=view_id # Pass loading_view_id (which is view_id here)
            ) 
        
        client.views_update(view_id=view_id, view=final_view)
        logger.info(f"Updated modal {view_id} for user {user_id} with {len(similar_tickets_details_for_modal)} similar tickets.")

    except Exception as e:
        logger.error(f"Error in background task for view_id {view_id}: {e}", exc_info=True)
        # Update the modal with an error message
        error_modal_view = build_loading_modal_view(message="Sorry, an error occurred while finding similar tickets.")
        try:
            client.views_update(view_id=view_id, view=error_modal_view)
        except Exception as e_update:
            logger.error(f"Failed to update modal {view_id} with error message: {e_update}")


@app.action("view_similar_tickets_modal_button")
def handle_view_similar_tickets_action(ack, body, client, logger):
    logger.info(f"User {body['user']['id']} clicked 'View Similar Tickets' button.")
    ack() # Acknowledge the action immediately
    source = "view_similar_tickets_action"  # Add source information
    trigger_id = body["trigger_id"]
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"] # For potential ephemeral messages
    action_details = body["actions"][0]
    button_value_str = action_details.get("value")
    original_ticket_key = None # Initialize original_ticket_key
    
    thread_summary = None
    if button_value_str:
        try:
            button_payload = json.loads(button_value_str)
            if isinstance(button_payload, dict):
                thread_summary = button_payload.get("thread_summary")
                original_ticket_key = button_payload.get("original_ticket_key") # Extract original_ticket_key
            else:
                logger.error(f"Button value was not a dictionary: {button_value_str}")
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON from button value: {button_value_str}")
    
    if not thread_summary:
        logger.warning("Could not extract thread_summary from button value. Cannot find similar tickets.")
        try:
            client.chat_postEphemeral(channel=channel_id, user=user_id, text="Sorry, I couldn't retrieve the context needed to find similar tickets.")
        except Exception as e_post:
            logger.error(f"Failed to post ephemeral error for missing thread_summary: {e_post}")
        return

    try:
        # --- Open a loading modal immediately ---
        loading_view = build_loading_modal_view(message="🔍 Finding similar tickets for you... please wait a moment.")
        loading_modal_response = client.views_open(
            trigger_id=trigger_id,
            view=loading_view
        )
        loading_view_id = loading_modal_response["view"]["id"]
        logger.info(f"Opened loading modal {loading_view_id} for user {user_id} to find similar tickets.")

        # --- Submit the long-running task to the executor ---
        app_executor.submit(
            _task_find_and_display_similar_tickets, 
            client, 
            logger, 
            loading_view_id, 
            thread_summary, 
            user_id,
            channel_id, # Pass channel_id if the task needs it for error reporting, though modal update is preferred
            source,  # Pass the source to the task
            original_ticket_key  # Pass original_ticket_key
        )
        logger.info(f"Submitted background task for view_id: {loading_view_id} to find similar tickets.")

    except SlackApiError as e:
        logger.error(f"Slack API error opening loading modal: {e.response['error']}", exc_info=True)
        # Notify user if initial modal opening fails
        try:
            client.chat_postEphemeral(channel=channel_id, user=user_id, text="Sorry, an error occurred trying to process your request. Please try again.")
        except Exception as e_post:
            logger.error(f"Failed to post ephemeral error for modal open failure: {e_post}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_view_similar_tickets_action: {e}", exc_info=True)
        try:
            client.chat_postEphemeral(channel=channel_id, user=user_id, text="An unexpected error occurred. Please try again.")
        except Exception as e_post:
            logger.error(f"Failed to post ephemeral error for unexpected error: {e_post}")


@app.view("similar_tickets_modal")
def handle_similar_tickets_submission(ack, body, client, logger):
    """Handles the submission of the similar tickets modal (e.g., when 'Link Selected Tickets' or 'Continue Create Ticket' is clicked)."""
    
    view = body.get("view", {})
    private_metadata_str = view.get("private_metadata", "{}")
    user_id = body.get("user", {}).get("id")
    current_view_id = view.get("id")
    trigger_id = body.get("trigger_id") # Useful for opening new views in error scenarios

    try:
        private_metadata = json.loads(private_metadata_str)
        submit_action = private_metadata.get("submit_action")
        source_channel_id = private_metadata.get("channel_id") # Channel where the modal was invoked or relevant context

        if submit_action == "continue_creation":
            logger.info(f"User {user_id} submitted similar_tickets_modal for 'continue_creation' from view {current_view_id}.")
            original_thread_channel_id = private_metadata.get("original_thread_channel_id")
            original_thread_ts = private_metadata.get("original_thread_ts")

            if not original_thread_channel_id or not original_thread_ts:
                logger.error(f"Missing original_thread_channel_id or original_thread_ts in private_metadata for continue_creation. View: {current_view_id}")
                error_view = build_loading_modal_view("Error: Essential thread information missing. Cannot continue ticket creation.")
                ack({"response_action": "update", "view": error_view})
                return

            # Acknowledge by updating to a loading view
            loading_view_payload = build_loading_modal_view("🤖 Our AI is analyzing the thread and generating ticket details... ⏳")
            ack({"response_action": "update", "view": loading_view_payload})
            logger.info(f"Updated modal {current_view_id} to loading state for 'continue_creation'.")

            # --- Begin: Ported logic from create_ticket_from_thread_from_shortcut_continue_create_ticket --- 
            all_thread_messages = []
            cursor = None
            while True:
                replies_result = client.conversations_replies(
                    channel=original_thread_channel_id,
                    ts=original_thread_ts,
                    limit=200,
                    cursor=cursor
                )
                all_thread_messages.extend(replies_result.get('messages', []))
                if not replies_result.get('has_more'):
                    break
                cursor = replies_result.get('response_metadata', {}).get('next_cursor')
            
            logger.info(f"Fetched {len(all_thread_messages)} messages from thread {original_thread_ts} for view {current_view_id}.")

            if not all_thread_messages:
                logger.warning(f"No messages found in the thread for continue_creation. View: {current_view_id}")
                error_view = build_loading_modal_view("Could not find any messages in this thread to process.")
                client.views_update(view_id=current_view_id, view=error_view)
                return

            formatted_conversation = format_messages_for_summary(all_thread_messages, client)
            if not formatted_conversation:
                logger.warning(f"Formatted conversation is empty for continue_creation. View: {current_view_id}")
                error_view = build_loading_modal_view("Could not format the conversation for summary.")
                client.views_update(view_id=current_view_id, view=error_view)
                return

            logger.info(f"Generating ticket components from formatted conversation (first 200 chars): {formatted_conversation[:200]} for view {current_view_id}")
            ticket_components = generate_ticket_components_from_thread(formatted_conversation)
            
            ai_title = ticket_components.get("suggested_title")
            ai_description = ticket_components.get("refined_description")
            thread_summary_for_context = ticket_components.get("thread_summary", "")
            ai_priority = ticket_components.get("priority")
            ai_issue_type = ticket_components.get("issue_type")

            if not ai_title or ai_title.startswith("Error:") or not ai_description or ai_description.startswith("Error:"):
                error_message = "Sorry, I couldn't generate all ticket details from the thread."
                detailed_error = f"AI generation failed. Title: '{ai_title}', Description: '{ai_description}', Priority: '{ai_priority}', Issue Type: '{ai_issue_type}'"
                logger.error(f"{detailed_error} for view {current_view_id}")
                final_error_view = build_loading_modal_view(f"{error_message}. Please try again. ({detailed_error[:100]})" )
                client.views_update(view_id=current_view_id, view=final_error_view)
                return
            
            logger.info(f"AI Suggested Title: {ai_title} for view {current_view_id}")

            context_to_store_for_jira_modal = {
                "channel_id": original_thread_channel_id, 
                "thread_ts": original_thread_ts, 
                "user_id": user_id,
                "is_message_action": True, # Or a more specific flag if needed
                "thread_summary": thread_summary_for_context
            }
            jira_modal_private_metadata_str = json.dumps(context_to_store_for_jira_modal)

            final_jira_modal_view = build_create_ticket_modal(
                initial_summary=ai_title, 
                initial_description=ai_description,
                initial_priority=ai_priority,
                initial_issue_type=ai_issue_type,
                private_metadata=jira_modal_private_metadata_str 
            )
            
            client.views_update(view_id=current_view_id, view=final_jira_modal_view)
            logger.info(f"Updated modal {current_view_id} with Jira creation form after 'continue_creation' submit.")
            # --- End: Ported logic --- 

        elif submit_action == "link_tickets":
            logger.info(f"User {user_id} submitted similar_tickets_modal for 'link_tickets' from view {current_view_id}.")
            original_ticket_key = private_metadata.get("original_ticket_key")
            # The channel_id for linking confirmation messages is source_channel_id (modal's context)
            # thread_ts for linking confirmation is not directly available in private_metadata in this exact form for linking, but might not be needed if modal updates are sufficient.

            if not original_ticket_key:
                logger.error("Original ticket key not found in private metadata for linking.")
                error_view = {
                    "type": "modal", "title": {"type": "plain_text", "text": "Error"},
                    "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": ":warning: Critical information (original ticket key) was missing. Cannot link tickets."}}],
                    "close": {"type": "plain_text", "text": "Close"}
                }
                ack({"response_action": "update", "view": error_view})
                return

            selected_ticket_keys = []
            state_values = view.get("state", {}).get("values", {})
            logger.debug(f"View state values for linking from similar_tickets_modal: {json.dumps(state_values, indent=2)}")

            for block_id, block_content in state_values.items():
                if block_id.startswith("input_link_ticket_"):
                    checkbox_action_id_key = list(block_content.keys())[0]
                    if checkbox_action_id_key.startswith("checkbox_action_"):
                        selected_options = block_content[checkbox_action_id_key].get("selected_options", [])
                        if selected_options:
                            for option in selected_options:
                                selected_ticket_keys.append(option["value"])
            
            logger.info(f"User {user_id} submitted similar_tickets_modal to link: {selected_ticket_keys} to original ticket: {original_ticket_key}")

            if not selected_ticket_keys:
                logger.info("No tickets were selected to link via similar_tickets_modal.")
                error_view = {
                    "type": "modal", "title": {"type": "plain_text", "text": "Error"},
                    "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": ":warning: No tickets were selected. Please select at least one ticket to link."}}],
                    "close": {"type": "plain_text", "text": "Close"}
                }
                ack({"response_action": "update", "view": error_view})
                return
            
            # REMOVED early ack() here. All ack() calls will now include a response_action.

            original_ticket = get_jira_ticket(original_ticket_key)
            if not original_ticket:
                logger.error(f"Could not fetch original ticket {original_ticket_key} for linking (from view submission).")
                error_view = {
                    "type": "modal", "title": {"type": "plain_text", "text": "Error"},
                    "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f":warning: Sorry, I couldn't retrieve the details of the original ticket {original_ticket_key} to link to."}}],
                    "close": {"type": "plain_text", "text": "Close"}
                }
                ack({"response_action": "update", "view": error_view})
                return

            current_description = original_ticket.get("description", "").strip()
            final_description = current_description # Start with current description
            description_updated_with_similar_tickets = False # Flag for similar tickets section
            description_updated_with_linked_summaries = False # Flag for summaries from linked tickets

            # Part 1: Build and add Similar Tickets links
            similar_tickets_header_text = "\n\n---\n*Similar Tickets:*"
            links_text_to_append = ""
            actual_new_links_count = 0

            for ticket_key_to_link in selected_ticket_keys:
                link_line_for_check = f"• {ticket_key_to_link}"
                if not (similar_tickets_header_text in final_description and link_line_for_check in final_description):
                    links_text_to_append += f"\n• {ticket_key_to_link}"
                    actual_new_links_count += 1
            
            if actual_new_links_count > 0:
                if similar_tickets_header_text not in final_description:
                    if final_description and not final_description.endswith('\n'):
                        final_description += '\n' # Add newline if current description doesn't end with one
                    final_description += similar_tickets_header_text
                final_description += links_text_to_append + "\n"
                description_updated_with_similar_tickets = True

            # Part 2: Add Solution Summaries from selected linked tickets
            loading_view_id = private_metadata.get("loading_view_id")
            linked_ticket_summaries_content = ""
            if loading_view_id:
                displayed_tickets_info = conversation_states.pop(f"{loading_view_id}_displayed_tickets", None)
                if displayed_tickets_info:
                    logger.info(f"Retrieved {len(displayed_tickets_info)} displayed ticket details from conversation_states for {loading_view_id}")
                    for s_key in selected_ticket_keys:
                        for ticket_info in displayed_tickets_info:
                            if ticket_info.get('key') == s_key:
                                solution_summary = ticket_info.get('retrieved_solution_summary')
                                if solution_summary and solution_summary != '_(Resolution details not found)_' and solution_summary != '_(Problem details not found)_': # Ensure summary is meaningful
                                    # Add newline if current description doesn't end with one, before adding the section
                                    if linked_ticket_summaries_content == "" and final_description and not final_description.endswith('\n'):
                                        linked_ticket_summaries_content += '\n'
                                    linked_ticket_summaries_content += f"\n---\n*Summary from {s_key}:*\n{solution_summary}\n"
                                    description_updated_with_linked_summaries = True
                                break # Found the selected ticket's info
                else:
                    logger.warning(f"Could not retrieve displayed_tickets_info from conversation_states for {loading_view_id}")
            else:
                logger.warning("loading_view_id not found in private_metadata. Cannot fetch linked ticket summaries.")
            
            if linked_ticket_summaries_content: # Append all collected summaries to the final description
                final_description += linked_ticket_summaries_content

            # Determine if any update is needed to Jira
            if not description_updated_with_similar_tickets and not description_updated_with_linked_summaries:
                logger.info(f"No new links to add for {original_ticket_key}, and no new summaries from linked tickets to add.")
                already_linked_view = {
                    "type": "modal", "title": {"type": "plain_text", "text": "No Changes"},
                    "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f"It looks like the selected tickets are already linked to <{original_ticket.get('url')}|{original_ticket_key}>, and no new progress summary needs to be added."}}],
                    "close": {"type": "plain_text", "text": "Close"}
                }
                ack({"response_action": "update", "view": already_linked_view})
                return

            # If we are here, either new links or new summaries (or both) need to be added to the description.
            if description_updated_with_similar_tickets or description_updated_with_linked_summaries:
                update_payload = {"key": original_ticket_key, "description": final_description.strip()}
                update_success = update_jira_ticket(update_payload)
            
                if update_success:
                    logger.info(f"Jira ticket update successful for {original_ticket_key} with similar tickets and/or linked summaries.")
                    linked_message_part = f"Successfully linked {actual_new_links_count} ticket(s)" if description_updated_with_similar_tickets else ""
                    summary_message_part = "Summaries from linked tickets added" if description_updated_with_linked_summaries else ""
                    
                    final_success_message = ""
                    if linked_message_part and summary_message_part:
                        final_success_message = f"{linked_message_part} and {summary_message_part.lower()} to <{original_ticket.get('url')}|{original_ticket_key}>!"
                    elif linked_message_part:
                        final_success_message = f"{linked_message_part} to <{original_ticket.get('url')}|{original_ticket_key}>!"
                    elif summary_message_part:
                        final_success_message = f"{summary_message_part} for <{original_ticket.get('url')}|{original_ticket_key}>!"
                    else: # Should not happen if we passed the check above, but as a fallback
                        final_success_message = f"Ticket <{original_ticket.get('url')}|{original_ticket_key}> updated."

                    success_linking_modal_view = {
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "✅ Update Successful"},
                        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": final_success_message}}],
                        "close": {"type": "plain_text", "text": "Close"}
                    }
                    ack({"response_action": "update", "view": success_linking_modal_view})
                else: # Jira update failed
                    logger.error(f"Jira ticket update for linking/progress summary returned False for {original_ticket_key}.")
                    # ... (existing error linking modal view) ...
                    error_linking_modal_view = {
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "⚠️ Link Failed"},
                        "blocks": [{
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f"Sorry, there was an issue updating <{original_ticket.get('url')}|{original_ticket_key}>. The Jira update failed."}
                        }],
                        "close": {"type": "plain_text", "text": "Close"}
                    }
                    ack({"response_action": "update", "view": error_linking_modal_view})
            else:
                # This case means the description effectively did not change, though logic suggested it might.
                # This could happen if only already linked tickets were selected and progress summary was already there or not provided.
                # This should have been caught by the (actual_new_links_count == 0 and not description_updated_by_progress_summary) check.
                # Corrected check:
                # This should have been caught by the (not description_updated_with_similar_tickets and not description_updated_with_progress_summary) check.
                logger.info(f"No effective change to description for ticket {original_ticket_key}. Re-confirming as 'No Changes'.")
                no_effective_change_view = {
                    "type": "modal", "title": {"type": "plain_text", "text": "No Changes Made"},
                    "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f"No new links were added and progress summary was already up-to-date for <{original_ticket.get('url')}|{original_ticket_key}>."}}],
                    "close": {"type": "plain_text", "text": "Close"}
                }
                ack({"response_action": "update", "view": no_effective_change_view})

        else: # Unknown submit_action or no action
            logger.warning(f"Unknown or missing submit_action in similar_tickets_modal. Action: '{submit_action}'. View ID: {current_view_id}")
            ack() # Simple acknowledgment if the action is unclear

    except SlackApiError as e_slack:
        logger.error(f"Slack API error in handle_similar_tickets_submission (view: {current_view_id}): {e_slack.response['error']}", exc_info=True)
        error_text = f"A Slack API error occurred: {e_slack.response['error']}."
        # Try to update the current modal if it exists and an ack hasn't been sent with an update already.
        # This is a best-effort as ack() might have already been called or the view might be closed.
        if current_view_id: # Check if current_view_id is available
            try:
                # Check if ack has already been called with a response_action. This is hard to check directly.
                # For safety, we might only call client.views_update if we are sure ack wasn't for an update.
                # However, if an error occurs before any ack, updating is fine.
                # If an error occurs after ack(update), this client.views_update might fail or be ignored.
                # Let's assume if we reach here, we want to try to show an error on the current modal.
                client.views_update(view_id=current_view_id, view=build_loading_modal_view(error_text + " Please try again."))
            except Exception as e_update:
                logger.error(f"Failed to update modal {current_view_id} with Slack API error message: {e_update}")
        # If no current_view_id or update fails, not much else can be done for this interaction.

    except Exception as e:
        logger.error(f"Error in handle_similar_tickets_submission (view: {current_view_id}): {e}", exc_info=True)
        # Generic error, update modal to show a generic error message if possible
        if current_view_id:
            try:
                generic_error_view = build_loading_modal_view(message=":warning: An unexpected error occurred. Please try again.")
                client.views_update(view_id=current_view_id, view=generic_error_view)
            except Exception as e_update_generic:
                logger.error(f"Failed to update modal {current_view_id} with generic error message: {e_update_generic}")
        # If ack was already used for an update, this might fail. A simple ack() might be the only option if not already called.
        # However, Slack expects only one ack per interaction. If an error happens after an ack(update), the modal might already be gone or changed.


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
        #         total_tickets_to_scrape=100000, # Changed from 2000 to 200
        #         api_batch_size=300
        #     )
        #     logger.info(f"Jira scraping complete. Scraped/Updated {scraped_count} out of {total_available} available tickets for project {project_key_to_scrape}.")

        #     if scraped_count > 0:
        #         logger.info("Proceeding to Pinecone ingestion pipeline...")
        # run_ingestion_pipeline() # Call the ingestion pipeline # Temporarily commented out
        #         logger.info("Temporarily skipping Pinecone ingestion pipeline after scraping.") # Added temp log
        #     else:
        #         logger.info("No tickets were scraped. Skipping Pinecone ingestion pipeline.")

        # else:
        #     logger.warning("JIRA_PROJECT_KEY_TO_SCRAPE environment variable not set. Skipping Jira scraping and Pinecone ingestion on startup.")

        logger.info("Starting Socket Mode Handler...")
        # Use SocketModeHandler for development/testing without exposing a public URL
        # Requires SLACK_APP_TOKEN (App-Level Token with connections:write scope)
        handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
        handler.start()
    # except KeyError as e:
    #     logger.error(f"Missing environment variable: {e}. Ensure SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, and SLACK_APP_TOKEN are set in .env")
    except Exception as e:
        logger.error(f"Error starting app: {e}") 