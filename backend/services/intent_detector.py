"""Intent Detection — structured classification of message intent.

Supports multiple simultaneous intents.
Each prediction includes confidence, reason, and supporting evidence.
"""

from services.conversation_models import IntentCategory, IntentPrediction


_INTENT_PATTERNS: list[tuple[IntentCategory, list[str], str, int]] = [
    (IntentCategory.PRICING_REQUEST, [
        "pricing", "price", "cost", "how much", "what does it cost",
        "pricing page", "quote", "quotation", "pricing model",
        "subscription", "plan", "pricing plans", "per seat", "per month",
    ], "Explicit pricing-related keywords detected", 85),
    (IntentCategory.MEETING_REQUEST, [
        "schedule", "meeting", "book a call", "set up a time",
        "calendar", "availability", "find time", "let's talk",
        "hop on a call", "phone call", "call me", "when are you free",
        "coffee", "lunch", "discuss further", "talk further",
    ], "Meeting or call request detected", 80),
    (IntentCategory.DEMO_REQUEST, [
        "demo", "demonstration", "show me", "walk me through",
        "see it in action", "product tour", "live demo",
        "see how it works", "show how",
    ], "Demo request detected", 85),
    (IntentCategory.TECHNICAL_QUESTION, [
        "how does it work", "architecture", "api", "integration",
        "security", "sso", "single sign on", "data", "encryption",
        "compliance", "gdpr", "soc2", "infrastructure", "uptime",
        "reliability", "scalability", "performance",
    ], "Technical question detected", 75),
    (IntentCategory.IMPLEMENTATION_QUESTION, [
        "implement", "setup", "onboarding", "deploy", "roll out",
        "migration", "migrate", "integration process", "time to implement",
        "how long", "timeframe", "timeline for", "getting started",
        "installation", "configure", "configuration",
    ], "Implementation question detected", 80),
    (IntentCategory.COMPETITOR_MENTION, [
        "competitor", "compared to", "vs ", "versus", "alternative",
        "other option", "also use", "currently using", "switching from",
        "using x", "using y", "similar to", "like ", "instead of",
    ], "Competitor reference detected", 70),
    (IntentCategory.OBJECTION, [
        "but", "however", "problem is", "issue is", "concern",
        "worried about", "not sure", "hesitant", "difficult",
        "challenging", "not convinced", "doesn't work",
    ], "Objection language detected", 65),
    (IntentCategory.BUDGET_CONCERN, [
        "budget", "expensive", "too much", "costly", "can't afford",
        "not in budget", "tight budget", "roi", "return on investment",
        "value", "worth it", "overpriced", "cost effective",
        "spend", "spending", "allocated",
    ], "Budget-related concern detected", 80),
    (IntentCategory.TIMING_CONCERN, [
        "not now", "not the right time", "too busy", "later",
        "next quarter", "next year", "someday", "not yet",
        "too soon", "priorities", "other priorities", "busy",
        "circling back", "reach out later",
    ], "Timing concern detected", 75),
    (IntentCategory.AUTHORITY_CONCERN, [
        "need to check with", "talk to my team", "discuss with",
        "my manager", "my boss", "decision maker", "not my decision",
        "not my area", "need approval", "need to run it by",
        "my partner", "my co-founder", "the team",
    ], "Authority concern detected", 75),
    (IntentCategory.NEED_MORE_INFO, [
        "more information", "tell me more", "learn more", "more details",
        "additional information", "can you explain", "what about",
        "could you elaborate", "more about", "send me more",
        "brochure", "materials", "resources",
    ], "Request for more information detected", 70),
    (IntentCategory.REFERRAL, [
        "refer", "introduce", "connection", "colleague", "coworker",
        "partner", "someone who", "know someone", "friend",
        "network", "contact who",
    ], "Referral or introduction detected", 70),
    (IntentCategory.NOT_INTERESTED, [
        "not interested", "no thank you", "unsubscribe", "stop",
        "don't contact", "remove me", "not a fit", "not relevant",
        "not for us", "waste of time", "not applicable", "leave me alone",
        "spam", "stop emailing",
    ], "Not interested signal detected", 85),
    (IntentCategory.UNSUBSCRIBE, [
        "unsubscribe", "opt out", "opt-out", "remove from list",
        "take me off", "do not email", "stop sending",
    ], "Unsubscribe request detected", 90),
    (IntentCategory.OUT_OF_OFFICE, [
        "out of office", "out of the office", "ooo", "vacation", "on leave", "away from",
        "will respond", "back on", "not in the office", "holiday",
        "annual leave", "sick leave",
    ], "Out of office auto-reply detected", 90),
    (IntentCategory.FOLLOW_UP_LATER, [
        "follow up", "remind me", "ping me", "touch base",
        "check back", "reach out", "circle back", "get back to me",
        "remind", "followup",
    ], "Request to follow up later detected", 65),
    (IntentCategory.POSITIVE_FEEDBACK, [
        "great", "awesome", "love it", "excellent", "amazing",
        "perfect", "fantastic", "helpful", "useful", "valuable",
        "impressed", "interested in", "looks good", "sounds good",
        "makes sense", "thanks for", "appreciate",
    ], "Positive sentiment detected", 65),
    (IntentCategory.NEGATIVE_FEEDBACK, [
        "disappointed", "frustrated", "annoying", "terrible",
        "worst", "bad experience", "not working", "broken",
        "useless", "waste", "unhappy", "unfortunately",
    ], "Negative sentiment detected", 70),
    (IntentCategory.INTERESTED, [
        "interested", "curious", "tell me more", "sounds interesting",
        "looks interesting", "could be useful", "this looks",
        "excited about", "want to learn", "explore",
    ], "Interest signal detected", 60),
    (IntentCategory.GENERAL_QUESTION, [
        "what is", "how do you", "can you tell", "question", "help me understand",
        "i was wondering", "curious about", "explain",
    ], "General question detected", 50),
]


def detect_intents(message: str, top_n: int = 3) -> list[IntentPrediction]:
    """Detect all intents in a message, returning the top N by confidence."""
    ml = message.lower()
    results: list[IntentPrediction] = []

    for intent, patterns, reason, base_conf in _INTENT_PATTERNS:
        evidence = [p for p in patterns if p in ml]
        if evidence:
            confidence = min(base_conf + (len(evidence) * 5), 99)
            results.append(IntentPrediction(
                intent=intent,
                confidence=confidence,
                reason=reason,
                supporting_evidence=evidence[:3],
            ))

    results.sort(key=lambda x: x.confidence, reverse=True)
    return results[:top_n]
