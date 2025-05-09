# app.py
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
import logging
from slack_sdk import WebClient
import json

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
from handlers.mention_handler import handle_app_mention_event

# Import mention flow handlers
from handlers.modals.interaction_handlers import build_create_ticket_modal
from services.jira_service import create_jira_ticket
from handlers.flows.ticket_creation_orchestrator import present_duplicate_check_and_options

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

    conversation_key = f"{thread_ts}_{user_id}_mention_context"
    mention_context = conversation_states.get(conversation_key)

    summary_to_search = ""
    if mention_context and "summary" in mention_context:
        summary_to_search = mention_context["summary"]
        logger.info(f"Retrieved summary for duplicate search: {summary_to_search[:100]}...")
    else:
        logger.warning(f"Could not retrieve summary from conversation_states for key {conversation_key}. Cannot find similar issues.")
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, user=user_id, text="Sorry, I couldn't retrieve the conversation summary to search for similar issues.")
        return

    if not summary_to_search.strip():
        logger.warning("Summary to search is empty. Aborting find similar issues.")
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, user=user_id, text="The conversation summary was empty, so I can't search for similar issues.")
        return
        
    try:
        # Inform user work is in progress
        client.chat_postMessage(
            channel=channel_id, 
            thread_ts=thread_ts, 
            text=f"Thanks, <@{user_id}>! Searching for JIRA tickets similar to the conversation summary..."
        )

        duplicate_results = find_and_summarize_duplicates(user_query=summary_to_search)
        top_tickets = duplicate_results.get("tickets", [])
        overall_summary = duplicate_results.get("summary", "Could not generate an overall summary for similar tickets.")

        response_blocks = []
        if top_tickets:
            response_blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"""Here are some existing JIRA tickets that might be related to the conversation:

{overall_summary}"""}
            })
            response_blocks.append({"type": "divider"})
            for ticket in top_tickets:
                ticket_id = ticket.get("metadata", {}).get("ticket_id", "Unknown ID")
                ticket_url = ticket.get("metadata", {}).get("url")
                ticket_desc_snippet = ticket.get("page_content", "No content available.")[:200] # Langchain Document content
                
                link_md = f"*{ticket_id}*"
                if ticket_url:
                    link_md = f"*<{ticket_url}|{ticket_id}>*"

                response_blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"""{link_md}:
>{ticket_desc_snippet}..."""}
                })
            response_blocks.append({"type": "divider"})
        else:
            response_blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"""I searched based on the conversation summary, but couldn't find any closely matching JIRA tickets.

Summary I used for search:
>>> {summary_to_search}"""}
            })
        
        response_blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "You can still choose to create a new ticket if needed."}
        })


        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=response_blocks,
            text="Here are the results of the similarity search."
        )
        logger.info(f"Posted similar tickets results for mention flow in thread {thread_ts}")

    except Exception as e:
        logger.error(f"Error during mention_flow_find_issues: {e}", exc_info=True)
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, user=user_id, text="Sorry, I encountered an error while searching for similar issues.")


# --- View Handlers ---
@app.view("create_ticket_modal")
def handle_modal_submission(ack, body, client, view, logger):
    # This is the generic modal submission handler. It needs to be robust.
    # The private_metadata should guide which flow this submission belongs to.
    private_metadata_str = view.get("private_metadata")
    logger.info(f"Modal submitted. Private metadata: {private_metadata_str}")

    # Default values in case metadata parsing fails or state is missing
    user_id = body["user"]["id"] # User who submitted the modal
    # channel_id/thread_ts for posting back might not be in basic modal body, rely on state
    
    state_data = conversation_states.get(private_metadata_str)

    if not state_data:
        ack_text = "Error: Couldn't find context for this submission. Please try starting over."
        logger.error(f"No state found for private_metadata_key: {private_metadata_str} in modal submission.")
        ack(response_action="errors", errors={"title": ack_text}) # Or a more specific field
        # Optionally post an ephemeral message to the user if possible, though channel/thread unknown here.
        return

    # Extract necessary info from state_data
    submission_channel_id = state_data.get("channel_id")
    submission_thread_ts = state_data.get("thread_ts")
    # initial_description = state_data.get("initial_description") # This might be the summary from mention flow
    # or description from direct creation flow. The modal has the final description.
    
    # Extract values from the modal submission
    submitted_values = view["state"]["values"]
    jira_title = submitted_values["title_input_block"]["title_input_action"]["value"]
    jira_description = submitted_values["description_input_block"]["description_input_action"]["value"]
    # Optional: project_id, issue_type_id if they were in the modal

    logger.info(f"Modal submission by {user_id} for state key {private_metadata_str}: Title='{jira_title}', Desc='{jira_description[:50]}...'")

    # Handle the actual Jira ticket creation
    ack() # Acknowledge the view submission immediately

    try:
        # Call your existing Jira creation service
        # Assuming create_jira_ticket takes title and description
        # You might need project and issue type if your modal collects them
        # For now, using hardcoded project/issue type as an example, replace with modal values if available
        project_key = "PROJECT_KEY_PLACEHOLDER" # Replace with actual or from modal
        issue_type_name = "Task" # Replace with actual or from modal

        created_ticket_info = create_jira_ticket(
            summary=jira_title, 
            description=jira_description,
            project_key=project_key, # TODO: Get from modal or config
            issue_type_name=issue_type_name # TODO: Get from modal or config
        )

        if created_ticket_info and "key" in created_ticket_info and "url" in created_ticket_info:
            ticket_key = created_ticket_info["key"]
            ticket_url = created_ticket_info["url"]
            confirmation_message = f"✅ Great! I've created Jira ticket <{ticket_url}|{ticket_key}> for you: *{jira_title}*"
            logger.info(f"Successfully created Jira ticket {ticket_key} from modal submission.")
        else:
            confirmation_message = "⚠️ I tried to create the Jira ticket, but something went wrong. I didn't get the ticket details back."
            logger.error(f"Failed to create Jira ticket or parse response. create_jira_ticket response: {created_ticket_info}")

    except Exception as e:
        logger.error(f"Error creating Jira ticket from modal: {e}", exc_info=True)
        confirmation_message = f"❌ Sorry, there was an error creating the Jira ticket: {e}"

    # Post confirmation to the original thread/channel
    if submission_channel_id: # Should always be present if state_data was found
        try:
            client.chat_postMessage(
                channel=submission_channel_id,
                thread_ts=submission_thread_ts, # Post in thread if available
                text=confirmation_message
            )
        except Exception as e_post:
            logger.error(f"Failed to post ticket creation confirmation: {e_post}")
    else: # Should not happen if state is managed correctly
        logger.error("submission_channel_id missing in state_data, cannot post confirmation.")
        # Fallback: maybe an ephemeral message to the user if user_id is known and channel_id is not
        # client.chat_postEphemeral(user=user_id, channel=SOME_FALLBACK_CHANNEL, text=confirmation_message)


    # Clean up state for this modal interaction
    if private_metadata_str in conversation_states:
        del conversation_states[private_metadata_str]
        logger.info(f"Cleared state for modal key {private_metadata_str}")


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