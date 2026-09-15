from datetime import datetime, timezone
from typing import Optional


_timelines: dict[str, list[dict]] = {}
_MAX_EVENTS = 50


def _log(msg: str) -> None:
    print(f"[workspace_timeline] {msg}")


def add_event(session_token: str, event_type: str, text: str, metadata: Optional[dict] = None) -> dict:
    if session_token not in _timelines:
        _timelines[session_token] = []
    event = {
        "type": event_type,
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }
    _timelines[session_token].append(event)
    if len(_timelines[session_token]) > _MAX_EVENTS:
        _timelines[session_token] = _timelines[session_token][-_MAX_EVENTS:]
    _log(f"add_event [{session_token}] {event_type}: {text}")
    return event


def get_events(session_token: str, limit: int = 20) -> list[dict]:
    events = _timelines.get(session_token, [])
    return list(reversed(events))[:limit]


def get_grouped_events(session_token: str, limit: int = 10) -> list[dict]:
    """Return timeline events with consecutive same-type events grouped.

    Groups events of the same type that occurred within a 5-minute window,
    showing a count label instead of repeating entries.
    """
    raw = _timelines.get(session_token, [])
    reversed_events = list(reversed(raw))
    if not reversed_events:
        return []

    grouped: list[dict] = []
    window_minutes = 5

    for e in reversed_events:
        if grouped and _is_same_group(grouped[-1], e, window_minutes):
            grouped[-1]["_count"] += 1
            grouped[-1]["_texts"].append(e.get("text", ""))
            grouped[-1]["_latest"] = e.get("timestamp", "")
        else:
            grouped.append({**e, "_count": 1, "_texts": [e.get("text", "")], "_latest": e.get("timestamp", "")})

    result = []
    for g in grouped[:limit]:
        entry = {
            "type": g["type"],
            "timestamp": g.get("_latest", g.get("timestamp", "")),
        }
        if g["_count"] > 1:
            entry["text"] = _group_label(g["type"], g["_count"])
            entry["count"] = g["_count"]
            entry["grouped"] = True
        else:
            entry["text"] = g.get("text", "")
            entry["count"] = 1
            entry["grouped"] = False
        result.append(entry)

    return result


def _is_same_group(prev: dict, curr: dict, window_minutes: int) -> bool:
    if prev.get("type") != curr.get("type"):
        return False
    try:
        t1 = datetime.fromisoformat(prev.get("timestamp", "").replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(curr.get("timestamp", "").replace("Z", "+00:00"))
        return abs((t1 - t2).total_seconds()) / 60 <= window_minutes
    except (ValueError, TypeError):
        return False


def _group_label(event_type: str, count: int) -> str:
    labels = {
        "draft_approved": f"Approved {count} drafts",
        "campaign_created": f"Created {count} campaigns",
        "drafts_generated": f"Generated drafts for {count} campaigns",
        "search_completed": f"Completed {count} searches",
        "campaign_ready": f"{count} campaigns ready to launch",
        "campaign_launched": f"Launched {count} campaigns",
    }
    return labels.get(event_type, f"{event_type.replace('_', ' ').title()} ({count}x)")


def clear(session_token: str) -> None:
    if session_token in _timelines:
        del _timelines[session_token]
        _log(f"cleared timeline for {session_token}")


def record_search_started(session_token: str, query: str) -> dict:
    return add_event(session_token, "search_started", f"Searching {query}...")


def record_search_completed(session_token: str, query: str, count: int) -> dict:
    label = f"Found {count} qualified companies" if count > 0 else "Search completed — no new results"
    return add_event(session_token, "search_completed", label, {"query": query, "count": count})


def record_campaign_created(session_token: str, name: str) -> dict:
    return add_event(session_token, "campaign_created", f"Created campaign: {name}")


def record_drafts_generated(session_token: str, campaign_name: str, count: int) -> dict:
    return add_event(session_token, "drafts_generated", f"Generated {count} personalized drafts for {campaign_name}")


def record_draft_approved(session_token: str, lead_name: str, campaign_name: Optional[str] = None) -> dict:
    label = f"Approved draft for {lead_name}" + (f" in {campaign_name}" if campaign_name else "")
    return add_event(session_token, "draft_approved", label)


def record_campaign_ready(session_token: str, name: str) -> dict:
    return add_event(session_token, "campaign_ready", f"{name} is ready to launch")


def record_campaign_launched(session_token: str, name: str) -> dict:
    return add_event(session_token, "campaign_launched", f"Launched {name}")
