# genai_handler.py
import os
import logging
import google.generativeai as genai # Import Google GenAI
from langchain_google_genai import ChatGoogleGenerativeAI
import json
from typing import Optional, Dict, Any, List
# tenacity is not used by the top-level functions, consider removing if GenAIService is fully gone
# from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Import prompts
from utils.prompts import (
    SUMMARIZE_SLACK_THREAD_PROMPT, # Added this import
    GENERATE_TICKET_TITLE_PROMPT,
    GENERATE_TICKET_DESCRIPTION_PROMPT,
    GENERATE_TICKET_COMPONENTS_FROM_THREAD_PROMPT,
    GENERATE_TICKET_TITLE_AND_DESCRIPTION_PROMPT,
    PROCESS_MENTION_AND_GENERATE_ALL_COMPONENTS_PROMPT,
    GENERATE_CONCISE_PROBLEM_STATEMENT_PROMPT,
    GENERATE_CONCISE_PROBLEM_STATEMENTS_BATCH_PROMPT, # ADDED IMPORT
    GENERATE_CONCISE_SOLUTIONS_BATCH_PROMPT # ADDED IMPORT FOR NEW PROMPT
)

logger = logging.getLogger(__name__)

# Configure the GenAI client using API key from environment variables
genai_model = None
try:
    GOOGLE_GENAI_KEY = os.environ.get("GOOGLE_GENAI_KEY")
    if GOOGLE_GENAI_KEY:
        genai.configure(api_key=GOOGLE_GENAI_KEY)
        genai_model = genai.GenerativeModel('gemini-2.0-flash') # Set to user-specified model
        logger.info("Google Generative AI client configured successfully.")
    else:
        logger.warning("GOOGLE_GENAI_KEY environment variable not set. GenAI features will be disabled.")
except ImportError:
    logger.warning("'google-generativeai' library not found. Please install it: pip install google-generativeai. GenAI features will be disabled.")
except Exception as e:
    logger.error(f"Failed to configure Google Generative AI: {e}. GenAI features will be disabled.")




def get_llm():
    """Gets a configured LangChain LLM instance using Google's Gemini model."""
    api_key = os.environ.get("GOOGLE_GENAI_KEY")
    if not api_key:
        logger.error("GOOGLE_GENAI_KEY environment variable not set. Cannot create LLM.")
        return None

    try:
        _llm_instance = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=api_key,
            convert_system_message_to_human=True
        )
        return _llm_instance
    except Exception as e:
        logger.error(f"Failed to create LLM instance: {e}")
        return None
         

def generate_text(prompt):
    """Generates text using the configured Google GenAI model."""
    if not genai_model:
        logger.error("GenAI model not initialized. Cannot generate text.")
        return "Error: GenAI model not available."
    
    logger.debug(f"Sending prompt to GenAI model (first 200 chars): {prompt[:200]}...")
    try:
        response = genai_model.generate_content(prompt)
        # Consider adding more robust response handling (e.g., checking finish reason, safety ratings)
        if response.parts:
             generated_text = "".join(part.text for part in response.parts) # Handle multi-part responses
             logger.debug(f"Received GenAI response: {generated_text[:200]}...")
             return generated_text.strip()
        elif response.prompt_feedback:
             logger.warning(f"GenAI call blocked or failed. Feedback: {response.prompt_feedback}")
             return f"Error: Generation failed due to prompt feedback ({response.prompt_feedback.block_reason})."
        else:
             logger.warning("GenAI response received but contained no usable parts.")
             return "Error: Received an empty response from AI."
             
    except Exception as e:
        logger.error(f"Error calling Google GenAI API: {e}", exc_info=True)
        return f"Error: Could not generate AI response due to an API error."

