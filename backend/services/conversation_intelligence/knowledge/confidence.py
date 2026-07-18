"""Named confidence defaults.

No magic numbers in analyzers.
All numeric confidence values are defined here.
"""

# Entity extraction
PERSON_CONFIDENCE: float = 0.6
COMPANY_CONFIDENCE: float = 0.5
COMPANY_WITH_INDICATOR_CONFIDENCE: float = 0.7
TITLE_CONFIDENCE: float = 0.7
DECISION_MAKER_CONFIDENCE: float = 0.5
BUDGET_EXPLICIT_CONFIDENCE: float = 0.8
BUDGET_IMPLICIT_CONFIDENCE: float = 0.6
TIMELINE_DATE_CONFIDENCE: float = 0.7
TIMELINE_OTHER_CONFIDENCE: float = 0.5
MEETING_CONFIDENCE: float = 0.6
TECHNOLOGY_CONFIDENCE: float = 0.8
PRODUCT_CONFIDENCE: float = 0.6

# Objection detection
OBJECTION_EVIDENCE_BOOST: float = 0.05
OBJECTION_MAX_CONFIDENCE: float = 0.99

# Memory extraction
MEMORY_NAME_CONFIDENCE: float = 0.7
MEMORY_COMPANY_CONFIDENCE: float = 0.7
MEMORY_ROLE_CONFIDENCE: float = 0.6
MEMORY_BUDGET_CONFIDENCE: float = 0.8
MEMORY_NEED_CONFIDENCE: float = 0.6
MEMORY_ENTITY_MIN_CONFIDENCE: float = 0.6

# Buying signal
BUYING_SIGNAL_CONFIDENCE_DIVISOR: int = 100

# Scoring baselines
SCORING_BASELINE: int = 50
SCORING_MAX: int = 100
SCORING_MIN: int = 0

# Engagement scoring
ENGAGEMENT_POSITIVE_LABELS: set[str] = {
    "interested", "meeting_request", "demo_request", "referral", "follow_up",
}
ENGAGEMENT_NEGATIVE_LABELS: set[str] = {
    "not_interested",
}

# Reasoning thresholds
HEALTH_STRONG_THRESHOLD: int = 70
HEALTH_MODERATE_THRESHOLD: int = 50
HEALTH_ATTENTION_THRESHOLD: int = 30

# Evidence boost per additional match
COMPANY_CONFIDENCE_BOOST_PER_WORD: float = 0.1
COMPANY_MAX_CONFIDENCE: float = 0.9
