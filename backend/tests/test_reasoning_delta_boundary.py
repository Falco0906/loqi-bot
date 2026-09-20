"""Regression coverage for the durable reasoning-delta boundary."""

from services.reasoning.coordinator import ReasoningCoordinator


def _snapshot(delta: dict | None = None) -> dict:
    snapshot = {
        "campaigns": [],
        "drafts": {},
        "jobs": {},
        "memory": {},
        "total_leads": 0,
        "timeline": [],
    }
    if delta is not None:
        snapshot["_delta"] = delta
    return snapshot


def test_missing_delta_stays_empty_even_when_legacy_session_token_is_supplied(monkeypatch):
    """Reasoning never falls back to the session-keyed World Model store."""
    import services.world_model.publisher as publisher

    def unexpected_store_read():
        raise AssertionError("reasoning must not read the in-memory World Model")

    monkeypatch.setattr(publisher, "get_store", unexpected_store_read)

    result = ReasoningCoordinator().analyze(_snapshot(), session_token="legacy-session")

    assert result["_briefing_context"].workspace_delta == {}


def test_supplied_durable_delta_flows_through_reasoning_unchanged():
    durable_delta = {
        "event_count": 2,
        "event_range": [4, 5],
        "new_campaigns": 1,
        "changed_campaigns": 1,
        "new_drafts": 0,
    }

    result = ReasoningCoordinator().analyze(_snapshot(durable_delta))

    assert result["_briefing_context"].workspace_delta is durable_delta
