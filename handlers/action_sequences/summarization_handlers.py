import logging
import json
from slack_sdk.errors import SlackApiError
from utils.state_manager import conversation_states
from services.duplicate_detection_service import summarize_ticket_similarities
from langchain.schema import Document
from services.jira_service import fetch_jira_ticket_data
from services.summarize_service import summarize_jira_ticket
from utils.data_cleaner import prepare_ticket_data_for_summary

logger = logging.getLogger(__name__)

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
            text="Okay, let\'s summarize a Jira ticket. Please provide the Ticket ID (e.g., PROJ-123) or the full Jira link."
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

def handle_summarize_individual_duplicates_from_message(ack, body, client, logger):
    """Handles 'Summarize Individual Tickets' from the duplicate check message."""
    ack()
    logger.info("'Summarize Individual Tickets' button clicked.")

    try:
        action_value = json.loads(body["actions"][0]["value"])
        user_query = action_value["user_query"]
        tickets_data = action_value["tickets_data"]
        original_context = action_value["original_context"]

        thread_ts = str(original_context["thread_ts"])
        channel_id = str(original_context["channel_id"])
        # assistant_id = str(original_context.get("assistant_id")) if original_context.get("assistant_id") else None # assistant_id not used here

        logger.info(f"Thread {thread_ts}: Summarizing {len(tickets_data)} individual tickets for query: '{user_query[:50]}...'")

        if not tickets_data:
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text="No specific tickets were provided to summarize.")
            return

        header_posted = False
        for i, ticket_data_dict in enumerate(tickets_data):
            if not header_posted:
                 client.chat_postMessage(
                    channel=channel_id, 
                    thread_ts=thread_ts, 
                    text=f"📝 Here are individual summaries for the top tickets based on your query: '{user_query[:50]}...'"
                )
                 header_posted = True

            doc_to_summarize = Document(page_content=ticket_data_dict["page_content"], metadata=ticket_data_dict.get("metadata", {}))
            ticket_id_display = ticket_data_dict.get("metadata", {}).get("ticket_id", f"Ticket {i+1}")
            ticket_url_display = ticket_data_dict.get("metadata", {}).get("url")
            
            display_name = f"*{ticket_id_display}*"
            if ticket_url_display:
                display_name = f"*<{ticket_url_display}|{ticket_id_display}>*"

            individual_summary = summarize_ticket_similarities(query=user_query, tickets=[doc_to_summarize])
            
            summary_blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Summary for {display_name}:*\n{individual_summary}"}},
                {"type": "divider"}
            ]
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, blocks=summary_blocks, text=f"Summary for {ticket_id_display}")
            logger.info(f"Thread {thread_ts}: Posted individual summary for {ticket_id_display}.")

        final_cta_blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "What would you like to do next?"}},
            {
                "type": "actions", 
                "elements": [
                    {
                        "type": "button", 
                        "text": {"type": "plain_text", "text": "Proceed with Original Description"}, 
                        "style": "primary", 
                        "action_id": "proceed_to_ai_title_suggestion", 
                        "value": json.dumps(original_context)
                    },
                    {
                        "type": "button", 
                        "text": {"type": "plain_text", "text": "Cancel Creation"}, 
                        "style": "danger", 
                        "action_id": "cancel_creation_at_message_duplicates",
                        "value": json.dumps({"thread_ts": thread_ts}) # Only thread_ts needed for cancellation context
                    }
                ]
            }
        ]
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, blocks=final_cta_blocks, text="What would you like to do next?")
        logger.info(f"Thread {thread_ts}: Posted final CTAs after individual summaries.")

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from button value in handle_summarize_individual: {e}")
    except KeyError as e:
        logger.error(f"Missing key in button value in handle_summarize_individual: {e}")
    except SlackApiError as e:
        logger.error(f"Slack API error in handle_summarize_individual: {e.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_summarize_individual: {e}", exc_info=True)

