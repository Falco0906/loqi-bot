from typing import Dict, Any

# In-memory store for user states
# Format: { chat_id: { "step": int, "service": str, "target": str } }
user_sessions: Dict[int, Dict[str, Any]] = {}

def get_session(chat_id: int) -> Dict[str, Any]:
    """Retrieve or initialize a user session."""
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {"step": 1, "service": None, "target": None}
    return user_sessions[chat_id]

def update_session(chat_id: int, updates: Dict[str, Any]) -> None:
    """Update a user session with new data."""
    session = get_session(chat_id)
    session.update(updates)

def clear_session(chat_id: int) -> None:
    """Clear a user session."""
    if chat_id in user_sessions:
        user_sessions.pop(chat_id)
