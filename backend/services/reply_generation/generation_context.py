from __future__ import annotations
from services.conversation_intelligence.intelligence_models import ConversationIntelligence
from services.reasoning.reasoning_models import ReasoningResult
from services.reply_generation.generation_models import GenerationContext, GenerationStyle, CONTEXT_BUILDER_VERSION


def build_context(
    intelligence: ConversationIntelligence,
    reasoning: ReasoningResult,
    style: GenerationStyle = GenerationStyle.PROFESSIONAL,
    latest_messages: list[str] = None,
    follow_up: bool = False,
    knowledge_context: dict | None = None,
) -> GenerationContext:
    """Build a normalized GenerationContext from intelligence and reasoning.
    
    All data is structured and filtered before reaching providers.
    No raw conversation objects. No provider objects. No store references.
    """
    summary = ""
    if intelligence.summaries:
        for s in intelligence.summaries:
            if s.level and s.level.value == "short":
                summary = s.content
                break
        if not summary and intelligence.summaries:
            summary = intelligence.summaries[0].content

    signals = [
        f"{s.signal_type} ({s.strength.value})"
        for s in intelligence.buying_signals[:5]
    ]

    objections = [
        {"category": o.category.value, "severity": o.severity.value}
        for o in intelligence.objections[:5]
    ]

    entities = [
        f"{e.entity_type.value}: {e.value}"
        for e in intelligence.entities[:8]
    ]

    memory_facts = [
        f"{m.key}: {m.value}"
        for m in intelligence.memory[:10]
    ]

    policy_results = [
        f"{p.policy_name}: {p.result.value}"
        for p in reasoning.decision.policy_results
    ]

    stage = getattr(reasoning, 'stage', None)
    if stage:
        conversation_stage = str(stage)
    else:
        conversation_stage = "Active"

    target_action = reasoning.decision.type.value.replace("_", " ").title() if reasoning.decision else ""
    knowledge = knowledge_context if isinstance(knowledge_context, dict) else {}

    return GenerationContext(
        conversation_id=intelligence.conversation_id,
        executive_summary=summary,
        conversation_stage=conversation_stage,
        primary_goal=reasoning.goal.primary.value if reasoning.goal else "",
        alternative_goal=reasoning.goal.alternative.value if reasoning.goal and reasoning.goal.alternative else "",
        decision_type=reasoning.decision.type.value,
        decision_priority=reasoning.decision.priority.value,
        decision_confidence=reasoning.decision.confidence,
        buying_signals=signals,
        objections=objections,
        key_entities=entities,
        memory_facts=memory_facts,
        latest_messages=latest_messages or [],
        style_name=style.value,
        policy_results=policy_results,
        risk_level=reasoning.decision.risk.value,
        health_score=intelligence.health.score if intelligence.health else 0,
        target_action=target_action,
        follow_up=follow_up,
        knowledge_context=knowledge,
        knowledge_item_ids=list(knowledge.get("item_ids") or []),
        knowledge_source_ids=list(knowledge.get("source_ids") or []),
        knowledge_query=str(knowledge.get("query") or ""),
    )
