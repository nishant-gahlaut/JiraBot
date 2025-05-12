import os
import csv
import logging
from typing import List, Dict, Any
import pandas as pd
import re # IMPORT ADDED FOR FINAL WHITESPACE CHECK
from langchain.schema import Document
from services.embedding_service import get_embeddings_in_batches
from services.vector_store_service import initialize_pinecone_vector_store_ingestion, upsert_documents_to_pinecone
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
LLM_BATCH_SIZE = int(os.environ.get("LLM_BATCH_SIZE", 50)) 

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
    Generates concise problem statements and solution summaries using an LLM IN BATCHES.
    Creates ONE Document per ticket, with page_content as the problem_statement.
    Metadata includes ticketId, title, original fields, and both LLM-generated
    problem_statement and solution_summary.
    """
    langchain_documents = [] 
    all_problem_statements = {} 
    all_solution_summaries = {} 
    total_problem_llm_errors = 0
    total_solution_llm_errors = 0
    num_tickets = len(ticket_data_df)
    logger.info(f"Preparing documents for {num_tickets} tickets, using LLM batch size {LLM_BATCH_SIZE}.")

    # Process DataFrame in chunks/batches for LLM calls
    for i in range(0, num_tickets, LLM_BATCH_SIZE):
        chunk_df = ticket_data_df.iloc[i:i + LLM_BATCH_SIZE]
        batch_num = i // LLM_BATCH_SIZE + 1
        total_batches = (num_tickets + LLM_BATCH_SIZE - 1) // LLM_BATCH_SIZE
        logger.info(f"Processing LLM batch {batch_num} / {total_batches} (tickets {i} to {min(i + LLM_BATCH_SIZE, num_tickets) - 1})")

        # --- Problem statement generation ---
        problem_batch_input_data = []
        for index, ticket in chunk_df.iterrows():
            problem_batch_input_data.append({
                "id": index, 
                "summary": ticket.get('cleaned_summary', ''),
                "description": ticket.get('cleaned_description', '')
            })
        batch_problem_statements_results = [] # Renamed for clarity
        if problem_batch_input_data:
            batch_problem_statements_results = generate_concise_problem_statements_batch(problem_batch_input_data)
            if len(batch_problem_statements_results) != len(problem_batch_input_data):
                logger.error(f"LLM problem statement batch result size mismatch! Expected {len(problem_batch_input_data)}, got {len(batch_problem_statements_results)}. Marking all as errors.")
                batch_problem_statements_results = [f"Error: Batch result size mismatch for item {item.get('id', 'N/A')}" for item in problem_batch_input_data]
                total_problem_llm_errors += len(problem_batch_input_data)
        else:
            logger.warning(f"Problem batch input was empty for batch {batch_num}. Skipping problem generation.")

        # --- Solution summary generation ---
        solution_batch_input_data = []
        for index, ticket in chunk_df.iterrows():
            solution_batch_input_data.append({
                "id": index, 
                "cleaned_comments": ticket.get('cleaned_comments', '')
            })
        batch_solution_summaries_results = [] # Renamed for clarity
        if solution_batch_input_data:
            batch_solution_summaries_results = generate_concise_solutions_batch(solution_batch_input_data)
            if len(batch_solution_summaries_results) != len(solution_batch_input_data):
                logger.error(f"LLM solution summary batch result size mismatch! Expected {len(solution_batch_input_data)}, got {len(batch_solution_summaries_results)}. Marking all as errors.")
                batch_solution_summaries_results = [f"Error: Batch solution result size mismatch for item {item.get('id', 'N/A')}" for item in solution_batch_input_data]
                total_solution_llm_errors += len(solution_batch_input_data)
        else:
            logger.warning(f"Solution batch input was empty for batch {batch_num}. Skipping solution generation.")

        # --- Store LLM results keyed by original DataFrame index ---
        batch_problem_errors_this_batch = 0 # Renamed for clarity
        batch_solution_errors_this_batch = 0 # Renamed for clarity

        for idx in range(len(chunk_df)):
            original_ticket_index = chunk_df.index[idx]
            ticket_data = chunk_df.iloc[idx]

            # Store problem statement
            problem_statement_text = "Error: Problem generation failed or skipped"
            if idx < len(batch_problem_statements_results):
                current_problem_result = batch_problem_statements_results[idx]
                if isinstance(current_problem_result, str) and current_problem_result.startswith("Error:"):
                    batch_problem_errors_this_batch += 1
                    logger.warning(f"Problem statement LLM failed for ticket index {original_ticket_index} (ID: {ticket_data.get('ticket_id', 'N/A')}). Error: {current_problem_result}")
                    # Store the error as the problem statement for this ticket
                    problem_statement_text = current_problem_result 
                else:
                    problem_statement_text = current_problem_result
            else:
                logger.error(f"Problem statement result missing for index {idx} in batch {batch_num}.")
                batch_problem_errors_this_batch += 1
                problem_statement_text = "Error: Problem statement result missing in batch"
            all_problem_statements[original_ticket_index] = problem_statement_text

            # Store solution summary
            solution_summary_text = "Error: Solution generation failed or skipped"
            if idx < len(batch_solution_summaries_results):
                current_solution_result = batch_solution_summaries_results[idx]
                if isinstance(current_solution_result, str) and current_solution_result.startswith("Error:"):
                    batch_solution_errors_this_batch += 1
                    logger.warning(f"Solution summary LLM failed for ticket index {original_ticket_index} (ID: {ticket_data.get('ticket_id', 'N/A')}). Error: {current_solution_result}")
                elif isinstance(current_solution_result, str) and current_solution_result == "No clear solution or significant progress identified in the comments.":
                    logger.info(f"No solution identified by LLM for ticket index {original_ticket_index} (ID: {ticket_data.get('ticket_id', 'N/A')}).")
                # In all these cases, we store what we got (error, specific message, or valid summary)
                solution_summary_text = current_solution_result
            else:
                logger.error(f"Solution summary result missing for index {idx} in batch {batch_num}.")
                batch_solution_errors_this_batch += 1
                solution_summary_text = "Error: Solution result missing in batch"
            all_solution_summaries[original_ticket_index] = solution_summary_text

        if batch_problem_errors_this_batch > 0:
            total_problem_llm_errors += batch_problem_errors_this_batch # Accumulate total errors
        if batch_solution_errors_this_batch > 0:
            total_solution_llm_errors += batch_solution_errors_this_batch # Accumulate total errors

    # --- Create ONE Document per ticket with problem_statement as content and both summaries in metadata ---
    logger.info(f"Creating LangChain Document objects for {num_tickets} tickets...")
    documents_created_count = 0
    skipped_tickets_no_id_count = 0
    skipped_tickets_no_problem_count = 0

    metadata_fields = [
        'ticket_id', 'summary', 'status', 'priority', 'reporter', 'assignee', 
        'created_at', 'updated_at', 'labels', 'components', 'owned_by_team', 
        'brand', 'product', 'geo_region', 'environment', 'root_cause', 'sprint'
    ]

    for index, ticket_row in ticket_data_df.iterrows():
        original_ticket_id = ticket_row.get('ticket_id') # Use original ticket_id for Pinecone ID
        if not original_ticket_id:
            logger.warning(f"Ticket data missing 'ticket_id' at original index {index}. Skipping record creation.")
            skipped_tickets_no_id_count += 1
            continue

        llm_problem_statement = all_problem_statements.get(index, "")
        if not llm_problem_statement or llm_problem_statement.startswith("Error:"):
            logger.warning(f"Skipping ticket {original_ticket_id} (index {index}) due to missing or failed LLM problem statement. Statement: '{llm_problem_statement}'")
            skipped_tickets_no_problem_count += 1
            continue

        llm_solution_summary = all_solution_summaries.get(index, "Error: Solution summary not found after LLM processing")

        # Prepare metadata dictionary
        metadata = {field: ticket_row.get(field) for field in metadata_fields}
        metadata["ticketId"] = original_ticket_id # Ensure this key is consistently named for Pinecone ID
        metadata["title"] = ticket_row.get('summary', '') 
        metadata["retrieved_problem_statement"] = llm_problem_statement # Store LLM problem statement in metadata
        metadata["retrieved_solution_summary"] = llm_solution_summary # Store LLM solution summary in metadata
        # No content_type field needed anymore
        
        # Clean metadata values for Pinecone
        for key, value in metadata.items():
            if isinstance(value, list):
                metadata[key] = ", ".join(map(str, value)) if value else ""
            elif value is None:
                metadata[key] = ""
            else:
                metadata[key] = str(value)

        # Create ONE Document per ticket
        # page_content is the LLM-generated problem statement
        langchain_documents.append(Document(page_content=llm_problem_statement, metadata=metadata))
        documents_created_count += 1

    logger.info(f"Finished preparing LangChain documents. Total documents created: {len(langchain_documents)} ({documents_created_count} documents). Skipped {skipped_tickets_no_id_count} (no ID), {skipped_tickets_no_problem_count} (no problem statement).")
    if total_problem_llm_errors > 0:
        logger.warning(f"Total Problem statement LLM failures during generation: {total_problem_llm_errors}.")
    if total_solution_llm_errors > 0:
        logger.warning(f"Total Solution summary LLM failures/invalid responses during generation: {total_solution_llm_errors}.")

    # --- ADDED: Save LLM outputs and key metadata to CSV --- 
    logger.info("Preparing data for LLM outputs CSV export...")
    data_for_llm_summary_csv = []
    for doc in langchain_documents:
        # Ensure metadata exists and get values safely
        metadata = doc.metadata if doc.metadata else {}
        data_for_llm_summary_csv.append({
            'ticket_id': metadata.get('ticketId', 'N/A'), # Use the consistent ticketId key
            'original_summary': metadata.get('title', ''), # Original summary stored as title
            'llm_problem_statement': metadata.get('retrieved_problem_statement', 'Error: Not found in metadata'),
            'llm_solution_summary': metadata.get('retrieved_solution_summary', 'Error: Not found in metadata')
            # Add other metadata fields here if needed for the CSV
        })

    if data_for_llm_summary_csv:
        llm_summary_df = pd.DataFrame(data_for_llm_summary_csv)
        output_csv_filename = "llm_outputs_summary.csv"
        try:
            # Use quoting to handle potential commas/newlines in summaries
            llm_summary_df.to_csv(output_csv_filename, index=False, encoding='utf-8', quoting=csv.QUOTE_ALL)
            logger.info(f"Successfully saved LLM output summary for {len(llm_summary_df)} documents to '{output_csv_filename}'.")
        except Exception as e:
            logger.error(f"Failed to save LLM output summary data to CSV '{output_csv_filename}': {e}", exc_info=True)
    else:
        logger.warning("No data extracted from documents to save to LLM summary CSV.")
    # --- END ADDED CSV EXPORT --- 

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
    logger.info("Initializing Cohere embeddings model...")
    cohere_embeddings = get_cohere_embeddings() # From embedding_service
    if not cohere_embeddings:
        logger.error("Failed to initialize Cohere embeddings. Aborting pipeline.")
        return

    logger.info("Initializing Pinecone vector store...")
    # Pass the initialized embeddings object, though our current initialize_pinecone_vector_store doesn't use it directly
    # It's good practice if it were to e.g. get embedding dimension
    # UPDATED to use the new ingestion-specific function
    pinecone_index = initialize_pinecone_vector_store_ingestion(embeddings=cohere_embeddings)
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