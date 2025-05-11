import logging
import os
# import asyncio # No longer needed for direct sync conversion
from slack_sdk.errors import SlackApiError
import json # For storing complex data in button values if needed, or for logging

# Import the specific genai function and prompt
from services.genai_service import generate_text, process_mention_and_generate_all_components # Updated import
from utils.prompts import SUMMARIZE_SLACK_THREAD_PROMPT, PROCESS_MENTION_AND_GENERATE_ALL_COMPONENTS_PROMPT
from utils.state_manager import conversation_states # Import for CTA handling
# from utils.state_manager import conversation_states # For CTA handling later

# Placeholder for conversation_states if needed for passing summary to modal
# from utils.state_manager import conversation_states 
# Placeholder for duplicate detection service
# from services.duplicate_detection_service import find_and_summarize_duplicates

logger = logging.getLogger(__name__)
# genai_service = GenAIService() # Removed instantiation

MAX_MESSAGES_TO_FETCH = 20
MAX_MESSAGES_TO_FETCH_HISTORY = 20 # For conversation history

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

def post_summary_with_ctas(client, channel_id, thread_ts, summary: str, user_id: str, context_key_identifier: str):
    """
    Posts the summary and CTAs (Create Ticket, Find Similar Issues) to the thread.
    Stores summary in conversation_states for CTA use with a more unique key.
    """
    logger.info(f"Posting summary and CTAs to channel {channel_id}, thread {thread_ts} for user {user_id} (context: {context_key_identifier})")
    
    # Ensure summary is not excessively long for display or state
    display_summary = summary
    if len(summary) > 1000: # Arbitrary limit for display, actual state limit might be different
        logger.warning(f"Summary for CTA posting is very long ({len(summary)} chars), truncating for display.")
        display_summary = summary[:997] + "..."

    # More specific key for state to avoid clashes if user is in multiple flows
    conversation_key = f"{channel_id}_{thread_ts}_{user_id}_{context_key_identifier}"
    
    conversation_states[conversation_key] = {
        "summary": summary, # Store the full summary for backend use
        "channel_id": channel_id, 
        "user_id": user_id, 
        "thread_ts": thread_ts, # This is the reply_thread_ts
        "flow_context_key": conversation_key # Self-reference for clarity
    }
    logger.info(f"Stored mention context in conversation_states with key: {conversation_key}. Summary (original): {summary[:100]}...")

    action_button_value = json.dumps({
        "mention_context_key": conversation_key 
    })
    # Check length of action_button_value, though conversation_key should be manageable
    if len(action_button_value) > 2000:
         logger.error(f"Action button value for post_summary_with_ctas is too long: {len(action_button_value)}. Key: {conversation_key}")
         # Fallback: don't send value, or send minimal key. This would break current CTA handlers.
         # For now, assume it fits. This needs robust handling if keys become too long.
         # A possible solution is to use a much shorter, perhaps hashed, key if this becomes an issue.

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"""<@{user_id}>, I've processed your request. Based on the context, here's a summary:
>>> {display_summary}"""
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "What would you like to do next?"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Create Ticket from this",
                        "emoji": True
                    },
                    "action_id": "mention_flow_create_ticket", # Reverted to original action_id
                    "value": action_button_value 
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Find Similar Issues",
                        "emoji": True
                    },
                    "action_id": "mention_flow_find_issues", # Reverted to original action_id
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
            text=f"Summary: {display_summary}\nWhat would you like to do?" 
        )
        logger.info(f"Successfully posted summary and CTAs for context {context_key_identifier}.")
    except SlackApiError as e:
        logger.error(f"Error posting summary and CTAs for {context_key_identifier}: {e}")
    except Exception as e_gen: # Catch any other general errors
        logger.error(f"Generic error in post_summary_with_ctas for {context_key_identifier}: {e_gen}", exc_info=True)

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
        post_summary_with_ctas(client, channel_id, reply_thread_ts, summary, user_id, "mention_context_fallback_create")

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

