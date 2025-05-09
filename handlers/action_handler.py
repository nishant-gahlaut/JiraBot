# actions_handler.py
import logging
from slack_sdk.errors import SlackApiError # Import SlackApiError
import json # For private_metadata
import os # Ensure os is imported

# Import state store from utils
# from state_manager import conversation_states # Old import
from utils.state_manager import conversation_states # Corrected import
from services.jira_service import create_jira_ticket # Import the Jira service function
from services.genai_service import generate_jira_details # Ensure GenAI service is imported if not already for the new handler
from services.duplicate_detection_service import summarize_ticket_similarities # Ensure duplicate detection and summarizer are imported for new handlers
from langchain.schema import Document # For reconstructing documents if needed by summarizer

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
                "block_id": "issue_type_block",
                "element": {
                    "type": "static_select",
                    "action_id": "issue_type_select",
                    "placeholder": {"type": "plain_text", "text": "Select issue type"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Task"}, "value": "Task"},
                        {"text": {"type": "plain_text", "text": "Bug"}, "value": "Bug"},
                        {"text": {"type": "plain_text", "text": "Story"}, "value": "Story"},
                        {"text": {"type": "plain_text", "text": "Epic"}, "value": "Epic"}
                    ]
                },
                "label": {"type": "plain_text", "text": "Issue Type"}
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
            },
            {
                "type": "input",
                "block_id": "root_cause_block",
                "element": {
                    "type": "multi_static_select",
                    "action_id": "root_cause_select",
                    "placeholder": {"type": "plain_text", "text": "Select root cause(s) (optional)"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Existing Bug in Application"}, "value": "existing_bug"},
                        {"text": {"type": "plain_text", "text": "Data Issue"}, "value": "data_issue"},
                        {"text": {"type": "plain_text", "text": "Configuration Error"}, "value": "config_error"},
                        {"text": {"type": "plain_text", "text": "New Requirement/Change Request"}, "value": "new_requirement"},
                        {"text": {"type": "plain_text", "text": "Other"}, "value": "other"}
                    ]
                },
                "label": {"type": "plain_text", "text": "Root Cause(s) (Optional)"},
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
        
        issue_type_option = state_values["issue_type_block"]["issue_type_select"].get("selected_option")
        issue_type = issue_type_option["value"] if issue_type_option else None

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

        root_cause_options = state_values["root_cause_block"]["root_cause_select"].get("selected_options", [])
        root_causes = [opt["value"] for opt in root_cause_options] if root_cause_options else []

    except KeyError as e:
        logger.error(f"Error extracting modal submission values: Missing key {e}")
        # Identify block_id from the key error if possible
        block_id_match = str(e).strip("'")
        error_block_map = {
            "summary_block": "summary_block", 
            "description_block": "description_block",
            "issue_type_block": "issue_type_block",
            "priority_block": "priority_block", 
            "assignee_block": "assignee_block", 
            "label_block": "label_block", 
            "team_block": "team_block", 
            "brand_block": "brand_block", 
            "environment_block": "environment_block", 
            "product_block": "product_block", 
            "task_type_block": "task_type_block",
            "root_cause_block": "root_cause_block"
        }
        error_block = error_block_map.get(block_id_match, "summary_block") # Default to summary
        ack({"response_action": "errors", "errors": {error_block: f"Error processing input: {e}"}})
        return

    # Basic validation (Summary is required)
    errors = {}
    if not summary or summary.isspace():
        errors["summary_block"] = "Summary cannot be empty."
    if not issue_type: # Added validation for issue_type
        errors["issue_type_block"] = "Please select an Issue Type."
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
        
    # Collate data for Jira
    project_key_from_env = os.environ.get("TICKET_CREATION_PROJECT_ID")
    if not project_key_from_env:
        logger.error("TICKET_CREATION_PROJECT_ID environment variable not set.")
        try:
            client.chat_postMessage(
                channel=original_channel_id,
                thread_ts=original_thread_ts,
                text=f"<@{submitter_user_id}> I couldn't create the Jira ticket because the Project ID is not configured in the bot. Please contact an administrator."
            )
        except Exception as e_post:
            logger.error(f"Error posting project ID missing message: {e_post}")
        return

    ticket_data_for_jira = {
        "summary": summary,
        "description": description,
        "project_key": project_key_from_env, 
        "issue_type": issue_type, 
        "priority": priority, 
        "assignee_id": assignee_id, # This is the Slack User ID, mapping to Jira ID is a TODO in jira_service
        "labels": labels,
        "team": team, # This and following fields need mapping to custom fields in jira_service if required
        "brand": brand,
        "environment": environment,
        "product": product,
        "task_types": task_types,
        "root_causes": root_causes
    }
    logger.info(f"Attempting to create Jira ticket with data: {ticket_data_for_jira}")

    # Call Jira service to create the ticket
    jira_response = create_jira_ticket(ticket_data_for_jira)

    # Post confirmation message back to the original thread
    if jira_response and jira_response.get("key") and jira_response.get("url"):
        confirmation_text = (
            f"<@{submitter_user_id}>, your Jira ticket has been successfully created!\n\n"
            f"*Ticket*: <{jira_response['url']}|{jira_response['key']}>\n"
            f"*Project*: {project_key_from_env}\n"
            f"*Issue Type*: {issue_type or 'Not Set'}\n"
            f"*Summary*: {summary}\n"
            f"*Priority*: {priority or 'Not Set'}\n"
            f"*Assignee*: {f'<@{assignee_id}>' if assignee_id else 'Unassigned (or mapping pending)'}\n"
            + (f"*Labels*: {', '.join(labels)}\n" if labels else "")
            + (f"*Team*: {team}\n" if team else "") # These custom fields are displayed as is for now
            + (f"*Brand*: {brand}\n" if brand else "")
            + (f"*Environment*: {environment}\n" if environment else "")
            + (f"*Product*: {product}\n" if product else "")
            + (f"*Task Types*: {', '.join(task_types)}\n" if task_types else "")
            + (f"*Root Cause(s)*: {', '.join(root_causes)}\n" if root_causes else "")
        )
        logger.info(f"Successfully created Jira ticket {jira_response['key']}. Confirmation posted to Slack.")
    else:
        confirmation_text = (
            f"<@{submitter_user_id}>, there was an error creating your Jira ticket. \n"
            f"Our team has been notified. Please try again later or contact support if the issue persists."
        )
        logger.error(f"Failed to create Jira ticket. Jira service response: {jira_response}")

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

def handle_proceed_to_ai_title_suggestion(ack, body, client, logger):
    """Handles the 'Proceed with this Description' button after duplicate check."""
    ack()
    logger.info("'Proceed with this Description' button clicked after duplicate check.")
    assistant_id = None # Initialize assistant_id to ensure it has a value in finally if try block fails early
    thread_ts = None # Initialize thread_ts for the same reason

    try:
        action_value = json.loads(body["actions"][0]["value"])
        initial_description = action_value["initial_description"]
        thread_ts = str(action_value["thread_ts"])
        channel_id = str(action_value["channel_id"])
        user_id = str(action_value["user_id"])
        assistant_id = str(action_value.get("assistant_id")) if action_value.get("assistant_id") else None

        logger.info(f"Thread {thread_ts}: Proceeding with description: '{initial_description[:100]}...'" )

        if assistant_id:
            try:
                client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="Generating suggestion...")
                logger.info(f"Thread {thread_ts}: Set status to 'Generating suggestion...'" )
            except Exception as e:
                logger.error(f"Thread {thread_ts}: Error setting status before GenAI for initial title: {e}")

        # Call GenAI to get *suggested title* based on user description
        generated_details = generate_jira_details(initial_description)
        suggested_title = generated_details.get("title", "Suggestion Error")
        logger.info(f"Thread {thread_ts}: GenAI suggested title: '{suggested_title}'" )

        # Store data and update state - THIS IS THE CRITICAL STATE UPDATE
        # that message_handler.py used to do.
        conversation_states[thread_ts] = {
            "step": "awaiting_ai_confirmation",
            "user_id": user_id,
            "channel_id": channel_id,
            "assistant_id": assistant_id,
            "data": {
                "initial_description": initial_description,
                "suggested_title": suggested_title
            }
        }
        logger.info(f"Thread {thread_ts}: Updated state to 'awaiting_ai_confirmation' with data." )

        # Prepare confirmation response with buttons (same as message_handler used to send)
        ai_confirmation_blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Thanks! Based on your description, I suggest the following:\n\n*Suggested Title:* {suggested_title}\n\n*Your Description:*```{initial_description}```\n\nWould you like to proceed with these details or modify them?"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Continue", "emoji": True}, "style": "primary", "action_id": "continue_after_ai"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Modify", "emoji": True}, "action_id": "modify_after_ai"}
                ]
            }
        ]

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=ai_confirmation_blocks,
            text=f"Suggested Title: {suggested_title}"
        )
        logger.info(f"Thread {thread_ts}: Posted AI title suggestion and Continue/Modify buttons." )

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from button value in handle_proceed_to_ai_title_suggestion: {e}")
    except KeyError as e:
        logger.error(f"Missing key in button value in handle_proceed_to_ai_title_suggestion: {e}")
    except SlackApiError as e:
        logger.error(f"Slack API error in handle_proceed_to_ai_title_suggestion: {e.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_proceed_to_ai_title_suggestion: {e}", exc_info=True)
    finally:
        if assistant_id and thread_ts: # Ensure thread_ts is also available
            try:
                client.assistant_threads_setStatus(assistant_id=assistant_id, thread_ts=thread_ts, status="")
                logger.info(f"Thread {thread_ts}: Cleared status after proceeding to AI title suggestion.")
            except Exception as se:
                logger.error(f"Thread {thread_ts}: Error clearing status: {se}")

