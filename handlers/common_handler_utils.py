import logging
import json
from slack_sdk.errors import SlackApiError
from utils.state_manager import conversation_states # Assuming this is still relevant for how CTAs are built or keys are managed

logger = logging.getLogger(__name__)

MAX_MESSAGES_TO_FETCH_HISTORY = 20 # Copied from mention_handler, ensure consistency

def format_messages_for_mention_processing(messages, client, bot_user_id, limit=MAX_MESSAGES_TO_FETCH_HISTORY):
    """
    Formats a list of Slack message objects into a single string for the LLM.
    Excludes messages from the bot itself (based on bot_user_id).
    Orders messages oldest to newest.
    """
    messages_text_list = []
    user_cache = {}

    for msg in messages:
        msg_user_id = msg.get("user")
        msg_bot_id = msg.get("bot_id")

        if msg_user_id == bot_user_id or msg_bot_id == bot_user_id:
            continue

        if msg_user_id:
            if msg_user_id not in user_cache:
                try:
                    # TODO: Make this async if client is async (e.g., await client.users_info(...))
                    user_info_result = client.users_info(user=msg_user_id)
                    user_cache[msg_user_id] = user_info_result.get("user", {}).get("real_name") or user_info_result.get("user", {}).get("name", "Unknown User")
                except SlackApiError as e_user:
                    logger.error(f"Error fetching user info for {msg_user_id}: {e_user}")
                    user_cache[msg_user_id] = "Unknown User"
            
            user_name = user_cache[msg_user_id]
            text = msg.get("text", "")
            if text.strip():
                messages_text_list.append(f"{user_name}: {text}")

    final_formatted_string = "\n".join(messages_text_list[-limit:])
    logger.info(f"Formatted {len(messages_text_list)} messages for mention processing, using tail {limit}. Preview: {final_formatted_string[:100]}...")
    return final_formatted_string

def format_messages_for_summary(messages, client):
    """
    Formats a list of Slack message objects into a single string for summarization.
    Includes all messages (users and bots) and orders them by timestamp (oldest to newest).
    Fetches user names for user messages.
    """
    messages_text_list = []
    user_cache = {}

    # Slack API (conversations_replies) usually returns messages oldest to newest.
    # If explicit sorting is ever needed: messages.sort(key=lambda m: float(m.get('ts', 0)))

    for msg in messages:
        text = msg.get("text", "")
        user_name = None

        if "user" in msg: # User messages and some bot messages have a 'user' field
            msg_user_id = msg["user"]
            if msg_user_id not in user_cache:
                try:
                    user_info_result = client.users_info(user=msg_user_id)
                    user_cache[msg_user_id] = user_info_result.get("user", {}).get("real_name") or user_info_result.get("user", {}).get("name", "Unknown User")
                except SlackApiError as e_user:
                    logger.error(f"Error fetching user info for {msg_user_id} during summary formatting: {e_user}")
                    user_cache[msg_user_id] = "Unknown User"
                except Exception as e_gen_user:
                    logger.error(f"Generic error fetching user info for {msg_user_id} during summary formatting: {e_gen_user}")
                    user_cache[msg_user_id] = "Unknown User (Error)"
            user_name = user_cache[msg_user_id]
        elif "bot_id" in msg and not user_name:
            # Try to get bot's name if it has a bot_profile and no user field was processed
            bot_profile = msg.get("bot_profile")
            if bot_profile and "name" in bot_profile:
                user_name = bot_profile["name"]
            else:
                user_name = msg.get("username", "Bot") # Fallback to username or just "Bot"

        if text.strip(): # Only include messages with actual text content
            if user_name:
                messages_text_list.append(f"{user_name}: {text}")
            else: # Should ideally not happen if user or bot_id is present
                messages_text_list.append(text) 
    
    final_formatted_string = "\n".join(messages_text_list)
    logger.info(f"Formatted {len(messages_text_list)} messages for summary. Preview: {final_formatted_string[:200]}...")
    return final_formatted_string

