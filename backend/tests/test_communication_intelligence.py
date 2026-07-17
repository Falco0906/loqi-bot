"""Tests for the Communication Intelligence Engine (Phase 3.5.1).

Covers intent detection, buying signals, memory, reply intelligence,
follow-up reasoner, summary, and timeline.
"""

from services.conversation_models import (
    ConversationMessage, IntentCategory, SignalStrength,
    ConversationStage, FollowupAction, TimelineEventType,
)
from services.intent_detector import detect_intents
from services.buying_signal import detect_signals
from services.conversation_classifier import classify_stage
from services.conversation_memory import memory_store, create_or_update_memory, MemoryStore
from services.followup_reasoner import recommend_followup
from services.reply_summary import generate_summary
from services.conversation_timeline import create_event, get_events, clear_events, clear_all
from services.reply_intelligence import analyze_message


# ── Fixtures ──

def _msg(text: str, sender: str = "lead") -> ConversationMessage:
    return ConversationMessage(text=text, sender=sender)


def _cleanup():
    memory_store._store.clear()
    clear_all()


# ═══════════════════════════════════════════════════════════════════
# 1. Intent Detection
# ═══════════════════════════════════════════════════════════════════

class TestIntentDetection:
    def test_single_intent(self):
        intents = detect_intents("How much does this cost?")
        assert len(intents) >= 1
        assert intents[0].intent == IntentCategory.PRICING_REQUEST
        assert intents[0].confidence > 0
        assert intents[0].reason
        assert len(intents[0].supporting_evidence) > 0

    def test_multiple_intents(self):
        intents = detect_intents("This looks interesting but how much does it cost?")
        categories = {i.intent for i in intents}
        assert IntentCategory.INTERESTED in categories
        assert IntentCategory.PRICING_REQUEST in categories

    def test_ambiguous_reply(self):
        intents = detect_intents("Let me think about it")
        assert len(intents) == 0 or intents[0].confidence < 70

    def test_contradictory_intents(self):
        intents = detect_intents("I'm interested but it's too expensive and not the right time", top_n=5)
        cats = {i.intent for i in intents}
        assert IntentCategory.INTERESTED in cats
        assert IntentCategory.BUDGET_CONCERN in cats
        assert IntentCategory.TIMING_CONCERN in cats

    def test_out_of_office(self):
        intents = detect_intents("I am out of the office until next Monday")
        cats = {i.intent for i in intents}
        assert IntentCategory.OUT_OF_OFFICE in cats

    def test_not_interested(self):
        intents = detect_intents("I'm not interested, please stop emailing me")
        cats = {i.intent for i in intents}
        assert IntentCategory.NOT_INTERESTED in cats

    def test_meeting_request(self):
        intents = detect_intents("Can we schedule a call next week?")
        cats = {i.intent for i in intents}
        assert IntentCategory.MEETING_REQUEST in cats

    def test_demo_request(self):
        intents = detect_intents("I'd like to see a demo of the product")
        cats = {i.intent for i in intents}
        assert IntentCategory.DEMO_REQUEST in cats

    def test_top_n(self):
        intents = detect_intents("How much does this cost? I want a demo", top_n=1)
        assert len(intents) == 1

    def test_return_structure(self):
        intents = detect_intents("How does your API work?")
        assert len(intents) >= 1
        p = intents[0]
        assert p.intent
        assert isinstance(p.confidence, int)
        assert 0 <= p.confidence <= 100
        assert isinstance(p.reason, str)
        assert isinstance(p.supporting_evidence, list)


# ═══════════════════════════════════════════════════════════════════
# 2. Buying Signals
# ═══════════════════════════════════════════════════════════════════

