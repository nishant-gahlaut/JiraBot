# message_handler.py
import logging

# Import dependencies from new locations
# from state_manager import conversation_states # Old
# from genai_handler import generate_jira_details # Old
# from jira_handler import extract_ticket_id_from_input, fetch_jira_ticket_data # Old
# from summarize_handler import summarize_jira_ticket # Old

from utils.state_manager import conversation_states
from services.genai_service import generate_jira_details
from services.jira_service import extract_ticket_id_from_input, fetch_jira_ticket_data
from services.summarize_service import summarize_jira_ticket
from utils.data_cleaner import clean_jira_data
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
            current_state = conversation_states.get(thread_ts)
            logger.info(f"Checking state for thread {thread_ts}: {current_state}")

            # --- Handle Summary Input (From Create Ticket Flow) ---
            # REMOVED - Now handled by modal
            # if current_state and current_state["step"] == "awaiting_summary":
                # ... (removed logic) ...

            # --- Handle Initial Summary/Description Input (NEW Create Ticket Flow Start) ---
            if current_state and current_state["step"] == "awaiting_initial_summary":
                user_text = text
                logger.info(f"Thread {thread_ts} is in 'awaiting_initial_summary' state. Processing text: '{user_text}'")

                # Set status while processing with GenAI
                if assistant_id:
                    try:
                        client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="Generating suggestion...")
                        logger.info("Set status to 'Generating suggestion...'")
                    except Exception as e:
                        logger.error(f"Error setting status before GenAI for initial summary: {e}")

                # Call GenAI to get *suggested title* based on user description
                # Treat user text as the initial description
                # We assume generate_jira_details returns at least a 'title'
                generated_details = generate_jira_details(user_text) # Use the full text
                suggested_title = generated_details.get("title", "Suggestion Error") 
                initial_description = user_text # User's input is the description

                # Store data and update state
                current_state["data"]["initial_description"] = initial_description
                current_state["data"]["suggested_title"] = suggested_title
                current_state["step"] = "awaiting_ai_confirmation"
                conversation_states[thread_ts] = current_state
                logger.info(f"Updated state for thread {thread_ts} to 'awaiting_ai_confirmation' with data: {{'suggested_title': '{suggested_title}', 'initial_description': Truncated}}")

                # Prepare confirmation response with buttons
                ai_confirmation_blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"Thanks! Based on your description, I suggest the following:\n\n*Suggested Title:* {suggested_title}\n\n*Your Description:*```{initial_description}```\n\nWould you like to proceed with these details or modify them?"
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

                try:
                    client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        blocks=ai_confirmation_blocks,
                        text=f"Suggested Title: {suggested_title}" # Fallback
                    )
                    logger.info(f"Posted AI suggestion confirmation to thread {thread_ts}")
                    # Status is cleared by message post
                except Exception as e:
                    logger.error(f"Error posting AI confirmation message: {e}")
                    # Clear status on error
                    if assistant_id:
                        try: client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
                        except Exception as se: logger.error(f"Error clearing status after AI confirmation post failure: {se}")

            # --- Handle Assignee Input (From Create Ticket Flow) ---
            # REMOVED - Now handled by modal
            # elif current_state and current_state["step"] == "awaiting_assignee":
                # ... (removed logic) ...

            # --- Handle Ticket ID/URL Input (From Summarize Ticket Flow) ---
            if current_state and current_state["step"] == "awaiting_summary_input": # Changed from elif to if
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
                    jira_data = fetch_jira_ticket_data(ticket_id)
                    if not jira_data:
                        try:
                            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=f"Sorry, I couldn't fetch data for ticket '{ticket_id}'. It might not exist, or there was an error. (Placeholder response)")
                            logger.warning(f"Failed to fetch Jira data for {ticket_id} in thread {thread_ts}")
                        except Exception as e:
                            logger.error(f"Error posting data fetch failure message: {e}")
                    else:
                        # Clean the fetched data
                        cleaned_data = clean_jira_data(jira_data)
                        
                        if not cleaned_data:
                            # Handle cleaning error
                            logger.error(f"Failed to clean Jira data for {ticket_id} in thread {thread_ts}")
                            try:
                                client.chat_postMessage(
                                    channel=channel_id,
                                    thread_ts=thread_ts,
                                    text=f"Sorry, there was an error processing the data for ticket '{ticket_id}'."
                                )
                            except Exception as e:
                                logger.error(f"Error posting data cleaning failure message: {e}")
                        else:
                            # Summarize Cleaned Data (Placeholder)
                            # Pass cleaned_data instead of jira_data
                            summary_result = summarize_jira_ticket(cleaned_data)
    
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

            else:
                # Handle messages not part of a known flow or without state
                logger.info(f"Thread {thread_ts} not in a recognized state or no state found. Sending generic response.")
                try:
                    client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=f"Received: '{text}'. Please use the initial buttons or follow the current prompt."
                    )
                    logger.info(f"Sent generic non-flow response to thread {thread_ts}")
                except Exception as e:
                    logger.error(f"Error posting generic message: {e}")
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