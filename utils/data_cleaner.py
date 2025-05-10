# utils/data_cleaner.py
import logging
import re
import json # Ensure json is imported for pretty printing
from datetime import datetime

logger = logging.getLogger(__name__)

def _parse_comment_body(body):
    """(Helper) Extracts mentions and cleans the comment body."""
    # Simple regex for Jira mentions like [~accountId:...] or [~username]
    mention_pattern = r'\[~(\w+):([a-zA-Z0-9\-:]+)\]|\[~([a-zA-Z0-9_\-\.]+)\]'
    mentions = []
    cleaned_body = body
    try:
        # Find all mentions
        for match in re.finditer(mention_pattern, body):
            # Extract accountId or username
            mention_id = match.group(2) or match.group(3)
            if mention_id:
                mentions.append(mention_id)
            # Remove the raw mention syntax for cleaner text (optional)
            # cleaned_body = cleaned_body.replace(match.group(0), f"(mention:{mention_id})") # Or just remove
            cleaned_body = cleaned_body.replace(match.group(0), "") # Simple removal

        # Optional: Remove Jira formatting like {code}, *bold*, etc. (Add more as needed)
        cleaned_body = re.sub(r'\{code(:.*?)?\}(.*?)\{code\}', r'\2', cleaned_body, flags=re.DOTALL) # Remove code blocks
        cleaned_body = cleaned_body.replace('*', '') # Remove bold markers
        cleaned_body = cleaned_body.replace('_', '') # Remove italic markers
        # Add more complex cleaning (links, images etc.) if necessary
        
        cleaned_body = cleaned_body.strip()

    except Exception as e:
        logger.error(f"Error parsing comment body: {e}")
        # Return original body on error
        return body, [] 
        
    return cleaned_body, mentions

def _get_custom_field_value(raw_fields, field_id, default=None):
    """Helper to get custom field value, handling common structures."""
    field_data = raw_fields.get(field_id)
    if field_data:
        if isinstance(field_data, dict):
            # Common for select lists, user pickers, etc.
            return field_data.get('value', field_data.get('name', default))
        elif isinstance(field_data, list) and field_data:
            # Common for multi-select lists
            return [item.get('value', item.get('name', str(item))) for item in field_data if isinstance(item, dict)]
        # Simple text or number field
        return field_data
    return default

def clean_jira_data(raw_issue_data, ticket_id):
    """
    Cleans and restructures raw Jira issue data.
    raw_issue_data is expected to be the 'raw' attribute of a Jira issue object (a dictionary).
    """
    if not raw_issue_data or not isinstance(raw_issue_data, dict):
        logger.warning(f"No raw issue data provided or not a dictionary for ticket {ticket_id}. Cannot clean.")
        return None

    logger.info(f"Generically cleaning raw data for ticket: {ticket_id}")
    
    cleaned_data = {'ticket_id': ticket_id}
    fields = raw_issue_data.get('fields', {})

    try:
        # --- Standard/Common Fields ---
        cleaned_data['summary'] = fields.get('summary', '').strip()
        cleaned_data['description'] = (fields.get('description') or '').strip()
        cleaned_data['status'] = fields.get('status', {}).get('name', 'Unknown')
        cleaned_data['priority'] = fields.get('priority', {}).get('name', 'Unknown')
        cleaned_data['issue_type'] = fields.get('issuetype', {}).get('name', 'Unknown')
        cleaned_data['reporter'] = fields.get('reporter', {}).get('displayName', 'Unknown')
        assignee_field = fields.get('assignee')
        cleaned_data['assignee'] = assignee_field.get('displayName') if assignee_field else None
        cleaned_data['created_at'] = fields.get('created')
        cleaned_data['updated_at'] = fields.get('updated')
        cleaned_data['labels'] = fields.get('labels', [])
        cleaned_data['components'] = [comp.get('name') for comp in fields.get('components', []) if comp.get('name')]

        # --- Custom Fields (Identified from logs or placeholders) ---
        # You'll need to find the correct customfield_XXXXX from your Jira's raw issue output
        
        # Identified from CAP-142897 log:
        cleaned_data['owned_by_team'] = _get_custom_field_value(fields, 'customfield_12003') # e.g., "Customer Success"
        cleaned_data['brand'] = _get_custom_field_value(fields, 'customfield_11997') # e.g., ["Shell India", "Shell Indonesia"]
        cleaned_data['product'] = _get_custom_field_value(fields, 'customfield_12024') # e.g., "Platforms"
        cleaned_data['geo_region'] = _get_custom_field_value(fields, 'customfield_11998') # e.g., "SEA"
        
        # Identified from user input - Handles single or multi-select:
        cleaned_data['environment'] = _get_custom_field_value(fields, 'customfield_11800') 
        
        # Identified from CAP-146316 log:
        cleaned_data['root_cause'] = _get_custom_field_value(fields, 'customfield_11920') # e.g., ["Existing Bug in Application"]

        # --- Sprint Field (customfield_10016) --- 
        sprint_info = []
        raw_sprint_data = fields.get('customfield_10016')
        if isinstance(raw_sprint_data, list):
            for sprint_str in raw_sprint_data:
                if isinstance(sprint_str, str):
                    # Extract name using regex from strings like '...name=Sprint Alpha,state=ACTIVE...'
                    match = re.search(r'name=([^,]+)', sprint_str)
                    if match:
                        sprint_info.append(match.group(1).strip())
                    else:
                        logger.warning(f"Could not parse sprint name from raw string: {sprint_str}")
                        # sprint_info.append(sprint_str) # Option: include raw string if parsing fails
        elif raw_sprint_data:
             logger.warning(f"Unexpected format for sprint data (customfield_10016): {type(raw_sprint_data)}")
             # Potentially handle other formats if needed

        cleaned_data['sprint'] = sprint_info if sprint_info else None # Store list of names or None

        # --- Clean Comments ---
        comment_data = fields.get('comment', {})
        raw_comments = comment_data.get('comments', [])
        cleaned_comments = []
        
        def parse_jira_date(date_str):
            if not date_str: return None
            # Python's %z can handle offsets like +0530 or -0700 directly if they don't have a colon.
            # If Jira ever includes a colon (e.g., +05:30), this might need adjustment or preprocessing.
            # The format YYYY-MM-DDTHH:MM:SS.mmm+ZZZZ (e.g., 2025-04-27T10:11:35.923+0530)
            # matches "%Y-%m-%dT%H:%M:%S.%f%z"
            try: 
                return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z")
            except ValueError: 
                # Fallback for dates that might not have microseconds (less common from APIs but possible)
                try:
                    return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S%z")
                except ValueError:
                    logger.warning(f"Could not parse date string with multiple formats: {date_str}")
                    return None

        sorted_comments = sorted(
            raw_comments, 
            key=lambda c: parse_jira_date(c.get('created')) or datetime.min
        )

        for comment in sorted_comments:
            cleaned_body, mentions = _parse_comment_body(comment.get('body', ''))
            cleaned_comments.append({
                'author': comment.get('author', {}).get('displayName', 'Unknown'),
                'timestamp': comment.get('created'),
                'cleaned_body': cleaned_body,
                'mentions': mentions
            })
            
        cleaned_data['comments'] = cleaned_comments

        logger.info(f"Generic data cleaning complete for ticket {ticket_id}. Found {len(cleaned_comments)} comments.")
        return cleaned_data

    except Exception as e:
        logger.error(f"Unexpected error during generic data cleaning for ticket {ticket_id}: {e}", exc_info=True)
        return None

