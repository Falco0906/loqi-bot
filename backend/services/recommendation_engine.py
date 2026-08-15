"""Recommendation engine — thin adapter between Reasoning Layer and Narrative Engine.

Phase 5: the recommendation engine no longer decides what to recommend.
It builds structured recommendation cards from the deterministic Reasoning
Layer output (priorities, attention items, recommended_next_action) and
delegates natural-language refinement to ``NarrativeEngine.write_recommendations()``.

The LLM only rephrases wording — it never decides what to recommend or
how to rank recommendations.
"""

import json
from typing import Optional

from services.ai import _send_openai_request, OpenAIError
from services.narrative_engine import BriefingContext, get_engine


_cache: dict[str, dict] = {}
_cache_key: Optional[str] = None


def _log(msg: str) -> None:
    print(f"[recommendation_engine] {msg}")


def _make_cache_key(snapshot: dict) -> str:
    campaigns = snapshot.get("campaigns", [])
    drafts = snapshot.get("drafts", {})
    return f"{len(campaigns)}:{drafts.get('pending', 0)}:{drafts.get('approved', 0)}"


def _build_structured_recommendations(snapshot: dict) -> list[dict]:
    """Build recommendation cards from deterministic Reasoning Layer output.

    This is the core business judgment — it converts analysis data into
    structured recommendations.  No LLM involved.  Returns the same
    schema as the legacy ``generate_recommendations()``.
    """
    analysis = snapshot.get("analysis", {})
    attention = analysis.get("attention_items", [])
    priorities = analysis.get("campaign_priorities", [])
    rna = analysis.get("recommended_next_action", {})
    health = analysis.get("workspace_health", {})
    campaigns = snapshot.get("campaigns", [])
    drafts = snapshot.get("drafts", {})

    recommendations = []

    # ── Build from attention items (pre-ranked by WorkspaceReasoner) ──
    for a in attention[:3]:
        rec = {
            "type": a.get("action", "review").lower().replace(" ", "_"),
            "observation": a.get("title", ""),
            "reason": a.get("reason", ""),
            "action": a.get("action", "Review"),
            "confidence": _confidence_label(a.get("confidence", 75)),
            "link": a.get("link", "/campaigns"),
            "why_details": [
                a.get("title", ""),
                f"Importance: {a.get('importance', 5)}/10",
                f"Waiting: {a.get('time_waiting', 'recently')}",
            ],
        }
        recommendations.append(rec)

    # ── Fill remaining slots with priority-driven recommendations ──
    if len(recommendations) < 3 and priorities:
        for cp in priorities:
            if len(recommendations) >= 3:
                break
            c = next(
                (c for c in campaigns if c.get("id") == cp.get("campaign_id")),
                None,
            )
            if not c:
                continue

            # Skip if this campaign already has an attention item
            if any(
                r.get("link", "").endswith(cp.get("campaign_id", ""))
                for r in recommendations
            ):
                continue

            status = c.get("status", "")
            step = c.get("current_step", "")
            rec = None

            if step == "sending":
                rec = {
                    "type": "launch_campaign",
                    "observation": f"You're ready to launch {c.get('name', '')}.",
                    "reason": "Every day you wait, the messaging gets less fresh. Launching now puts your outreach in front of leads immediately.",
                    "action": "Launch Campaign",
                    "confidence": "high",
                    "link": f"/campaigns/{c.get('id', '')}",
                    "why_details": ["All drafts approved", "Highest priority campaign", "No blockers remaining"],
                }
            elif step == "review":
                pd = c.get("pending_drafts", 0)
                if pd > 0:
                    rec = {
                        "type": "review_drafts",
                        "observation": f"I'd review the {pd} pending draft{'s' if pd > 1 else ''} in {c.get('name', '')}.",
                        "reason": "Pending drafts create a bottleneck that holds up the rest of your pipeline.",
                        "action": "Review Drafts",
                        "confidence": "high",
                        "link": "/draft",
                        "why_details": [f"{pd} draft{'s' if pd > 1 else ''} waiting", "Blocks campaign launch"],
                    }
            elif status == "planning" and c.get("lead_count", 0) > 0:
                rec = {
                    "type": "continue_planning",
                    "observation": f"{c.get('name', '')} is ready for its strategy.",
                    "reason": "Setting the strategy now means drafts can generate.",
                    "action": "Continue Planning",
                    "confidence": "medium",
                    "link": f"/campaigns/{c.get('id', '')}",
                    "why_details": [f"{c.get('lead_count', 0)} leads waiting", "Next step after planning"],
                }
            elif status == "planning":
                rec = {
                    "type": "find_leads",
                    "observation": f"{c.get('name', '')} needs leads to move forward.",
                    "reason": "A campaign without leads cannot progress. Discovery takes a few minutes.",
                    "action": "Find Leads",
                    "confidence": "medium",
                    "link": "/discovery",
                    "why_details": ["No leads yet", "Quick to start", "Builds pipeline momentum"],
                }

            if rec:
                recommendations.append(rec)

    # ── If still empty, use the recommended_next_action from analysis ──
    if not recommendations and rna:
        recommendations.append({
            "type": rna.get("link", "/campaigns").strip("/").replace("/", "_") or "review",
            "observation": rna.get("title", ""),
            "reason": rna.get("reason", ""),
            "action": rna.get("title", "Review"),
            "confidence": rna.get("confidence", "medium"),
            "link": rna.get("link", "/campaigns"),
            "why_details": ["Recommended by workspace analysis"],
        })

    # ── Last-resort fallback ──
    if not recommendations and not campaigns:
        recommendations.append({
            "type": "find_leads",
            "observation": "Let's find your first leads.",
            "reason": "Outbound success starts with finding the right prospects.",
            "action": "Find Leads",
            "confidence": "medium",
            "link": "/discovery",
            "why_details": ["No campaigns yet", "Quick to start"],
        })

    return recommendations[:3]


