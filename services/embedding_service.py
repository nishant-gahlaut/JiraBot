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

def get_embeddings_in_batches(texts: list[str], batch_size: int = 96):
    """
    Generates embeddings for a list of texts in batches using Cohere.

    Args:
        texts: A list of strings to embed.
        batch_size: The number of texts to embed in each batch (Cohere's free tier limit is often 96).

    Returns:
        A list of embeddings, where each embedding is a list of floats.
        Returns an empty list if the input texts list is empty.
    """
    if not texts:
        return []

    cohere_embeddings = get_cohere_embeddings()
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch_embeddings = cohere_embeddings.embed_documents(batch)
        all_embeddings.extend(batch_embeddings)
    return all_embeddings 