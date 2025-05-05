# actions_handler.py
import logging
from slack_sdk.errors import SlackApiError # Import SlackApiError
import json # For private_metadata

# Import state store from utils
# from state_manager import conversation_states # Old import
from utils.state_manager import conversation_states # Corrected import

logger = logging.getLogger(__name__)

def build_create_ticket_modal(initial_summary="", initial_description="", private_metadata=""):
    """Builds the Block Kit JSON for the create ticket modal."""
    return {
        "type": "modal",
        "callback_id": "create_ticket_modal_submission", # Identifier for submission
        "private_metadata": private_metadata, # Pass context like channel_id, thread_ts
        "title": {"type": "plain_text", "text": "Create New Jira Ticket"},
        "submit": {"type": "plain_text", "text": "Create"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "summary_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "summary_input",
                    "placeholder": {"type": "plain_text", "text": "Enter a concise summary for the ticket"},
                    "initial_value": initial_summary # Pre-fill if needed
                },
                "label": {"type": "plain_text", "text": "Summary"}
            },
            {
                "type": "input",
                "block_id": "description_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "description_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "Enter a detailed description (optional)"},
                    "initial_value": initial_description # Pre-fill description
                },
                "label": {"type": "plain_text", "text": "Description (Optional)"},
                "optional": True
            },
            {
                "type": "input",
                "block_id": "priority_block",
                "element": {
                    "type": "static_select",
                    "action_id": "priority_select",
                    "placeholder": {"type": "plain_text", "text": "Select priority"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Highest (P0)"}, "value": "P0"},
                        {"text": {"type": "plain_text", "text": "High (P1)"}, "value": "P1"},
                        {"text": {"type": "plain_text", "text": "Medium (P2)"}, "value": "P2"},
                        # Add other priorities (P3, P4) if needed
                        {"text": {"type": "plain_text", "text": "Low (P3)"}, "value": "P3"},
                        {"text": {"type": "plain_text", "text": "Lowest (P4)"}, "value": "P4"}
                    ]
                },
                "label": {"type": "plain_text", "text": "Priority"}
            },
            {
                "type": "input",
                "block_id": "assignee_block",
                "element": {
                    "type": "users_select",
                    "action_id": "assignee_select",
                    "placeholder": {"type": "plain_text", "text": "Select assignee (optional)"}
                },
                "label": {"type": "plain_text", "text": "Assignee (Optional)"},
                "optional": True
            },
            # --- New Optional Fields ---
            {
                "type": "input",
                "block_id": "label_block",
                "element": {
                    "type": "multi_static_select",
                    "action_id": "label_select",
                    "placeholder": {"type": "plain_text", "text": "Select labels (optional)"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "UATBugs_CustomerModule"}, "value": "UATBugs_CustomerModule"},
                        {"text": {"type": "plain_text", "text": "UATBugs_Functional_Defects"}, "value": "UATBugs_Functional_Defects"},
                        {"text": {"type": "plain_text", "text": "UAT_Team_Bugs"}, "value": "UAT_Team_Bugs"}
                        # Note: Custom labels require separate handling/input
                    ]
                },
                "label": {"type": "plain_text", "text": "Labels (Optional)"},
                "optional": True
            },
            {
                "type": "input",
                "block_id": "team_block",
                "element": {
                    "type": "static_select",
                    "action_id": "team_select",
                    "placeholder": {"type": "plain_text", "text": "Select team (optional)"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Platform"}, "value": "platform"},
                        {"text": {"type": "plain_text", "text": "Loyalty"}, "value": "loyalty"},
                        {"text": {"type": "plain_text", "text": "Incentive"}, "value": "incentive"}
                    ]
                },
                "label": {"type": "plain_text", "text": "Owned by Team (Optional)"},
                "optional": True
            },
            {
                "type": "input",
                "block_id": "brand_block",
                "element": {
                    "type": "static_select",
                    "action_id": "brand_select",
                    "placeholder": {"type": "plain_text", "text": "Select brand (optional)"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Tata"}, "value": "tata"},
                        {"text": {"type": "plain_text", "text": "Indigo"}, "value": "indigo"},
                        {"text": {"type": "plain_text", "text": "Shell"}, "value": "shell"}
                    ]
                },
                "label": {"type": "plain_text", "text": "Brand (Optional)"},
                "optional": True
            },
             {
                "type": "input",
                "block_id": "environment_block",
                "element": {
                    "type": "static_select",
                    "action_id": "environment_select",
                    "placeholder": {"type": "plain_text", "text": "Select environment (optional)"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Demo"}, "value": "demo"},
                        {"text": {"type": "plain_text", "text": "Prod"}, "value": "prod"}
                    ]
                },
                "label": {"type": "plain_text", "text": "Environment (Optional)"},
                "optional": True
            },
             {
                "type": "input",
                "block_id": "product_block",
                "element": {
                    "type": "static_select",
                    "action_id": "product_select",
                    "placeholder": {"type": "plain_text", "text": "Select product (optional)"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Platforms"}, "value": "Platforms"}
                    ]
                },
                "label": {"type": "plain_text", "text": "Product (Optional)"},
                "optional": True
            },
             {
                "type": "input",
                "block_id": "task_type_block",
                "element": {
                    "type": "multi_static_select",
                    "action_id": "task_type_select",
                    "placeholder": {"type": "plain_text", "text": "Select task types (optional)"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Code Level"}, "value": "code_level"},
                        {"text": {"type": "plain_text", "text": "DB Level"}, "value": "db_level"},
                        {"text": {"type": "plain_text", "text": "Access"}, "value": "access"}
                        # Note: Custom task types require separate handling/input
                    ]
                },
                "label": {"type": "plain_text", "text": "Type of Task (Optional)"},
                "optional": True
            }
            # TODO: Add Project Key and Issue Type selectors later
            # These often require dynamic population from Jira API
        ]
    }