class TestBuyingSignals:
    def test_weak_signal(self):
        signals = detect_signals("Can you send a case study?")
        assert len(signals) >= 1
        assert signals[0].strength in (
            SignalStrength.MEDIUM, SignalStrength.WEAK, SignalStrength.VERY_WEAK
        )

    def test_medium_signal(self):
        signals = detect_signals("Who is your current vendor?")
        found = any(s.signal == "mentioned_current_vendor" for s in signals)
        # current vendor keyword check
        signals2 = detect_signals("We are currently using a different platform")
        found2 = any(s.signal == "mentioned_current_vendor" for s in signals2)
        assert found or found2

    def test_strong_signal(self):
        signals = detect_signals("Can we schedule a call to discuss this further?")
        assert any(s.strength == SignalStrength.STRONG for s in signals)

    def test_very_strong_signal(self):
        signals = detect_signals("How much does this cost? I need a quote")
        assert any(s.strength == SignalStrength.VERY_STRONG for s in signals)

    def test_multiple_simultaneous_signals(self):
        signals = detect_signals("What's the pricing and how long does implementation take?")
        assert len(signals) >= 2
        names = {s.signal for s in signals}
        assert "asked_for_pricing" in names
        assert "asked_implementation_timeline" in names

    def test_no_signals(self):
        signals = detect_signals("Hello, how are you?")
        assert len(signals) == 0

    def test_return_structure(self):
        signals = detect_signals("What's the pricing?")
        assert len(signals) >= 1
        s = signals[0]
        assert isinstance(s.signal, str)
        assert isinstance(s.strength, SignalStrength)
        assert isinstance(s.confidence, int)
        assert 0 <= s.confidence <= 100
        assert isinstance(s.reason, str)


# ═══════════════════════════════════════════════════════════════════
# 3. Conversation Memory
# ═══════════════════════════════════════════════════════════════════

class TestConversationMemory:
    def setup_method(self):
        _cleanup()

    def test_memory_creation(self):
        msg = _msg("How much does this cost?")
        intents = detect_intents(msg.text)
        signals = detect_signals(msg.text)
        mem = create_or_update_memory(
            conversation_id="test-1",
            message=msg,
            intents=intents,
            buying_signals=signals,
            stage=ConversationStage.ENGAGED,
            stage_reasoning="Test",
        )
        assert mem.conversation_id == "test-1"
        assert len(mem.buying_signals) > 0

    def test_memory_update(self):
        msg1 = _msg("How much does this cost?")
        intents1 = detect_intents(msg1.text)
        sigs1 = detect_signals(msg1.text)
        mem = create_or_update_memory(
            conversation_id="test-2", message=msg1,
            intents=intents1, buying_signals=sigs1,
            stage=ConversationStage.ENGAGED, stage_reasoning="Test",
        )
        assert "Asked For Pricing" in " ".join(mem.buying_signals)

        msg2 = _msg("Can you tell me about implementation?")
        intents2 = detect_intents(msg2.text)
        sigs2 = detect_signals(msg2.text)
        mem2 = create_or_update_memory(
            conversation_id="test-2", message=msg2,
            intents=intents2, buying_signals=sigs2,
            stage=ConversationStage.EVALUATION, stage_reasoning="Test 2",
            existing_memory=mem,
        )
        assert len(mem2.buying_signals) >= len(mem.buying_signals)

    def test_fact_preservation(self):
        msg1 = _msg("We are struggling with scaling our infrastructure")
        intents = detect_intents(msg1.text)
        sigs = detect_signals(msg1.text)
        mem = create_or_update_memory(
            conversation_id="test-3", message=msg1,
            intents=intents, buying_signals=sigs,
            stage=ConversationStage.DISCOVERY, stage_reasoning="Test",
        )
        assert len(mem.pain_points) > 0

    def test_memory_store(self):
        msg = _msg("Hello")
        intents = detect_intents(msg.text)
        sigs = detect_signals(msg.text)
        mem = create_or_update_memory(
            conversation_id="store-1", message=msg,
            intents=intents, buying_signals=sigs,
            stage=ConversationStage.ENGAGED, stage_reasoning="Test",
        )
        stored = memory_store.get("store-1")
        assert stored is not None
        assert stored.conversation_id == "store-1"

    def test_key_risks_populated(self):
        msg = _msg("This is too expensive and not in our budget")
        intents = detect_intents(msg.text)
        sigs = detect_signals(msg.text)
        mem = create_or_update_memory(
            conversation_id="test-risks", message=msg,
            intents=intents, buying_signals=sigs,
            stage=ConversationStage.EVALUATION, stage_reasoning="Test",
        )
        assert len(mem.key_risks) > 0
        assert any("budget" in r.lower() for r in mem.key_risks)


