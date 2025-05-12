import os
import logging
import time # Added for waiting loop
from typing import Optional, List
from pinecone import Pinecone, Index, ServerlessSpec # Added ServerlessSpec
from langchain.embeddings.base import Embeddings
from langchain.schema import Document

logger = logging.getLogger(__name__)

# Default values for index creation, can be overridden by environment variables if needed
PINECONE_METRIC = os.environ.get("PINECONE_METRIC", "cosine")
PINECONE_CLOUD = os.environ.get("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.environ.get("PINECONE_REGION", "us-east-1")

def get_embedding_dimension(embeddings: Embeddings) -> Optional[int]:
    """Gets the dimension of the embeddings by embedding a dummy query."""
    try:
        dummy_vector = embeddings.embed_query("test")
        return len(dummy_vector)
    except Exception as e:
        logger.error(f"Could not determine embedding dimension: {e}", exc_info=True)
        return None

def initialize_pinecone_vector_store(embeddings: Embeddings) -> Optional[Index]:
    """
    Initializes and returns a Pinecone Index object.
    If the index doesn't exist, it attempts to create it.
    """
    pinecone_api_key = os.environ.get("PINECONE_API_KEY")
    pinecone_index_name = os.environ.get("PINECONE_INDEX_NAME")

    if not pinecone_api_key or not pinecone_index_name:
        logger.warning("Missing PINECONE_API_KEY or PINECONE_INDEX_NAME in environment variables.")
        return None
    
    if not embeddings:
        logger.error("Embeddings object not provided, cannot determine dimension for index creation.")
        return None

    try:
        pc = Pinecone(api_key=pinecone_api_key)
        existing_indexes = [idx.name for idx in pc.list_indexes().indexes]

        if pinecone_index_name not in existing_indexes:
            logger.info(f"Index '{pinecone_index_name}' not found. Attempting to create it...")
            
            dimension = get_embedding_dimension(embeddings)
            if dimension is None:
                logger.error(f"Failed to get embedding dimension. Cannot create index '{pinecone_index_name}'.")
                return None

            logger.info(f"Creating index '{pinecone_index_name}' with dimension {dimension}, metric '{PINECONE_METRIC}', cloud '{PINECONE_CLOUD}', region '{PINECONE_REGION}'.")
            try:
                pc.create_index(
                    name=pinecone_index_name,
                    dimension=dimension,
                    metric=PINECONE_METRIC,
                    spec=ServerlessSpec(
                        cloud=PINECONE_CLOUD,
                        region=PINECONE_REGION
                    ),
                    timeout=-1 # Wait indefinitely for creation, or set a specific timeout in seconds
                )
                # Wait for the index to be ready
                wait_time = 0
                max_wait_time = 300 # 5 minutes
                sleep_interval = 15 # seconds
                while wait_time < max_wait_time:
                    index_description = pc.describe_index(name=pinecone_index_name)
                    if index_description.status and index_description.status['ready']:
                        logger.info(f"Index '{pinecone_index_name}' created and is ready.")
                        break
                    logger.info(f"Waiting for index '{pinecone_index_name}' to be ready... ({wait_time}/{max_wait_time}s)")
                    time.sleep(sleep_interval)
                    wait_time += sleep_interval
                else:
                    logger.error(f"Index '{pinecone_index_name}' did not become ready within {max_wait_time} seconds.")
                    # Optionally, attempt to delete the partially created index or handle error
                    # try:
                    #     pc.delete_index(pinecone_index_name)
                    #     logger.info(f"Attempted to delete index '{pinecone_index_name}' after timeout.")
                    # except Exception as del_e:
                    #     logger.error(f"Failed to delete index '{pinecone_index_name}' after timeout: {del_e}")
                    return None
            except Exception as create_e:
                logger.error(f"Failed to create Pinecone index '{pinecone_index_name}': {create_e}", exc_info=True)
                return None
        else:
            logger.info(f"Index '{pinecone_index_name}' already exists.")

        index = pc.Index(pinecone_index_name)
        logger.info(f"Successfully connected to Pinecone index: {pinecone_index_name}")
        # Verify connection and get stats
        try:
            stats = index.describe_index_stats()
            logger.info(f"Index stats: {stats}")
        except Exception as e_stats:
            logger.warning(f"Could not retrieve stats for index '{pinecone_index_name}': {e_stats}")
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
        logger.info(f"Found {len(matches)} matches from Pinecone query.")
        
        output_matches = []
        for i, match_item in enumerate(matches):
            if not match_item:
                logger.warning(f"Match item at index {i} from Pinecone is None. Skipping.")
                continue
            
            # Directly construct the dictionary from ScoredVector attributes
            # Pinecone's match_item (ScoredVector) has .id, .score, and .metadata (which should be a dict)
            if hasattr(match_item, 'id') and hasattr(match_item, 'metadata'):
                try:
                    current_match_dict = {
                        "id": match_item.id,
                        "score": getattr(match_item, 'score', None), # score might be optional
                        "metadata": match_item.metadata if match_item.metadata is not None else {} # Ensure metadata is a dict, default to empty if None
                    }
                    output_matches.append(current_match_dict)
                    # logger.debug(f"Successfully processed match item {match_item.id}") # Optional: for very verbose debugging
                except Exception as e_manual:
                    logger.error(f"Error during manual construction for match {getattr(match_item, 'id', 'N/A')}: {e_manual}", exc_info=True)
            else:
                logger.warning(f"Skipping match item at index {i} as it lacks essential 'id' or 'metadata' attributes. Item type: {type(match_item)}, Content: {str(match_item)[:200]}")
                
        return output_matches

    except Exception as e:
        logger.error(f"Error during Pinecone query: {e}", exc_info=True)
        return []

def upsert_documents_to_pinecone(index: Index, documents: List[Document], embeddings: List[List[float]], batch_size: int = 100, namespace: Optional[str] = None):
    """
    Upserts documents and their embeddings to Pinecone in batches.
    Uses the 'ticketId' from metadata as the Pinecone vector ID.

    Args:
        index: The initialized Pinecone Index object.
        documents: A list of LangChain Document objects.
        embeddings: A list of embeddings corresponding to the documents.
        batch_size: The number of vectors to upsert in each batch (Pinecone recommends batches of 100 or fewer).
        namespace: Optional namespace for the upsert operation.
    """
    if not index:
        logger.error("Pinecone index not provided. Cannot upsert documents.")
        return
    if not documents or not embeddings:
        logger.warning("No documents or embeddings provided to upsert.")
        return
    if len(documents) != len(embeddings):
        logger.error(f"Mismatch between number of documents ({len(documents)}) and embeddings ({len(embeddings)}). Cannot upsert.")
        return

    total_documents = len(documents)
    upserted_count = 0
    error_count = 0

    for i in range(0, total_documents, batch_size):
        batch_documents = documents[i:i + batch_size]
        batch_embeddings = embeddings[i:i + batch_size]
        
        vectors_to_upsert = []
        for doc, emb in zip(batch_documents, batch_embeddings):
            # --- REVERTED ID GENERATION ---
            # Get ticketId from metadata (ensure key matches what's set in prepare_documents...)
            ticket_id = doc.metadata.get("ticketId") 

            if not ticket_id:
                logger.warning(f"Document is missing 'ticketId' in metadata. Skipping. Content snippet: {doc.page_content[:100]}...")
                error_count += 1
                continue
            
            # Use the ticketId directly as the Pinecone ID (must be string)
            pinecone_id = str(ticket_id)
            # --- END REVERTED ID GENERATION ---

            # Ensure metadata values are suitable for Pinecone 
            # The cleaning done in prepare_documents_for_embedding should handle this
            pinecone_metadata = doc.metadata 

            vectors_to_upsert.append({
                "id": pinecone_id,  # Use the ticketId as the ID
                "values": emb,
                "metadata": pinecone_metadata
            })

        if not vectors_to_upsert:
            logger.info(f"Batch {i // batch_size + 1} had no valid vectors to upsert. Skipping.")
            continue

        try:
            logger.info(f"Upserting batch {i // batch_size + 1}/{(total_documents + batch_size - 1) // batch_size} with {len(vectors_to_upsert)} vectors...")
            upsert_response = index.upsert(vectors=vectors_to_upsert, namespace=namespace)
            
            if upsert_response and hasattr(upsert_response, 'upserted_count') and upsert_response.upserted_count is not None:
                batch_upserted_count = upsert_response.upserted_count
                upserted_count += batch_upserted_count
                logger.info(f"Successfully upserted {batch_upserted_count} vectors in this batch.")
            else:
                # If upserted_count is not directly available or is None, we might assume all attempted were successful if no error
                # This can happen if the response structure varies or for older client versions.
                # For robustness, you might want to log the full response or handle this case based on Pinecone's current API.
                logger.warning(f"Upsert response for batch {i // batch_size + 1} did not return a clear upserted_count. Assuming {len(vectors_to_upsert)} were attempted. Full response: {upsert_response}")
                # We'll cautiously add the number we attempted to upsert to our count, but this part might need refinement.
                upserted_count += len(vectors_to_upsert)


        except Exception as e:
            logger.error(f"Error upserting batch {i // batch_size + 1} to Pinecone: {e}", exc_info=True)
            error_count += len(vectors_to_upsert) # Assume all in batch failed if exception occurs

    logger.info(f"Pinecone upsert process finished. Total documents processed: {total_documents}. Successfully upserted (estimated): {upserted_count}. Errors/Skipped: {error_count}.")

# --- NEW FUNCTION FOR INGESTION PIPELINE ---
def initialize_pinecone_vector_store_ingestion(embeddings: Embeddings) -> Optional[Index]:
    """
    Initializes and returns a Pinecone Index object specifically for the ingestion pipeline.
    If the index doesn't exist, it attempts to create it.
    (Currently identical to initialize_pinecone_vector_store, but provides a separate entry point)
    """
    pinecone_api_key = os.environ.get("PINECONE_API_KEY")
    pinecone_index_name = os.environ.get("PINECONE_INDEX_NAME")

    if not pinecone_api_key or not pinecone_index_name:
        logger.warning("Missing PINECONE_API_KEY or PINECONE_INDEX_NAME in environment variables.")
        return None
    
    if not embeddings:
        logger.error("Embeddings object not provided, cannot determine dimension for index creation.")
        return None

    try:
        pc = Pinecone(api_key=pinecone_api_key)
        existing_indexes = [idx.name for idx in pc.list_indexes().indexes]

        if pinecone_index_name not in existing_indexes:
            logger.info(f"Index '{pinecone_index_name}' not found. Attempting to create it...")
            
            dimension = get_embedding_dimension(embeddings)
            if dimension is None:
                logger.error(f"Failed to get embedding dimension. Cannot create index '{pinecone_index_name}'.")
                return None

            logger.info(f"Creating index '{pinecone_index_name}' with dimension {dimension}, metric '{PINECONE_METRIC}', cloud '{PINECONE_CLOUD}', region '{PINECONE_REGION}'.")
            try:
                pc.create_index(
                    name=pinecone_index_name,
                    dimension=dimension,
                    metric=PINECONE_METRIC,
                    spec=ServerlessSpec(
                        cloud=PINECONE_CLOUD,
                        region=PINECONE_REGION
                    ),
                    timeout=-1 # Wait indefinitely for creation, or set a specific timeout in seconds
                )
                # Wait for the index to be ready
                wait_time = 0
                max_wait_time = 300 # 5 minutes
                sleep_interval = 15 # seconds
                while wait_time < max_wait_time:
                    index_description = pc.describe_index(name=pinecone_index_name)
                    if index_description.status and index_description.status['ready']:
                        logger.info(f"Index '{pinecone_index_name}' created and is ready.")
                        break
                    logger.info(f"Waiting for index '{pinecone_index_name}' to be ready... ({wait_time}/{max_wait_time}s)")
                    time.sleep(sleep_interval)
                    wait_time += sleep_interval
                else:
                    logger.error(f"Index '{pinecone_index_name}' did not become ready within {max_wait_time} seconds.")
                    # Optionally, attempt to delete the partially created index or handle error
                    # try:
                    #     pc.delete_index(pinecone_index_name)
                    #     logger.info(f"Attempted to delete index '{pinecone_index_name}' after timeout.")
                    # except Exception as del_e:
                    #     logger.error(f"Failed to delete index '{pinecone_index_name}' after timeout: {del_e}")
                    return None
            except Exception as create_e:
                logger.error(f"Failed to create Pinecone index '{pinecone_index_name}': {create_e}", exc_info=True)
                return None
        else:
            logger.info(f"Index '{pinecone_index_name}' already exists.")

        index = pc.Index(pinecone_index_name)
        logger.info(f"Successfully connected to Pinecone index: {pinecone_index_name}")
        # Verify connection and get stats
        try:
            stats = index.describe_index_stats()
            logger.info(f"Index stats: {stats}")
        except Exception as e_stats:
            logger.warning(f"Could not retrieve stats for index '{pinecone_index_name}': {e_stats}")
        return index

    except Exception as e:
        logger.error(f"Error initializing Pinecone: {e}", exc_info=True)
        return None
# --- END NEW FUNCTION ---
