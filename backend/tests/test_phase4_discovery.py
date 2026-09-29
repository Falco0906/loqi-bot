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


def test_provider_no_matches_is_a_completed_zero_result_search(monkeypatch):
    """A valid empty provider response must not be mislabeled as a failure."""
    from services.discovery import providers

    class EmptyProvider:
        def search_leads(self, *, icp, search_expansion, limit):
            return {"ok": True, "provider": "synthetic", "leads": []}

    monkeypatch.setattr(providers, "get_provider", lambda: EmptyProvider())
    monkeypatch.setattr(
        "services.discovery.search_expansion.expand_search_intent",
        lambda *_args, **_kwargs: {"search_queries": ["founder saas"]},
    )

    result = providers.search_with_expansion(
        "CRM", "startups", plan={"industries": [], "decision_maker_roles": []},
    )

    assert result["ok"] is True
    assert result["empty_result"] is True
    assert result["leads"] == []


def test_provider_configuration_failure_is_a_safe_terminal_provider_failure(monkeypatch):
    """Provider construction must not escape as a generic runner crash."""
    from services.discovery import providers

    monkeypatch.setattr(
        providers,
        "get_provider",
        lambda: (_ for _ in ()).throw(ValueError("unknown provider")),
    )

    result = providers.search_with_expansion("CRM", "startups")

    assert result == {
        "ok": False,
        "provider_error_kind": "permanent",
        "error": "Lead provider configuration is unavailable",
        "leads": [],
        "icp": None,
        "context_provenance": {},
    }


@pytest.mark.asyncio
async def test_runner_preserves_provider_failure_kind_for_discovery_status():
    """Timeout/permanent provider failures reach the durable discovery owner."""
    from services.job_engine.models import Job
    from services.job_engine.runner import BackgroundRunner

    updates: list[dict] = []

    class Storage:
        def update_job(self, *_args, **_kwargs):
            return True

    async def failed_provider(*_args):
        return {
            "ok": False,
            "provider_error_kind": "timeout",
            "error": "provider timeout after retry budget",
        }

    runner = BackgroundRunner(Storage())
    await runner._run_wrapper(
        Job(id="job-1", type="search", discovery_id="discovery-1"),
        failed_provider,
        on_update=updates.append,
    )

    assert updates[-1]["status"] == "failed"
    assert updates[-1]["error_kind"] == "timeout"


# ─── first-result callback ───────────────────────────────────────────────

def test_first_result_hook_in_pipeline(monkeypatch):
    """_search_with_progress invokes on_results the moment the provider
    returns — before finalize — proving first-result latency decoupling."""
    import services.communication.inbox_sync_engine  # noqa: F401 (env warm-up)
    from workflow_dispatcher import _search_with_progress

    partial_calls: list[list] = []

    # Stub the expansion module so no LLM runs.
    import services.discovery.search_expansion as se
    monkeypatch.setattr(se, "expand_search_intent",
                        lambda service, target, icp: {"search_queries": ["q"]})

    from services.discovery.providers import search_with_expansion as _swe
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
        __import__("services.discovery.icp", fromlist=["x"]),
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


def test_pipeline_does_not_expand_the_same_query_before_provider_search(monkeypatch):
    """The provider pipeline owns one expansion; dispatcher must not duplicate it."""
    from workflow_dispatcher import _search_with_progress
    import services.discovery.search_expansion as expansion

    def duplicate_expansion(*_args, **_kwargs):
        raise AssertionError("dispatcher must not preflight query expansion")

    monkeypatch.setattr(expansion, "expand_search_intent", duplicate_expansion)
    monkeypatch.setattr(
        __import__("workflow_dispatcher", fromlist=["x"]),
        "search_with_expansion",
        lambda *_args, **_kwargs: {"ok": True, "leads": []},
    )

    result = _search_with_progress(
        "CRM", "startups", {"industries": [], "decision_maker_roles": []}, {},
        lambda *_args: None,
    )

    assert result == {"ok": True, "leads": []}


@pytest.mark.asyncio
async def test_distinct_queries_reach_the_same_provider_workflow_without_a_default(monkeypatch):
    """Discovery must use each explicit query, never a recovered hard-coded target."""
    import workflow_dispatcher
    from services.job_engine.models import Job

    captured: list[tuple[str, str]] = []

    async def context(_owner_id, query=""):
        return {"query": query, "provenance": {}}

    def search(service, target, _plan, _context, _progress, _on_results):
        captured.append((service, target))
        return {"ok": True, "leads": []}

    monkeypatch.setattr(
        "services.discovery.context.retrieve_discovery_context", context,
    )
    monkeypatch.setattr(
        "services.discovery.plan.derive_discovery_plan", lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(workflow_dispatcher, "_search_with_progress", search)

    await workflow_dispatcher.run_search_workflow(
        Job(id="job-india", user_id="owner-1", query="SaaS founders in India"),
        lambda *_args: None,
    )
    await workflow_dispatcher.run_search_workflow(
        Job(
            id="job-us", user_id="owner-1",
            query="ecommerce companies hiring sales leaders in the US",
        ),
        lambda *_args: None,
    )

    assert captured == [
        ("SaaS founders", "India"),
        ("ecommerce companies hiring sales leaders", "the US"),
    ]
