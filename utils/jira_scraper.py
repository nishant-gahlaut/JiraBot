# utils/jira_scraper.py
import logging
import sqlite3 # REMOVE
import csv # ADD
import os
import json
import time # For potential delays between batches
from services.jira_service import jira_client # Import the initialized client
# Import the cleaner function
from utils.data_cleaner import clean_jira_data
from jira.exceptions import JIRAError

logger = logging.getLogger(__name__)
# DB_NAME = "local_jira_cache.db" # REMOVE DB Name
CSV_FILENAME = "jira_tickets_cache.csv"
# Define batch size for fetching issues
BATCH_SIZE = 100

# REMOVE init_local_db function entirely
# def init_local_db(db_path=DB_NAME):
#     ...

def scrape_and_store_tickets(project_key, csv_path=CSV_FILENAME):
    """Scrapes tickets from a project in batches and stores cleaned data locally in a CSV file."""
    if not jira_client:
        logger.error("Jira client not initialized. Cannot scrape tickets.")
        return 0, 0 # Scraped 0, Total 0

    if not project_key:
        logger.error("No PROJECT_KEY_TO_SCRAPE provided. Cannot scrape tickets.")
        return 0, 0

    # JQL to fetch issues in the project, ordered by updated date
    jql = f'project = "{project_key}" ORDER BY updated DESC'
    # Update log to mention CSV and batch limit
    logger.info(f"Starting Jira scrape for the first batch (up to {BATCH_SIZE}) of tickets in project '{project_key}' using JQL: {jql}")
    logger.info(f"Output will be stored in: {csv_path}")

    start_at = 0
    total_fetched_count = 0
    total_available = 0 # Will get this from the first API call
    processed_count = 0
    error_count = 0
    
    # Define CSV header columns based on clean_jira_data output
    header_columns = [
        'ticket_id', 'summary', 'description', 'status', 'priority', 
        'reporter', 'assignee', 'created_at', 'updated_at', 'labels', 
        'components', 'owned_by_team', 'brand', 'product', 'geo_region', 
        'environment', 'root_cause', 'sprint', 'comments'
    ]

    try:
        # Open CSV file for writing
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            csv_writer = csv.writer(csvfile)
            # Write header row
            csv_writer.writerow(header_columns)
            logger.info(f"Opened '{csv_path}' and wrote header row.")

            # Remove SQLite connection
            # conn = sqlite3.connect(db_path)
            # cursor = conn.cursor()

            while True:
                logger.info(f"Fetching issues batch: startAt={start_at}, maxResults={BATCH_SIZE}")
                try:
                    search_results = jira_client.search_issues(
                        jql, 
                        startAt=start_at, 
                        maxResults=BATCH_SIZE, 
                        fields='*all', 
                        expand='changelog'
                    )
                except JIRAError as e:
                    logger.error(f"JIRA API Error fetching batch startAt {start_at}: {e.status_code} - {e.text}")
                    error_count += BATCH_SIZE 
                    time.sleep(5) 
                    start_at += BATCH_SIZE
                    if total_available > 0 and start_at >= total_available:
                        logger.warning("Stopping due to API error after trying to fetch past total.") 
                        break 
                    continue 
                except Exception as e:
                     logger.error(f"Unexpected error fetching batch startAt {start_at}: {e}", exc_info=True)
                     error_count += BATCH_SIZE
                     time.sleep(5)
                     start_at += BATCH_SIZE
                     if total_available > 0 and start_at >= total_available:
                         logger.warning("Stopping due to unexpected error after trying to fetch past total.")
                         break
                     continue

                if start_at == 0: # First batch
                    total_available = search_results.total
                    logger.info(f"Total available tickets matching query in project: {total_available}")

                if not search_results:
                    logger.info(f"No more issues found after startAt={start_at}. Ending fetch.")
                    break # Exit loop if no issues are returned
                    
                batch_issue_count = len(search_results)
                total_fetched_count += batch_issue_count
                logger.info(f"Fetched batch of {batch_issue_count} issues (Total fetched so far: {total_fetched_count}/{total_available})")

                # Process issues in the current batch
                for issue in search_results:
                    try:
                        if not hasattr(issue, 'raw') or not issue.raw:
                            logger.warning(f"Issue {issue.key} is missing .raw attribute. Skipping.")
                            error_count += 1
                            continue
                            
                        cleaned_data = clean_jira_data(issue.raw, issue.key)
                        
                        if not cleaned_data:
                            logger.warning(f"Cleaning failed for issue {issue.key}. Skipping.")
                            error_count += 1
                            continue

                        # Prepare row data for CSV
                        row_data = []
                        for col in header_columns:
                            value = cleaned_data.get(col)
                            if isinstance(value, list) or isinstance(value, dict):
                               try:
                                   # Convert lists/dicts to JSON strings for CSV cell
                                   row_data.append(json.dumps(value, default=str))
                               except TypeError as json_err:
                                   logger.error(f"JSON serialization error for key '{col}' in ticket {issue.key}: {json_err}. Storing as string.")
                                   row_data.append(str(value)) # Fallback
                            elif value is None:
                                row_data.append('') # Use empty string for None
                            else:
                                row_data.append(str(value)) # Convert other types to string

                        # Write row to CSV
                        csv_writer.writerow(row_data)
                        processed_count += 1
                        
                    except Exception as proc_err:
                         logger.error(f"Error processing and writing issue {issue.key} to CSV: {proc_err}", exc_info=True)
                         error_count += 1

                # Log progress after processing each batch (no commit needed for CSV)
                logger.info(f"Finished processing batch ending at {start_at + batch_issue_count - 1}. Processed: {processed_count}, Errors: {error_count}")

                # Check if we have fetched all issues (or if loop should break)
                if total_fetched_count >= total_available:
                    logger.info("Fetched count meets or exceeds total available. Ending fetch.")
                    break
                
                # Move to the next batch
                start_at += batch_issue_count
                
                # --- BREAK AFTER FIRST BATCH (Keep for now)--- 
                logger.info(f"Limiting scrape to the first batch ({BATCH_SIZE} tickets). Stopping loop.")
                break 
                # --- END BREAK --- 

        # File is automatically closed by `with open(...)`
        # conn.close() # REMOVE
        logger.info(f"Finished scraping initial batch. CSV file '{csv_path}' created/updated. Total Processed: {processed_count}, Total Fetched in batch: {total_fetched_count}, Total Available in Project: {total_available}, Errors: {error_count}")

    except IOError as e:
        logger.error(f"Could not open or write to CSV file '{csv_path}': {e}")
        return processed_count, total_available
    except Exception as e:
        logger.error(f"Unexpected error during CSV scraping process: {e}", exc_info=True)
        return processed_count, total_available
        
    return processed_count, total_available 