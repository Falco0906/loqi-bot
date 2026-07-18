"""Objection definitions with category, keywords, severity, and base confidence.

No extraction logic. Data only.
"""

from services.conversation_intelligence.intelligence_models import ObjectionCategory, ObjectionSeverity


OBJECTION_DEFINITIONS: list[dict] = [
    {
        "category": ObjectionCategory.PRICE,
        "keywords": [
            "too expensive", "too costly", "can't afford", "overpriced",
            "price is high", "cost is high", "expensive", "pricey",
            "beyond our budget", "out of our price range", "costly",
            "pricing is steep", "more than we expected",
        ],
        "severity": ObjectionSeverity.HIGH,
        "base_confidence": 0.85,
    },
    {
        "category": ObjectionCategory.TIMING,
        "keywords": [
            "not the right time", "too busy", "other priorities",
            "not now", "later", "next quarter", "next year",
            "too soon", "bad timing", "not a priority right now",
            "we're focused on", "currently focused on",
        ],
        "severity": ObjectionSeverity.MEDIUM,
        "base_confidence": 0.8,
    },
    {
        "category": ObjectionCategory.FEATURE_GAP,
        "keywords": [
            "doesn't have", "missing", "needs", "required",
            "doesn't support", "can't do", "not able to",
            "feature gap", "lacks", "would need", "if only it had",
            "does it do", "can it handle",
        ],
        "severity": ObjectionSeverity.MEDIUM,
        "base_confidence": 0.7,
    },
    {
        "category": ObjectionCategory.COMPETITION,
        "keywords": [
            "already use", "using another", "happy with",
            "satisfied with", "sticking with", "staying with",
            "competitor", "compared to", "versus", "alternative",
            "similar to", "using x instead",
        ],
        "severity": ObjectionSeverity.MEDIUM,
        "base_confidence": 0.75,
    },
    {
        "category": ObjectionCategory.SECURITY,
        "keywords": [
            "security concern", "data privacy", "data security",
            "security review", "security team", "infosec",
            "vulnerability", "breach", "encryption", "sso",
            "security compliance", "security audit",
        ],
        "severity": ObjectionSeverity.HIGH,
        "base_confidence": 0.8,
    },
    {
        "category": ObjectionCategory.COMPLIANCE,
        "keywords": [
            "compliance", "gdpr", "soc2", "hipaa", "pci",
            "regulation", "regulatory", "legal review",
            "legal team", "data protection", "privacy law",
        ],
        "severity": ObjectionSeverity.HIGH,
        "base_confidence": 0.85,
    },
    {
        "category": ObjectionCategory.INTERNAL_APPROVAL,
        "keywords": [
            "need to check", "talk to my team", "discuss with",
            "need approval", "run it by", "check with",
            "need to discuss", "team decision", "board approval",
            "multiple stakeholders", "buying committee",
        ],
        "severity": ObjectionSeverity.LOW,
        "base_confidence": 0.7,
    },
    {
        "category": ObjectionCategory.BUDGET,
        "keywords": [
            "budget", "no budget", "budget freeze", "budget cut",
            "budget approval", "budget planning", "fiscal year",
            "budget cycle", "allocated", "spending freeze",
            "tight budget", "limited budget",
        ],
        "severity": ObjectionSeverity.HIGH,
        "base_confidence": 0.8,
    },
    {
        "category": ObjectionCategory.EXISTING_VENDOR,
        "keywords": [
            "under contract", "existing vendor", "current provider",
            "contracted", "locked in", "multi-year deal",
            "just renewed", "signed with", "committed to",
            "in the middle of", "long-term relationship",
        ],
        "severity": ObjectionSeverity.MEDIUM,
        "base_confidence": 0.8,
    },
    {
        "category": ObjectionCategory.IMPLEMENTATION,
        "keywords": [
            "too complex", "too much work", "too disruptive",
            "implementation", "migration", "onboarding",
            "learning curve", "setup time", "too difficult",
            "resource intensive",
        ],
        "severity": ObjectionSeverity.MEDIUM,
        "base_confidence": 0.7,
    },
]
