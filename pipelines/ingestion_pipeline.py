import os
import csv
import logging
from typing import List, Dict, Any
from langchain.schema import Document
from services.embedding_service import get_embeddings_in_batches
from services.vector_store_service import initialize_pinecone_vector_store, upsert_documents_to_pinecone
from services.embedding_service import get_cohere_embeddings # For initializing embeddings
from utils.jira_scraper import CSV_FILENAME # To get the default CSV file name

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define constants for batch sizes, can be overridden by environment variables or arguments if needed
PINECONE_UPSERT_BATCH_SIZE = int(os.environ.get("PINECONE_UPSERT_BATCH_SIZE", 100))
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", 96)) # Default for Cohere free tier

def load_tickets_from_csv(csv_filepath: str = CSV_FILENAME) -> List[Dict[str, Any]]:
    """Loads ticket data from the specified CSV file."""
    tickets = []
    try:
        with open(csv_filepath, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                tickets.append(row)
        logger.info(f"Successfully loaded {len(tickets)} tickets from '{csv_filepath}'.")
    except FileNotFoundError:
        logger.error(f"CSV file not found: '{csv_filepath}'. Please ensure Jira scraping has run.")
    except Exception as e:
        logger.error(f"Error loading tickets from CSV '{csv_filepath}': {e}", exc_info=True)
    return tickets

def prepare_documents_for_embedding(ticket_data: List[Dict[str, Any]]) -> List[Document]:
    """
    Prepares LangChain Document objects from ticket data.
    The text for embedding combines summary and description.
    Metadata includes ticket_id and other relevant fields.
    """
    langchain_documents = []
    for ticket in ticket_data:
        # Combine summary and description for the main content to be embedded
        # Handle cases where description might be missing or empty
        content = ticket.get('summary', '')
        description = ticket.get('description', '')
        if description and description.lower() != 'none' and description.lower() != 'null': # Check for common placeholders for empty
            content += "\n\n" + description

        # Prepare metadata, ensuring ticket_id is present
        metadata = {k: v for k, v in ticket.items()} # Start with all fields from CSV
        if 'ticket_id' not in metadata or not metadata['ticket_id']:
            logger.warning(f"Ticket data missing 'ticket_id'. Skipping record: {ticket.get('summary', 'N/A')[:50]}...")
            continue
        
        langchain_documents.append(Document(page_content=content, metadata=metadata))
    logger.info(f"Prepared {len(langchain_documents)} LangChain documents for embedding.")
    return langchain_documents

def run_ingestion_pipeline():
    """
    Main function to orchestrate the ingestion pipeline:
    1. Load tickets from CSV.
    2. Prepare Document objects.
    3. Initialize Cohere embeddings and Pinecone index.
    4. Get embeddings for documents in batches.
    5. Upsert documents and embeddings to Pinecone in batches.
    """
    logger.info("Starting Jira to Pinecone ingestion pipeline...")

    # 1. Load tickets from CSV
    # Assumes CSV_FILENAME is defined in jira_scraper and imported, or define path directly
    # For now, using the imported CSV_FILENAME from utils.jira_scraper
    jira_tickets = load_tickets_from_csv(csv_filepath=CSV_FILENAME)
    if not jira_tickets:
        logger.error("No tickets loaded from CSV. Aborting pipeline.")
        return

    # 2. Prepare Document objects
    documents_to_embed = prepare_documents_for_embedding(jira_tickets)
    if not documents_to_embed:
        logger.error("No documents prepared for embedding. Aborting pipeline.")
        return

    # 3. Initialize Cohere embeddings model (needed for Pinecone init if it relies on dimension)
    # and Pinecone index
    logger.info("Initializing Cohere embeddings model...")
    cohere_embeddings = get_cohere_embeddings() # From embedding_service
    if not cohere_embeddings:
        logger.error("Failed to initialize Cohere embeddings. Aborting pipeline.")
        return

    logger.info("Initializing Pinecone vector store...")
    # Pass the initialized embeddings object, though our current initialize_pinecone_vector_store doesn't use it directly
    # It's good practice if it were to e.g. get embedding dimension
    pinecone_index = initialize_pinecone_vector_store(embeddings=cohere_embeddings)
    if not pinecone_index:
        logger.error("Failed to initialize Pinecone index. Aborting pipeline.")
        return

    # 4. Get embeddings for documents in batches
    logger.info(f"Generating embeddings for {len(documents_to_embed)} documents in batches of {EMBEDDING_BATCH_SIZE}...")
    texts_to_embed = [doc.page_content for doc in documents_to_embed]
    
    # The get_embeddings_in_batches function is already in services.embedding_service
    # It uses the CohereEmbeddings object internally by calling get_cohere_embeddings()
    # So, we don't need to pass cohere_embeddings object directly to it.
    embeddings = get_embeddings_in_batches(texts=texts_to_embed, batch_size=EMBEDDING_BATCH_SIZE)

    if not embeddings or len(embeddings) != len(documents_to_embed):
        logger.error(f"Failed to generate embeddings or mismatch in count. Expected: {len(documents_to_embed)}, Got: {len(embeddings) if embeddings else 0}. Aborting.")
        return
    logger.info(f"Successfully generated {len(embeddings)} embeddings.")

    # 5. Upsert documents and embeddings to Pinecone in batches
    logger.info(f"Upserting {len(documents_to_embed)} documents to Pinecone in batches of {PINECONE_UPSERT_BATCH_SIZE}...")
    upsert_documents_to_pinecone(
        index=pinecone_index,
        documents=documents_to_embed,
        embeddings=embeddings,
        batch_size=PINECONE_UPSERT_BATCH_SIZE
        # namespace can be added here if needed, e.g., namespace="jira-tickets"
    )

    logger.info("Jira to Pinecone ingestion pipeline finished successfully.")

if __name__ == "__main__":
    # This allows the script to be run directly for testing or manual ingestion
    # Load .env variables if running standalone and they are not already loaded by a parent process
    from dotenv import load_dotenv
    load_dotenv() # Load environment variables from .env
    
    run_ingestion_pipeline() 