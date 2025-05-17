import logging
import json
from slack_sdk.errors import SlackApiError

from services.genai_service import process_mention_and_generate_all_components
from utils.state_manager import conversation_states
# Assuming prompts are not directly used in this handler but by the genai_service
# from utils.prompts import PROCESS_MENTION_AND_GENERATE_ALL_COMPONENTS_PROMPT

# Updated import to use the new common_handler_utils.py
from .common_handler_utils import (
    format_messages_for_mention_processing, 
    post_summary_with_ctas, 
    post_summary_and_final_ctas_for_mention
)

logger = logging.getLogger(__name__)

MAX_MESSAGES_TO_FETCH_HISTORY = 20 # Consistent with common_handler_utils

def process_user_query(
    client, 
    bot_user_id: str,
    user_id: str, 
    channel_id: str, 
    thread_ts: str | None, # Timestamp of the parent message if in a thread
    message_ts: str, # Timestamp of the user's current message
    user_message_text: str,
    is_direct_message: bool,
    # context might be needed for assistant_id or other context-specific details
    # For now, assuming bot_user_id is passed directly.
    # If assistant_id is crucial for all paths, it needs to be passed or retrieved.
    assistant_id: str | None = None 
):
    """
    Unified handler for processing user queries from @mentions or direct messages.
    
    1. Fetches thread context (if applicable).
    2. Calls AI to understand intent, summarize, and extract components.
    3. Handles follow-up questions or Q&A if intent is identified.
    4. If action intent (create ticket, find issues), proceeds with existing flows.
    """
    logger.info(f"Processing user query. User: {user_id}, Channel: {channel_id}, Thread: {thread_ts}, DM: {is_direct_message}, Message TS: {message_ts}")
    logger.debug(f"User message text: {user_message_text}")

    # reply_ts is where the bot's response should go.
    # If in a thread (thread_ts is not None), reply in that thread.
    # If not in a thread (e.g., new message in channel or DM), reply by starting a thread from user's message (message_ts).
    reply_ts = thread_ts if thread_ts else message_ts

    # --- 1. Fetch Thread Context (if applicable) ---
    formatted_conversation_history = ""
    if thread_ts: # Indicates the user's message is part of an existing thread
        logger.info(f"Query is in thread {thread_ts}. Fetching entire thread content for channel {channel_id} as context.")
        try:
            # Fetch all messages in this specific thread
            result = client.conversations_replies(
                channel=channel_id,
                ts=thread_ts, # Parent message TS of the thread
                limit=MAX_MESSAGES_TO_FETCH_HISTORY, # Max messages to consider from the thread
                inclusive=True
            )
            thread_messages = result.get('messages', [])
            if thread_messages:
                # Format these messages, excluding bot's own messages
                # format_messages_for_mention_processing is used as it handles user mapping and bot message exclusion
                formatted_conversation_history = format_messages_for_mention_processing(
                    thread_messages, 
                    client, 
                    bot_user_id, 
                    MAX_MESSAGES_TO_FETCH_HISTORY 
                )
                logger.debug(f"Fetched and formatted {len(thread_messages)} messages from thread {thread_ts} for AI context.")
            else:
                logger.debug(f"No messages found in thread {thread_ts} for AI context.")
        except SlackApiError as e:
            logger.error(f"Slack API error fetching thread replies for AI context: {e}")
        except Exception as e_gen:
            logger.error(f"Generic error fetching thread replies for AI context: {e_gen}", exc_info=True)
    else:
        logger.info("Query is not in a thread (new message or DM). No additional conversation history from channel/DM will be passed to AI beyond user_message_text.")
        # For DMs not in a thread, or new channel messages, history is just the current message unless extended later.

    logger.debug(f"User's direct message for AI: {user_message_text}")
    logger.debug(f"Formatted conversation history for AI: {formatted_conversation_history[:200]}...")

    # --- 2. Call AI Service to Understand Intent & Generate Components ---
    try:
        ai_components = process_mention_and_generate_all_components( # Sync call
            user_direct_message_to_bot=user_message_text,
            formatted_conversation_history=formatted_conversation_history
            # We might need to pass more context to the AI service if it needs to behave differently for DMs vs. Mentions
        )
    except Exception as e:
        logger.error(f"Error calling process_mention_and_generate_all_components: {e}", exc_info=True)
        try:
            client.chat_postMessage( # Sync call
                channel=channel_id,
                thread_ts=reply_ts,
                text=f"<@{user_id}> Sorry, I encountered an error trying to understand your request. Please try again later."
            )
        except Exception as e_post:
            logger.error(f"Failed to send AI error message to user: {e_post}")
        return

    if not ai_components or "intent" not in ai_components:
        logger.error(f"Failed to get valid components from AI. Response: {ai_components}")
        try:
            client.chat_postMessage( # Sync call
                channel=channel_id,
                thread_ts=reply_ts,
                text=f"<@{user_id}> I'm having a little trouble understanding that. Could you try rephrasing?"
            )
        except Exception as e_post:
            logger.error(f"Failed to send AI component error message to user: {e_post}")
        return

    intent = ai_components.get("intent")
    contextual_summary = ai_components.get("contextual_summary", "Could not generate a summary.")
    suggested_title = ai_components.get("suggested_title")
    refined_description = ai_components.get("refined_description")
    # For Q&A, the AI might return a direct answer. Let's assume a field like 'direct_answer' for now.
    direct_answer = ai_components.get("direct_answer") 

    # Normalize intent to uppercase for consistent matching
    intent = intent.upper() if intent else None

    logger.info(f"AI processed query: Intent='{intent}', Summary='{contextual_summary[:100]}...', Title='{suggested_title}', Desc: {bool(refined_description)}, Answer: {bool(direct_answer)}")

    # --- Store AI components in conversation_states for potential later use by actions ---
    # The key needs to be robust for both mentions and DMs.
    # message_ts should be unique enough for the initiating event.
    # Using reply_ts because that's the thread context where subsequent interactions might happen.
    context_key_base = f"{channel_id}_{reply_ts}_{user_id}_{message_ts}"
    
    # Storing a comprehensive context
    current_context_key = f"{context_key_base}_unified_context"
    conversation_states[current_context_key] = {
        "intent": intent,
        "summary": contextual_summary,
        "ai_suggested_title": suggested_title,
        "ai_refined_description": refined_description,
        "direct_answer": direct_answer, # Store potential direct answer
        "user_id": user_id,
        "channel_id": channel_id,
        "thread_ts": reply_ts, # Where bot replies and actions might occur
        "original_message_ts": message_ts, 
        "bot_user_id": bot_user_id,
        "is_direct_message": is_direct_message,
        "assistant_id": assistant_id # Pass along if available
    }
    logger.info(f"Stored unified query context in conversation_states with key: {current_context_key}.")

    # --- 3. Handle Follow-up Questions / Normal Question Answer ---
    if intent == "GENERAL_QUESTION" or intent == "QUESTION_ANSWERING":
        if direct_answer:
            logger.info(f"Intent is Q&A. Posting direct answer from AI to thread {reply_ts}.")
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=reply_ts,
                    text=f"<@{user_id}> {direct_answer}"
                )
            except Exception as e_post:
                logger.error(f"Failed to post direct answer: {e_post}")
            return
        else:
            logger.warning(f"Q&A intent recognized, but no direct_answer provided. Posting conversational follow-up. Summary: {contextual_summary}")
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=reply_ts,
                    text=f"<@{user_id}> I've processed your query. I can help with Jira tasks like creating tickets or finding similar issues. How can I assist you today?"
                )
            except Exception as e_post:
                logger.error(f"Failed to post Q&A conversational follow-up: {e_post}")
            return
    elif intent == "CLARIFICATION":
        logger.info(f"Intent is CLARIFICATION. Posting a general conversational response for thread {reply_ts}.")
        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=reply_ts,
                text=f"<@{user_id}> Hi there! I can help with Jira tasks like creating tickets or finding similar issues. What can I do for you today?"
            )
        except Exception as e_post:
            logger.error(f"Failed to post CLARIFICATION conversational response: {e_post}")
        return
    elif intent == "CREATE_TICKET" or intent == "FIND_ISSUES_AND_CREATE":
        logger.info(f"Intent is CREATE_TICKET. Posting CTAs for mention in thread {reply_ts}.")
        post_summary_and_final_ctas_for_mention(
            client=client, 
            channel_id=channel_id, 
            thread_ts=reply_ts, 
            summary_to_display=contextual_summary,
            user_id=user_id, 
            mention_context_key_for_cta=current_context_key, 
            ai_suggested_title=suggested_title,
            ai_refined_description=refined_description
        )
    elif intent == "FIND_SIMILAR_TICKETS":
        logger.info(f"Intent is FIND_SIMILAR_ISSUES. Using summary: {contextual_summary} for thread {reply_ts}.")
        try: # Outer try for the whole FIND_SIMILAR_ISSUES flow
            from handlers.flows.ticket_creation_orchestrator import present_duplicate_check_and_options 
            
            try: # Inner try for posting the initial message
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=reply_ts,
                    text=f'<@{user_id}> Understood. I\'m looking for similar issues based on: "{contextual_summary[:150]}..."'
                )
            except Exception as e_post_initial_msg:
                logger.error(f"Failed to post 'looking for similar issues' message: {e_post_initial_msg}")

            present_duplicate_check_and_options(
                client=client,
                channel_id=channel_id,
                user_id=user_id,
                thread_ts=reply_ts,
                initial_description=contextual_summary,
                assistant_id=assistant_id,
            )
        except ImportError:
            logger.error("ImportError: `present_duplicate_check_and_options` not found. FIND_SIMILAR_ISSUES cannot be fully handled.")
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=reply_ts,
                    text=f"<@{user_id}> I understood you want to find similar issues, but I'm having trouble accessing that feature right now."
                )
            except Exception as e_post_import_error:
                logger.error(f"Failed to post FIND_SIMILAR_ISSUES import error message: {e_post_import_error}")
        except Exception as e_find_flow: # Catch other errors during the find issues flow (e.g., from present_duplicate_check_and_options)
            logger.error(f"Error during FIND_SIMILAR_ISSUES flow: {e_find_flow}", exc_info=True)
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=reply_ts,
                    text=f"<@{user_id}> Sorry, an error occurred while trying to find similar issues."
                )
            except Exception as e_post_general_error:
                logger.error(f"Failed to post FIND_SIMILAR_ISSUES general flow error message: {e_post_general_error}")       
    elif intent == "UNCLEAR_INTENT" or not intent:
        logger.info(f"Intent is UNCLEAR or missing for thread {reply_ts}. Posting clarification request.")
        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=reply_ts,
                text=f"<@{user_id}> I'm not quite sure what you mean. Could you please rephrase or tell me what you'd like to do?"
            )
        except Exception as e_post:
            logger.error(f"Failed to post UNCLEAR_INTENT clarification request: {e_post}")
    else: 
        logger.warning(f"Unknown intent '{intent}' received from AI for thread {reply_ts}. Defaulting to clarification request.")
        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=reply_ts,
                text=f"<@{user_id}> I'm not quite sure how to help with that. Can you please clarify your request?"
            )
        except Exception as e_post:
            logger.error(f"Failed to post UNKNOWN_INTENT clarification request: {e_post}") 