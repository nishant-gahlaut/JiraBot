import os
import logging
from typing import Optional, List
from pinecone import Pinecone, Index
from langchain.embeddings.base import Embeddings
from langchain.schema import Document

logger = logging.getLogger(__name__)

def initialize_pinecone_vector_store(embeddings: Embeddings) -> Optional[Index]:
    """
    Initializes and returns a Pinecone Index object using new SDK (pinecone>=3.0.0).
    """
    pinecone_api_key = os.environ.get("PINECONE_API_KEY")
    pinecone_index_name = os.environ.get("PINECONE_INDEX_NAME")

    if not pinecone_api_key or not pinecone_index_name:
        logger.warning("Missing PINECONE_API_KEY or PINECONE_INDEX_NAME in environment variables.")
        return None

    try:
        pc = Pinecone(api_key=pinecone_api_key)

        # Get list of index names
        existing_indexes = [idx.name for idx in pc.list_indexes().indexes]

        if pinecone_index_name not in existing_indexes:
            logger.error(f"Index '{pinecone_index_name}' not found. Available indexes: {existing_indexes}")
            return None

        index = pc.Index(pinecone_index_name)
        logger.info(f"Connected to Pinecone index: {pinecone_index_name}")
        return index

    except Exception as e:
        logger.error(f"Error initializing Pinecone: {e}", exc_info=True)
        return None


def search_pinecone_index(index: Index, query_vector: List[float], k: int, namespace: Optional[str] = None) -> List[dict]:
    """
    Searches the Pinecone index using a vector.
    """
    if not index or not query_vector:
        logger.warning("Missing index or query_vector.")
        return []

    try:
        query_kwargs = {
            "vector": query_vector,
            "top_k": k,
            "include_metadata": True
        }
        if namespace:
            query_kwargs["namespace"] = namespace

        results = index.query(**query_kwargs)
        matches = results.matches if hasattr(results, "matches") else []
        logger.info(f"Found {len(matches)} matches.")
        return [match.model_dump() for match in matches]  # Convert from Pydantic models to dicts

    except Exception as e:
        logger.error(f"Error during Pinecone query: {e}", exc_info=True)
        return []
