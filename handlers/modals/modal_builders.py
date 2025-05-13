import logging
from utils.slack_ui_helpers import build_rich_ticket_blocks # Import the helper

logger = logging.getLogger(__name__)

# --- NEW MODAL BUILDER --- 
def build_similar_tickets_modal(similar_tickets_details: list):
    """Builds the modal view to display a list of similar tickets."""
    modal_blocks = []
    modal_title = "Similar Tickets" # Default short title

    if not similar_tickets_details:
        modal_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "No similar tickets found or provided."
            }
        })
        modal_title = "No Matches Found" # Specific, short title for no results
    else:
        count = len(similar_tickets_details)
        # Construct dynamic title
        base_title = f"{count} Similar Ticket"
        if count != 1:
            base_title += "s"
        
        if len(base_title) <= 24:
            modal_title = base_title
        elif count > 99: # Example: if count is 3 digits or more, "99+ Similar" is short
            modal_title = f"{count}+ Similar"
            if len(modal_title) > 24: # If even that is too long (e.g. 9999+ Similar)
                modal_title = "Many Similar Tickets" # Fallback to a generic short title
        else: # Fallback to simple truncation for counts like 10-99 if they make it too long
            modal_title = base_title[:24]
            
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

                # ADDED: Subtle spacer block between rich ticket details and Problem section
                modal_blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": " "}] # Non-breaking space or just a space
                })

                # --- 2. Problem Summary --- Change to context block for smaller font
                problem_summary_text = ticket.get('retrieved_problem_statement', '_(Problem summary not available)_')
                if problem_summary_text and problem_summary_text != '_(Problem summary not available)_':
                    problem_lines = [f"> {line.strip()}" for line in problem_summary_text.split('\n') if line.strip()]
                    quoted_problem_summary = "\n".join(problem_lines)
                    modal_blocks.append({
                        "type": "context", # CHANGED to context
                        "elements": [ # Context block uses elements array
                            {
                                "type": "mrkdwn",
                                "text": f"💡 *Problem:*\n{quoted_problem_summary}"
                            }
                        ]
                    })

                # --- 3. Solution Summary --- Change to context block for smaller font
                solution_summary_raw = ticket.get('retrieved_solution_summary', '_(Resolution summary not available)_')
                if solution_summary_raw and solution_summary_raw != '_(Resolution summary not available)_':
                    lines = []
                    if any(solution_summary_raw.strip().startswith(p) for p in ["- ", "* ", "1. "]): 
                        lines = [line.strip() for line in solution_summary_raw.split('\n') if line.strip()]
                        formatted_solution_summary = "\n".join([f"> {line}" for line in lines]) # Keep blockquote
                    else:
                        lines = [line.strip() for line in solution_summary_raw.split('\n') if line.strip()]
                        formatted_solution_summary = "\n".join([f"> • {line}" for line in lines]) # Add Slack bullets and blockquote
                    
                    if formatted_solution_summary:
                        modal_blocks.append({
                            "type": "context", # CHANGED to context
                            "elements": [ # Context block uses elements array
                                {
                                    "type": "mrkdwn",
                                    "text": f"🛠️ *Resolution:*\n{formatted_solution_summary}"
                                }
                            ]
                        })
                    elif solution_summary_raw:
                        raw_solution_lines = [f"> {line.strip()}" for line in solution_summary_raw.split('\n') if line.strip()]
                        quoted_raw_solution = "\n".join(raw_solution_lines)
                        modal_blocks.append({
                            "type": "context", # CHANGED to context
                            "elements": [ # Context block uses elements array
                                {
                                    "type": "mrkdwn",
                                    "text": f"🛠️ *Resolution:*\n{quoted_raw_solution}"
                                }
                            ]
                        })

                # --- Divider between entire tickets ---
                # Add a divider only if it's not the last ticket to avoid trailing divider
                if similar_tickets_details.index(ticket) < len(similar_tickets_details) - 1:
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
        
        # Remove the last divider if tickets were added (This logic might be redundant now or needs adjustment)
        # if modal_blocks and modal_blocks[-1].get("type") == "divider":
        #     modal_blocks.pop()

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