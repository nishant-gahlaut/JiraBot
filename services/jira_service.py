# jira_handler.py
import logging
import re
import os # For environment variables
import json # Added for pretty-printing Jira raw data
from jira import JIRA # Import the JIRA library
from jira.exceptions import JIRAError # Import JIRAError for exception handling
import requests # Ensure 'requests' library is installed
from .jira_payload_mapper import build_jira_payload_fields # Import the new mapper

logger = logging.getLogger(__name__)

# Initialize Jira client using environment variables
try:
    JIRA_SERVER = os.environ.get("JIRA_SERVER")
    JIRA_USER_NAME = os.environ.get("JIRA_USER_NAME")
    JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")

    if not all([JIRA_SERVER, JIRA_USER_NAME, JIRA_API_TOKEN]):
        logger.warning("Jira environment variables (JIRA_SERVER, JIRA_USER_NAME, JIRA_API_TOKEN) not fully set. Jira integration will be disabled.")
        jira_client = None
    else:
        jira_options = {'server': JIRA_SERVER}
        jira_client = JIRA(options=jira_options, basic_auth=(JIRA_USER_NAME, JIRA_API_TOKEN))
        logger.info(f"Jira client initialized for server: {JIRA_SERVER}")
except ImportError:
    logger.warning("'jira' library not found. Please install it: pip install jira. Jira integration will be disabled.")
    jira_client = None
except Exception as e: # Catch any other initialization errors
    logger.error(f"Failed to initialize Jira client: {e}. Jira integration will be disabled.")
    jira_client = None

def extract_ticket_id_from_input(user_input):
    """Extracts Jira ticket ID (e.g., PROJ-123) from user input (ID or URL)."""
    user_input = user_input.strip()
    logger.info(f"Attempting to extract ticket ID from input: '{user_input}'")
    
    # Regex to find common Jira key format (e.g., ABC-123 or CAP-147580 based on user example)
    # Allows 1-10 uppercase letters for project key, followed by a hyphen, then digits.
    jira_key_pattern = r'([A-Z][A-Z0-9]{1,9}-\d+)' # Adjusted to ensure project key part is at least 2 chars if it contains numbers too
    
    match = re.search(jira_key_pattern, user_input, re.IGNORECASE)
    
    if match:
        ticket_id = match.group(1).upper() # Extract and ensure uppercase
        logger.info(f"Extracted ticket ID: {ticket_id}")
        return ticket_id
    else:
        logger.warning(f"Could not extract a valid Jira ticket ID pattern from input: '{user_input}'")
        return None

def _fetch_raw_ticket_from_jira(ticket_id):
    """Internal method to fetch raw ticket data from Jira API."""
    if not jira_client:
        logger.error("Jira client is not initialized. Cannot fetch ticket.")
        return None
    
    logger.info(f"Attempting to fetch ticket '{ticket_id}' from Jira API.")
    try:
        issue = jira_client.issue(ticket_id)
        logger.info(f"Successfully fetched raw data for {ticket_id} from Jira.")

        # --- BEGIN: REMOVED INFO level logging for all raw fields ---
        # try:
        #     if issue and hasattr(issue, 'raw') and issue.raw:
        #         logger.info(f"--- All Raw Fields for Jira Ticket {ticket_id} (INFO) ---")
        #         # Pretty print the JSON for better readability in logs
        #         formatted_raw_data = json.dumps(issue.raw, indent=2, sort_keys=True)
        #         for line in formatted_raw_data.splitlines():
        #             logger.info(line)
        #         logger.info(f"--- End of Raw Fields for Jira Ticket {ticket_id} ---")
        #     else:
        #         logger.info(f"No raw data found or issue object is None for {ticket_id} when attempting detailed logging.")
        # except Exception as log_detail_err:
        #     logger.error(f"Error during detailed logging of issue.raw for {ticket_id}: {log_detail_err}")
        # --- END: REMOVED INFO level logging for all raw fields ---

        # Log the raw issue data for debugging field names (Keeping DEBUG level log)
        try:
            logger.debug(f"Raw Jira issue data for {ticket_id}: {issue.raw}")
        except Exception as log_e:
            logger.error(f"Error logging raw issue data: {log_e}")
        return issue
    except JIRAError as e:
        logger.error(f"JIRA API Error for ticket {ticket_id}: Status {e.status_code} - {e.text}")
        if e.status_code == 404:
            logger.warning(f"Ticket {ticket_id} not found in Jira.")
        # Other errors could be 401 (auth), 403 (permissions), etc.
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching {ticket_id} from Jira: {e}")
        return None

