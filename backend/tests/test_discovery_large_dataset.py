"""604-candidate HTTP/worker regression with process-local synthetic persistence.

No listener, database or existing server is used. These tests exercise result
pages through HTTP, not browser rendering or real PostgREST semantics.
"""
import time

import pytest

from services.job_engine.storage import JobStorage
from tests.discovery_backend.store import A, B, FOREIGN, Query
from tests.test_discovery_backend import isolated  # Reuse the guarded fixture.
from tests.discovery_backend.datasets import lead_id


BROAD_QUERY = "operations leaders at ecommerce companies"
pytestmark = pytest.mark.parametrize("isolated", ["large"], indirect=True)


@pytest.fixture
def large_case(isolated, monkeypatch):
    client, app = isolated
    store = app.state.synthetic
    # Shared startup builder seeds this test's private store before requests.
    assert store.tables["jobs"] == store.tables["discoveries"] == []
    assert store.profile == "large"
    assert len({row["id"] for row in store.tables["workspace_leads"]}) == 607
    reads, writes = [], []
    faults = {"candidate_read": False}
    execute = Query.execute
    insert = Query.insert

    def observed_execute(query):
        paged = (query.operation == "select" and query.cap == 500
                 and query.name in {"workspace_leads", "search_results"})
        if paged and query.name == "workspace_leads" and faults["candidate_read"]:
            raise RuntimeError("Synthetic canonical candidate retrieval failure")
        response = execute(query)
        if paged:
            ids = [row["lead_data"]["workspace_lead_id"] if query.name == "search_results"
                   else row["id"] for row in response.data]
            reads.append((query.name, query.offset, list(query.orders), ids))
        return response

    def observed_insert(query, payload):
        if query.name == "search_results":
            writes.append([row["lead_data"]["workspace_lead_id"] for row in payload])
        return insert(query, payload)

    # Observers delegate unchanged; matching, paging and persistence stay real.
    monkeypatch.setattr(Query, "execute", observed_execute)
    monkeypatch.setattr(Query, "insert", observed_insert)
    return client, app, reads, writes, faults


def run_search(client, app, query=BROAD_QUERY, filters=None):
    reply = client.post("/api/discoveries", json={
        "query": query, "initiation": "manual", "filters": filters or {},
    })
    assert reply.status_code == 200, reply.text
    identity = reply.json()["discovery_id"]
    # Bound test observation only; do not alter application request timeouts.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(f"/api/discoveries/{identity}")
        assert response.status_code == 200, response.text
        run = response.json()["discovery"]
        with app.state.synthetic.lock:
            job = next(row.copy() for row in app.state.synthetic.tables["jobs"]
                       if row["discovery_id"] == identity)
        if run["status"] in {"completed", "failed"} and job["status"] in {"completed", "failed"}:
            return run, job
        time.sleep(.01)
    pytest.fail(f"Synthetic Discovery {identity} did not reach a terminal run/job state within 15 seconds")


def assert_accounting(outcomes, expected, evaluated, exclusions):
    assert outcomes["retrieved_count"] == 604
    assert outcomes["filtered_candidate_count"] == outcomes["evaluated_count"] == evaluated
    assert outcomes["matched_count"] == expected
    assert {key: count for key, count in outcomes["exclusions"].items() if count} == exclusions
    assert outcomes["retrieved_count"] == expected + sum(outcomes["exclusions"].values())
    pre_match = sum(outcomes["exclusions"].get(key, 0)
                    for key in ("explicit_filter", "explicit_keywords", "literal_query"))
    assert outcomes["retrieved_count"] == evaluated + pre_match
    assert evaluated == expected + sum(outcomes["exclusions"].values()) - pre_match


