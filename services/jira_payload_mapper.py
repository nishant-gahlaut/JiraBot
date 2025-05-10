import logging
import os
import json # For logging and potentially constructing payloads
import requests # For making Jira API calls

logger = logging.getLogger(__name__)

# Define your custom field mappings here
# Format: "slack_field_name_in_ticket_data": "jira_custom_field_id"
# For more complex custom fields (e.g., select lists requiring an object like {"value": "option"}),
# you might need a more elaborate mapping structure or conditional logic below.
# Example:
# CUSTOM_FIELD_CONFIG = {
#     "team": {"id": "customfield_10010", "type": "string_or_select_value"}, # e.g., for a select list: {"value": "TeamA"}
#     "brand": {"id": "customfield_10011", "type": "string"},
#     "environment": {"id": "customfield_10012", "type": "select_name"}, # e.g. if Jira expects {"name": "Prod"}
#     "product": {"id": "customfield_10013", "type": "string"},
#     "task_types": {"id": "customfield_10014", "type": "array_of_strings_or_objects"} # e.g., for multi-select: [{"value": "TypeA"}, {"value": "TypeB"}]
# }
# For now, this is a placeholder. You will need to populate this with your actual IDs.
CUSTOM_FIELD_CONFIG = {
    # Populate with your actual custom field IDs and types based on your Jira setup
    # "team":          {"id": "customfield_12003", "type": "select_value_object"}, # Temporarily commented out
    "brand":         {"id": "customfield_11997", "type": "array_of_value_objects"}, # Assuming multi-select, sending as array of value objects
    # "environment":   {"id": "customfield_11800", "type": "select_value_object"}, # Temporarily commented out
    # "product":       {"id": "customfield_12024", "type": "select_value_object"}, # Temporarily commented out
    # "root_causes":   {"id": "customfield_11920", "type": "array_of_value_objects"}, # Temporarily commented out
    # "task_types": {"id": "customfield_BBBBB", "type": "array_of_value_objects"}, # Placeholder - ID needed
}