def generate_jira_details(user_summary):
    """Generates a suggested Jira title and description based on user input."""
    logger.info(f"Generating Jira details for summary: '{user_summary}'")

    # --- Placeholder Logic (Retained as per request) --- 
    # Replace this with the actual Google GenAI API call *using generate_text* if needed in future
    try:
        # Simulate API call
        if not user_summary or user_summary.isspace():
             logger.warning("User summary is empty, returning default placeholder.")
             return {
                 "title": "Placeholder Title (Empty Summary)",
                 "description": "Placeholder description because the user provided an empty summary."
             }

        # Basic placeholder generation
        generated_title = f"Issue: {user_summary[:50]}"
        generated_description = f"User reported the following issue:\n\n{user_summary}"
        logger.info(f"Generated Title: {generated_title}")
        logger.info(f"Generated Description: {generated_description}")
        return {
            "title": generated_title,
            "description": generated_description
        }
    except Exception as e:
        logger.error(f"Error during placeholder GenAI call: {e}")
        # In a real scenario, handle API errors more robustly
        return {
            "title": "Error Generating Title",
            "description": f"Could not generate details due to an error: {e}"
        }
    

    
    # --- End Placeholder Logic ---

    # --- Actual GenAI Logic (Example) ---
    # prompt = f"Create a concise Jira ticket title and a detailed description based on the following user summary:\n\nUser Summary: {user_summary}\n\nFormat the output as:\nTitle: [Your generated title]\nDescription: [Your generated description]"
    # try:
    #     response = model.generate_content(prompt)
    #     # TODO: Parse the response.text to extract Title and Description
    #     # This parsing depends heavily on the model's output format
    #     raw_text = response.text
    #     logger.info(f"Raw GenAI response: {raw_text}")
    #     # Example parsing (needs refinement based on actual output):
    #     title = "Parsed Title Placeholder"
    #     description = "Parsed Description Placeholder"
    #     if "Title:" in raw_text and "Description:" in raw_text:
    #        parts = raw_text.split("Description:", 1)
    #        title = parts[0].replace("Title:", "").strip()
    #        description = parts[1].strip()
    # 
    #     logger.info(f"Parsed GenAI Title: {title}")
    #     logger.info(f"Parsed GenAI Description: {description}")
    #     return {"title": title, "description": description}
    # except Exception as e:
    #     logger.error(f"Error calling Google GenAI API: {e}")
    #     return {
    #         "title": "Error Generating Title",
    #         "description": f"Could not generate details due to an API error: {e}"
    #     }
    # --- End Actual GenAI Logic --- 

# New top-level function for summarizing thread
def summarize_thread(thread_content: str) -> Optional[str]:
    if not thread_content or thread_content.isspace():
        logger.warning("Thread content is empty for summarization. Returning None.")
        return None
    prompt = SUMMARIZE_SLACK_THREAD_PROMPT.format(thread_content=thread_content)
    logger.info(f"Summarizing thread: '{thread_content[:100]}...'")
    summary = generate_text(prompt)
    if isinstance(summary, str) and summary.startswith("Error:"):
        logger.error(f"Failed to summarize thread: {summary}")
        return None # Or return the error string if preferred by callers
    return summary

def generate_suggested_title(user_description: str) -> str:
    """Generates a suggested Jira ticket title using an LLM."""
    if not user_description or user_description.isspace():
        logger.warning("User description is empty for title generation. Returning default.")
        return "Title not generated (empty input)"

    prompt = GENERATE_TICKET_TITLE_PROMPT.format(user_description=user_description)
    logger.info(f"Generating suggested title for description: '{user_description[:100]}...'" )
    suggested_title = generate_text(prompt)
    # Basic cleaning: LLM might sometimes include the label like "Jira Ticket Title:"
    if "Jira Ticket Title:" in suggested_title:
        suggested_title = suggested_title.split("Jira Ticket Title:", 1)[-1].strip()
    if isinstance(suggested_title, str) and suggested_title.startswith("Error:"):
        logger.error(f"Failed to generate title: {suggested_title}")
        return "Could not generate title"
    return suggested_title

def generate_refined_description(user_description: str) -> str:
    """Generates a refined Jira ticket description using an LLM."""
    if not user_description or user_description.isspace():
        logger.warning("User description is empty for description refinement. Returning default.")
        return "Description not generated (empty input)"

    prompt = GENERATE_TICKET_DESCRIPTION_PROMPT.format(user_description=user_description)
    logger.info(f"Generating refined description for: '{user_description[:100]}...'" )
    refined_description = generate_text(prompt)
    # Basic cleaning: LLM might sometimes include the label
    if "Refined Jira Ticket Description:" in refined_description:
        refined_description = refined_description.split("Refined Jira Ticket Description:", 1)[-1].strip()
    if isinstance(refined_description, str) and refined_description.startswith("Error:"):
        logger.error(f"Failed to generate refined description: {refined_description}")
        return "Could not generate refined description. Original: " + user_description
    return refined_description

