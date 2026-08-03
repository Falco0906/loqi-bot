from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from services.ai import _send_openai_request, OpenAIError


# ── Structured contract between Reasoning and Narrative ──


@dataclass
class BriefingContext:
    """Everything the Narrative Engine needs to produce natural-language output.

    This is the **only** input to the Narrative Engine.  It is produced by the
    deterministic Reasoning Layer (WorkspaceReasoner + World Model) and must
    contain **pre-ranked, pre-prioritised** data.  The Narrative Engine never
    re-orders or re-prioritises — it only communicates.
    """

    greeting: str = ""

    # ── World Model data ──
    workspace_state: dict[str, Any] = field(default_factory=dict)
    workspace_delta: dict[str, Any] = field(default_factory=dict)

    # ── Reasoning Layer output (deterministic, pre-ranked) ──
    priorities: list[dict] = field(default_factory=list)
    attention_items: list[dict] = field(default_factory=list)
    health_summary: dict[str, Any] = field(default_factory=dict)
    current_focus: dict[str, Any] = field(default_factory=dict)
    recommended_next_action: dict[str, Any] = field(default_factory=dict)
    cross_campaign_insights: list[dict] = field(default_factory=list)

    # ── Recommendations (from recommendation engine, pre-ranked) ──
    recommendations: list[dict] = field(default_factory=list)

    # ── Derived by Reasoning Layer from delta + analysis ──
    opportunities: list[dict] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)

    # ── Snapshot fields for legacy compatibility ──
    campaigns: list[dict] = field(default_factory=list)
    drafts: dict[str, Any] = field(default_factory=dict)
    jobs: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict] = field(default_factory=list)

    def is_first_visit(self) -> bool:
        return self.workspace_delta.get("first_visit", True)

    def has_delta(self) -> bool:
        return self.workspace_delta.get("has_delta", False) and not self.is_first_visit()

    def to_user_text(self) -> str:
        """Build the user prompt from structured context."""
        parts = [f"Greeting: {self.greeting}"]

        # ── Delta section (pre-computed, no judgment) ──
        if self.is_first_visit():
            parts.append("")
            parts.append("FIRST VISIT — the user has never seen this workspace before.")
            parts.append("Introduce the workspace naturally and highlight the most important items.")
        elif self.has_delta():
            d = self.workspace_delta
            delta_lines = []
            if d.get("new_campaigns"):
                delta_lines.append(f"{d['new_campaigns']} new campaign(s)")
            if d.get("changed_campaigns"):
                delta_lines.append(f"{d['changed_campaigns']} campaign(s) changed status")
            if d.get("new_drafts"):
                delta_lines.append(f"{d['new_drafts']} new draft(s)")
            if d.get("scheduled_drafts"):
                delta_lines.append(f"{d['scheduled_drafts']} draft(s) scheduled")
            if d.get("sent_outreach"):
                delta_lines.append(f"{d['sent_outreach']} outreach message(s) sent")
            if d.get("new_leads"):
                delta_lines.append(f"{d['new_leads']} new lead(s)")
            if d.get("new_conversations"):
                delta_lines.append(f"{d['new_conversations']} new conversation(s)")
            if d.get("completed_jobs"):
                delta_lines.append(f"{d['completed_jobs']} job(s) completed")
            if d.get("learned_preferences"):
                delta_lines.append(f"{d['learned_preferences']} new preference(s) learned")
            if d.get("new_insights"):
                delta_lines.append(f"{d['new_insights']} new insight(s)")
            if delta_lines:
                parts.append("")
                parts.append("WHAT CHANGED since last visit (in order of importance):")
                parts.extend(f"  - {line}" for line in delta_lines)
        else:
            parts.append("")
            parts.append("NOTHING CHANGED since the last visit. Keep the briefing brief.")

        # ── Work in progress (running research jobs) ──
        running = self.jobs.get("running") or []
        if running:
            parts.append("")
            parts.append("CURRENTLY WORKING:")
            for j in running[:2]:
                stage = j.get("stage", "in progress")
                q = j.get("query", "")
                parts.append(f"  - Research ({stage})" + (f" searching for '{q}'" if q else ""))
            parts.append("Mention that work is already underway — do not imply the workspace is idle.")

        # ── Priorities section (pre-ranked by reasoning layer) ──
        if self.priorities:
            parts.append("")
            parts.append("CAMPAIGN PRIORITIES (ranked by importance, 1 = highest):")
            for cp in self.priorities[:5]:
                label = cp.get("label", f"#{cp.get('rank', '?')}")
                name = cp.get("name", "?")
                status = cp.get("status", "")
                reasons = ", ".join(cp.get("reasons", []))
                parts.append(f"  {label}: {name} ({status}) — {reasons}")

        # ── Health section ──
        h = self.health_summary
        if h:
            parts.append("")
            parts.append("WORKSPACE HEALTH:")
            parts.append(f"  Overall: {h.get('overall_health', 'unknown')}")
            parts.append(f"  Pipeline: {h.get('pipeline_velocity', 'unknown').replace('_', ' ').title()}")
            if h.get("blocked_workflows"):
                parts.append(f"  Blocked: {', '.join(h['blocked_workflows'])}")
            parts.append(f"  Ready to launch: {h.get('campaigns_ready', 0)}")
            parts.append(f"  Waiting: {h.get('campaigns_waiting', 0)}")
            if h.get("draft_backlog", 0) > 0:
                parts.append(f"  Draft backlog: {h['draft_backlog']}")

        # ── Attention items (pre-ranked by reasoning layer) ──
        if self.attention_items:
            parts.append("")
            parts.append("ATTENTION ITEMS (highest priority first):")
            for a in self.attention_items[:4]:
                parts.append(f"  - {a.get('title', '')}: {a.get('reason', '')}")

        # ── Current focus ──
        cf = self.current_focus
        if cf:
            parts.append("")
            parts.append(f"CURRENT FOCUS: {cf.get('focus', 'unknown')}")

        # ── Insights ──
        if self.cross_campaign_insights:
            parts.append("")
            parts.append("CROSS-CAMPAIGN INSIGHTS:")
            for ins in self.cross_campaign_insights:
                parts.append(f"  - {ins.get('insight', '')}")

        # ── Recommendations (pre-ranked) ──
        if self.recommendations:
            parts.append("")
            parts.append("RECOMMENDED ACTIONS (in priority order):")
            for r in self.recommendations[:3]:
                confidence = r.get("confidence", "medium")
                parts.append(f"  - [{confidence}] {r.get('observation', '')}")

        # ── Recommendations from analysis ──
        rna = self.recommended_next_action
        if rna:
            parts.append("")
            parts.append(f"NEXT ACTION: {rna.get('title', '')} — {rna.get('reason', '')}")

        # ── Campaign details (for reference) ──
        if self.campaigns:
            parts.append("")
            parts.append("CAMPAIGNS:")
            for c in self.campaigns[:8]:
                parts.append(
                    f"  - {c.get('name', '?')}: {c.get('status', '?')} "
                    f"({c.get('pending_drafts', 0)} pending, {c.get('approved_drafts', 0)} approved)"
                )

        # ── Drafts summary ──
        if self.drafts:
            parts.append("")
            parts.append(
                f"DRAFTS: {self.drafts.get('total', 0)} total, "
                f"{self.drafts.get('pending', 0)} pending, "
                f"{self.drafts.get('approved', 0)} approved"
            )

        return "\n".join(parts)