def fetch_jira_ticket_data(ticket_id):
    """Fetches the raw Jira issue object for a given ticket ID."""
    logger.info(f"Fetching raw Jira issue object for ticket ID: {ticket_id}")
    
    # Directly return the result of _fetch_raw_ticket_from_jira
    # The raw issue object contains issue.raw (for all fields) and issue.fields (for common attributes)
    # The new clean_jira_data function in data_cleaner.py will process issue.raw
    raw_issue_object = _fetch_raw_ticket_from_jira(ticket_id)
    
    if not raw_issue_object:
        logger.warning(f"_fetch_raw_ticket_from_jira returned None for {ticket_id}.")
        return None
    
    logger.info(f"Successfully fetched raw issue object for {ticket_id}. Downstream will process .raw attribute.")
    return raw_issue_object

def fetch_my_jira_tickets(assignee_id, period, status):
    """Fetches a list of tickets assigned to a user, with details, based on period and status."""
    if not jira_client:
        logger.error("Jira client is not initialized. Cannot fetch 'My Tickets'.")
        return None

    if period == "1m":
        jql_period = "-4w"
    else:
        jql_period = f"-{period}"

    jql_query = f'assignee = "{assignee_id}" AND status = "{status}" AND updated >= {jql_period} ORDER BY updated DESC'
    logger.info(f"Executing JQL query for My Tickets: {jql_query}")

    tickets_with_details = []
    try:
        # Request specific fields needed for rich display
        # Note: 'key' is implicitly returned. Add others explicitly if not covered by a default set.
        fields_to_fetch = ["summary", "status", "priority", "assignee", "issuetype"]
        
        issues = jira_client.search_issues(jql_query, maxResults=50, fields=fields_to_fetch, expand=None) # Explicitly set expand to None or minimal if not needed
        
        jira_base_url_for_link = os.environ.get("JIRA_SERVER", "") # Use JIRA_SERVER for consistency with .env

        for issue in issues:
            assignee_name = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
            priority_name = issue.fields.priority.name if issue.fields.priority else "N/A"
            
            ticket_detail = {
                "ticket_key": issue.key,
                "summary": issue.fields.summary if hasattr(issue.fields, 'summary') else "No summary",
                "url": f"{jira_base_url_for_link.rstrip('/')}/browse/{issue.key}" if jira_base_url_for_link else None,
                "status": issue.fields.status.name if hasattr(issue.fields, 'status') and issue.fields.status else "N/A",
                "priority": priority_name,
                "assignee": assignee_name,
                "issue_type": issue.fields.issuetype.name if hasattr(issue.fields, 'issuetype') and issue.fields.issuetype else "N/A"
            }
            tickets_with_details.append(ticket_detail)
            
        logger.info(f"Found {len(tickets_with_details)} tickets with details for query: {jql_query}")
        return tickets_with_details
        
    except JIRAError as e:
        logger.error(f"JIRA API Error searching issues for 'My Tickets': {e.status_code} - {e.text}")
        return None 
    except AttributeError as ae:
        # This can happen if a field (e.g. issue.fields.assignee) is None and we try to access a sub-attribute like .displayName
        logger.error(f"AttributeError processing issue fields for 'My Tickets' JQL '{jql_query}': {ae}. This might indicate missing data for an issue.", exc_info=True)
        # Depending on strictness, you might return partial results or None
        # For now, let's return what we have, but this indicates a potential data issue or an issue in an unexpected state.
        if tickets_with_details: 
            logger.warning("Returning partially collected ticket details due to AttributeError.")
            return tickets_with_details
        return None # Or an empty list if preferred: []
    except Exception as e:
        logger.error(f"Unexpected error searching issues for 'My Tickets': {e}", exc_info=True)
        return None 

