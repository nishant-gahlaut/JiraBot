# JiraBot

JiraBot is a conversational AI assistant designed to streamline Jira ticketing processes directly within Slack. It helps users create, summarize, and manage Jira tickets, leveraging AI for tasks like title generation, description refinement, and duplicate ticket detection.

## Features

*   **Conversational AI for Jira**: Interact with the bot in Slack threads or via app mentions to manage Jira tasks.
*   **AI-Powered Ticket Creation**: 
    *   Initiate ticket creation from Slack messages or by describing an issue.
    *   Receive AI-generated suggestions for ticket titles, descriptions,Issue type and criticality.
    *   Capture detailed descriptions through Slack modals.
*   **Duplicate Ticket Detection**: Automatically checks for and displays potentially similar/duplicate Jira tickets before creating a new one.
*   **Ticket Summarization**: Request summaries for existing Jira tickets.
*   **Slack-Native Experience**:
    *   Utilizes Slack buttons, modals, and message threads for a seamless user experience.
    *   Responds to app mentions (`@JiraBot`) for direct queries and actions.
    *   Supports Slack shortcuts for quick actions like "Check Similar Issues" and "Create Ticket from Thread."
*   **Background Data Processing**: Includes capabilities for scraping and ingesting Jira ticket data, potentially for enhancing search and duplicate detection.

## Tech Stack

*   **Core**: Python
*   **Slack Integration**: `slack_bolt` for Python
*   **Jira Integration**: `jira` Python library
*   **AI & LLM**: 
    *   `google-generativeai` (Google Gemini models)
    *   `langchain` (LLM orchestration)
*   **Vector Search/Similarity**: (Indicated by dependencies; specific usage may vary)
    *   `pinecone`
    *   `faiss-cpu` 
*   **Machine Learning/NLP**: `transformers`, `torch` (Potentially for local NLP tasks)
*   **Environment Management**: `python-dotenv`
*   **Other Key Libraries**: `requests`, `joblib`, `pandarallel`

## Prerequisites

*   Python (e.g., 3.9+ recommended)
*   Access to a Jira Cloud or Jira Server instance.
*   Jira API token with appropriate permissions.
*   A Slack workspace where you can install and configure Slack apps.
*   Slack Bot Token and Signing Secret.
*   Google Generative AI API Key.
*   (If using Pinecone) Pinecone API Key and environment details.

### Required Permissions and Configurations

**1. Slack App Configuration:**
Ensure your Slack App is configured with the following:

*   **Socket Mode**: Enabled in your Slack App's settings under "Socket Mode". You will also need an App-Level Token (`SLACK_APP_TOKEN`) generated here.
*   **OAuth & Permissions Scopes**: Under "OAuth & Permissions", your Bot Token Scopes should include at least:
    *   `app_mentions:read`: To receive direct mentions.
    *   `chat:write`: To send messages.
    *   `channels:history`, `groups:history`, `im:history`, `mpim:history`: To read messages in conversations the bot is part of (for context).
    *   `users:read`: To fetch user information (e.g., for mapping Slack users to Jira users).
    *   `commands`: If you plan to add any slash commands.
    *   (Potentially others like `reactions:write`, `files:read` depending on extended functionalities).
