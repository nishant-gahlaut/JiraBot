import logging
from utils.slack_ui_helpers import build_rich_ticket_blocks # Import the helper
import json
from slack_sdk.errors import SlackApiError # Ensure this is imported if not already

logger = logging.getLogger(__name__)

MAX_MODAL_TITLE_LENGTH = 24
MAX_BLOCKS_FALLBACK_MSG = "_... remaining tickets truncated due to display limits._"

# Placeholder for build_rich_ticket_blocks if it's in another file or needs to be defined
# def build_rich_ticket_blocks(ticket_data, source, original_ticket_key):
# return [{"type": "section", "text": {"type": "mrkdwn", "text": f"Ticket: {ticket_data.get('ticket_key')}"}}]

# --- NEW MODAL BUILDER --- 
def build_similar_tickets_modal(
    similar_tickets_details: list, 
    channel_id: str = None, 
    source: str = "unknown", 
    original_ticket_key: str = None,
    add_continue_creation_button: bool = False,
    continue_creation_thread_info: dict = None,
    loading_view_id: str = None
):
    """Builds the modal view to display a list of similar tickets."""
    modal_blocks = []
    modal_title = "Similar Tickets" # Default short title
    
    private_metadata_payload = {
        "source": source, 
        "channel_id": channel_id, 
        "original_ticket_key": original_ticket_key,
        "submit_action": None, # Initialize, will be set based on context
        "loading_view_id": loading_view_id
    }

    if not similar_tickets_details:
        modal_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "No similar tickets found or provided."
            }
        })
        modal_title = "No Matches Found"
    else:
        count = len(similar_tickets_details)
        base_title = f"{count} Similar Ticket{'s' if count != 1 else ''}"
        if len(base_title) <= MAX_MODAL_TITLE_LENGTH:
            modal_title = base_title
        elif count > 99:
            modal_title = f"{count}+ Similar"
            if len(modal_title) > MAX_MODAL_TITLE_LENGTH:
                modal_title = "Many Similar Tickets"
        else:
            modal_title = base_title[:MAX_MODAL_TITLE_LENGTH]
            
        for ticket in similar_tickets_details:
            try:
                ticket_data_for_rich_block = {
                    'ticket_key': ticket.get('key', 'N/A'),
                    'url': ticket.get('url', None),
                    'summary': ticket.get('summary', '_Summary not available_'),
                    'status': ticket.get('status', '_Status not available_'),
                    'priority': ticket.get('priority', ''),
                    'assignee': ticket.get('assignee', ''),
                    'owned_by_team': ticket.get('owned_by_team', 'N/A')
                }
                rich_blocks = build_rich_ticket_blocks(ticket_data_for_rich_block, source, original_ticket_key)
                if rich_blocks and rich_blocks[-1].get("type") == "divider":
                    rich_blocks.pop()
                modal_blocks.extend(rich_blocks)

                modal_blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": " "}]
                })

                problem_summary_text = ticket.get('retrieved_problem_statement', '_(Problem summary not available)_')
                if problem_summary_text and problem_summary_text != '_(Problem summary not available)_':
                    problem_lines = [f"> {line.strip()}" for line in problem_summary_text.split('\n') if line.strip()]
                    quoted_problem_summary = "\n".join(problem_lines)
                    modal_blocks.append({
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "💡 *Problem:*"}
                    })
                    if quoted_problem_summary:
                        modal_blocks.append({
                            "type": "context", 
                            "elements": [{"type": "mrkdwn", "text": quoted_problem_summary}]
                        })

                solution_summary_raw = ticket.get('retrieved_solution_summary', '_(Resolution summary not available)_')
                current_ticket_status = ticket.get('status', '').lower()
                solution_label = "🛠️ *Progress Summary:*" if current_ticket_status != "closed" else "🛠️ *Resolution:*"

                if solution_summary_raw and solution_summary_raw != '_(Resolution summary not available)_':
                    lines = []
                    if any(solution_summary_raw.strip().startswith(p) for p in ["- ", "* ", "1. "]): 
                        lines = [line.strip() for line in solution_summary_raw.split('\n') if line.strip()]
                        formatted_solution_summary = "\n".join([f"> {line}" for line in lines])
                    else:
                        lines = [line.strip() for line in solution_summary_raw.split('\n') if line.strip()]
                        formatted_solution_summary = "\n".join([f"> • {line}" for line in lines])
                    
                    if formatted_solution_summary:
                        modal_blocks.append({
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": solution_label}
                        })
                        modal_blocks.append({
                            "type": "context", 
                            "elements": [{"type": "mrkdwn", "text": formatted_solution_summary}]
                        })
                    elif solution_summary_raw:
                        raw_solution_lines = [f"> {line.strip()}" for line in solution_summary_raw.split('\n') if line.strip()]
                        quoted_raw_solution = "\n".join(raw_solution_lines)
                        modal_blocks.append({
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": solution_label}
                        })
                        if quoted_raw_solution:
                            modal_blocks.append({
                                "type": "context", 
                                "elements": [{"type": "mrkdwn", "text": quoted_raw_solution}]
                            })

                if source == "view_similar_tickets_action" and original_ticket_key: # Check for original_ticket_key here
                    modal_blocks.append({
                        "type": "input",
                        "block_id": f"input_link_ticket_{ticket.get('key', 'N/A')}",
                        "label": {"type": "plain_text", "text": " ", "emoji": True},
                        "element": {
                            "type": "checkboxes",
                            "options": [
                                {
                                    "text": {"type": "plain_text", "text": f"Link {ticket.get('key', 'N/A')}", "emoji": True},
                                    "value": ticket.get('key', 'N/A')
                                }
                            ],
                            "action_id": f"checkbox_action_{ticket.get('key', 'N/A')}"
                        },
                        "optional": True
                    })

                if similar_tickets_details.index(ticket) < len(similar_tickets_details) - 1:
                    modal_blocks.append({"type": "divider"})
            except Exception as e:
                logger.error(f"Error building blocks for similar ticket {ticket.get('key', 'N/A')}: {e}", exc_info=True)
                modal_blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"Error displaying ticket {ticket.get('key', 'N/A')}"}
                })
                modal_blocks.append({"type": "divider"})

    if len(modal_blocks) > 100:
        logger.warning(f"Truncating similar tickets modal blocks from {len(modal_blocks)} to 100.")
        modal_blocks = modal_blocks[:99] + [{
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": MAX_BLOCKS_FALLBACK_MSG}]
        }]

    view = {
        "type": "modal",
        "callback_id": "similar_tickets_modal",
        "title": {"type": "plain_text", "text": modal_title, "emoji": True},
        "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
        "blocks": modal_blocks
        # private_metadata will be set after determining submit action
    }

    # Determine submit button and action
    if original_ticket_key and source == "view_similar_tickets_action": # Linking flow from button
        private_metadata_payload["submit_action"] = "link_tickets"
        view["submit"] = {"type": "plain_text", "text": "Link Selected Tickets", "emoji": True}
    elif add_continue_creation_button and not original_ticket_key: # Continue creation flow (no linking involved)
        if continue_creation_thread_info and continue_creation_thread_info.get("channel_id") and continue_creation_thread_info.get("thread_ts"):
            private_metadata_payload["submit_action"] = "continue_creation"
            private_metadata_payload["original_thread_channel_id"] = continue_creation_thread_info.get("channel_id")
            private_metadata_payload["original_thread_ts"] = continue_creation_thread_info.get("thread_ts")
            view["submit"] = {"type": "plain_text", "text": "Continue Create Ticket", "emoji": True}
        else:
            logger.warning("Cannot add 'Continue to Create Ticket' button: missing continue_creation_thread_info.")
    # If no specific submit action is determined, the modal will only have a "Cancel" button.
    
    view["private_metadata"] = json.dumps(private_metadata_payload)
    return view

# --- Loading Modal Builder ---
def build_loading_modal_view(message="Processing your request..."):
    """Builds a simple modal view to show a loading or processing message."""
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Processing...", "emoji": True},
        "close": {"type": "plain_text", "text": "Cancel", "emoji": True}, # Add a close button
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn", 
                    "text": f":hourglass_flowing_sand: {message}"
                 },
            }
        ],
    }

def build_description_capture_modal(private_metadata: str = ""):
    """Builds the Block Kit JSON for the initial modal to capture issue description."""
    return {
        "type": "modal",
        "callback_id": "description_capture_modal_submission", # Unique callback_id
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Describe Your Issue"},
        "submit": {"type": "plain_text", "text": "Next"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "issue_description_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "issue_description_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "Please provide a detailed description of the Jira ticket you want to create..."}
                },
                "label": {"type": "plain_text", "text": "Issue Description"}
            }
        ]
    }

# ... other modal builder functions ... 