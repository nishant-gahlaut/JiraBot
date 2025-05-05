# jira_handler.py
import logging
import re
# TODO: Add imports for Jira API client library (e.g., from jira import JIRA)

logger = logging.getLogger(__name__)

# TODO: Initialize Jira client using environment variables for URL, username, API token
# jira_options = {'server': os.environ.get("JIRA_URL")}
# jira = JIRA(options=jira_options, basic_auth=(os.environ.get("JIRA_EMAIL"), os.environ.get("JIRA_API_TOKEN")))

def extract_ticket_id_from_input(user_input):
    """Extracts Jira ticket ID (e.g., PROJ-123) from user input (ID or URL)."""
    user_input = user_input.strip()
    logger.info(f"Attempting to extract ticket ID from input: '{user_input}'")
    
    # Regex to find common Jira key format (e.g., ABC-123)
    # Allows 1-10 uppercase letters for project key, followed by a hyphen, then digits.
    jira_key_pattern = r'([A-Z][A-Z0-9]{0,9}-\d+)'
    
    match = re.search(jira_key_pattern, user_input, re.IGNORECASE)
    
    if match:
        ticket_id = match.group(1).upper() # Extract and ensure uppercase
        logger.info(f"Extracted ticket ID: {ticket_id}")
        return ticket_id
    else:
        logger.warning(f"Could not extract a valid Jira ticket ID pattern from input: '{user_input}'")
        return None

def fetch_jira_ticket_data(ticket_id):
    """Fetches Jira ticket data using the Jira API. (Placeholder)"""
    logger.info(f"Fetching Jira data for ticket ID: {ticket_id} (Placeholder)")
    # --- Placeholder Logic ---
    # Simulate fetching data. Replace with actual API call.
    try:
        # Simulate finding the ticket
        if ticket_id == "PROJ-1": # Example known ticket
             return {
                "id": ticket_id,
                "summary": "API returning 500 error on update",
                "description": "The PUT endpoint /api/v1/items/{id} is returning a 500 Internal Server Error when updating an existing item. Logs attached.",
                "status": "Open",
                "assignee": "nishantgahlaut",
                "reporter": "janedoe",
                "priority": "Highest",
                "comments": [
                    {"author": "bob", "body": "Checking server logs now."}, 
                    {"author": "alice", "body": "Could this be related to the database migration last night?"}
                ]
                # Add other relevant fields like labels, components, created date etc.
            }
        else:
             # Simulate ticket not found
             logger.warning(f"Placeholder: Ticket {ticket_id} not found.")
             return None # Or raise a specific exception
    except Exception as e:
        logger.error(f"Error during placeholder Jira data fetch for {ticket_id}: {e}")
        return None
    # --- End Placeholder Logic ---

    # --- Actual Jira API Logic (Example) ---
    # try:
    #     issue = jira.issue(ticket_id)
    #     logger.info(f"Successfully fetched data for {ticket_id} from Jira.")
    #     # Extract relevant data into a dictionary
    #     comments_data = []
    #     for comment in issue.fields.comment.comments:
    #         comments_data.append({
    #             "author": comment.author.displayName, # Or emailAddress
    #             "body": comment.body,
    #             "created": comment.created # Timestamp
    #         })
    #     
    #     return {
    #         "id": issue.key,
    #         "summary": issue.fields.summary,
    #         "description": issue.fields.description,
    #         "status": issue.fields.status.name,
    #         "assignee": issue.fields.assignee.displayName if issue.fields.assignee else None,
    #         "reporter": issue.fields.reporter.displayName,
    #         "priority": issue.fields.priority.name if issue.fields.priority else None,
    #         "labels": issue.fields.labels,
    #         "components": [comp.name for comp in issue.fields.components],
    #         "created": issue.fields.created,
    #         "updated": issue.fields.updated,
    #         "comments": comments_data
    #         # Add other fields as needed
    #     }
    # except Exception as e: # Catch specific JiraError if possible
    #     logger.error(f"Error fetching data for {ticket_id} from Jira API: {e}")
    #     # Handle different errors like not found, permissions etc.
    #     return None
    # --- End Actual Jira API Logic --- 