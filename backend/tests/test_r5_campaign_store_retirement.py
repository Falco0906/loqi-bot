"""R5-B regression coverage for retiring main.py's session-local campaign map."""
from __future__ import annotations

import main as main_module


def test_copilot_context_reads_canonical_workspace_campaigns(monkeypatch):
    def load_workspace_state(owner_id, include_details=False, workspace_id="", canonical_only=False):
        assert owner_id == "owner-1"
        assert workspace_id == "workspace-1"
        assert canonical_only is True
        return {
            "campaigns": [{"id": "campaign-1", "name": "Canonical campaign", "lead_count": 2}],
            "drafts": [],
        }

    monkeypatch.setattr("services.workspace.state.load_workspace_state", load_workspace_state)

    context = main_module._build_copilot_workspace_context(
        "session-token",
        user_id="owner-1",
        workspace_id="workspace-1",
    )

    assert not hasattr(main_module, "campaign_store")
    assert context["snapshot"]["campaigns"][0]["name"] == "Canonical campaign"
