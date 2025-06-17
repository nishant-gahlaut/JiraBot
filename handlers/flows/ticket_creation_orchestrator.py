import logging
import json
from slack_sdk.errors import SlackApiError

from services.duplicate_detection_service import find_and_summarize_duplicates
from utils.slack_ui_helpers import get_issue_type_emoji, get_priority_emoji, build_rich_ticket_blocks
# conversation_states is not directly manipulated here, only context passed through button values

logger = logging.getLogger(__name__)

def present_duplicate_check_and_options(client, channel_id: str, thread_ts: str, user_id: str, initial_description: str, assistant_id: str = None, pre_existing_title: str = None, pre_existing_description: str = None, ai_suggested_title: str | None = None, ai_refined_description: str | None = None, ai_priority: str | None = None, ai_issue_type: str | None = None):
    """
    Orchestrates the duplicate check process and presents results with standard CTAs.

    Args:
        client: The Slack client instance.
        channel_id: The ID of the channel where the interaction is happening.
        thread_ts: The timestamp of the thread.
        user_id: The ID of the user who initiated the description/summary.
        initial_description: The text (user description or bot summary) to check for duplicates.
        assistant_id: Optional assistant ID for status updates.
        pre_existing_title: Optional existing title for the ticket.
        pre_existing_description: Optional existing description for the ticket.
        ai_suggested_title: Optional AI suggested title for the ticket.
        ai_refined_description: Optional AI refined description for the ticket.
        ai_priority: Optional AI priority for the ticket.
        ai_issue_type: Optional AI issue type for the ticket.
    """
    logger.info(f"Thread {thread_ts}: Orchestrator - Starting duplicate check for user {user_id} with description: '{initial_description[:100]}...'")

    try:
        if assistant_id:
            try:
                client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="Checking for similar tickets...")
                logger.info(f"Thread {thread_ts}: Orchestrator - Set status to 'Checking for similar tickets...'")
            except Exception as e_status:
                logger.error(f"Thread {thread_ts}: Orchestrator - Error setting status before duplicate check: {e_status}")

        duplicate_results = find_and_summarize_duplicates(user_query=initial_description)
        
        top_tickets = duplicate_results.get("tickets", [])
        overall_similarity_summary = duplicate_results.get("summary", "Could not generate an overall summary for similar tickets.")
        logger.info(f"Thread {thread_ts}: Orchestrator - Duplicate detection found {len(top_tickets)} potential matches.")

        # Process title and description before adding to button context
        processed_title = ai_suggested_title
        if not ai_suggested_title or str(ai_suggested_title).strip().lower() == 'none':
            processed_title = None

        processed_description = ai_refined_description
        if not ai_refined_description:
            processed_description = initial_description

        button_context_value = {
            "initial_description": initial_description,
            "thread_ts": str(thread_ts),
            "channel_id": str(channel_id),
            "user_id": str(user_id),
            "assistant_id": str(assistant_id) if assistant_id else None,
            "title": processed_title,
            "description": processed_description,
            "priority": ai_priority,
            "issue_type": ai_issue_type,
            "summary_for_confirmation": initial_description
        }

        blocks_for_duplicates = []

        if top_tickets:
            for i, ticket_dict in enumerate(top_tickets):
                current_metadata = ticket_dict.get('metadata', {})
                
                ticket_key = current_metadata.get('ticket_id', f'Similar Ticket {i+1}')
                ticket_url = current_metadata.get('url')
                summary = current_metadata.get('summary', 'No summary available')
                status = current_metadata.get('status', 'Unknown')
                priority = current_metadata.get('priority', 'Unknown')
                assignee = current_metadata.get('assignee', 'Unassigned')
                issue_type = current_metadata.get('issue_type', 'Unknown')
                
                # Get description and resolution for display
                description_to_display = current_metadata.get('retrieved_problem_statement', '_No description available_')
                resolution_to_display = current_metadata.get('retrieved_solution_summary', '_Resolution not available_')

                ticket_data_for_helper = {
                    'ticket_key': ticket_key,
                    'summary': summary,
                    'url': ticket_url,
                    'status': status,
                    'priority': priority,
                    'assignee': assignee,
                    'issue_type': issue_type,
                    'description': description_to_display,
                    'resolution': resolution_to_display
                }

                action_elements_for_ticket = []
                
                rich_ticket_display_blocks = build_rich_ticket_blocks(ticket_data_for_helper, action_elements_for_ticket)
                blocks_for_duplicates.extend(rich_ticket_display_blocks)

        else:
            blocks_for_duplicates.append({"type": "section", "text": {"type": "mrkdwn", "text": "I didn't find any strong matches for existing tickets. You can proceed with creating a new one."}})

        # Standardized main action buttons
        main_action_buttons = [
            {"type": "button", "text": {"type": "plain_text", "text": "Continue Creating Ticket", "emoji": True}, "style": "primary", "action_id": "create_ticket_from_Bot_from_Looks_Good_Create_Ticket_Button_Action", "value": json.dumps(button_context_value)},
           
            {"type": "button", "text": {"type": "plain_text", "text": "Cancel Creation", "emoji": True}, "style": "danger", "action_id": "cancel_creation_at_message_duplicates", "value": json.dumps({"thread_ts": str(thread_ts), "user_id": str(user_id), "channel_id": str(channel_id)})}
        ]
        blocks_for_duplicates.append({"type": "actions", "elements": main_action_buttons})

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=blocks_for_duplicates,
            text="Found potential duplicate tickets."
        )
        logger.info(f"Thread {thread_ts}: Orchestrator - Posted duplicate ticket suggestions and actions.")

    except SlackApiError as e_slack:
        logger.error(f"Thread {thread_ts}: Orchestrator - Slack API Error: {e_slack}", exc_info=True)
        # Try to inform the user in the thread
        try:
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=f"Sorry, I encountered a Slack API error while checking for similar tickets. Please try again.")
        except Exception as e_post_err:
            logger.error(f"Thread {thread_ts}: Orchestrator - Failed to post Slack API error message to user: {e_post_err}")
    except Exception as e:
        logger.error(f"Thread {thread_ts}: Orchestrator - Unexpected error: {e}", exc_info=True)
        # Try to inform the user in the thread
        try:
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=f"Sorry, an unexpected error occurred while checking for similar tickets. Please try again.")
        except Exception as e_post_err:
            logger.error(f"Thread {thread_ts}: Orchestrator - Failed to post unexpected error message to user: {e_post_err}")
    finally:
        if assistant_id:
            try:
                client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
                logger.info(f"Thread {thread_ts}: Orchestrator - Cleared status after duplicate check attempt.")
            except Exception as se:
                logger.error(f"Thread {thread_ts}: Orchestrator - Error clearing status: {se}") 