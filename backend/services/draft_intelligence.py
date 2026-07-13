"""Structured draft intelligence engine.

Analyzes cold outreach drafts across multiple quality dimensions
and detects sales-specific patterns, producing actionable coaching feedback.

Extension points for Buyer Psychology (Phase 3.3.3B):
- BUYER_PERSONA_HOOKS: pluggable list of persona-specific evaluators
- INDUSTRY_PLAYBOOK_HOOKS: pluggable list of industry-specific evaluators
- MESSAGING_FRAMEWORK_HOOKS: pluggable list of framework-specific evaluators

All hooks are automatically wired on import.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from services.ai import _send_openai_request, OpenAIError


# ── Human-friendly score labels ──────────────────────────────────────────

SCORE_THRESHOLDS = [
    (9, "Excellent"),
    (7, "Strong"),
    (5, "Fair"),
    (3, "Weak"),
    (0, "Critical"),
]


def score_label(score: int) -> str:
    """Convert a numeric score to a human-friendly label."""
    for threshold, label in SCORE_THRESHOLDS:
        if score >= threshold:
            return label
    return "Critical"


def score_to_phrase(category: str, score: int, improvement: str) -> str:
    """Convert a score+improvement pair into a natural coaching phrase.

    Example: cta_strength, 6, "Make it more specific" →
        "Your CTA is fair. Make it more specific."
    """
    display_name = category.replace("_", " ").title()
    label = score_label(score)
    if label == "Excellent":
        return f"Your {display_name} is excellent."
    if label == "Strong":
        return f"Your {display_name} is strong."
    if label == "Fair":
        return f"Your {display_name} is fair — {improvement}"
    if label == "Weak":
        return f"Your {display_name} is weak. {improvement}"
    return f"Your {display_name} needs significant work. {improvement}"


# ── Extension points for Buyer Psychology (Phase 3.3.3B) ─────────────────

BUYER_PERSONA_HOOKS: list[Callable[[str, dict | None], dict | None]] = []
INDUSTRY_PLAYBOOK_HOOKS: list[Callable[[str, dict | None], dict | None]] = []
MESSAGING_FRAMEWORK_HOOKS: list[Callable[[str, dict | None], dict | None]] = []


def register_buyer_persona_hook(hook: Callable[[str, dict | None], dict | None]) -> None:
    """Register a buyer persona evaluator.

    The hook receives (draft_text, context) and should return a dict with
    persona-specific analysis or None. The returned dict can contain any keys
    and will be merged into the DraftIntelligence result under `persona_analysis`.
    """
    BUYER_PERSONA_HOOKS.append(hook)


def register_industry_playbook_hook(hook: Callable[[str, dict | None], dict | None]) -> None:
    """Register an industry playbook evaluator."""
    INDUSTRY_PLAYBOOK_HOOKS.append(hook)


def register_messaging_framework_hook(hook: Callable[[str, dict | None], dict | None]) -> None:
    """Register a messaging framework evaluator."""
    MESSAGING_FRAMEWORK_HOOKS.append(hook)


# ── Data classes ─────────────────────────────────────────────────────────

@dataclass
class DraftIntelligenceCategory:
    score: int
    reason: str
    improvement: str

    @property
    def label(self) -> str:
        return score_label(self.score)

    def to_phrase(self, category: str) -> str:
        return score_to_phrase(category, self.score, self.improvement)


@dataclass
class DraftIntelligence:
    opening_strength: DraftIntelligenceCategory
    personalization_quality: DraftIntelligenceCategory
    pain_alignment: DraftIntelligenceCategory
    relevance: DraftIntelligenceCategory
    credibility: DraftIntelligenceCategory
    cta_strength: DraftIntelligenceCategory
    readability: DraftIntelligenceCategory
    length: DraftIntelligenceCategory
    tone: DraftIntelligenceCategory
    confidence: DraftIntelligenceCategory

    patterns: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)

    persona_analysis: dict | None = None
    persona: dict | None = None
    company_context: dict | None = None
    messaging_strategy: dict | None = None
    cta_recommendation: dict | None = None
    objection_predictions: list[dict] | None = None
    trust_suggestions: list[dict] | None = None
    framework_recommendation: dict | None = None

    def to_dict(self) -> dict:
        result = {
            "opening_strength": {"score": self.opening_strength.score, "label": self.opening_strength.label, "reason": self.opening_strength.reason, "improvement": self.opening_strength.improvement},
            "personalization_quality": {"score": self.personalization_quality.score, "label": self.personalization_quality.label, "reason": self.personalization_quality.reason, "improvement": self.personalization_quality.improvement},
            "pain_alignment": {"score": self.pain_alignment.score, "label": self.pain_alignment.label, "reason": self.pain_alignment.reason, "improvement": self.pain_alignment.improvement},
            "relevance": {"score": self.relevance.score, "label": self.relevance.label, "reason": self.relevance.reason, "improvement": self.relevance.improvement},
            "credibility": {"score": self.credibility.score, "label": self.credibility.label, "reason": self.credibility.reason, "improvement": self.credibility.improvement},
            "cta_strength": {"score": self.cta_strength.score, "label": self.cta_strength.label, "reason": self.cta_strength.reason, "improvement": self.cta_strength.improvement},
            "readability": {"score": self.readability.score, "label": self.readability.label, "reason": self.readability.reason, "improvement": self.readability.improvement},
            "length": {"score": self.length.score, "label": self.length.label, "reason": self.length.reason, "improvement": self.length.improvement},
            "tone": {"score": self.tone.score, "label": self.tone.label, "reason": self.tone.reason, "improvement": self.tone.improvement},
            "confidence": {"score": self.confidence.score, "label": self.confidence.label, "reason": self.confidence.reason, "improvement": self.confidence.improvement},
            "patterns": self.patterns,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "opportunities": self.opportunities,
        }
        for key in ("persona", "company_context", "messaging_strategy", "cta_recommendation", "objection_predictions", "trust_suggestions", "framework_recommendation", "persona_analysis"):
            val = getattr(self, key, None)
            if val:
                result[key] = val
        return result

    def natural_summary(self) -> str:
        """Return a natural-language summary of the draft's strengths and weaknesses."""
        parts = []
        if self.strengths:
            parts.append("Strengths: " + "; ".join(self.strengths[:3]))
        if self.weaknesses:
            parts.append("Weaknesses: " + "; ".join(self.weaknesses[:3]))
        if self.opportunities:
            parts.append("Opportunities: " + "; ".join(self.opportunities[:3]))
        return " | ".join(parts)