def format_messages_for_mention_processing(messages, client, bot_user_id, limit=MAX_MESSAGES_TO_FETCH_HISTORY):
    """
    Formats a list of Slack message objects into a single string for the LLM.
    Excludes messages from the bot itself (based on bot_user_id).
    Orders messages oldest to newest.
    """
    messages_text_list = []
    user_cache = {}

    # Messages should already be oldest to newest
    for msg in messages:
        msg_user_id = msg.get("user")
        msg_bot_id = msg.get("bot_id") # Some bot messages might have bot_id but not user_id

        # Skip messages from our own bot to avoid feedback loops or confusion
        if msg_user_id == bot_user_id or msg_bot_id == bot_user_id: # Assuming bot_user_id is passed correctly
            continue

        if msg_user_id:
            if msg_user_id not in user_cache:
                try:
                    user_info_result = client.users_info(user=msg_user_id)
                    user_cache[msg_user_id] = user_info_result.get("user", {}).get("real_name") or user_info_result.get("user", {}).get("name", "Unknown User")
                except SlackApiError as e_user:
                    logger.error(f"Error fetching user info for {msg_user_id}: {e_user}")
                    user_cache[msg_user_id] = "Unknown User"
            
            user_name = user_cache[msg_user_id]
            text = msg.get("text", "")
            if text.strip():
                messages_text_list.append(f"{user_name}: {text}")
        # Consider if other bot messages (not our own) should be included or have special formatting
        # For now, only including user messages in history for simplicity in this pass

    final_formatted_string = "\n".join(messages_text_list[-limit:])
    logger.info(f"Formatted {len(messages_text_list)} messages for mention processing (excluding own bot messages), using tail {limit}. Preview: {final_formatted_string[:100]}...")
    return final_formatted_string

def fetch_conversation_history_for_mention(client, event_payload, bot_user_id, limit=MAX_MESSAGES_TO_FETCH_HISTORY):
    """
    Fetches conversation history *preceding* the app_mention event.
    - If in a thread, fetches thread replies excluding the mention itself.
    - If a top-level mention, fetches channel history leading up to (excluding) the mention.
    Returns a formatted string of messages.
    """
    channel_id = event_payload.get("channel")
    mention_ts = event_payload.get("ts") # Timestamp of the mention message itself
    thread_parent_ts = event_payload.get("thread_ts") # Timestamp of the parent message, if in a thread

    fetched_messages_for_history = []

    try:
        if thread_parent_ts:
            # Mention is in an existing thread
            logger.info(f"Mention is in thread {thread_parent_ts}. Fetching thread replies for history for channel {channel_id}.")
            result = client.conversations_replies(
                channel=channel_id,
                ts=thread_parent_ts,
                limit=limit + 5, # Fetch a bit more to ensure we can filter out the mention
                inclusive=True 
            )
            raw_thread_messages = result.get('messages', [])
            # Filter out the current mention message and any subsequent messages (if any)
            for msg in raw_thread_messages:
                if msg.get("ts") == mention_ts:
                    break # Stop when we reach the mention itself
                fetched_messages_for_history.append(msg)
            logger.debug(f"Fetched {len(fetched_messages_for_history)} messages from thread {thread_parent_ts} for history (before current mention).")
        else:
            # Mention is a top-level message. Fetch channel history *before* this mention.
            logger.info(f"Mention is top-level in channel {channel_id} (message_ts: {mention_ts}). Fetching channel history (exclusive of current mention).")
            result = client.conversations_history(
                channel=channel_id,
                limit=limit,
                latest=mention_ts, # Fetch messages up to this timestamp
                inclusive=False   # Exclude the message at 'latest' timestamp (the mention itself)
            )
            raw_channel_messages = result.get('messages', [])
            fetched_messages_for_history = list(reversed(raw_channel_messages)) # Reverse to get oldest first
            logger.debug(f"Fetched {len(fetched_messages_for_history)} messages from channel {channel_id} history (oldest first, exclusive of mention).")
        
        if not fetched_messages_for_history:
            logger.warning("No historical messages were fetched for context.")
            return ""

        return format_messages_for_mention_processing(fetched_messages_for_history, client, bot_user_id, limit)

    except SlackApiError as e:
        logger.error(f"Slack API error fetching conversation history for mention: {e}")
        return ""
    except Exception as e_gen:
        logger.error(f"Generic error fetching conversation history for mention: {e_gen}", exc_info=True)
        return ""

