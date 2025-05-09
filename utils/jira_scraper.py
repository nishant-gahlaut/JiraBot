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

def scrape_and_store_tickets(project_key: str, total_tickets_to_scrape: int, api_batch_size: int = 100, csv_path: str = CSV_FILENAME):
    """Scrapes a specified total number of tickets from a project in batches and stores cleaned data locally in a CSV file."""
    if not jira_client:
        logger.error("Jira client not initialized. Cannot scrape tickets.")
        return 0, 0

    if not project_key:
        logger.error("No project_key provided. Cannot scrape tickets.")
        return 0, 0
    
    if total_tickets_to_scrape <= 0:
        logger.warning("total_tickets_to_scrape is zero or negative. No tickets will be scraped.")
        return 0, 0

    jql = f'project = "{project_key}" ORDER BY updated DESC'
    logger.info(f"Starting Jira scrape for up to {total_tickets_to_scrape} tickets in project '{project_key}' using JQL: {jql}")
    logger.info(f"API batch size: {api_batch_size}. Output CSV: {csv_path}")

    start_at = 0
    total_fetched_this_run = 0
    total_available_in_jira = 0 # Will get this from the first API call
    processed_count = 0
    error_count = 0
    
    header_columns = [
        'ticket_id', 'summary', 'description', 'status', 'priority', 
        'reporter', 'assignee', 'created_at', 'updated_at', 'labels', 
        'components', 'owned_by_team', 'brand', 'product', 'geo_region', 
        'environment', 'root_cause', 'sprint', 'comments', 'url' # Ensure URL is in headers if clean_jira_data provides it
    ]

    try:
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow(header_columns)
            logger.info(f"Opened '{csv_path}' and wrote header row.")

            while total_fetched_this_run < total_tickets_to_scrape:
                # Determine how many to fetch in this batch
                remaining_to_scrape_overall = total_tickets_to_scrape - total_fetched_this_run
                current_batch_max_results = min(api_batch_size, remaining_to_scrape_overall)

                if current_batch_max_results <= 0: # Should not happen if loop condition is correct, but as safeguard
                    logger.info("Target number of tickets to scrape has been reached (or current_batch_max_results is 0). Ending fetch.")
                    break

                logger.info(f"Fetching issues batch: startAt={start_at}, maxResults={current_batch_max_results}")
                try:
                    search_results = jira_client.search_issues(
                        jql, 
                        startAt=start_at, 
                        maxResults=current_batch_max_results, 
                        fields='*all', 
                        expand='changelog' # Consider if changelog is always needed, it adds to response size
                    )
                except JIRAError as e:
                    logger.error(f"JIRA API Error fetching batch startAt {start_at}: {e.status_code} - {e.text}")
                    # Decide on retry/skip strategy. For now, simple skip of this batch attempt.
                    error_count += current_batch_max_results 
                    time.sleep(5) 
                    start_at += current_batch_max_results # Advance start_at to attempt next logical block if API error was for a range
                    if total_available_in_jira > 0 and start_at >= total_available_in_jira:
                        logger.warning(f"Stopping due to API error; attempted to fetch past total available tickets ({total_available_in_jira}).")
                        break 
                    if total_fetched_this_run + (start_at - total_fetched_this_run) >= total_tickets_to_scrape: # If next start_at would exceed scrape goal
                        logger.warning("Stopping due to API error; advancing start_at would exceed total_tickets_to_scrape.")
                        break
                    continue 
                except Exception as e:
                     logger.error(f"Unexpected error fetching batch startAt {start_at}: {e}", exc_info=True)
                     error_count += current_batch_max_results
                     time.sleep(5)
                     start_at += current_batch_max_results
                     if total_available_in_jira > 0 and start_at >= total_available_in_jira:
                         logger.warning("Stopping due to unexpected error; attempted to fetch past total available.")
                         break
                     if total_fetched_this_run + (start_at - total_fetched_this_run) >= total_tickets_to_scrape:
                         logger.warning("Stopping due to unexpected error; advancing start_at would exceed total_tickets_to_scrape.")
                         break
                     continue

                if start_at == 0 and search_results: # First successful batch
                    total_available_in_jira = search_results.total
                    logger.info(f"Total available tickets matching query in Jira: {total_available_in_jira}")
                    if total_tickets_to_scrape > total_available_in_jira:
                        logger.warning(f"Requested {total_tickets_to_scrape} tickets, but only {total_available_in_jira} are available in Jira. Will scrape all available.")
                        total_tickets_to_scrape = total_available_in_jira # Adjust goal to what's actually available

                if not search_results: # Corrected: ResultList itself is the list/iterable
                    logger.info(f"No more issues found from Jira after startAt={start_at} or current batch is empty. Ending fetch.")
                    break 
                    
                batch_issue_count = len(search_results) # Corrected: Get length directly from ResultList
                logger.info(f"Fetched batch of {batch_issue_count} issues. (Total fetched this run so far: {total_fetched_this_run + batch_issue_count}/{total_tickets_to_scrape}) | Jira Total: {total_available_in_jira}")

                for issue in search_results: # Corrected: Iterate directly over ResultList
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

                        row_data = [str(cleaned_data.get(col, '')) if not isinstance(cleaned_data.get(col), (list, dict)) else json.dumps(cleaned_data.get(col), default=str) for col in header_columns]
                        csv_writer.writerow(row_data)
                        processed_count += 1
                        
                    except Exception as proc_err:
                         logger.error(f"Error processing and writing issue {issue.key} to CSV: {proc_err}", exc_info=True)
                         error_count += 1
                
                total_fetched_this_run += batch_issue_count
                logger.info(f"Finished processing batch. Processed this batch: {batch_issue_count}. Total processed this run: {processed_count}. Errors this run: {error_count}")

                if total_fetched_this_run >= total_available_in_jira: # Check against actual Jira total
                    logger.info(f"All available tickets from Jira ({total_available_in_jira}) have been fetched and processed.")
                    break
                
                start_at += batch_issue_count # Correctly advance start_at by the number of issues actually processed in this batch

        logger.info(f"Jira scraping finished. Total tickets processed and written to CSV: {processed_count}. Total fetched from Jira in this run: {total_fetched_this_run}. Errors encountered: {error_count}.")

    except IOError as e:
        logger.error(f"Could not open or write to CSV file '{csv_path}': {e}")
        return processed_count, total_available_in_jira
    except Exception as e:
        logger.error(f"Unexpected error during CSV scraping process: {e}", exc_info=True)
        return processed_count, total_available_in_jira
        
    return processed_count, total_available_in_jira 