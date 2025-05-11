import logging
import json
import os
from slack_sdk.errors import SlackApiError
from services.jira_service import create_jira_ticket
from utils.state_manager import conversation_states
from utils.slack_ui_helpers import build_rich_ticket_blocks
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
    private_metadata_str = view.get("private_metadata")
    logger.info(f"Modal submitted with view_id 'create_ticket_modal_submission'. Private metadata: {private_metadata_str}")

    user_id = body["user"]["id"]
    state_data = conversation_states.get(private_metadata_str)

    if not state_data:
        ack_text = "Error: Couldn't find context for this submission. Please try starting over."
        logger.error(f"No state found for private_metadata_key: {private_metadata_str} in modal submission.")
        ack(response_action="errors", errors={"summary_block": ack_text}) # Error on a specific field (summary_block as an example)
        return

    submission_channel_id = state_data.get("channel_id")
    submission_thread_ts = state_data.get("thread_ts")
    
    submitted_values = view["state"]["values"]
    jira_title = submitted_values["summary_block"]["summary_input"]["value"]
    jira_description = submitted_values["description_block"]["description_input"]["value"]
    selected_issue_type = submitted_values.get("issue_type_block", {}).get("issue_type_select", {}).get("selected_option", {}).get("value")
    selected_priority = submitted_values.get("priority_block", {}).get("priority_select", {}).get("selected_option", {}).get("value")
    selected_assignee_id = submitted_values.get("assignee_block", {}).get("assignee_select", {}).get("selected_user")
    selected_labels_data = submitted_values.get("label_block", {}).get("label_select", {}).get("selected_options", [])
    selected_labels = [opt["value"] for opt in selected_labels_data] if selected_labels_data else []
    
    assignee_email_to_send = None
    if selected_assignee_id:
        try:
            user_info_response = client.users_info(user=selected_assignee_id)
            if user_info_response and user_info_response.get("ok"):
                assignee_email_to_send = user_info_response.get("user", {}).get("profile", {}).get("email")
                logger.info(f"Fetched email '{assignee_email_to_send}' for Slack user ID '{selected_assignee_id}'")
            else:
                logger.warning(f"Could not fetch profile or email for Slack user ID '{selected_assignee_id}'. API response: {user_info_response.get('error') if user_info_response else 'empty response'}")
        except SlackApiError as e_user:
            logger.error(f"Slack API error fetching user info for {selected_assignee_id}: {e_user.response['error']}")
        except Exception as e_user_generic:
            logger.error(f"Generic error fetching user info for {selected_assignee_id}: {e_user_generic}")

    team_option = submitted_values.get("team_block", {}).get("team_select", {}).get("selected_option")
    selected_team = team_option.get("value") if team_option else None
    brand_option = submitted_values.get("brand_block", {}).get("brand_select", {}).get("selected_option")
    selected_brand = brand_option.get("value") if brand_option else None
    environment_option = submitted_values.get("environment_block", {}).get("environment_select", {}).get("selected_option")
    selected_environment = environment_option.get("value") if environment_option else None
    product_option = submitted_values.get("product_block", {}).get("product_select", {}).get("selected_option")
    selected_product = product_option.get("value") if product_option else None
    selected_task_types_data = submitted_values.get("task_type_block", {}).get("task_type_select", {}).get("selected_options", [])
    selected_task_types = [opt["value"] for opt in selected_task_types_data] if selected_task_types_data else []
    selected_root_causes_data = submitted_values.get("root_cause_block", {}).get("root_cause_select", {}).get("selected_options", [])
    selected_root_causes = [opt["value"] for opt in selected_root_causes_data] if selected_root_causes_data else []

    logger.info(f"Modal submission by {user_id} for state key {private_metadata_str}: Title='{jira_title}', Desc='{jira_description[:50]}...'")
    ack() 

    project_key_from_env = os.environ.get("TICKET_CREATION_PROJECT_ID", "PROJ")
    issue_type_to_create = selected_issue_type if selected_issue_type else "Task"

    ticket_payload_data = {
        "summary": jira_title,
        "description": jira_description,
        "project_key": project_key_from_env, 
        "issue_type": issue_type_to_create,
        "priority": selected_priority,
        "assignee_slack_id": selected_assignee_id,
        "assignee_email": assignee_email_to_send,
        "labels": selected_labels,
        "team": selected_team,
        "brand": selected_brand,
        "environment": selected_environment,
        "product": selected_product,
        "task_types": selected_task_types,
        "root_causes": selected_root_causes
    }
    
    final_confirmation_blocks = []
    fallback_text = ""

    try:
        created_ticket_info = create_jira_ticket(ticket_payload_data)
        logger.info(f"Jira service call returned: {json.dumps(created_ticket_info, indent=2) if created_ticket_info else 'None'}")

        if created_ticket_info and created_ticket_info.get("key"):
            ticket_data_for_blocks = {
                'ticket_key': created_ticket_info["key"],
                'url': created_ticket_info["url"],
                'summary': created_ticket_info.get("title", jira_title),
                'status': created_ticket_info.get("status_name", "N/A"),
                'issue_type': created_ticket_info.get("issue_type_name", issue_type_to_create),
                'assignee': created_ticket_info.get("assignee_name", "Unassigned"),
                'priority': created_ticket_info.get("priority_name", selected_priority if selected_priority else "N/A")
            }
            logger.info(f"Successfully created Jira ticket {ticket_data_for_blocks['ticket_key']} with details: Status='{ticket_data_for_blocks['status']}', Type='{ticket_data_for_blocks['issue_type']}', Assignee='{ticket_data_for_blocks['assignee']}', Priority='{ticket_data_for_blocks['priority']}'")

            fallback_text = f"Ticket {ticket_data_for_blocks['ticket_key']} created: {ticket_data_for_blocks['summary']}"
            
            # Add the initial user message
            final_confirmation_blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<@{user_id}> created a {ticket_data_for_blocks['issue_type']} using Jira Bot"
                }
            })
            
            # Add the rich ticket display (without the divider, as it's the end of this specific display)
            rich_blocks = build_rich_ticket_blocks(ticket_data_for_blocks) # No actions, no divider needed from helper
            if rich_blocks and rich_blocks[-1].get("type") == "divider": # Remove default divider if present
                rich_blocks.pop()
            final_confirmation_blocks.extend(rich_blocks)

        else:
            logger.error(f"Failed to create Jira ticket or parse response. create_jira_ticket response: {created_ticket_info}")
            fallback_text = "⚠️ I tried to create the Jira ticket, but something went wrong. I didn't get all the ticket details back."
            final_confirmation_blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": fallback_text}}]

    except Exception as e:
        logger.error(f"Error creating Jira ticket from modal or building confirmation: {e}", exc_info=True)
        fallback_text = f"❌ Sorry, there was an error creating the Jira ticket: {str(e)}"
        final_confirmation_blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": fallback_text}}]

    if submission_channel_id:
        try:
            logger.info(f"Attempting to post to channel {submission_channel_id}, thread {submission_thread_ts}")
            logger.info(f"Fallback text to be sent: {fallback_text}")
            logger.info(f"Blocks to be sent: {json.dumps(final_confirmation_blocks, indent=2) if final_confirmation_blocks else 'None'}")
            client.chat_postMessage(
                channel=submission_channel_id,
                thread_ts=submission_thread_ts,
                blocks=final_confirmation_blocks,
                text=fallback_text
            )
        except Exception as e_post:
            logger.error(f"Failed to post ticket creation confirmation: {e_post}")
    else:
        logger.error("submission_channel_id missing in state_data, cannot post confirmation.")

    if private_metadata_str in conversation_states:
        del conversation_states[private_metadata_str]
        logger.info(f"Cleared state for modal key {private_metadata_str}")

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
                text=f"<@{submitter_user_id}> I couldn\\'t create the Jira ticket because the Project ID is not configured in the bot. Please contact an administrator."
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