def build_jira_payload_fields(ticket_data_from_slack):
    """
    Constructs the 'fields' object for the Jira API payload from Slack ticket data.

    Args:
        ticket_data_from_slack (dict): Data collected from the Slack modal.

    Returns:
        dict: The 'fields' object for the Jira API.
    """
    payload_fields = {
        "project": {
            "key": ticket_data_from_slack["project_key"]
        },
        "summary": ticket_data_from_slack["summary"],
        "issuetype": {
            "name": ticket_data_from_slack["issue_type"]
        }
    }

    # Description (Atlassian Document Format)
    if ticket_data_from_slack.get("description"):
        payload_fields["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": ticket_data_from_slack["description"]
                        }
                    ]
                }
            ]
        }
    
    # New Assignee mapping logic
    assignee_email = ticket_data_from_slack.get("assignee_email")
    if assignee_email:
        logger.info(f"Attempting to map assignee via email: {assignee_email}")
        jira_base_url = os.environ.get("JIRA_BASE_URL")
        jira_user_email_auth = os.environ.get("JIRA_USER_EMAIL") # For auth
        jira_api_token = os.environ.get("JIRA_API_TOKEN")

        if not all([jira_base_url, jira_user_email_auth, jira_api_token]):
            logger.warning("Jira API credentials for user search (JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN) are not fully configured in jira_payload_mapper. Cannot search for assignee.")
        else:
            search_url = f"{jira_base_url.rstrip('/')}/rest/api/3/user/search?query={assignee_email}"
            auth = (jira_user_email_auth, jira_api_token)
            headers = {"Accept": "application/json"}
            try:
                response = requests.get(search_url, headers=headers, auth=auth, timeout=10)
                response.raise_for_status()
                users = response.json()
                active_users = [user for user in users if user.get("active", False)]
                
                if len(active_users) == 1:
                    jira_account_id = active_users[0]["accountId"]
                    payload_fields["assignee"] = {"accountId": jira_account_id}
                    logger.info(f"Successfully mapped Slack user email '{assignee_email}' to Jira accountId '{jira_account_id}' and set assignee.")
                elif len(active_users) == 0:
                    logger.warning(f"No active Jira user found for email '{assignee_email}'. Ticket will be unassigned.")
                else:
                    logger.warning(f"Multiple active Jira users found for email '{assignee_email}'. Cannot determine unique assignee. Ticket will be unassigned. Found: {[(u.get('displayName'), u.get('accountId')) for u in active_users]}")
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP error searching for Jira user with email '{assignee_email}': {e.response.status_code} - {e.response.text}")
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error searching for Jira user with email '{assignee_email}': {e}")
            except Exception as e:
                logger.error(f"Unexpected error searching for Jira user with email '{assignee_email}': {e}")

    # Priority (currently commented out, can be re-enabled and refined here)
    # if ticket_data_from_slack.get("priority"):
    #     priority_value_from_slack = ticket_data_from_slack["priority"]
    #     priority_map = {
    #         "P0": "Highest", "P1": "High", "P2": "Medium",
    #         "P3": "Low", "P4": "Lowest"
    #     }
    #     jira_priority_name = priority_map.get(priority_value_from_slack, priority_value_from_slack) # Fallback to raw value
    #     payload_fields["priority"] = {"name": jira_priority_name}
    #     logger.info(f"Set Jira priority to name: '{jira_priority_name}' based on Slack value '{priority_value_from_slack}'")

    # Labels
    if ticket_data_from_slack.get("labels"):
        labels = ticket_data_from_slack["labels"]
        if isinstance(labels, list) and len(labels) > 0:
            payload_fields["labels"] = labels
        elif isinstance(labels, str) and labels.strip(): # Handle if it's a single string
             payload_fields["labels"] = [label.strip() for label in labels.split(',')]

    # Handle Custom Fields based on CUSTOM_FIELD_CONFIG
    for slack_key, jira_config in CUSTOM_FIELD_CONFIG.items():
        if slack_key in ticket_data_from_slack and ticket_data_from_slack[slack_key] is not None:
            value = ticket_data_from_slack[slack_key]
            jira_field_id = jira_config["id"]
            field_type = jira_config.get("type", "string") # Default to string if type not specified

            if not value and (isinstance(value, list) and not all(v is not None for v in value)): # Skip empty lists or lists with None
                 continue


            logger.info(f"Processing custom field: Slack key='{slack_key}', Jira ID='{jira_field_id}', Type='{field_type}', Value='{value}'")

            if field_type == "string":
                payload_fields[jira_field_id] = str(value)
            elif field_type == "select_value_object": # For single select expecting {"value": "OptionA"}
                payload_fields[jira_field_id] = {"value": str(value)}
            elif field_type == "select_name_object": # For single select expecting {"name": "OptionA"}
                 payload_fields[jira_field_id] = {"name": str(value)}
            elif field_type == "array_of_strings": # For multi-select string values
                if isinstance(value, list):
                    payload_fields[jira_field_id] = [str(v) for v in value if v is not None]
                elif isinstance(value, str): # If it's a comma-separated string for multi-select
                    payload_fields[jira_field_id] = [v.strip() for v in value.split(',') if v.strip()]
            elif field_type == "array_of_value_objects": # For multi-select expecting [{"value": "A"}, {"value": "B"}]
                if isinstance(value, list):
                    payload_fields[jira_field_id] = [{"value": str(v)} for v in value if v is not None]
            elif field_type == "array_of_name_objects": # For multi-select expecting [{"name": "A"}, {"name": "B"}]
                if isinstance(value, list):
                    payload_fields[jira_field_id] = [{"name": str(v)} for v in value if v is not None]
            # Add more type handlers as needed (e.g., number, date, user picker)
            else:
                logger.warning(f"Unknown custom field type '{field_type}' for '{slack_key}'. Storing as string.")
                payload_fields[jira_field_id] = str(value)
            
            # Ensure we don't add the field if its processed value is empty (e.g. an empty list from array_of_strings)
            if jira_field_id in payload_fields and not payload_fields[jira_field_id]:
                del payload_fields[jira_field_id]
                logger.info(f"Removed empty custom field '{jira_field_id}' after processing.")


    logger.debug(f"Constructed payload_fields: {payload_fields}")
    return payload_fields 