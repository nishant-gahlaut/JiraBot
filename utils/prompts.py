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

# Prompt for generating ticket title and description from a single user text input
GENERATE_TICKET_TITLE_AND_DESCRIPTION_PROMPT = """
You are an expert Jira assistant. Given an original ticket description, generate a concise, informative Jira ticket title and a refined, structured Jira ticket description.
The refined description should be suitable for a Jira ticket, well-organized, and easy to read. It should capture all key information from the original description.
Do NOT use any subheadings (e.g., "Summary:", "Details:", "Steps to Reproduce:", "Expected Behavior:", "Actual Behavior:").
Simply provide the refined description as a single block of text.

Original Description:
{original_description}

Respond with a JSON object with two keys: "suggested_title" and "refined_description".
Ensure the JSON is well-formed. For example:
{
  "suggested_title": "Example: User login fails with network error",
  "refined_description": "When a user attempts to log in, if there is a network interruption during the authentication process, the login attempt fails and an unclear error message is displayed. This issue was observed on version 1.2.3 of the web application during peak usage hours. The expected behavior is that the system should either retry the authentication or provide a clear error message indicating a network problem."
}
"""

PROCESS_MENTION_AND_GENERATE_ALL_COMPONENTS_PROMPT = """
You are an intelligent Jira assistant integrated into Slack. You need to process a user's message to you, along with the recent conversation history from the channel/thread where you were mentioned, to understand the user's intent and extract relevant information for Jira ticket creation or issue searching.

User's direct message to bot (this is the message that triggered the mention):
"{user_direct_message_to_bot}"

Formatted conversation history (last 20 messages, excluding the bot's own messages from this an other invocations, and the direct message already provided above):
"{formatted_conversation_history}"

Based on the user's direct message and the conversation history, determine the user's primary intent. The possible intents are:
1.  "CREATE_TICKET": The user wants to create a new Jira ticket.
2.  "FIND_SIMILAR_ISSUES": The user wants to find existing Jira tickets similar to their problem.
3.  "UNCLEAR_INTENT": The user's intent is not clearly to create a ticket or find similar issues. It might be a general question, a comment, or something else.

Then, regardless of the intent, provide the following:
1.  `contextual_summary`: A concise summary of the conversation and the user's message. This summary will be used as context if the user wants to create a ticket or find similar issues. If the intent is `UNCLEAR_INTENT`, this summary helps in deciding the next step.
2.  `suggested_title`: If the information is sufficient, suggest a Jira ticket title. If not, or if the intent is not `CREATE_TICKET`, this can be null or a very generic placeholder if some context is available.
3.  `refined_description`: If the information is sufficient, suggest a refined Jira ticket description. This should be well-structured for a Jira ticket. If not, or if the intent is not `CREATE_TICKET`, this can be null.

Respond with a JSON object containing these four keys: "intent", "contextual_summary", "suggested_title", and "refined_description".
Ensure the JSON is well-formed.

Example for CREATE_TICKET intent:
{{
  "intent": "CREATE_TICKET",
  "contextual_summary": "The user reported that the login page is broken after the latest deployment. They are unable to access their account and see a 500 error. This is affecting multiple users.",
  "suggested_title": "Login page broken after deployment - 500 error",
  "refined_description": "Users are experiencing a 500 error on the login page following the recent deployment (v1.5.2). This prevents them from accessing their accounts. Issue seems to have started immediately after the deployment completed. Multiple users have confirmed this behavior across different browsers."
}}

Example for FIND_SIMILAR_ISSUES intent:
{{
  "intent": "FIND_SIMILAR_ISSUES",
  "contextual_summary": "User is asking if there are any known issues with the payment gateway failing for VISA cards. They mentioned an error code 'ERR_PAY_003'.",
  "suggested_title": null,
  "refined_description": null
}}

Example for UNCLEAR_INTENT intent:
{{
  "intent": "UNCLEAR_INTENT",
  "contextual_summary": "User mentioned 'the new dashboard looks great, but I think the colors are a bit off for the main KPI widget.' They also asked when the next release is planned.",
  "suggested_title": null,
  "refined_description": null
}}
""" 