def handle_create_ticket_action(ack, body, client, logger):
    """Handles the 'Create Ticket' button click by asking for initial summary/description."""
    ack() # Acknowledge the button click immediately
    logger.info("'Create Ticket' button clicked. Asking for initial description.")

    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]
    assistant_id = body.get("assistant", {}).get("id") # Get assistant_id if available

    # Set state to await the user's initial description
    conversation_states[thread_ts] = {
        "step": "awaiting_initial_summary",
        "user_id": user_id,
        "channel_id": channel_id,
        "assistant_id": assistant_id,
        "data": {}
    }
    logger.info(f"Set state for thread {thread_ts} to 'awaiting_initial_summary'")

    # Ask for the initial description
    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Okay, let's start creating a Jira ticket. Please describe the issue or request:"
        )
        if assistant_id:
            client.assistant_threads_setStatus(
                assistant_id=assistant_id,
                thread_ts=thread_ts,
                status=""
            )
    except Exception as e:
        logger.error(f"Error posting initial summary request: {e}")

    # --- Modal opening logic removed from here ---

def handle_summarize_ticket_action(ack, body, client, logger):
    """Handles the 'Summarize Ticket' button click."""
    ack() # Acknowledge the action immediately
    logger.info("'Summarize Ticket' button clicked.")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"] # Get thread_ts from the original message
    assistant_id = body.get("assistant", {}).get("id") # Get assistant_id

    # Set state
    conversation_states[thread_ts] = {
        "step": "awaiting_summary_input",
        "user_id": user_id,
        "channel_id": channel_id,
        "assistant_id": assistant_id,
        "data": {}
    }
    logger.info(f"Set state for thread {thread_ts} to 'awaiting_summary_input'")

    # Ask for Ticket ID or URL
    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Okay, let's summarize a Jira ticket. Please provide the Ticket ID (e.g., PROJ-123) or the full Jira link."
        )
        if assistant_id:
             # Optionally clear status if needed
            client.assistant_threads_setStatus(
                assistant_id=assistant_id,
                thread_ts=thread_ts,
                status=""
            )
        logger.info(f"Asked for Ticket ID/URL for summarization in thread {thread_ts}")
    except SlackApiError as e:
        logger.error(f"Slack API Error posting summarize ticket prompt: {e.response['error']}")
    except Exception as e:
        logger.error(f"Error posting summarize ticket prompt: {e}")

