"""Durable state projection for the canonical web workspace workflow.

The launch foundation introduces first-class tables (campaigns, strategies,
campaign_leads, leads, companies, drafts) as the canonical business storage.
`workflow_events` remains ONLY an event log for audit / replay / timeline.

Write path is dual: every mutation appends the event (kept for compatibility)
and also persists canonical rows. Reads prefer the canonical tables and fall
back to the event projection while backfill is still running.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from services.conversation_store import ensure_workflow_session
from services.persistence.launch import (
    Campaign,
    CampaignLead,
    CampaignLeadRepository,
    CampaignRepository,
    Company,
    CompanyRepository,
    Draft,
    DraftRepository,
    Lead,
    LeadRepository,
    Strategy,
    StrategyRepository,
    Workspace,
    WorkspaceCompany,
    WorkspaceCompanyRepository,
    WorkspaceLead,
    WorkspaceLeadRepository,
    WorkspaceMember,
    WorkspaceMemberRepository,
    WorkspaceRepository,
)
from services.supabase import get_supabase_client


def _utc_iso(dt: datetime | None = None) -> str:
    return (dt or datetime.now(timezone.utc)).isoformat()


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _run(async_fn):
    """Fire an async write from a sync or async context without awaiting."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(async_fn())
    except RuntimeError:
        import threading
        threading.Thread(target=lambda: asyncio.run(async_fn()), daemon=True).start()


def _run_sync(coro_or_fn, timeout: float = 30.0):
    """Run a coroutine to completion from either a sync or async context.

    Accepts either an already-created coroutine or a zero-arg callable that
    returns one.
    """
    coro = coro_or_fn if inspect.iscoroutine(coro_or_fn) else coro_or_fn()
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # Inside a running loop: run in a dedicated thread's loop and block.
    import threading
    holder: dict[str, object] = {}

    def runner():
        holder["value"] = asyncio.run(coro)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    return holder.get("value")


def _session_id(user_id: str) -> str:
    return ensure_workflow_session(
        user_id=user_id,
        channel="workspace",
        session_key=user_id,
    )


# ─── Workspaces ─────────────────────────────────────────────────────────

def ensure_workspace(
    user_id: str,
    *,
    name: str = "Personal Workspace",
    organization_id: str = "",
    slug: str = "",
) -> str | None:
    """Return the workspace id (= its workflow_sessions.id), creating the
    canonical workspaces + workspace_members rows on first touch."""
    try:
        workspace_id = _session_id(user_id)
        if not workspace_id:
            return None
        client = get_supabase_client()
        if client is None:
            return workspace_id

        async def _upsert():
            ws_repo = WorkspaceRepository()
            existing = await ws_repo.get(workspace_id)
            if not existing:
                await ws_repo.save(Workspace(
                    id=workspace_id,
                    organization_id=organization_id or "",
                    name=name,
                    slug=slug or name.replace(" ", "-").lower(),
                    owner_user_id=user_id,
                    status="active",
                ))
            member_repo = WorkspaceMemberRepository()
            member = await member_repo.find_member(workspace_id, user_id)
            if member is None:
                await member_repo.save(WorkspaceMember(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    role="owner",
                    status="active",
                ))
        _run_sync(_upsert())
        return workspace_id
    except Exception as error:
        print(f"[workspace_state] ensure_workspace failed: {error}")
        return _session_id(user_id) or None


# ─── Events (compatibility log) ────────────────────────────────────────

def append_event(user_id: str, event_type: str, payload: dict[str, Any]) -> bool:
    client = get_supabase_client()
    if client is None or not user_id:
        return False
    try:
        session_id = _session_id(user_id)
        result = client.table("workflow_events").insert({
            "workflow_session_id": session_id,
            "event_type": event_type,
            "payload": payload,
            "created_at": _utc_iso(),
        }).select("id").execute()
        return bool(getattr(result, "data", None))
    except Exception as error:
        print(f"[workspace_state] append_event failed: {error}")
        return False


# ─── Canonical writes (dual with events) ───────────────────────────────

def persist_campaign(user_id: str, campaign: dict[str, Any]) -> bool:
    if campaign.get("id"):
        _run(_write_campaign_row(user_id, campaign))
    return append_event(user_id, "campaign.created", {"campaign": campaign})