def handle_summarize_individual_duplicates_from_message(ack, body, client, logger):
    """Handles 'Summarize Individual Tickets' from the duplicate check message."""
    ack()
    logger.info("'Summarize Individual Tickets' button clicked.")

    try:
        action_value = json.loads(body["actions"][0]["value"])
        user_query = action_value["user_query"]
        tickets_data = action_value["tickets_data"]
        original_context = action_value["original_context"]

        thread_ts = str(original_context["thread_ts"])
        channel_id = str(original_context["channel_id"])
        # user_id = str(original_context["user_id"])
        assistant_id = str(original_context.get("assistant_id")) if original_context.get("assistant_id") else None

        logger.info(f"Thread {thread_ts}: Summarizing {len(tickets_data)} individual tickets for query: '{user_query[:50]}...'" )

        if not tickets_data:
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text="No specific tickets were provided to summarize.")
            return

        header_posted = False
        for i, ticket_data_dict in enumerate(tickets_data):
            if not header_posted:
                 client.chat_postMessage(
                    channel=channel_id, 
                    thread_ts=thread_ts, 
                    text=f"📝 Here are individual summaries for the top tickets based on your query: '{user_query[:50]}...'"
                )
                 header_posted = True

            doc_to_summarize = Document(page_content=ticket_data_dict["page_content"], metadata=ticket_data_dict.get("metadata", {}))
            ticket_id_display = ticket_data_dict.get("metadata", {}).get("ticket_id", f"Ticket {i+1}")
            ticket_url_display = ticket_data_dict.get("metadata", {}).get("url")
            
            display_name = f"*{ticket_id_display}*"
            if ticket_url_display:
                display_name = f"*<{ticket_url_display}|{ticket_id_display}>*"

            individual_summary = summarize_ticket_similarities(query=user_query, tickets=[doc_to_summarize])
            
            summary_blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Summary for {display_name}:*\n{individual_summary}"}},
                {"type": "divider"}
            ]
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, blocks=summary_blocks, text=f"Summary for {ticket_id_display}")
            logger.info(f"Thread {thread_ts}: Posted individual summary for {ticket_id_display}." )

        # After individual summaries, offer to continue or cancel
        final_cta_blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "What would you like to do next?"}},
            {
                "type": "actions", 
                "elements": [
                    {
                        "type": "button", 
                        "text": {"type": "plain_text", "text": "Proceed with Original Description"}, 
                        "style": "primary", 
                        "action_id": "proceed_to_ai_title_suggestion", 
                        "value": json.dumps(original_context) # Pass the original full context back
                    },
                    {
                        "type": "button", 
                        "text": {"type": "plain_text", "text": "Cancel Creation"}, 
                        "style": "danger", 
                        "action_id": "cancel_creation_at_message_duplicates",
                        "value": json.dumps({"thread_ts": thread_ts})
                    }
                ]
            }
        ]
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, blocks=final_cta_blocks, text="What would you like to do next?")
        logger.info(f"Thread {thread_ts}: Posted final CTAs after individual summaries." )

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from button value in handle_summarize_individual: {e}")
    except KeyError as e:
        logger.error(f"Missing key in button value in handle_summarize_individual: {e}")
    except SlackApiError as e:
        logger.error(f"Slack API error in handle_summarize_individual: {e.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_summarize_individual: {e}", exc_info=True)

