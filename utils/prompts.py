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
SUMMARIZE_SLACK_THREAD_PROMPT = """You are an expert assistant tasked with summarizing a Slack thread conversation. 
The conversation history is provided below, with each message prefixed by the user who sent it. 
Messages are ordered from oldest to newest.
Provide a concise summary (2-3 sentences) of the main topics discussed and any potential action items or questions raised.

Conversation History:
{conversation_history}

Concise Summary:"""

# Prompt for generating a concise Jira ticket title from user description
GENERATE_TICKET_TITLE_PROMPT = """You are an expert technical writer. Based on the following user description of an issue or request, 
craft a clear, concise, and informative Jira ticket title. The title should be a single line and accurately reflect the core problem or task.

User Description:
'''{user_description}'''

Jira Ticket Title:"""

# Prompt for generating a refined Jira ticket description
GENERATE_TICKET_DESCRIPTION_PROMPT = """You are an expert technical writer creating a Jira ticket description. 
Based on the user's initial description, generate a refined and structured ticket description suitable for a Jira ticket.

Follow these guidelines for the description:
- Begin with a 2-3 line concise overview of the core issue or request.
- If the user's input suggests multiple steps, tasks, or distinct points, present these as bullet points following the overview.
- If relevant and inferable, you can subtly incorporate general context about common IT/software development environments, backend systems, or tech stacks to enhance clarity. Do not invent specific technical details not hinted at by the user.
- Ensure the language is professional and clear for a development team.
- Do NOT include any prefixed labels like 'Summary:', 'Overview:', 'Bullet Points:', or 'Details:' in your output. Provide only the refined description text itself.

User's Initial Description:
'''{user_description}'''

Refined Jira Ticket Description (direct output):
"""

# Prompt for generating all ticket components (summary, title, description) from a Slack thread
GENERATE_TICKET_COMPONENTS_FROM_THREAD_PROMPT = """You are an expert AI assistant analyzing a Slack thread to help create a Jira ticket.
Based on the following Slack thread conversation, provide three pieces of information:
1.  A concise overall summary of the entire thread's discussion (2-4 sentences).
2.  A suggested, concise Jira ticket title that captures the main actionable issue or request from the thread.
3.  A refined and structured Jira ticket description. This description should start with a 2-3 line overview of the core issue/request identified from the thread, and if the thread implies multiple steps, tasks, or distinct points, list them as bullet points under the overview. If relevant, subtly incorporate general IT/software context if it enhances clarity, but do not invent specifics.

Return these three items formatted as a single JSON object with the keys "thread_summary", "suggested_title", and "refined_description".
Do NOT include any prefixed labels like 'Summary:', 'Title:', 'Description:' within the *values* of these JSON fields. The values should be the direct text for each component.

Slack Thread Conversation:
--- BEGIN THREAD ---
{slack_thread_conversation}
--- END THREAD ---

JSON Output:
""" 