# ═══════════════════════════════════════════════════════════════════
# 4. Reply Intelligence
# ═══════════════════════════════════════════════════════════════════

class TestReplyIntelligence:
    def setup_method(self):
        _cleanup()

    def test_aggregation(self):
        msg = _msg("How much does this cost? I'd like a demo too")
        intel, mem = analyze_message(msg, conversation_id="ri-1")
        assert intel.conversation_id == "ri-1"
        assert len(intel.intents) >= 2
        assert len(intel.buying_signals) >= 1
        assert intel.executive_summary
        assert intel.suggested_workflow_objective
        assert intel.recommended_next_step

    def test_missing_fields(self):
        msg = _msg("")
        intel, mem = analyze_message(msg, conversation_id="ri-empty")
        assert intel.intents == []
        assert intel.buying_signals == []
        assert intel.executive_summary

    def test_empty_conversation(self):
        msg = _msg("Hi there")
        intel, mem = analyze_message(msg, conversation_id="ri-hi")
        assert intel is not None
        assert mem is not None

    def test_multiple_messages(self):
        msg1 = _msg("Tell me more about your product")
        intel1, mem1 = analyze_message(msg1, conversation_id="ri-multi")

        msg2 = _msg("How does pricing work?")
        intel2, mem2 = analyze_message(msg2, conversation_id="ri-multi", existing_memory=mem1)
        assert len(intel2.intents) >= 1
        assert intel2.conversation_stage

    def test_urgency_computed(self):
        msg = _msg("Can we schedule a meeting for next week?")
        intel, mem = analyze_message(msg, conversation_id="ri-urgent")
        assert intel.urgency == "high"


# ═══════════════════════════════════════════════════════════════════
# 5. Follow-up Reasoner
# ═══════════════════════════════════════════════════════════════════