async def _write_campaign_row(user_id: str, campaign: dict[str, Any]) -> None:
    workspace_id = await _async_workspace(user_id)
    if not workspace_id:
        return
    repo = CampaignRepository()
    entity = Campaign(
        id=str(campaign.get("id")),
        workspace_id=workspace_id,
        organization_id=str(campaign.get("organization_id") or ""),
        name=str(campaign.get("name") or ""),
        objective=str(campaign.get("objective") or ""),
        status=str(campaign.get("status") or "planning"),
        search_query=str(campaign.get("search_query") or ""),
        created_by=user_id,
        created_at=campaign.get("created_at") or datetime.now(timezone.utc),
        updated_at=campaign.get("updated_at") or datetime.now(timezone.utc),
    )
    existing = await repo.get(entity.id)
    if existing is not None:
        entity = existing
        for key in ("name", "objective", "status", "search_query"):
            if campaign.get(key) is not None:
                setattr(entity, key, str(campaign[key]))
        entity.updated_at = datetime.now(timezone.utc)
    await repo.save(entity)

    strategy = campaign.get("strategy")
    if isinstance(strategy, dict):
        await _write_strategy(campaign_id=entity.id, strategy=strategy)


async def _async_workspace(user_id: str) -> str | None:
    client = get_supabase_client()
    if client is None:
        return _session_id(user_id) or None
    ws_id = _session_id(user_id)
    if not ws_id:
        return None
    ws_repo = WorkspaceRepository()
    if await ws_repo.get(ws_id) is None:
        await ws_repo.save(Workspace(
            id=ws_id,
            owner_user_id=user_id,
            name="Personal Workspace",
            status="active",
        ))
    return ws_id


async def _write_strategy(campaign_id: str, strategy: dict[str, Any]) -> None:
    repo = StrategyRepository()
    current = None
    try:
        current = await repo.current_for_campaign(campaign_id)
    except Exception:
        current = None
    version = (current.version + 1) if current else 1
    if current:
        current.is_current = False
        await repo.save(current)
    await repo.save(Strategy(
        campaign_id=campaign_id,
        version=version,
        is_current=True,
        objective=str(strategy.get("objective") or ""),
        audience=str(strategy.get("audience") or ""),
        channel=str(strategy.get("channel") or ""),
        messaging_angle=str(strategy.get("messaging_angle") or ""),
        sequence=[str(x) for x in (strategy.get("sequence") or [])],
        tone=str(strategy.get("tone") or ""),
        persona=str(strategy.get("persona") or ""),
        offer=strategy.get("offer") if isinstance(strategy.get("offer"), dict) else {},
        objections=list(strategy.get("objections") or []),
        raw=dict(strategy),
        generated_at=strategy.get("generated_at") or datetime.now(timezone.utc),
        generated_by="loqi",
        model_used=str(strategy.get("model_used") or ""),
    ))


def persist_campaign_update(user_id: str, campaign_id: str, updates: dict[str, Any]) -> bool:
    if campaign_id:
        _run(_update_campaign_row(user_id, campaign_id, updates))
    return append_event(user_id, "campaign.updated", {
        "campaign_id": campaign_id,
        "updates": updates,
    })


async def _update_campaign_row(user_id: str, campaign_id: str, updates: dict[str, Any]) -> None:
    repo = CampaignRepository()
    entity = await repo.get(campaign_id)
    if entity is None:
        return
    for key in ("name", "objective", "status", "search_query"):
        if updates.get(key) is not None:
            setattr(entity, key, str(updates[key]))
    if updates.get("status") in ("archived", "cancelled"):
        entity.archived_at = datetime.now(timezone.utc)
    entity.updated_at = datetime.now(timezone.utc)
    await repo.save(entity)

    strategy = updates.get("strategy")
    if isinstance(strategy, dict):
        await _write_strategy(campaign_id=campaign_id, strategy=strategy)


def persist_campaign_lead(user_id: str, campaign_id: str, lead: dict[str, Any]) -> bool:
    _run(_persist_campaign_lead_row(user_id, campaign_id, lead))
    return append_event(user_id, "campaign.lead_added", {
        "campaign_id": campaign_id,
        "lead": lead,
    })


