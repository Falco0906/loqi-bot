"""Characterization coverage for the legacy ReplyIntelligence projection."""

from services.conversation_intelligence.legacy_reply_projection import project_legacy_reply_intelligence
from services.conversation_intelligence.legacy_models import ConversationMessage


def test_pricing_reply_preserves_legacy_projection_and_memory_contract():
    intelligence, memory = project_legacy_reply_intelligence(
        ConversationMessage(text="How much does this cost?", sender="lead"),
        conversation_id="projection-contract",
    )

    assert intelligence.model_dump(mode="json") == {
        "conversation_id": "projection-contract",
        "executive_summary": (
            "Lead is actively evaluating the product. "
            "Primary concern: direct pricing inquiry — strong purchase intent "
            "Strong buying intent shown through 2 signals. "
            "Recommended action: Send Pricing today."
        ),
        "intents": [{
            "intent": "pricing_request",
            "confidence": 95,
            "reason": "Explicit pricing-related keywords detected",
            "supporting_evidence": ["cost", "how much"],
        }],
        "buying_signals": [
            {
                "signal": "asked_for_pricing",
                "strength": "very_strong",
                "confidence": 99,
                "reason": "Direct pricing inquiry — strong purchase intent",
                "supporting_evidence": ["cost", "how much"],
            },
            {
                "signal": "mentioned_budget",
                "strength": "very_strong",
                "confidence": 93,
                "reason": "Budget discussion — serious consideration",
                "supporting_evidence": ["cost"],
            },
        ],
        "conversation_stage": "evaluation",
        "stage_reasoning": "Strong buying signals indicate evaluation",
        "key_risks": [],
        "key_opportunities": ["Pricing discussion"],
        "top_objection": "",
        "decision_confidence": 50,
        "urgency": "high",
        "recommended_next_step": "send_pricing",
        "next_step_reasoning": "Lead asked about pricing. Respond with pricing and value proposition.",
        "human_approval_required": False,
        "suggested_workflow_objective": "Generate Pricing Email",
    }
    assert memory.model_dump(mode="json") == {
        "conversation_id": "projection-contract",
        "current_stage": "evaluation",
        "summary": "Message from lead: How much does this cost?...",
        "open_questions": [],
        "outstanding_objections": [],
        "pain_points": [],
        "business_goals": [],
        "competitor_mentioned": "",
        "decision_makers": [],
        "buying_signals": ["Asked For Pricing", "Mentioned Budget"],
        "last_recommendation": "Strong buying signals indicate evaluation",
        "last_followup": "send_pricing",
        "promised_actions": [],
        "preferred_communication_style": "",
        "key_risks": [],
        "key_opportunities": ["Pricing discussion"],
        "urgency": "high",
        "decision_confidence": 50,
        "top_objection": "",
    }
