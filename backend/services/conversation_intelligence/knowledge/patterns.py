"""Generic extraction regex patterns (people, products, needs).

No extraction logic. Data only.
"""

PERSON_PATTERNS: list[str] = [
    r"(?:from|contact|introduce|meet)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",
    r"([A-Z][a-z]+),?\s+(?:here|writing|emailing)",
]

PERSON_SELF_IDENTIFICATION: list[str] = [
    r"(?:I'm|I am|my name is|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",
]

PRODUCT_PATTERNS: list[tuple[str, str]] = [
    (r"(?:your|the)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:platform|product|tool|software|solution)", "product"),
]

NEED_PATTERNS: list[tuple[str, float]] = [
    (r"(?:looking for|need|needs|want|wants|interested in)\s+(.+?)(?:\.|,|$)", 0.6),
    (r"(?:trying to|looking to|hoping to)\s+(\w+\s+\w+)", 0.5),
]