async def _persist_campaign_lead_row(user_id: str, campaign_id: str, lead: dict[str, Any]) -> None:
    workspace = await _async_workspace(user_id)
    if not workspace:
        return
    lead_id = await _normalize_lead(workspace, lead)
    if not lead_id:
        return
    cl_repo = CampaignLeadRepository()
    link = await cl_repo.find_link(campaign_id, lead_id)
    if link is not None:
        return
    await cl_repo.save(CampaignLead(campaign_id=campaign_id, lead_id=lead_id, added_by=user_id))


async def _normalize_lead(workspace_id: str, lead: dict[str, Any]) -> str | None:
    """Persist a lead as a global person + company, then link it to the workspace.

    Global identity is by normalized email (leads) / domain (companies), so the
    same person and company are never duplicated across workspaces. Workspace
    state (status, source, confidence, company link) lives in workspace_leads.
    Returns the workspace-lead id — what campaign_leads and drafts reference.
    """
    email = str(lead.get("email") or "").strip().lower()
    if not email:
        return None

    lead_repo = LeadRepository()
    profile = await lead_repo.find_by_email(email)
    if profile is None:
        profile = Lead(
            canonical_id=f"email:{email}",
            email=email,
            first_name=str(lead.get("first_name") or ""),
            last_name=str(lead.get("last_name") or ""),
            title=str(lead.get("title") or ""),
            phone=str(lead.get("phone") or ""),
            linkedin_url=str(lead.get("linkedin_url") or ""),
        )
        name = lead.get("name") or lead.get("full_name") or ""
        if not profile.first_name and name:
            parts = str(name).split(" ", 1)
            profile.first_name = parts[0]
            if len(parts) > 1:
                profile.last_name = parts[1]
        profile = await lead_repo.save(profile)

    company_id = None
    domain = _lead_domain(lead)
    if domain:
        company_repo = CompanyRepository()
        company = await company_repo.find_by_domain(domain)
        if company is None:
            company = Company(
                canonical_id=f"domain:{domain}",
                domain=domain,
                name=str(lead.get("company") or lead.get("company_name") or domain),
                website=str(lead.get("website") or ""),
                linkedin_url=str(lead.get("linkedin_url") or ""),
                industry=str(lead.get("industry") or ""),
                country=str(lead.get("country") or ""),
                city=str(lead.get("city") or ""),
            )
            company = await company_repo.save(company)
        company_id = company.id
        ws_company_repo = WorkspaceCompanyRepository()
        link = await ws_company_repo.find(workspace_id, company.id)
        if link is None:
            await ws_company_repo.save(WorkspaceCompany(
                workspace_id=workspace_id,
                company_id=company.id,
                source=str(lead.get("source") or ""),
            ))

    ws_lead_repo = WorkspaceLeadRepository()
    existing = await ws_lead_repo.find_in_workspace(workspace_id, profile.id)
    if existing is not None:
        if company_id is not None:
            existing.company_id = company_id
        for key in ("first_name", "last_name", "title", "phone", "linkedin_url"):
            value = lead.get(key)
            if value:
                setattr(existing, key, str(value))
        status = lead.get("status") or lead.get("lead_status")
        if status:
            existing.lead_status = str(status)
        if lead.get("source"):
            existing.source = str(lead.get("source"))
        existing.updated_at = datetime.now(timezone.utc)
        await ws_lead_repo.save(existing)
        return existing.id

    ws_lead = WorkspaceLead(
        workspace_id=workspace_id,
        lead_id=profile.id,
        company_id=company_id,
        email=email,
        first_name=profile.first_name,
        last_name=profile.last_name,
        title=profile.title,
        phone=profile.phone,
        linkedin_url=profile.linkedin_url,
        lead_status=str(lead.get("status") or lead.get("lead_status") or "new"),
        confidence=_to_float(lead.get("confidence")),
        source=str(lead.get("source") or ""),
    )
    saved = await ws_lead_repo.save(ws_lead)
    return saved.id


