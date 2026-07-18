"""Buying signal definitions with keywords, strength, and base confidence.

No extraction logic. Data only.
"""

from services.conversation_models import SignalStrength


BUYING_SIGNAL_DEFINITIONS: list[dict] = [
    {
        "name": "asked_for_pricing",
        "keywords": ["pricing", "price", "cost", "how much", "quote", "subscription plan"],
        "strength": SignalStrength.VERY_STRONG,
        "reason": "Direct pricing inquiry — strong purchase intent",
        "base_confidence": 95,
    },
    {
        "name": "requested_demo",
        "keywords": ["demo", "demonstration", "show me", "walk me through", "see it in action"],
        "strength": SignalStrength.VERY_STRONG,
        "reason": "Demo request — active evaluation",
        "base_confidence": 95,
    },
    {
        "name": "requested_meeting",
        "keywords": ["meeting", "schedule", "book a call", "talk", "discuss further"],
        "strength": SignalStrength.STRONG,
        "reason": "Meeting request — serious engagement",
        "base_confidence": 85,
    },
    {
        "name": "asked_implementation_timeline",
        "keywords": ["implement", "roll out", "how long", "timeframe", "setup time",
                      "deploy", "onboarding", "migration", "time to"],
        "strength": SignalStrength.STRONG,
        "reason": "Implementation timeline question — active planning",
        "base_confidence": 80,
    },
    {
        "name": "asked_integration_questions",
        "keywords": ["integration", "api", "connect", "import", "export",
                      "compatible with", "works with", "integrate"],
        "strength": SignalStrength.STRONG,
        "reason": "Integration questions — technical evaluation underway",
        "base_confidence": 80,
    },
    {
        "name": "mentioned_budget",
        "keywords": ["budget", "cost", "expensive", "spend", "roi", "value",
                      "worth it", "investment", "afford"],
        "strength": SignalStrength.VERY_STRONG,
        "reason": "Budget discussion — serious consideration",
        "base_confidence": 90,
    },
    {
        "name": "mentioned_current_vendor",
        "keywords": ["currently using", "current vendor", "we use", "switching from",
                      "migrating from", "replacing", "alternative to"],
        "strength": SignalStrength.MEDIUM,
        "reason": "Current vendor mentioned — in-market signal",
        "base_confidence": 70,
    },
    {
        "name": "mentioned_decision_maker",
        "keywords": ["ceo", "cto", "vp", "director", "head of", "manager",
                      "team lead", "founder", "owner", "decision maker", "procurement"],
        "strength": SignalStrength.MEDIUM,
        "reason": "Decision maker referenced — organizational buying process",
        "base_confidence": 65,
    },
    {
        "name": "mentioned_procurement",
        "keywords": ["procurement", "purchasing", "vendor review", "approval process",
                      "legal review", "contract review", "terms"],
        "strength": SignalStrength.STRONG,
        "reason": "Procurement mentioned — formal buying process",
        "base_confidence": 80,
    },
    {
        "name": "mentioned_contract",
        "keywords": ["contract", "agreement", "terms", "msa", "sla", "renewal",
                      "sign off", "signature"],
        "strength": SignalStrength.STRONG,
        "reason": "Contract mentioned — closing stage",
        "base_confidence": 85,
    },
    {
        "name": "mentioned_rollout",
        "keywords": ["roll out", "launch", "deploy", "company-wide", "team rollout",
                      "org-wide", "adoption", "implementation plan"],
        "strength": SignalStrength.STRONG,
        "reason": "Rollout planning — committed buyer",
        "base_confidence": 80,
    },
    {
        "name": "asked_for_proposal",
        "keywords": ["proposal", "send over", "send details", "formal proposal",
                      "statement of work", "proposal"],
        "strength": SignalStrength.VERY_STRONG,
        "reason": "Proposal request — active buying process",
        "base_confidence": 90,
    },
    {
        "name": "asked_for_case_studies",
        "keywords": ["case study", "reference", "customer story", "success story",
                      "example", "similar company", "use case"],
        "strength": SignalStrength.MEDIUM,
        "reason": "Case study request — evaluating proof points",
        "base_confidence": 65,
    },
    {
        "name": "asked_for_technical_specs",
        "keywords": ["specs", "specifications", "requirements", "compatibility",
                      "system requirements", "platform", "supported"],
        "strength": SignalStrength.MEDIUM,
        "reason": "Technical specs request — due diligence",
        "base_confidence": 60,
    },
    {
        "name": "discussed_timeline",
        "keywords": ["timeline", "when", "by when", "deadline", "target date",
                      "expected by", "need it by", "by next"],
        "strength": SignalStrength.STRONG,
        "reason": "Timeline discussion — planning purchase",
        "base_confidence": 75,
    },
]
