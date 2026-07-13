import json
from typing import Optional

from services.ai import _send_openai_request, OpenAIError


_cache: dict[str, dict] = {}
_cache_key: Optional[str] = None


def _log(msg: str) -> None:
    print(f"[recommendation_engine] {msg}")


def _build_snapshot_text(snapshot: dict) -> str:
    parts = [f"Total campaigns: {snapshot['campaign_count']}"]
    parts.append(f"Campaigns ready to launch: {snapshot['campaigns_ready']}")
    parts.append(f"Campaigns in draft review: {snapshot['campaigns_draft_review']}")
    parts.append(f"Total drafts: {snapshot['drafts']['total']}")
    parts.append(f"Pending drafts: {snapshot['drafts']['pending']}")
    parts.append(f"Approved drafts: {snapshot['drafts']['approved']}")
    parts.append(f"Total leads: {snapshot['total_leads']}")

    if snapshot["campaigns"]:
        parts.append("\nCampaigns:")
        for c in snapshot["campaigns"]:
            parts.append(
                f"  - {c['name']}: status={c['status']}, "
                f"leads={c['lead_count']}, "
                f"pending_drafts={c['pending_drafts']}, "
                f"approved_drafts={c['approved_drafts']}"
            )

    if snapshot["jobs"]["running"]:
        parts.append("\nRunning jobs:")
        for j in snapshot["jobs"]["running"]:
            parts.append(f"  - {j.get('type', 'unknown')}: {j.get('progress', 0)}%")

    if snapshot["memory"]["last_action"]:
        parts.append(f"\nLast user action: {snapshot['memory']['last_action']}")

    if snapshot.get("analysis"):
        analysis = snapshot["analysis"]
        cf = analysis.get("current_focus")
        if cf:
            parts.append(f"\nCurrent focus: {cf.get('focus', 'unknown')}")
        rna = analysis.get("recommended_next_action")
        if rna:
            parts.append(f"Recommended: {rna.get('title', '')} ({rna.get('reason', '')})")
        priorities = analysis.get("campaign_priorities", [])
        if priorities:
            parts.append("\nCampaign priorities (highest first):")
            for cp in priorities[:5]:
                parts.append(f"  {cp.get('label', f'#{cp.get('rank')}')}: {cp.get('name', '?')} ({cp.get('status', '')}) — {', '.join(cp.get('reasons', []))}")
        health = analysis.get("workspace_health")
        if health:
            vel = health.get("pipeline_velocity", "")
            parts.append(f"\nPipeline: {vel.replace('_', ' ').title()}")
        insights = analysis.get("cross_campaign_insights", [])
        if insights:
            parts.append("\nCross-campaign insights:")
            for ins in insights:
                parts.append(f"  - {ins.get('insight', '')}")
        wc_obj = analysis.get("workflow_continuation")
        if wc_obj:
            parts.append(f"\nNext step: {wc_obj.get('where', 'Start something new')}")
        attention = analysis.get("attention_items", [])
        if attention:
            parts.append("\nAttention items:")
            for a_item in attention[:3]:
                parts.append(f"  - {a_item.get('title', '')}: {a_item.get('reason', '')}")

    return "\n".join(parts)


def _make_cache_key(snapshot: dict) -> str:
    campaigns = snapshot.get("campaigns", [])
    drafts = snapshot.get("drafts", {})
    return f"{len(campaigns)}:{drafts.get('pending', 0)}:{drafts.get('approved', 0)}"


