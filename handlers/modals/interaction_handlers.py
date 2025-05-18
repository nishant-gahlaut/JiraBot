import logging
import json
import os
from slack_sdk.errors import SlackApiError
from services.jira_service import create_jira_ticket
from utils.state_manager import conversation_states
from utils.slack_ui_helpers import build_rich_ticket_blocks
from .modal_builders import build_similar_tickets_modal
# conversation_states is not directly used by these two functions, so not importing from utils.state_manager yet.
# Other service imports like genai_service are also not needed here.

logger = logging.getLogger(__name__)

def build_create_ticket_modal(initial_summary="", initial_description="", private_metadata="", initial_priority=None, initial_issue_type=None):
    """Builds the Block Kit JSON for the create ticket modal."""
    
    # Define options for priority and issue type
    priority_options = [
        {"text": {"type": "plain_text", "text": "Highest-P0"}, "value": "Highest-P0"},
        {"text": {"type": "plain_text", "text": "High-P1"}, "value": "High-P1"},
        {"text": {"type": "plain_text", "text": "Medium-P2"}, "value": "Medium-P2"},
        {"text": {"type": "plain_text", "text": "Low-P3"}, "value": "Low-P3"}
    ]
    
    issue_type_options = [
        {"text": {"type": "plain_text", "text": "Bug"}, "value": "Bug"},
        {"text": {"type": "plain_text", "text": "Task"}, "value": "Task"},
        {"text": {"type": "plain_text", "text": "Story"}, "value": "Story"},
        {"text": {"type": "plain_text", "text": "Epic"}, "value": "Epic"},
        {"text": {"type": "plain_text", "text": "Other"}, "value": "Other"}
    ]
    
    # Prepare initial_option for priority
    selected_priority_option = None
    if initial_priority:
        for option in priority_options:
            if option["value"] == initial_priority:
                selected_priority_option = option
                break
                
    # Prepare initial_option for issue_type
    selected_issue_type_option = None
    if initial_issue_type:
        for option in issue_type_options:
            if option["value"] == initial_issue_type:
                selected_issue_type_option = option
                break

    modal_definition = {
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
                    "options": issue_type_options
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
                    "options": priority_options
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
                "block_id": "components_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "components_input",
                    "placeholder": {"type": "plain_text", "text": "Enter component(s) (e.g., Backend, API)"}
                },
                "label": {"type": "plain_text", "text": "Components"}
            },
            {
                "type": "input",
                "block_id": "brand_block",
                "element": {
                    "type": "multi_static_select",
                    "action_id": "brand_select",
                    "placeholder": {"type": "plain_text", "text": "Select brand(s)"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "TATA"}, "value": "TATA"},
                        {"text": {"type": "plain_text", "text": "Shell malasia"}, "value": "shell_malasia"},
                        {"text": {"type": "plain_text", "text": "Domino"}, "value": "domino"},
                        {"text": {"type": "plain_text", "text": "Hertz"}, "value": "hertz"}
                    ]
                },
                "label": {"type": "plain_text", "text": "Brand(s)"}
            },
             {
                "type": "input",
                "block_id": "environment_block",
                "element": {
                    "type": "multi_static_select",
                    "action_id": "environment_select",
                    "placeholder": {"type": "plain_text", "text": "Select environment(s)"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Prod"}, "value": "Prod"},
                        {"text": {"type": "plain_text", "text": "Staging"}, "value": "Staging"},
                        {"text": {"type": "plain_text", "text": "Nightly"}, "value": "Nightly"}
                    ]
                },
                "label": {"type": "plain_text", "text": "Environment(s)"}
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
        ]
    }
    
    # Add initial_option if found
    if selected_issue_type_option:
        modal_definition["blocks"][2]["element"]["initial_option"] = selected_issue_type_option
        
    if selected_priority_option:
        modal_definition["blocks"][3]["element"]["initial_option"] = selected_priority_option
        
    return modal_definition

