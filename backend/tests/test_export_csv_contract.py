"""Characterization coverage for the legacy workspace lead CSV export."""
from __future__ import annotations

import csv
import io
from types import SimpleNamespace

import pytest

import services.conversations.legacy_engine as legacy_engine
import services.export.api as export_api
import services.export.service as export_service


SESSION_TOKEN = "resolved-session-token"
OWNER_ID = "owner-1"
WORKSPACE_ID = "workspace-1"


def _request() -> SimpleNamespace:
    return SimpleNamespace(headers={"authorization": "Bearer ignored"})


@pytest.fixture
def authorized_export(monkeypatch):
    async def owner(_request, _session_token=""):
        return OWNER_ID

    async def workspace(_request, owner_id):
        assert owner_id == OWNER_ID
        return SimpleNamespace(workspace_id=WORKSPACE_ID)

    async def session(_request):
        return OWNER_ID, SESSION_TOKEN

    monkeypatch.setattr(
        export_api.identity_dependencies,
        "web_session_token",
        lambda _request: SESSION_TOKEN,
    )
    monkeypatch.setattr(export_api.identity_dependencies, "authenticated_user_id", owner)
    monkeypatch.setattr(export_api.identity_dependencies, "resolve_web_session", session)
    monkeypatch.setattr(
        export_api.workspace_access,
        "resolve_selected_workspace_context",
        workspace,
    )


async def _export():
    return await export_api.export_csv("ignored-path-token", _request())


def _csv_rows(response) -> list[list[str]]:
    content = getattr(response, "body", None)
    if content is None:
        content = response.content
    return list(csv.reader(io.StringIO(content.decode())))


@pytest.mark.asyncio
async def test_export_csv_preserves_columns_field_mapping_and_filename(
    monkeypatch,
    authorized_export,
):
    def load_drafts(owner_id: str, workspace_id: str = ""):
        assert (owner_id, workspace_id) == (OWNER_ID, WORKSPACE_ID)
        return [
            {
                "lead": {
                    "name": "Ada Lovelace",
                    "title": "CTO",
                    "company": "Analytical Engines",
                    "email": "ada@example.com",
                    "linkedin_url": "https://linkedin.example/ada",
                    "company_industry": "Computing",
                }
            },
            {
                "lead": {
                    "first_name": "Grace",
                    "last_name": "Hopper",
                    "title": "Admiral",
                    "company": "Navy",
                    "email": "grace@example.com",
                    "linkedin_url": "https://linkedin.example/grace",
                    "company_industry": "Technology",
                }
            },
        ]

    monkeypatch.setattr(export_service, "load_drafts_only", load_drafts)

    response = await _export()

    assert response.media_type == "text/csv"
    assert response.headers["content-disposition"] == (
        "attachment; filename=loqi-leads-resolved.csv"
    )
    assert _csv_rows(response) == [
        ["Name", "Title", "Company", "Email", "LinkedIn URL", "Industry", "Phone"],
        [
            "Ada Lovelace",
            "CTO",
            "Analytical Engines",
            "ada@example.com",
            "https://linkedin.example/ada",
            "Computing",
            "",
        ],
        [
            "Grace Hopper",
            "Admiral",
            "Navy",
            "grace@example.com",
            "https://linkedin.example/grace",
            "Technology",
            "",
        ],
    ]


def test_export_csv_route_is_registered_and_uses_the_same_contract(
    monkeypatch,
    authorized_export,
    client,
):
    monkeypatch.setattr(
        export_service,
        "load_drafts_only",
        lambda *_args, **_kwargs: [{"lead": {"name": "Ada", "email": "ada@example.com"}}],
    )

    response = client.get(
        "/api/web/session/ignored-path-token/export-csv",
        headers={"Authorization": "Bearer ignored"},
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        "attachment; filename=loqi-leads-resolved.csv"
    )
    assert _csv_rows(response) == [
        ["Name", "Title", "Company", "Email", "LinkedIn URL", "Industry", "Phone"],
        ["Ada", "", "", "ada@example.com", "", "", ""],
    ]


@pytest.mark.asyncio
async def test_export_csv_reads_only_the_authorized_selected_workspace(
    monkeypatch,
    authorized_export,
):
    drafts_by_workspace = {
        WORKSPACE_ID: [{"lead": {"name": "Visible", "email": "visible@example.com"}}],
        "workspace-other": [{"lead": {"name": "Hidden", "email": "hidden@example.com"}}],
    }
    seen: list[tuple[str, str]] = []

    def load_drafts(owner_id: str, workspace_id: str = ""):
        seen.append((owner_id, workspace_id))
        return drafts_by_workspace[workspace_id]

    monkeypatch.setattr(export_service, "load_drafts_only", load_drafts)

    response = await _export()

    assert seen == [(OWNER_ID, WORKSPACE_ID)]
    body = response.body.decode()
    assert "Visible" in body
    assert "Hidden" not in body


@pytest.mark.asyncio
async def test_export_csv_returns_header_only_when_canonical_drafts_are_empty(
    monkeypatch,
    authorized_export,
):
    monkeypatch.setattr(export_service, "load_drafts_only", lambda *_args, **_kwargs: [])

    response = await _export()

    assert _csv_rows(response) == [
        ["Name", "Title", "Company", "Email", "LinkedIn URL", "Industry", "Phone"],
    ]


@pytest.mark.asyncio
async def test_export_csv_legacy_conversation_fallback_cannot_recover_leads(
    monkeypatch,
    authorized_export,
):
    """ConversationEngine's persisted-message read drops lead-list metadata."""
    monkeypatch.setattr(export_service, "load_drafts_only", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        legacy_engine,
        "get_web_session",
        lambda _token: {"id": OWNER_ID, "username": "Owner"},
    )
    monkeypatch.setattr(legacy_engine, "list_workflow_sessions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(legacy_engine, "has_connected_account", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        legacy_engine,
        "list_conversation_messages",
        lambda _user_id: [
            {
                "role": "assistant",
                "message": "Here are your leads",
                "created_at": "2026-01-01T00:00:00Z",
                # This represents data a legacy producer might have stored.
                # ConversationEngine.list_messages intentionally omits it.
                "data": {"leads": [{"name": "Must not leak into export"}]},
            }
        ],
    )

    monkeypatch.setattr(
        legacy_engine.ConversationEngine,
        "get_web_session_summary",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("export must not consult legacy conversation state")
        ),
    )

    response = await _export()

    assert _csv_rows(response) == [
        ["Name", "Title", "Company", "Email", "LinkedIn URL", "Industry", "Phone"],
    ]
