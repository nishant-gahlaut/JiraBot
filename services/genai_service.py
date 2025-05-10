# genai_handler.py
import os
import logging
import google.generativeai as genai # Import Google GenAI
from langchain_google_genai import ChatGoogleGenerativeAI
import json

# Import prompts
from utils.prompts import GENERATE_TICKET_TITLE_PROMPT, GENERATE_TICKET_DESCRIPTION_PROMPT, GENERATE_TICKET_COMPONENTS_FROM_THREAD_PROMPT, GENERATE_TICKET_TITLE_AND_DESCRIPTION_PROMPT

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

def generate_suggested_title(user_description: str) -> str:
    """Generates a suggested Jira ticket title using an LLM."""
    if not user_description or user_description.isspace():
        logger.warning("User description is empty for title generation. Returning default.")
        return "Title not generated (empty input)"

    prompt = GENERATE_TICKET_TITLE_PROMPT.format(user_description=user_description)
    logger.info(f"Generating suggested title for description: '{user_description[:100]}...'")
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
    logger.info(f"Generating refined description for: '{user_description[:100]}...'")
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
    logger.info(f"Generating ticket components from thread: '{slack_thread_conversation[:200]}...'")
    
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
        logger.error(f"Failed to decode LLM output as JSON: {e}. Raw output: '{raw_llm_output[:500]}...'")
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

    prompt = GENERATE_TICKET_TITLE_AND_DESCRIPTION_PROMPT.format(user_description=user_text)
    logger.info(f"Generating ticket title and description from text: '{user_text[:200]}...'")
    
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
        logger.error(f"Failed to decode LLM output as JSON: {e}. Raw output: '{raw_llm_output[:500]}...'")
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
