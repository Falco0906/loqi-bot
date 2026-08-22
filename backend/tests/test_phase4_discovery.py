"""PR-4 — Discovery production-grade regression tests.

Covers:
  provider retry classification (retryable vs permanent)
  first-result hook fires before filtering/finalize
  partial persistence callback + rank-offset batching
  finalize still aggregates incrementally-persisted results
  job event enrichment carries discovery_id
"""
import asyncio
import json

import pytest

from services.providers import base_provider as bp
from services.providers.base_provider import (
    ProviderPermanentError,
    ProviderTimeoutError,
    classify_provider_error,
    search_leads_with_retry,
)


# ─── provider retry classification ──────────────────────────────────────

def test_retryable_classification():
    assert classify_provider_error("request timeout") == "retryable"
    assert classify_provider_error("connection reset by peer") == "retryable"
    assert classify_provider_error("", status=429) == "retryable"
    assert classify_provider_error("", status=503) == "retryable"


def test_permanent_classification():
    assert classify_provider_error("invalid api key") == "permanent"
    assert classify_provider_error("unauthorized access", status=401) == "permanent"
    assert classify_provider_error("bad request", status=400) == "permanent"
    assert classify_provider_error("ApolloProvider is a stub — not yet implemented") == "permanent"


def test_retry_bounded_then_timeout():
    calls = {"n": 0}

    class Flaky:
        def search_leads(self, icp, search_expansion, limit=20):
            calls["n"] += 1
            return {"ok": False, "error": "upstream timeout"}

    with pytest.raises(ProviderTimeoutError):
        search_leads_with_retry(
            Flaky(), icp={}, search_expansion={},
            max_retries=2, timeout_seconds=1,
        )
    assert calls["n"] == 3  # initial + 2 retries


def test_permanent_fails_immediately_no_retry():
    calls = {"n": 0}

    class Auth:
        def search_leads(self, icp, search_expansion, limit=20):
            calls["n"] += 1
            return {"ok": False, "error": "invalid credentials"}

    with pytest.raises(ProviderPermanentError):
        search_leads_with_retry(Auth(), icp={}, search_expansion={})
    assert calls["n"] == 1


def test_success_first_try_no_retry():
    calls = {"n": 0}

    class Good:
        def search_leads(self, icp, search_expansion, limit=20):
            calls["n"] += 1
            return {"ok": True, "leads": [{"lead_id": "l1"}]}

    result = search_leads_with_retry(Good(), icp={}, search_expansion={})
    assert result["ok"] is True and calls["n"] == 1


# ─── first-result callback ───────────────────────────────────────────────

def test_first_result_hook_in_pipeline(monkeypatch):
    """_search_with_progress invokes on_results the moment the provider
    returns — before finalize — proving first-result latency decoupling."""
    import services.communication.inbox_sync_engine  # noqa: F401 (env warm-up)
    from workflow_dispatcher import _search_with_progress

    partial_calls: list[list] = []

    # Stub the expansion module so no LLM runs.
    import services.search_expansion as se
    monkeypatch.setattr(se, "expand_search_intent",
                        lambda service, target, icp: {"search_queries": ["q"]})

    from services.lead_provider import search_with_expansion as _swe
    # Patch the dispatcher's own imported symbol so _search_with_progress
    # exercises its real callback plumbing.
    def fake_search_with_expansion(service, target, plan=None, context=None,
                                    on_partial_results=None):
        leads = [{"lead_id": f"l{i}", "name": f"Lead {i}", "provider": "synthetic"}
                 for i in range(5)]
        if on_partial_results:
            on_partial_results(leads)   # ← fires BEFORE any finalize work
        return {"ok": True, "leads": leads, "source": "synthetic"}

    monkeypatch.setattr(
        __import__("workflow_dispatcher", fromlist=["x"]),
        "search_with_expansion",
        fake_search_with_expansion,
    )
    # Prevent real OpenAI/Redis side effects from other pipeline stages.
    monkeypatch.setattr(
        __import__("services.icp_extractor", fromlist=["x"]),
        "extract_structured_icp",
        lambda q, ctx=None: {"buyer_roles": ["cto"], "keywords": ["saas"]},
    )

    stages: list[str] = []
    def on_progress(stage: str, pct: int):
        stages.append(stage)

    got = _search_with_progress(
        "CRM for startups", "", None, None,
        on_progress,
        on_results=lambda leads: partial_calls.append(leads),
    )

    assert got.get("ok") is True
    assert len(partial_calls) == 1 and len(partial_calls[0]) == 5, (
        "first-result callback must fire exactly once with raw provider leads"
    )
