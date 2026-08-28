"""Canonical read access to durable workspace campaigns."""
from __future__ import annotations

from typing import Any

from services.workspace_state import load_workspace_state


def load_campaigns(
    user_id: str,
    *,
    workspace_id: str = "",
    include_details: bool = True,
) -> list[dict[str, Any]]:
    """Return the caller's durable campaigns for one workspace."""
    state = load_workspace_state(
        user_id,
        workspace_id=workspace_id,
        include_details=include_details,
    )
    return state["campaigns"]
