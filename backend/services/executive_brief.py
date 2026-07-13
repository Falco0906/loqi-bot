import json
from typing import Optional

from services.ai import _send_openai_request, OpenAIError


_cache: dict[str, dict] = {}
_cache_key: Optional[str] = None


def _log(msg: str) -> None:
    print(f"[executive_brief] {msg}")


def _make_cache_key(snapshot: dict) -> str:
    campaigns = snapshot.get("campaigns", [])
    drafts = snapshot.get("drafts", {})
    tl = snapshot.get("timeline", [])
    return f"{len(campaigns)}:{drafts.get('pending', 0)}:{drafts.get('approved', 0)}:{len(tl)}"


def generate_brief(snapshot: dict, recommendations: list[dict], force_refresh: bool = False) -> dict:
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

    campaigns = snapshot.get("campaigns", [])
    drafts = snapshot.get("drafts", {})
    jobs = snapshot.get("jobs", {})
    timeline = snapshot.get("timeline", [])
    memory = snapshot.get("memory", {})

    campaigns_text = "\n".join(
        f"  - {c['name']}: {c['status']} ({c['pending_drafts']} pending, {c['approved_drafts']} approved)"
        for c in campaigns[:8]
    ) if campaigns else "  (none)"

    timeline_text = "\n".join(
        f"  - {e['text']}"
        for e in timeline[:5]
    ) if timeline else "  (none)"

    recs_text = "\n".join(
        f"  - [{r['confidence']}] {r['observation']} → {r['action']}"
        for r in recommendations[:3]
    ) if recommendations else "  (none recommended)"

    jobs_text = "\n".join(
        f"  - {j.get('type', 'unknown')} at {j.get('progress', 0)}%"
        for j in jobs.get("running", [])[:3]
    ) if jobs.get("running") else "  (none running)"

    memory_text = f"last action: {memory.get('last_action', 'none')}"

    analysis = snapshot.get("analysis", {})
    analysis_text = ""
    cf = analysis.get("current_focus")
    if cf:
        analysis_text += f"Current focus: {cf.get('focus', 'unknown')}\n"
    rna = analysis.get("recommended_next_action")
    if rna:
        analysis_text += f"Recommended: {rna.get('title', '')}\n"
    priorities = analysis.get("campaign_priorities", [])
    if priorities:
        priority_lines = []
        for cp in priorities[:5]:
            rank_label = cp.get("label", f"#{cp.get('rank', '?')}")
            priority_lines.append(f"  {rank_label}: {cp.get('name', '?')} ({', '.join(cp.get('reasons', []))})")
        analysis_text += "Priorities:\n" + "\n".join(priority_lines) + "\n"
    health = analysis.get("workspace_health")
    if health:
        vel = health.get("pipeline_velocity", "")
        overall = health.get("overall_health", "")
        analysis_text += f"Pipeline: {vel.replace('_', ' ').title()}, Health: {overall}\n"
    wc_obj = analysis.get("workflow_continuation")
    if wc_obj:
        analysis_text += f"Next step: {wc_obj.get('where', 'Start')}\n"
    insights = analysis.get("cross_campaign_insights", [])
    if insights:
        analysis_text += "Cross-campaign dynamics:\n" + "\n".join(f"  - {ins.get('insight', '')}" for ins in insights) + "\n"

    system_text = (
        "You are an executive assistant for Loqi, an outbound sales platform.\n"
        "Write a brief workspace summary in natural, conversational English.\n\n"
        "Return valid JSON with exactly these keys:\n"
        "{\n"
        '  "greeting": "<greeting>",\n'
        '  "lines": ["<paragraph 1>", "<paragraph 2>", ...],\n'
        '  "suggestion": "<one action sentence>"\n'
        "}\n\n"
        "Rules:\n"
        "- The greeting is always provided — use it as-is\n"
        "- Write 2-4 paragraphs (one sentence each is fine). Maximum 4 sentences total.\n"
        "- Speak like an executive assistant: natural, warm, specific\n"
        "- Start with what's most important. Explain tradeoffs.\n"
        "- Reference campaign names naturally\n"
        "- Never list raw statistics unless helpful\n"
        "- End with a recommendation — the single most important action\n"
        "- Never say 'Here's your status', 'Based on the data', 'There are', or 'The workspace contains'\n"
        "- Never use bullet points or lists — write prose"
    )

    user_text = (
        f"Greeting: {greeting}\n\n"
        f"Campaigns:\n{campaigns_text}\n\n"
        f"Drafts: {drafts.get('total', 0)} total, {drafts.get('pending', 0)} pending, {drafts.get('approved', 0)} approved\n\n"
        f"Recent timeline events:\n{timeline_text}\n\n"
        f"Running jobs:\n{jobs_text}\n\n"
        f"User memory: {memory_text}\n\n"
        f"Current recommendations:\n{recs_text}\n\n"
        f"Workspace analysis:\n{analysis_text}\n\n"
        "Write a brief workspace summary in the style of an executive assistant."
    )

    try:
        result = _send_openai_request(system_text, user_text)
        data = json.loads(result)
        brief = {
            "greeting": data.get("greeting", greeting),
            "lines": data.get("lines", []),
            "suggestion": data.get("suggestion", ""),
        }
        _cache_key = ck
        _cache["brief"] = brief
        return brief

    except (OpenAIError, json.JSONDecodeError, KeyError) as e:
        _log(f"brief generation failed: {e}")
        return _fallback_brief(greeting, snapshot, recommendations)