@pytest.mark.parametrize("query,filters,indices,evaluated,exclusions", [
    (BROAD_QUERY, {}, range(1, 603), 604, {"role": 1, "industry": 1}),
    (BROAD_QUERY, {"location": "London"}, range(1, 601), 602,
     {"explicit_filter": 2, "role": 1, "industry": 1}),
    (BROAD_QUERY, {"industry": "ecommerce"}, range(1, 602), 602,
     {"explicit_filter": 2, "role": 1}),
    ("CTO", {}, [], 604, {"role": 604}),
], ids=["broad-602", "london-600", "industry-601", "completed-zero"])
def test_large_search_exact_ids_pages_and_accounting(large_case, query, filters, indices, evaluated, exclusions):
    client, app, reads, writes, _ = large_case
    store = app.state.synthetic
    canonical_ids = {row["id"] for row in store.tables["workspace_leads"]}
    expected = {lead_id(index) for index in indices}
    run, job = run_search(client, app, query, filters)
    assert run["status"] == job["status"] == "completed"
    assert job["result_ready"] is True
    assert run["summary"]["lead_count"] == len(expected)
    outcomes = run["summary"]["candidate_outcomes"]
    assert_accounting(outcomes, len(expected), evaluated, exclusions)
    assert run["metadata"]["candidate_outcomes"] == outcomes
    assert outcomes["unverified_match_count"] == int(602 in indices)

    # Observe actual repository retrieval past its 500-row boundary.
    candidate_reads = [row for row in reads if row[0] == "workspace_leads"]
    assert [(row[1], len(row[3])) for row in candidate_reads] == [(0, 500), (500, 104)]
    assert all(row[2] == [("id", False)] for row in candidate_reads)
    assert [identity for row in candidate_reads for identity in row[3]] == [lead_id(i) for i in range(1, 605)]

    staged = sorted((row for row in store.tables["search_results"] if row["job_id"] == job["id"]),
                    key=lambda row: row["rank"])
    staged_ids = [row["lead_data"]["workspace_lead_id"] for row in staged]
    assert len(staged_ids) == len(set(staged_ids)) == len(expected)
    assert set(staged_ids) == expected
    assert [row["rank"] for row in staged] == list(range(1, len(expected) + 1))
    assert writes == ([staged_ids] if expected else [])
    scores = {row["id"]: (row["metadata"].get("qualification") or {}).get("final_score")
              for row in store.tables["workspace_leads"] if row["id"] in expected}
    assert staged_ids == sorted(expected, key=lambda identity: (-scores[identity], identity))
    staged_reads = [row for row in reads if row[0] == "search_results"]
    assert [(row[1], len(row[3])) for row in staged_reads] == (
        [(0, 500), (500, len(expected) - 500)] if expected else [(0, 0)])
    assert all(row[2] == [("rank", False), ("id", False)] for row in staged_reads)
    assert [identity for row in staged_reads for identity in row[3]] == staged_ids
    assert [row["workspace_lead_id"] for row in JobStorage().get_search_results(job["id"])] == staged_ids
    links = run["discovery_leads"]
    assert [row["lead_id"] for row in sorted(links, key=lambda row: row["rank"])] == staged_ids
    assert len(links) == len(expected)

    # These are the real HTTP result pages consumed by the UI, not UI execution.
    expected_order = sorted(expected, key=lambda identity: (
        "synthetic shop", f"person {int(identity[-12:])}".lower(), "synthetic", identity))
    params = {"q": query, "discovery_id": run["id"], **filters}
    page_count = max(1, (len(expected) + 49) // 50)
    actual = []
    for page in range(1, page_count + 2):
        response = client.get("/api/web/session/_/leads", params={**params, "page": page})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == len(expected)
        ids = [row["id"] for row in body["leads"]]
        assert ids == expected_order[(page - 1) * 50:page * 50]
        actual.extend(ids)
    assert actual == expected_order
    assert len(actual) == len(set(actual)) == len(expected)
    reread = client.get("/api/web/session/_/leads", params={**params, "page": 1})
    assert reread.status_code == 200
    assert [row["id"] for row in reread.json()["leads"]] == expected_order[:50]
    controls = client.get("/api/web/session/_/leads", headers={"x-workspace-id": B})
    assert controls.status_code == 200
    assert {row["id"] for row in controls.json()["leads"]} == {lead_id(605), lead_id(606)}
    assert client.get("/api/web/session/_/leads", headers={"x-workspace-id": FOREIGN}).status_code == 404

    if not filters and query == BROAD_QUERY:
        replay, replay_job = run_search(client, app)
        assert replay["status"] == replay_job["status"] == "completed"
        assert replay["id"] != run["id"]  # Searches are separate runs, not idempotent POSTs.
        assert replay["summary"]["lead_count"] == len(expected)
        replay_ids = [row["lead_id"] for row in replay["discovery_leads"]]
        assert len(replay_ids) == len(set(replay_ids)) == len(expected)
        assert set(replay_ids) == expected
    assert {row["id"] for row in store.tables["workspace_leads"]} == canonical_ids
    assert all("qualification" not in row["metadata"] for row in store.tables["workspace_leads"]
               if row["workspace_id"] != A)
    assert app.state.blocked == []


@pytest.mark.parametrize("mode,stored", [("fail-staging", 0), ("truncate-staging", 601)])
def test_large_incomplete_staging_is_failed(large_case, mode, stored):
    client, app, reads, writes, _ = large_case
    assert client.post("/__loqi_test/fault", json={"mode": mode}).status_code == 200
    run, job = run_search(client, app)
    assert run["status"] == job["status"] == "failed"
    assert job["result_ready"] is False
    assert run["summary"]["error_kind"] in {"execution", "persistence"}
    assert_accounting(run["metadata"]["candidate_outcomes"], 602, 604, {"role": 1, "industry": 1})
    assert len(writes) == 1
    assert len(writes[0]) == len(set(writes[0])) == 602
    assert set(writes[0]) == {lead_id(i) for i in range(1, 603)}
    assert len(app.state.synthetic.tables["search_results"]) == stored
    staged = JobStorage().get_search_results(job["id"])
    assert [row["workspace_lead_id"] for row in staged] == writes[0][:stored]
    linked = [row["lead_id"] for row in run["discovery_leads"]]
    assert len(linked) == len(set(linked))
    assert set(linked) <= set(writes[0][:stored])
    if mode == "truncate-staging":
        assert run["summary"]["persistence"] == "partial_failed"
        assert run["summary"]["staged_lead_count"] == 601
        assert any(row[0] == "search_results" and row[1] == 500 for row in reads)
    assert app.state.blocked == []


def test_large_candidate_retrieval_failure_is_not_completed_zero(large_case):
    client, app, _, writes, faults = large_case
    faults["candidate_read"] = True
    run, job = run_search(client, app)
    assert run["status"] == job["status"] == "failed"
    assert job["result_ready"] is False
    assert run["summary"]["error_kind"] == "execution"
    assert writes == []
    assert app.state.synthetic.tables["search_results"] == []
    assert run["discovery_leads"] == []
    assert app.state.blocked == []