def handle_app_mention_event(event, client, logger_param, context):
    """
    Handles 'app_mention' events using the new GenAI service for intent detection and component generation.
    """
    global logger 
    logger = logger_param 

    bot_user_id = context.get("bot_user_id") # Critical for filtering own messages
    user_direct_message_to_bot = event.get("text", "")

    # Basic validation and filtering
    if event.get("user") == bot_user_id or (event.get("bot_id") and not event.get("user")): # Second part for some bot messages
        logger.info(f"App mention event from bot_id {event.get('bot_id')} or user {event.get('user')} (likely self or another bot without user field). Ignoring.")
        return

    logger.info(f"Received app_mention event for processing: {json.dumps(event, indent=2)}")

    channel_id = event.get("channel")
    # reply_thread_ts: where the bot's response should go. If mention is in a thread, reply in thread. Else, start a new thread from the mention.
    reply_thread_ts = event.get("thread_ts", event.get("ts")) 
    user_id = event.get("user") # The user who mentioned the bot

    if not all([channel_id, reply_thread_ts, user_id, bot_user_id]):
        logger.error("Missing critical information (channel_id, reply_thread_ts, user_id, or bot_user_id) from app_mention event or context. Cannot proceed.")
        return
    
    # Ensure the bot was actually mentioned (safeguard, though event type implies it)
    if f"<@{bot_user_id}>" not in user_direct_message_to_bot:
        logger.info(f"Bot user ID <@{bot_user_id}> not found in event text: '{user_direct_message_to_bot}'. Ignoring.")
        return

    # 1. Fetch conversation history (excluding the current mention and bot's own previous messages)
    formatted_conversation_history = fetch_conversation_history_for_mention(client, event, bot_user_id)
    logger.debug(f"User's direct message to bot: {user_direct_message_to_bot}")
    logger.debug(f"Formatted conversation history for LLM: {formatted_conversation_history}")

    # 2. Call GenAIService to process mention and generate components
    try:
        # Call the imported top-level function directly
        ai_components = process_mention_and_generate_all_components(
            user_direct_message_to_bot=user_direct_message_to_bot,
            formatted_conversation_history=formatted_conversation_history
        )
    except Exception as e:
        logger.error(f"Error calling process_mention_and_generate_all_components: {e}", exc_info=True)
        # Post a generic error message
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=reply_thread_ts,
            text=f"<@{user_id}> Sorry, I encountered an error trying to understand your request. Please try again later."
        )
        return

    if not ai_components or "intent" not in ai_components:
        logger.error(f"Failed to get valid components from process_mention_and_generate_all_components. Response: {ai_components}")
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=reply_thread_ts,
            text=f"<@{user_id}> I'm having a little trouble understanding that. Could you try rephrasing?"
        )
        return

    intent = ai_components.get("intent")
    contextual_summary = ai_components.get("contextual_summary", "Could not generate a summary.") # Fallback summary
    suggested_title = ai_components.get("suggested_title")
    refined_description = ai_components.get("refined_description")

    logger.info(f"GenAI processed mention: Intent='{intent}', Summary='{contextual_summary[:100]}...', Title='{suggested_title}', Desc provided: {bool(refined_description)}")

    # Store these components in conversation_states using a unique key for this mention event
    # This key will be passed in button values for subsequent actions to retrieve this context.
    # Using a more robust key including user_id to prevent theoretical cross-talk if multiple users trigger mentions in same thread around same time.
    # Though thread_ts is usually unique enough for a single interaction.
    unique_event_id = event.get("event_ts", event.get("ts")) # A unique identifier for this specific mention event
    mention_context_key = f"{channel_id}_{reply_thread_ts}_{user_id}_{unique_event_id}_mention_full_context"
    
    conversation_states[mention_context_key] = {
        "intent": intent,
        "summary": contextual_summary, # This is the contextual_summary from AI
        "ai_suggested_title": suggested_title, # Storing the AI suggested title
        "ai_refined_description": refined_description, # Storing the AI refined description
        "user_id": user_id, # User who was mentioned / initiated
        "channel_id": channel_id,
        "thread_ts": reply_thread_ts, # Thread where bot will reply and subsequent actions happen
        "original_message_ts": event.get("ts"), # TS of the actual mention message
        "bot_user_id": bot_user_id, # Bot's own user ID
        "assistant_id": context.get("assistant_id") # Assistant ID if available in this context
    }
    logger.info(f"Stored full mention context in conversation_states with key: {mention_context_key}. Title: {suggested_title}, Desc: {refined_description[:50] if refined_description else 'N/A'}...")

    # Now, decide what to do based on the intent
    if intent == "create_ticket" or intent == "find_issues_and_create":
        # For creating a ticket, we'll use the contextual_summary as the basis for duplicate check
        # and then the suggested_title & refined_description to pre-fill the modal.
        # The CTA will carry the mention_context_key.
        post_summary_and_final_ctas_for_mention(
            client=client, 
            channel_id=channel_id, 
            thread_ts=reply_thread_ts, 
            summary_to_display=contextual_summary, # Summary to show the user
            user_id=user_id, 
            mention_context_key_for_cta=mention_context_key, # Key to retrieve all context including title/desc
            ai_suggested_title=suggested_title, # Pass for potential direct use
            ai_refined_description=refined_description # Pass for potential direct use
        )
    elif intent == "FIND_SIMILAR_ISSUES":
        logger.info(f"Intent is FIND_SIMILAR_ISSUES. Using summary: {contextual_summary}")
        try:
            from handlers.flows.ticket_creation_orchestrator import present_duplicate_check_and_options # Corrected import
            
            client.chat_postMessage( # Let user know we are searching
                channel=channel_id,
                thread_ts=reply_thread_ts,
                text=f"<@{user_id}> Understood. I'm looking for similar issues based on: \"{contextual_summary[:150]}...\""
            )
            
            # Call the orchestrator's main function for presenting duplicates
            present_duplicate_check_and_options(
                client=client,
                channel_id=channel_id,
                user_id=user_id,
                thread_ts=reply_thread_ts,
                initial_description=contextual_summary, # Use LLM summary as the basis for search
                # assistant_id is not strictly needed here as this flow doesn't use assistant status updates typically.
                # If present_duplicate_check_and_options requires it for all paths, we might need to pass it from context.
                # For now, assuming it's optional or handled by a default in the orchestrator if None.
                assistant_id=context.get("assistant_id") # Pass assistant_id from context if available
            )

        except ImportError:
            logger.error("ImportError: `present_duplicate_check_and_options` from orchestrator not found. FIND_SIMILAR_ISSUES intent cannot be fully handled.")
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=reply_thread_ts,
                text=f"<@{user_id}> I understood you want to find similar issues, but I'm having trouble accessing that feature right now."
            )
        except Exception as e_find:
            logger.error(f"Error during FIND_SIMILAR_ISSUES flow: {e_find}", exc_info=True)
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=reply_thread_ts,
                text=f"<@{user_id}> Sorry, an error occurred while trying to find similar issues."
            )

    elif intent == "UNCLEAR_INTENT" or not intent: # Fallback for unclear or missing intent
        logger.info(f"Intent is UNCLEAR or missing. Using summary: {contextual_summary}. Posting standard CTAs.")
        # Use existing post_summary_with_ctas, but pass the LLM's summary
        # Ensure post_summary_with_ctas can take a pre-generated summary
        post_summary_with_ctas(client, channel_id, reply_thread_ts, contextual_summary, user_id, "mention_context_unclear")
    
    else: # Unknown intent string
        logger.warning(f"Unknown intent received from process_mention_and_generate_all_components: '{intent}'. Defaulting to UNCLEAR_INTENT behavior.")
        post_summary_with_ctas(client, channel_id, reply_thread_ts, contextual_summary, user_id, "mention_context_unknown_intent")