def handle_summarize_specific_duplicate_ticket(ack, body, client, logger):
    """Handles the action when a user clicks 'Summarize this ticket' for a specific duplicate."""
    ack()
    logger.info(f"handle_summarize_specific_duplicate_ticket: Action received: {body['actions'][0]['value']}")
    
    assistant_id = None # Initialize to handle potential errors before assignment
    thread_ts = None # Initialize for finally block

    try:
        action_value = json.loads(body['actions'][0]['value'])
        ticket_id_to_summarize = action_value.get("ticket_id_to_summarize")
        thread_ts = action_value.get("thread_ts")
        channel_id = action_value.get("channel_id")
        user_id = action_value.get("user_id") # user_id who requested the summary
        assistant_id = action_value.get("assistant_id")

        if not all([ticket_id_to_summarize, thread_ts, channel_id, user_id]): # Added user_id check
            logger.error(f"Missing critical info in action_value: {action_value}")
            # Ensure body has user and channel for ephemeral message fallback
            ephemeral_channel_id = channel_id or body.get("channel", {}).get("id")
            ephemeral_user_id = body.get("user", {}).get("id")
            ephemeral_thread_ts = thread_ts or body.get("message",{}).get("thread_ts") or body.get("container",{}).get("thread_ts")

            if ephemeral_channel_id and ephemeral_user_id:
                client.chat_postEphemeral(
                    channel=ephemeral_channel_id,
                    user=ephemeral_user_id,
                    thread_ts=ephemeral_thread_ts,
                    text="Sorry, something went wrong while trying to summarize that ticket. Essential information was missing."
                )
            return

        logger.info(f"Thread {thread_ts}: Attempting to summarize specific ticket: {ticket_id_to_summarize} for user {user_id}")

        if assistant_id:
            try:
                client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status=f"Summarizing {ticket_id_to_summarize}...")
                logger.info(f"Thread {thread_ts}: Set status to 'Summarizing {ticket_id_to_summarize}...'")
            except Exception as e:
                logger.error(f"Thread {thread_ts}: Error setting status for specific ticket summary: {e}")
        
        raw_jira_issue = fetch_jira_ticket_data(ticket_id_to_summarize)
        if not raw_jira_issue:
            logger.warning(f"Thread {thread_ts}: Could not fetch data for ticket {ticket_id_to_summarize}.")
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"Sorry, I couldn\'t fetch data for ticket *{ticket_id_to_summarize}*. It might not exist, or there was an API error."
            )
            return

        summary_relevant_data = None
        if hasattr(raw_jira_issue, 'raw') and raw_jira_issue.raw:
            summary_relevant_data = prepare_ticket_data_for_summary(raw_jira_issue.raw, ticket_id_to_summarize)
        else:
            logger.error(f"Thread {thread_ts}: Fetched Jira issue for {ticket_id_to_summarize} is missing .raw attribute or it is empty.")

        if not summary_relevant_data:
            logger.error(f"Thread {thread_ts}: Failed to prepare data for {ticket_id_to_summarize} for summarization.")
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"Sorry, there was an error processing the data for ticket *{ticket_id_to_summarize}* before summarization."
            )
            return

        summary_result = summarize_jira_ticket(summary_relevant_data)
        if not summary_result:
            logger.error(f"Thread {thread_ts}: Failed to generate summary for {ticket_id_to_summarize}.")
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"Sorry, an error occurred while trying to generate a summary for ticket *{ticket_id_to_summarize}*."
            )
            return

        summary_text = (
            f"Here is a summary for ticket *{ticket_id_to_summarize}* (requested by <@{user_id}>):\n\n"
            f"*Status*: {summary_result.get('status', 'N/A')}\n"
            f"*Issue*: {summary_result.get('issue_summary', 'N/A')}\n"
            f"*Resolution/Next Steps*: {summary_result.get('resolution_summary', 'N/A')}"
        )
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=summary_text
        )
        logger.info(f"Thread {thread_ts}: Posted summary for specific ticket {ticket_id_to_summarize}.")

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from action value: {e}. Value: {body['actions'][0]['value']}")
        # Fallback for posting ephemeral message if channel_id/thread_ts not in parsed action_value
        ephemeral_channel_id = body.get("channel", {}).get("id")
        ephemeral_user_id = body.get("user", {}).get("id")
        ephemeral_thread_ts = body.get("message",{}).get("thread_ts") or body.get("container",{}).get("thread_ts")
        if ephemeral_channel_id and ephemeral_user_id:
             client.chat_postEphemeral(
                channel=ephemeral_channel_id,
                user=ephemeral_user_id,
                thread_ts=ephemeral_thread_ts,
                text="Sorry, there was a technical issue processing your request. Please try again."
            )
    except Exception as e:
        logger.error(f"General error in handle_summarize_specific_duplicate_ticket: {e}", exc_info=True)
        action_value_str = "Not available"
        try:
            action_value_str = body['actions'][0]['value']
            parsed_value = json.loads(action_value_str)
            ch_id = parsed_value.get("channel_id")
            th_ts = parsed_value.get("thread_ts")
            if ch_id and th_ts: # Check if th_ts (thread_ts) is available from parsed value
                 client.chat_postMessage(
                    channel=ch_id,
                    thread_ts=th_ts,
                    text="An unexpected error occurred while trying to summarize the ticket. Please check the logs."
                )
            else: # Fallback to body if not in action_value
                ch_id_body = body.get("channel", {}).get("id")
                th_ts_body = body.get("message",{}).get("thread_ts") or body.get("container",{}).get("thread_ts")
                if ch_id_body and th_ts_body:
                    client.chat_postMessage(
                        channel=ch_id_body,
                        thread_ts=th_ts_body,
                        text="An unexpected error occurred. Could not determine context to post full error."
                    )
        except Exception as inner_e:
            logger.error(f"Could not parse action_value ('{action_value_str}') to send error message to thread. Inner error: {inner_e}")
    finally:
        if assistant_id and thread_ts: 
            try:
                client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
                logger.info(f"Thread {thread_ts}: Cleared status after specific ticket summary attempt.")
            except Exception as se:
                logger.error(f"Thread {thread_ts}: Error clearing status after specific ticket summary attempt: {se}") 