class TestFollowupReasoner:
    def test_pricing_request(self):
        intents = detect_intents("How much does it cost?")
        signals = detect_signals("How much does it cost?")
        rec = recommend_followup(intents, signals, ConversationStage.ENGAGED)
        assert rec.action == FollowupAction.SEND_PRICING
        assert rec.priority == "high"

    def test_meeting_request(self):
        intents = detect_intents("Can we schedule a call?")
        signals = detect_signals("Can we schedule a call?")
        rec = recommend_followup(intents, signals, ConversationStage.ENGAGED)
        assert rec.action == FollowupAction.SCHEDULE_MEETING

    def test_demo_request(self):
        intents = detect_intents("I want a demo of the product")
        signals = detect_signals("I want a demo of the product")
        rec = recommend_followup(intents, signals, ConversationStage.ENGAGED)
        assert rec.action == FollowupAction.SCHEDULE_DEMO

    def test_objection(self):
        intents = detect_intents("I'm not sure this will work for us")
        signals = detect_signals("I'm not sure this will work for us")
        rec = recommend_followup(intents, signals, ConversationStage.ENGAGED)
        assert rec.action == FollowupAction.ANSWER_OBJECTION

    def test_dormant_lead(self):
        intents = detect_intents("Not the right time, reach out later")
        signals = detect_signals("Not the right time, reach out later")
        rec = recommend_followup(intents, signals, ConversationStage.DORMANT)
        assert rec.action in (FollowupAction.WAIT, FollowupAction.CONTINUE_NURTURING, FollowupAction.CLOSE_CONVERSATION)

    def test_lost_opportunity(self):
        intents = detect_intents("We went with another vendor")
        signals = detect_signals("We went with another vendor")
        rec = recommend_followup(intents, signals, ConversationStage.LOST)
        assert rec.action == FollowupAction.MARK_LOST
        assert rec.approval_required is True

    def test_not_interested(self):
        intents = detect_intents("I'm not interested")
        signals = detect_signals("I'm not interested")
        rec = recommend_followup(intents, signals, ConversationStage.ENGAGED)
        assert rec.action == FollowupAction.CLOSE_CONVERSATION

    def test_out_of_office(self):
        intents = detect_intents("I am out of the office")
        signals = detect_signals("I am out of the office")
        rec = recommend_followup(intents, signals, ConversationStage.ENGAGED)
        assert rec.action == FollowupAction.WAIT

    def test_technical_question_with_strong_signal(self):
        intents = detect_intents("How does your API integration work?")
        signals = detect_signals("How does your API integration work?")
        rec = recommend_followup(intents, signals, ConversationStage.EVALUATION)
        assert rec.action in (FollowupAction.GENERATE_TECHNICAL_RESPONSE, FollowupAction.REPLY_IMMEDIATELY)

    def test_return_structure(self):
        intents = detect_intents("Hello")
        signals = detect_signals("Hello")
        rec = recommend_followup(intents, signals, ConversationStage.ENGAGED)
        assert isinstance(rec.action, FollowupAction)
        assert isinstance(rec.priority, str)
        assert isinstance(rec.reason, str)
        assert isinstance(rec.estimated_value, str)
        assert isinstance(rec.approval_required, bool)


# ═══════════════════════════════════════════════════════════════════
# 6. Timeline
# ═══════════════════════════════════════════════════════════════════

class TestTimeline:
    def setup_method(self):
        clear_all()

    def test_correct_event_creation(self):
        ev = create_event("conv-1", TimelineEventType.LEAD_REPLIED, "Lead replied")
        assert ev.event_type == TimelineEventType.LEAD_REPLIED
        assert ev.message == "Lead replied"
        assert ev.timestamp

    def test_correct_ordering(self):
        from datetime import datetime, timezone, timedelta
        import time
        e1 = create_event("conv-2", TimelineEventType.LEAD_REPLIED, "First")
        time.sleep(0.01)
        e2 = create_event("conv-2", TimelineEventType.PRICING_REQUESTED, "Second")
        events = get_events("conv-2")
        assert len(events) == 2
        assert events[0].message == "First"
        assert events[1].message == "Second"

    def test_multiple_conversations(self):
        create_event("conv-a", TimelineEventType.LEAD_REPLIED, "A1")
        create_event("conv-b", TimelineEventType.PRICING_REQUESTED, "B1")
        create_event("conv-a", TimelineEventType.DEMO_REQUESTED, "A2")
        assert len(get_events("conv-a")) == 2
        assert len(get_events("conv-b")) == 1

    def test_clear_events(self):
        create_event("conv-c", TimelineEventType.LEAD_REPLIED, "Test")
        clear_events("conv-c")
        assert get_events("conv-c") == []


# ═══════════════════════════════════════════════════════════════════
# 7. Classification / Stage
# ═══════════════════════════════════════════════════════════════════

