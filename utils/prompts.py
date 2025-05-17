# utils/prompts.py

# Prompt to summarize the core issue based on Jira summary and description
ISSUE_SUMMARY_PROMPT = """
You are an expert technical assistant summarizing Jira tickets.
Based on the following Jira ticket details, provide a concise, one-sentence summary of the core problem or request reported. Focus only on the issue itself.

Ticket Summary: {ticket_summary}
Description: {ticket_description}

Concise Issue Summary (1 sentence):
"""

# Prompt to summarize the resolution status or next steps based on comments
RESOLUTION_SUMMARY_PROMPT = """
You are an expert technical assistant analyzing Jira ticket comment history.
Based *only* on the following comments (from oldest to newest), provide a concise summary (1-2 sentences) of the current resolution status or the immediate next steps discussed. If the resolution or next steps are unclear from the comments, state that clearly.

Comments:
{formatted_comments}

Resolution/Next Steps Summary (1-2 sentences):
""" 

# Prompt for reranking retrieved tickets based on a query
RERANK_DUPLICATE_TICKETS_PROMPT = """You are an assistant. Given the following user query and retrieved tickets,
rank the tickets by relevance and return the top {top_n} ones.

Query: {query}

Tickets:
{formatted_docs}

Respond with only the most relevant {top_n} ticket numbers as a list (e.g., 1,3,5).
If you think none are relevant or cannot determine, respond with an empty list or 'None'.
"""

# Prompt for summarizing similarities between a query and a list of tickets
SUMMARIZE_TICKET_SIMILARITIES_PROMPT = """You are a technical assistant. Given a user query and a list of JIRA tickets,
summarize how these tickets are related to the user query and to each other.
Focus on highlighting the key similarities.

User Query:
{query}

Tickets:
{ticket_texts}

Provide a detailed but concise summary.
"""

# New prompt for summarizing a Slack conversation thread
SUMMARIZE_SLACK_THREAD_PROMPT = """
Analyze the following Slack thread conversation. Your goal is to extract a concise, factual summary of the **core technical problem or question** being discussed. This summary will be used for similarity searches against a knowledge base of existing issues.

**Instructions for the summary:**
- Focus exclusively on the underlying technical issue, bug, or request.
- OMIT all user names, mentions, or any phrases attributing statements to specific people (e.g., "User A said...", "X is asking about...").
- EXCLUDE greetings, salutations, thank yous, and other conversational filler.
- DO NOT include any proposed solutions, workarounds, or next steps from the thread. Only summarize the problem itself.
- The summary should be phrased as a neutral statement of the problem.


Conversation:
---
{thread_content}
---

Concise Problem-Focused Summary:"""

# Prompt for generating a concise Jira ticket title from user description
GENERATE_TICKET_TITLE_PROMPT = """
Based on the following Jira ticket description, generate a concise and informative Jira Ticket Title (max 15 words).

Description:
---
{user_description}
---

Jira Ticket Title:"""

# Prompt for generating a refined Jira ticket description
GENERATE_TICKET_DESCRIPTION_PROMPT = """
Refine the following user-provided description into a well-structured Jira ticket description. Ensure clarity, include relevant details if mentioned, and format it appropriately for a Jira ticket. If the input is very short, expand slightly to make it a useful description.

User Description:
---
{user_description}
---

Refined Jira Ticket Description:"""

# Prompt for generating Title and Description in one go (JSON output)
GENERATE_TICKET_TITLE_AND_DESCRIPTION_PROMPT = """
Please act as a helpful Jira assistant. Analyze the User Description and generate the following components in a VALID JSON format:
1.  "suggested_title": A clear and concise Jira ticket title based on the problem.
2.  "refined_description": A well-structured Jira ticket description, including key details from the conversation. If the conversation is very short and is already a good description, you can use that.
Output *only* a valid JSON object with the keys "suggested_title" and "refined_description".

User Description:
---
{user_description}
---

JSON Output:"""

# Prompt for generating Summary, Title, and Description from a thread (JSON output)
GENERATE_TICKET_COMPONENTS_FROM_THREAD_PROMPT = """
Given the following Slack thread conversation:

{slack_thread_conversation}

Please act as a helpful Jira assistant. Analyze the conversation and generate the following components in a VALID JSON format:
1.  "thread_summary": A concise summary of the entire thread, capturing the main problem and context.
2.  "suggested_title": A clear and concise Jira ticket title based on the problem.
3.  "refined_description": A well-structured Jira ticket description, including key details from the conversation. If the conversation is very short and is already a good description, you can use that.

Your response MUST be only the JSON object, like this:
{{
  "thread_summary": "summary of the thread...",
  "suggested_title": "suggested ticket title...",
  "refined_description": "refined ticket description..."
}}
"""