def _lead_domain(lead: dict[str, Any]) -> str | None:
    raw = str(lead.get("domain") or "").strip().lower()
    if not raw:
        website = str(lead.get("website") or "").strip().lower()
        if website:
            host = urlparse(website if "//" in website else f"//{website}").hostname or ""
            raw = host.removeprefix("www.") if host else ""
    if not raw:
        email = str(lead.get("email") or "").strip().lower()
        if "@" in email:
            raw = email.split("@", 1)[1]
    return raw or None


def persist_lead_decision(user_id: str, lead: dict[str, Any], approved: bool) -> bool:
    _run(_update_lead_decision(user_id, lead, approved))
    return append_event(user_id, "lead.approved" if approved else "lead.rejected", {
        "lead": lead,
        "lead_id": lead.get("id", ""),
    })


async def _update_lead_decision(user_id: str, lead: dict[str, Any], approved: bool) -> None:
    workspace = await _async_workspace(user_id)
    if not workspace:
        return
    email = str(lead.get("email") or "").strip().lower()
    if not email:
        return
    ws_lead_repo = WorkspaceLeadRepository()
    entity = None
    lead_repo = LeadRepository()
    profile = await lead_repo.find_by_email(email) if email else None
    if profile is not None:
        entity = await ws_lead_repo.find_in_workspace(workspace, profile.id)
    if entity is None:
        matches = await ws_lead_repo.list_by_email(workspace, email)
        entity = matches[0] if matches else None
    if entity is not None:
        entity.lead_status = "approved" if approved else "rejected"
        entity.updated_at = datetime.now(timezone.utc)
        await ws_lead_repo.save(entity)


def persist_draft(user_id: str, draft: dict[str, Any]) -> bool:
    _run(_write_draft_row(user_id, draft))
    return append_event(user_id, "draft.created", {"draft": draft})


async def _write_draft_row(user_id: str, draft: dict[str, Any]) -> None:
    workspace = await _async_workspace(user_id)
    if not workspace:
        return
    repo = DraftRepository()
    existing = await repo.get(str(draft.get("id")))
    if existing is not None:
        return
    lead_snapshot = draft.get("lead") if isinstance(draft.get("lead"), dict) else {}
    meta: dict[str, Any] = {}
    for key in ("batch_id", "lead_intelligence", "company_intelligence", "strategy", "generation_metadata"):
        if draft.get(key) is not None:
            meta[key] = draft[key]
    text = str(draft.get("text") or draft.get("body") or "")
    entity = Draft(
        id=str(draft.get("id")),
        workspace_id=workspace,
        campaign_id=str(draft.get("campaign_id") or "") or None,
        lead_id=str(draft.get("lead_id") or "") or None,
        subject=str(draft.get("subject") or ""),
        body=text,
        preview=str(draft.get("body_preview") or "") or text[:200],
        status=str(draft.get("status") or "pending"),
        tone=str(draft.get("tone") or ""),
        length=str(draft.get("length") or ""),
        generation_model=str(draft.get("generation_model") or ""),
        generation_version=str(draft.get("generation_version") or ""),
        prompt_hash=str(draft.get("prompt_hash") or ""),
        generation_metadata=meta,
        lead_snapshot=lead_snapshot,
        created_at=draft.get("created_at") or datetime.now(timezone.utc),
    )
    await repo.save(entity)


def persist_draft_update(user_id: str, draft_id: str, updates: dict[str, Any]) -> bool:
    if draft_id:
        _run(_update_draft_row(user_id, draft_id, updates))
    return append_event(user_id, "draft.updated", {
        "draft_id": draft_id,
        "updates": updates,
    })


async def _update_draft_row(user_id: str, draft_id: str, updates: dict[str, Any]) -> None:
    repo = DraftRepository()
    entity = await repo.get(draft_id)
    if entity is None:
        return
    for key in ("subject", "status", "tone", "length", "body"):
        if updates.get(key) is not None:
            setattr(entity, key, str(updates[key]))
    if updates.get("status") == "approved":
        entity.approved_at = datetime.now(timezone.utc)
    if updates.get("status") in ("sent", "delivered"):
        entity.sent_at = datetime.now(timezone.utc)
    if updates.get("reply_state"):
        entity.reply_state = str(updates["reply_state"])
    entity.updated_at = datetime.now(timezone.utc)
    await repo.save(entity)