_DETECTABLE_PATTERNS = [
    "Too generic",
    "Too long",
    "Weak opening",
    "Weak CTA",
    "Not enough personalization",
    "Talking too much about ourselves",
    "Talking too much about features",
    "Not enough about business outcomes",
    "No proof",
    "No credibility",
    "Too formal",
    "Too casual",
    "Reads like AI",
    "Feels salesy",
    "Feels repetitive",
    "No clear problem statement",
    "Weak transition",
    "Multiple CTAs",
    "Missing curiosity",
]


def _build_context_block(context: dict | None) -> str:
    if not context:
        return ""
    parts = []
    for key, label in [
        ("company", "Target company"),
        ("contact", "Contact name"),
        ("role", "Contact role"),
        ("industry", "Industry"),
        ("campaign_name", "Campaign"),
        ("messaging_angle", "Messaging angle"),
        ("business_summary", "Business summary"),
    ]:
        val = context.get(key)
        if val:
            parts.append(f"{label}: {val}")
    return "\n".join(parts) + "\n\n" if parts else ""


def analyze_draft(draft_text: str, context: dict | None = None) -> DraftIntelligence:
    """Analyze a draft and return structured intelligence across all dimensions.

    Uses the LLM to evaluate every category and detect patterns,
    then returns a DraftIntelligence dataclass.
    """
    context_block = _build_context_block(context)

    categories_json = json.dumps([
        "opening_strength",
        "personalization_quality",
        "pain_alignment",
        "relevance",
        "credibility",
        "cta_strength",
        "readability",
        "length",
        "tone",
        "confidence",
    ])

    patterns_json = json.dumps(_DETECTABLE_PATTERNS)

    system_text = (
        "You are a senior B2B outbound sales coach. Analyze the cold outreach draft "
        "across these categories and return a structured JSON analysis.\n\n"
        "For each category, provide:\n"
        '- score (0-10 integer, 10 being best)\n'
        '- reason (1-2 sentence explanation of the score)\n'
        '- improvement (1-2 sentence actionable suggestion)\n\n'
        f"Categories: {categories_json}\n\n"
        "Then detect which of these sales patterns apply (list only the ones that apply, "
        "or an empty array if none):\n"
        f"{patterns_json}\n\n"
        "Then list:\n"
        '- "strengths": top 2-3 strong points about the draft (short phrases)\n'
        '- "weaknesses": top 2-3 weak points about the draft (short phrases)\n'
        '- "opportunities": top 2-3 specific improvement opportunities (short phrases)\n\n'
        "Return ONLY valid JSON with this exact structure:\n"
        "{\n"
        '  "opening_strength": {"score": 0, "reason": "...", "improvement": "..."},\n'
        '  "personalization_quality": {"score": 0, "reason": "...", "improvement": "..."},\n'
        '  "pain_alignment": {"score": 0, "reason": "...", "improvement": "..."},\n'
        '  "relevance": {"score": 0, "reason": "...", "improvement": "..."},\n'
        '  "credibility": {"score": 0, "reason": "...", "improvement": "..."},\n'
        '  "cta_strength": {"score": 0, "reason": "...", "improvement": "..."},\n'
        '  "readability": {"score": 0, "reason": "...", "improvement": "..."},\n'
        '  "length": {"score": 0, "reason": "...", "improvement": "..."},\n'
        '  "tone": {"score": 0, "reason": "...", "improvement": "..."},\n'
        '  "confidence": {"score": 0, "reason": "...", "improvement": "..."},\n'
        '  "patterns": ["pattern1", "pattern2"],\n'
        '  "strengths": ["strength1", "strength2"],\n'
        '  "weaknesses": ["weakness1", "weakness2"],\n'
        '  "opportunities": ["opportunity1", "opportunity2"]\n'
        "}\n\n"
        "No markdown, no explanation outside JSON."
    )

    user_text = (
        f"{context_block}"
        f"Draft to analyze:\n\n{draft_text}\n\n"
        "Provide the structured JSON analysis."
    )

    try:
        result = _send_openai_request(system_text, user_text)
        data = json.loads(result)
    except (OpenAIError, json.JSONDecodeError) as e:
        raise OpenAIError(f"Draft intelligence analysis failed: {e}")

    def _cat(key: str) -> DraftIntelligenceCategory:
        entry = data.get(key, {})
        return DraftIntelligenceCategory(
            score=entry.get("score", 5),
            reason=entry.get("reason", ""),
            improvement=entry.get("improvement", ""),
        )

    strategic = analyze_strategic(draft_text, context)

    return DraftIntelligence(
        opening_strength=_cat("opening_strength"),
        personalization_quality=_cat("personalization_quality"),
        pain_alignment=_cat("pain_alignment"),
        relevance=_cat("relevance"),
        credibility=_cat("credibility"),
        cta_strength=_cat("cta_strength"),
        readability=_cat("readability"),
        length=_cat("length"),
        tone=_cat("tone"),
        confidence=_cat("confidence"),
        patterns=data.get("patterns", []),
        strengths=data.get("strengths", []),
        weaknesses=data.get("weaknesses", []),
        opportunities=data.get("opportunities", []),
        persona=strategic.get("persona"),
        company_context=strategic.get("company_context"),
        messaging_strategy=strategic.get("messaging_strategy"),
        cta_recommendation=strategic.get("cta_recommendation"),
        objection_predictions=strategic.get("objection_predictions"),
        trust_suggestions=strategic.get("trust_suggestions"),
        framework_recommendation=strategic.get("framework_recommendation"),
        persona_analysis=strategic.get("persona_analysis"),
    )