# ── Narrative Engine ──


class NarrativeEngine:
    """Stateless natural-language engine for the Narrative Layer.

    Receives **structured**, **pre-ranked** data from the Reasoning Layer
    and produces natural-language output.  Never decides what is important —
    only how to communicate it.

    Design rules (from ARCHITECTURE_RFC §2.4):
    - Receives structured data only. Never reads the World Model directly.
    - Stateless. All state is in the World Model.
    - Cached by input hash. Same context → same output (for a given version).
    - Version-pinned. When the model improves, the version is bumped.
    """

    _VERSION = "1"

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def _cache_key(self, kind: str, context: BriefingContext) -> str:
        return f"{kind}:v{self._VERSION}:{hash(json.dumps(context.to_user_text(), default=str))}"

    # ── Briefing Writer ──

    def write_brief(self, context: BriefingContext) -> dict:
        """Generate the greeting + narrative lines + suggestion.

        Input: structured context with pre-ranked priorities, delta, health.
        Output: ``{greeting, lines: [str], suggestion: str}``.
        The Narrative Engine decides phrasing only — never what to include or prioritise.
        """
        ck = self._cache_key("brief", context)
        cached = self._cache.get(ck)
        if cached:
            return json.loads(cached)

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
            "- The 'WHAT CHANGED' section tells you what's new since the last visit — focus on it\n"
            "- The 'CAMPAIGN PRIORITIES' section is already ranked — follow the order given\n"
            "- The 'ATTENTION ITEMS' section tells you what needs the user's attention — highlight the top item\n"
            "- The 'NEXT ACTION' section tells you what the user should do next\n"
            "- Reference campaign names naturally\n"
            "- Never list raw statistics unless helpful\n"
            "- End with a recommendation — the single most important action\n"
            "- Never say 'Here's your status', 'Based on the data', 'There are', 'The workspace contains'\n"
            "- Never use bullet points or lists — write prose"
        )

        user_text = context.to_user_text() + "\n\nWrite a brief workspace summary."

        try:
            result = _send_openai_request(system_text, user_text)
            data = json.loads(result)
            brief = {
                "greeting": data.get("greeting", context.greeting),
                "lines": data.get("lines", []),
                "suggestion": data.get("suggestion", ""),
            }
            self._cache[ck] = json.dumps(brief)
            return brief
        except (OpenAIError, json.JSONDecodeError, KeyError) as e:
            return self._fallback_brief(context)

    def _fallback_brief(self, context: BriefingContext) -> dict:
        """Deterministic fallback when LLM is unavailable.

        Uses only the pre-ranked data from the reasoning layer — no business judgment.
        """
        lines = []

        if context.is_first_visit():
            if context.jobs.get("running"):
                lines.append("Welcome to Loqi. I've started researching prospects that match your profile, and I'll bring a shortlist back as soon as it's ready.")
            else:
                lines.append("Welcome to Loqi. I've been setting up your workspace.")
        elif not context.has_delta():
            lines.append("Nothing new since your last visit. Everything is running smoothly.")
        else:
            d = context.workspace_delta
            if d.get("new_drafts"):
                lines.append(f"I prepared {d['new_drafts']} new draft{'s' if d['new_drafts'] > 1 else ''} for your review.")
            if d.get("changed_campaigns"):
                n = d["changed_campaigns"]
                lines.append(f"{n} campaign{'s' if n > 1 else ''} changed status since you last checked.")
            if d.get("sent_outreach"):
                lines.append(f"I sent {d['sent_outreach']} outreach message{'s' if d['sent_outreach'] > 1 else ''}.")
            if d.get("new_leads"):
                lines.append(f"I discovered {d['new_leads']} new lead{'s' if d['new_leads'] > 1 else ''} matching your criteria.")
            if d.get("new_conversations"):
                lines.append(f"{d['new_conversations']} new conversation{'s' if d['new_conversations'] > 1 else ''} came in.")
            if d.get("completed_jobs"):
                lines.append(f"{d['completed_jobs']} research task{'s' if d['completed_jobs'] > 1 else ''} completed.")

        # Use the pre-ranked priority from the reasoning layer — no campaign-status re-derivation
        if context.attention_items:
            top = context.attention_items[0]
            lines.append(f"{top.get('title', 'The top item')} needs your attention.")
        elif context.priorities:
            top = context.priorities[0]
            lines.append(f"{top.get('name', 'Your top campaign')} is your highest priority.")

        if not lines:
            lines.append("Everything looks up to date.")

        suggestion = ""
        rna = context.recommended_next_action
        if rna:
            suggestion = rna.get("title", "")
        elif context.recommendations:
            suggestion = context.recommendations[0].get("action", "")

        return {"greeting": context.greeting, "lines": lines, "suggestion": suggestion}

    # ── Recommendation Writer ──

    def write_recommendations(self, context: BriefingContext) -> list[dict]:
        """Rephrase pre-ranked recommendations into natural language.

        The reasoning layer produces structured recommendations.
        This method only refines the wording — it never decides what to recommend.
        """
        if not context.recommendations:
            return self._fallback_recommendations(context)

        ck = self._cache_key("recs", context)
        cached = self._cache.get(ck)
        if cached:
            return json.loads(cached)

        recs_text = "\n".join(
            f"  - [{r.get('confidence', 'medium')}] {r.get('observation', '')} → {r.get('action', '')}"
            for r in context.recommendations[:3]
        )

        system_text = (
            "You are an advisor for an outbound sales platform.\n"
            "Refine the following recommendations into natural, specific language.\n"
            "Return a JSON array of objects with exactly these keys:\n"
            "observation, reason, action, confidence, type, link, why_details\n\n"
            "Rules:\n"
            "- Keep the same number of items (don't add or remove)\n"
            "- Keep the same confidence level and type\n"
            "- Improve the wording to sound more natural\n"
            "- Be specific about campaigns and actions"
        )

        user_text = (
            f"Current recommendations:\n{recs_text}\n\n"
            f"Campaigns:\n" + "\n".join(
                f"  - {c.get('name', '?')}: {c.get('status', '?')}"
                for c in context.campaigns[:8]
            ) + "\n\nRefine these recommendations."
        )

        try:
            result = _send_openai_request(system_text, user_text)
            data = json.loads(result)
            if not isinstance(data, list):
                data = [data]
            self._cache[ck] = json.dumps(data[:3])
            return data[:3]
        except (OpenAIError, json.JSONDecodeError, KeyError):
            return self._fallback_recommendations(context)

    def _fallback_recommendations(self, context: BriefingContext) -> list[dict]:
        """Return the recommendations as-is when LLM is unavailable."""
        return context.recommendations[:3] if context.recommendations else []

    # ── Insight Writer ──

    def write_insights(self, context: BriefingContext) -> list[str]:
        """Phrase cross-campaign insights into natural language."""
        insights = context.cross_campaign_insights
        if not insights:
            return []

        return [
            ins.get("insight", "")
            for ins in insights[:3]
        ]

    # ── Confidence Phraser ──

    def phrase_confidence(self, score: float) -> str:
        """Convert a numeric confidence score to natural language."""
        if score >= 90:
            return "I'm very confident"
        if score >= 75:
            return "I'd recommend"
        if score >= 60:
            return "This looks promising"
        if score >= 40:
            return "I'd like your opinion on this"
        return "I'm not certain, but"


_narrative_engine = NarrativeEngine()


def get_engine() -> NarrativeEngine:
    return _narrative_engine