# ─── Canonical reads (events fallback) ────────────────────────────────

def _events(user_id: str) -> list[dict[str, Any]]:
    client = get_supabase_client()
    if client is None or not user_id:
        return []
    try:
        sessions = client.table("workflow_sessions").select("id").eq(
            "user_id", user_id
        ).eq("channel", "workspace").eq("session_key", user_id).limit(1).execute()
        session_rows = getattr(sessions, "data", None) or []
        if not session_rows:
            return []
        result = client.table("workflow_events").select("*").eq(
            "workflow_session_id", session_rows[0]["id"]
        ).order("created_at", desc=False).execute()
        return getattr(result, "data", None) or []
    except Exception as error:
        print(f"[workspace_state] events read failed: {error}")
        return []


def _project_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    campaigns: dict[str, dict[str, Any]] = {}
    drafts: dict[str, dict[str, Any]] = {}
    approved_leads: dict[str, dict[str, Any]] = {}
    for event in events:
        kind = event.get("event_type", "")
        payload = event.get("payload") or {}
        if kind == "campaign.created":
            campaign = dict(payload.get("campaign") or {})
            if campaign.get("id"):
                campaigns[campaign["id"]] = campaign
        elif kind == "campaign.updated":
            campaign = campaigns.get(payload.get("campaign_id"))
            if campaign:
                campaign.update(payload.get("updates") or {})
        elif kind == "campaign.lead_added":
            campaign = campaigns.get(payload.get("campaign_id"))
            lead = payload.get("lead")
            if campaign and isinstance(lead, dict):
                leads = campaign.setdefault("leads", [])
                if not any(str(item.get("id")) == str(lead.get("id")) for item in leads):
                    leads.append(lead)
                    campaign["lead_count"] = len(leads)
        elif kind == "lead.approved":
            lead = payload.get("lead")
            if isinstance(lead, dict) and lead.get("id"):
                approved_leads[str(lead["id"])] = lead
        elif kind == "lead.rejected":
            approved_leads.pop(str(payload.get("lead_id")), None)
        elif kind == "draft.created":
            draft = dict(payload.get("draft") or {})
            if draft.get("id"):
                drafts[draft["id"]] = draft
        elif kind == "draft.updated":
            draft = drafts.get(payload.get("draft_id"))
            if draft:
                draft.update(payload.get("updates") or {})
    return {
        "campaigns": list(campaigns.values()),
        "drafts": list(drafts.values()),
        "approved_leads": list(approved_leads.values()),
    }


def load_workspace_state(user_id: str) -> dict[str, Any]:
    """Return {campaigns, drafts, approved_leads} for the user's workspace.

    Prefers canonical tables when seeded; falls back to the event projection
    until backfill completes or Supabase is unavailable.
    """
    client = get_supabase_client()
    if client is not None:
        try:
            projection = _run_sync(_load_canonical_state(user_id))
            if projection is not None:
                return projection
        except Exception as error:
            print(f"[workspace_state] canonical read failed, falling back: {error}")
    return _project_from_events(_events(user_id))


