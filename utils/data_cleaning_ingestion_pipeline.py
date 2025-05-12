"""
data_cleaning_ingestion_pipeline.py

This module provides robust text and data cleaning utilities for Jira ticket ingestion.
It is designed to be used in the ingestion pipeline after loading the raw CSV into a DataFrame.
The main entry point is `clean_all_columns(df)`, which returns a DataFrame with cleaned columns.
"""

import re
import json
import pandas as pd
from pandarallel import pandarallel

# --- solution keywords for filtering comments ---
SOLUTION_KEYWORDS = [
    "fixed by", "fix available", "workaround", "resolved by", "solution", "patch",
    "hotfix", "temporary fix", "permanent fix", "quick fix", "manual fix",
    "mitigated by", "apply this", "can be solved by", "try this", "steps to fix",
    "proposed solution", "proposed fix", "suggestion", "recommended",
    "use this approach", "alternative", "change the setting", "adjust config",
    "configuration change", "updated config", "rollback", "roll back",
    "reverted", "downgrade", "upgrade", "update", "restart", "reboot",
    "reinstall", "clean install", "reset", "patch applied", "deployed fix",
    "resolved with", "resolved after", "fix implemented", "manually edited",
    "follow these steps", "here's how", "you can fix this by", "script to fix",
    "just do this", "solved after", "solved by", "mitigation", "workaround found"
]

solution_keyword_pattern = r'\b(?:' + '|'.join(re.escape(k) for k in SOLUTION_KEYWORDS) + r')\b'

# --- Cleaning Functions ---
def strip_jira_markup(text):
    """Remove common Jira wiki markup and formatting from text."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r'\{panel:[^}]*}(.*?)\{panel}', r'\1', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\{code:[^}]*}(.*?)\{code}', r'\1', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\{code}(.*?)\{code}', r'\1', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\{color:[^}]*}(.*?)\{color}', r'\1', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'^\s*posted on:.*?(\n|$)', '', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^\s*original author:.*?(\n|$)', '', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'h[1-6]\.\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    text = re.sub(r'\+(.*?)\+', r'\1', text)
    text = re.sub(r'-(.*?)-', r'\1', text)
    text = re.sub(r'\?\?(.*?)\?\?', r'\1', text)
    text = re.sub(r'\{\{(.*?)\}\}', r'\1', text)
    text = re.sub(r'bq\.\s+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[([^|\]]+)\|[^\]]+\]', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]', r'\1', text)
    text = re.sub(r'!([^!]+)!', '', text)
    text = re.sub(r'^\s*[\*#-]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\{noformat\}(.*?)\{noformat\}', r'\1', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\{quote}(.*?)\{quote\}', r'\1', text, flags=re.DOTALL | re.IGNORECASE)
    return text

def normalize_whitespace(text):
    """Replace multiple spaces/tabs/newlines with a single space and trim."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def standardize_case(text):
    """Convert text to lowercase."""
    if not isinstance(text, str):
        return ""
    return text.lower()

