# jira_handler.py
import logging
import re
import os # For environment variables
import json # Added for pretty-printing Jira raw data
from jira import JIRA # Import the JIRA library
from jira.exceptions import JIRAError # Import JIRAError for exception handling

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