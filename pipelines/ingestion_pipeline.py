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
LLM_BATCH_SIZE = int(os.environ.get("LLM_BATCH_SIZE", 50))  # New constant for processing the main CSV in chunks

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

    Returns:
        A tuple containing:
            - List[Document]: The prepared LangChain documents.
            - pd.DataFrame: The input DataFrame augmented with 'llm_problem_statement' 
                            and 'llm_solution_summary' columns.
    """
    langchain_documents = [] 
    all_problem_statements = {} 
    all_solution_summaries = {} 
    total_problem_llm_errors = 0
    total_solution_llm_errors = 0
    num_tickets = len(ticket_data_df)
    logger.info(f"Preparing documents for {num_tickets} tickets, using LLM batch size {LLM_BATCH_SIZE}.")

    # Initialize new columns in the DataFrame for LLM outputs
    ticket_data_df['llm_problem_statement'] = pd.Series(dtype='str')
    ticket_data_df['llm_solution_summary'] = pd.Series(dtype='str')

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
            # Add to DataFrame
            ticket_data_df.loc[original_ticket_index, 'llm_problem_statement'] = problem_statement_text

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
            # Add to DataFrame
            ticket_data_df.loc[original_ticket_index, 'llm_solution_summary'] = solution_summary_text

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
        'brand', 'product', 'geo_region', 'environment', 'root_cause', 'sprint',
        'url'  # ADDED URL to metadata fields
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
        
        logger.debug(f"Ticket {original_ticket_id} metadata includes URL: {metadata.get('url')}")

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

    # The DataFrame ticket_data_df is now augmented with llm_problem_statement and llm_solution_summary

    return langchain_documents, ticket_data_df

def post_llm_processing(df_augmented: pd.DataFrame, docs_to_embed: List[Document]) -> (pd.DataFrame, List[Document]):
    """
    Filters the augmented DataFrame and the list of Document objects based on LLM output quality.

    Rows are removed if:
    - 'llm_solution_summary' contains "No clear solution" (case-insensitive).
    - 'llm_problem_statement' contains "failed to generate/parse" (case-insensitive) 
      or starts with "Error:" (case-insensitive).

    Args:
        df_augmented (pd.DataFrame): DataFrame with 'llm_problem_statement' and 'llm_solution_summary'.
        docs_to_embed (List[Document]): List of LangChain Document objects.

    Returns:
        A tuple containing:
            - pd.DataFrame: The filtered DataFrame.
            - List[Document]: The filtered list of Document objects.
    """
    if df_augmented.empty:
        logger.warning("post_llm_processing received an empty DataFrame. Returning as is.")
        return df_augmented, docs_to_embed

    initial_df_rows = len(df_augmented)
    initial_docs_count = len(docs_to_embed)
    logger.info(f"Starting post-LLM processing. Initial DataFrame rows: {initial_df_rows}, Initial documents: {initial_docs_count}")

    # Ensure columns exist to prevent KeyErrors on empty or malformed DataFrames
    if 'llm_solution_summary' not in df_augmented.columns:
        logger.error("'llm_solution_summary' column missing in DataFrame for post_llm_processing.")
        return df_augmented, docs_to_embed # Or handle more gracefully
    if 'llm_problem_statement' not in df_augmented.columns:
        logger.error("'llm_problem_statement' column missing in DataFrame for post_llm_processing.")
        return df_augmented, docs_to_embed

    # Conditions for removal
    # Convert to string type and fill NA to avoid errors with .str accessor on non-string types
    condition_no_clear_solution = df_augmented['llm_solution_summary'].astype(str).str.contains(
        "No clear solution", 
        case=False, 
        na=False
    )
    condition_failed_problem_parse = df_augmented['llm_problem_statement'].astype(str).str.contains(
        "failed to generate/parse", 
        case=False, 
        na=False
    )
    condition_error_problem = df_augmented['llm_problem_statement'].astype(str).str.startswith(
        "Error:",
        na=False # Treats NaN as not starting with "Error:"
    )

    # More comprehensive conditions for llm_solution_summary errors
    condition_solution_contains_failed_parse = df_augmented['llm_solution_summary'].astype(str).str.contains(
        "Failed to generate/parse solution", # General check, covers with/without "after 10"
        case=False, 
        na=False
    )
    condition_solution_starts_with_error = df_augmented['llm_solution_summary'].astype(str).str.startswith(
        "Error:",
        na=False # Treats NaN as not starting with "Error:"
    )
    
    # Combine removal conditions (rows to remove = True)
    rows_to_remove_mask = (
        condition_no_clear_solution |          # For solution summary
        condition_failed_problem_parse |       # For problem statement
        condition_error_problem |              # For problem statement
        condition_solution_contains_failed_parse | # For solution summary (replaces old specific one)
        condition_solution_starts_with_error     # For solution summary
    )

    # DataFrame to keep (rows_to_remove_mask is False)
    df_processed = df_augmented[~rows_to_remove_mask].copy()
    num_rows_removed_df = initial_df_rows - len(df_processed)
    logger.info(f"DataFrame filtering: Removed {num_rows_removed_df} rows.")

    # Get ticket_ids of the rows that were kept in the DataFrame
    kept_ticket_ids = set(df_processed['ticket_id'].unique())
    logger.info(f"{len(kept_ticket_ids)} unique ticket_ids kept after DataFrame filtering.")

    # Filter documents_to_embed
    docs_processed = [doc for doc in docs_to_embed if doc.metadata.get('ticketId') in kept_ticket_ids]
    num_docs_removed = initial_docs_count - len(docs_processed)
    logger.info(f"Documents filtering: Removed {num_docs_removed} documents.")

    if len(df_processed) != len(docs_processed):
        logger.warning(
            f"Mismatch after filtering: Processed DataFrame rows: {len(df_processed)}, "
            f"Processed Documents: {len(docs_processed)}. "
            f"This may indicate issues with ticket_id mapping or prior document creation logic."
        )

    logger.info(f"Finished post-LLM processing. Final DataFrame rows: {len(df_processed)}, Final documents: {len(docs_processed)}.")
    return df_processed, docs_processed

def run_ingestion_pipeline():
    # INITIAL PARAMETER LOGGING
    MAIN_CSV_CHUNK_SIZE = 200
    max_rows_to_process_this_run=2000
    start_row_index_in_csv=2001
    logger.info(f"RUN_INGESTION_PIPELINE CALLED WITH: start_row_index_in_csv={start_row_index_in_csv} (type: {type(start_row_index_in_csv)}), max_rows_to_process_this_run={max_rows_to_process_this_run} (type: {type(max_rows_to_process_this_run)})")
    """
    Main function to orchestrate the ingestion pipeline.
    Processes a segment of the Jira tickets CSV file.

    Args:
        start_row_index_in_csv (int): 0-based index of the data row in the CSV 
                                      from which to start processing (default: 0).
        max_rows_to_process_this_run (int): Maximum number of rows to process in this run.
                                            -1 means process all rows from start_row_index_in_csv 
                                            to the end of the file (default: -1).
    """
    logger.info(
        f"Starting Jira to Pinecone ingestion pipeline. \
        Starting from CSV row index: {start_row_index_in_csv}, \
        Max rows to process this run: {'ALL' if max_rows_to_process_this_run == -1 else max_rows_to_process_this_run}"
    )
    
    total_rows_iterated_from_csv = 0 # Tracks all rows seen by the CSV iterator
    rows_processed_in_this_run = 0
      # Tracks rows processed in this specific pipeline invocation

    # 1. Initialize Cohere embeddings model and Pinecone index (once at the start)
    logger.info("Initializing Cohere embeddings model...")
    cohere_embeddings = get_cohere_embeddings() # From embedding_service
    if not cohere_embeddings:
        logger.error("Failed to initialize Cohere embeddings. Aborting pipeline.")
        return

    logger.info("Initializing Pinecone vector store...")
    pinecone_index = initialize_pinecone_vector_store_ingestion(embeddings=cohere_embeddings)
    if not pinecone_index:
        logger.error("Failed to initialize Pinecone index. Aborting pipeline.")
        return

    try:
        # 2. Read Jira tickets CSV in chunks
        for raw_chunk_df in pd.read_csv(CSV_FILENAME, chunksize=MAIN_CSV_CHUNK_SIZE, encoding='utf-8'):
            current_chunk_size = len(raw_chunk_df)
            # Determine the slice of this raw_chunk_df that we need to process for the current run
            
            # If this entire chunk is before our desired start_row_index_in_csv
            if total_rows_iterated_from_csv + current_chunk_size <= start_row_index_in_csv:
                total_rows_iterated_from_csv += current_chunk_size
                continue

            # Determine the starting point within this current raw_chunk_df
            offset_in_chunk_for_start_row = 0
            if total_rows_iterated_from_csv < start_row_index_in_csv:
                offset_in_chunk_for_start_row = start_row_index_in_csv - total_rows_iterated_from_csv
            
            # Determine how many rows we can take from this chunk for the current run
            rows_to_take_from_this_chunk = current_chunk_size - offset_in_chunk_for_start_row
            
            # DEBUG LOGGING FOR CHECK 1 (Early Exit Logic)
            logger.info(f"DEBUG CHK1 PRE-LIMIT: rows_to_take_from_this_chunk_initial={rows_to_take_from_this_chunk}")
            logger.info(f"DEBUG CHK1 PRE-LIMIT: max_rows_this_run={max_rows_to_process_this_run} (type {type(max_rows_to_process_this_run)}), rows_processed_so_far={rows_processed_in_this_run} (type {type(rows_processed_in_this_run)})")

            if max_rows_to_process_this_run != -1:
                remaining_rows_to_process_for_run = max_rows_to_process_this_run - rows_processed_in_this_run
                logger.info(f"DEBUG CHK1 PRE-LIMIT: remaining_rows_to_process_for_run={remaining_rows_to_process_for_run}")
                if remaining_rows_to_process_for_run <= 0:
                    logger.info(f"DEBUG CHK1 PRE-LIMIT: Breaking because remaining_rows_to_process_for_run ({remaining_rows_to_process_for_run}) <= 0.")
                    break # Already processed enough for this run
                rows_to_take_from_this_chunk = min(rows_to_take_from_this_chunk, remaining_rows_to_process_for_run)
                logger.info(f"DEBUG CHK1 PRE-LIMIT: rows_to_take_from_this_chunk_after_limit_check={rows_to_take_from_this_chunk}")

            if rows_to_take_from_this_chunk <= 0:
                total_rows_iterated_from_csv += current_chunk_size # Still need to account for iterating past it
                # This condition might be hit if max_rows_to_process_this_run was small and already satisfied by previous chunks
                # or if the start_row_index_in_csv is beyond this chunk after accounting for offset.
                if max_rows_to_process_this_run != -1 and rows_processed_in_this_run >= max_rows_to_process_this_run:
                    break
                continue

            # Slice the chunk to get the actual data for processing in this iteration
            jira_tickets_df_chunk_for_processing = raw_chunk_df.iloc[offset_in_chunk_for_start_row : offset_in_chunk_for_start_row + rows_to_take_from_this_chunk]
            total_rows_iterated_from_csv += current_chunk_size # Always advance by full raw chunk iterated

            if jira_tickets_df_chunk_for_processing.empty:
                continue

            current_run_batch_log_idx = (rows_processed_in_this_run // MAIN_CSV_CHUNK_SIZE) + 1 # For logging batch number within this run
            logger.info(f"--- Processing Run Batch {current_run_batch_log_idx} (derived from CSV rows approx. {start_row_index_in_csv + rows_processed_in_this_run} to {start_row_index_in_csv + rows_processed_in_this_run + len(jira_tickets_df_chunk_for_processing) -1}) --- Shape: {jira_tickets_df_chunk_for_processing.shape}")

            # 3a. Clean data for the current processing chunk
            logger.info(f"Starting data cleaning process for run batch {current_run_batch_log_idx}...")
            try:
                # Use .copy() on the slice to avoid SettingWithCopyWarning later
                jira_tickets_df_cleaned_chunk = clean_all_columns(jira_tickets_df_chunk_for_processing.copy()) 
                logger.info(f"Data cleaning finished for run batch {current_run_batch_log_idx}. DataFrame shape: {jira_tickets_df_cleaned_chunk.shape}")
                non_empty_comments = len(jira_tickets_df_cleaned_chunk[jira_tickets_df_cleaned_chunk['cleaned_comments'].str.len() > 0])
                logger.info(f"Run batch {current_run_batch_log_idx}: Number of tickets with non-empty cleaned_comments: {non_empty_comments}")
            except Exception as e:
                logger.error(f"Error during data cleaning for run batch {current_run_batch_log_idx}: {e}", exc_info=True)
                logger.warning(f"Skipping run batch {current_run_batch_log_idx} due to data cleaning error.")
                rows_processed_in_this_run += len(jira_tickets_df_chunk_for_processing) # Count as attempted
                
                # DEBUG LOGGING FOR CHECK 2 (Data Clean Fail Path)
                logger.info(f"DEBUG CHK2 (DataCleanFail): len_chunk_attempted={len(jira_tickets_df_chunk_for_processing)}")
                logger.info(f"DEBUG CHK2 (DataCleanFail): max_rows_this_run={max_rows_to_process_this_run} (type {type(max_rows_to_process_this_run)}), UPDATED rows_processed_so_far={rows_processed_in_this_run} (type {type(rows_processed_in_this_run)})")
                comparison_result_chk2_clean_fail = (max_rows_to_process_this_run != -1 and rows_processed_in_this_run >= max_rows_to_process_this_run)
                logger.info(f"DEBUG CHK2 (DataCleanFail): Comparison (rows_processed_so_far >= max_rows_this_run) is {comparison_result_chk2_clean_fail}")
                if comparison_result_chk2_clean_fail:
                    logger.info(f"DEBUG CHK2 (DataCleanFail): Reached max_rows_to_process_this_run ({max_rows_to_process_this_run}). Stopping.")
                    break
                continue 
            
            # 3b. Prepare Document objects (includes LLM calls) for the current chunk
            documents_to_embed_initial_chunk, jira_tickets_df_augmented_chunk = prepare_documents_for_embedding(jira_tickets_df_cleaned_chunk)
            
            # 3c. Save pre-filter augmented chunk data to CSV
            if jira_tickets_df_augmented_chunk is not None and not jira_tickets_df_augmented_chunk.empty:
                augmented_csv_filename = "jira_tickets_with_llm_outputs.csv" # Static filename
                
                file_exists_augmented = os.path.exists(augmented_csv_filename)
                write_mode_augmented = 'a' if file_exists_augmented else 'w'
                include_header_augmented = not file_exists_augmented
                
                try:
                    jira_tickets_df_augmented_chunk.to_csv(
                        augmented_csv_filename, 
                        index=False, 
                        encoding='utf-8', 
                        quoting=csv.QUOTE_ALL,
                        mode=write_mode_augmented,
                        header=include_header_augmented
                    )
                    logger.info(f"Run batch {current_run_batch_log_idx}: Successfully saved/appended augmented Jira tickets ({len(jira_tickets_df_augmented_chunk)} rows) to '{augmented_csv_filename}'.")
                except Exception as e:
                    logger.error(f"Run batch {current_run_batch_log_idx}: Failed to save/append augmented data to CSV '{augmented_csv_filename}': {e}", exc_info=True)
            else:
                logger.warning(f"Run batch {current_run_batch_log_idx}: Augmented DataFrame is empty or None. Skipping pre-filter CSV export.")

            if not documents_to_embed_initial_chunk:
                logger.warning(f"Run batch {current_run_batch_log_idx}: No documents prepared for embedding after initial LLM processing. Skipping further processing for this batch.")
                rows_processed_in_this_run += len(jira_tickets_df_chunk_for_processing)

                # DEBUG LOGGING FOR CHECK 2 (No Docs Initial Path)
                logger.info(f"DEBUG CHK2 (NoDocsInitial): len_chunk_processed={len(jira_tickets_df_chunk_for_processing)}")
                logger.info(f"DEBUG CHK2 (NoDocsInitial): max_rows_this_run={max_rows_to_process_this_run} (type {type(max_rows_to_process_this_run)}), UPDATED rows_processed_so_far={rows_processed_in_this_run} (type {type(rows_processed_in_this_run)})")
                comparison_result_chk2_no_docs_init = (max_rows_to_process_this_run != -1 and rows_processed_in_this_run >= max_rows_to_process_this_run)
                logger.info(f"DEBUG CHK2 (NoDocsInitial): Comparison (rows_processed_so_far >= max_rows_this_run) is {comparison_result_chk2_no_docs_init}")
                if comparison_result_chk2_no_docs_init:
                    logger.info(f"DEBUG CHK2 (NoDocsInitial): Reached max_rows_to_process_this_run ({max_rows_to_process_this_run}). Stopping.")
                    break
                continue 
            logger.info(f"Run batch {current_run_batch_log_idx}: Initial documents prepared after LLM processing: {len(documents_to_embed_initial_chunk)}.")

            # 3d. Perform post-LLM processing (filtering) for the current chunk
            jira_tickets_df_post_processed_chunk, documents_to_embed_processed_chunk = post_llm_processing(
                jira_tickets_df_augmented_chunk, 
                documents_to_embed_initial_chunk
            )

            # 3e. Save post-filter augmented chunk data to CSV
            if jira_tickets_df_post_processed_chunk is not None and not jira_tickets_df_post_processed_chunk.empty:
                post_processed_csv_filename = "jira_tickets_df_augmented_post_process.csv" # Static filename

                file_exists_post_processed = os.path.exists(post_processed_csv_filename)
                write_mode_post_processed = 'a' if file_exists_post_processed else 'w'
                include_header_post_processed = not file_exists_post_processed
                
                try:
                    jira_tickets_df_post_processed_chunk.to_csv(
                        post_processed_csv_filename, 
                        index=False, 
                        encoding='utf-8', 
                        quoting=csv.QUOTE_ALL,
                        mode=write_mode_post_processed,
                        header=include_header_post_processed
                    )
                    logger.info(f"Run batch {current_run_batch_log_idx}: Successfully saved/appended post-processed augmented tickets ({len(jira_tickets_df_post_processed_chunk)} rows) to '{post_processed_csv_filename}'.")
                except Exception as e:
                    logger.error(f"Run batch {current_run_batch_log_idx}: Failed to save/append post-processed data to CSV '{post_processed_csv_filename}': {e}", exc_info=True)
            else:
                logger.warning(f"Run batch {current_run_batch_log_idx}: Post-processed DataFrame is empty or None. Skipping post-filter CSV export.")

            if not documents_to_embed_processed_chunk:
                logger.warning(f"Run batch {current_run_batch_log_idx}: No documents remaining after post-LLM processing. Skipping embedding and upsert for this batch.")
                rows_processed_in_this_run += len(jira_tickets_df_chunk_for_processing)

                # DEBUG LOGGING FOR CHECK 2 (No Docs PostProc Path)
                logger.info(f"DEBUG CHK2 (NoDocsPostProc): len_chunk_processed={len(jira_tickets_df_chunk_for_processing)}")
                logger.info(f"DEBUG CHK2 (NoDocsPostProc): max_rows_this_run={max_rows_to_process_this_run} (type {type(max_rows_to_process_this_run)}), UPDATED rows_processed_so_far={rows_processed_in_this_run} (type {type(rows_processed_in_this_run)})")
                comparison_result_chk2_no_docs_post = (max_rows_to_process_this_run != -1 and rows_processed_in_this_run >= max_rows_to_process_this_run)
                logger.info(f"DEBUG CHK2 (NoDocsPostProc): Comparison (rows_processed_so_far >= max_rows_this_run) is {comparison_result_chk2_no_docs_post}")
                if comparison_result_chk2_no_docs_post:
                    logger.info(f"DEBUG CHK2 (NoDocsPostProc): Reached max_rows_to_process_this_run ({max_rows_to_process_this_run}). Stopping.")
                    break # Processed enough for this run
                continue 
            logger.info(f"Run batch {current_run_batch_log_idx}: Documents remaining after post-LLM processing: {len(documents_to_embed_processed_chunk)}.")

            # 3f. Get embeddings for the filtered documents in the chunk
            logger.info(f"Run batch {current_run_batch_log_idx}: Generating embeddings for {len(documents_to_embed_processed_chunk)} documents in batches of {EMBEDDING_BATCH_SIZE}...")
            texts_to_embed_chunk = [doc.page_content for doc in documents_to_embed_processed_chunk]
            
            embeddings_chunk = get_embeddings_in_batches(texts=texts_to_embed_chunk, batch_size=EMBEDDING_BATCH_SIZE)

            if not embeddings_chunk or len(embeddings_chunk) != len(documents_to_embed_processed_chunk):
                logger.error(f"Run batch {current_run_batch_log_idx}: Failed to generate embeddings or mismatch in count. Expected: {len(documents_to_embed_processed_chunk)}, Got: {len(embeddings_chunk) if embeddings_chunk else 0}. Skipping upsert for this batch.")
                rows_processed_in_this_run += len(jira_tickets_df_chunk_for_processing)

                # DEBUG LOGGING FOR CHECK 2 (Embedding Fail Path)
                logger.info(f"DEBUG CHK2 (EmbeddingFail): len_chunk_processed={len(jira_tickets_df_chunk_for_processing)}")
                logger.info(f"DEBUG CHK2 (EmbeddingFail): max_rows_this_run={max_rows_to_process_this_run} (type {type(max_rows_to_process_this_run)}), UPDATED rows_processed_so_far={rows_processed_in_this_run} (type {type(rows_processed_in_this_run)})")
                comparison_result_chk2_embed_fail = (max_rows_to_process_this_run != -1 and rows_processed_in_this_run >= max_rows_to_process_this_run)
                logger.info(f"DEBUG CHK2 (EmbeddingFail): Comparison (rows_processed_so_far >= max_rows_this_run) is {comparison_result_chk2_embed_fail}")
                if comparison_result_chk2_embed_fail:
                    logger.info(f"DEBUG CHK2 (EmbeddingFail): Reached max_rows_to_process_this_run ({max_rows_to_process_this_run}). Stopping.")
                    break
                continue 
            logger.info(f"Run batch {current_run_batch_log_idx}: Successfully generated {len(embeddings_chunk)} embeddings.")

            # 3g. Upsert documents and embeddings for the chunk to Pinecone
            logger.info(f"Run batch {current_run_batch_log_idx}: Upserting {len(documents_to_embed_processed_chunk)} documents to Pinecone in batches of {PINECONE_UPSERT_BATCH_SIZE}...")
            upsert_documents_to_pinecone(
                index=pinecone_index,
                documents=documents_to_embed_processed_chunk,
                embeddings=embeddings_chunk,
                batch_size=PINECONE_UPSERT_BATCH_SIZE
            )
            logger.info(f"Run batch {current_run_batch_log_idx}: Successfully upserted documents to Pinecone.")
            
            rows_processed_in_this_run += len(jira_tickets_df_chunk_for_processing)
            
            # DEBUG LOGGING FOR CHECK 2 (Main Success Path)
            logger.info(f"DEBUG CHK2 (Success): len_chunk_just_processed={len(jira_tickets_df_chunk_for_processing)}")
            logger.info(f"DEBUG CHK2 (Success): max_rows_this_run={max_rows_to_process_this_run} (type {type(max_rows_to_process_this_run)}), UPDATED rows_processed_so_far={rows_processed_in_this_run} (type {type(rows_processed_in_this_run)})")
            comparison_result_chk2_success = (max_rows_to_process_this_run != -1 and rows_processed_in_this_run >= max_rows_to_process_this_run)
            logger.info(f"DEBUG CHK2 (Success): Comparison (rows_processed_so_far >= max_rows_this_run) is {comparison_result_chk2_success}")

            if comparison_result_chk2_success:
                logger.info(f"Reached max_rows_to_process_this_run ({max_rows_to_process_this_run}). Stopping. Condition was: {rows_processed_in_this_run} >= {max_rows_to_process_this_run}")
                break # Break from the pd.read_csv loop

    except FileNotFoundError:
        logger.error(f"CRITICAL: Main CSV file '{CSV_FILENAME}' not found. Aborting pipeline.")
        return
    except Exception as e:
        logger.error(f"An unexpected error occurred during chunk processing loop: {e}", exc_info=True)
        logger.error("Pipeline may have partially completed. Please check logs and output files.")
        return

    if rows_processed_in_this_run == 0:
        logger.info("No batches were processed from the CSV file. This might be due to an empty file or an early error.")
    else:
        logger.info(f"Jira to Pinecone ingestion pipeline finished processing {rows_processed_in_this_run // MAIN_CSV_CHUNK_SIZE} batches.")

if __name__ == "__main__":
    # This allows the script to be run directly for testing or manual ingestion
    # Load .env variables if running standalone and they are not already loaded by a parent process
    from dotenv import load_dotenv
    load_dotenv() # Load environment variables from .env
    
    # Example 1: Process first 500 data rows (0-499)
    # run_ingestion_pipeline(start_row_index_in_csv=0, max_rows_to_process_this_run=500)
    
    # Example 2: Process next 500 data rows (500-999)
    # run_ingestion_pipeline(start_row_index_in_csv=500, max_rows_to_process_this_run=500)

    # Example 3: Process all from the beginning
    # run_ingestion_pipeline()
    
    # Default call for testing (e.g., process first 200, then next 300)
    run_ingestion_pipeline()
    # To append the next set, you would call for example:
    # run_ingestion_pipeline(start_row_index_in_csv=200, max_rows_to_process_this_run=300) 