def post_summary_with_ctas(client, channel_id, thread_ts, summary_to_display, user_id, context_key_identifier):
    """
    Posts a message with a summary and CTAs for 'Create Ticket' and 'Find Similar Issues'.
    This is typically used when the intent is less clear or for general summarization.
    'context_key_identifier' is used to ensure button actions can retrieve the correct context later.
    """
    logger.info(f"Posting summary and general CTAs to channel {channel_id}, thread {thread_ts} for user {user_id}. Context key: {context_key_identifier}")

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<@{user_id}> Here's a summary of our conversation so far:\n>>> {summary_to_display}"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Create Ticket with these details",
                        "emoji": True
                    },
                    "action_id": "mention_flow_create_ticket", 
                    "value": json.dumps({"mention_context_key": context_key_identifier}),
                    "style": "primary"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "🔍 Find Similar Issues",
                        "emoji": True
                    },
                    "action_id": "mention_flow_find_issues",
                    "value": json.dumps({"mention_context_key": context_key_identifier, "original_user_id": user_id})
                }
            ]
        }
    ]

    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=blocks,
            text=f"<@{user_id}> Summary & Actions"
        )
        logger.info(f"Successfully posted summary with general CTAs for {context_key_identifier}.")
    except SlackApiError as e:
        logger.error(f"Error posting summary with CTAs for {context_key_identifier}: {e.response['error']}")
    except Exception as e_gen:
        logger.error(f"Generic error posting summary with CTAs for {context_key_identifier}: {e_gen}", exc_info=True)

def post_summary_and_final_ctas_for_mention(
    client, 
    channel_id: str, 
    thread_ts: str, 
    summary_to_display: str, 
    user_id: str, 
    mention_context_key_for_cta: str,
    ai_suggested_title: str | None = None,
    ai_refined_description: str | None = None
):
    """
    Posts a message after a mention has been processed, showing the summary and specific CTAs
    to either confirm opening the create ticket modal (pre-filled) or find similar issues.
    """
    logger.info(f"Posting final CTAs for processed mention. User: {user_id}, Channel: {channel_id}, Thread: {thread_ts}. Context key: {mention_context_key_for_cta}")

    action_value_payload = {
        "mention_context_key": mention_context_key_for_cta, # Main key to retrieve full context
        "title": ai_suggested_title if ai_suggested_title else "Untitled Ticket",
        "description": ai_refined_description if ai_refined_description else summary_to_display,
        "user_id": user_id,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "summary_for_confirmation": summary_to_display # The specific summary that was shown
    }
    action_value_str = json.dumps(action_value_payload)

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<@{user_id}>, I've processed your request and prepared the following ticket details based on our conversation:"
            }
        },
        {"type": "divider"}
    ]

    # AI Suggested Title is NOT displayed in this message anymore as per user request.
    # It will still be passed in action_value_payload for modal pre-filling.
    # if ai_suggested_title:
    #     blocks.append({
    #         "type": "section",
    #         "text": {
    #             "type": "mrkdwn",
    #             "text": f"""*AI Suggested Title:*
    # `{ai_suggested_title}`"""
    #         }
    #     })

    blocks.extend([
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*AI Summary:*"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{ai_suggested_title if ai_suggested_title else summary_to_display}```"
            }
        }
    ])

    if ai_refined_description and ai_refined_description != summary_to_display:
        blocks.extend([
            # No divider here if title is removed and summary is directly above
            # {"type": "divider"}, # Only add divider if there was a title block or if summary itself needs separation before desc
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*AI Description:*"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```{ai_refined_description}```"
                }
            }
        ])

    blocks.extend([
        {"type": "divider"}, # Divider before actions
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Looks Good, Create Ticket",
                        "emoji": True
                    },
                    "action_id": "mention_confirm_open_create_form",
                    "value": action_value_str,
                    "style": "primary"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "🔍 Find Similar Issues First",
                        "emoji": True
                    },
                    "action_id": "check_similar_issues_button_action", 
                     "value": json.dumps({"mention_context_key": mention_context_key_for_cta, "original_user_id": user_id})
                }
            ]
        }
    ])

    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=blocks,
            text=f"<@{user_id}>, I've processed your request to create a ticket. Here's what I've prepared:"
        )
        logger.info(f"Successfully posted final CTAs for processed mention {mention_context_key_for_cta}.")
    except SlackApiError as e:
        logger.error(f"Error posting final CTAs for processed mention {mention_context_key_for_cta}: {e.response['error']}")
    except Exception as e_gen:
        logger.error(f"Generic error posting final CTAs for processed mention {mention_context_key_for_cta}: {e_gen}", exc_info=True) 