def generate_recommendations(snapshot: dict, force_refresh: bool = False) -> list[dict]:
    global _cache_key

    ck = _make_cache_key(snapshot)
    if not force_refresh and _cache_key == ck and _cache.get("recommendations"):
        _log("returning cached recommendations")
        return _cache["recommendations"]

    snapshot_text = _build_snapshot_text(snapshot)

    system_text = (
        "You are an experienced outbound operator advising a founder running campaigns.\n"
        "Your tone is direct, warm, and specific — never robotic.\n"
        "Given the workspace below, give 1-3 advisory recommendations.\n\n"
        "Each must include:\n"
        "- observation: what you see, stated naturally (e.g. \"You're ready to launch Restaurant Outreach\")\n"
        "- reason: why now — what happens if ignored, and what benefit acting provides\n"
        "- action: a short verb phrase (e.g. \"Review Drafts\", \"Launch Campaign\")\n"
        "- confidence: \"high\", \"medium\", or \"low\"\n"
        "- type: one of \"review_drafts\", \"launch_campaign\", \"continue_planning\", \"expand_leads\", \"generate_drafts\", \"find_leads\"\n"
        "- link: \"/draft\", \"/campaigns\", or \"/discovery\"\n"
        "- why_details: a list of 2-4 concrete reasons that explain WHY this recommendation\n\n"
        "Rules:\n"
        "- Speak like an advisor: \"I'd focus on...\", \"The quickest win is...\", \"Next I'd...\"\n"
        "- Every recommendation must answer: why now? what happens if ignored? what benefit?\n"
        "- Compare campaigns when useful: \"Restaurant is further along than Websites\"\n"
        "- Never recommend something already done\n"
        "- Never say 'There are', 'The campaign has', or 'The workspace contains'\n"
        "- Return valid JSON array only — no markdown, no explanation\n"
        "- Maximum 3 recommendations, minimum 1 if anything needs attention"
    )

    user_text = f"Workspace snapshot:\n\n{snapshot_text}\n\nGenerate advisory recommendations as a JSON array."

    try:
        result = _send_openai_request(system_text, user_text)
        data = json.loads(result)
        if not isinstance(data, list):
            data = [data]

        validated = []
        for rec in data[:3]:
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

    except (OpenAIError, json.JSONDecodeError, KeyError) as e:
        _log(f"recommendation generation failed: {e}")
        return _fallback_recommendations(snapshot)


def _fallback_recommendations(snapshot: dict) -> list[dict]:
    recommendations = []
    campaigns = snapshot.get("campaigns", [])
    drafts = snapshot.get("drafts", {})

    ready = [c for c in campaigns if c.get("status") in ("ready", "ready_to_send")]
    review = [c for c in campaigns if c.get("status") == "draft_review" and c.get("pending_drafts", 0) > 0]
    planning = [c for c in campaigns if c.get("status") == "planning"]

    if ready:
        c = ready[0]
        recommendations.append({
            "type": "launch_campaign",
            "observation": f"You're ready to launch {c['name']}.",
            "reason": f"Every day you wait, the messaging gets less fresh. Launching now puts your outreach in front of leads immediately.",
            "action": "Launch Campaign",
            "confidence": "high",
            "link": f"/campaigns/{c['id']}",
            "why_details": ["All drafts approved", "Highest priority campaign", "No blockers remaining"],
        })
    elif review:
        c = review[0]
        n = c["pending_drafts"]
        recommendations.append({
            "type": "review_drafts",
            "observation": f"I'd review the {n} pending draft{'s' if n > 1 else ''} in {c['name']}.",
            "reason": "Finishing the review moves this campaign one step closer to launch. Pending drafts create a bottleneck that holds up the rest of your pipeline.",
            "action": "Review Drafts",
            "confidence": "high",
            "link": "/draft",
            "why_details": [f"{n} draft{'s' if n > 1 else ''} waiting", "Blocks campaign launch", "Quick to complete"],
        })
    elif planning:
        c = planning[0]
        recommendations.append({
            "type": "continue_planning",
            "observation": f"{c['name']} is ready for its strategy.",
            "reason": "Setting the messaging now means drafts can generate overnight while you sleep.",
            "action": "Continue Planning",
            "confidence": "medium",
            "link": f"/campaigns/{c['id']}",
            "why_details": [f"{c.get('lead_count', 0)} leads waiting", "Draft generation unlocks review stage"],
        })
    elif drafts.get("total", 0) == 0 and campaigns:
        c = campaigns[0]
        recommendations.append({
            "type": "generate_drafts",
            "observation": f"Your leads in {c['name']} are ready for drafts.",
            "reason": "Generation runs in the background. Starting now means you'll have drafts to review by the time you're back.",
            "action": "Generate Drafts",
            "confidence": "medium",
            "link": f"/campaigns/{c['id']}",
            "why_details": ["Runs in background", "No effort required", "Moves pipeline forward"],
        })
    elif not campaigns:
        recommendations.append({
            "type": "find_leads",
            "observation": "Let's find your first leads.",
            "reason": "Outbound success starts with at least 3 active campaigns. Discovery takes a few minutes and sets everything in motion.",
            "action": "Find Leads",
            "confidence": "medium",
            "link": "/discovery",
            "why_details": ["No campaigns yet", "Quick to start", "Builds pipeline momentum"],
        })

    return recommendations