# New prompt for generating ticket components from a user-provided description
GENERATE_TICKET_COMPONENTS_FROM_DESCRIPTION_PROMPT = """\
A user has provided the following description for a new Jira ticket:

---
{user_description}
---

Please act as a helpful Jira assistant. Analyze this description and generate the following components.
Your response MUST be only a VALID JSON object with exactly these three keys:
1.  `issue_summary`: A concise summary of the core issue described. This summary will be used for finding similar existing tickets.
2.  `suggested_title`: A clear and concise Jira ticket title based on the user's description.
3.  `refined_description`: A well-structured Jira ticket description. If the user's description is already good, you can use it directly or slightly enhance its formatting.

Example of the required JSON output format:
```json
{{
  "issue_summary": "concise summary of the core issue...",
  "suggested_title": "suggested ticket title based on description...",
  "refined_description": "refined ticket description based on user input..."
}}
```

VALID JSON Output:
"""

# Prompt for processing a mention, understanding intent, and generating components (JSON output)
PROCESS_MENTION_AND_GENERATE_ALL_COMPONENTS_PROMPT = """\
Analyze the user's direct message to the bot and the recent conversation history provided below.
Your primary goal is to understand the user's needs and prepare information for potential Jira ticket creation or other actions.

1.  **Determine Intent**: Identify the user's primary intent (e.g., 'CREATE_TICKET', 'FIND_SIMILAR_TICKETS', 'CLARIFICATION', 'GENERAL_QUESTION', 'UNRELATED').

2.  **Generate Contextual Summary (`contextual_summary`)**: 
    Create a very brief, on-point summary (1-2 sentences) of *the core problem or topic reported/discussed by the user*. 
    This summary MUST focus solely on the essence of what the user is reporting or discussing. 
    Do NOT include any mention of the user's request for action (e.g., do not say 'user wants to create a ticket'). 
    Do NOT include any specific user names.

3.  **Generate Ticket Components (if applicable)**:
    *   If the intent strongly suggests creating a ticket or involves describing a problem, then generate:
        a.  `suggested_title`: A relevant and concise Jira ticket title. Do NOT include user names.
        b.  `refined_description`: A Jira ticket description that *details the problem or the user's request as comprehensively as possible based on the provided input (direct message and history)*. This description MUST focus exclusively on explaining the issue. Do NOT include suggested solutions, questions back to the user, any conversational fluff, or specific user names. If the user provided specific details about the problem, ensure those details are captured here. It should be a clear, detailed problem statement suitable for a Jira ticket.
    *   If the intent is NOT related to ticket creation or problem reporting (e.g., 'CLARIFICATION', 'GENERAL_QUESTION' where a direct answer is expected), set `suggested_title` and `refined_description` to null or an empty string.

4.  **Generate Direct Answer (`direct_answer` if applicable)**:
    *   If the intent is 'GENERAL_QUESTION' or 'QUESTION_ANSWERING' and a direct, factual answer can be derived from the conversation, provide it in `direct_answer`.
    *   Otherwise, set `direct_answer` to null or an empty string.

Output *only* a valid JSON object containing these exact keys:
-   `intent`: The determined user intent string (e.g., "CREATE_TICKET", "FIND_SIMILAR_TICKETS", "CLARIFICATION", "GENERAL_QUESTION").
-   `contextual_summary`: The very brief, problem-focused summary (NO user names, NO request for action).
-   `suggested_title`: The Jira ticket title (string, or null/empty if not applicable; NO user names).
-   `refined_description`: The detailed, problem-focused Jira ticket description (string, or null/empty if not applicable; NO user names).
-   `direct_answer`: A direct answer to a user's question (string, or null/empty if not applicable).

User Direct Message to Bot:
---
{user_direct_message_to_bot}
---

Recent Conversation History (if any, may be empty):
---
{formatted_conversation_history}
---

VALID JSON Output (ensure all keys are present, even if value is null/empty for some based on intent):
"""

# Prompt for generating a concise problem statement for embedding
GENERATE_CONCISE_PROBLEM_STATEMENT_PROMPT = """
Analyze the following Jira ticket information. Focus *only* on the core problem being reported or the primary task requested.
Generate a concise summary of the problem/task in {max_lines_lower_bound} to {max_lines} lines. 
Prioritize information from the summary and description. Only use comments if the summary and description are insufficient to understand the core problem/task. 
Do not include greetings, author names, solutions, questions asking for more info, ticket IDs, specific user IDs/data blobs, or status updates. 
Output only the concise problem/task description.

Ticket Information:
---
Ticket Summary:
{summary}

Ticket Description:
{description}

Relevant Comments (Use only if summary/description are unclear):
{comments}
---

Concise Problem/Task Statement ({max_lines_lower_bound}-{max_lines} lines):"""