class TestStageClassification:
    def test_initial_outreach(self):
        stage, reason = classify_stage([], "Hello, saw your email")
        assert stage == ConversationStage.INITIAL_OUTREACH

    def test_engaged(self):
        signals = detect_signals("Thanks, tell me more")
        stage, reason = classify_stage(signals, "Thanks, tell me more")
        assert stage in (ConversationStage.ENGAGED, ConversationStage.INITIAL_OUTREACH)

    def test_evaluation(self):
        signals = detect_signals("I'd like a demo to see how it works")
        stage, reason = classify_stage(signals, "I'd like a demo to see how it works")
        assert stage == ConversationStage.EVALUATION

    def test_dormant(self):
        stage, reason = classify_stage([], "Not now, maybe next quarter")
        assert stage == ConversationStage.DORMANT

    def test_decision(self):
        signals = [
            type('obj', (), {'signal': 'mentioned_contract', 'strength': type('s', (), {'value': 'strong'}),
                             'confidence': 90, 'reason': '', 'supporting_evidence': []})(),
            type('obj', (), {'signal': 'asked_for_pricing', 'strength': type('s', (), {'value': 'very_strong'}),
                             'confidence': 95, 'reason': '', 'supporting_evidence': []})(),
        ]
        stage, reason = classify_stage(signals, "Send over the contract")
        assert stage == ConversationStage.DECISION


# ═══════════════════════════════════════════════════════════════════
# 8. Summary
# ═══════════════════════════════════════════════════════════════════

class TestSummary:
    def test_empty(self):
        s = generate_summary([], [], type('obj', (), {
            'action': FollowupAction.REPLY_IMMEDIATELY, 'priority': 'low',
            'reason': '', 'estimated_value': '', 'approval_required': False
        })())
        assert s
        assert "No significant" in s

    def test_pricing_summary(self):
        intents = detect_intents("How much does this cost? I need pricing")
        signals = detect_signals("How much does this cost? I need pricing")
        rec = recommend_followup(intents, signals, ConversationStage.ENGAGED)
        s = generate_summary(intents, signals, rec)
        assert s
        assert any(word in s.lower() for word in ["pricing", "evaluating", "recommended"])

    def test_not_interested_summary(self):
        intents = detect_intents("Not interested, thanks")
        signals = detect_signals("Not interested, thanks")
        rec = recommend_followup(intents, signals, ConversationStage.ENGAGED)
        s = generate_summary(intents, signals, rec)
        assert "not interested" in s.lower() or "opted out" in s.lower()


# ═══════════════════════════════════════════════════════════════════
# 9. Integration: End-to-end flow
# ═══════════════════════════════════════════════════════════════════

class TestEndToEnd:
    def setup_method(self):
        _cleanup()

    def test_full_flow(self):
        cid = "e2e-1"

        msg1 = _msg("Your product looks interesting")
        intel1, mem1 = analyze_message(msg1, conversation_id=cid)
        assert intel1.decision_confidence >= 0
        assert intel1.urgency
        assert intel1.suggested_workflow_objective

        msg2 = _msg("How much does it cost? I need to understand pricing")
        intel2, mem2 = analyze_message(msg2, conversation_id=cid, existing_memory=mem1)
        assert len(intel2.intents) >= 1
        assert len(mem2.buying_signals) > 0

        msg3 = _msg("Can you walk me through a demo?")
        intel3, mem3 = analyze_message(msg3, conversation_id=cid, existing_memory=mem2)
        assert intel3.recommended_next_step in (
            FollowupAction.SCHEDULE_DEMO, FollowupAction.REPLY_IMMEDIATELY
        )

        events = get_events(cid)
        assert len(events) >= 3
        event_types = {e.event_type for e in events}
        assert TimelineEventType.LEAD_REPLIED in event_types

    def test_workflow_objective_mapping(self):
        from services.conversation_models import FollowupAction
        from services.reply_intelligence import _map_to_workflow_objective
        from services.conversation_models import IntentCategory, IntentPrediction

        result = _map_to_workflow_objective(
            FollowupAction.SEND_PRICING,
            [IntentPrediction(intent=IntentCategory.PRICING_REQUEST, confidence=80, reason="test")]
        )
        assert result == "Generate Pricing Email"

        result = _map_to_workflow_objective(
            FollowupAction.SCHEDULE_DEMO,
            []
        )
        assert result == "Schedule Demo"