def generate_ticket_components_from_thread(slack_thread_conversation: str) -> dict:
    """
    Generates thread summary, suggested Jira title, and refined Jira description from a Slack thread
    in a single LLM call, expecting a JSON output.
    """
    if not slack_thread_conversation or slack_thread_conversation.isspace():
        logger.warning("Slack thread conversation is empty. Cannot generate ticket components.")
        return {
            "thread_summary": "Could not summarize: Empty thread input.",
            "suggested_title": "Could not generate title: Empty thread input.",
            "refined_description": "Could not generate description: Empty thread input."
        }

    prompt = GENERATE_TICKET_COMPONENTS_FROM_THREAD_PROMPT.format(slack_thread_conversation=slack_thread_conversation)
    logger.info(f"Generating ticket components from thread: '{slack_thread_conversation[:200]}...'" )
    
    raw_llm_output = generate_text(prompt)

    if isinstance(raw_llm_output, str) and raw_llm_output.startswith("Error:"):
        logger.error(f"LLM call failed for component generation: {raw_llm_output}")
        return {
            "thread_summary": f"Error during summarization: {raw_llm_output}",
            "suggested_title": f"Error during title generation: {raw_llm_output}",
            "refined_description": f"Error during description generation: {raw_llm_output}"
        }
    
    try:
        # The LLM output might be wrapped in ```json ... ``` or just be the JSON string.
        # Basic cleaning for common markdown code block wrapper.
        cleaned_output = raw_llm_output.strip()
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[len("```json"):].strip()
        if cleaned_output.startswith("```"):
            cleaned_output = cleaned_output[len("```"):].strip()
        if cleaned_output.endswith("```"):
            cleaned_output = cleaned_output[:-len("```")].strip()
        
        logger.debug(f"Cleaned LLM output for JSON parsing: {cleaned_output}")
        components = json.loads(cleaned_output)
        
        # Validate expected keys
        if not all(key in components for key in ["thread_summary", "suggested_title", "refined_description"]):
            logger.error(f"LLM output parsed as JSON, but missing one or more required keys. Output: {components}")
            missing_keys_message = "LLM output was missing some components."
            return {
                "thread_summary": components.get("thread_summary", missing_keys_message),
                "suggested_title": components.get("suggested_title", missing_keys_message),
                "refined_description": components.get("refined_description", missing_keys_message)
            }
        
        logger.info("Successfully generated and parsed ticket components from thread.")
        return components
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode LLM output as JSON: {e}. Raw output: '{raw_llm_output[:500]}...'" )
        return {
            "thread_summary": "Error: Could not parse AI summary output.",
            "suggested_title": "Error: Could not parse AI title output.",
            "refined_description": "Error: Could not parse AI description output. Raw LLM output was: " + raw_llm_output[:200] + "..."
        }
    except Exception as e:
        logger.error(f"An unexpected error occurred during ticket component generation: {e}", exc_info=True)
        return {
            "thread_summary": f"Unexpected error: {e}",
            "suggested_title": f"Unexpected error: {e}",
            "refined_description": f"Unexpected error: {e}"
        }