# Prompt for generating concise problem statements for a BATCH of tickets
GENERATE_CONCISE_PROBLEM_STATEMENTS_BATCH_PROMPT = """
You are an AI assistant tasked with summarizing the core problem for a batch of Jira tickets, using ONLY the summary and description provided.
Input is a JSON list of ticket objects, each containing 'id', 'summary', and 'description'.
Analyze each ticket object in the input list ({batch_size} tickets total).
For *each* ticket, generate a concise summary (problem statement) of the core problem/task in {max_lines_lower_bound} to {max_lines} lines, following these rules:
- Base the summary *strictly* on the provided summary and description.
- Focus primarily on the core problem being reported or the primary task requested, but include essential context from the summary/description if necessary to understand the issue clearly.
- Do NOT use any information outside of the provided summary and description for each ticket.
- Do NOT include greetings, author names, solutions, questions asking for more info, ticket IDs, user IDs/data blobs, or status updates in the output statements.

Input JSON list of tickets:
```json
{batch_input_json}
```

Output *only* a valid JSON list of strings. The list should contain exactly {batch_size} strings.
Each string in the output list must be the concise problem statement (based on summary/description) for the corresponding ticket in the input list, maintaining the original order.
Example output format for a batch of 2:
["Concise problem statement for first ticket based on its summary/desc.", "Concise problem statement for second ticket based on its summary/desc."]

JSON Output list of concise problem statements:"""

# Prompt for generating concise solution summaries from comments for a BATCH of tickets
GENERATE_CONCISE_SOLUTIONS_BATCH_PROMPT = """
You are an AI assistant tasked with analyzing Jira ticket comment history to identify potential solutions, resolutions, or significant progress.
Input is a JSON list of ticket objects, each containing 'id' and 'cleaned_comments'. The comments are sorted newest to oldest.
Analyze the 'cleaned_comments' for *each* ticket object in the input list ({batch_size} tickets total).
For *each* ticket, perform the following:
1. Read through the 'cleaned_comments' (remembering they are oldest first) to understand the resolution attempts and outcomes.
2. Determine if the comments describe:
    a. A clear, implemented solution or fix that resolved the issue.
    b. Significant progress, investigative steps taken, or workarounds attempted, even if a final resolution is not yet documented.
3. If a clear solution/fix (scenario 2a) is described:
    Generate a summary of THE SOLUTION in bullet points (typically 3-6 points), phrased as if explaining the resolution *to the user*. Use descriptive language (e.g., "The issue was resolved...", "The root cause was identified as...", "This was fixed through..."). Focus on what actions or findings resolved the issue.
4. If a clear solution/fix is NOT described, BUT there is evidence of significant progress, steps taken, or attempted workarounds (scenario 2b):
    Generate a concise summary of THE PROGRESS OR STEPS TAKEN in bullet points (typically 3-6 points), phrased as if explaining the status *to the user*. Use descriptive language (e.g., "Investigation currently points to...", "Steps taken so far include...", "The team is currently working on...", "Progress includes..."). Focus on the latest significant actions or findings.
5. If neither a solution/fix nor significant progress/steps can be identified:
    Output the specific string "No clear solution or significant progress identified."

Output *only* a valid JSON list of strings. The list must contain exactly {batch_size} strings.
Each string in the output list must be one of the following, corresponding to the ticket in the input list and maintaining original order:
- The bullet-point solution summary (if scenario 2a).
- The bullet-point progress/steps summary (if scenario 2b).
- The "No clear solution or significant progress identified." message (if scenario 5).

Input JSON list of tickets (with newest comments first):
```json
{batch_input_json}
```

Example output format for a batch of 4 tickets:
[
  "- The root cause was identified as a network configuration issue.\n- Firewall rules were updated accordingly.\n- The fix has been verified with the user and the issue is resolved.",
  "- Investigation currently points towards a potential database deadlock.\n- An attempt was made to optimize related query Q1.\n- The system is now being monitored to assess the impact of this change.",
  "No clear solution or significant progress identified.",
  "- A rollback of the recent deployment (version X) was performed.\n- The issue was confirmed resolved after the rollback."
]

JSON Output list of concise solution summaries, progress updates, or 'no clear information' messages:""" 