*   **Event Subscriptions**: Under "Event Subscriptions", subscribe your bot to workspace events. If using Socket Mode primarily, some events might be implicitly handled, but ensure these are considered:
    *   `app_mention`
    *   `message.channels`
    *   `message.groups`
    *   `message.im`
    *   `message.mpim`
    *   `assistant_thread_started` (if using Slack's newer assistant features)
    *   `assistant_thread_context_changed` (if using Slack's newer assistant features)
*   **Interactivity & Shortcuts**:
    *   Enable "Interactivity" and provide a request URL (though for Socket Mode, this might be less critical for button clicks handled directly).
    *   Configure any message shortcuts or global shortcuts under "Interactivity & Shortcuts".

**2. Jira User Permissions:**
The Jira account associated with `JIRA_USER_EMAIL` and `JIRA_API_TOKEN` must have permissions in your Jira instance to:
*   Browse relevant projects.
*   Search issues.
*   Create issues in relevant projects.
*   Read issue details (summary, description, status, priority, assignee, comments, etc.).
*   (Optional, if bot functionality is extended): Edit issues, add comments, manage watchers.

**3. Google Cloud Project:**
*   A Google Cloud Project must be set up.
*   The Google Generative AI API (e.g., Vertex AI API which provides access to Gemini models) must be enabled for this project.
*   The `GOOGLE_GENAI_KEY` should be an API key associated with this project, having permissions to use the Generative AI services.

## Setup and Installation

1.  **Clone the Repository**:
    ```bash
    git clone <your-repository-url>
    cd JiraBot # Or your project directory name
    ```

2.  **Create and Activate a Virtual Environment**:
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    ```

3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables**:
    Create a `.env` file in the root of the project and add the following necessary variables. Obtain these values from your Slack app configuration (make sure the app is configured with the permissions outlined in "Prerequisites"), Jira admin, and Google Cloud Console.

    ```env
    # Slack
    SLACK_BOT_TOKEN="xoxb-your-bot-token"
    SLACK_SIGNING_SECRET="your-slack-signing-secret"
    SLACK_APP_TOKEN="xapp-your-app-level-token-for-socket-mode" # If using Socket Mode

    # Jira
    JIRA_SERVER="https://your-domain.atlassian.net" # Or your self-hosted Jira URL
    JIRA_USER_EMAIL="your-jira-bot-user-email@example.com"
    JIRA_API_TOKEN="your-jira-api-token"
    # JIRA_PROJECT_KEY="YOUR_DEFAULT_JIRA_PROJECT_KEY" # If a default project is often used

    # Google Generative AI
    GOOGLE_GENAI_KEY="your-google-genai-api-key"

    # Pinecone (if used)
    # PINECONE_API_KEY="your-pinecone-api-key"
    # PINECONE_ENVIRONMENT="your-pinecone-environment"
    
    # Other configurations (example)
    # JIRA_ASSISTANT_ID="your-slack-assistant-id" # If applicable for certain Slack API calls
    ```
    **Note**: `SLACK_APP_TOKEN` is required if you are running the bot using Socket Mode (which is common for development and some deployment scenarios).

## Running the Application

The application uses Socket Mode for connecting to Slack.

1.  **Ensure your `.env` file is correctly configured.**
2.  **Run the application**:
    ```bash
    python app.py
    ```
    The bot should connect to Slack and be ready for interactions. Check the console logs for any errors or confirmation messages.

## Usage

Interact with JiraBot within your Slack workspace:

*   **App Mentions**: Mention `@JiraBot` in any channel it has been added to, followed by your query (e.g., `@JiraBot create a ticket for a login bug`).
*   **Slack Threads**: Start a thread on a message or reply in an existing thread where the bot is active. The bot can use the thread context to help create or find tickets.
*   **Buttons and Modals**: The bot uses interactive buttons (e.g., "Create Ticket", "Summarize", "My Tickets") and modals for structured input like ticket details.
*   **Shortcuts**:
    *   **Check Similar Issues**: Accessible from message shortcuts, allowing you to select a message and check for related Jira tickets.
    *   **Create Ticket from Thread**: A message shortcut to quickly start the ticket creation process using the content of the selected message.

**Example Interactions:**

*   User posts a message: "The login page is broken again."
*   Use the "Create Ticket from Thread" message shortcut on that message.
*   The bot may ask for confirmation or more details, suggest a title/description, and check for duplicates before creating the Jira ticket.
*   Mentioning the bot: `@JiraBot show me my open tickets updated in the last week.`

## Project Structure

*   `app.py`: Main application file, sets up the Slack app and routes events.
*   `handlers/`: Contains modules for handling Slack events (messages, actions, mentions, modals, shortcuts) and orchestrating bot responses and flows.
    *   `action_sequences/`: Specific multi-step interaction flows.
    *   `modals/`: Logic for building and handling Slack modals.
*   `services/`: Includes modules for interacting with external services like Jira (`jira_service.py`), AI/LLM providers (`genai_service.py`), and duplicate detection (`duplicate_detection_service.py`).
*   `utils/`: Utility functions, helpers (e.g., `slack_ui_helpers.py`, `state_manager.py`), and data processing scripts.
*   `pipelines/`: For data ingestion and processing tasks (e.g., `ingestion_pipeline.py`).
*   `requirements.txt`: Python dependencies.
*   `.env.example`: (Recommended to create) An example template for the `.env` file.
*   `Data_cleaning_pipeline.ipynb`: Jupyter notebook for data cleaning and experimentation.

## Contributing

(Details on how to contribute to the project, if applicable. E.g., coding standards, pull request process.)

## License

This project is licensed under the terms of the `LICENSE` file.