def handle_modal_submission(ack, body, client, view, logger):
    """Handles the submission of the Jira ticket creation modal."""
    logger.debug("Handling modal submission...")
    
    ack() # Acknowledge immediately

    # --- Extract Data ---
    user_id_submitted = body["user"]["id"]
    view = body["view"]
    state_values = view["state"]["values"]
    private_metadata_str = view.get("private_metadata", "{}")
    
    logger.info(f"Modal submitted by user {user_id_submitted}. View ID: {view['id']}. Callback ID: {view['callback_id']}")
    # logger.debug(f"View state values: {json.dumps(state_values, indent=2)}")
    # logger.debug(f"Private metadata string: {private_metadata_str}")

    errors = {}
    title = state_values.get("summary_block", {}).get("summary_input", {}).get("value")
    description = state_values.get("description_block", {}).get("description_input", {}).get("value", "")
    
    # Extract Issue Type
    issue_type_selected_option = state_values.get("issue_type_block", {}).get("issue_type_select", {}).get("selected_option")
    issue_type_id = issue_type_selected_option.get("value") if issue_type_selected_option else None
    
    # Extract Priority
    priority_selected_option = state_values.get("priority_block", {}).get("priority_select", {}).get("selected_option")
    priority_id = priority_selected_option.get("value") if priority_selected_option else None
    
    assignee_id = state_values.get("assignee_block", {}).get("assignee_select", {}).get("selected_user")
    
    label_options = state_values.get("label_block", {}).get("label_select", {}).get("selected_options", [])
    labels = [opt["value"] for opt in label_options] if label_options else []
    
    team_selected_option = state_values.get("team_block", {}).get("team_select", {}).get("selected_option")
    team_id = team_selected_option.get("value") if team_selected_option else None
    
    components_input = state_values.get("components_block", {}).get("components_input", {})
    components_str = components_input.get("value", "")
    components_list = [comp.strip() for comp in components_str.split(',') if comp.strip()] if components_str else []

    brand_options = state_values.get("brand_block", {}).get("brand_select", {}).get("selected_options", [])
    brand_ids = [opt["value"] for opt in brand_options] if brand_options else []
    
    environment_options = state_values.get("environment_block", {}).get("environment_select", {}).get("selected_options", [])
    environment_ids = [opt["value"] for opt in environment_options] if environment_options else []

    product_selected_option = state_values.get("product_block", {}).get("product_select", {}).get("selected_option")
    product_id = product_selected_option.get("value") if product_selected_option else None

    task_type_options = state_values.get("task_type_block", {}).get("task_type_select", {}).get("selected_options", [])
    task_type_ids = [opt["value"] for opt in task_type_options] if task_type_options else []

    root_cause_options = state_values.get("root_cause_block", {}).get("root_cause_select", {}).get("selected_options", [])
    root_cause_ids = [opt["value"] for opt in root_cause_options] if root_cause_options else []

    # Validation (simplified for brevity, add more as needed)
    if not title or len(title.strip()) == 0:
        errors["summary_block"] = "Summary cannot be empty."
    if not issue_type_id:
        errors["issue_type_block"] = "Issue Type is required."
    if not priority_id:
        errors["priority_block"] = "Priority is required."
    if not components_list:
        errors["components_block"] = "Components are required."
    if not brand_ids:
        errors["brand_block"] = "Brand(s) are required."
    if not environment_ids:
        errors["environment_block"] = "Environment(s) are required."

    if errors:
        ack({"response_action": "errors", "errors": errors})
        logger.warning(f"Modal validation failed with errors: {errors}")
        return

    # If no errors, acknowledge the submission to close the modal or update it.
    # For this flow, we will post a message later, so a simple ack() is fine if no immediate update.
    # However, it's good practice to ack quickly. If create_jira_ticket is fast, we can ack with update later.
    # For now, ack to close the modal immediately upon successful validation.
    ack() 
    logger.info("Modal submission validated successfully and acknowledged.")

    try:
        private_metadata = json.loads(private_metadata_str)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse private_metadata: {private_metadata_str}")
        private_metadata = {} # Default to empty dict if parsing fails

    # Extract context for posting confirmation/error messages
    original_channel_id = private_metadata.get("channel_id")
    original_thread_ts = private_metadata.get("thread_ts")
    flow_origin = private_metadata.get("flow_origin", "unknown")
    # User who INITIATED the modal flow (might be different from user_id_submitted if it was a shortcut on another's message)
    user_id_initiated_flow = private_metadata.get("user_id", user_id_submitted)
    thread_summary_for_button = private_metadata.get("thread_summary", "") # For 'View Similar Tickets' button
    ai_summary_for_context = private_metadata.get("ai_summary_for_context") # From mention flow

    # --- Prepare Jira Payload ---
    # Use actual IDs/values extracted from the modal for priority and issue type
    project_key_from_env = os.environ.get("TICKET_CREATION_PROJECT_ID")
    if not project_key_from_env:
        logger.error("TICKET_CREATION_PROJECT_ID environment variable not set. Cannot create ticket.")
        # Notify user in Slack
        if original_channel_id and user_id_initiated_flow:
            try:
                client.chat_postEphemeral(
                    channel=original_channel_id, 
                    user=user_id_initiated_flow, 
                    thread_ts=original_thread_ts,
                    text="Sorry, I can't create a ticket right now. The Jira Project Key is not configured. Please contact an administrator."
                )
            except Exception as e_ephemeral:
                logger.error(f"Failed to send ephemeral message for missing project key: {e_ephemeral}")
        return # Stop processing if project key is missing

    jira_payload = {
        "project_key": project_key_from_env, # <-- Ensure project_key is added
        "summary": title,
        "description": description,
        "issue_type": issue_type_id, 
        "priority": priority_id,   
        "assignee_id": assignee_id,
        "labels": labels,
        "components": components_list, 
        "brand": brand_ids, 
        "environment": environment_ids, 
        "product": product_id,
        "task_types": task_type_ids,
        "root_causes": root_cause_ids,
        "selected_team_value": team_id 
    }
    
    logger.info(f"Attempting to create Jira ticket with payload: {json.dumps(jira_payload, indent=2)}")

    # --- Create Jira Ticket ---
    try:
        created_ticket_details = create_jira_ticket(jira_payload)
        
        if created_ticket_details:
            logger.info(f"Successfully created Jira ticket: {created_ticket_details['key']}")
            
            # --- Build Success Message Blocks ---
            priority_name = priority_id # Use the submitted value as fallback
            
            # --- Prepare dictionary for build_rich_ticket_blocks ---
            ticket_data_for_blocks = {
                'ticket_key': created_ticket_details["key"], # Use 'ticket_key' as expected by the function
                'url': created_ticket_details["url"],
                'summary': title, 
                'status': created_ticket_details.get("status_name", "Open"), 
                'priority': created_ticket_details.get("priority_name", priority_name), 
                'assignee': created_ticket_details.get("assignee_name", "Unassigned"),
                'issue_type': created_ticket_details.get("issue_type_name", issue_type_id)
            }

            # --- Call build_rich_ticket_blocks with the dictionary ---
            success_blocks = build_rich_ticket_blocks(ticket_data=ticket_data_for_blocks)

            # --- ADD BUTTON CONDITIONALLY (Using thread_summary and original_ticket_key) ---
            if thread_summary_for_button: # Check if summary is non-empty
                 button_payload = {"thread_summary": thread_summary_for_button,
                                   "original_ticket_key": created_ticket_details["key"]} # Store as dict
                 button_value = json.dumps(button_payload)
                 if len(button_value) < 2000:
                     similar_tickets_button_block = {
                         "type": "actions",
                         "elements": [
                             {
                                 "type": "button",
                                 "text": {
                                     "type": "plain_text",
                                     "text": "🔍 View Similar Tickets",
                                     "emoji": True
                                 },
                                 "action_id": "view_similar_tickets_modal_button", 
                                 "value": button_value,
                                 "style": "primary"
                             }
                         ]
                     }
                     success_blocks.append(similar_tickets_button_block)
                 else:
                      logger.warning(f"Could not add 'View Similar Tickets' button for ticket {created_ticket_details['key']} - thread_summary too long for button value ({len(button_value)} chars).")
            else:
                 logger.info("No thread_summary available, skipping 'View Similar Tickets' button.")

            # --- Post Success Message to Thread ---
            confirmation_text = f"✅ Ticket <{created_ticket_details['url']}|{created_ticket_details['key']}> created successfully!"
            if original_channel_id and original_thread_ts:
                client.chat_postMessage(
                    channel=original_channel_id,
                    thread_ts=original_thread_ts,
                    text=confirmation_text,
                    blocks=success_blocks
                )
            else:
                 logger.warning("Missing channel_id or thread_ts in metadata, cannot post confirmation.")

        else:
            logger.error("Jira ticket creation failed (returned None or missing key).")
            if original_channel_id and original_thread_ts:
                 client.chat_postMessage(channel=original_channel_id, thread_ts=original_thread_ts, text="❌ Failed to create Jira ticket.")
            elif original_channel_id and user_id_initiated_flow:
                 client.chat_postEphemeral(channel=original_channel_id, user=user_id_initiated_flow, text="❌ Failed to create Jira ticket.")

    except Exception as e:
        logger.error(f"Error during Jira ticket creation or posting confirmation: {e}", exc_info=True)
        if original_channel_id and original_thread_ts:
            client.chat_postMessage(channel=original_channel_id, thread_ts=original_thread_ts, text="❌ An error occurred while creating the Jira ticket.")
        elif original_channel_id and user_id_initiated_flow:
            client.chat_postEphemeral(channel=original_channel_id, user=user_id_initiated_flow, text="❌ An error occurred while creating the Jira ticket.")

