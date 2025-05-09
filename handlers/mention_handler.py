import logging
import os
# import asyncio # No longer needed for direct sync conversion
from slack_sdk.errors import SlackApiError
import json # For storing complex data in button values if needed, or for logging

# Import the specific genai function and prompt
from services.genai_service import generate_text
from utils.prompts import SUMMARIZE_SLACK_THREAD_PROMPT
from utils.state_manager import conversation_states # Import for CTA handling
# from utils.state_manager import conversation_states # For CTA handling later

# Placeholder for conversation_states if needed for passing summary to modal
# from utils.state_manager import conversation_states 
# Placeholder for duplicate detection service
# from services.duplicate_detection_service import find_and_summarize_duplicates

logger = logging.getLogger(__name__)

MAX_MESSAGES_TO_FETCH = 20

def format_messages_for_summary(messages, client, limit=MAX_MESSAGES_TO_FETCH):
    """
    Formats a list of Slack message objects into a single string for summarization,
    including sender names.
    Orders messages oldest to newest before returning the tail end based on limit.
    """
    messages_text_list = []
    user_cache = {}

    # Ensure messages are processed oldest to newest if not already guaranteed by caller
    # For conversations_history, we reverse it before calling this.
    # For conversations_replies, it's already oldest to newest.

    for msg in messages: 
        if msg.get("user"): 
            user_id = msg.get("user")
            if user_id not in user_cache:
                try:
                    user_info_result = client.users_info(user=user_id)
                    user_cache[user_id] = user_info_result.get("user", {}).get("real_name") or user_info_result.get("user", {}).get("name", "Unknown User")
                except SlackApiError as e_user:
                    logger.error(f"Error fetching user info for {user_id}: {e_user}")
                    user_cache[user_id] = "Unknown User"
            
            user_name = user_cache[user_id]
            text = msg.get("text", "")
            if text.strip(): # Avoid empty messages
                messages_text_list.append(f"{user_name}: {text}")
        elif msg.get("bot_id") and msg.get("text", "").strip():
             # Optionally include bot messages if they have text and a username
             bot_name = msg.get("username", "Bot") 
             text = msg.get("text", "")
             if text.strip(): # Ensure bot message has content
                messages_text_list.append(f"{bot_name}: {text}")

    # Return the last 'limit' formatted messages
    # If messages_text_list has fewer than limit items, it returns all of them.
    final_formatted_string = "\n".join(messages_text_list[-limit:])
    logger.info(f"Formatted {len(messages_text_list)} messages into a string for summary, using tail {limit}. Preview: {final_formatted_string[:100]}...")
    return final_formatted_string

def fetch_conversation_context_for_mention(client, event_payload, limit=MAX_MESSAGES_TO_FETCH):
    """
    Fetches conversation context based on the app_mention event.
    - If in a thread, fetches thread replies.
    - If a top-level mention, fetches channel history leading up to the mention.
    Returns a formatted string of messages for summarization.
    """
    channel_id = event_payload.get("channel")
    message_ts = event_payload.get("ts")         # Timestamp of the mention message itself
    thread_parent_ts = event_payload.get("thread_ts") # Timestamp of the parent message, if in a thread

    fetched_messages = []

    try:
        if thread_parent_ts:
            # Mention is in an existing thread (thread_parent_ts is the first message in the thread)
            logger.info(f"Mention is in thread {thread_parent_ts}. Fetching thread replies for channel {channel_id}.")
            result = client.conversations_replies(
                channel=channel_id, 
                ts=thread_parent_ts, 
                limit=limit,
                inclusive=True # Ensure the parent message of the thread is included
            )
            # conversations_replies returns messages oldest first by default.
            fetched_messages = result.get('messages', [])
            logger.debug(f"Fetched {len(fetched_messages)} messages from thread {thread_parent_ts}.")
        else:
            # Mention is a top-level message or starts a new thread.
            # Fetch recent channel history UP TO AND INCLUDING the mention message.
            logger.info(f"Mention is top-level in channel {channel_id} (message_ts: {message_ts}). Fetching channel history.")
            result = client.conversations_history(
                channel=channel_id, 
                limit=limit, 
                latest=message_ts, # Fetch messages up to this timestamp (exclusive by default, but inclusive=True makes it inclusive)
                inclusive=True     # Include the message at 'latest' timestamp (the mention itself)
            )
            # conversations_history returns messages newest first by default.
            raw_messages = result.get('messages', [])
            fetched_messages = list(reversed(raw_messages)) # Reverse to get oldest first for consistent processing
            logger.debug(f"Fetched {len(fetched_messages)} messages from channel {channel_id} history (reversed to oldest first).")
        
        if not fetched_messages:
            logger.warning("No messages were fetched for context.")
            return ""

        # Format these messages
        return format_messages_for_summary(fetched_messages, client, limit)

    except SlackApiError as e:
        logger.error(f"Slack API error fetching conversation context: {e}")
        return ""
    except Exception as e_gen:
        logger.error(f"Generic error fetching conversation context: {e_gen}", exc_info=True)
        return ""

