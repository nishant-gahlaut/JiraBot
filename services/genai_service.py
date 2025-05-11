# genai_handler.py
import os
import logging
import google.generativeai as genai # Import Google GenAI
from langchain_google_genai import ChatGoogleGenerativeAI
import json
from typing import Optional, Dict, Any
# tenacity is not used by the top-level functions, consider removing if GenAIService is fully gone
# from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Import prompts
from utils.prompts import (
    SUMMARIZE_SLACK_THREAD_PROMPT, # Added this import
    GENERATE_TICKET_TITLE_PROMPT,
    GENERATE_TICKET_DESCRIPTION_PROMPT,
    GENERATE_TICKET_COMPONENTS_FROM_THREAD_PROMPT,
    GENERATE_TICKET_TITLE_AND_DESCRIPTION_PROMPT,
    PROCESS_MENTION_AND_GENERATE_ALL_COMPONENTS_PROMPT
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
