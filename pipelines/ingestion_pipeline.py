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
from services.genai_service import generate_concise_solutions_batch # IMPORT ADDED FOR SOLUTION LLM CALL

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
    Generates concise solution summaries using an LLM IN BATCHES from comments.
    Metadata includes ticket_id, solution_summary, and other relevant fields.
    """
    langchain_documents = []
    total_problem_llm_errors = 0
    total_solution_llm_errors = 0
    num_tickets = len(ticket_data_df)
    logger.info(f"Preparing documents for {num_tickets} tickets, using LLM batch size {LLM_BATCH_SIZE}.")

    all_solution_summaries = {} # Dictionary to store solutions keyed by original DataFrame index

    # Process DataFrame in chunks/batches for LLM calls
    for i in range(0, num_tickets, LLM_BATCH_SIZE):
        chunk_df = ticket_data_df.iloc[i:i + LLM_BATCH_SIZE]
        batch_num = i // LLM_BATCH_SIZE + 1
        total_batches = (num_tickets + LLM_BATCH_SIZE - 1) // LLM_BATCH_SIZE
        logger.info(f"Processing LLM batch {batch_num} / {total_batches} (tickets {i} to {min(i + LLM_BATCH_SIZE, num_tickets) - 1})")

        # --- Prepare input data for PROBLEM statement generation ---
        problem_batch_input_data = []
        for index, ticket in chunk_df.iterrows():
            problem_batch_input_data.append({
                "id": index, # Use DataFrame index as unique ID for this batch
                "summary": ticket.get('cleaned_summary', ''),
                "description": ticket.get('cleaned_description', '')
                # Comments are not needed for problem statement generation per the current prompt
            })

        # --- Call LLM for PROBLEM statements ---
        batch_problem_statements = []
        if problem_batch_input_data:
            batch_problem_statements = generate_concise_problem_statements_batch(problem_batch_input_data)
            if len(batch_problem_statements) != len(problem_batch_input_data):
                logger.error(f"LLM problem statement batch result size mismatch! Expected {len(problem_batch_input_data)}, got {len(batch_problem_statements)}. Marking all as errors for batch {batch_num}.")
                # Mark all as errors for this batch
                batch_problem_statements = [f"Error: Batch result size mismatch for item {item.get('id', 'N/A')}" for item in problem_batch_input_data]
                total_problem_llm_errors += len(problem_batch_input_data)
        else:
            logger.warning(f"Problem batch input was empty for batch {batch_num}. Skipping problem generation.")

        # --- Prepare input data for SOLUTION summary generation ---
        solution_batch_input_data = []
        for index, ticket in chunk_df.iterrows():
            solution_batch_input_data.append({
                "id": index, # Use DataFrame index as unique ID
                "cleaned_comments": ticket.get('cleaned_comments', '') # Only need comments for solutions
            })

        # --- Call LLM for SOLUTION summaries ---
        batch_solution_summaries = []
        if solution_batch_input_data:
            batch_solution_summaries = generate_concise_solutions_batch(solution_batch_input_data)
            if len(batch_solution_summaries) != len(solution_batch_input_data):
                logger.error(f"LLM solution summary batch result size mismatch! Expected {len(solution_batch_input_data)}, got {len(batch_solution_summaries)}. Marking all as errors for batch {batch_num}.")
                # Mark all as errors for this batch
                batch_solution_summaries = [f"Error: Batch solution result size mismatch for item {item.get('id', 'N/A')}" for item in solution_batch_input_data]
                total_solution_llm_errors += len(solution_batch_input_data)
        else:
            logger.warning(f"Solution batch input was empty for batch {batch_num}. Skipping solution generation.")

        # --- Process results and create Documents for this batch ---
        batch_problem_errors = 0
        batch_solution_errors = 0
        for idx in range(len(chunk_df)):
            original_ticket_index = chunk_df.index[idx] # Get original DataFrame index
            ticket = chunk_df.iloc[idx] # Get original ticket data

            # Get problem statement result
            problem_statement = ""
            if idx < len(batch_problem_statements):
                 problem_statement = batch_problem_statements[idx]
                 if isinstance(problem_statement, str) and problem_statement.startswith("Error:"):
                    batch_problem_errors += 1
                    logger.warning(f"Problem statement LLM failed for ticket index {original_ticket_index} (ID: {ticket.get('ticket_id', 'N/A')}). Using fallback. Error: {problem_statement}")
                    # Fallback strategy: Combine cleaned fields
                    summary = ticket.get('cleaned_summary', '')
                    description = ticket.get('cleaned_description', '')
                    content_parts = [summary, description]
                    page_content = " ".join(part for part in content_parts if part and isinstance(part, str) and part.strip())
                    page_content = re.sub(r'\\s+', ' ', page_content).strip() # Final whitespace check
                 else:
                     page_content = problem_statement # Use successful generation
            else:
                 # Should not happen if batch sizes match, but handle defensively
                 logger.error(f"Problem statement result missing for index {idx} in batch {batch_num}. Using fallback.")
                 batch_problem_errors += 1
                 summary = ticket.get('cleaned_summary', '')
                 description = ticket.get('cleaned_description', '')
                 content_parts = [summary, description]
                 page_content = " ".join(part for part in content_parts if part and isinstance(part, str) and part.strip())
                 page_content = re.sub(r'\\s+', ' ', page_content).strip()

            # Get solution summary result
            solution_summary = "Error: Solution generation failed or skipped" # Default / Fallback
            if idx < len(batch_solution_summaries):
                solution_summary = batch_solution_summaries[idx]
                if isinstance(solution_summary, str) and solution_summary.startswith("Error:"):
                    batch_solution_errors += 1
                    logger.warning(f"Solution summary LLM failed for ticket index {original_ticket_index} (ID: {ticket.get('ticket_id', 'N/A')}). Storing error message. Error: {solution_summary}")
                elif solution_summary == "No clear solution identified in the comments.":
                    logger.info(f"No solution identified by LLM for ticket index {original_ticket_index} (ID: {ticket.get('ticket_id', 'N/A')}).")
                # else: use the successful solution_summary
            else:
                 logger.error(f"Solution summary result missing for index {idx} in batch {batch_num}. Storing error.")
                 batch_solution_errors += 1

            # Store the solution summary globally keyed by index
            all_solution_summaries[original_ticket_index] = solution_summary

            # --- Create Document ---
            if not page_content:
                 logger.warning(f"Skipping ticket index {original_ticket_index} (ID: {ticket.get('ticket_id', 'N/A')}) due to empty page_content after LLM attempt/fallback.")
                 continue

            # Prepare metadata (exclude cleaned text columns, add solution)
            metadata = {k: v for k, v in ticket.items() if k not in ['cleaned_summary', 'cleaned_description', 'cleaned_comments']}
            metadata['df_index'] = original_ticket_index
            metadata['solution_summary'] = solution_summary # ADDED SOLUTION SUMMARY

            if 'ticket_id' not in metadata or not metadata['ticket_id']:
                logger.warning(f"Ticket data missing 'ticket_id' at index {original_ticket_index}. Skipping record: {ticket.get('summary', 'N/A')[:50]}...")
                continue

            langchain_documents.append(Document(page_content=page_content, metadata=metadata))

        # Log errors for the batch
        if batch_problem_errors > 0:
             logger.warning(f"Problem statement LLM failed for {batch_problem_errors} tickets in batch {batch_num}.")
             total_problem_llm_errors += batch_problem_errors
        if batch_solution_errors > 0:
             logger.warning(f"Solution summary LLM failed for {batch_solution_errors} tickets in batch {batch_num}.")
             total_solution_llm_errors += batch_solution_errors

    logger.info(f"Finished preparing {len(langchain_documents)} LangChain documents using LLM batch processing.")
    if total_problem_llm_errors > 0:
        logger.warning(f"Total Problem statement LLM failures: {total_problem_llm_errors}.")
    if total_solution_llm_errors > 0:
        logger.warning(f"Total Solution summary LLM failures: {total_solution_llm_errors}.")

    # --- DEBUGGING: Update CSV export logic ---
    # Add the solution summary to the CSV export
    logger.info("Preparing data for summary CSV export (including solutions)...")
    data_for_summary_csv = []
    for doc in langchain_documents:
        metadata = doc.metadata if doc.metadata else {}
        df_index = metadata.get('df_index')
        solution_summary = metadata.get('solution_summary', 'Error: Not found in metadata') # Get solution from metadata

        cleaned_summary = "Error: Index missing"
        cleaned_description = "Error: Index missing"
        cleaned_comments = "Error: Index missing"

        if df_index is not None and df_index in ticket_data_df.index:
            original_row = ticket_data_df.loc[df_index]
            cleaned_summary = original_row.get('cleaned_summary', 'Error: Column missing')
            cleaned_description = original_row.get('cleaned_description', 'Error: Column missing')
            cleaned_comments = original_row.get('cleaned_comments', 'Error: Column missing')
            # Double-check solution summary consistency if needed, though it should be in metadata now
            # stored_solution = all_solution_summaries.get(df_index, 'Error: Not found in global dict')
            # if stored_solution != solution_summary: logger.warning(...)
        elif df_index is None:
             logger.warning(f"Doc for ticket {metadata.get('ticket_id', 'N/A')} missing 'df_index'. Cannot retrieve full data for CSV.")
        else:
             logger.warning(f"Index {df_index} not found in DataFrame. Cannot retrieve full data for CSV for ticket {metadata.get('ticket_id', 'N/A')}.")

        data_for_summary_csv.append({
            'ticket_id': metadata.get('ticket_id', 'N/A'),
            'original_summary': metadata.get('summary', ''),
            'cleaned_summary': cleaned_summary,
            'original_description': metadata.get('description', ''),
            'cleaned_description': cleaned_description,
            'original_comments': metadata.get('comments', ''),
            'cleaned_comments': cleaned_comments,
            'llm_problem_statement': doc.page_content,
            'llm_solution_summary': solution_summary # ADDED
        })

    if data_for_summary_csv:
        summary_df = pd.DataFrame(data_for_summary_csv)
        # Incrementing CSV name to avoid overwriting previous debug outputs
        output_csv_filename = "summary_jira_with_solutions.csv" # Updated filename
        try:
            summary_df.to_csv(output_csv_filename, index=False, encoding='utf-8', quoting=csv.QUOTE_ALL)
            logger.info(f"Successfully saved summary data for {len(summary_df)} documents to '{output_csv_filename}'.")
        except Exception as e:
            logger.error(f"Failed to save summary data to CSV '{output_csv_filename}': {e}", exc_info=True)
    else:
        logger.warning("No data extracted from documents to save to summary CSV.")

    # --- END DEBUGGING CSV EXPORT ---

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
    # if not documents_to_embed:
    #     logger.error("No documents prepared for embedding after cleaning. Aborting pipeline.")
    #     return
    logger.info(f"--- Debugging: Printing details for {len(documents_to_embed)} prepared documents ---")
    # for i, doc in enumerate(documents_to_embed):
    #     # Extract metadata safely using .get()
    #     metadata = doc.metadata if doc.metadata else {}
    #     ticket_id = metadata.get('ticket_id', 'N/A')
    #     summary = metadata.get('summary', 'N/A')
    #     description = metadata.get('description', 'N/A')
    #     comments = metadata.get('comments', 'N/A')
    #     solution = metadata.get('solution_summary', 'N/A') # GET SOLUTION SUMMARY

        # # The page_content is the LLM-generated problem statement or the fallback content
        # problem_statement = doc.page_content

        # logger.info(f"Document {i+1} (Ticket ID: {ticket_id}):")
        # # Print snippets to keep logs manageable
        # logger.info(f"  Metadata Summary: {str(summary)[:150]}...")
        # logger.info(f"  Metadata Description: {str(description)[:150]}...")
        # logger.info(f"  Metadata Comments: {str(comments)[:150]}...")
        # logger.info(f"  Metadata Solution Summary: {str(solution)[:200]}...") # LOG SOLUTION
        # logger.info(f"  LLM Problem Statement (page_content): {str(problem_statement)[:200]}...")
        # logger.info("-" * 20) # Separator for readability

    logger.info("--- Finished printing document details ---")
    # 3. Initialize Cohere embeddings model (needed for Pinecone init if it relies on dimension)
    # and Pinecone index
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