def _confidence_label(score: int) -> str:
    if score >= 85:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


def generate_recommendations(
    snapshot: dict,
    force_refresh: bool = False,
) -> list[dict]:
    """Generate recommendations from a workspace snapshot.

    Phase 5: builds structured recommendations from the deterministic
    Reasoning Layer (analysis data) and delegates wording refinement
    to the Narrative Engine.

    Returns the same schema as before for API compatibility.
    """
    global _cache_key

    ck = _make_cache_key(snapshot)
    if not force_refresh and _cache_key == ck and _cache.get("recommendations"):
        _log("returning cached recommendations")
        return _cache["recommendations"]

    # Step 1: build structured cards from reasoning layer (deterministic)
    structured = _build_structured_recommendations(snapshot)

    # Step 2: refine wording via Narrative Engine (NLG only)
    analysis = snapshot.get("analysis", {})
    context = BriefingContext(
        workspace_delta=snapshot.get("_delta", {}),
        priorities=analysis.get("campaign_priorities", []),
        attention_items=analysis.get("attention_items", []),
        health_summary=analysis.get("workspace_health", {}),
        recommendations=structured,
        campaigns=snapshot.get("campaigns", []),
        drafts=snapshot.get("drafts", {}),
        jobs=snapshot.get("jobs", {}),
    )

    engine = get_engine()
    refined = engine.write_recommendations(context)

    validated = []
    for rec in (refined if refined else structured):
        if all(k in rec for k in ("observation", "reason", "action", "confidence", "type")):
            validated.append({
                "type": rec["type"],
                "observation": rec["observation"],
                "reason": rec["reason"],
                "action": rec["action"],
                "confidence": rec["confidence"],
                "link": rec.get("link", "/campaigns"),
                "why_details": rec.get("why_details", []),
            })

    _cache_key = ck
    _cache["recommendations"] = validated
    return validated
