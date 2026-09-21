"""Structured draft comparison between versions.

Supports comparing current vs previous version and producing
a categorized diff (added, removed, changed, improved, regressed).
"""

import difflib
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComparisonItem:
    category: str  # "added", "removed", "changed", "improved", "regression"
    description: str


@dataclass
class ComparisonResult:
    improvements: list[ComparisonItem]
    regressions: list[ComparisonItem]
    added: list[str]
    removed: list[str]
    length_change_pct: int

    def to_dict(self) -> dict:
        return {
            "improvements": [{"category": i.category, "description": i.description} for i in self.improvements],
            "regressions": [{"category": i.category, "description": i.description} for i in self.regressions],
            "added": self.added,
            "removed": self.removed,
            "length_change_pct": self.length_change_pct,
        }

    def natural_summary(self) -> str:
        """Return a short natural-language summary of what changed."""
        parts = []
        if self.improvements:
            items = [i.description for i in self.improvements[:3]]
            parts.append("Improved: " + "; ".join(items))
        if self.regressions:
            items = [i.description for i in self.regressions[:2]]
            parts.append("Potential regression: " + "; ".join(items))
        if self.length_change_pct:
            direction = "reduced" if self.length_change_pct < 0 else "increased"
            parts.append(f"Length {direction} by {abs(self.length_change_pct)}%")
        return " | ".join(parts)


def compare_versions(old_text: str, new_text: str, change_summary: list[str] | None = None) -> ComparisonResult:
    """Compare two draft versions and produce a structured comparison.

    Args:
        old_text: The previous version of the draft.
        new_text: The current version of the draft.
        change_summary: Optional list of change descriptions from the rewrite engine.

    Returns:
        ComparisonResult with categorized changes.
    """
    improvements: list[ComparisonItem] = []
    regressions: list[ComparisonItem] = []

    if change_summary:
        for change in change_summary:
            lower = change.lower().lstrip("✓-* ").strip()
            if any(neg in lower for neg in ["lost", "removed", "removed personalization", "weaker", "less personal"]):
                regressions.append(ComparisonItem("regression", change))
            else:
                improvements.append(ComparisonItem("improved", change))

    old_sentences = _split_sentences(old_text)
    new_sentences = _split_sentences(new_text)

    added = [s for s in new_sentences if s not in old_sentences]
    removed = [s for s in old_sentences if s not in new_sentences]

    old_len = len(old_text.split())
    new_len = len(new_text.split())
    length_change_pct = round(((new_len - old_len) / max(old_len, 1)) * 100)

    return ComparisonResult(
        improvements=improvements,
        regressions=regressions,
        added=added,
        removed=removed,
        length_change_pct=length_change_pct,
    )


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, preserving the sentence text."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]