def generate_ticket_title_and_description_from_text(user_text: str) -> dict:
    """
    Generates a suggested Jira title and refined Jira description from a single user text input
    in a single LLM call, expecting a JSON output.
    """
    if not user_text or user_text.isspace():
        logger.warning("User text is empty. Cannot generate ticket title and description.")
        return {
            "suggested_title": "Could not generate title: Empty input.",
            "refined_description": "Could not generate description: Empty input."
        }

    prompt = GENERATE_TICKET_TITLE_AND_DESCRIPTION_PROMPT.format(user_description=user_text) # Corrected to user_description to match prompt
    logger.info(f"Generating ticket title and description from text: '{user_text[:200]}...'" )
    
    raw_llm_output = generate_text(prompt)

    if isinstance(raw_llm_output, str) and raw_llm_output.startswith("Error:"):
        logger.error(f"LLM call failed for title/description generation: {raw_llm_output}")
        return {
            "suggested_title": f"Error during title generation: {raw_llm_output}",
            "refined_description": f"Error during description generation: {raw_llm_output}"
        }
    
    try:
        cleaned_output = raw_llm_output.strip()
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[len("```json"):].strip()
        if cleaned_output.startswith("```"):
            cleaned_output = cleaned_output[len("```"):].strip()
        if cleaned_output.endswith("```"):
            cleaned_output = cleaned_output[:-len("```")].strip()
        
        logger.debug(f"Cleaned LLM output for JSON parsing: {cleaned_output}")
        components = json.loads(cleaned_output)
        
        if not all(key in components for key in ["suggested_title", "refined_description"]):
            logger.error(f"LLM output parsed as JSON, but missing required keys ('suggested_title', 'refined_description'). Output: {components}")
            missing_keys_message = "LLM output was missing some components."
            return {
                "suggested_title": components.get("suggested_title", missing_keys_message),
                "refined_description": components.get("refined_description", missing_keys_message)
            }
        
        logger.info("Successfully generated and parsed ticket title and description from text.")
        return components
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode LLM output as JSON: {e}. Raw output: '{raw_llm_output[:500]}...'" )
        return {
            "suggested_title": "Error: Could not parse AI title output.",
            "refined_description": "Error: Could not parse AI description output. Raw LLM output was: " + raw_llm_output[:200] + "..."
        }
    except Exception as e:
        logger.error(f"An unexpected error occurred during title/description generation: {e}", exc_info=True)
        return {
            "suggested_title": f"Unexpected error: {e}",
            "refined_description": f"Unexpected error: {e}"
        }

# New top-level function for processing mention and generating all components
def process_mention_and_generate_all_components(user_direct_message_to_bot: str, formatted_conversation_history: str) -> Optional[Dict[str, Any]]:
    prompt = PROCESS_MENTION_AND_GENERATE_ALL_COMPONENTS_PROMPT.format(
        user_direct_message_to_bot=user_direct_message_to_bot,
        formatted_conversation_history=formatted_conversation_history
    )
    logger.info(f"Processing mention and generating all components. User message: '{user_direct_message_to_bot[:100]}...', History: '{formatted_conversation_history[:100]}...'" )
    
    raw_llm_output = generate_text(prompt) # Use the Google GenAI model via generate_text

    if isinstance(raw_llm_output, str) and raw_llm_output.startswith("Error:"):
        logger.error(f"LLM call failed for mention processing: {raw_llm_output}")
        # Return None or a dict with error, consistent with other functions
        return {
            "intent": None,
            "contextual_summary": f"Error: {raw_llm_output}",
            "suggested_title": None,
            "refined_description": None
        }

    try:
        cleaned_output = raw_llm_output.strip()
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[len("```json"):].strip()
        if cleaned_output.startswith("```"):
            cleaned_output = cleaned_output[len("```"):].strip()
        if cleaned_output.endswith("```"):
            cleaned_output = cleaned_output[:-len("```")].strip()
        
        logger.debug(f"Cleaned LLM output for JSON parsing (mention processing): {cleaned_output}")
        parsed_json = json.loads(cleaned_output)
        
        # Validate expected keys
        expected_keys = ["intent", "contextual_summary", "suggested_title", "refined_description"]
        if not all(key in parsed_json for key in expected_keys):
            logger.error(f"Missing one or more expected keys in parsed JSON (mention processing). Keys: {parsed_json.keys()}, Raw: {cleaned_output}")
            # Allow partial data but log error, ensure all keys exist even if null
            return {
                "intent": parsed_json.get("intent"),
                "contextual_summary": parsed_json.get("contextual_summary", "Error: Missing summary from AI response."),
                "suggested_title": parsed_json.get("suggested_title"),
                "refined_description": parsed_json.get("refined_description")
            }
        
        logger.info("Successfully processed mention and generated all components.")
        return parsed_json
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from LLM (mention processing): {e}. Raw output: '{raw_llm_output[:500]}...'" )
        return {
            "intent": None,
            "contextual_summary": "Error: Could not parse AI response for mention.",
            "suggested_title": None,
            "refined_description": None
        }
    except Exception as e:
        logger.error(f"Unexpected error during mention processing: {e}", exc_info=True)
        return {
            "intent": None,
            "contextual_summary": f"Unexpected error: {e}",
            "suggested_title": None,
            "refined_description": None
        }

