# state_manager.py
import logging

logger = logging.getLogger(__name__)

# In-memory store for conversation states
# Key: thread_ts, Value: dict containing state info (e.g., {'step': 'awaiting_summary', 'data': {...}})
conversation_states = {}

logger.info("Conversation state manager initialized.") 