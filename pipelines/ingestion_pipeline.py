import os
import csv
import logging
from typing import List, Dict, Any
import pandas as pd
import re # IMPORT ADDED FOR FINAL WHITESPACE CHECK
from langchain.schema import Document
from services.embedding_service import get_embeddings_in_batches
from services.vector_store_service import initialize_pinecone_vector_store, upsert_documents_to_pinecone
from services.embedding_service import get_cohere_embeddings # For initializing embeddings
from utils.jira_scraper import CSV_FILENAME # To get the default CSV file name
from utils.data_cleaning_ingestion_pipeline import clean_all_columns # ADDED IMPORT
from services.genai_service import generate_concise_problem_statements_batch # IMPORT ADDED FOR LLM CALL

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define constants for batch sizes, can be overridden by environment variables or arguments if needed
PINECONE_UPSERT_BATCH_SIZE = int(os.environ.get("PINECONE_UPSERT_BATCH_SIZE", 100))
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", 96)) # Default for Cohere free tier
# Define batch size for LLM calls
LLM_BATCH_SIZE = int(os.environ.get("LLM_PROBLEM_STATEMENT_BATCH_SIZE", 50)) 

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

def prepare_documents_for_embedding(ticket_data_df: pd.DataFrame) -> List[Document]:
    """
    Prepares LangChain Document objects from the cleaned ticket DataFrame.
    Generates concise problem statements using an LLM IN BATCHES for embedding content.
    Metadata includes ticket_id and other relevant fields from the original CSV/DataFrame.
    """
    langchain_documents = []
    total_llm_errors = 0
    num_tickets = len(ticket_data_df)
    logger.info(f"Preparing documents for {num_tickets} tickets, using LLM batch size {LLM_BATCH_SIZE}.")

    # Process DataFrame in chunks/batches for LLM calls
    for i in range(0, num_tickets, LLM_BATCH_SIZE):
        chunk_df = ticket_data_df.iloc[i:i + LLM_BATCH_SIZE]
        logger.info(f"Processing LLM batch {i // LLM_BATCH_SIZE + 1} / { (num_tickets + LLM_BATCH_SIZE - 1) // LLM_BATCH_SIZE } (tickets {i} to {min(i + LLM_BATCH_SIZE, num_tickets) - 1})")

        # Prepare input data for the batch function
        batch_input_data = []
        for index, ticket in chunk_df.iterrows():
            batch_input_data.append({
                "id": index, # Use DataFrame index as unique ID for this batch
                "summary": ticket.get('cleaned_summary', ''),
                "description": ticket.get('cleaned_description', '')
            })

        if not batch_input_data:
            continue # Skip if chunk was empty for some reason

        # *** CALL BATCH LLM FUNCTION ***
        batch_problem_statements = generate_concise_problem_statements_batch(batch_input_data)

        # Check if the number of results matches the input batch size
        if len(batch_problem_statements) != len(batch_input_data):
            logger.error(f"LLM batch result size mismatch in prepare_documents! Expected {len(batch_input_data)}, got {len(batch_problem_statements)}. Skipping batch {i // LLM_BATCH_SIZE + 1}. Check logs.")
            total_llm_errors += len(batch_input_data) # Count all items in failed batch as errors
            continue # Skip processing this entire batch

        # Process the results for this batch
        batch_llm_errors = 0
        for result_index, problem_statement in enumerate(batch_problem_statements):
            original_ticket_index = batch_input_data[result_index]["id"] # Get original index
            ticket = ticket_data_df.loc[original_ticket_index] # Get original ticket data
            
            page_content = ""
            # Check if the result indicates an error
            if isinstance(problem_statement, str) and problem_statement.startswith("Error:"):
                batch_llm_errors += 1
                logger.warning(f"LLM failed for ticket index {original_ticket_index} (ID: {ticket.get('ticket_id', 'N/A')}). Using fallback content. Error: {problem_statement}")
                # Fallback strategy: Combine cleaned fields
                summary = ticket.get('cleaned_summary', '')
                description = ticket.get('cleaned_description', '')
                content_parts = [summary, description]
                page_content = " ".join(part for part in content_parts if part and isinstance(part, str) and part.strip())
                page_content = re.sub(r'\s+', ' ', page_content).strip() # Final whitespace check
            else:
                # Use the successful LLM generation
                page_content = problem_statement

            # If after fallback or LLM, page_content is empty, maybe skip?
            if not page_content:
                 logger.warning(f"Skipping ticket index {original_ticket_index} (ID: {ticket.get('ticket_id', 'N/A')}) due to empty page_content after LLM attempt/fallback.")
                 continue

            # Prepare metadata (exclude cleaned columns)
            metadata = {k: v for k, v in ticket.items() if k not in ['cleaned_summary', 'cleaned_description']}
            metadata['df_index'] = original_ticket_index # ADD DATAFRAME INDEX TO METADATA
            
            # Ensure ticket_id is present in metadata
            if 'ticket_id' not in metadata or not metadata['ticket_id']:
                logger.warning(f"Ticket data missing 'ticket_id' at index {original_ticket_index} while preparing document. Skipping record: {ticket.get('summary', 'N/A')[:50]}...")
                continue
            
            # Create and append the LangChain Document
            langchain_documents.append(Document(page_content=page_content, metadata=metadata))

        # Log errors for the batch
        if batch_llm_errors > 0:
             logger.warning(f"LLM generation failed for {batch_llm_errors} tickets in batch {i // LLM_BATCH_SIZE + 1}.")
             total_llm_errors += batch_llm_errors
            
    logger.info(f"Finished preparing {len(langchain_documents)} LangChain documents using LLM batch processing.")
    if total_llm_errors > 0:
        logger.warning(f"Total LLM generation failures across all batches: {total_llm_errors}. Used fallback content for these.")
        
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
        
    # Convert list of dicts to DataFrame
    jira_tickets_df = pd.DataFrame(jira_tickets)
    logger.info(f"Converted loaded tickets to DataFrame. Shape: {jira_tickets_df.shape}")

    # *** ADDED DATA CLEANING STEP ***
    logger.info("Starting data cleaning process...")
    try:
        # Apply the cleaning pipeline defined in the utils module
        jira_tickets_df = clean_all_columns(jira_tickets_df)
        logger.info(f"Data cleaning finished. DataFrame shape remains: {jira_tickets_df.shape}")
        # Optionally: Log info about cleaned columns, e.g., how many comments remain non-empty
        non_empty_comments = len(jira_tickets_df[jira_tickets_df['cleaned_comments'].str.len() > 0])
        logger.info(f"Number of tickets with non-empty cleaned_comments after filtering/cleaning: {non_empty_comments}")
    except Exception as e:
        logger.error(f"Error during data cleaning: {e}", exc_info=True)
        logger.error("Aborting pipeline due to data cleaning error.")
        return
    # *** END OF ADDED DATA CLEANING STEP ***

    # 2. Prepare Document objects (using the cleaned DataFrame)
    documents_to_embed = prepare_documents_for_embedding(jira_tickets_df) # Pass the DataFrame
    if not documents_to_embed:
        logger.error("No documents prepared for embedding after cleaning. Aborting pipeline.")
        return
    logger.info(f"--- Debugging: Printing details for {len(documents_to_embed)} prepared documents ---")
    for i, doc in enumerate(documents_to_embed):
        # Extract metadata safely using .get()
        metadata = doc.metadata if doc.metadata else {}
        ticket_id = metadata.get('ticket_id', 'N/A')
        summary = metadata.get('summary', 'N/A')
        description = metadata.get('description', 'N/A')
        # Note: 'comments' in metadata might be the original, not the cleaned version used for LLM input.
        # The 'cleaned_comments' were used in prepare_documents_for_embedding but might not be in final metadata.
        # We'll print what's available in the final Document metadata.
        comments = metadata.get('comments', 'N/A') 
        
        # The page_content is the LLM-generated problem statement or the fallback content
        problem_statement = doc.page_content

        logger.info(f"Document {i+1} (Ticket ID: {ticket_id}):")
        # Print snippets to keep logs manageable
        logger.info(f"  Metadata Summary: {str(summary)[:150]}...") 
        logger.info(f"  Metadata Description: {str(description)[:150]}...")
        logger.info(f"  Metadata Comments: {str(comments)[:150]}...")
        logger.info(f"  LLM Problem Statement (page_content): {str(problem_statement)[:200]}...")
        logger.info("-" * 20) # Separator for readability

    logger.info("--- Finished printing document details ---")
    # Create a DataFrame from the prepared documents for saving to CSV
    logger.info("Preparing data for summary_jira.csv export...")
    data_for_summary_csv = []
    for doc in documents_to_embed:
        metadata = doc.metadata if doc.metadata else {}
        df_index = metadata.get('df_index') # Get the DataFrame index from metadata
        
        cleaned_summary = "Error: Index missing" 
        cleaned_description = "Error: Index missing"
        cleaned_comments = "Error: Index missing"
        
        # Look up the original row in the DataFrame using the index
        if df_index is not None and df_index in jira_tickets_df.index:
            original_row = jira_tickets_df.loc[df_index]
            cleaned_summary = original_row.get('cleaned_summary', 'Error: Column missing')
            cleaned_description = original_row.get('cleaned_description', 'Error: Column missing')
            cleaned_comments = original_row.get('cleaned_comments', 'Error: Column missing')
        elif df_index is None:
             logger.warning(f"Document for ticket {metadata.get('ticket_id', 'N/A')} is missing 'df_index' in metadata. Cannot retrieve cleaned data for CSV.")
        else: # df_index not None but not in jira_tickets_df.index
             logger.warning(f"DataFrame index {df_index} from document metadata not found in jira_tickets_df. Cannot retrieve cleaned data for CSV for ticket {metadata.get('ticket_id', 'N/A')}.")

        data_for_summary_csv.append({
            'ticket_id': metadata.get('ticket_id', 'N/A'),
            'original_summary': metadata.get('summary', ''),
            'cleaned_summary': cleaned_summary, # ADDED
            'original_description': metadata.get('description', ''),
            'cleaned_description': cleaned_description, # ADDED
            'original_comments': metadata.get('comments', ''), 
            'cleaned_comments': cleaned_comments, # ADDED
            'llm_problem_statement': doc.page_content # This is the content used for embedding
        })
    
    if data_for_summary_csv:
        summary_df = pd.DataFrame(data_for_summary_csv)
        output_csv_filename = "summary_jira2.csv"
        try:
            summary_df.to_csv(output_csv_filename, index=False, encoding='utf-8', quoting=csv.QUOTE_ALL)
            logger.info(f"Successfully saved summary data for {len(summary_df)} documents to '{output_csv_filename}'.")
        except Exception as e:
            logger.error(f"Failed to save summary data to CSV '{output_csv_filename}': {e}", exc_info=True)
            # Decide if this error should halt the pipeline or just be logged
            # For now, just log it and continue
    else:
        logger.warning("No data extracted from documents to save to summary_jira.csv.")
    # # 3. Initialize Cohere embeddings model (needed for Pinecone init if it relies on dimension)
    # # and Pinecone index
    # logger.info("Initializing Cohere embeddings model...")
    # cohere_embeddings = get_cohere_embeddings() # From embedding_service
    # if not cohere_embeddings:
    #     logger.error("Failed to initialize Cohere embeddings. Aborting pipeline.")
    #     return

    # logger.info("Initializing Pinecone vector store...")
    # # Pass the initialized embeddings object, though our current initialize_pinecone_vector_store doesn't use it directly
    # # It's good practice if it were to e.g. get embedding dimension
    # pinecone_index = initialize_pinecone_vector_store(embeddings=cohere_embeddings)
    # if not pinecone_index:
    #     logger.error("Failed to initialize Pinecone index. Aborting pipeline.")
    #     return

    # # 4. Get embeddings for documents in batches
    # logger.info(f"Generating embeddings for {len(documents_to_embed)} documents in batches of {EMBEDDING_BATCH_SIZE}...")
    # texts_to_embed = [doc.page_content for doc in documents_to_embed]
    
    # # The get_embeddings_in_batches function is already in services.embedding_service
    # # It uses the CohereEmbeddings object internally by calling get_cohere_embeddings()
    # # So, we don't need to pass cohere_embeddings object directly to it.
    # embeddings = get_embeddings_in_batches(texts=texts_to_embed, batch_size=EMBEDDING_BATCH_SIZE)

    # if not embeddings or len(embeddings) != len(documents_to_embed):
    #     logger.error(f"Failed to generate embeddings or mismatch in count. Expected: {len(documents_to_embed)}, Got: {len(embeddings) if embeddings else 0}. Aborting.")
    #     return
    # logger.info(f"Successfully generated {len(embeddings)} embeddings.")

    # # 5. Upsert documents and embeddings to Pinecone in batches
    # logger.info(f"Upserting {len(documents_to_embed)} documents to Pinecone in batches of {PINECONE_UPSERT_BATCH_SIZE}...")
    # upsert_documents_to_pinecone(
    #     index=pinecone_index,
    #     documents=documents_to_embed,
    #     embeddings=embeddings,
    #     batch_size=PINECONE_UPSERT_BATCH_SIZE
    #     # namespace can be added here if needed, e.g., namespace="jira-tickets"
    # )

    logger.info("Jira to Pinecone ingestion pipeline finished successfully.")

if __name__ == "__main__":
    # This allows the script to be run directly for testing or manual ingestion
    # Load .env variables if running standalone and they are not already loaded by a parent process
    from dotenv import load_dotenv
    load_dotenv() # Load environment variables from .env
    
    run_ingestion_pipeline() 