def generate_concise_problem_statement(summary: str, description: str, comments: str, max_lines: int = 7) -> str:
    """
    Uses an LLM (Google Flash via LangChain) to generate a concise problem statement (5-7 lines) 
    from Jira ticket details, prioritizing summary and description.

    Args:
        summary: The cleaned summary of the Jira ticket.
        description: The cleaned description of the Jira ticket.
        comments: The cleaned and filtered comments relevant to the problem.
        max_lines: The target maximum number of lines for the output.

    Returns:
        A string containing the concise problem statement, or an error message 
        if generation fails.
    """
    llm = get_llm() # Get the configured LangChain LLM instance
    if not llm:
        logger.error("Cannot generate problem statement: LLM instance is not available.")
        # Return a fallback or error indicator
        fallback_text = f"Fallback (LLM unavailable): {summary}"
        return fallback_text[:500] # Limit fallback length

    # Combine inputs, potentially indicating priority or source
    # If comments are very long, consider truncating them for the prompt
    # Ensure inputs are strings
    summary_str = str(summary) if summary is not None else ""
    description_str = str(description) if description is not None else ""
    comments_str = str(comments) if comments is not None else ""
    
    # Limit comments length passed to the prompt
    max_comment_length = 2000
    if len(comments_str) > max_comment_length:
        comments_str = comments_str[:max_comment_length] + "... (truncated)"

    # Format the prompt using the imported constant
    prompt = GENERATE_CONCISE_PROBLEM_STATEMENT_PROMPT.format(
        summary=summary_str,
        description=description_str,
        comments=comments_str,
        max_lines=max_lines,
        max_lines_lower_bound=max_lines - 1
    )

    try:
        # Use the LangChain LLM's invoke method
        logger.debug(f"Invoking LLM for problem statement. Prompt length: {len(prompt)}")
        response = llm.invoke(prompt)
        
        # LangChain ChatGoogleGenerativeAI typically returns an AIMessage with content attribute
        generated_text = response.content if hasattr(response, 'content') else str(response)
        
        if not generated_text or generated_text.isspace():
             logger.warning("LLM returned empty response for problem statement.")
             raise ValueError("LLM returned empty response")
             
        # Simple post-processing: ensure it's roughly within line limits (optional)
        lines = generated_text.strip().split('\n')
        if len(lines) > max_lines:
            logger.debug(f"LLM output ({len(lines)} lines) exceeded max_lines ({max_lines}). Truncating.")
            generated_text = "\n".join(lines[:max_lines])
            
        logger.info(f"Successfully generated problem statement (length: {len(generated_text)} chars).")
        return generated_text.strip()

    except Exception as e:
        logger.error(f"Error generating problem statement with LLM: {e}", exc_info=True)
        # Return a fallback or error indicator
        fallback_text = f"Error: Could not generate problem statement. Fallback: {summary_str}"
        return fallback_text[:500] # Limit fallback length

