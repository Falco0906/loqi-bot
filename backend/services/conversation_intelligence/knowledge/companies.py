"""Company-related patterns and indicators.

No extraction logic. Data only.
"""

COMPANY_INDICATORS: list[str] = [
    "inc", "corp", "llc", "ltd", "gmbh", "saas",
    "technologies", "solutions", "software", "systems",
    "group", "holdings", "partners", "ventures",
    "limited", "corporation", "incorporated",
]

COMPANY_PATTERNS: list[tuple[str, float]] = [
    (r"(?:at|for|with|from)\s+([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){1,3})", 0.5),
    (r"([A-Z][A-Za-z0-9]+(?:[\s\-][A-Z][A-Za-z0-9]+)*\s+(?:Inc|Corp|LLC|Ltd|Gmbh))", 0.7),
    (r"([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*\s+(?:Technologies|Solutions|Software))", 0.6),
]

COMPANY_INDICATOR_EXCEPTIONS: list[str] = [
    "the", "a ", "an ", "my ", "our ", "your ",
]