def analyze_strategic(
    draft_text: str,
    context: dict | None = None,
    buyer_persona: dict | None = None,
    company_context: dict | None = None,
) -> dict:
    """Run all registered buyer psychology hooks and return combined strategic analysis.

    This function is called during draft analysis to enrich the DraftIntelligence
    with strategic insights from the Buyer Psychology services.

    Returns a dict with keys matching the DraftIntelligence strategic fields.
    """
    result: dict[str, Any] = {}

    for hook in BUYER_PERSONA_HOOKS:
        try:
            r = hook(draft_text, context)
            if r:
                for key, val in r.items():
                    if val:
                        result[key] = val
        except Exception:
            pass

    for hook in INDUSTRY_PLAYBOOK_HOOKS:
        try:
            r = hook(draft_text, context)
            if r:
                for key, val in r.items():
                    if val:
                        result.setdefault(key, val)
        except Exception:
            pass

    for hook in MESSAGING_FRAMEWORK_HOOKS:
        try:
            r = hook(draft_text, context)
            if r:
                for key, val in r.items():
                    if val:
                        result.setdefault(key, val)
        except Exception:
            pass

    return result


# ── Auto-wire buyer psychology services on import ─────────────────────────

def _wire_buyer_psychology() -> None:
    """Register buyer psychology services as hooks.

    Called on import to wire the modular services into the
    Draft Intelligence analysis pipeline.
    """
    from services.buyer_psychology import analyze_buyer
    from services.company_context import analyze_company
    from services.messaging_strategy import select_strategy
    from services.objection_predictor import predict_objections
    from services.trust_builder import suggest_trust_builders
    from services.cta_strategy import recommend_cta
    from services.framework_selector import select_framework

    def persona_hook(draft_text: str, context: dict | None) -> dict | None:
        persona = analyze_buyer(context)
        cc = analyze_company(context)
        strategy = select_strategy(persona.to_dict(), cc.to_dict(), context)
        cta = recommend_cta(persona.to_dict(), cc.to_dict(), context)
        objections = predict_objections(persona.to_dict(), cc.to_dict(), context)
        trust = suggest_trust_builders(draft_text, persona.to_dict(), cc.to_dict(), context)
        framework = select_framework(persona.to_dict(), cc.to_dict(), context)

        result = {
            "persona": persona.to_dict(),
            "company_context": cc.to_dict(),
            "messaging_strategy": strategy.to_dict(),
            "cta_recommendation": cta.to_dict(),
            "objection_predictions": [o.to_dict() for o in objections],
            "trust_suggestions": [t.to_dict() for t in trust],
            "framework_recommendation": framework.to_dict(),
        }
        return result

    register_buyer_persona_hook(persona_hook)


_wire_buyer_psychology()
