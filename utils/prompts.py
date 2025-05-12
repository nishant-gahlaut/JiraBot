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
Summarize the following Slack thread conversation concisely. Focus on the main topic, any problems raised, and proposed solutions or next steps mentioned. Extract the core information relevant for understanding the situation quickly.

Conversation:
---
{thread_content}
---

Concise Summary:"""

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
Analyze the user description below. Generate a concise Jira ticket title and a refined, detailed Jira ticket description. 
Output *only* a valid JSON object with the keys "suggested_title" and "refined_description".

User Description:
---
{user_description}
---

JSON Output:"""

# Prompt for generating Summary, Title, and Description from a thread (JSON output)
GENERATE_TICKET_COMPONENTS_FROM_THREAD_PROMPT = """
Analyze the following Slack thread conversation. Generate a concise summary of the thread, a suggested Jira ticket title, and a refined Jira ticket description based on the conversation. 
Focus the title and description on the primary issue or task discussed.
Output *only* a valid JSON object with the keys "thread_summary", "suggested_title", and "refined_description".

Slack Thread Conversation:
---
{slack_thread_conversation}
---

JSON Output:"""

# Prompt for processing a mention, understanding intent, and generating components (JSON output)
PROCESS_MENTION_AND_GENERATE_ALL_COMPONENTS_PROMPT = """
Analyze the user's direct message to the bot and the recent conversation history provided below.
Determine the user's primary intent (e.g., 'create_ticket', 'find_similar_tickets', 'clarification', 'unrelated').
Generate a concise contextual summary based on the direct message and history.
If the intent seems to be 'create_ticket' or involves describing a problem, generate a suggested Jira ticket title and a refined Jira ticket description.
Output *only* a valid JSON object containing:
- "intent": The determined user intent string.
- "contextual_summary": A brief summary of the conversation context.
- "suggested_title": A relevant Jira ticket title (or null/empty if intent is not creation-related).
- "refined_description": A detailed Jira ticket description (or null/empty if intent is not creation-related).

User Direct Message to Bot:
---
{user_direct_message_to_bot}
---

Recent Conversation History:
---
{formatted_conversation_history}
---

JSON Output:"""

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