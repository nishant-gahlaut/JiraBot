import logging
import os
# import asyncio # No longer needed for direct sync conversion
from slack_sdk.errors import SlackApiError
import json # For storing complex data in button values if needed, or for logging

# Import the specific genai function and prompt
# These are now primarily used by unified_query_handler via process_mention_and_generate_all_components
# from services.genai_service import generate_text, process_mention_and_generate_all_components 
# from utils.prompts import SUMMARIZE_SLACK_THREAD_PROMPT, PROCESS_MENTION_AND_GENERATE_ALL_COMPONENTS_PROMPT
from utils.state_manager import conversation_states # Import for CTA handling (though unified_query_handler manages its own state)
from handlers.unified_query_handler import process_user_query # Import the new unified query processor

# Placeholder for conversation_states if needed for passing summary to modal
# from utils.state_manager import conversation_states 
# Placeholder for duplicate detection service
# from services.duplicate_detection_service import find_and_summarize_duplicates

logger = logging.getLogger(__name__)
# genai_service = GenAIService() # Removed instantiation

MAX_MESSAGES_TO_FETCH = 20
MAX_MESSAGES_TO_FETCH_HISTORY = 20 # For conversation history

# Functions like format_messages_for_mention_processing, post_summary_with_ctas, 
# and post_summary_and_final_ctas_for_mention have been moved to common_handler_utils.py

# The main entry point for @mentions, now refactored
def handle_app_mention_event(event, client, logger_param, context):
    """
    Handles 'app_mention' events by delegating to the unified_query_handler.
    """
    global logger 
    logger = logger_param 

    bot_user_id = context.get("bot_user_id") 
    user_direct_message_to_bot = event.get("text", "")
    
    if event.get("user") == bot_user_id or (event.get("bot_id") and not event.get("user")):
        logger.info(f"App mention event from bot_id {event.get('bot_id')} or user {event.get('user')} (likely self or another bot without user field). Ignoring.")
        return

    logger.info(f"Received app_mention event for unified processing: {json.dumps(event, indent=2)}")

    channel_id = event.get("channel")
    message_ts = event.get("ts") 
    thread_ts_for_context = event.get("thread_ts") 
    user_id = event.get("user") 

    if not all([channel_id, message_ts, user_id, bot_user_id]):
        logger.error("Missing critical information from app_mention event. Cannot proceed with unified handler.")
        return
    
    if f"<@{bot_user_id}>" not in user_direct_message_to_bot:
        logger.info(f"Bot user ID <@{bot_user_id}> not found in event text. Ignoring.")
        return

    # Call the unified query processor (now a sync call)
    process_user_query(
        client=client,
        bot_user_id=bot_user_id,
        user_id=user_id,
        channel_id=channel_id,
        thread_ts=thread_ts_for_context,
        message_ts=message_ts,
        user_message_text=user_direct_message_to_bot,
        is_direct_message=False,
        assistant_id=context.get("assistant_id")
    )

# Old helper functions previously here are now in common_handler_utils.py or removed if obsolete.

# Removed old helper functions like fetch_conversation_history_for_mention, 
# summarize_conversation, fetch_conversation_context_for_mention
# as their logic is now within or superseded by unified_query_handler and its direct calls.

# Remove or comment out the old summarize_conversation if no longer used directly by handle_app_mention_event
# def summarize_conversation(conversation_history: str): ...

# Remove or comment out the original format_messages_for_summary if it's fully replaced
# def format_messages_for_summary(messages, client, limit=MAX_MESSAGES_TO_FETCH): ...

# Original fetch_conversation_context_for_mention is replaced by fetch_conversation_history_for_mention
# def fetch_conversation_context_for_mention(client, event_payload, limit=MAX_MESSAGES_TO_FETCH): ... 