import logging

logger = logging.getLogger(__name__)

def get_issue_type_emoji(issue_type_name: str) -> str:
    """Returns an emoji for a given Jira issue type name."""
    if not issue_type_name:
        return "❓" # Default for unknown or missing
    name_lower = issue_type_name.lower()
    if "bug" in name_lower:
        return "🐛"
    elif "story" in name_lower or "user story" in name_lower:
        return "📖"
    elif "task" in name_lower:
        return "✅"
    elif "epic" in name_lower:
        return "⛰️" # Mountain for Epic
    elif "sub-task" in name_lower or "subtask" in name_lower:
        return "🧩" # Puzzle piece for Sub-task
    elif "improvement" in name_lower:
        return "💡"
    elif "spike" in name_lower:
        return "🔬" # Microscope for Spike/Research
    elif "change" in name_lower or "change request" in name_lower:
        return "🔄"
    elif "incident" in name_lower:
        return "🔥"
    elif "problem" in name_lower:
        return "🤔"
    elif "service request" in name_lower or "support request" in name_lower:
        return "🆘" # Switched from 헬 to 🆘 for better compatibility
    else:
        return "📄" # Default document emoji (was " Jira_Issue")

def get_priority_emoji(priority_name: str) -> str:
    """Returns an emoji for a given Jira priority name."""
    if not priority_name:
        return "" # No emoji if no priority
    name_lower = priority_name.lower()
    if "highest" in name_lower or "critical" in name_lower:
        return "❗" # Exclamation mark for highest/critical
    elif "high" in name_lower:
        return "⬆️" # Up arrow for high
    elif "medium" in name_lower:
        return "↔️" # Using left-right arrow for medium (was "➡️")
    elif "low" in name_lower:
        return "⬇️" # Down arrow for low
    elif "lowest" in name_lower:
        return "📉" # Chart decreasing for lowest
    else:
        return "" # No emoji for unmatched or "None"

def build_rich_ticket_blocks(ticket_data: dict, action_elements: list = None) -> list:
    """
    Builds a list of Slack Block Kit blocks for a single richly formatted ticket.

    Args:
        ticket_data (dict): A dictionary containing ticket details:
            'ticket_key': (str) The Jira ticket key (e.g., "PROJ-123").
            'summary': (str) The ticket summary/title.
            'url': (str, optional) The URL to the Jira ticket.
            'status': (str, optional) The ticket status name.
            'priority': (str, optional) The ticket priority name.
            'assignee': (str, optional) The display name of the assignee.
            'issue_type': (str, optional) The name of the issue type.
        action_elements (list, optional): A list of Slack action elements (buttons)
                                          to append to the ticket display.

    Returns:
        list: A list of Slack Block Kit blocks.
    """
    blocks = []

    ticket_key = ticket_data.get('ticket_key', 'Unknown Ticket')
    summary = ticket_data.get('summary', 'No summary available')
    url = ticket_data.get('url')
    status = ticket_data.get('status', 'N/A')
    priority = ticket_data.get('priority', 'N/A')
    assignee = ticket_data.get('assignee', 'Unassigned')
    issue_type = ticket_data.get('issue_type', 'N/A')

    type_emoji = get_issue_type_emoji(issue_type)
    priority_emoji = get_priority_emoji(priority)

    ticket_link_text = f"*<{url}|{ticket_key}: {summary}>*" if url else f"*{ticket_key}: {summary}*"
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": ticket_link_text}
    })

    details_text = f"{type_emoji} *Type:* {issue_type}    {priority_emoji} *Priority:* {priority}\n👤 *Assignee:* {assignee}    📉 *Status:* {status}"
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": details_text}]
    })

    if action_elements and isinstance(action_elements, list) and len(action_elements) > 0:
        blocks.append({
            "type": "actions",
            "elements": action_elements
        })
    
    blocks.append({"type": "divider"})

    return blocks 