# --- NEW BATCH FUNCTION --- 
def generate_concise_problem_statements_batch(batch_data: List[Dict[str, Any]], max_lines: int = 7) -> List[str]:
    """
    Uses an LLM to generate concise problem statements for a batch of tickets.

    Args:
        batch_data: A list of dictionaries, where each dict represents a ticket
                    and must contain 'id' (unique identifier like index or ticket_id),
                    'summary', 'description', and 'comments'.
        max_lines: The target maximum number of lines for each problem statement.

    Returns:
        A list of strings. Each string is either the generated problem statement
        or an error message (e.g., "Error: Failed to generate for item <id>")
        corresponding to the input batch order.
    """
    llm = get_llm()
    if not llm:
        logger.error("Cannot generate batch problem statements: LLM instance not available.")
        return [f"Error: LLM unavailable for item {item.get('id', 'N/A')}" for item in batch_data]
        
    if not batch_data:
        logger.warning("Received empty batch_data for problem statement generation.")
        return []

    batch_size = len(batch_data)
    
    # Pre-process batch data for prompt (e.g., truncate long comments)
    # IMPORTANT: Create a copy to avoid modifying the original data if passed by reference elsewhere
    prepared_batch_data = []
    for item in batch_data:
        prepared_batch_data.append({
            "id": item.get('id', 'N/A'), # Keep ID for potential error reporting
            "summary": str(item.get('summary', '')),
            "description": str(item.get('description', ''))
        })

    try:
        # Serialize the prepared batch data to a JSON string for the prompt
        # Use ensure_ascii=False to handle potential non-ASCII chars better if needed, but check LLM tolerance
        batch_input_json = json.dumps(prepared_batch_data, indent=2, ensure_ascii=True)
    except Exception as e:
        logger.error(f"Failed to serialize batch data to JSON: {e}", exc_info=True)
        return [f"Error: Failed to prepare batch input for item {item.get('id', 'N/A')}" for item in batch_data]
        
    # Format the prompt
    prompt = GENERATE_CONCISE_PROBLEM_STATEMENTS_BATCH_PROMPT.format(
        batch_input_json=batch_input_json,
        batch_size=batch_size,
        max_lines=max_lines,
        max_lines_lower_bound=2
    )

    # Estimate token count - very rough, use a proper tokenizer if needed
    # prompt_token_estimate = len(prompt) // 3 # Rough estimate - Replaced with more accurate count below
    # logger.debug(f"Invoking LLM for batch problem statements. Batch Size: {batch_size}. Prompt Token Estimate: ~{prompt_token_estimate}")
    # # Adjust threshold based on the specific model's context window (e.g., Gemini 1.5 Flash is large, but use a safer limit)
    # if prompt_token_estimate > 80000: # Example Threshold (adjust based on model limits)
    #      logger.warning(f"Potential high token count ({prompt_token_estimate}) for batch LLM call. Consider reducing LLM_BATCH_SIZE or further input truncation.")
    
    # --- Accurate Token Counting for the Prompt ---
    prompt_token_count = -1 # Default if counting fails
    if genai_model: # Check if the base model client is available
        try:
            count_response = genai_model.count_tokens(prompt)
            prompt_token_count = count_response.total_tokens
            logger.info(f"Prompt token count for batch size {batch_size}: {prompt_token_count} tokens.")
        except Exception as count_e:
            logger.warning(f"Could not count prompt tokens using genai_model: {count_e}. Falling back to estimate.")
            # Fallback to rough estimate if count fails
            prompt_token_count = len(prompt) // 3 
            logger.info(f"Prompt token count ESTIMATE for batch size {batch_size}: ~{prompt_token_count} tokens.")
    else:
        logger.warning("Base genai_model not initialized, cannot accurately count prompt tokens. Using estimate.")
        prompt_token_count = len(prompt) // 3
        logger.info(f"Prompt token count ESTIMATE for batch size {batch_size}: ~{prompt_token_count} tokens.")
        
    # Note: Checking remaining account tokens is not possible via the API response.
    # Monitor usage via Google Cloud Console.
    if prompt_token_count > 80000: # Re-evaluate threshold based on accurate count if available
        logger.warning(f"High token count ({prompt_token_count}) detected for batch LLM call. Consider reducing LLM_BATCH_SIZE or further input truncation.")
    # --- End Token Counting ---

    raw_llm_output = "Error: LLM Invocation Failed Initially" # Default error
    try:
        response = llm.invoke(prompt)
        raw_llm_output = response.content if hasattr(response, 'content') else str(response)

        # Clean potential markdown code block wrappers
        cleaned_output = raw_llm_output.strip()
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[len("```json"):].strip()
        if cleaned_output.startswith("```"):
            cleaned_output = cleaned_output[len("```"):].strip()
        if cleaned_output.endswith("```"):
            cleaned_output = cleaned_output[:-len("```")].strip()
            
        logger.debug(f"Cleaned LLM batch output for JSON parsing: {cleaned_output[:200]}...")

        # Parse the JSON list response
        results = json.loads(cleaned_output)

        if not isinstance(results, list):
            logger.error(f"LLM batch output was not a list. Type: {type(results)}. Output: {cleaned_output[:500]}...")
            raise ValueError("LLM output for batch was not a list.")

        if len(results) != batch_size:
            logger.error(f"LLM batch output list size mismatch. Expected: {batch_size}, Got: {len(results)}. Output: {cleaned_output[:500]}...")
            # For safety, return errors for all items in this batch
            return [f"Error: LLM output size mismatch for item {item.get('id', 'N/A')}" for item in batch_data]
            
        # Optional: Post-process each result (e.g., strip extra whitespace)
        processed_results = [str(res).strip() for res in results]
        logger.info(f"Successfully generated and parsed {len(processed_results)} problem statements from batch LLM call.")
        return processed_results

    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode LLM batch output as JSON: {e}. Raw output: '{raw_llm_output[:500]}...'")
        return [f"Error: Failed to parse LLM JSON output for item {item.get('id', 'N/A')}" for item in batch_data]
    except Exception as e:
        logger.error(f"Error during LLM batch invocation or processing: {e}", exc_info=True)
        return [f"Error: LLM invocation/processing failed for item {item.get('id', 'N/A')}" for item in batch_data]

