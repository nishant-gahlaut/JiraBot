import logging
import json
from slack_sdk.errors import SlackApiError

from services.duplicate_detection_service import find_and_summarize_duplicates
# conversation_states is not directly manipulated here, only context passed through button values

logger = logging.getLogger(__name__)

def present_duplicate_check_and_options(client, channel_id: str, thread_ts: str, user_id: str, initial_description: str, assistant_id: str = None):
    """
    Orchestrates the duplicate check process and presents results with standard CTAs.

    Args:
        client: The Slack client instance.
        channel_id: The ID of the channel where the interaction is happening.
        thread_ts: The timestamp of the thread.
        user_id: The ID of the user who initiated the description/summary.
        initial_description: The text (user description or bot summary) to check for duplicates.
        assistant_id: Optional assistant ID for status updates.
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

        # Prepare context for the CTA buttons
        button_context_value = {
            "initial_description": initial_description,
            "thread_ts": str(thread_ts),
            "channel_id": str(channel_id),
            "user_id": str(user_id),
            "assistant_id": str(assistant_id) if assistant_id else None
        }

        blocks_for_duplicates = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<@{user_id}>, thanks for the description. Before we proceed, I found some tickets that might be similar to your request:"
                }
            }
        ]

        if top_tickets:
            for i, ticket_dict in enumerate(top_tickets):
                current_metadata = ticket_dict.get('metadata', {})
                page_content = ticket_dict.get('page_content', '')
                ticket_id_meta = current_metadata.get('ticket_id', f'Similar Ticket {i+1}')
                ticket_url_meta = current_metadata.get('url')
                preview_text = page_content[:150].replace('\n', ' ') + "..."
                ticket_display_text = f"*<{ticket_url_meta}|{ticket_id_meta}>*" if ticket_url_meta else f"*{ticket_id_meta}*"
                
                blocks_for_duplicates.extend([
                    {"type": "section", "text": {"type": "mrkdwn", "text": f"{ticket_display_text}\n*Preview:* {preview_text}"}},
                    {"type": "actions", "elements": [{
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Summarize this ticket", "emoji": True},
                        "action_id": "summarize_specific_duplicate_ticket",
                        "value": json.dumps({
                            "ticket_id_to_summarize": ticket_id_meta,
                            "thread_ts": str(thread_ts),
                            "channel_id": str(channel_id),
                            "user_id": str(user_id),
                            "assistant_id": str(assistant_id) if assistant_id else None
                        })
                    }]},
                    {"type": "divider"}
                ])
            if overall_similarity_summary:
                blocks_for_duplicates.append({"type": "section", "text": {"type": "mrkdwn", "text": f"""*Overall Similarity Summary:*\n{overall_similarity_summary}"""}})
        else:
            blocks_for_duplicates.append({"type": "section", "text": {"type": "mrkdwn", "text": "I didn't find any strong matches for existing tickets. You can proceed with creating a new one."}})

        # Standardized main action buttons
        main_action_buttons = [
            {"type": "button", "text": {"type": "plain_text", "text": "Continue Creating Ticket", "emoji": True}, "style": "primary", "action_id": "proceed_to_ai_title_suggestion", "value": json.dumps(button_context_value)},
            # {"type": "button", "text": {"type": "plain_text", "text": "Create Ticket Directly", "emoji": True}, "action_id": "proceed_directly_to_modal_no_ai", "value": json.dumps(button_context_value)},
            # For 'Refine Description', the action_id is 'refine_description_after_duplicates'. 
            # The text should be generic enough for both user description and bot summary contexts.
            # {"type": "button", "text": {"type": "plain_text", "text": "Refine Description", "emoji": True}, "action_id": "refine_description_after_duplicates", "value": json.dumps(button_context_value)},
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
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=f"<@{user_id}>, sorry, I encountered a Slack API error while checking for similar tickets. Please try again.")
        except Exception as e_post_err:
            logger.error(f"Thread {thread_ts}: Orchestrator - Failed to post Slack API error message to user: {e_post_err}")
    except Exception as e:
        logger.error(f"Thread {thread_ts}: Orchestrator - Unexpected error: {e}", exc_info=True)
        # Try to inform the user in the thread
        try:
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=f"<@{user_id}>, sorry, an unexpected error occurred while checking for similar tickets. Please try again.")
        except Exception as e_post_err:
            logger.error(f"Thread {thread_ts}: Orchestrator - Failed to post unexpected error message to user: {e_post_err}")
    finally:
        if assistant_id:
            try:
                client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
                logger.info(f"Thread {thread_ts}: Orchestrator - Cleared status after duplicate check attempt.")
            except Exception as se:
                logger.error(f"Thread {thread_ts}: Orchestrator - Error clearing status: {se}") 