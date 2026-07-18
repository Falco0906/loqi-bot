"""Meeting-related regex patterns.

No extraction logic. Data only.
"""

MEETING_PATTERNS: list[tuple[str, str]] = [
    (r"(?:schedule|book|set up|meet on|meeting on)\s+(.+?)(?:\.|\,|$)", "meeting"),
    (r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)", "day"),
    (r"(?:next|this)\s+(?:monday|tuesday|wednesday|thursday|friday)", "relative_day"),
]

MEETING_KEYWORDS: list[str] = [
    "meeting", "schedule", "book a call", "talk", "discuss further",
    "demo", "demonstration", "show me", "walk me through",
]
