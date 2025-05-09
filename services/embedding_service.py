import os # Added import
from langchain_cohere import CohereEmbeddings # Updated import

def get_cohere_embeddings():
    """
    Initializes and returns Cohere embeddings.
    Reads COHERE_API_KEY from environment variables.
    """
    api_key = os.environ.get("COHERE_API_KEY")
    if not api_key:
        print("Warning: COHERE_API_KEY environment variable not set. CohereEmbeddings might not work.")
        # Depending on desired behavior, you could return None or raise an error
        # For now, it will proceed and langchain_cohere will likely raise its own error if key is missing/invalid.

    # You might need to install langchain-cohere: pip install langchain-cohere
    return CohereEmbeddings(cohere_api_key=api_key, model="embed-english-light-v2.0") 