import logging
from slack_sdk.errors import SlackApiError
from utils.state_manager import conversation_states
from services.jira_service import fetch_my_jira_tickets
from utils.slack_ui_helpers import build_rich_ticket_blocks
import os

logger = logging.getLogger(__name__)

def handle_my_tickets_initial_action(ack, body, client, logger):
    """Handles the 'My Tickets' button click and asks for the period."""
    ack()
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]
    assistant_id = body.get("assistant", {}).get("id")

    logger.info(f"'My Tickets' button clicked by user {user_id} in thread {thread_ts}.")

    conversation_states[thread_ts] = {
        "step": "awaiting_my_tickets_period",
        "user_id": user_id,
        "channel_id": channel_id,
        "assistant_id": assistant_id,
        "data": {}
    }
    logger.info(f"Set state for thread {thread_ts} to 'awaiting_my_tickets_period'")

    period_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Okay, let's find your tickets. How far back should I look?"
            }
        },
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Past 1 Week"}, "action_id": "my_tickets_period_1w"},
                {"type": "button", "text": {"type": "plain_text", "text": "Past 2 Weeks"}, "action_id": "my_tickets_period_2w"},
                {"type": "button", "text": {"type": "plain_text", "text": "Past 1 Month"}, "action_id": "my_tickets_period_1m"}
            ]
        }
    ]
    try:
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, blocks=period_blocks, text="Select a period for your tickets:")
        logger.info(f"Asked for period for 'My Tickets' in thread {thread_ts}.")
    except SlackApiError as e:
        logger.error(f"Error posting period selection for My Tickets: {e.response['error']}")

def handle_my_tickets_period_selection(ack, body, client, logger, period_value):
    """Handles the period selection and asks for status."""
    ack()
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]
    
    current_state = conversation_states.get(thread_ts)
    if not current_state or current_state["step"] != "awaiting_my_tickets_period":
        logger.warning(f"Received 'my_tickets_period' action for thread {thread_ts} but state is incorrect: {current_state}")
        return

    current_state["data"]["period"] = period_value
    current_state["step"] = "awaiting_my_tickets_status"
    conversation_states[thread_ts] = current_state
    logger.info(f"Stored period '{period_value}' for thread {thread_ts}. State: {current_state['step']}")

    clicked_button_text = "the selected period"
    try:
        clicked_button_text = body["actions"][0]["text"]["text"]
    except (KeyError, IndexError) as e:
        logger.warning(f"Could not extract button text from period selection: {e}")

    status_blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"Got it, looking for tickets from '{clicked_button_text}'. Now, select a status:"}
        },
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Open"}, "action_id": "my_tickets_status_open"},
                {"type": "button", "text": {"type": "plain_text", "text": "In Detailing"}, "action_id": "my_tickets_status_indetailing"},
                {"type": "button", "text": {"type": "plain_text", "text": "In Dev"}, "action_id": "my_tickets_status_indev"},
                {"type": "button", "text": {"type": "plain_text", "text": "QA"}, "action_id": "my_tickets_status_qa"},
                {"type": "button", "text": {"type": "plain_text", "text": "Closed"}, "action_id": "my_tickets_status_closed"}
            ]
        }
    ]
    try:
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, blocks=status_blocks, text="Select ticket status:")
        logger.info(f"Asked for status for 'My Tickets' in thread {thread_ts}.")
    except SlackApiError as e:
        logger.error(f"Error posting status selection for My Tickets: {e.response['error']}")