def handle_create_ticket_submission(ack, body, client, logger):
    """Handles the submission of the create ticket modal."""
    
    # Extract submitted data
    view = body["view"]
    state_values = view["state"]["values"]
    
    try:
        summary = state_values["summary_block"]["summary_input"]["value"]
        description = state_values["description_block"]["description_input"].get("value", "") # Optional field
        priority_option = state_values["priority_block"]["priority_select"].get("selected_option")
        priority = priority_option["value"] if priority_option else None # Handle if not selected
        assignee_id = state_values["assignee_block"]["assignee_select"].get("selected_user") # Optional field
        
        # Extract new optional fields
        label_options = state_values["label_block"]["label_select"].get("selected_options", [])
        labels = [opt["value"] for opt in label_options] if label_options else []
        
        team_option = state_values["team_block"]["team_select"].get("selected_option")
        team = team_option["value"] if team_option else None
        
        brand_option = state_values["brand_block"]["brand_select"].get("selected_option")
        brand = brand_option["value"] if brand_option else None
        
        environment_option = state_values["environment_block"]["environment_select"].get("selected_option")
        environment = environment_option["value"] if environment_option else None
        
        product_option = state_values["product_block"]["product_select"].get("selected_option")
        product = product_option["value"] if product_option else None
        
        task_type_options = state_values["task_type_block"]["task_type_select"].get("selected_options", [])
        task_types = [opt["value"] for opt in task_type_options] if task_type_options else []

    except KeyError as e:
        logger.error(f"Error extracting modal submission values: Missing key {e}")
        # Identify block_id from the key error if possible
        block_id_match = str(e).strip("'")
        error_block = block_id_match if block_id_match in ["summary_block", "description_block", "priority_block", "assignee_block", "label_block", "team_block", "brand_block", "environment_block", "product_block", "task_type_block"] else "summary_block" # Default to summary
        ack({"response_action": "errors", "errors": {error_block: f"Error processing input: {e}"}})
        return

    # Basic validation (Summary is required)
    errors = {}
    if not summary or summary.isspace():
        errors["summary_block"] = "Summary cannot be empty."
    # Add more validation if needed (e.g., priority selected)
    if not priority:
         errors["priority_block"] = "Please select a priority."

    if errors:
        ack({"response_action": "errors", "errors": errors})
        logger.warning(f"Modal validation failed: {errors}")
        return

    # Acknowledge the submission if validation passes (clears the modal)
    ack() 
    logger.info("Create ticket modal submission acknowledged.")

    # Extract original context from private_metadata
    try:
        metadata = json.loads(view["private_metadata"])
        original_channel_id = metadata["channel_id"]
        original_thread_ts = metadata["thread_ts"]
        submitter_user_id = metadata["user_id"]
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error parsing private_metadata from modal submission: {e}")
        # We can't easily post back to the original thread, maybe post to user DM?
        # Or log and fail gracefully
        return 
        
    # Collate data for Jira (Placeholder for actual creation)
    ticket_data = {
        "summary": summary,
        "description": description,
        "priority": priority, 
        "assignee_id": assignee_id, # This is the Slack User ID
        # TODO: Map Slack User ID to Jira User ID if necessary
        "labels": labels,
        "team": team,
        "brand": brand,
        "environment": environment,
        "product": product,
        "task_types": task_types
        # TODO: Add Project Key, Issue Type when those fields are added to modal
    }
    logger.info(f"Modal submitted. Data for Jira (placeholder): {ticket_data}")

    # Post confirmation message back to the original thread
    confirmation_text = (
        f"<@{submitter_user_id}> initiated Jira ticket creation:\n"
        f"*Summary*: {summary}\n"
        f"*Priority*: {priority or 'Not Set'}\n"
        f"*Assignee*: {f'<@{assignee_id}>' if assignee_id else 'Unassigned'}\n"
        # Display new fields if selected
        + (f"*Labels*: { ', '.join(labels)}\n" if labels else "")
        + (f"*Team*: {team}\n" if team else "")
        + (f"*Brand*: {brand}\n" if brand else "")
        + (f"*Environment*: {environment}\n" if environment else "")
        + (f"*Product*: {product}\n" if product else "")
        + (f"*Task Types*: { ', '.join(task_types)}\n" if task_types else "")
        + "\n(Simulating ticket creation... Jira API call not implemented yet.)"
    )
    try:
        client.chat_postMessage(
            channel=original_channel_id,
            thread_ts=original_thread_ts,
            text=confirmation_text
        )
        logger.info(f"Posted modal submission confirmation to thread {original_thread_ts}")
    except SlackApiError as e:
        logger.error(f"Slack API Error posting modal confirmation: {e.response['error']}")
    except Exception as e:
        logger.error(f"Error posting modal submission confirmation: {e}") 

def handle_continue_after_ai(ack, body, client, logger):
    """Handles the 'Continue' button click after AI suggestion. Opens the modal."""
    ack()
    logger.info("'Continue after AI' button clicked.")

    trigger_id = body["trigger_id"]
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]

    # Retrieve state
    current_state = conversation_states.get(thread_ts)
    if not current_state or current_state["step"] != "awaiting_ai_confirmation":
        logger.warning(f"Received 'continue_after_ai' action for thread {thread_ts} but state is not awaiting_ai_confirmation: {current_state}")
        # Post error message to user?
        ack() # Need to ack anyway
        try:
             client.chat_postEphemeral(channel=channel_id, thread_ts=thread_ts, user=user_id, text="Sorry, something went wrong. Please try starting over.")
        except Exception as e:
             logger.error(f"Error posting ephemeral error message: {e}")
        return

    # Get stored data
    initial_description = current_state["data"].get("initial_description", "")
    suggested_title = current_state["data"].get("suggested_title", "")

    # Prepare metadata for the modal
    metadata = {
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "user_id": user_id
        # No need to pass title/desc here, they are pre-filled in the view
    }

    try:
        # Build the modal view, pre-filling with suggested title and original description
        modal_view = build_create_ticket_modal(
            initial_summary=suggested_title,
            initial_description=initial_description,
            private_metadata=json.dumps(metadata)
        )

        # Open the modal
        client.views_open(trigger_id=trigger_id, view=modal_view)
        logger.info(f"Opened create ticket modal for user {user_id} after AI confirmation (thread {thread_ts})")
        # Clear state *after* successfully opening modal
        # Or rely on modal submission/cancel to handle state?
        # Let's keep state for now, modal submission will handle it.
        # current_state["step"] = "modal_opened" # Optional intermediate state
        # conversation_states[thread_ts] = current_state

    except SlackApiError as e:
        logger.error(f"Slack API Error opening modal after AI confirm: {e.response['error']}")
    except Exception as e:
        logger.error(f"Error opening create ticket modal after AI confirm: {e}")

