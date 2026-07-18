"""Reusable normalization utilities for entity values.

Normalizes titles, technologies, company suffixes, and entity labels.
These functions contain only normalization logic — no extraction.
"""

from __future__ import annotations
from services.conversation_intelligence.knowledge.titles import TITLE_NORMALIZATIONS
from services.conversation_intelligence.knowledge.technologies import TECHNOLOGY_NORMALIZATIONS
from services.conversation_intelligence.knowledge.companies import COMPANY_INDICATORS


def normalize_title(title: str) -> str:
    """Normalize a job title to its canonical form."""
    key = title.strip().lower()
    return TITLE_NORMALIZATIONS.get(key, title)


def normalize_technology(tech: str) -> str:
    """Normalize a technology name to its canonical form."""
    key = tech.strip().lower()
    return TECHNOLOGY_NORMALIZATIONS.get(key, tech)


def normalize_company_suffix(name: str) -> str:
    """Strip or standardize company suffix (Inc, Corp, LLC, etc.)."""
    lower = name.lower().strip()
    for indicator in COMPANY_INDICATORS:
        if lower.endswith(indicator):
            prefix = name[:-(len(indicator))].strip()
            return f"{prefix} {indicator.title()}"
    return name


def normalize_budget_value(raw: str) -> str:
    """Normalize a budget value string (e.g., '$50k' -> '50000')."""
    cleaned = raw.lower().replace("$", "").replace(",", "").strip()
    if cleaned.endswith("k") or cleaned.endswith("k"):
        num = cleaned.rstrip("k")
        try:
            return str(int(float(num) * 1000))
        except ValueError:
            return raw
    if cleaned.endswith("m") or cleaned.endswith("m"):
        num = cleaned.rstrip("m")
        try:
            return str(int(float(num) * 1000000))
        except ValueError:
            return raw
    return raw


def normalize_entity_type_label(label: str) -> str:
    """Normalize an entity type label for display."""
    return label.replace("_", " ").title()
