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

def handle_modal_submission(ack, body, client, view, logger):
    """Handles the submission of the Jira ticket creation modal."""
    logger.debug("Handling modal submission...")
    
    ack() # Acknowledge immediately

    # --- Extract Data ---
    user_id = body["user"]["id"]
    values = view["state"]["values"]
    private_metadata_str = view.get("private_metadata")
    metadata = {}
    if private_metadata_str:
        try:
            metadata = json.loads(private_metadata_str)
        except json.JSONDecodeError:
            logger.error("Failed to parse private_metadata from modal submission")
            return

    channel_id = metadata.get("channel_id")
    thread_ts = metadata.get("thread_ts")
    thread_summary_for_button = metadata.get("thread_summary", "")
    if not thread_summary_for_button:
        logger.warning("thread_summary not found in private_metadata for 'View Similar Tickets' button.")

    # --- Extract submitted values (SAFELY) ---
    try:
        # Required fields (assuming these have validation or are always selected)
        # project_key = values["project_block"]["project_select_action"]["selected_option"]["value"] # Still assuming project is from env
        issue_type_option = values["issue_type_block"]["issue_type_select"]["selected_option"]
        issue_type_id = issue_type_option["value"] if issue_type_option else None # Should be required, but safe access
        
        title = values["summary_block"]["summary_input"]["value"]
        
        priority_option = values["priority_block"]["priority_select"]["selected_option"]
        priority_id = priority_option["value"] if priority_option else None # Should be required, but safe access

        # Optional fields
        description = values.get("description_block", {}).get("description_input", {}).get("value", "") # Optional text input
        
        assignee_state = values.get("assignee_block", {}).get("assignee_select", {})
        assignee_id = assignee_state.get("selected_user") # users_select provides selected_user directly

        label_state = values.get("label_block", {}).get("label_select", {})
        label_options = label_state.get("selected_options", []) # multi_static_select provides selected_options (list)
        labels = [opt["value"] for opt in label_options] if label_options else []

        team_state = values.get("team_block", {}).get("team_select", {})
        team_option = team_state.get("selected_option") # Get selected option (might be None)
        team = team_option.get("value") if team_option else None # Get value only if option exists
        
        brand_state = values.get("brand_block", {}).get("brand_select", {})
        brand_option = brand_state.get("selected_option")
        brand = brand_option.get("value") if brand_option else None

        environment_state = values.get("environment_block", {}).get("environment_select", {})
        environment_option = environment_state.get("selected_option")
        environment = environment_option.get("value") if environment_option else None

        product_state = values.get("product_block", {}).get("product_select", {})
        product_option = product_state.get("selected_option")
        product = product_option.get("value") if product_option else None

        task_type_state = values.get("task_type_block", {}).get("task_type_select", {})
        task_type_options = task_type_state.get("selected_options", [])
        task_types = [opt["value"] for opt in task_type_options] if task_type_options else []

        root_cause_state = values.get("root_cause_block", {}).get("root_cause_select", {})
        root_cause_options = root_cause_state.get("selected_options", [])
        root_causes = [opt["value"] for opt in root_cause_options] if root_cause_options else []

        # Validation for required fields (if not handled by modal itself)
        if not title or not issue_type_id or not priority_id:
            # This path shouldn't be hit if modal required fields are set, but good failsafe
            logger.error(f"Modal submission missing required field(s). Title: {title}, IssueType: {issue_type_id}, Priority: {priority_id}")
            # Cannot ack() here as ack() was already called. Post ephemeral error.
            if channel_id and user_id:
                client.chat_postEphemeral(channel=channel_id, user=user_id, thread_ts=thread_ts, text="Error: Missing required fields (Title, Issue Type, or Priority) in submission.")
            return

    except KeyError as e:
         # This error should be less likely now with .get() usage
         logger.error(f"Failed to extract value from modal state: Missing key {e}", exc_info=True)
         if channel_id and user_id:
             client.chat_postEphemeral(channel=channel_id, user=user_id, thread_ts=thread_ts, text=f"Error processing modal: issue with field structure {e}.")
         return

    # --- Prepare Jira Payload ---
    project_key_from_env = os.environ.get("TICKET_CREATION_PROJECT_ID")
    if not project_key_from_env:
        logger.error("TICKET_CREATION_PROJECT_ID env var not set! Cannot create ticket.")
        if channel_id and user_id:
            client.chat_postEphemeral(channel=channel_id, user=user_id, thread_ts=thread_ts, text="Error: Jira Project Key not configured. Cannot create ticket.")
        return

    # TODO: Map Slack assignee_id to Jira assignee_id/email if needed
    assignee_jira_id = None
    # TODO: Map Slack submitter user_id to Jira reporter_id/email if needed
    reporter_jira_id = None

    jira_payload = {
        "project_key": project_key_from_env,
        "issue_type": issue_type_id,
        "summary": title,
        "description": description,
        "priority_name": priority_id,
        "assignee_id": assignee_jira_id,
        "reporter_id": reporter_jira_id,
        "labels": labels,
        # Map custom fields (replace customfield_XXXXX with actual IDs from your Jira)
        # Ensure the values (team, brand, env, etc.) are correctly formatted if they are structured fields in Jira
        # For multi-selects (task_types, root_causes), ensure they are passed as a list of {'value': '...'} or similar if required by Jira API
        # "customfield_10010": {"value": team} if team else None, # Example for single select CF
        # "customfield_10011": {"value": brand} if brand else None,
        # "customfield_10012": {"value": environment} if environment else None,
        # "customfield_10013": {"value": product} if product else None,
        # "customfield_10014": [{"value": tt} for tt in task_types] if task_types else None, # Example for multi-select CF
        # "customfield_10015": [{"value": rc} for rc in root_causes] if root_causes else None,
    }
    jira_payload = {k: v for k, v in jira_payload.items() if v is not None and v != []} # Clean empty/None values
    logger.debug(f"Prepared Jira payload: {jira_payload}")

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

            # --- ADD BUTTON CONDITIONALLY (Using thread_summary) ---
            if thread_summary_for_button: # Check if summary is non-empty
                 button_payload = {"thread_summary": thread_summary_for_button} # Store as dict
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
            if channel_id and thread_ts:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=confirmation_text,
                    blocks=success_blocks
                )
            else:
                 logger.warning("Missing channel_id or thread_ts in metadata, cannot post confirmation.")

        else:
            logger.error("Jira ticket creation failed (returned None or missing key).")
            if channel_id and thread_ts:
                 client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text="❌ Failed to create Jira ticket.")
            elif channel_id and user_id:
                 client.chat_postEphemeral(channel=channel_id, user=user_id, text="❌ Failed to create Jira ticket.")

    except Exception as e:
        logger.error(f"Error during Jira ticket creation or posting confirmation: {e}", exc_info=True)
        if channel_id and thread_ts:
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text="❌ An error occurred while creating the Jira ticket.")
        elif channel_id and user_id:
            client.chat_postEphemeral(channel=channel_id, user=user_id, text="❌ An error occurred while creating the Jira ticket.")

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
        block_id_match = str(e).strip("\'")
        error_block_map = {
            "summary_block": "summary_block", "description_block": "description_block",
            "issue_type_block": "issue_type_block", "priority_block": "priority_block", 
            "assignee_block": "assignee_block", "label_block": "label_block", 
            "team_block": "team_block", "brand_block": "brand_block", 
            "environment_block": "environment_block", "product_block": "product_block", 
            "task_type_block": "task_type_block", "root_cause_block": "root_cause_block"
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

    if errors:
        ack({"response_action": "errors", "errors": errors})
        logger.warning(f"Modal validation failed: {errors}")
        return

    ack() 
    logger.info("Create ticket modal submission acknowledged.")

    try:
        metadata = json.loads(view["private_metadata"])
        original_channel_id = metadata["channel_id"]
        original_thread_ts = metadata["thread_ts"]
        submitter_user_id = metadata["user_id"]
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error parsing private_metadata from modal submission: {e}")
        return 
        
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
        "summary": summary, "description": description,
        "project_key": project_key_from_env, "issue_type": issue_type, 
        "priority": priority, "assignee_id": assignee_id,
        "labels": labels, "team": team, "brand": brand,
        "environment": environment, "product": product,
        "task_types": task_types, "root_causes": root_causes
    }
    logger.info(f"Attempting to create Jira ticket with data: {ticket_data_for_jira}")

    jira_response = create_jira_ticket(ticket_data_for_jira)

    if jira_response and jira_response.get("key") and jira_response.get("url"):
        confirmation_text = (
            f"<@{submitter_user_id}>, your Jira ticket has been successfully created!\\n\\n"
            f"*Ticket*: <{jira_response['url']}|{jira_response['key']}>\\n"
            f"*Project*: {project_key_from_env}\\n"
            f"*Issue Type*: {issue_type or 'Not Set'}\\n"
            f"*Summary*: {summary}\\n"
            f"*Priority*: {priority or 'Not Set'}\\n"
            f"*Assignee*: {f'<@{assignee_id}>' if assignee_id else 'Unassigned (or mapping pending)'}\\n"
            + (f"*Labels*: {', '.join(labels)}\\n" if labels else "")
            + (f"*Team*: {team}\\n" if team else "")
            + (f"*Brand*: {brand}\\n" if brand else "")
            + (f"*Environment*: {environment}\\n" if environment else "")
            + (f"*Product*: {product}\\n" if product else "")
            + (f"*Task Types*: {', '.join(task_types)}\\n" if task_types else "")
            + (f"*Root Cause(s)*: {', '.join(root_causes)}\\n" if root_causes else "")
        )
        logger.info(f"Successfully created Jira ticket {jira_response['key']}. Confirmation posted to Slack.")
    else:
        confirmation_text = (
            f"<@{submitter_user_id}>, there was an error creating your Jira ticket. \\n"
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