def create_jira_ticket(ticket_data):
    """
    Creates a Jira ticket using the Jira REST API and fetches its details.

    Args:
        ticket_data (dict): A dictionary containing the ticket details, including:
            - summary (str): The summary of the ticket.
            - description (str): The description of the ticket.
            - project_key (str): The Jira project key.
            - issue_type (str): The name of the issue type (e.g., "Task", "Bug").
            - priority (str, optional): The priority of the ticket (e.g., "P0", "P1"). 
                                        Jira might expect a name or an ID here.
                                        This example uses the value directly.
            - assignee_id (str, optional): Slack user ID of the assignee. 
                                           Mapping to Jira accountId will be needed.
            - labels (list, optional): A list of labels.
            # Add other fields from ticket_data as needed for Jira payload

    Returns:
        dict: A dictionary with "key", "id", "url", "title", "status_name", 
              "issue_type_name", "assignee_name", "priority_name" of the created ticket on success.
        None: On failure to create or critical failure to fetch details.
    """
    jira_base_url = os.environ.get("JIRA_BASE_URL") # Reverted to JIRA_BASE_URL
    jira_user_email = os.environ.get("JIRA_USER_EMAIL") # Reverted to JIRA_USER_EMAIL
    jira_api_token = os.environ.get("JIRA_API_TOKEN")

    if not all([jira_base_url, jira_user_email, jira_api_token]):
        logger.error("Jira API credentials (JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN) are not fully configured.") # Updated log message
        return None

    # Endpoint for creating an issue
    create_api_url = f"{jira_base_url.rstrip('/')}/rest/api/3/issue"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload_fields = build_jira_payload_fields(ticket_data)
    if not payload_fields:
        logger.error("Failed to build Jira payload fields from ticket_data.")
        return None

    jira_payload = {"fields": payload_fields}

    logger.debug(f"Jira Create API URL: {create_api_url}")
    logger.debug(f"Jira Create API Payload: {json.dumps(jira_payload, indent=2)}")

    created_ticket_key = None
    created_ticket_id = None
    created_ticket_url = None
    created_ticket_summary = payload_fields.get("summary", "Summary not provided in payload") # Get summary from input

    try:
        # 1. Create the ticket
        response = requests.post(
            create_api_url,
            data=json.dumps(jira_payload),
            headers=headers,
            auth=(jira_user_email, jira_api_token),
            timeout=30
        )
        response.raise_for_status()
        creation_response_data = response.json()
        created_ticket_key = creation_response_data.get("key")
        created_ticket_id = creation_response_data.get("id")
        created_ticket_url = f"{jira_base_url.rstrip('/')}/browse/{created_ticket_key}"
        logger.info(f"Successfully initiated creation of Jira ticket: {created_ticket_key}")

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error creating Jira ticket: {e.response.status_code} - {e.response.text}")
        try:
            error_details = e.response.json()
            logger.error(f"Jira error messages: {error_details.get('errorMessages')}")
            logger.error(f"Jira errors: {error_details.get('errors')}")
        except ValueError: # If response is not JSON
            logger.error("Jira error response was not in JSON format.")
        return None # Failed to create
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error creating Jira ticket: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during Jira ticket creation: {e}")
        return None

    if not created_ticket_key:
        logger.error("Ticket creation seemed to succeed but no key was returned.")
        return None

    # 2. Fetch the newly created ticket to get all details
    try:
        get_issue_url = f"{jira_base_url.rstrip('/')}/rest/api/3/issue/{created_ticket_key}"
        logger.info(f"Fetching details for newly created ticket: {created_ticket_key} from {get_issue_url}")
        
        get_response = requests.get(
            get_issue_url,
            headers=headers,
            auth=(jira_user_email, jira_api_token),
            timeout=30
        )
        get_response.raise_for_status()
        fetched_issue_data = get_response.json()
        
        fields = fetched_issue_data.get("fields", {})
        status_name = fields.get("status", {}).get("name", "N/A")
        issue_type_name = fields.get("issuetype", {}).get("name", "N/A")
        assignee_data = fields.get("assignee")
        assignee_name = assignee_data.get("displayName", "Unassigned") if assignee_data else "Unassigned"
        priority_data = fields.get("priority")
        priority_name = priority_data.get("name", "N/A") if priority_data else "N/A"
        # The summary should be what we sent, but we can confirm from 'fields'
        # title = fields.get("summary", created_ticket_summary) 
        # For consistency, let's use the summary from the input payload, as it's what the user saw/confirmed.
        title = created_ticket_summary

        logger.info(f"Successfully fetched details for ticket {created_ticket_key}: Status='{status_name}', Type='{issue_type_name}', Assignee='{assignee_name}', Priority='{priority_name}'")

        return {
            "id": created_ticket_id,
            "key": created_ticket_key,
            "url": created_ticket_url,
            "title": title,
            "status_name": status_name,
            "issue_type_name": issue_type_name,
            "assignee_name": assignee_name,
            "priority_name": priority_name
        }

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error fetching details for ticket {created_ticket_key}: {e.response.status_code} - {e.response.text}")
        # Fallback: return basic info if detail fetch fails but creation succeeded
        return {
            "id": created_ticket_id,
            "key": created_ticket_key,
            "url": created_ticket_url,
            "title": created_ticket_summary, # Use summary from payload
            "status_name": "N/A",
            "issue_type_name": "N/A", # Or perhaps from initial ticket_data if available
            "assignee_name": "N/A",
            "priority_name": "N/A"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error fetching details for ticket {created_ticket_key}: {e}")
        # Fallback as above
        return { "id": created_ticket_id, "key": created_ticket_key, "url": created_ticket_url, "title": created_ticket_summary, "status_name": "N/A", "issue_type_name": "N/A", "assignee_name": "N/A", "priority_name": "N/A"}
    except Exception as e:
        logger.error(f"Unexpected error fetching details for ticket {created_ticket_key}: {e}")
        # Fallback as above
        return { "id": created_ticket_id, "key": created_ticket_key, "url": created_ticket_url, "title": created_ticket_summary, "status_name": "N/A", "issue_type_name": "N/A", "assignee_name": "N/A", "priority_name": "N/A"}

# Ensure to add calls to this function from your action_handler.py
# Example (in action_handler.py, inside handle_create_ticket_submission):
#
# from services.jira_service import create_jira_ticket # Import the function
#
# ... later in the function ...
# if validation_passes:
#     ack()
#     # ... (extract metadata, collate ticket_data) ...
#     project_key_from_env = os.environ.get("TICKET_CREATION_PROJECT_ID")
#     # ... (handle if project_key_from_env is None) ...
#
#     # Update ticket_data with the correct project key before passing
#     current_ticket_data = { 
#         "summary": summary, 
#         "description": description,
#         "project_key": project_key_from_env, # Crucial: use the env var
#         "issue_type": issue_type,
#         "priority": priority,
#         "assignee_id": assignee_id, # Slack ID, needs mapping
#         "labels": labels
#         # ... add other fields collected from modal ...
#     }
#
#     jira_response = create_jira_ticket(current_ticket_data)
#
#     if jira_response:
#         confirmation_text = f"Successfully created Jira ticket: <{jira_response['url']}|{jira_response['key']}>"
#         # ... (add more details to confirmation_text if needed) ...
#     else:
#         confirmation_text = "Failed to create Jira ticket. Please check logs or contact an admin."
#
#     client.chat_postMessage(channel=original_channel_id, thread_ts=original_thread_ts, text=confirmation_text)


# Placeholder for other existing functions
# def fetch_my_jira_tickets(assignee_id, period, status): ...
# def fetch_jira_ticket_data(ticket_id): ...
# def prepare_ticket_data_for_summary(raw_jira_issue, ticket_id): ...
# def summarize_jira_ticket(ticket_data_for_summary): ... 