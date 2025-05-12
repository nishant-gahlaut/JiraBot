import logging
from utils.slack_ui_helpers import build_rich_ticket_blocks # Import the helper

logger = logging.getLogger(__name__)

# --- NEW MODAL BUILDER --- 
def build_similar_tickets_modal(similar_tickets_details: list):
    """Builds the modal view to display a list of similar tickets."""
    modal_blocks = []
    modal_title = "Potentially Similar Tickets"

    if not similar_tickets_details:
        modal_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "No similar tickets found or provided."
            }
        })
    else:
        # Shorten the title text to comply with Slack's limit (max 24 chars)
        count = len(similar_tickets_details)
        modal_title = f"{count} Similar Ticket{'s' if count != 1 else ''}" 
        # Ensure title is definitely <= 24 chars, truncate if somehow still too long
        if len(modal_title) > 24:
            modal_title = modal_title[:24]
            
        for ticket in similar_tickets_details:
            try:
                # --- 1. Rich Ticket Block (Adapted) ---
                # Extract data needed by build_rich_ticket_blocks
                # Use placeholder/defaults if data is missing from the input dict
                ticket_data_for_rich_block = {
                    'ticket_key': ticket.get('key', 'N/A'),
                    'url': ticket.get('url', None),
                    'summary': ticket.get('summary', '_Summary not available_'),
                    'status': ticket.get('status', '_Status not available_'),
                    # Add other fields if needed/available and expected by build_rich_ticket_blocks
                    # e.g., 'priority', 'assignee', 'issue_type' 
                    'priority': ticket.get('priority', ''), # Assuming priority name is passed
                    'assignee': ticket.get('assignee', ''), # Assuming assignee name is passed
                    'issue_type': ticket.get('issue_type', '') # Assuming issue type name is passed
                }
                # Generate the rich block, but remove the default divider it might add
                rich_blocks = build_rich_ticket_blocks(ticket_data_for_rich_block)
                if rich_blocks and rich_blocks[-1].get("type") == "divider":
                    rich_blocks.pop()
                modal_blocks.extend(rich_blocks)
                
                # --- 2. Problem Summary ---
                problem_summary = ticket.get('retrieved_problem_statement', '_(Problem summary not available)_')
                modal_blocks.append({
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Problem:* {problem_summary}"
                        }
                    ]
                })

                # --- 3. Solution Summary ---
                solution_summary = ticket.get('retrieved_solution_summary', '_(Resolution summary not available)_')
                modal_blocks.append({
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Resolution:* {solution_summary}"
                        }
                    ]
                })

                # --- Divider ---
                modal_blocks.append({"type": "divider"})

            except Exception as e:
                logger.error(f"Error building blocks for similar ticket {ticket.get('key', 'N/A')}: {e}", exc_info=True)
                modal_blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Error displaying ticket {ticket.get('key', 'N/A')}"
                    }
                })
                modal_blocks.append({"type": "divider"})
        
        # Remove the last divider if tickets were added
        if modal_blocks and modal_blocks[-1].get("type") == "divider":
            modal_blocks.pop()

    # Limit blocks to Slack's maximum (100)
    if len(modal_blocks) > 100:
        logger.warning(f"Truncating similar tickets modal blocks from {len(modal_blocks)} to 100.")
        # Keep a context message at the end indicating truncation
        modal_blocks = modal_blocks[:99] + [{
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_... remaining tickets truncated due to display limits._"
                }
            ]
        }]

    # --- Build the final modal view structure ---
    view = {
        "type": "modal",
        "title": {
            "type": "plain_text",
            "text": modal_title,
            "emoji": True
        },
        "close": {
            "type": "plain_text",
            "text": "Close",
            "emoji": True
        },
        "blocks": modal_blocks
    }

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

# ... other modal builder functions ... 