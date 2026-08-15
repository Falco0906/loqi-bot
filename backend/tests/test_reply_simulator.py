"""Tests for the development reply simulator (services/communication/reply_simulator.py).

The simulator is the pluggable event producer behind PR4.2: synthetic
replies must flow through the exact Gmail ingestion pipeline and the
conversations module (classification, status, timeline), and must be a
complete no-op when disabled.
"""

import os
import random
import tempfile

import pytest

from services.communication import reply_simulator as sim
from services.communication.provider_events import get_events, reset_events
from services.conversations.classification import classifier_service
from services.conversations.conversation_models import ConversationStatus
from services.conversations.conversation_store import conversation_store
from services.conversations.integration import create_conversation_from_send
from services.conversations.timeline import TimelineEventType

SIM_PROVIDER_ID = "sim_reply"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMULATE_REPLIES", raising=False)
    monkeypatch.delenv("SIMULATE_ACCELERATED", raising=False)
    monkeypatch.delenv("SIMULATE_REPLY_MULTIPLIER", raising=False)
    monkeypatch.delenv("SIMULATE_REPLY_WEIGHTS", raising=False)
    monkeypatch.setattr(sim, "STATE_FILE", str(tmp_path / "simulate_replies.json"))
    monkeypatch.setattr(sim, "rng", random.Random(42))
    monkeypatch.setattr(sim, "_pending", [])
    monkeypatch.setattr(sim, "_loaded", False)
    reset_events()
    yield
    reset_events()


def _send_context(overrides=None):
    ctx = {
        "conversation_id": "conv-test-1",
        "external_thread_id": "thread_abc123",
        "subject": "Quick question about {company}",
        "from_email": "faisal@loqi.com",
        "from_name": "Faisal",
        "to_email": "jordan@bella-vista.com",
        "to_name": "Jordan Parker",
        "body": "Hi Jordan, would Loqi be a fit for Bella Vista?",
        "campaign_id": "cmp-1",
        "workflow_id": "wf-1",
        "lead": {"name": "Jordan Parker", "company": "Bella Vista", "role": "Operations Manager"},
        "objective": "Book discovery calls",
    }
    ctx.update(overrides or {})
    return ctx


_thread_counter = 0


def _make_conversation(ctx):
    global _thread_counter
    _thread_counter += 1
    ctx = {**ctx, "external_thread_id": f"thread_{_thread_counter}"}
    return create_conversation_from_send(
        provider_id=SIM_PROVIDER_ID,
        provider_type="gmail",
        external_thread_id=ctx["external_thread_id"],
        external_message_id="outbound-1",
        subject=ctx["subject"],
        from_email=ctx["from_email"],
        from_name=ctx["from_name"],
        to_email=ctx["to_email"],
        to_name=ctx["to_name"],
        body=ctx["body"],
        campaign_id=ctx["campaign_id"],
        workflow_id=ctx["workflow_id"],
    )


def _force_scenario(monkeypatch, scenario_key):
    import json
    weights = {s.key: 0 for s in sim.SCENARIOS}
    weights[scenario_key] = 100
    monkeypatch.setenv("SIMULATE_REPLY_WEIGHTS", json.dumps(weights))


class TestDisabledMode:
    def test_maybe_schedule_is_noop_when_disabled(self):
        sim.maybe_schedule(_send_context())
        assert sim.pending_count() == 0
        assert not sim.is_enabled()

    def test_state_file_untouched_when_disabled(self):
        assert not os.path.exists(sim.STATE_FILE)
        sim.maybe_schedule(_send_context())
        assert not os.path.exists(sim.STATE_FILE)

    def test_weights_defaults(self):
        weights = sim._weights()
        assert weights == {
            "no_reply": 70, "interested": 10, "pricing_request": 6,
            "referral": 4, "competitor": 4, "out_of_office": 3,
            "not_interested": 3,
        }

    def test_weights_env_override(self, monkeypatch):
        monkeypatch.setenv("SIMULATE_REPLY_WEIGHTS", '{"interested": 50, "no_reply": 20}')
        weights = sim._weights()
        assert weights["interested"] == 50
        assert weights["no_reply"] == 20
        assert weights["competitor"] == 4


