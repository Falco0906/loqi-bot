"""Buying Signal Detection — analyses messages for purchase intent signals.

Signal strength uses human labels (Very Weak → Very Strong).
No numeric scores exposed to consumers.
"""

from services.conversation_models import BuyingSignal, SignalStrength


_SIGNAL_PATTERNS: list[tuple[str, list[str], SignalStrength, str, int]] = [
    ("asked_for_pricing", [
        "pricing", "price", "cost", "how much", "quote", "subscription plan",
    ], SignalStrength.VERY_STRONG, "Direct pricing inquiry — strong purchase intent", 95),
    ("requested_demo", [
        "demo", "demonstration", "show me", "walk me through", "see it in action",
    ], SignalStrength.VERY_STRONG, "Demo request — active evaluation", 95),
    ("requested_meeting", [
        "meeting", "schedule", "book a call", "talk", "discuss further",
    ], SignalStrength.STRONG, "Meeting request — serious engagement", 85),
    ("asked_implementation_timeline", [
        "implement", "roll out", "how long", "timeframe", "setup time",
        "deploy", "onboarding", "migration", "time to",
    ], SignalStrength.STRONG, "Implementation timeline question — active planning", 80),
    ("asked_integration_questions", [
        "integration", "api", "connect", "import", "export", "compatible with",
        "works with", "integrate",
    ], SignalStrength.STRONG, "Integration questions — technical evaluation underway", 80),
    ("mentioned_budget", [
        "budget", "cost", "expensive", "spend", "roi", "value", "worth it",
        "investment", "afford",
    ], SignalStrength.VERY_STRONG, "Budget discussion — serious consideration", 90),
    ("mentioned_current_vendor", [
        "currently using", "current vendor", "we use", "switching from",
        "migrating from", "replacing", "alternative to",
    ], SignalStrength.MEDIUM, "Current vendor mentioned — in-market signal", 70),
    ("mentioned_decision_maker", [
        "ceo", "cto", "vp", "director", "head of", "manager", "team lead",
        "founder", "owner", "decision maker", "procurement",
    ], SignalStrength.MEDIUM, "Decision maker referenced — organizational buying process", 65),
    ("mentioned_procurement", [
        "procurement", "purchasing", "vendor review", "approval process",
        "legal review", "contract review", "terms",
    ], SignalStrength.STRONG, "Procurement mentioned — formal buying process", 80),
    ("mentioned_contract", [
        "contract", "agreement", "terms", "msa", "sla", "renewal",
        "sign off", "signature",
    ], SignalStrength.STRONG, "Contract mentioned — closing stage", 85),
    ("mentioned_rollout", [
        "roll out", "launch", "deploy", "company-wide", "team rollout",
        "org-wide", "adoption", "implementation plan",
    ], SignalStrength.STRONG, "Rollout planning — committed buyer", 80),
    ("asked_for_proposal", [
        "proposal", "send over", "send details", "formal proposal",
        "statement of work", "proposal",
    ], SignalStrength.VERY_STRONG, "Proposal request — active buying process", 90),
    ("asked_for_case_studies", [
        "case study", "reference", "customer story", "success story",
        "example", "similar company", "use case",
    ], SignalStrength.MEDIUM, "Case study request — evaluating proof points", 65),
    ("asked_for_technical_specs", [
        "specs", "specifications", "requirements", "compatibility",
        "system requirements", "platform", "supported",
    ], SignalStrength.MEDIUM, "Technical specs request — due diligence", 60),
    ("discussed_timeline", [
        "timeline", "when", "by when", "deadline", "target date",
        "expected by", "need it by", "by next",
    ], SignalStrength.STRONG, "Timeline discussion — planning purchase", 75),
]


def detect_signals(message: str) -> list[BuyingSignal]:
    """Analyze a message for buying signals, returning all detected signals."""
    ml = message.lower()
    results: list[BuyingSignal] = []

    for name, patterns, strength, reason, base_conf in _SIGNAL_PATTERNS:
        evidence = [p for p in patterns if p in ml]
        if evidence:
            confidence = min(base_conf + (len(evidence) * 3), 99)
            results.append(BuyingSignal(
                signal=name,
                strength=strength,
                confidence=confidence,
                reason=reason,
                supporting_evidence=evidence[:3],
            ))

    results.sort(key=lambda x: x.confidence, reverse=True)
    return results