def handle_create_ticket_submission(ack, body, client, logger):
    """Handles the submission of the create ticket modal."""
    
    view = body["view"]
    state_values = view["state"]["values"]
    
    try:
        summary = state_values["summary_block"]["summary_input"]["value"]
        description = state_values["description_block"]["description_input"].get("value", "")
        
        issue_type_option = state_values["issue_type_block"]["issue_type_select"].get("selected_option")
        issue_type = issue_type_option["value"] if issue_type_option else None

        priority_option = state_values["priority_block"]["priority_select"].get("selected_option")
        priority = priority_option["value"] if priority_option else None
        assignee_id = state_values["assignee_block"]["assignee_select"].get("selected_user")
        
        label_options = state_values["label_block"]["label_select"].get("selected_options", [])
        labels = [opt["value"] for opt in label_options] if label_options else []
        
        team_option = state_values["team_block"]["team_select"].get("selected_option")
        team = team_option["value"] if team_option else None
        
        # Extract Components (newly added, assuming plain_text_input)
        components_input = state_values.get("components_block", {}).get("components_input", {})
        components = components_input.get("value")
        
        brand_options = state_values["brand_block"]["brand_select"].get("selected_options", [])
        brand = [opt["value"] for opt in brand_options] if brand_options else []
        logger.info(f"Extracted Brand from modal: {brand} (Type: {type(brand)})")
        
        environment_options = state_values["environment_block"]["environment_select"].get("selected_options", [])
        environment = [opt["value"] for opt in environment_options] if environment_options else []
        logger.info(f"Extracted Environment from modal: {environment} (Type: {type(environment)})")
        
        product_option = state_values["product_block"]["product_select"].get("selected_option")
        product = product_option["value"] if product_option else None
        
        task_type_options = state_values["task_type_block"]["task_type_select"].get("selected_options", [])
        task_types = [opt["value"] for opt in task_type_options] if task_types else []

        root_cause_options = state_values["root_cause_block"]["root_cause_select"].get("selected_options", [])
        root_causes = [opt["value"] for opt in root_cause_options] if root_cause_options else []

    except KeyError as e:
        logger.error(f"Error extracting modal submission values: Missing key {e}")
        block_id_match = str(e).strip("\'")
        error_block_map = {
            "summary_block": "summary_block", "description_block": "description_block",
            "issue_type_block": "issue_type_block", "priority_block": "priority_block", 
            "assignee_block": "assignee_block", "label_block": "label_block", 
            "team_block": "team_block", "brand_block": "brand_block", 
            "environment_block": "environment_block", "product_block": "product_block", 
            "task_type_block": "task_type_block", "root_cause_block": "root_cause_block",
            "components_block": "components_block" # Added components_block to map
        }
        error_block = error_block_map.get(block_id_match, "summary_block")
        ack({"response_action": "errors", "errors": {error_block: f"Error processing input: {e}"}})
        return

    errors = {}
    if not summary or summary.isspace():
        errors["summary_block"] = "Summary cannot be empty."
    if not issue_type:
        errors["issue_type_block"] = "Please select an Issue Type."
    if not priority:
         errors["priority_block"] = "Please select a priority."
    if not components or components.isspace(): # Added validation for components
        errors["components_block"] = "Components are required."
    if not brand:
        errors["brand_block"] = "Brand is required."
    if not environment:
        errors["environment_block"] = "Environment is required."

    if errors:
        ack({"response_action": "errors", "errors": errors})
        logger.warning(f"Modal validation failed: {errors}")
        return

    # ack() # This ack() is redundant as it was called at the start of the function or in the error block.
    logger.info("Create ticket modal submission acknowledged and validated.")

    try:
        metadata_str = view.get("private_metadata", "{}") # Get metadata string safely
        metadata = json.loads(metadata_str)
        original_channel_id = metadata.get("channel_id") # Use .get for safety
        original_thread_ts = metadata.get("thread_ts")
        submitter_user_id = metadata.get("user_id") # This might be the user who initiated the modal, not necessarily who submitted

        # Fallback if channel_id or thread_ts is not in metadata (e.g. direct /create command)
        # For direct commands, the initial interaction might not have a channel/thread context stored in private_metadata.
        # The body of the view_submission itself might contain a channel_id if the modal was opened from a message context.
        # However, for a globally submitted modal, body.channel.id might not be present.
        # Safest is to rely on what was put into private_metadata.
        if not original_channel_id and body.get("channel"): # Fallback, but might not exist
            original_channel_id = body["channel"]["id"]
        if not submitter_user_id:
            submitter_user_id = body["user"]["id"] # User who submitted the modal
            
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error parsing private_metadata or missing keys in modal submission: {e}", exc_info=True)
        # Can't reliably post to channel if channel_id is missing.
        # If user_id is available from body, could post ephemeral error.
        if body.get("user", {}).get("id"):
            client.chat_postEphemeral(
                channel=body["user"]["id"], # DM to user if channel context is lost
                user=body["user"]["id"],
                text="Sorry, there was an internal error processing your request (metadata issue). Please try again."
            )
        return 
        
    project_key_from_env = os.environ.get("TICKET_CREATION_PROJECT_ID")
    if not project_key_from_env:
        logger.error("TICKET_CREATION_PROJECT_ID environment variable not set.")
        # Post error message to the original channel if possible
        if original_channel_id and submitter_user_id:
            try:
                client.chat_postMessage(
                    channel=original_channel_id,
                    thread_ts=original_thread_ts, # Post in thread if ts is available
                    text=f"<@{submitter_user_id}> I couldn't create the Jira ticket because the Project ID is not configured in the bot. Please contact an administrator."
                )
            except Exception as e_post:
                logger.error(f"Error posting project ID missing message: {e_post}")
        elif submitter_user_id: # Fallback to DM if channel context is fully lost
            client.chat_postEphemeral(channel=submitter_user_id, user=submitter_user_id, text="Project ID not configured for Jira integration.")
        return

    ticket_data_for_jira = {
        "summary": summary, "description": description,
        "project_key": project_key_from_env, "issue_type": issue_type, 
        "priority_name": priority, # Changed from priority to priority_name to match payload expectations
        "assignee_id": assignee_id,
        "labels": labels, 
        # "team": team, # Custom field mapping will be handled by build_jira_payload_fields
        # "brand": brand,
        # "environment": environment,
        "components_by_name": [comp.strip() for comp in components.split(',')] if components else None, # Pass as list of names
        "product": product,
        "task_types": task_types, 
        "root_causes": root_causes,
        # Pass raw selected values for custom fields that build_jira_payload_fields will map
        "selected_team_value": team, 
        "brand": brand,
        "environment": environment
    }
    # Remove None or empty list values before sending to build_jira_payload_fields, or let it handle them
    logger.info(f"Final ticket_data_for_jira before calling create_jira_ticket: {json.dumps(ticket_data_for_jira, indent=2)}")

    jira_response = create_jira_ticket(ticket_data_for_jira)

    confirmation_blocks = []
    fallback_text = ""

    if jira_response and jira_response.get("key") and jira_response.get("url"):
        logger.info(f"Successfully created Jira ticket {jira_response['key']}. Confirmation posted to Slack.")
        # Use build_rich_ticket_blocks for the main ticket display
        # Ensure the data passed to build_rich_ticket_blocks matches its expectations
        rich_ticket_data = {
            'ticket_key': jira_response["key"],
            'url': jira_response["url"],
            'summary': jira_response.get("title", summary), # Use title from response, fallback to submitted summary
            'status': jira_response.get("status_name", "N/A"),
            'priority': jira_response.get("priority_name", priority),
            'assignee': jira_response.get("assignee_name", f"<@{assignee_id}>" if assignee_id else "Unassigned"),
            'issue_type': jira_response.get("issue_type_name", issue_type)
            # Add other fields like 'owned_by_team' if available and needed by build_rich_ticket_blocks
        }
        confirmation_blocks.extend(build_rich_ticket_blocks(rich_ticket_data))
        fallback_text = f"Ticket {jira_response['key']} created: {jira_response['url']}"

        # --- Add 'View Similar Tickets' Button --- 
        # Using original_ticket_key (which is jira_response["key"]) and thread_summary (if available from metadata)
        original_ticket_key_for_button = jira_response["key"]
        thread_summary_for_similar_button = metadata.get("thread_summary", "") # From original modal context
        
        button_payload_for_similar = {
            "original_ticket_key": original_ticket_key_for_button,
            "thread_summary": thread_summary_for_similar_button,
            "channel_id": original_channel_id, # Carry context for the next modal
            "thread_ts": original_thread_ts   # Carry context for the next modal
        }
        button_value_str = json.dumps(button_payload_for_similar)

        if len(button_value_str) < 2000: # Slack's limit for button value
            confirmation_blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔍 View Similar Tickets", "emoji": True},
                        "action_id": "view_similar_tickets_modal_button",
                        "value": button_value_str,
                        "style": "primary"
                    }
                ]
            })
        else:
            logger.warning(f"Button payload for 'View Similar' too long ({len(button_value_str)}), not adding button.")

    else:
        fallback_text = (
            f"<@{submitter_user_id}>, there was an error creating your Jira ticket. \n"
            f"Our team has been notified. Please try again later or contact support if the issue persists."
        )
        confirmation_blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": fallback_text}
        })
        logger.error(f"Failed to create Jira ticket. Jira service response: {jira_response}")

    # Post the message
    if original_channel_id: # Only post if we have a channel context
        try:
            client.chat_postMessage(
                channel=original_channel_id,
                thread_ts=original_thread_ts, # Will post as a new message if original_thread_ts is None
                text=fallback_text, # Fallback for notifications
                blocks=confirmation_blocks
            )
            logger.info(f"Posted modal submission confirmation to channel {original_channel_id}, thread {original_thread_ts or 'N/A'}.")
        except SlackApiError as e:
            logger.error(f"Slack API Error posting modal confirmation: {e.response['error']}", exc_info=True)
        except Exception as e:
            logger.error(f"Error posting modal submission confirmation: {e}", exc_info=True)
    elif submitter_user_id: # Fallback to DM if no channel context
        try:
            client.chat_postMessage(
                channel=submitter_user_id, # DM to the user who submitted
                text=fallback_text,
                blocks=confirmation_blocks
            )
            logger.info(f"Posted modal submission confirmation via DM to user {submitter_user_id}.")
        except Exception as e_dm:
            logger.error(f"Error posting modal submission confirmation via DM: {e_dm}", exc_info=True) 