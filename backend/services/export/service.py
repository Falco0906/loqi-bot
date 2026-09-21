"""Build the canonical workspace lead CSV export."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

from services.workspace.state import load_drafts_only


CSV_HEADER = ("Name", "Title", "Company", "Email", "LinkedIn URL", "Industry", "Phone")


@dataclass(frozen=True)
class WorkspaceLeadsCsv:
    content: str
    filename: str


def build_workspace_leads_csv(
    user_id: str,
    workspace_id: str,
    session_token: str,
) -> WorkspaceLeadsCsv:
    """Export the leads attached to the user's canonical workspace drafts."""
    drafts = load_drafts_only(user_id, workspace_id=workspace_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_HEADER)

    for draft in drafts:
        lead = draft.get("lead")
        if not lead:
            continue
        writer.writerow(
            [
                lead.get("name") or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                lead.get("title", ""),
                lead.get("company", ""),
                lead.get("email", ""),
                lead.get("linkedin_url", ""),
                lead.get("company_industry", ""),
                "",
            ]
        )

    return WorkspaceLeadsCsv(
        content=output.getvalue(),
        filename=f"loqi-leads-{session_token[:8]}.csv",
    )
