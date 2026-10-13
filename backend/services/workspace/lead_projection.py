"""Project lead facts owned by one workspace, never shared global profiles.

Global email/domain identities are deduplication keys, not authorization to
read another workspace's imported or enriched fields. Missing local facts
remain missing. Existing rows are not backfilled from those global records.
"""
from collections.abc import Mapping
from typing import Any


def workspace_lead_context(row: Any) -> dict[str, Any]:
    metadata = row.get("metadata", {}) if isinstance(row, Mapping) else getattr(row, "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    provider = metadata.get("provider_context")
    imported = metadata.get("csv_import")
    context = {
        **(provider if isinstance(provider, dict) else {}),
        **(imported if isinstance(imported, dict) else {}),
    }
    result = {
        key: value.strip() for key, value in context.items()
        if key in {"company", "website", "domain", "location", "industry", "description",
                   "city", "country", "revenue_band", "growth_stage", "company_size"}
        and isinstance(value, str)
    }
    employees = context.get("employee_count")
    if isinstance(employees, int) and not isinstance(employees, bool) and employees >= 0:
        result["employee_count"] = employees
    for key in ("buying_signals", "recent_events", "pain_points"):
        if isinstance(context.get(key), list):
            result[key] = context[key]
    if isinstance(context.get("technology"), dict):
        result["technology"] = context["technology"]
    return result


def workspace_lead_fields(row: Any) -> dict[str, str]:
    """Bounded display/search fields from the authorized workspace row only."""
    def text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    def field(name: str) -> str:
        return text(row.get(name) if isinstance(row, Mapping) else getattr(row, name, ""))

    context = workspace_lead_context(row)
    fields = {name: field(name) for name in (
        "first_name", "last_name", "email", "title", "phone", "linkedin_url",
    )}
    fields.update({name: text(context.get(name)) for name in (
        "company", "website", "location", "industry",
    )})
    fields["website"] = fields["website"] or text(context.get("domain"))
    return fields