def _fallback_brief(greeting: str, snapshot: dict, recommendations: list[dict]) -> dict:
    lines = []
    campaigns = snapshot.get("campaigns", [])
    drafts = snapshot.get("drafts", {})
    memory = snapshot.get("memory", {})

    ready = [c for c in campaigns if c.get("status") in ("ready", "ready_to_send")]
    review = [c for c in campaigns if c.get("status") == "draft_review" and c.get("pending_drafts", 0) > 0]
    planning = [c for c in campaigns if c.get("status") == "planning"]

    if ready:
        c = ready[0]
        lines.append(f"Your {c['name']} campaign is ready to launch.")
        if review:
            r = review[0]
            lines.append(f"After launching, I'd come back to {r['name']} where {r['pending_drafts']} draft{'s' if r['pending_drafts'] > 1 else ''} {'are' if r['pending_drafts'] > 1 else 'is'} waiting for review.")
        elif planning:
            p = planning[0]
            lines.append(f"Once that's out, {p['name']} needs its strategy finalized before it can move forward.")
        if len(ready) > 1:
            r2 = ready[1]
            lines.append(f"{r2['name']} is also ready to launch as soon as you're free.")
    elif review:
        c = review[0]
        n = c["pending_drafts"]
        lines.append(f"I'd focus on reviewing the {n} pending draft{'s' if n > 1 else ''} in {c['name']}.")
        if planning:
            p = planning[0]
            lines.append(f"Once those are done, {p['name']} can move into draft review too, which keeps your pipeline moving.")
    elif planning:
        c = planning[0]
        lines.append(f"{c['name']} is still in planning with {c.get('lead_count', 0)} leads ready to go.")
        lines.append("Finalizing the strategy now means drafts can generate overnight.")
    elif not campaigns:
        lines.append("No campaigns yet. Finding your first leads takes a few minutes and sets everything in motion.")
    else:
        active = [c for c in campaigns if c.get("status") not in ("completed", "archived")]
        if active:
            lines.append(f"Your {' and '.join(c['name'] for c in active[:2])} campaign{'s' if len(active) > 1 else ''} {'are' if len(active) > 1 else 'is'} in progress.")

    if not lines:
        lines.append("Everything looks up to date. If you're free, discovering leads for your next campaign is never a bad move.")

    suggestion = ""
    if recommendations:
        r = recommendations[0]
        suggestion = f"I'd start with {r['action'].lower()}."

    return {"greeting": greeting, "lines": lines, "suggestion": suggestion}