def handle_refine_description_after_duplicates(ack, body, client, logger):
    """Handles 'Refine My Description' button after duplicate check."""
    ack()
    logger.info("'Refine My Description' button clicked.")
    try:
        action_value = json.loads(body["actions"][0]["value"])
        thread_ts = str(action_value["thread_ts"])
        channel_id = str(action_value["channel_id"])
        user_id = str(action_value["user_id"])
        assistant_id = str(action_value.get("assistant_id")) if action_value.get("assistant_id") else None

        # Set state back to await the user's new description
        conversation_states[thread_ts] = {
            "step": "awaiting_initial_summary",
            "user_id": user_id,
            "channel_id": channel_id,
            "assistant_id": assistant_id,
            "data": {} # Clear previous data for this flow
        }
        logger.info(f"Thread {thread_ts}: Set state back to 'awaiting_initial_summary' for refinement." )

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Okay, let's try again. Please provide your refined description for the Jira ticket:"
        )
        logger.info(f"Thread {thread_ts}: Prompted user for refined description." )

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from button value in handle_refine_description: {e}")
    except KeyError as e:
        logger.error(f"Missing key in button value in handle_refine_description: {e}")
    except SlackApiError as e:
        logger.error(f"Slack API error in handle_refine_description: {e.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_refine_description: {e}", exc_info=True)

def handle_cancel_creation_at_message_duplicates(ack, body, client, logger):
    """Handles 'Cancel Ticket Creation' from the duplicate check message step."""
    ack()
    logger.info("'Cancel Ticket Creation' button clicked at duplicate message step.")
    try:
        action_value = json.loads(body["actions"][0]["value"])
        thread_ts = str(action_value["thread_ts"])
        channel_id = body["channel"]["id"]
        user_id = body["user"]["id"]

        if thread_ts in conversation_states:
            del conversation_states[thread_ts]
            logger.info(f"Thread {thread_ts}: Cleared conversation state due to cancellation." )
        
        client.chat_postMessage(
            channel=channel_id, # Post to the channel where button was clicked
                thread_ts=thread_ts,
            text=f"<@{user_id}>, the Jira ticket creation process has been cancelled."
            )
        logger.info(f"Thread {thread_ts}: Posted ticket creation cancellation message." )

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from button value in handle_cancel_creation: {e}")
    except KeyError as e:
        logger.error(f"Missing key in button value in handle_cancel_creation: {e}")
    except SlackApiError as e:
        logger.error(f"Slack API error in handle_cancel_creation: {e.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error in handle_cancel_creation: {e}", exc_info=True) 