from datetime import datetime, timezone
from typing import Optional


_memory: dict[str, dict] = {}


def _log(msg: str) -> None:
    print(f"[workspace_memory] {msg}")


def record(session_token: str, key: str, value: str) -> None:
    if session_token not in _memory:
        _memory[session_token] = {}
    _memory[session_token][key] = value
    _memory[session_token]["_last_updated"] = datetime.now(timezone.utc).isoformat()
    _log(f"record [{session_token}] {key} = {value}")


def get(session_token: str, key: str, default: Optional[str] = None) -> Optional[str]:
    store = _memory.get(session_token, {})
    return store.get(key, default)


def get_all(session_token: str) -> dict:
    store = _memory.get(session_token, {}).copy()
    store.pop("_last_updated", None)
    return {
        "company_description": store.get("company_description", None),
        "ideal_customer": store.get("ideal_customer", None),
        "last_search": store.get("last_search", None),
        "last_campaign_id": store.get("last_campaign_id", None),
        "last_campaign_name": store.get("last_campaign_name", None),
        "last_draft_id": store.get("last_draft_id", None),
        "last_draft_name": store.get("last_draft_name", None),
        "last_recommendation": store.get("last_recommendation", None),
        "last_recommendation_type": store.get("last_recommendation_type", None),
        "last_action": store.get("last_action", None),
        "last_action_timestamp": store.get("_last_updated", None),
    }


def clear(session_token: str) -> None:
    if session_token in _memory:
        del _memory[session_token]
        _log(f"cleared memory for {session_token}")


def record_search(session_token: str, query: str) -> None:
    record(session_token, "last_search", query)
    record(session_token, "last_action", f"search:{query}")


def record_campaign_open(session_token: str, campaign_id: str, name: str) -> None:
    record(session_token, "last_campaign_id", campaign_id)
    record(session_token, "last_campaign_name", name)
    record(session_token, "last_action", f"open_campaign:{name}")


def record_draft_review(session_token: str, draft_id: str, lead_name: str) -> None:
    record(session_token, "last_draft_id", draft_id)
    record(session_token, "last_draft_name", lead_name)
    record(session_token, "last_action", f"review_draft:{lead_name}")


def record_recommendation(session_token: str, rec_type: str, text: str) -> None:
    record(session_token, "last_recommendation", text)
    record(session_token, "last_recommendation_type", rec_type)


def record_launch(session_token: str, campaign_name: str) -> None:
    record(session_token, "last_action", f"launch:{campaign_name}")