async def _load_canonical_state(user_id: str) -> dict[str, Any] | None:
    workspace_id = _session_id(user_id)
    if not workspace_id:
        return None
    campaign_repo = CampaignRepository()
    draft_repo = DraftRepository()
    ws_lead_repo = WorkspaceLeadRepository()
    lead_repo = LeadRepository()
    strategy_repo = StrategyRepository()
    company_repo = CompanyRepository()
    cl_repo = CampaignLeadRepository()

    campaigns_rows = await campaign_repo.list_for_workspace(workspace_id)
    if not campaigns_rows:
        return None  # not yet backfilled → keep event projection

    campaigns: list[dict[str, Any]] = []
    for campaign in campaigns_rows:
        links = await cl_repo.list_for_campaign(campaign.id)
        ws_leads: list[WorkspaceLead] = []
        profiles: dict[str, Lead] = {}
        companies_by_id: dict[str, Company] = {}
        for link in links:
            ws_lead = await ws_lead_repo.get(link.lead_id)
            if ws_lead is None:
                continue
            ws_leads.append(ws_lead)
        for ws_lead in ws_leads:
            if ws_lead.lead_id and ws_lead.lead_id not in profiles:
                profile = await lead_repo.get(ws_lead.lead_id)
                if profile is not None:
                    profiles[ws_lead.lead_id] = profile
            if ws_lead.company_id and ws_lead.company_id not in companies_by_id:
                company = await company_repo.get(ws_lead.company_id)
                if company is not None:
                    companies_by_id[ws_lead.company_id] = company
        strategy = None
        try:
            strategy = await strategy_repo.current_for_campaign(campaign.id)
        except Exception:
            strategy = None
        campaigns.append({
            "id": campaign.id,
            "name": campaign.name,
            "objective": campaign.objective,
            "status": campaign.status,
            "search_query": campaign.search_query,
            "lead_count": len(ws_leads),
            "leads": [
                _lead_as_dict(ws_lead, profiles.get(ws_lead.lead_id), companies_by_id)
                for ws_lead in ws_leads
            ],
            "strategy": _strategy_as_dict(strategy),
            "created_at": _utc_iso(campaign.created_at),
            "updated_at": _utc_iso(campaign.updated_at),
        })

    drafts_rows = await draft_repo.list_for_workspace(workspace_id)
    drafts: list[dict[str, Any]] = []
    for draft in drafts_rows:
        drafts.append({
            "id": draft.id,
            "campaign_id": draft.campaign_id or "",
            "lead_id": draft.lead_id or "",
            "subject": draft.subject,
            "body_preview": draft.preview or draft.body[:200],
            "text": draft.body,
            "body": draft.body,
            "status": draft.status,
            "tone": draft.tone,
            "length": draft.length,
            "created_at": _utc_iso(draft.created_at),
            "updated_at": _utc_iso(draft.updated_at),
            "lead_intelligence": draft.generation_metadata.get("lead_intelligence"),
            "company_intelligence": draft.generation_metadata.get("company_intelligence"),
        })

    approved: list[dict[str, Any]] = []
    for campaign in campaigns:
        for lead in campaign.get("leads", []):
            if lead.get("lead_status") in ("approved", "selected"):
                approved.append(lead)

    return {
        "campaigns": campaigns,
        "drafts": drafts,
        "approved_leads": approved,
    }


def _lead_as_dict(ws_lead: WorkspaceLead, profile: Lead | None,
                  companies: dict[str, Company]) -> dict[str, Any]:
    company = companies.get(ws_lead.company_id or "")
    first = ws_lead.first_name or (profile.first_name if profile else "")
    last = ws_lead.last_name or (profile.last_name if profile else "")
    name = " ".join(p for p in (first, last) if p)
    email = ws_lead.email or (profile.email if profile else "")
    title = ws_lead.title or (profile.title if profile else "")
    phone = ws_lead.phone or (profile.phone if profile else "")
    linkedin_url = ws_lead.linkedin_url or (profile.linkedin_url if profile else "")
    return {
        "id": ws_lead.id,
        "name": name,
        "first_name": first,
        "last_name": last,
        "title": title,
        "email": email,
        "phone": phone,
        "linkedin_url": linkedin_url,
        "company": company.name if company else "",
        "company_name": company.name if company else "",
        "domain": company.domain if company else "",
        "status": ws_lead.lead_status,
        "lead_status": ws_lead.lead_status,
        "research_status": ws_lead.research_status,
        "verification_status": ws_lead.verification_status,
        "confidence": ws_lead.confidence,
        "source": ws_lead.source,
    }


def _strategy_as_dict(strategy: Strategy | None) -> dict[str, Any] | None:
    if strategy is None:
        return None
    return {
        "objective": strategy.objective,
        "audience": strategy.audience,
        "channel": strategy.channel,
        "messaging_angle": strategy.messaging_angle,
        "sequence": list(strategy.sequence),
        "tone": strategy.tone,
        "persona": strategy.persona,
        "offer": strategy.offer,
        "objections": list(strategy.objections),
        "generated_at": _utc_iso(strategy.generated_at),
        "version": strategy.version,
        "content": strategy.raw,
    }