def handle_my_tickets_status_selection(ack, body, client, logger, status_value):
    """Handles status selection, fetches tickets from Jira, and displays them using rich format."""
    ack()
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]
    assistant_id = body.get("assistant", {}).get("id")
    
    current_state = conversation_states.get(thread_ts)
    if not current_state or current_state["step"] != "awaiting_my_tickets_status":
        logger.warning(f"Received 'my_tickets_status' action for thread {thread_ts} but state is incorrect: {current_state}")
        return

    current_state["data"]["status"] = status_value
    slack_user_id_for_query = current_state.get("user_id") 
    jira_query_assignee_name = None
    try:
        user_info_response = client.users_info(user=slack_user_id_for_query)
        if user_info_response and user_info_response.get("ok"):
            user_profile = user_info_response.get("user")
            logger.debug(f"Slack user_info response for {slack_user_id_for_query}: {user_profile}")
            if user_profile.get("profile") and user_profile["profile"].get("display_name") and user_profile["profile"]["display_name"].strip():
                jira_query_assignee_name = user_profile["profile"]["display_name"].strip()
            elif user_profile.get("real_name") and user_profile["real_name"].strip():
                jira_query_assignee_name = user_profile["real_name"].strip()
            elif user_profile.get("name") and user_profile["name"].strip():
                jira_query_assignee_name = user_profile["name"].strip()
            if jira_query_assignee_name:
                logger.info(f"Fetched Slack user profile for {slack_user_id_for_query}. Using resolved name for Jira query: '{jira_query_assignee_name}'")
            else:
                logger.warning(f"Could not reliably determine a Jira-like username from Slack profile for {slack_user_id_for_query}. Profile: {user_profile}")
        else:
            logger.error(f"Failed to fetch Slack user info for {slack_user_id_for_query}: {user_info_response.get('error') if user_info_response else 'No response'}")
    except SlackApiError as e:
        logger.error(f"Slack API error fetching user info for {slack_user_id_for_query}: {e.response['error']}")
    except Exception as e:
        logger.error(f"Generic error fetching user info for {slack_user_id_for_query}: {e}", exc_info=True)

    name_for_jql_query = jira_query_assignee_name
    if not name_for_jql_query:
        logger.warning(f"Assignee name for JQL could not be resolved from Slack profile for {slack_user_id_for_query}.")
        try:
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text="Sorry, I couldn't identify your Jira username from your Slack profile to fetch your tickets. Please ensure your Slack profile name/display name is set and similar to your Jira username.")
        except Exception as e_post:
            logger.error(f"Error posting assignee determination failure: {e_post}")
        if thread_ts in conversation_states: del conversation_states[thread_ts]
        if assistant_id: 
            try: client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
            except Exception: pass
        return
    
    period = current_state["data"]["period"]
    status = current_state["data"]["status"]
    logger.info(f"Fetching 'My Tickets' for user (Slack ID: {slack_user_id_for_query}, Using for JQL Assignee: '{name_for_jql_query}') with period: {period}, status: {status} in thread {thread_ts}.")

    if assistant_id:
        try: client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="Fetching your tickets...")
        except Exception as e: logger.error(f"Error setting status for My Tickets fetch: {e}")

    fetched_tickets = fetch_my_jira_tickets(assignee_id=name_for_jql_query, period=period, status=status)

    action_text = "selected criteria"
    if body.get("actions") and isinstance(body["actions"], list) and len(body["actions"]) > 0:
        if body["actions"][0].get("text") and isinstance(body["actions"][0]["text"], dict):
            action_text = body["actions"][0]["text"].get("text", "selected criteria")

    if fetched_tickets is None:
        try:
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text="Sorry, I couldn't fetch your tickets from Jira at the moment.")
        except Exception as e:
            logger.error(f"Error posting fetch_my_jira_tickets failure message: {e}")
    elif not fetched_tickets:
        try:
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=f"No tickets found for you with status '{status}' in the timeframe corresponding to '{action_text}'.")
        except Exception as e:
            logger.error(f"Error posting no tickets found message: {e}")
    else:
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Here are your tickets with status *{status}* (timeframe: *{action_text}*)."}
            }
            # Divider will be added by build_rich_ticket_blocks for each ticket
        ]
        for ticket_data in fetched_tickets[:20]: # Limit to avoid huge messages
            rich_ticket_blocks = build_rich_ticket_blocks(ticket_data) # No action elements for these tickets
            blocks.extend(rich_ticket_blocks)
            
        if len(fetched_tickets) > 20:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"And {len(fetched_tickets) - 20} more..."}]})

        try:
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, blocks=blocks, text=f"Found {len(fetched_tickets)} tickets.")
            logger.info(f"Displayed {len(fetched_tickets)} tickets using rich format for 'My Tickets' in thread {thread_ts}.")
        except SlackApiError as e:
            logger.error(f"Error displaying My Tickets list: {e.response['error']}")

    if thread_ts in conversation_states:
        del conversation_states[thread_ts]
        logger.info(f"Cleared state for 'My Tickets' flow, thread {thread_ts}.")
    if assistant_id:
        try: client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
        except Exception as e: logger.error(f"Error clearing status for My Tickets: {e}") 