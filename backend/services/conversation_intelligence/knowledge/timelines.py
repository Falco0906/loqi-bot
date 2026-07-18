"""Timeline and date-related regex patterns.

No extraction logic. Data only.
"""

TIMELINE_PATTERNS: list[tuple[str, str]] = [
    (r"(?:by|before|within)\s+(\w+\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?)", "date"),
    (r"(?:next|this|following)\s+(week|month|quarter|year)", "relative"),
    (r"(?:in|within)\s+(\d+\s*(?:weeks?|months?|days?))", "duration"),
    (r"(\d{1,2})[\/-](\d{1,2})[\/-](\d{2,4})", "date"),
    (r"(Q[1-4])\s*(?:\d{4})?", "quarter"),
]

TIMELINE_KEYWORDS: list[str] = [
    "timeline", "when", "by when", "deadline", "target date",
    "expected by", "need it by", "by next", "timeframe",
]
