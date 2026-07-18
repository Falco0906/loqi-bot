"""Budget-related regex patterns and metadata.

No extraction logic. Data only.
"""

BUDGET_PATTERNS: list[tuple[str, str]] = [
    (r"\$(\d+[kK])\s*(?:-|to)\s*\$?(\d+[kK])", "range"),
    (r"\$(\d+[kK])", "single"),
    (r"(\d+)\s*(?:k|thousand)\s*(?:-|to)\s*(\d+)\s*(?:k|thousand)", "range"),
    (r"budget\s*(?:of|is|:)\s*\$?(\d+[kKmbMB])", "explicit"),
    (r"under\s*\$?(\d+[kK])", "under"),
    (r"up to\s*\$?(\d+[kK])", "up_to"),
]

BUDGET_KEYWORDS: list[str] = [
    "budget", "cost", "expensive", "spend", "roi",
    "value", "worth it", "investment", "afford",
    "pricing", "price", "how much", "quote",
]
