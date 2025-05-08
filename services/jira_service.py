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
    """Fetches a list of ticket IDs assigned to a user based on period and status."""
    if not jira_client:
        logger.error("Jira client is not initialized. Cannot fetch 'My Tickets'.")
        return None

    # Convert period to JQL relative date (e.g., -1w, -2w, -1m)
    # Assuming period_value from action_id (e.g., "1w", "2w", "1m")
    if period == "1m": # Jira often prefers weeks or specific dates for updated
        jql_period = "-4w" # Approximate 1 month as 4 weeks
    else:
        jql_period = f"-{period}"

    # Construct JQL query
    # Note: For assignee, Jira usually expects the Jira username or accountId.
    # If assignee_id is Slack ID, a mapping would be needed in a real scenario.
    # For now, we are assuming assignee_id might be a Jira username or accountId directly.
    # Or, if we want tickets reported BY the user, we'd use `reporter = "{assignee_id}"`
    # For tickets ASSIGNED to the user: `assignee = "{assignee_id}"`
    # Let's assume for "My Tickets" we mean tickets assigned to the user.
    jql_query = f'assignee = "{assignee_id}" AND status = "{status}" AND updated >= {jql_period} ORDER BY updated DESC'
    # If you want to use the JIRA_USER_NAME from .env as the assignee for testing:
    # current_jira_user = os.environ.get("JIRA_USER_NAME")
    # if current_jira_user:
    #     jql_query = f'assignee = "{current_jira_user}" AND status = "{status}" AND updated >= {jql_period} ORDER BY updated DESC'
    # else:
    #     logger.warning("JIRA_USER_NAME not set, cannot reliably query current user's tickets without a specific assignee_id.")
    #     return [] # Return empty if no user to query for
        
    logger.info(f"Executing JQL query for My Tickets: {jql_query}")

    try:
        # Search for issues using JQL
        # maxResults can be adjusted. Fields limited to 'key' for just IDs.
        issues = jira_client.search_issues(jql_query, maxResults=50, fields="key")
        ticket_ids = [issue.key for issue in issues]
        logger.info(f"Found {len(ticket_ids)} tickets for query: {jql_query}")
        return ticket_ids
    except JIRAError as e:
        logger.error(f"JIRA API Error searching issues for 'My Tickets': {e.status_code} - {e.text}")
        return None # Indicate an error occurred
    except Exception as e:
        logger.error(f"Unexpected error searching issues for 'My Tickets': {e}")
        return None 

def create_jira_ticket(ticket_data):
    """
    Creates a Jira ticket using the Jira REST API.

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
        dict: A dictionary with "key", "id", and "url" of the created ticket on success.
        None: On failure.
    """
    jira_base_url = os.environ.get("JIRA_BASE_URL") # e.g., https://your-domain.atlassian.net
    jira_user_email = os.environ.get("JIRA_USER_EMAIL")
    jira_api_token = os.environ.get("JIRA_API_TOKEN")

    if not all([jira_base_url, jira_user_email, jira_api_token]):
        logger.error("Jira API credentials (JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN) are not fully configured.")
        return None

    api_url = f"{jira_base_url.rstrip('/')}/rest/api/3/issue"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    # Construct the payload using the new mapper
    payload_fields = build_jira_payload_fields(ticket_data)
    if not payload_fields:
        logger.error("Failed to build Jira payload fields from ticket_data.")
        return None

    jira_payload = {"fields": payload_fields}

    logger.debug(f"Jira API URL: {api_url}")
    logger.debug(f"Jira API Payload: {json.dumps(jira_payload, indent=2)}")

    try:
        response = requests.post(
            api_url,
            data=json.dumps(jira_payload),
            headers=headers,
            auth=(jira_user_email, jira_api_token),
            timeout=30  # 30 seconds timeout
        )
        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)

        response_data = response.json()
        logger.info(f"Successfully created Jira ticket: {response_data.get('key')}")
        return {
            "id": response_data.get("id"),
            "key": response_data.get("key"),
            "url": f"{jira_base_url.rstrip('/')}/browse/{response_data.get('key')}"
        }

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error creating Jira ticket: {e.response.status_code} - {e.response.text}")
        try:
            error_details = e.response.json()
            logger.error(f"Jira error messages: {error_details.get('errorMessages')}")
            logger.error(f"Jira errors: {error_details.get('errors')}")
        except ValueError: # If response is not JSON
            logger.error("Jira error response was not in JSON format.")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error creating Jira ticket: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while creating Jira ticket: {e}")
        return None

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