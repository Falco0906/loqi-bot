"""CSV preview/import and read model for canonical ``workspace_leads``."""
from __future__ import annotations

import csv
import io
import logging
import asyncio
from dataclasses import dataclass
from typing import Any

from services.persistence.launch import (
    CompanyRepository,
    LeadRepository,
    LeadSignalRepository,
    WorkspaceLeadRepository,
)
from services.workspace.state import import_workspace_lead


log = logging.getLogger("loqi.leads")

MAPPABLE_FIELDS = {
    "first_name", "last_name", "name", "email", "company", "website", "title",
    "linkedin_url", "location", "industry", "company_size", "phone",
}
ALIASES = {
    "first name": "first_name", "firstname": "first_name", "last name": "last_name",
    "lastname": "last_name", "full name": "name", "full_name": "name",
    "job title": "title", "job_title": "title", "company name": "company",
    "company website": "website", "linkedin": "linkedin_url", "linkedin url": "linkedin_url",
    "phone number": "phone", "company size": "company_size",
}


class LeadImportError(ValueError):
    pass


def suggested_mapping(headers: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for header in headers:
        normalized = header.strip().lower().replace("-", " ").replace("_", " ")
        field = ALIASES.get(normalized, normalized.replace(" ", "_"))
        if field in MAPPABLE_FIELDS and field not in result.values():
            result[header] = field
    return result


def parse_csv_preview(content: str, mapping: dict[str, str] | None = None) -> dict[str, Any]:
    if not content or not content.strip():
        raise LeadImportError("CSV file is empty")
    try:
        reader = csv.DictReader(io.StringIO(content))
        headers = [header.strip() for header in (reader.fieldnames or []) if header and header.strip()]
    except csv.Error as error:
        raise LeadImportError("CSV could not be parsed") from error
    if not headers:
        raise LeadImportError("CSV must include a header row")
    active_mapping = {key: value for key, value in (mapping or suggested_mapping(headers)).items()
                      if key in headers and value in MAPPABLE_FIELDS}
    rows: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for number, raw in enumerate(reader, start=2):
        row = {key: (value or "").strip() for key, value in raw.items() if key}
        mapped = {field: row.get(column, "") for column, field in active_mapping.items()}
        if not any(mapped.get(field) for field in ("email", "name", "first_name", "last_name", "company")):
            invalid.append({"row": number, "reason": "Provide at least a name, email, or company"})
            continue
        rows.append({"row": number, "lead": mapped})
    return {
        "headers": headers, "mapping": active_mapping,
        "unmapped_columns": [header for header in headers if header not in active_mapping],
        "total_rows": len(rows) + len(invalid), "valid_rows": len(rows),
        "invalid_rows": invalid, "preview": rows[:20], "rows": rows,
    }


async def import_csv_rows(workspace_id: str, actor_user_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    repo = WorkspaceLeadRepository()
    imported: list[str] = []
    duplicates: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    seen_emails: set[str] = set()
    for item in rows:
        number = int(item.get("row") or 0)
        lead = dict(item.get("lead") or {})
        email = str(lead.get("email") or "").strip().lower()
        if email and email in seen_emails:
            duplicates.append({"row": number, "reason": "Duplicate email in this CSV"})
            continue
        if email:
            seen_emails.add(email)
            if await repo.list_by_email(workspace_id, email):
                duplicates.append({"row": number, "reason": "Lead already exists in this workspace"})
                continue
        lead["source"] = "csv_import"
        try:
            lead_id = await import_workspace_lead(workspace_id, lead)
        except Exception:
            invalid.append({"row": number, "reason": "Lead could not be persisted"})
            continue
        if lead_id:
            imported.append(lead_id)
        else:
            invalid.append({"row": number, "reason": "Lead could not be persisted"})
    return {"imported": len(imported), "imported_ids": imported, "duplicates": duplicates, "invalid": invalid}


async def list_workspace_leads(workspace_id: str, query: str = "", page: int = 1, page_size: int = 50,
                               filters: dict[str, str] | None = None) -> dict[str, Any]:
    workspace_rows = await WorkspaceLeadRepository().list_for_workspace(workspace_id)
    profiles = LeadRepository()
    companies = CompanyRepository()
    records: list[dict[str, Any]] = []
    needle = query.strip().lower(); filters = filters or {}
    for row in workspace_rows:
        profile = await profiles.get(row.lead_id) if row.lead_id else None
        company = await companies.get(row.company_id) if row.company_id else None
        record = {
            "id": row.id, "first_name": row.first_name or getattr(profile, "first_name", ""),
            "last_name": row.last_name or getattr(profile, "last_name", ""),
            "email": row.email or getattr(profile, "email", ""), "title": row.title or getattr(profile, "title", ""),
            "phone": row.phone or getattr(profile, "phone", ""), "linkedin_url": row.linkedin_url or getattr(profile, "linkedin_url", ""),
            "company": getattr(company, "name", ""), "website": getattr(company, "website", ""),
            "location": getattr(company, "location", ""), "industry": getattr(company, "industry", ""),
            "status": row.lead_status,
        }
        searchable = " ".join(str(value or "") for value in record.values()).lower()
        matches_filters = all(
            not value or value.lower() in str(record.get(field, "") or "").lower()
            for field, value in filters.items()
        )
        if (not needle or needle in searchable) and matches_filters:
            records.append(record)
    records.sort(key=lambda record: (record["company"].lower(), record["last_name"].lower(), record["first_name"].lower()))
    total = len(records); start = max(page - 1, 0) * page_size
    return {"leads": records[start:start + page_size], "total": total, "page": page, "page_size": page_size}


async def analyze_workspace_leads(
    workspace_id: str,
    actor_user_id: str,
    lead_ids: list[str],
) -> dict[str, Any]:
    """Analyze selected workspace leads from durable facts only.

    This is the Beta intelligence boundary: it never sources, enriches through
    an external provider, sends email, or persists generated analysis.  Each
    requested id is fetched through its canonical workspace scope instead of
    loading a broad lead list and filtering it in application memory.
    """
    if not lead_ids or len(lead_ids) > 50 or len(set(lead_ids)) != len(lead_ids):
        raise LeadImportError("Provide between 1 and 50 unique lead IDs")

    selected_leads = await _load_selected_workspace_leads(workspace_id, lead_ids)
    if len(selected_leads) != len(lead_ids):
        raise LeadImportError("One or more selected leads are unavailable in this workspace")

    guidance = await _business_guidance(actor_user_id, workspace_id)
    results: list[dict[str, Any]] = []
    for lead in selected_leads:
        try:
            results.append(await _analyze_selected_lead(lead))
        except Exception as error:
            # A malformed canonical record must not discard useful analysis for
            # other explicitly selected leads. Do not include PII in the log.
            log.exception("lead intelligence failed for workspace_lead_id=%s", lead["id"])
            results.append({
                "lead": _lead_display(lead),
                "status": "failed",
                "error": "This lead could not be analyzed from its current data.",
            })
    return {"results": results, "business_guidance": guidance}


async def generate_workspace_lead_strategy_drafts(
    workspace_id: str,
    actor_user_id: str,
    lead_ids: list[str],
) -> dict[str, Any]:
    """Explicitly generate review-only AI drafts from fresh Phase 4B evidence.

    Re-running the authorized deterministic analysis here makes the server,
    rather than client state or URL parameters, the authority for every model
    input. This function neither persists nor sends generated content.
    """
    from services.intelligence.ai import OpenAIError, generate_evidence_grounded_lead_strategy

    analysis = await analyze_workspace_leads(workspace_id, actor_user_id, lead_ids)
    results: list[dict[str, Any]] = []
    for item in analysis["results"]:
        lead = item["lead"]
        if item["status"] != "completed":
            results.append({
                "lead_id": lead["id"],
                "status": "failed",
                "error": "Strategy and draft require completed lead intelligence.",
            })
            continue
        try:
            generated = await asyncio.to_thread(
                generate_evidence_grounded_lead_strategy,
                {
                    "facts": item["facts"],
                    "observed_signals": item["observed_signals"],
                    "derived_assessment": item["derived_assessment"],
                    "business_guidance": analysis["business_guidance"],
                },
            )
            results.append({"lead_id": lead["id"], "status": "completed", **generated})
        except OpenAIError as error:
            log.warning(
                "lead strategy generation failed workspace_lead_id=%s error_type=%s",
                lead["id"], type(error).__name__,
            )
            results.append({
                "lead_id": lead["id"],
                "status": "failed",
                "error": "Strategy and draft could not be generated right now.",
            })
    return {"results": results}


async def _load_selected_workspace_leads(
    workspace_id: str,
    lead_ids: list[str],
) -> list[dict[str, Any]]:
    """Load exactly the requested canonical workspace-lead records."""
    workspace_leads = WorkspaceLeadRepository()
    profiles = LeadRepository()
    companies = CompanyRepository()
    selected: list[dict[str, Any]] = []
    for lead_id in lead_ids:
        row = await workspace_leads.get_for_workspace(lead_id, workspace_id)
        if row is None or getattr(row, "deleted_at", None) is not None:
            continue
        profile = await profiles.get(row.lead_id) if row.lead_id else None
        company = await companies.get(row.company_id) if row.company_id else None
        selected.append(_canonical_analysis_lead(row, profile, company))
    return selected


def _canonical_analysis_lead(row: Any, profile: Any, company: Any) -> dict[str, Any]:
    """Make the bounded canonical record accepted by deterministic services."""
    first_name = row.first_name or getattr(profile, "first_name", "")
    last_name = row.last_name or getattr(profile, "last_name", "")
    industry = getattr(company, "industry", "") or ""
    company_metadata = getattr(company, "metadata", {}) or {}
    workspace_metadata = getattr(row, "metadata", {}) or {}
    record = {
        "id": row.id,
        "first_name": first_name,
        "last_name": last_name,
        "name": f"{first_name} {last_name}".strip(),
        "email": row.email or getattr(profile, "email", ""),
        "title": row.title or getattr(profile, "title", ""),
        "phone": row.phone or getattr(profile, "phone", ""),
        "linkedin_url": row.linkedin_url or getattr(profile, "linkedin_url", ""),
        "company": getattr(company, "name", "") or "",
        "website": getattr(company, "website", "") or "",
        "location": getattr(company, "location", "") or "",
        "industry": industry,
        "company_industry": industry,
        "company_description": getattr(company, "description", "") or "",
        "company_employees": getattr(company, "employee_count", None) or 0,
        "company_revenue_band": getattr(company, "revenue_band", "") or "",
        "company_growth_stage": str(company_metadata.get("growth_stage") or ""),
        "company_technology": company_metadata.get("technology") or {},
        "buying_signals": list(company_metadata.get("buying_signals") or []),
        "recent_events": list(company_metadata.get("recent_events") or []),
        "pain_points": list(company_metadata.get("pain_points") or []),
    }
    # The canonical normalizer stores provider qualification under this key.
    # Omit absent scores so generate_lead_intelligence keeps its established
    # neutral fallback rather than treating an unscored CSV lead as zero-fit.
    qualification = workspace_metadata.get("qualification")
    if isinstance(qualification, dict):
        record["commercial_score_breakdown"] = qualification
    return record


async def _analyze_selected_lead(lead: dict[str, Any]) -> dict[str, Any]:
    """Run the existing local-only intelligence services for one lead."""
    from services.enrichment.synthetic_enricher import SyntheticEnricher
    from services.intelligence.account_intelligence import generate_account_intelligence
    from services.intelligence.contact_intelligence import generate_contact_intelligence
    from services.intelligence.lead_intelligence import generate_lead_intelligence

    enrichment = SyntheticEnricher().enrich_lead(lead)
    account = generate_account_intelligence({
        "name": lead["company"],
        "website": lead["website"],
        "industry": lead["industry"],
        "size": str(lead["company_employees"] or ""),
        "buying_signals": lead["buying_signals"],
        "recent_events": lead["recent_events"],
    }, enrichment)
    contact = generate_contact_intelligence(lead, enrichment)
    intelligence = generate_lead_intelligence(lead, enrichment)
    signals = await LeadSignalRepository().list_for_lead(lead["id"])
    return {
        "lead": _lead_display(lead),
        "status": "completed",
        "facts": _facts(lead),
        "observed_signals": [
            {
                "type": signal.signal_type,
                "label": signal.label,
                "strength": signal.strength,
                "source": signal.source,
                "detected_at": str(signal.detected_at),
            }
            for signal in signals
        ],
        "derived_assessment": {
            "priority": _priority(intelligence["fit_score"]),
            "icp_fit": intelligence["fit_score"],
            "why_this_lead": intelligence["why_selected"],
            "recommended_approach": intelligence["recommended_pitch"],
            "lead_intelligence": intelligence,
            "account_intelligence": account,
            "contact_intelligence": contact,
            "enrichment_confidence": enrichment.get("confidence_score", 0),
        },
    }


def _lead_display(lead: dict[str, Any]) -> dict[str, Any]:
    return {
        key: lead.get(key, "")
        for key in ("id", "first_name", "last_name", "email", "title", "company", "website", "location", "industry")
    }


def _facts(lead: dict[str, Any]) -> list[dict[str, str]]:
    """Expose only canonical fields; no generated text belongs here."""
    fields = (
        ("Name", lead["name"]),
        ("Job title", lead["title"]),
        ("Company", lead["company"]),
        ("Website", lead["website"]),
        ("Location", lead["location"]),
        ("Industry", lead["industry"]),
        ("Company size", str(lead["company_employees"] or "")),
    )
    return [
        {"label": label, "value": value, "source": "canonical workspace lead data"}
        for label, value in fields
        if value
    ]


def _priority(fit_score: int) -> str:
    if fit_score >= 70:
        return "high"
    if fit_score >= 40:
        return "medium"
    return "low"


async def _business_guidance(
    actor_user_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    """Retrieve attributable user guidance once for the selected batch."""
    from services.knowledge.context_adapter import retrieve_knowledge_context

    context = await retrieve_knowledge_context(
        actor_user_id,
        # Business guidance is workspace context, not evidence about a named
        # prospect. Retrieve a bounded category set rather than dropping it
        # because a company name is absent from a user-authored Knowledge item.
        query="",
        categories=["company", "icp", "messaging", "sales_offer"],
        limit=8,
        workspace_id=workspace_id,
    )
    return {
        "note": "This is user-provided business guidance, not evidence about a prospect.",
        "items": [
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "summary": str(item.get("summary") or ""),
                "category": str(item.get("category") or ""),
                "source_type": str(item.get("source_type") or ""),
            }
            for item in context.items
        ],
        "source_ids": context.source_ids,
    }
