# summarize_handler.py
import logging
import os
# Import prompts
from utils.prompts import ISSUE_SUMMARY_PROMPT, RESOLUTION_SUMMARY_PROMPT
# Import the actual LLM caller
from services.genai_service import generate_text
# TODO: Add import for google.generativeai when implementing

logger = logging.getLogger(__name__)

# TODO: Configure GenAI client (similar to genai_handler.py)
# genai.configure(api_key=os.environ["GOOGLE_GENAI_KEY"])
# model = genai.GenerativeModel('gemini-pro') # Or your preferred model

def _summarize_issue(ticket_summary, description):
    """Generates a summary of the issue using LLM."""
    logger.info("Generating issue summary...")
    if not ticket_summary and not description:
        return "No summary or description provided."
        
    prompt = ISSUE_SUMMARY_PROMPT.format(
        ticket_summary=ticket_summary or "[No Summary Provided]",
        ticket_description=description or "[No Description Provided]"
    )
    
    # Use the real generate_text function
    llm_response = generate_text(prompt)
    return llm_response 

def _summarize_resolution(comments):
    """Generates a summary of the resolution/next steps using LLM based on comments."""
    logger.info("Generating resolution summary...")
    if not comments:
        return "No comments available to determine resolution status."
    
    # Format comments for the prompt (oldest to newest)
    formatted_comments = "\n".join([
        f"- {c.get('timestamp')} by {c.get('author', 'Unknown')}: {c.get('cleaned_body', '')}"
        for c in comments
    ])
    
    prompt = RESOLUTION_SUMMARY_PROMPT.format(formatted_comments=formatted_comments)
    
    # Use the real generate_text function
    llm_response = generate_text(prompt)
    return llm_response

def summarize_jira_ticket(cleaned_data):
    """Orchestrates the summarization of a Jira ticket using cleaned data."""
    if not cleaned_data:
        logger.error("Cannot summarize ticket, cleaned data is missing.")
        return None
        
    ticket_id = cleaned_data.get('ticket_id')
    logger.info(f"Generating orchestrated summary for ticket ID: {ticket_id}")
    
    # Extract necessary data from the cleaned structure
    ticket_status = cleaned_data.get("status", "Unknown")
    ticket_summary = cleaned_data.get("summary", "")
    description = cleaned_data.get("description", "")
    comments = cleaned_data.get("comments", []) # Expects cleaned comments list

    try:
        # Generate issue summary
        issue_summary = _summarize_issue(ticket_summary, description)
        
        # Generate resolution summary
        resolution_summary = _summarize_resolution(comments)
             
        # Combine results
        final_summary = {
            "status": ticket_status, # Direct from metadata
            "issue_summary": issue_summary,
            "resolution_summary": resolution_summary
        }
        logger.info(f"Generated Orchestrated Summary for {ticket_id}: {final_summary}")
        return final_summary
        
    except Exception as e:
        logger.error(f"Error during orchestrated summarization for {ticket_id}: {e}", exc_info=True)
        return {
            "status": ticket_status,
            "issue_summary": "Error generating issue summary.",
            "resolution_summary": "Error generating resolution summary."
        }
    # --- Old Placeholder Logic Removed --- 