def remove_user_mentions(text):
    """Remove Jira and Slack user mentions (e.g., [~username], @username)."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r'\[~[^\]]+\]', '', text)
    text = re.sub(r'@\w+', '', text)
    return text

def remove_urls(text):
    """Remove URLs from text using a robust regex."""
    if not isinstance(text, str):
        return ""
    url_pattern = r"""\b(?:(?:https?|ftp)://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»"“‘’])"""
    text = re.sub(url_pattern, '', text, flags=re.IGNORECASE)
    return text

def manage_punctuation(text, keep_punctuation=".-_"):
    """Remove most punctuation, keeping only those specified."""
    if not isinstance(text, str):
        return ""
    processed_chars = []
    for char in text:
        if char.isalnum() or char in keep_punctuation or char.isspace():
            processed_chars.append(char)
        else:
            processed_chars.append(' ')
    text = "".join(processed_chars)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def process_code_and_stack_traces(text):
    """Replace code blocks and stack traces with generic tokens."""
    if not isinstance(text, str):
        return ""
    stack_trace_pattern = r'((?:[a-zA-Z0-9_]+\.)+[a-zA-Z0-9_]+Exception(?:[:\s].*)?\n(?:^\s*at .*(?:\n|$))+)'
    python_traceback_pattern = r'(Traceback \(most recent call last\):\n(?:(?:^\s*File ".*?", line \d+, in .*\n)|(?:^\s*.*\n))*?\w*Error:.*)'
    text = re.sub(stack_trace_pattern, ' <STACK_TRACE> ', text, flags=re.MULTILINE)
    text = re.sub(python_traceback_pattern, ' <STACK_TRACE> ', text, flags=re.MULTILINE)
    mysql_pattern = r'mysql>.*?;'
    text = re.sub(mysql_pattern, ' <CODE_SNIPPET> ', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def remove_id_data_blobs(text):
    """Remove lines that are mostly IDs or numbers (data blobs)."""
    if not isinstance(text, str):
        return ""
    data_token = r'(?:\b\d+(?:\.\d+)?\b|\b[a-zA-Z0-9_.-]{8,}\b|(?i)\bnull\b)'
    customer_id_list_pattern = r'^\s*(?:-\s*)?customerid(?:\s+' + data_token + '){3,}\s*$'
    text = re.sub(customer_id_list_pattern, ' <DATA_BLOB> ', text, flags=re.MULTILINE | re.IGNORECASE)
    generic_data_line_pattern = r'^\s*(?:' + data_token + r'\s*){4,}\s*$'
    text = re.sub(generic_data_line_pattern, ' <DATA_BLOB> ', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'(\s*<DATA_BLOB>\s*)+', ' <DATA_BLOB> ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def remove_or_replace_numbers(text):
    """Remove standalone numbers, preserving version-like patterns."""
    if not isinstance(text, str):
        return ""
    version_patterns = [
        r'\b\d+\.\d+\.\d+(?:\.\d+)?\b',
        r'\bv\d+\.\d+(?:\.\d+)?\b',
        r'\b[a-zA-Z_][a-zA-Z0-9_]*-\d+\.\d+\b'
    ]
    protected_versions = []
    placeholder_base = "||VERSION_PLACEHOLDER_{}||"
    for i, pattern in enumerate(version_patterns):
        matches = list(re.finditer(pattern, text))
        for match in reversed(matches):
            placeholder = placeholder_base.format(len(protected_versions))
            protected_versions.append(match.group(0))
            start, end = match.span()
            text = text[:start] + placeholder + text[end:]
    text = re.sub(r'\b\d+(?:\.\d+)?\b', ' ', text)
    for i, version_str in enumerate(reversed(protected_versions)):
        placeholder = placeholder_base.format(len(protected_versions) - 1 - i)
        text = text.replace(placeholder, version_str, 1)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def parse_filter_and_format_comments(comments_json_str):
    """Parse, sort, and filter comments for problem keywords, returning joined text only."""
    if pd.isna(comments_json_str) or not comments_json_str.strip():
        return ""
    try:
        comments_list = json.loads(comments_json_str)
        if not isinstance(comments_list, list) or not comments_list:
            return ""
        try:
            # Sort comments by timestamp, newest to oldest
            comments_list.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        except TypeError:
            # Handle cases where timestamp might be missing or not comparable
            pass
        filtered_comment_texts = []
        for comment_obj in comments_list:
            comment_text = comment_obj.get('cleaned_body', '')
            if comment_text:
                if re.search(solution_keyword_pattern, comment_text, flags=re.IGNORECASE):
                    filtered_comment_texts.append(comment_text)
        return "\n".join(filtered_comment_texts)
    except json.JSONDecodeError:
        return ""
    except Exception:
        return ""

# --- NEW HELPER FUNCTION ---
def parse_and_join_json_list_string(value):
    """Tries to parse a string as a JSON list and returns a comma-separated string.

    If the input is a string like '["Val1", "Val2"]', it returns "Val1, Val2".
    Handles potential JSON errors and non-list results gracefully.
    Returns an empty string if input is not a valid JSON list string or is NaN/None.
    """
    if pd.isna(value) or not isinstance(value, str) or not value.strip():
        return "" # Return empty string for NaN, None, non-strings, or empty strings
    try:
        # Attempt to parse the string as JSON
        parsed_list = json.loads(value)
        # Check if the parsed result is actually a list
        if isinstance(parsed_list, list):
            # Convert all items to string (just in case) and join with comma and space
            return ", ".join(map(str, parsed_list))
        else:
            # Parsed correctly but wasn't a list, return empty string
            return "" 
    except json.JSONDecodeError:
        # String was not valid JSON, return empty string
        return "" 
    except Exception:
        # Catch any other unexpected errors during processing
        return "" 
# --- END NEW HELPER FUNCTION ---

def clean_text_pipeline(text):
    """Apply all cleaning steps to a text field."""
    text = strip_jira_markup(text)
    text = normalize_whitespace(text)
    text = standardize_case(text)
    text = remove_user_mentions(text)
    text = remove_urls(text)
    text = manage_punctuation(text)
    text = process_code_and_stack_traces(text)
    text = remove_id_data_blobs(text)
    text = remove_or_replace_numbers(text)
    # Optionally:
    # text = remove_domain_specific_data(text)
    return text

def clean_all_columns(df):
    """Clean summary, description, and comments columns in the DataFrame using parallel processing."""
    # Initialize pandarallel (uses all available cores by default, shows progress bar)
    pandarallel.initialize(progress_bar=True)

    # Use .parallel_apply() instead of .apply()
    df['cleaned_summary'] = df['summary'].fillna('').astype(str).parallel_apply(clean_text_pipeline)
    df['cleaned_description'] = df['description'].fillna('').astype(str).parallel_apply(clean_text_pipeline)
    
    # Apply sequence for comments using parallel processing
    df['cleaned_comments'] = df['comments'].fillna('').astype(str).parallel_apply(parse_filter_and_format_comments)
    df['cleaned_comments'] = df['cleaned_comments'].parallel_apply(clean_text_pipeline) # Apply again

    # --- Process list-like string columns --- 
    list_like_columns = ['labels', 'brand', 'components','environment']
    for col in list_like_columns:
        if col in df.columns:
            # Apply the new parsing function using parallel processing
            # The helper function handles NaN/None by returning ""
            df[col] = df[col].parallel_apply(parse_and_join_json_list_string)
        else:
            # If the column doesn't exist in the DataFrame, create it and fill with empty strings
            # This ensures the columns are present for later metadata extraction in the ingestion pipeline
            df[col] = ""
    
    return df 