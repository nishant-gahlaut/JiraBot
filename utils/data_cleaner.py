# utils/data_cleaner.py
import logging
import re
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

def clean_jira_data(structured_data):
    """Cleans and restructures fetched Jira data for summarization."""
    if not structured_data:
        logger.warning("No structured data provided to clean.")
        return None

    logger.info(f"Cleaning data for ticket: {structured_data.get('id')}")
    cleaned_metadata = {}

    try:
        # --- Basic Fields ---
        cleaned_metadata['ticket_id'] = structured_data.get('id')
        cleaned_metadata['summary'] = structured_data.get('summary', '').strip()
        cleaned_metadata['description'] = (structured_data.get('description') or '').strip()
        cleaned_metadata['status'] = structured_data.get('status', 'Unknown')
        cleaned_metadata['priority'] = structured_data.get('priority', 'Unknown')
        cleaned_metadata['reporter'] = structured_data.get('reporter', 'Unknown')
        cleaned_metadata['assignee'] = structured_data.get('assignee') # Can be None
        cleaned_metadata['created_at'] = structured_data.get('created')
        cleaned_metadata['updated_at'] = structured_data.get('updated')

        # --- Clean Comments ---
        raw_comments = structured_data.get('comments', [])
        cleaned_comments = []
        
        # Sort comments by creation date (oldest first)
        # Requires parsing the date string
        def parse_jira_date(date_str):
            if not date_str:
                return None
            try:
                # Jira format often like: '2025-04-24T13:36:16.799+0530'
                # Python's fromisoformat handles timezone offsets correctly
                return datetime.fromisoformat(date_str)
            except ValueError:
                logger.warning(f"Could not parse date string: {date_str}")
                return None # Or return a default date?

        # Sort comments, handling potential None dates
        sorted_comments = sorted(
            raw_comments, 
            key=lambda c: parse_jira_date(c.get('created')) or datetime.min
        )

        for comment in sorted_comments:
            cleaned_body, mentions = _parse_comment_body(comment.get('body', ''))
            cleaned_comments.append({
                'author': comment.get('author', 'Unknown'),
                'timestamp': comment.get('created'),
                'cleaned_body': cleaned_body,
                'mentions': mentions
            })
            
        cleaned_metadata['comments'] = cleaned_comments

        logger.info(f"Data cleaning complete for ticket {cleaned_metadata['ticket_id']}. Found {len(cleaned_comments)} comments.")
        return cleaned_metadata

    except Exception as e:
        logger.error(f"Unexpected error during data cleaning for ticket {structured_data.get('id')}: {e}", exc_info=True)
        return None # Return None on failure 