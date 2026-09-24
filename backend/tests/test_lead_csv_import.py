import pytest

from services.leads.service import LeadImportError, parse_csv_preview, suggested_mapping
import services.leads.service as lead_service


def test_csv_preview_maps_known_columns_and_reports_invalid_rows():
    result = parse_csv_preview("First Name,Email,Company,Unmapped\nAda,ada@example.com,Acme,x\n,,,x\n")
    assert result["mapping"] == {"First Name": "first_name", "Email": "email", "Company": "company"}
    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == [{"row": 3, "reason": "Provide at least a name, email, or company"}]
    assert result["unmapped_columns"] == ["Unmapped"]


def test_csv_preview_rejects_empty_or_headerless_input():
    with pytest.raises(LeadImportError, match="empty"):
        parse_csv_preview("")
    with pytest.raises(LeadImportError, match="empty"):
        parse_csv_preview("\n\n")


def test_mapping_never_maps_unknown_columns():
    assert suggested_mapping(["Email", "Secret note"]) == {"Email": "email"}


@pytest.mark.asyncio
async def test_import_skips_workspace_duplicates_and_keeps_other_rows(monkeypatch):
    class Repo:
        async def list_by_email(self, workspace_id, email):
            assert workspace_id == "workspace-a"
            return [object()] if email == "exists@example.com" else []

    imported = []
    async def persist(workspace_id, lead):
        imported.append((workspace_id, lead))
        return "lead-new"

    monkeypatch.setattr(lead_service, "WorkspaceLeadRepository", Repo)
    monkeypatch.setattr(lead_service, "import_workspace_lead", persist)
    result = await lead_service.import_csv_rows("workspace-a", "actor-a", [
        {"row": 2, "lead": {"email": "exists@example.com"}},
        {"row": 3, "lead": {"email": "new@example.com", "name": "New"}},
        {"row": 4, "lead": {"email": "new@example.com", "name": "Duplicate"}},
    ])
    assert result["imported"] == 1
    assert len(result["duplicates"]) == 2
    assert imported == [("workspace-a", {"email": "new@example.com", "name": "New", "source": "csv_import"})]
