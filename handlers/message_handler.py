# message_handler.py
import logging
import json # Added for button value serialization

# Import dependencies from new locations
# from state_manager import conversation_states # Old
# from genai_handler import generate_jira_details # Old
# from jira_handler import extract_ticket_id_from_input, fetch_jira_ticket_data # Old
# from summarize_handler import summarize_jira_ticket # Old

from utils.state_manager import conversation_states
from services.genai_service import generate_jira_details
from services.jira_service import extract_ticket_id_from_input, fetch_jira_ticket_data
from services.summarize_service import summarize_jira_ticket
from utils.data_cleaner import prepare_ticket_data_for_summary
from services.duplicate_detection_service import find_and_summarize_duplicates # New import for duplicate detection
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

def handle_message(message, client, context, logger):
    """Handles incoming message events based on conversation state."""
    # Check if it's a direct message (IM) and not from the bot itself
    if message.get("channel_type") == "im" and "bot_id" not in message:
        logger.info(f"Received message.im event: {message}")
        channel_id = message["channel"]
        user_id = message["user"]
        text = message.get("text", "")
        thread_ts = message.get("thread_ts") # Important for threading in assistant container
        assistant_id = context.get("assistant_id") # Get assistant_id from context

        # Process only if it's within an assistant thread
        if thread_ts:
            current_state = conversation_states.get(str(thread_ts)) # Ensure thread_ts is string for dict key
            logger.info(f"Thread {thread_ts}: Checking state: {current_state}")

            # --- Handle Initial Summary/Description Input (NEW Create Ticket Flow Start) ---
            if current_state and current_state.get("step") == "awaiting_initial_summary":
                user_text = text # This is the initial description from the user
                logger.info(f"Thread {thread_ts}: State is 'awaiting_initial_summary'. Processing description: '{user_text[:100]}...'" )

                original_user_id = str(current_state.get("user_id", user_id))
                original_channel_id = str(current_state.get("channel_id", channel_id))
                original_assistant_id = str(current_state.get("assistant_id", assistant_id)) if current_state.get("assistant_id") else (str(assistant_id) if assistant_id else None)

                if original_assistant_id:
                    try:
                        client.assistant_threads_setStatus(assistant_id=original_assistant_id, thread_ts=thread_ts, status="Checking for similar tickets...")
                        logger.info(f"Thread {thread_ts}: Set status to 'Checking for similar tickets...'" )
                    except Exception as e:
                        logger.error(f"Thread {thread_ts}: Error setting status before duplicate check: {e}")

                logger.info(f"Thread {thread_ts}: Calling find_and_summarize_duplicates for query: '{user_text[:100]}...'" )
                duplicate_results = find_and_summarize_duplicates(user_query=user_text)
                top_tickets = duplicate_results.get("top_tickets", [])
                overall_summary = duplicate_results.get("summary", "Could not generate an overall summary for similar tickets.")
                logger.info(f"Thread {thread_ts}: Duplicate detection found {len(top_tickets)} potential matches." )

                button_context_value = {
                    "initial_description": user_text,
                    "thread_ts": str(thread_ts),
                    "channel_id": original_channel_id,
                    "user_id": original_user_id,
                    "assistant_id": original_assistant_id
                }

                blocks_for_duplicates = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"<@{original_user_id}>, thanks for the description. Before we proceed, I found some tickets that might be similar to your request:"
                        }
                    }
                ]

                if top_tickets:
                    for i, doc in enumerate(top_tickets):
                        ticket_id_meta = doc.metadata.get('ticket_id', f'Similar Ticket {i+1}')
                        ticket_url_meta = doc.metadata.get('url')
                        preview_text = doc.page_content[:150].replace('\n', ' ') + "..."
                        ticket_display_text = f"*{ticket_id_meta}*"
                        if ticket_url_meta:
                            ticket_display_text = f"*<{ticket_url_meta}|{ticket_id_meta}>*"
                        blocks_for_duplicates.extend([
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"{ticket_display_text}\n*Preview:* {preview_text}"
                                }
                            },
                            {"type": "divider"}
                        ])
                    if overall_summary:
                        blocks_for_duplicates.append({
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f"""*Overall Similarity Summary:*\n{overall_summary}"""}
                        })
                else:
                    blocks_for_duplicates.append({
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "I didn't find any strong matches for existing tickets. You can proceed with creating a new one."}
                    })

                action_buttons = [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Proceed with this Description", "emoji": True},
                        "style": "primary",
                        "action_id": "proceed_to_ai_title_suggestion",
                        "value": json.dumps(button_context_value)
                    }
                ]
                if top_tickets: # Only add summarize button if there are tickets
                    action_buttons.append({
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Summarize Individual Tickets", "emoji": True},
                        "action_id": "summarize_individual_duplicates_message_step",
                        "value": json.dumps({
                            "user_query": user_text,
                            "tickets_data": [{'metadata': t.metadata, 'page_content': t.page_content} for t in top_tickets],
                            "original_context": button_context_value
                        }),
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Are you sure?"},
                            "text": {"type": "mrkdwn", "text": f"This will post {len(top_tickets)} individual summary message(s) for the found tickets."},
                            "confirm": {"type": "plain_text", "text": "Yes, Summarize"},
                            "deny": {"type": "plain_text", "text": "Cancel"}
                        }
                    })
                
                action_buttons.extend([
                     {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Refine My Description", "emoji": True},
                        "action_id": "refine_description_after_duplicates",
                        "value": json.dumps(button_context_value) # Pass context for restarting
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Cancel Creation", "emoji": True},
                        "style": "danger",
                        "action_id": "cancel_creation_at_message_duplicates",
                        "value": json.dumps({"thread_ts": str(thread_ts)})
                    }
                ])
                
                blocks_for_duplicates.append({"type": "actions", "elements": action_buttons})

                try:
                    client.chat_postMessage(
                        channel=original_channel_id,
                        thread_ts=thread_ts,
                        blocks=blocks_for_duplicates,
                        text="Found potential duplicate tickets."
                    )
                    logger.info(f"Thread {thread_ts}: Posted duplicate ticket suggestions and actions." )
                except Exception as e:
                    logger.error(f"Thread {thread_ts}: Error posting duplicate ticket suggestions message: {e}")
                finally:
                    if original_assistant_id:
                        try:
                            client.assistant_threads_setStatus(assistant_id=original_assistant_id, thread_ts=thread_ts, status="")
                            logger.info(f"Thread {thread_ts}: Cleared status after duplicate check." )
                        except Exception as se:
                            logger.error(f"Thread {thread_ts}: Error clearing status after duplicate check: {se}")
                
                if str(thread_ts) in conversation_states:
                    del conversation_states[str(thread_ts)]
                    logger.info(f"Thread {thread_ts}: Cleared 'awaiting_initial_summary' state after posting duplicate info." )

            # --- Handle Ticket ID/URL Input (From Summarize Ticket Flow) ---
            elif current_state and current_state.get("step") == "awaiting_summary_input": # Make sure this is an elif or a separate if with a different state condition
                user_input = text
                logger.info(f"Thread {thread_ts} is in 'awaiting_summary_input' state. Processing input: '{user_input}'")
                # Set status
                if assistant_id:
                     try:
                         client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="Processing ticket...")
                         logger.info("Set status to 'Processing ticket...'")
                     except Exception as e:
                         logger.error(f"Error setting status for summary processing: {e}")

                ticket_id = extract_ticket_id_from_input(user_input)

                if not ticket_id:
                    try:
                        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=f"Sorry, I couldn't recognize a valid Jira Ticket ID (like PROJ-123) in your message: '{user_input}'. Please try again.")
                        logger.warning(f"Invalid summary input format for thread {thread_ts}")
                    except Exception as e:
                        logger.error(f"Error posting invalid summary input message: {e}")
                    if assistant_id:
                          try:
                              client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
                          except Exception as se: logger.error(f"Error clearing status after invalid input: {se}")
                else:
                    # Fetch the raw Jira issue object
                    raw_jira_issue = fetch_jira_ticket_data(ticket_id)
                    
                    if not raw_jira_issue:
                        try:
                            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=f"Sorry, I couldn't fetch data for ticket '{ticket_id}'. It might not exist, or there was an error.")
                            logger.warning(f"Failed to fetch Jira data for {ticket_id} in thread {thread_ts}")
                        except Exception as e:
                            logger.error(f"Error posting data fetch failure message: {e}")
                    else:
                        # Prepare the data for summarization using the new function
                        # It expects issue.raw and the ticket_id
                        summary_relevant_data = None
                        if hasattr(raw_jira_issue, 'raw') and raw_jira_issue.raw:
                            summary_relevant_data = prepare_ticket_data_for_summary(raw_jira_issue.raw, ticket_id)
                        else:
                            logger.error(f"Fetched Jira issue for {ticket_id} is missing .raw attribute or it is empty.")
                        
                        if not summary_relevant_data:
                            # Handle cleaning/preparation error
                            logger.error(f"Failed to prepare Jira data for summarization for {ticket_id} in thread {thread_ts}")
                            try:
                                client.chat_postMessage(
                                    channel=channel_id,
                                    thread_ts=thread_ts,
                                    text=f"Sorry, there was an error processing the data for ticket '{ticket_id}'."
                                )
                            except Exception as e:
                                logger.error(f"Error posting data preparation failure message: {e}")
                        else:
                            # Summarize the prepared data
                            summary_result = summarize_jira_ticket(summary_relevant_data)
    
                            if not summary_result:
                                # Handle summarization error
                                try:
                                    client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=f"Sorry, there was an error generating the summary for ticket '{ticket_id}'.")
                                    logger.error(f"Failed to summarize Jira data for {ticket_id} in thread {thread_ts}")
                                except Exception as e:
                                    logger.error(f"Error posting summarization failure message: {e}")
                            else:
                                summary_text = (
                                    f"Here is a summary for ticket *{ticket_id}*:\n\n"
                                    f"*Status*: {summary_result.get('status', 'N/A')}\n"
                                    f"*Issue*: {summary_result.get('issue_summary', 'N/A')}\n"
                                    f"*Resolution/Next Steps*: {summary_result.get('resolution_summary', 'N/A')}"
                                )
                                try:
                                    client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=summary_text)
                                    logger.info(f"Posted summary for {ticket_id} to thread {thread_ts}")
                                except Exception as e:
                                    logger.error(f"Error posting summary message: {e}")

                    # Clear state and status for summarization flow
                    if thread_ts in conversation_states:
                        del conversation_states[thread_ts]
                        logger.info(f"Cleared state for summarization thread {thread_ts}")
                    if assistant_id:
                        try:
                            client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
                        except Exception as se: logger.error(f"Error clearing status after summary processing: {se}")

            # Fallback for other states or no recognized state in a thread
            elif current_state:
                 logger.info(f"Thread {thread_ts} in unhandled state: {current_state.get('step')}. User text: '{text[:50]}...'" )
                 # Consider if a generic response is needed or just log
            else: # No current_state for this thread_ts
                logger.info(f"Thread {thread_ts}: No active state. User text: '{text[:50]}...'. Ignoring or generic response.")
                # ... (existing logic for messages not part of a known flow or no state)
        else:
            # Handle messages outside the assistant thread (no thread_ts)
            logger.warning(f"Received message without thread_ts from user {user_id} in channel {channel_id}. Cannot process without thread context.")
            # Optionally send a non-threaded reply if desired, but often ignored in assistant context.
            # try:
            #     client.chat_postMessage(channel=channel_id, text="Please interact via the Assistant thread.")
            # except Exception as e:
            #     logger.error(f"Error posting non-threaded message: {e}")
    else:
        # Message is not an IM or is from the bot itself, ignore.
        pass # Or log if needed 