# --- NEW BATCH SOLUTION FUNCTION ---
def generate_concise_solutions_batch(batch_data: List[Dict[str, Any]]) -> List[str]:
    """
    Uses an LLM to generate concise solution summaries from comments for a batch of tickets.

    Args:
        batch_data: A list of dictionaries, where each dict represents a ticket
                    and must contain 'id' (unique identifier like index or ticket_id)
                    and 'cleaned_comments'.

    Returns:
        A list of strings. Each string is either the generated solution summary (in bullet points)
        or a message "No clear solution identified in the comments."
        corresponding to the input batch order.
    """
    llm = get_llm()
    if not llm:
        logger.error("Cannot generate batch solutions: LLM instance not available.")
        return [f"Error: LLM unavailable for solution generation for item {item.get('id', 'N/A')}" for item in batch_data]

    if not batch_data:
        logger.warning("Received empty batch_data for solution generation.")
        return []

    batch_size = len(batch_data)

    prepared_batch_data = []
    for item in batch_data:
        # Truncate comments if they are too long to avoid excessively large prompts
        comments = str(item.get('cleaned_comments', ''))
        # Max length for comments per ticket in the batch prompt (adjust as needed)
        # This is a safeguard, individual comment cleaning should also handle extreme lengths.
        max_comment_length_for_batch_item = 5000
        if len(comments) > max_comment_length_for_batch_item:
            comments = comments[:max_comment_length_for_batch_item] + "... (truncated for batch prompt)"
            logger.debug(f"Comment for item {item.get('id', 'N/A')} truncated for batch solution prompt.")

        prepared_batch_data.append({
            "id": item.get('id', 'N/A'),
            "cleaned_comments": comments
        })

    try:
        batch_input_json = json.dumps(prepared_batch_data, indent=2, ensure_ascii=True)
    except Exception as e:
        logger.error(f"Failed to serialize batch data to JSON for solution generation: {e}", exc_info=True)
        return [f"Error: Failed to prepare batch input for solution for item {item.get('id', 'N/A')}" for item in batch_data]

    prompt = GENERATE_CONCISE_SOLUTIONS_BATCH_PROMPT.format(
        batch_input_json=batch_input_json,
        batch_size=batch_size
        # The prompt itself guides on bullet points (2-5), so max_lines isn't explicitly passed here
        # but could be added if prompt was designed to take it.
    )

    prompt_token_count = -1
    if genai_model:
        try:
            count_response = genai_model.count_tokens(prompt)
            prompt_token_count = count_response.total_tokens
            logger.info(f"Solution Prompt token count for batch size {batch_size}: {prompt_token_count} tokens.")
        except Exception as count_e:
            logger.warning(f"Could not count solution prompt tokens: {count_e}. Estimating.")
            prompt_token_count = len(prompt) // 3
            logger.info(f"Solution Prompt token count ESTIMATE for batch size {batch_size}: ~{prompt_token_count} tokens.")
    else:
        logger.warning("Base genai_model not initialized for token counting (solutions). Estimating.")
        prompt_token_count = len(prompt) // 3
        logger.info(f"Solution Prompt token count ESTIMATE for batch size {batch_size}: ~{prompt_token_count} tokens.")

    # Threshold from problem statement generation, can be adjusted if needed
    if prompt_token_count > 80000:
        logger.warning(f"High token count ({prompt_token_count}) detected for batch solution LLM call. Consider reducing LLM_BATCH_SIZE or comment length.")

    raw_llm_output = "Error: LLM Invocation Failed Initially for Solutions"
    try:
        response = llm.invoke(prompt)
        raw_llm_output = response.content if hasattr(response, 'content') else str(response)

        cleaned_output = raw_llm_output.strip()
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[len("```json"):].strip()
        if cleaned_output.startswith("```"):
            cleaned_output = cleaned_output[len("```"):].strip()
        if cleaned_output.endswith("```"):
            cleaned_output = cleaned_output[:-len("```")].strip()

        logger.debug(f"Cleaned LLM batch solution output for JSON parsing: {cleaned_output[:300]}...")
        results = json.loads(cleaned_output)

        if not isinstance(results, list):
            logger.error(f"LLM batch solution output was not a list. Type: {type(results)}. Output: {cleaned_output[:500]}...")
            raise ValueError("LLM output for batch solutions was not a list.")

        if len(results) != batch_size:
            logger.error(f"LLM batch solution output list size mismatch. Expected: {batch_size}, Got: {len(results)}. Output: {cleaned_output[:500]}...")
            return [f"Error: LLM solution output size mismatch for item {item.get('id', 'N/A')}" for item in batch_data]

        processed_results = [str(res).strip() for res in results]
        logger.info(f"Successfully generated and parsed {len(processed_results)} solution summaries from batch LLM call.")
        return processed_results

    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode LLM batch solution output as JSON: {e}. Raw output: '{raw_llm_output[:500]}...'")
        return [f"Error: Failed to parse LLM JSON solution output for item {item.get('id', 'N/A')}" for item in batch_data]
    except Exception as e:
        logger.error(f"Error during LLM batch solution invocation or processing: {e}", exc_info=True)
        return [f"Error: LLM solution invocation/processing failed for item {item.get('id', 'N/A')}" for item in batch_data]

