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
    "brand":         {"id": "customfield_11997", "type": "array_of_value_objects"}, # Changed to array_of_value_objects
    "environment":   {"id": "customfield_11800", "type": "array_of_value_objects"}, # Changed to array_of_value_objects
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
    logger.info(f"build_jira_payload_fields received ticket_data_from_slack: {json.dumps(ticket_data_from_slack, indent=2)}")
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
        labels_input = ticket_data_from_slack["labels"]
        processed_labels = []
        if isinstance(labels_input, list):
            processed_labels = [str(label).strip() for label in labels_input if label and str(label).strip()]
        elif isinstance(labels_input, str) and labels_input.strip():
            processed_labels = [label.strip() for label in labels_input.split(',') if label.strip()]
        
        if processed_labels:
            payload_fields["labels"] = processed_labels
            logger.info(f"Set Jira labels to: {processed_labels}")
        else:
            logger.info("Labels input was provided but resulted in an empty list after processing.")

    # Components (standard Jira field)
    components_value = ticket_data_from_slack.get("components") # This key comes from interaction_handlers.py
    if components_value and isinstance(components_value, str) and components_value.strip():
        component_names = [name.strip() for name in components_value.split(',') if name.strip()]
        if component_names:
            payload_fields["components"] = [{"name": name} for name in component_names]
            logger.info(f"Set Jira components to: {payload_fields['components']}")
        else:
            logger.info("Components value provided but resulted in empty list after parsing.")
    elif components_value: # Log if value is present but not a non-empty string
        logger.warning(f"Components value found but is not a non-empty string: '{components_value}' (type: {type(components_value)})")


    # Handle Custom Fields based on CUSTOM_FIELD_CONFIG
    for slack_key, jira_config in CUSTOM_FIELD_CONFIG.items():
        if slack_key in ticket_data_from_slack and ticket_data_from_slack[slack_key] is not None:
            value = ticket_data_from_slack[slack_key]
            jira_field_id = jira_config["id"]
            field_type = jira_config.get("type", "string") # Default to string if type not specified

            logger.info(f"CUSTOM_FIELD_TRACE: Processing field '{slack_key}'. Input value: '{value}' (Type: {type(value)}), Configured type: '{field_type}'")

            # Skip if value is an empty string for custom fields, or an empty list.
            # None is already checked by "ticket_data_from_slack[slack_key] is not None"
            if isinstance(value, str) and not value.strip():
                logger.info(f"CUSTOM_FIELD_TRACE: Skipping custom field '{slack_key}' because its string value is empty.")
                continue
            if isinstance(value, list) and not value: # Check for empty list explicitly
                logger.info(f"CUSTOM_FIELD_TRACE: Skipping custom field '{slack_key}' because its list value is empty.")
                continue


            logger.info(f"Processing custom field: Slack key='{slack_key}', Jira ID='{jira_field_id}', Type='{field_type}', Value='{value}' (Type: {type(value)})")

            if field_type == "string":
                payload_fields[jira_field_id] = str(value)
                logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' -> Mapped to string: '{str(value)}'")
            elif field_type == "select_value_object": 
                payload_fields[jira_field_id] = {"value": str(value)}
                logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' -> Mapped to select_value_object: {{\"value\": \"{str(value)}\"{{")
            elif field_type == "select_name_object": 
                 payload_fields[jira_field_id] = {"name": str(value)}
                 logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' -> Mapped to select_name_object: {{\"name\": \"{str(value)}\"{{")
            elif field_type == "array_of_strings": 
                processed_values = []
                if isinstance(value, list):
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' (array_of_strings) - input is list. Processing.")
                    processed_values = [str(v).strip() for v in value if v is not None and str(v).strip()]
                elif isinstance(value, str): 
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' (array_of_strings) - input is string. Splitting by comma.")
                    processed_values = [v.strip() for v in value.split(',') if v.strip()]
                if processed_values:
                    payload_fields[jira_field_id] = processed_values
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' -> Mapped to array_of_strings: {processed_values}")
                else:
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' (array_of_strings) - resulted in empty list after processing. Field will not be added.")
            elif field_type == "array_of_value_objects": 
                processed_values = []
                if isinstance(value, list): # If already a list (e.g. from a multi-select modal element)
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' (array_of_value_objects) - input is list. Processing.")
                    processed_values = [str(v).strip() for v in value if v is not None and str(v).strip()]
                elif isinstance(value, str): # If a single string (potentially comma-separated)
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' (array_of_value_objects) - input is string. Splitting by comma.")
                    processed_values = [v.strip() for v in value.split(',') if v.strip()]
                
                logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' (array_of_value_objects) - processed_values before object mapping: {processed_values}")
                if processed_values: # Only add if there are items after processing
                    payload_fields[jira_field_id] = [{"value": str(v)} for v in processed_values]
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' -> Mapped to array_of_value_objects: {payload_fields[jira_field_id]}")
                else:
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' (array_of_value_objects) - resulted in empty list after processing. Field will not be added.")
            elif field_type == "array_of_name_objects": 
                processed_values = []
                if isinstance(value, list):
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' (array_of_name_objects) - input is list. Processing.")
                    processed_values = [str(v).strip() for v in value if v is not None and str(v).strip()]
                elif isinstance(value, str):
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' (array_of_name_objects) - input is string. Splitting by comma.")
                    processed_values = [v.strip() for v in value.split(',') if v.strip()]

                logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' (array_of_name_objects) - processed_values before object mapping: {processed_values}")
                if processed_values: # Only add if there are items after processing
                    payload_fields[jira_field_id] = [{"name": str(v)} for v in processed_values]
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' -> Mapped to array_of_name_objects: {payload_fields[jira_field_id]}")
                else:
                    logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' (array_of_name_objects) - resulted in empty list after processing. Field will not be added.")
            else:
                logger.warning(f"Unknown custom field type '{field_type}' for '{slack_key}'. Storing as string.")
                payload_fields[jira_field_id] = str(value)
                logger.info(f"CUSTOM_FIELD_TRACE: '{slack_key}' -> Mapped to string due to unknown type: '{str(value)}'")
            
            if jira_field_id in payload_fields and not payload_fields[jira_field_id]:
                del payload_fields[jira_field_id]
                logger.info(f"Removed empty custom field '{jira_field_id}' after processing (e.g., array became empty).")


    logger.debug(f"Final constructed payload_fields for Jira: {json.dumps(payload_fields, indent=2)}")
    return payload_fields 