def prepare_ticket_data_for_summary(raw_issue_data, ticket_id):
    """
    Cleans raw Jira data and then prepares a subset of it specifically for summarization.
    raw_issue_data is expected to be the 'raw' attribute of a Jira issue object.
    """
    logger.info(f"Preparing ticket data for summarization: {ticket_id}")
    
    # Step 1: Get all cleaned data
    comprehensively_cleaned_data = clean_jira_data(raw_issue_data, ticket_id)

    # --- BEGIN: Added log for comprehensively_cleaned_data ---
    if comprehensively_cleaned_data:
        logger.info(f"--- Comprehensively Cleaned Data for {ticket_id} (before summarization filtering) ---")
        try:
            formatted_cleaned_data = json.dumps(comprehensively_cleaned_data, indent=2, sort_keys=True, default=str) # default=str for datetime objects
            for line in formatted_cleaned_data.splitlines():
                logger.info(line)
            logger.info(f"--- End of Comprehensively Cleaned Data for {ticket_id} ---")
        except Exception as log_err:
            logger.error(f"Error logging comprehensively_cleaned_data for {ticket_id}: {log_err}")
            logger.info(f"Comprehensively Cleaned Data (raw fallback) for {ticket_id}: {comprehensively_cleaned_data}") # Fallback log
    else:
        logger.info(f"comprehensively_cleaned_data is None for {ticket_id}, skipping detailed log.")
    # --- END: Added log for comprehensively_cleaned_data ---

    if not comprehensively_cleaned_data:
        logger.warning(f"Comprehensive cleaning failed for {ticket_id}. Cannot prepare for summary.")
        return None

    # Step 2: Select fields relevant for summarization
    summary_relevant_data = {
        'ticket_id': comprehensively_cleaned_data.get('ticket_id'),
        'summary': comprehensively_cleaned_data.get('summary'),
        'description': comprehensively_cleaned_data.get('description'),
        'status': comprehensively_cleaned_data.get('status'),
        'priority': comprehensively_cleaned_data.get('priority'),
        'comments': comprehensively_cleaned_data.get('comments', []),
        'labels': comprehensively_cleaned_data.get('labels', []),
        'components': comprehensively_cleaned_data.get('components', []),
        # Add the custom fields here IF they were successfully extracted by clean_jira_data
        # Ensure these keys match what clean_jira_data produces (e.g., 'owned_by_team')
        # 'owned_by_team': comprehensively_cleaned_data.get('owned_by_team'),
        # 'brand': comprehensively_cleaned_data.get('brand'),
        # 'product': comprehensively_cleaned_data.get('product'),
        # 'geo_region': comprehensively_cleaned_data.get('geo_region'),
        # 'environment': comprehensively_cleaned_data.get('environment'),
        # Only include if they exist to avoid passing None or empty values unless desired
    }
    
    # Add custom fields if they exist and are not None
    custom_field_keys_for_summary = [
        'owned_by_team', 'brand', 'product', 'geo_region', 'environment', 'root_cause', 'sprint' 
        # Add the actual keys used in clean_jira_data once you define them based on customfield_ IDs
    ]
    for key in custom_field_keys_for_summary:
        if key in comprehensively_cleaned_data and comprehensively_cleaned_data[key] is not None:
            summary_relevant_data[key] = comprehensively_cleaned_data[key]

    logger.info(f"Data prepared for summarization for ticket {ticket_id}.")
    return summary_relevant_data 