def summarize_conversation(conversation_history: str):
    """
    Summarizes the conversation history using GenAI service (generate_text).
    Synchronous version.
    """
    if not conversation_history:
        logger.warning("Conversation history is empty. Cannot summarize.")
        return "Could not fetch conversation history to summarize."
    
    logger.info(f"Preparing to summarize conversation: {conversation_history[:300]}...")
    prompt = SUMMARIZE_SLACK_THREAD_PROMPT.format(conversation_history=conversation_history)
    
    try:
        logger.debug("Calling generate_text for conversation summary.")
        summary = generate_text(prompt) 
        
        if "Error:" in summary:
            logger.error(f"GenAI service returned an error: {summary}")
            return f"Failed to generate summary due to an AI service error: {summary}"
            
        logger.info(f"Successfully generated summary: {summary[:200]}...")
        return summary
    except Exception as e:
        logger.error(f"Exception during GenAI call for summarization: {e}", exc_info=True)
        return "Error: Exception occurred while trying to generate the summary."

def post_summary_with_ctas(client, channel_id, thread_ts, summary: str, user_id: str):
    """
    Posts the summary and CTAs (Create Ticket, Find Similar Issues) to the thread.
    Synchronous version.
    Stores summary in conversation_states for CTA use.
    """
    logger.info(f"Posting summary and CTAs to channel {channel_id}, thread {thread_ts} for user {user_id}")
    
    conversation_key = f"{thread_ts}_{user_id}_mention_context"
    conversation_states[conversation_key] = {
        "summary": summary,
        "channel_id": channel_id, 
        "user_id": user_id, 
        "thread_ts": thread_ts,
        "flow": "mention_summary"
    }
    logger.info(f"Stored mention context in conversation_states with key: {conversation_key}. Summary: {summary[:100]}...")

    action_button_value = json.dumps({
        "mention_context_key": conversation_key 
    })

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"""Hi <@{user_id}>, I've summarized the recent conversation in this thread:
>>> {summary}"""
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "What would you like to do?"
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
                    "action_id": "mention_flow_create_ticket", 
                    "value": action_button_value
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Find Similar Issues",
                        "emoji": True
                    },
                    "action_id": "mention_flow_find_issues",
                    "value": action_button_value
                }
            ]
        }
    ]

    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts, 
            blocks=blocks,
            text=f"Summary: {summary}\nWhat would you like to do?" 
        )
        logger.info("Successfully posted summary and CTAs.")
    except SlackApiError as e:
        logger.error(f"Error posting summary and CTAs: {e}")
    except Exception as e_gen:
        logger.error(f"Generic error in post_summary_with_ctas: {e_gen}")

def handle_app_mention_event(event, client, logger_param, context):
    """
    Handles 'app_mention' events.
    Fetches thread history, summarizes it, and posts options back to the user.
    Synchronous version.
    """
    global logger 
    logger = logger_param 

    bot_user_id = context.get("bot_user_id")
    event_text = event.get("text", "") # Renamed to avoid conflict with local 'text' var

    if event.get("user") == bot_user_id or event.get("bot_id"):
        if event.get("bot_id") and not event.get("user"): 
             logger.info(f"App mention event from bot_id {event.get('bot_id')} (likely self or another bot), not a direct user mention. Ignoring.")
             return

    logger.info(f"Received app_mention event: {json.dumps(event, indent=2)}") # Log full event for debug

    channel_id = event.get("channel")
    # thread_ts for replying should be the event's thread_ts if it exists, or the event's ts itself to start/reply to a new thread.
    reply_thread_ts = event.get("thread_ts", event.get("ts")) 
    user_id = event.get("user") 

    if not channel_id or not reply_thread_ts or not user_id:
        logger.error("Could not extract channel_id, reply_thread_ts, or user_id from app_mention event. Cannot proceed.")
        return
    
    if f"<@{bot_user_id}>" not in event_text:
        logger.info(f"Bot (user ID {bot_user_id}) not directly mentioned in text: '{event_text}'. Ignoring event.")
        return

    try:
        logger.info("Starting synchronous flow for app_mention")
        
        # Use the new function, passing the whole event payload
        formatted_history = fetch_conversation_context_for_mention(client, event)

        if not formatted_history:
            logger.warning("No conversation history fetched or an error occurred.")
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=reply_thread_ts, # Reply in the correct thread context
                text="Sorry, I couldn't fetch the conversation history for this context."
            )
            return

        summary = summarize_conversation(formatted_history)

        if not summary or "Could not fetch" in summary or "Error:" in summary:
            logger.warning(f"Failed to generate summary: {summary}")
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=reply_thread_ts, # Reply in the correct thread context
                text="Sorry, I couldn't summarize the conversation."
            )
            return
            
        # Post CTAs back to the same thread where the mention occurred or was initiated
        post_summary_with_ctas(client, channel_id, reply_thread_ts, summary, user_id)

    except Exception as e:
        logger.error(f"Error in handle_app_mention_event: {e}", exc_info=True)
        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=reply_thread_ts, # Reply in the correct thread context
                text="Sorry, something went wrong while processing your mention."
            )
        except Exception as e_post:
            logger.error(f"Failed to send error message to user: {e_post}") 