class TestScheduling:
    def test_enabled_schedules_pending(self, monkeypatch):
        monkeypatch.setenv("SIMULATE_REPLIES", "true")
        _force_scenario(monkeypatch, "interested")
        sim.maybe_schedule(_send_context())
        assert sim.pending_count() == 1
        entry = sim._pending[0]
        assert entry["kind"] == "reply"
        assert entry["scenario"] == "interested"
        assert entry["conversation_id"] == "conv-test-1"
        assert entry["external_thread_id"] == "thread_abc123"

    def test_no_reply_schedules_follow_up_timer(self, monkeypatch):
        monkeypatch.setenv("SIMULATE_REPLIES", "true")
        _force_scenario(monkeypatch, "no_reply")
        sim.maybe_schedule(_send_context())
        assert sim.pending_count() == 1
        entry = sim._pending[0]
        assert entry["kind"] == "follow_up"
        assert "fire_at" in entry

    def test_unknown_scenario_falls_back_to_interest(self, monkeypatch):
        monkeypatch.setenv("SIMULATE_REPLIES", "true")
        body = sim.generate_reply_body("not_a_scenario", {
            "lead_name": "Jordan", "company": "Bella Vista", "role": "",
        })
        assert body

    def test_delay_bounds_respect_scenario_range(self, monkeypatch):
        monkeypatch.setenv("SIMULATE_REPLIES", "true")
        scenario = sim.Scenario("pricing_request", 6, 20, 60)
        fire_at = sim._reply_fire_at(scenario)
        minutes = (fire_at - fire_at.replace(minute=0, second=0, microsecond=0)).total_seconds() / 60
        assert 0 < minutes <= 60

    def test_persistence_roundtrip(self, monkeypatch):
        monkeypatch.setenv("SIMULATE_REPLIES", "true")
        _force_scenario(monkeypatch, "interested")
        sim.maybe_schedule(_send_context())
        assert os.path.exists(sim.STATE_FILE)
        sim._loaded = False
        sim._pending[:] = []
        sim._load_state()
        assert sim.pending_count() == 1
        assert sim._pending[0]["scenario"] == "interested"


class TestPersonalization:
    def test_body_uses_lead_name_and_company(self):
        body = sim.generate_reply_body("interested", {
            "lead_name": "Jordan Parker", "company": "Bella Vista", "role": "Operations Manager",
        })
        assert "Jordan" in body
        assert "Bella Vista" in body

    def test_company_fallback_from_email_domain(self):
        ctx = _send_context({"lead": {"name": "Jordan Parker", "company": ""}})
        monkeypatch = None
        assert sim._company_from_email(ctx["to_email"]) == "Bella Vista"

    def test_operations_role_picks_timeline_variant(self):
        body = sim.generate_reply_body("interested", {
            "lead_name": "Jordan", "company": "Bella Vista", "role": "Operations Manager",
        })
        assert "implementation timeline" in body

    def test_pricing_body_mentions_pricing(self):
        body = sim.generate_reply_body("pricing_request", {
            "lead_name": "Jordan", "company": "Bella Vista", "role": "",
        })
        assert "pricing" in body.lower() or "cost" in body.lower() or "quote" in body.lower()

    def test_not_generic_thanks_template(self):
        body = sim.generate_reply_body("interested", {
            "lead_name": "Jordan", "company": "Bella Vista", "role": "",
        })
        assert body.strip() != "Thanks for your email."