# Adapting post_summary_with_ctas to take a pre-computed summary and a unique context key part
def post_summary_with_ctas(client, channel_id, thread_ts, summary: str, user_id: str, context_key_identifier: str):
    """
    Posts the summary and CTAs (Create Ticket, Find Similar Issues) to the thread.
    Stores summary in conversation_states for CTA use with a more unique key.
    """
    logger.info(f"Posting summary and CTAs to channel {channel_id}, thread {thread_ts} for user {user_id} (context: {context_key_identifier})")
    
    # Ensure summary is not excessively long for display or state
    display_summary = summary
    if len(summary) > 1000: # Arbitrary limit for display, actual state limit might be different
        logger.warning(f"Summary for CTA posting is very long ({len(summary)} chars), truncating for display.")
        display_summary = summary[:997] + "..."

    # More specific key for state to avoid clashes if user is in multiple flows
    conversation_key = f"{channel_id}_{thread_ts}_{user_id}_{context_key_identifier}"
    
    conversation_states[conversation_key] = {
        "summary": summary, # Store the full summary for backend use
        "channel_id": channel_id, 
        "user_id": user_id, 
        "thread_ts": thread_ts, # This is the reply_thread_ts
        "flow_context_key": conversation_key # Self-reference for clarity
    }
    logger.info(f"Stored mention context in conversation_states with key: {conversation_key}. Summary (original): {summary[:100]}...")

    action_button_value = json.dumps({
        "mention_context_key": conversation_key 
    })
    # Check length of action_button_value, though conversation_key should be manageable
    if len(action_button_value) > 2000:
         logger.error(f"Action button value for post_summary_with_ctas is too long: {len(action_button_value)}. Key: {conversation_key}")
         # Fallback: don't send value, or send minimal key. This would break current CTA handlers.
         # For now, assume it fits. This needs robust handling if keys become too long.
         # A possible solution is to use a much shorter, perhaps hashed, key if this becomes an issue.

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"""<@{user_id}>, I've processed your request. Based on the context, here's a summary:
>>> {display_summary}"""
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "What would you like to do next?"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Create Ticket from this",
                        "emoji": True
                    },
                    "action_id": "mention_flow_create_ticket", # Reverted to original action_id
                    "value": action_button_value 
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Find Similar Issues",
                        "emoji": True
                    },
                    "action_id": "mention_flow_find_issues", # Reverted to original action_id
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
            text=f"Summary: {display_summary}\nWhat would you like to do?" 
        )
        logger.info(f"Successfully posted summary and CTAs for context {context_key_identifier}.")
    except SlackApiError as e:
        logger.error(f"Error posting summary and CTAs for {context_key_identifier}: {e}")
    except Exception as e_gen: # Catch any other general errors
        logger.error(f"Generic error in post_summary_with_ctas for {context_key_identifier}: {e_gen}", exc_info=True)

# Remove or comment out the old summarize_conversation if no longer used directly by handle_app_mention_event
# def summarize_conversation(conversation_history: str): ...

# Remove or comment out the original format_messages_for_summary if it's fully replaced
# def format_messages_for_summary(messages, client, limit=MAX_MESSAGES_TO_FETCH): ...

# Original fetch_conversation_context_for_mention is replaced by fetch_conversation_history_for_mention
# def fetch_conversation_context_for_mention(client, event_payload, limit=MAX_MESSAGES_TO_FETCH): ... 