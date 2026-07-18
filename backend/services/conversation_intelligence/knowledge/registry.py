"""Central Knowledge Registry.

All reasoning engines depend only on this registry.
Knowledge sources can be externalized (YAML/JSON/DB) later
without changing any analyzer implementation.

Usage:
    from services.conversation_intelligence.knowledge.registry import KnowledgeRegistry

    registry = KnowledgeRegistry()
    titles = registry.get_decision_maker_titles()
    technologies = registry.get_technologies()
    objections = registry.get_objection_definitions()
"""

from __future__ import annotations
from typing import Optional

from services.conversation_intelligence.knowledge import titles as _titles
from services.conversation_intelligence.knowledge import technologies as _technologies
from services.conversation_intelligence.knowledge import companies as _companies
from services.conversation_intelligence.knowledge import budgets as _budgets
from services.conversation_intelligence.knowledge import timelines as _timelines
from services.conversation_intelligence.knowledge import meeting_patterns as _meeting_patterns
from services.conversation_intelligence.knowledge import patterns as _patterns
from services.conversation_intelligence.knowledge import buying_signals as _buying_signals
from services.conversation_intelligence.knowledge import objections as _objections
from services.conversation_intelligence.knowledge import confidence as _confidence
from services.conversation_intelligence.knowledge import scoring_config as _scoring_config


class KnowledgeRegistry:
    """Central registry exposing all business knowledge to reasoning engines."""

    # ── Titles ──────────────────────────────────────────────────────────

    def get_decision_maker_titles(self) -> list[str]:
        return list(_titles.DECISION_MAKER_TITLES)

    def get_title_normalization_map(self) -> dict[str, str]:
        return dict(_titles.TITLE_NORMALIZATIONS)

    def is_decision_maker_title(self, text: str) -> bool:
        return text.lower().strip() in _titles.DECISION_MAKER_TITLES

    # ── Technologies ────────────────────────────────────────────────────

    def get_technologies(self, category: Optional[str] = None) -> list[str]:
        if category:
            return list(_technologies.TECHNOLOGIES.get(category, []))
        return list(_technologies.ALL_TECHNOLOGIES)

    def get_technologies_by_category(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in _technologies.TECHNOLOGIES.items()}

    def get_technology_normalization_map(self) -> dict[str, str]:
        return dict(_technologies.TECHNOLOGY_NORMALIZATIONS)

    # ── Companies ───────────────────────────────────────────────────────

    def get_company_indicators(self) -> list[str]:
        return list(_companies.COMPANY_INDICATORS)

    def get_company_patterns(self) -> list[tuple[str, float]]:
        return list(_companies.COMPANY_PATTERNS)

    def get_company_indicator_exceptions(self) -> list[str]:
        return list(_companies.COMPANY_INDICATOR_EXCEPTIONS)

    def is_company_indicator(self, word: str) -> bool:
        return word.lower().strip() in _companies.COMPANY_INDICATORS

    # ── Budgets ─────────────────────────────────────────────────────────

    def get_budget_patterns(self) -> list[tuple[str, str]]:
        return list(_budgets.BUDGET_PATTERNS)

    def get_budget_keywords(self) -> list[str]:
        return list(_budgets.BUDGET_KEYWORDS)

    # ── Timelines ───────────────────────────────────────────────────────

    def get_timeline_patterns(self) -> list[tuple[str, str]]:
        return list(_timelines.TIMELINE_PATTERNS)

    def get_timeline_keywords(self) -> list[str]:
        return list(_timelines.TIMELINE_KEYWORDS)

    # ── Meeting Patterns ────────────────────────────────────────────────

    def get_meeting_patterns(self) -> list[tuple[str, str]]:
        return list(_meeting_patterns.MEETING_PATTERNS)

    def get_meeting_keywords(self) -> list[str]:
        return list(_meeting_patterns.MEETING_KEYWORDS)

    # ── Generic Patterns ────────────────────────────────────────────────

    def get_person_patterns(self) -> list[str]:
        return list(_patterns.PERSON_PATTERNS)

    def get_person_self_identification_patterns(self) -> list[str]:
        return list(_patterns.PERSON_SELF_IDENTIFICATION)

    def get_product_patterns(self) -> list[tuple[str, str]]:
        return list(_patterns.PRODUCT_PATTERNS)

    def get_need_patterns(self) -> list[tuple[str, float]]:
        return list(_patterns.NEED_PATTERNS)

    # ── Buying Signals ──────────────────────────────────────────────────

    def get_buying_signal_definitions(self) -> list[dict]:
        return list(_buying_signals.BUYING_SIGNAL_DEFINITIONS)

    def get_buying_signal_names(self) -> list[str]:
        return [s["name"] for s in _buying_signals.BUYING_SIGNAL_DEFINITIONS]

    def get_buying_signal_keywords(self) -> list[str]:
        keywords = []
        for s in _buying_signals.BUYING_SIGNAL_DEFINITIONS:
            keywords.extend(s["keywords"])
        return keywords

    # ── Objections ──────────────────────────────────────────────────────

    def get_objection_definitions(self) -> list[dict]:
        return list(_objections.OBJECTION_DEFINITIONS)

    def get_objection_categories(self) -> list[str]:
        return [o["category"].value for o in _objections.OBJECTION_DEFINITIONS]

    def get_objection_keywords(self) -> list[str]:
        keywords = []
        for o in _objections.OBJECTION_DEFINITIONS:
            keywords.extend(o["keywords"])
        return keywords

    # ── Confidence ──────────────────────────────────────────────────────

    def get_confidence(self, name: str) -> float:
        return getattr(_confidence, name, 0.5)

    def get_all_confidences(self) -> dict[str, float]:
        return {
            k: v for k, v in vars(_confidence).items()
            if k.isupper() and isinstance(v, (int, float))
        }

    # ── Scoring ─────────────────────────────────────────────────────────

    def get_scoring_weights(self) -> dict[str, int]:
        return dict(_scoring_config.DEFAULT_SCORING_WEIGHTS)

    def get_strength_scores(self) -> dict[str, float]:
        return dict(_scoring_config.STRENGTH_SCORES)

    def get_severity_penalties(self) -> dict[str, float]:
        return dict(_scoring_config.SEVERITY_PENALTIES)


# Module-level singleton for convenience
_default_registry: Optional[KnowledgeRegistry] = None


def get_registry() -> KnowledgeRegistry:
    """Get the shared KnowledgeRegistry instance."""
    global _default_registry
    if _default_registry is None:
        _default_registry = KnowledgeRegistry()
    return _default_registry