# Example usage (optional, for testing)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    # gen_ai_service = GenAIService() # Removed GenAIService instantiation

    # Test summarize_thread
    # summary = summarize_thread("This is a test thread. User is having trouble with login.")
    # print(f"Summary: {summary}")

    # Test generate_suggested_title
    # title = generate_suggested_title("The application crashes when I click the submit button after filling the form.")
    # print(f"Suggested Title: {title}")

    # Test generate_refined_description
    # description = generate_refined_description("The payment page is not loading. I tried multiple times. It just spins.")
    # print(f"Refined Description: {description}")

    # Test generate_ticket_components_from_thread
    # thread_components = generate_ticket_components_from_thread("User A: The login is broken. User B: Yeah, I see a 500 error. User C: Happened after the deploy.")
    # if thread_components:
    #     print(f"Thread Components: Title: {thread_components.get('suggested_title')}, Description: {thread_components.get('refined_description')}")

    # Test generate_ticket_title_and_description_from_text
    # text_components = generate_ticket_title_and_description_from_text("My computer is making a weird buzzing sound and the screen is flickering. This started yesterday after the power surge.")
    # if text_components:
    #     print(f"Text Components: Title: {text_components.get('suggested_title')}, Description: {text_components.get('refined_description')}")

    # Test process_mention_and_generate_all_components - now a top-level function call
    mention_data = process_mention_and_generate_all_components(
        user_direct_message_to_bot="@JiraBot I can't log in, the main page shows an error 500.",
        formatted_conversation_history="UserA: Hey, did the new deployment go out? \nUserB: Yes, about an hour ago. \nUserC: I think something is wrong with the login page since then."
    )
    if mention_data and mention_data.get('intent'): # Check for successful processing
        print(f"Mention Processed Data: Intent: {mention_data.get('intent')}, Summary: {mention_data.get('contextual_summary')}, Title: {mention_data.get('suggested_title')}, Description: {mention_data.get('refined_description')}")
    else:
        print(f"Failed to process mention data or intent was None. Response: {mention_data}")
