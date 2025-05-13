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

# Import mention handler
from handlers.mention_handler import handle_app_mention_event, fetch_conversation_context_for_mention, format_messages_for_summary, summarize_conversation

# Import mention flow handlers
from handlers.modals.interaction_handlers import build_create_ticket_modal
from services.jira_service import create_jira_ticket
from handlers.flows.ticket_creation_orchestrator import present_duplicate_check_and_options
# Import AI title/description generators
from services.genai_service import generate_suggested_title, generate_refined_description, generate_ticket_components_from_thread, generate_ticket_components_from_description, summarize_thread
# Import UI helpers
from utils.slack_ui_helpers import get_issue_type_emoji, get_priority_emoji, build_rich_ticket_blocks

# Import the duplicate detection service
from services.duplicate_detection_service import find_and_summarize_duplicates,find_and_summarize_duplicatessss
from handlers.modals.modal_builders import build_similar_tickets_modal, build_loading_modal_view, build_description_capture_modal

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

        duplicate_results = find_and_summarize_duplicatessss(user_query=summary_to_search)
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

            for ticket_result in top_tickets:
                metadata = ticket_result.get("metadata", {})
                
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
                    'issue_type': metadata.get('issue_type', ''),
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
        loading_view_payload = build_loading_modal_view("⏳ Analyzing thread and searching for similar issues...")
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
        
        if not all_thread_messages:
            logger.warning(f"No messages found in thread {thread_parent_ts} for similarity check.")
            final_view_payload = build_similar_tickets_modal([]) # Show empty results modal
            client.views_update(view_id=loading_view_id, view=final_view_payload)
            return

        # 2. Format Messages
        # Assuming format_messages_for_summary expects client as an argument if it needs to fetch user names
        formatted_conversation = format_messages_for_summary(all_thread_messages, client)
        if not formatted_conversation:
            logger.warning(f"Formatted conversation is empty for thread {thread_parent_ts}.")
            final_view_payload = build_similar_tickets_modal([])
            client.views_update(view_id=loading_view_id, view=final_view_payload)
            return

        # 3. Generate AI Summary of the Thread
        logger.info(f"Generating AI summary for thread {thread_parent_ts} (first 100 chars of formatted: '{formatted_conversation[:100]}...')")
        thread_ai_summary = summarize_thread(formatted_conversation)

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
        duplicate_results = find_and_summarize_duplicates(user_query=thread_ai_summary)
        top_similar_tickets_raw = duplicate_results.get("tickets", [])

        # 5. Prepare and Display Results
        similar_tickets_details_for_modal = []
        for ticket_result in top_similar_tickets_raw:
            metadata = ticket_result.get("metadata", {})
            
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
                'issue_type': metadata.get('issue_type', ''),
                'retrieved_problem_statement': problem_statement_for_display,
                'retrieved_solution_summary': solution_summary_for_display
            }
            similar_tickets_details_for_modal.append(transformed_ticket)
        
        final_view_payload = build_similar_tickets_modal(similar_tickets_details_for_modal)
        client.views_update(view_id=loading_view_id, view=final_view_payload)
        logger.info(f"Updated modal {loading_view_id} with {len(similar_tickets_details_for_modal)} similar tickets found for thread {thread_parent_ts}.")

    except Exception as e:
        logger.error(f"Error in background task _task_check_similar_from_thread_and_display for {loading_view_id}: {e}", exc_info=True)
        try:
            error_view = build_loading_modal_view("Sorry, an unexpected error occurred while checking for similar issues.")
            client.views_update(view_id=loading_view_id, view=error_view)
        except Exception as e_update:
            logger.error(f"Failed to update modal {loading_view_id} with error from background task: {e_update}")


# --- Existing Shortcut Handler for Create Ticket from Thread ---
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

        if not ai_title or ai_title.startswith("Error:") or not ai_description or ai_description.startswith("Error:"):
            error_message = "Sorry, I couldn't generate all ticket details from the thread."
            detailed_error = f"AI generation failed. Title: '{ai_title}', Description: '{ai_description}'"
            logger.error(detailed_error)
            final_error_view = build_loading_modal_view(f"{error_message}. Please try again. ({detailed_error[:100]})" )
            client.views_update(view_id=view_id, view=final_error_view)
            return

        logger.info(f"AI Suggested Title: {ai_title}")
        logger.info(f"AI Refined Description: {ai_description[:200]}...")
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
        else:
             try:
                client.chat_postEphemeral(channel=channel_id, user=user_id_invoked, thread_ts=original_message_ts, text=error_text)
             except Exception as e_ephemeral:
                logger.error(f"Failed to send ephemeral error for Slack API error: {e_ephemeral}")

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


# --- Helper for background task ---
def _task_find_and_display_similar_tickets(client, logger, view_id, thread_summary, user_id, channel_id):
    logger.info(f"Background task started for view_id: {view_id}, finding similar tickets for user: {user_id}")
    final_view = None
    try:
        logger.info(f"Finding duplicates based on thread summary (first 100 chars): {thread_summary[:100]}...")
        duplicate_results = find_and_summarize_duplicates(user_query=thread_summary)
        top_similar_tickets = duplicate_results.get("tickets", [])
        
        similar_tickets_details_for_modal = []
        for ticket_result in top_similar_tickets:
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
                'issue_type': metadata.get('issue_type', ''),
                'retrieved_problem_statement': problem_statement,
                'retrieved_solution_summary': solution_summary
            }
            similar_tickets_details_for_modal.append(transformed_ticket)

        if not similar_tickets_details_for_modal:
            logger.info(f"No similar tickets found based on the thread summary for view_id: {view_id}.")
            # Update the modal to say no tickets were found
            final_view = build_similar_tickets_modal([]) # Pass empty list to show "No tickets" message
        else:
            final_view = build_similar_tickets_modal(similar_tickets_details_for_modal)
        
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

    trigger_id = body["trigger_id"]
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"] # For potential ephemeral messages
    action_details = body["actions"][0]
    button_value_str = action_details.get("value")

    thread_summary = None
    if button_value_str:
        try:
            button_payload = json.loads(button_value_str)
            if isinstance(button_payload, dict):
                thread_summary = button_payload.get("thread_summary")
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
            channel_id # Pass channel_id if the task needs it for error reporting, though modal update is preferred
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
        #         total_tickets_to_scrape=2000, # Changed from 2000 to 200
        #         api_batch_size=100
        #     )
        #     logger.info(f"Jira scraping complete. Scraped/Updated {scraped_count} out of {total_available} available tickets for project {project_key_to_scrape}.")

            # if scraped_count > 0:
                # logger.info("Proceeding to Pinecone ingestion pipeline...")
        # run_ingestion_pipeline() # Call the ingestion pipeline
            # else:
                # logger.info("No tickets were scraped. Skipping Pinecone ingestion pipeline.")

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