"""Supabase-backed conversation history storage."""
import os
from supabase import create_client

_client = None


def _get_client():
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        _client = create_client(url, key)
    return _client


def save_message(session_id: str, account_id: str, role: str, content: str):
    """Save a single message to Supabase."""
    try:
        _get_client().table("conversation_history").insert({
            "session_id": session_id,
            "account_id": account_id,
            "role": role,
            "content": content,
        }).execute()
    except Exception:
        pass  # don't crash the app if DB write fails


def load_history(session_id: str, limit: int = 10):
    """Load last N messages for a session."""
    try:
        result = (
            _get_client()
            .table("conversation_history")
            .select("role, content")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return list(reversed(result.data))
    except Exception:
        return []
