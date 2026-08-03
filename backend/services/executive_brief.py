"""Executive Brief — thin adapter between Reasoning Layer and Narrative Engine.

Phase 5: this module no longer decides what is important, what to highlight,
or how to prioritise.  Those responsibilities live in the deterministic
Reasoning Layer (WorkspaceReasoner + World Model).

It builds a ``BriefingContext`` from the incoming snapshot + recommendations
and delegates all natural-language generation to ``NarrativeEngine``.
"""

from services.narrative_engine import BriefingContext, get_engine


_cache: dict[str, dict] = {}
_cache_key: str | None = None


def _log(msg: str) -> None:
    print(f"[executive_brief] {msg}")


def _make_cache_key(snapshot: dict) -> str:
    campaigns = snapshot.get("campaigns", [])
    drafts = snapshot.get("drafts", {})
    tl = snapshot.get("timeline", [])
    delta = snapshot.get("_delta", {})
    dk = delta.get("event_count", 0) if delta else "0"
    return f"{len(campaigns)}:{drafts.get('pending', 0)}:{drafts.get('approved', 0)}:{len(tl)}:{dk}"


def generate_brief(
    snapshot: dict,
    recommendations: list[dict],
    force_refresh: bool = False,
) -> dict:
    """Generate a narrative briefing from the workspace snapshot.

    Public interface is unchanged (Phase 4/5 compatibility).
    Internally builds a ``BriefingContext`` and delegates to ``NarrativeEngine``.
    """
    global _cache_key

    ck = _make_cache_key(snapshot)
    if not force_refresh and _cache_key == ck and _cache.get("brief"):
        _log("returning cached brief")
        return _cache["brief"]

    import datetime
    h = datetime.datetime.now().hour
    if h < 12:
        greeting = "Good morning"
    elif h < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    analysis = snapshot.get("analysis", {})

    context = BriefingContext(
        greeting=greeting,
        workspace_delta=snapshot.get("_delta", {}),
        priorities=analysis.get("campaign_priorities", []),
        attention_items=analysis.get("attention_items", []),
        health_summary=analysis.get("workspace_health", {}),
        current_focus=analysis.get("current_focus", {}),
        recommended_next_action=analysis.get("recommended_next_action", {}),
        cross_campaign_insights=analysis.get("cross_campaign_insights", []),
        recommendations=recommendations,
        campaigns=snapshot.get("campaigns", []),
        drafts=snapshot.get("drafts", {}),
        jobs=snapshot.get("jobs", {}),
        memory=snapshot.get("memory", {}),
        timeline=snapshot.get("timeline", []),
    )

    engine = get_engine()
    brief = engine.write_brief(context)

    _cache_key = ck
    _cache["brief"] = brief
    return brief