class TestFiringPipeline:
    def _fire(self, monkeypatch, scenario_key, context=None):
        monkeypatch.setenv("SIMULATE_REPLIES", "true")
        _force_scenario(monkeypatch, scenario_key)
        ctx = context or _send_context()
        convo = _make_conversation(ctx)
        ctx["conversation_id"] = convo.conversation_id
        sim.maybe_schedule(ctx)
        return sim.fire_due(now=sim._parse_dt(sim._pending[0]["fire_at"]) or None)

    def test_reply_appears_in_conversation_store(self, monkeypatch):
        fired = self._fire(monkeypatch, "interested")
        assert len(fired) == 1
        convo = conversation_store.get_conversation(fired[0]["conversation_id"])
        assert convo.message_count == 2
        messages = conversation_store.get_messages_for_conversation(fired[0]["conversation_id"])
        inbound = [m for m in messages if m.direction == "inbound"]
        assert len(inbound) == 1
        assert inbound[0].from_email == "jordan@bella-vista.com"
        assert inbound[0].to_email == "faisal@loqi.com"
        assert inbound[0].subject.startswith("Re:")

    def test_classification_and_status_transition(self, monkeypatch):
        fired = self._fire(monkeypatch, "interested")
        convo = conversation_store.get_conversation(fired[0]["conversation_id"])
        assert convo.status == ConversationStatus.INTERESTED
        messages = conversation_store.get_messages_for_conversation(fired[0]["conversation_id"])
        inbound = [m for m in messages if m.direction == "inbound"][0]
        assert inbound.classification.get("category") in ("interested", "question", "unknown")

    def test_emits_message_received_provider_event(self, monkeypatch):
        self._fire(monkeypatch, "pricing_request")
        events = get_events()
        assert any(e.event_type.value == "message_received" for e in events)

    def test_timeline_has_reply_events(self, monkeypatch):
        fired = self._fire(monkeypatch, "pricing_request")
        timeline_types = {e.event_type for e in conversation_store.get_timeline(fired[0]["conversation_id"])}
        assert TimelineEventType.REPLY_RECEIVED in timeline_types
        assert TimelineEventType.REPLY_CLASSIFIED in timeline_types

    def test_thread_mapping_created(self, monkeypatch):
        fired = self._fire(monkeypatch, "interested")
        mapping = conversation_store.get_threads_for_conversation(fired[0]["conversation_id"])
        assert mapping

    def test_preserves_timestamp(self, monkeypatch):
        fired = self._fire(monkeypatch, "interested")
        from datetime import datetime, timezone
        fire_at = datetime.fromisoformat(fired[0]["fire_at"])
        messages = conversation_store.get_messages_for_conversation(fired[0]["conversation_id"])
        inbound = [m for m in messages if m.direction == "inbound"][0]
        assert inbound.sent_at.replace(tzinfo=timezone.utc) == fire_at

    def test_follow_up_plan_recorded(self, monkeypatch):
        fired = self._fire(monkeypatch, "pricing_request")
        convo = conversation_store.get_conversation(fired[0]["conversation_id"])
        plan = convo.metadata.get("follow_up_plan", {})
        assert plan.get("objective") == "provide_pricing"
        assert plan.get("should_follow_up") is True

    def test_not_interested_auto_closes(self, monkeypatch):
        fired = self._fire(monkeypatch, "not_interested")
        convo = conversation_store.get_conversation(fired[0]["conversation_id"])
        assert convo.status == ConversationStatus.CLOSED_LOST

    def test_ooo_auto_archives(self, monkeypatch):
        fired = self._fire(monkeypatch, "out_of_office")
        convo = conversation_store.get_conversation(fired[0]["conversation_id"])
        assert convo.status == ConversationStatus.CLOSED_LOST

    def test_no_reply_follow_up_timer(self, monkeypatch):
        fired = self._fire(monkeypatch, "no_reply")
        convo = conversation_store.get_conversation(fired[0]["conversation_id"])
        assert convo.status == ConversationStatus.FOLLOW_UP_PENDING
        timeline_types = {e.event_type for e in conversation_store.get_timeline(fired[0]["conversation_id"])}
        assert TimelineEventType.FOLLOW_UP_SUGGESTED in timeline_types

    def test_follow_up_timer_skipped_after_reply(self, monkeypatch):
        monkeypatch.setenv("SIMULATE_REPLIES", "true")
        ctx = _send_context()
        convo = _make_conversation(ctx)
        from services.conversations.state_machine import transition as state_transition
        convo.status = state_transition(convo.status, ConversationStatus.REPLIED)
        conversation_store.update_conversation(convo)
        sim.maybe_schedule({**ctx, "conversation_id": convo.conversation_id})
        entry = sim._pending[0]
        sim.fire_due(now=sim._parse_dt(entry["fire_at"]) or None)
        assert conversation_store.get_conversation(convo.conversation_id).status == ConversationStatus.REPLIED

    def test_rule_classifier_classifies_scenario_bodies(self):
        from services.conversations.conversation_models import ReplyCategory
        for scenario, expected in (
            ("interested", {ReplyCategory.INTERESTED}),
            ("pricing_request", {ReplyCategory.PRICING_REQUEST}),
            ("referral", {ReplyCategory.REFERRAL}),
            ("out_of_office", {ReplyCategory.OUT_OF_OFFICE}),
            ("not_interested", {ReplyCategory.NOT_INTERESTED}),
        ):
            body = sim.generate_reply_body(scenario, {
                "lead_name": "Jordan", "company": "Bella Vista", "role": "",
            })
            result = classifier_service.classify(body, f"Re: {scenario}")
            assert result.category in expected, f"{scenario}: {result.category} <- {body!r}"