def handle_modify_after_ai(ack, body, client, logger):
    """Handles the 'Modify' button click after AI suggestion. Opens the modal for editing."""
    ack()
    logger.info("'Modify after AI' button clicked. Opening modal for editing.")

    trigger_id = body["trigger_id"] # Needed to open a view
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"]

    # Retrieve state
    current_state = conversation_states.get(thread_ts)
    if not current_state or current_state["step"] != "awaiting_ai_confirmation":
        logger.warning(f"Received 'modify_after_ai' action for thread {thread_ts} but state is not awaiting_ai_confirmation: {current_state}")
        try:
             client.chat_postEphemeral(channel=channel_id, thread_ts=thread_ts, user=user_id, text="Sorry, something went wrong. Please try starting over.")
        except Exception as e:
             logger.error(f"Error posting ephemeral error message: {e}")
        return

    # Get stored data to pre-fill the modal
    initial_description = current_state["data"].get("initial_description", "")
    suggested_title = current_state["data"].get("suggested_title", "")

    # Prepare metadata for the modal submission handler
    metadata = {
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "user_id": user_id
    }

    # Open the modal, pre-filled for editing
    try:
        modal_view = build_create_ticket_modal(
            initial_summary=suggested_title,
            initial_description=initial_description,
            private_metadata=json.dumps(metadata)
        )
        client.views_open(trigger_id=trigger_id, view=modal_view)
        logger.info(f"Opened create ticket modal for user {user_id} for modification (thread {thread_ts})")
        # State remains 'awaiting_ai_confirmation' until modal is submitted/cancelled

    except SlackApiError as e:
        logger.error(f"Slack API Error opening modal for modification: {e.response['error']}")
    except Exception as e:
        logger.error(f"Error opening create ticket modal for modification: {e}")

    # --- Old logic removed --- 
    # # Set state back to await the user's new description
    # current_state["step"] = "awaiting_initial_summary"
    # # Clear previous suggestions from data if needed
    # current_state["data"].pop("initial_description", None)
    # current_state["data"].pop("suggested_title", None)
    # conversation_states[thread_ts] = current_state
    # logger.info(f"Set state for thread {thread_ts} back to 'awaiting_initial_summary' for modification.")
    # 
    # # Re-ask for the description
    # try:
    #     client.chat_postMessage(
    #         channel=channel_id,
    #         thread_ts=thread_ts,
    #         text="Okay, let's try again. Please describe the issue or request:"
    #     )
    #     # Clear status if needed (though likely cleared by previous message)
    #     # if assistant_id: client.assistant_threads_setStatus(...)
    # except Exception as e:
    #     logger.error(f"Error re-posting initial summary request for modification: {e}")

def handle_summarize_ticket_action(ack, body, client, logger):
    """Handles the 'Summarize Ticket' button click."""
    ack() # Acknowledge the action immediately
    logger.info("'Summarize Ticket' button clicked.")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    thread_ts = body["message"]["thread_ts"] # Get thread_ts from the original message
    assistant_id = body.get("assistant", {}).get("id") # Get assistant_id

    # Set state
    conversation_states[thread_ts] = {
        "step": "awaiting_summary_input",
        "user_id": user_id,
        "channel_id": channel_id,
        "assistant_id": assistant_id,
        "data": {}
    }
    logger.info(f"Set state for thread {thread_ts} to 'awaiting_summary_input'")

    # Ask for Ticket ID or URL
    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Okay, let's summarize a Jira ticket. Please provide the Ticket ID (e.g., PROJ-123) or the full Jira link."
        )
        if assistant_id:
             # Optionally clear status if needed
            client.assistant_threads_setStatus(
                assistant_id=assistant_id,
                thread_ts=thread_ts,
                status=""
            )
        logger.info(f"Asked for Ticket ID/URL for summarization in thread {thread_ts}")
    except SlackApiError as e:
        logger.error(f"Slack API Error posting summarize ticket prompt: {e.response['error']}")
    except Exception as e:
        logger.error(f"Error posting summarize ticket prompt: {e}") 