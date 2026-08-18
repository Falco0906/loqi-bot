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
from uuid import uuid4

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
    """Fire an async write from a sync or async context without awaiting.

    Accepts either a zero-arg callable that returns a coroutine or an
    already-created coroutine (matching ``_run_sync``'s contract). Failures in
    the background write are surfaced to the error log instead of vanishing.
    """
    def _make():
        from inspect import iscoroutine
        return async_fn if iscoroutine(async_fn) else async_fn()

    def _observe(task):
        try:
            task.result()
        except Exception as error:
            print(f"[workspace_state] fire-and-forget write failed: {error}", flush=True)

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_make())
        task.add_done_callback(_observe)
    except RuntimeError:
        import threading

        def _thread():
            try:
                asyncio.run(_make())
            except Exception as error:
                print(f"[workspace_state] fire-and-forget write failed: {error}", flush=True)

        threading.Thread(target=_thread, daemon=True).start()


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


def _workflow_session_id(user_id: str) -> str:
    """The channel='workspace' workflow session id (chat/log object only).

    SaaS-2.1: this is deliberately NOT the workspace identity. It keys the
    legacy workflow_events log/replay path; a workflow session may be
    recreated without changing the durable workspace id.
    """
    return ensure_workflow_session(
        user_id=user_id,
        channel="workspace",
        session_key=user_id,
    )


async def _canonical_organization_id(user_id: str) -> str:
    """Resolve the user's canonical organization from their active membership.

    Server-side authority only: never trusts client-supplied organization ids.
    The canonical org is the active organization membership on the durable
    memberships table (written by signup completion / onboarding / recovery).
    """
    client = get_supabase_client()
    if client is None or not user_id:
        return ""
    try:
        result = await asyncio.to_thread(
            lambda: client.table("memberships")
            .select("organization_id")
            .eq("user_id", user_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        return str(rows[0].get("organization_id") or "") if rows else ""
    except Exception:
        return ""


# ─── Workspaces ─────────────────────────────────────────────────────────

def _workspace_slug(workspace_id: str, name: str = "Personal Workspace") -> str:
    """Deterministic unique default slug.

    ``workspaces`` enforces a unique ``(organization_id, slug)`` index, so the
    default "personal-workspace" slug may only exist ONCE in the whole table.
    Every workspace must therefore derive its slug from its own id.
    """
    base = (name or "Personal Workspace").replace(" ", "-").lower()
    suffix = str(workspace_id or "")[:8]
    return f"{base}-{suffix}" if suffix else base


def ensure_workspace(
    user_id: str,
    *,
    name: str = "Personal Workspace",
    organization_id: str = "",
    slug: str = "",
) -> str | None:
    """Return the canonical durable workspace id for the user (create if needed).

    SaaS-2.1: the workspace owns a real durable uuid minted for itself and is
    resolved by the durable owner relationship (owner_user_id), independent of
    workflow_sessions.id, web-session ids and access tokens. Repeated calls
    return the same workspace; a recreated workflow session never changes it.
    Creates the workspaces + workspace_members rows on first touch.
    """
    try:
        return _run_sync(_async_workspace(
            user_id,
            name=name,
            organization_id=organization_id,
            slug=slug,
        ))
    except Exception as error:
        print(f"[workspace_state] ensure_workspace failed: {error}")
        return None


# ─── Events (compatibility log) ────────────────────────────────────────

def append_event(user_id: str, event_type: str, payload: dict[str, Any]) -> bool:
    client = get_supabase_client()
    if client is None or not user_id:
        return False
    try:
        session_id = _workflow_session_id(user_id)
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


async def duplicate_campaign(user_id: str, campaign_id: str) -> dict[str, Any] | None:
    """Deep-copy a campaign: campaign row + current strategy + lead links.

    Drafts, outbound threads, sent mail, analytics and runtime state are never
    duplicated. The copy starts fresh in the planning lifecycle with the same
    strategy and workspace leads so the user can re-run the pipeline.
    """
    workspace_id = await _async_workspace(user_id)
    if not workspace_id:
        return None
    campaign_repo = CampaignRepository()
    source = await campaign_repo.get(campaign_id)
    if source is None or source.status == "deleted":
        return None

    new_id = str(uuid4())
    entity = Campaign(
        id=new_id,
        workspace_id=source.workspace_id,
        organization_id=source.organization_id,
        name=f"{source.name} (Copy)",
        objective=source.objective,
        status="planning",
        search_query=source.search_query,
        discovery_id=source.discovery_id,
        settings=dict(source.settings or {}),
        created_by=user_id,
        updated_by=user_id,
        version=1,
    )
    await campaign_repo.save(entity)

    try:
        current = await StrategyRepository().current_for_campaign(campaign_id)
    except Exception:
        current = None
    strategy_dict: dict[str, Any] | None = None
    if current is not None:
        strategy_dict = _strategy_as_dict(current)
        await StrategyRepository().save(Strategy(
            campaign_id=new_id,
            version=1,
            is_current=True,
            objective=current.objective,
            audience=current.audience,
            channel=current.channel,
            messaging_angle=current.messaging_angle,
            sequence=list(current.sequence),
            tone=current.tone,
            persona=current.persona,
            offer=dict(current.offer),
            objections=list(current.objections),
            raw=dict(current.raw),
            generated_at=datetime.now(timezone.utc),
            generated_by="loqi",
            model_used=current.model_used,
        ))

    cl_repo = CampaignLeadRepository()
    try:
        links = await cl_repo.list_for_campaign(campaign_id)
    except Exception:
        links = []
    for link in links:
        await cl_repo.save(CampaignLead(
            campaign_id=new_id,
            lead_id=link.lead_id,
            status="added",
            added_by=user_id,
        ))

    append_event(user_id, "campaign.created", {"campaign": {
        "id": new_id,
        "name": entity.name,
        "objective": entity.objective,
        "status": "planning",
        "lead_count": len(links),
    }})
    return {
        "id": new_id,
        "name": entity.name,
        "objective": entity.objective,
        "status": "planning",
        "search_query": entity.search_query,
        "discovery_id": entity.discovery_id or "",
        "strategy": strategy_dict,
        "lead_count": len(links),
        "created_at": _utc_iso(datetime.now(timezone.utc)),
        "updated_at": _utc_iso(datetime.now(timezone.utc)),
    }


async def persist_campaign_row(user_id: str, campaign: dict[str, Any]) -> bool:
    """Await the canonical campaigns row write for ``campaign``.

    Mirrors ``persist_campaign``'s bool contract but guarantees the row is
    durable before the caller proceeds (unlike the fire-and-forget variant,
    whose task is cancelled when a TestClient request scope ends).
    """
    try:
        await _write_campaign_row(user_id, campaign)
        return True
    except Exception as error:
        print(f"[workspace_state] persist_campaign_row failed: {error}")
        return False


async def _write_campaign_row(user_id: str, campaign: dict[str, Any]) -> None:
    workspace_id = await _async_workspace(user_id)
    if not workspace_id:
        return
    repo = CampaignRepository()
    discovery_id = str(campaign.get("discovery_id") or "") or None
    entity = Campaign(
        id=str(campaign.get("id")),
        workspace_id=workspace_id,
        organization_id=str(campaign.get("organization_id") or ""),
        name=str(campaign.get("name") or ""),
        objective=str(campaign.get("objective") or ""),
        status=str(campaign.get("status") or "planning"),
        search_query=str(campaign.get("search_query") or ""),
        discovery_id=discovery_id,
        created_by=user_id,
        created_at=campaign.get("created_at") or datetime.now(timezone.utc),
        updated_at=campaign.get("updated_at") or datetime.now(timezone.utc),
    )
    existing = await repo.get(entity.id)
    if existing is not None:
        entity = existing
        for key in ("name", "objective", "status", "search_query", "discovery_id"):
            if campaign.get(key) is not None:
                value = str(campaign[key]) if campaign[key] != "" else None
                setattr(entity, key, value)
        entity.updated_at = datetime.now(timezone.utc)
    if isinstance(campaign.get("generation"), dict):
        settings = dict(entity.settings or {})
        settings["generation"] = campaign["generation"]
        entity.settings = settings
    if isinstance(campaign.get("launch"), dict):
        settings = dict(entity.settings or {})
        settings["launch"] = campaign["launch"]
        entity.settings = settings
    await repo.save(entity)

    strategy = campaign.get("strategy")
    if isinstance(strategy, dict):
        await _write_strategy(campaign_id=entity.id, strategy=strategy)


async def _async_workspace(
    user_id: str,
    *,
    name: str = "Personal Workspace",
    organization_id: str = "",
    slug: str = "",
) -> str | None:
    """Resolve the user's canonical durable workspace id (find or create).

    The workspace is keyed by the durable owner relationship
    (``owner_user_id``) and its id is a uuid minted for the workspace itself —
    never derived from workflow_sessions.id, web-session ids, access tokens or
    client-supplied ids. The ``organization_id`` is server-derived from the
    canonical active membership when not supplied.
    """
    repo = WorkspaceRepository()
    existing = await repo.find_active_by_owner(user_id)
    if existing is not None:
        await _attach_canonical_org(existing, organization_id)
        return existing.id

    org_id = organization_id or await _canonical_organization_id(user_id)
    workspace_id = str(uuid4())
    await _ensure_workspace_row(
        user_id, workspace_id,
        name=name, organization_id=org_id, slug=slug,
    )
    # Re-resolve after create so a concurrent first-touch converges on one
    # workspace even without a DB-level unique constraint (added in a later
    # phase once legacy duplicates are reconciled).
    found = await repo.find_active_by_owner(user_id)
    return found.id if found is not None else workspace_id


async def _attach_canonical_org(workspace: Workspace, organization_id: str) -> None:
    """Converge a workspace to its canonical organization.

    Attaches the server-derived org when a canonical organization is now known
    (e.g. a workspace minted by an anonymous web-session bootstrap before
    signup completion). No-op on the hot read path when no org is supplied and
    the workspace is already org-attached.
    """
    if organization_id:
        if workspace.organization_id == organization_id:
            return
        workspace.organization_id = organization_id
    elif workspace.organization_id:
        return
    else:
        org_id = await _canonical_organization_id(workspace.owner_user_id)
        if not org_id or workspace.organization_id == org_id:
            return
        workspace.organization_id = org_id
    await WorkspaceRepository().save(workspace)


async def _ensure_workspace_row(
    user_id: str,
    workspace_id: str,
    *,
    name: str = "Personal Workspace",
    organization_id: str = "",
    slug: str = "",
) -> None:
    """Create the durable workspace (+ owner identity + member) rows if missing.

    ``workspaces.owner_user_id`` references ``identity_users``, but anonymous
    web sessions only mint ``users`` rows. Every workspace bootstrap (both the
    synchronous ``ensure_workspace`` and the async write path) must therefore
    ensure the identity row exists before touching ``workspaces``.
    """
    ws_repo = WorkspaceRepository()
    existing = await ws_repo.get(workspace_id)
    if not existing:
        from services.persistence.repositories.user_repository import SupabaseUserRepository
        from services.identity.models import User
        user_repo = SupabaseUserRepository()
        owner = await user_repo.get(user_id)
        if owner is None:
            await user_repo.save(User(
                id=user_id,
                display_name=name if name != "Personal Workspace" else "web-user",
            ))
        await ws_repo.save(Workspace(
            id=workspace_id,
            organization_id=organization_id or "",
            name=name,
            slug=slug or _workspace_slug(workspace_id, name),
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


async def persist_campaign_update_awaited(user_id: str, campaign_id: str, updates: dict[str, Any]) -> bool:
    """Durable (awaited) campaign update for interactive endpoints.

    Mirrors ``persist_campaign_update``'s contract but guarantees the row is
    written before the caller proceeds. Fire-and-forget writes race reads and
    each other (unique-domain lead normalization), so the campaign endpoints
    must await persistence instead of scheduling it in the background.
    """
    try:
        await _update_campaign_row(user_id, campaign_id, updates)
    except Exception as error:
        print(f"[workspace_state] campaign update failed: {error}")
        return False
    # Mirror persist_campaign_update: append campaign.updated so the events
    # fallback projection stays consistent with the durable row (status,
    # generation, and launch progress must survive a transient canonical-read
    # failure).
    try:
        append_event(user_id, "campaign.updated", {
            "campaign_id": campaign_id,
            "updates": updates,
        })
    except Exception as error:
        print(f"[workspace_state] campaign update event append failed: {error}")
    return True


async def persist_campaign_lead_awaited(user_id: str, campaign_id: str, lead: dict[str, Any]) -> bool:
    """Durable (awaited) campaign-lead link for interactive endpoints.

    Returns False only when the link genuinely could not be written, so the
    endpoint can surface a real failure instead of a false success. (Attaching
    a company-only recommendation used to be silently dropped because the
    normalizer required an email and still reported True.)
    """
    try:
        if not await _persist_campaign_lead_row(user_id, campaign_id, lead):
            return False
    except Exception as error:
        print(f"[workspace_state] campaign lead write failed: {error}")
        return False
    # Mirror persist_campaign_lead: append campaign.lead_added so the events
    # fallback projection stays consistent with the durable link (a transient
    # canonical-read failure must not hide an already-attached lead).
    try:
        append_event(user_id, "campaign.lead_added", {
            "campaign_id": campaign_id,
            "lead": lead,
        })
    except Exception as error:
        print(f"[workspace_state] campaign lead event append failed: {error}")
    return True


async def _update_campaign_row(user_id: str, campaign_id: str, updates: dict[str, Any]) -> None:
    repo = CampaignRepository()
    entity = await repo.get(campaign_id)
    if entity is None:
        return
    for key in ("name", "objective", "status", "search_query", "discovery_id"):
        if updates.get(key) is not None:
            value = str(updates[key]) if updates[key] != "" else None
            setattr(entity, key, value)
    status = updates.get("status")
    removed_states = ("archived", "cancelled", "deleted")
    if status in removed_states:
        entity.archived_at = datetime.now(timezone.utc)
        if status == "deleted":
            entity.deleted_at = datetime.now(timezone.utc)
    elif status is not None:
        entity.archived_at = None
        entity.deleted_at = None
    if isinstance(updates.get("generation"), dict):
        settings = dict(entity.settings or {})
        settings["generation"] = updates["generation"]
        entity.settings = settings
    if isinstance(updates.get("launch"), dict):
        settings = dict(entity.settings or {})
        settings["launch"] = updates["launch"]
        entity.settings = settings
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


async def _persist_campaign_lead_row(user_id: str, campaign_id: str, lead: dict[str, Any]) -> bool:
    """Persist a campaign-lead link and report whether the link exists after.

    Returns True when the link is present after the write (newly created or
    already deduped), False when the lead could not be linked at all.
    """
    workspace = await _async_workspace(user_id)
    if not workspace:
        return False
    try:
        lead_id = await _normalize_lead(workspace, lead)
    except Exception:
        # Concurrent lead adds race the unique email/domain indexes: a second
        # normalizer may have created the global rows just before this one.
        # Retry once — the second pass finds and links the existing rows.
        lead_id = await _normalize_lead(workspace, lead)
    if not lead_id:
        return False
    cl_repo = CampaignLeadRepository()
    link = await cl_repo.find_link(campaign_id, lead_id)
    if link is not None:
        return True
    try:
        await cl_repo.save(CampaignLead(campaign_id=campaign_id, lead_id=lead_id, added_by=user_id))
    except Exception:
        if await cl_repo.find_link(campaign_id, lead_id) is None:
            raise
    return True


async def _normalize_lead(workspace_id: str, lead: dict[str, Any]) -> str | None:
    """Persist a lead as a global person + company, then link it to the workspace.

    Global identity is by normalized email (leads) / domain (companies), so the
    same person and company are never duplicated across workspaces. Workspace
    state (status, source, confidence, company link) lives in workspace_leads.
    Returns the workspace-lead id — what campaign_leads and drafts reference.
    """
    email = str(lead.get("email") or "").strip().lower()
    if not email:
        return await _normalize_company_lead(workspace_id, lead)

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
    source = str(lead.get("source") or lead.get("provider") or "").strip()
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
                source_provider=source,
            )
            company = await company_repo.save(company)
        company_id = company.id
        ws_company_repo = WorkspaceCompanyRepository()
        link = await ws_company_repo.find(workspace_id, company.id)
        if link is None:
            await ws_company_repo.save(WorkspaceCompany(
                workspace_id=workspace_id,
                company_id=company.id,
                source=source,
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
        if lead.get("source") or lead.get("provider"):
            existing.source = str(
                lead.get("source") or lead.get("provider") or ""
            )
        qualification = _qualification_metadata(lead)
        if qualification:
            existing.metadata.update(qualification)
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
        source=source or str(lead.get("source") or ""),
        metadata=_qualification_metadata(lead),
    )
    saved = await ws_lead_repo.save(ws_lead)
    return saved.id


async def _normalize_company_lead(workspace_id: str, lead: dict[str, Any]) -> str | None:
    """Persist a company-only prospect (no person email) as a workspace lead.

    Discovery recommendations are company-level, so attachments arrive without
    an email. The campaign-leads link targets the workspace lead, which itself
    carries the company link — attaching such a lead must still advance the
    campaign lifecycle. Deduplicated per (workspace, company); a synthetic
    global person row (empty email) satisfies the workspace_leads FK.
    """
    ws_lead_repo = WorkspaceLeadRepository()
    raw_id = str(lead.get("id") or "").strip()

    if raw_id:
        account = await _safe_repo_get(ws_lead_repo, raw_id)
        if account is not None and account.workspace_id == workspace_id:
            return account.id

    company = None
    company_repo = CompanyRepository()
    if raw_id:
        company = await _safe_repo_get(company_repo, raw_id)
    domain = _lead_domain(lead) if company is None else None
    if company is None and domain:
        company = await company_repo.find_by_domain(domain)
    company_id = company.id if company is not None else None

    if company_id:
        ws_company_repo = WorkspaceCompanyRepository()
        link = await ws_company_repo.find(workspace_id, company_id)
        if link is None:
            await ws_company_repo.save(WorkspaceCompany(
                workspace_id=workspace_id,
                company_id=company_id,
                source=str(lead.get("source") or ""),
            ))
        existing = await ws_lead_repo.find_by_company(workspace_id, company_id)
        if existing is not None:
            qualification = _qualification_metadata(lead)
            if qualification:
                existing.metadata.update(qualification)
                await ws_lead_repo.save(existing)
            return existing.id

    lead_repo = LeadRepository()
    profile = await lead_repo.save(Lead(
        canonical_id=f"company:{company_id or 'anonymous'}:{workspace_id}",
        email="",
        first_name=str(lead.get("first_name") or ""),
        last_name=str(lead.get("last_name") or ""),
        title=str(lead.get("title") or ""),
    ))
    ws_lead = WorkspaceLead(
        workspace_id=workspace_id,
        lead_id=profile.id,
        company_id=company_id,
        title=str(lead.get("title") or ""),
        linkedin_url=str(lead.get("linkedin_url") or ""),
        lead_status=str(lead.get("status") or lead.get("lead_status") or "new"),
        confidence=_to_float(lead.get("confidence")),
        source=str(lead.get("source") or ""),
        metadata=_qualification_metadata(lead),
    )
    try:
        saved = await ws_lead_repo.save(ws_lead)
    except Exception:
        if company_id:
            existing = await ws_lead_repo.find_by_company(workspace_id, company_id)
            if existing is not None:
                return existing.id
        raise
    return saved.id


def _qualification_metadata(lead: dict[str, Any]) -> dict[str, Any]:
    """Persist qualification explanation without changing the lead model."""
    breakdown = lead.get("commercial_score_breakdown")
    return {"qualification": breakdown} if isinstance(breakdown, dict) else {}


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


async def _safe_repo_get(repo, entity_id: str):
    """Look up a row by id without crashing on non-uuid ids.

    Discovery recommendations may carry fallback ids (e.g. ``company-0`` or a
    company name) that are not valid uuids. Querying a uuid column with such a
    value raises 22P02; the caller must treat it as "no match" so the rest of
    the normalizer (domain/company resolution) can still run instead of
    dropping the lead.
    """
    try:
        return await repo.get(entity_id)
    except Exception:
        return None


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


async def persist_draft_awaited(user_id: str, draft: dict[str, Any]) -> bool:
    """Durable (awaited) draft write for batch generation.

    Draft generation must not treat an event-append as success: the draft row
    write is the source of truth for review/sending steps. The batch loop uses
    this so partial/complete generation is reported accurately and retries
    never double-persist.
    """
    try:
        await _write_draft_row(user_id, draft)
    except Exception as error:
        print(f"[workspace_state] draft write failed: {error}")
        return False
    # Mirror persist_draft: the draft.created event keeps the events-fallback
    # projection consistent with the durable row. Without it, any transient
    # canonical-read failure leaves batch-generated drafts invisible to the
    # workflow UI and approval endpoints 404. The row write remains the source
    # of truth for the success return value.
    try:
        append_event(user_id, "draft.created", {"draft": draft})
    except Exception as error:
        print(f"[workspace_state] draft event append failed: {error}")
    return True


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
    for key in ("batch_id", "lead_intelligence", "company_intelligence", "strategy", "generation_metadata", "evidence_trace"):
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


async def persist_draft_update_awaited(user_id: str, draft_id: str, updates: dict[str, Any]) -> bool:
    """Durable (awaited) draft update for interactive endpoints."""
    if not draft_id:
        return False
    try:
        await _update_draft_row(user_id, draft_id, updates)
    except Exception as error:
        print(f"[workspace_state] draft update failed: {error}")
        return False
    # Keep the events-fallback projection consistent with the durable row so a
    # transient canonical-read failure cannot revert statuses in the UI view.
    try:
        append_event(user_id, "draft.updated", {
            "draft_id": draft_id,
            "updates": updates,
        })
    except Exception as error:
        print(f"[workspace_state] draft update event append failed: {error}")
    return True


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

def _events(user_id: str, session_id: str | None = None) -> list[dict[str, Any]]:
    client = get_supabase_client()
    if client is None or not user_id:
        return []
    try:
        if not session_id:
            sessions = client.table("workflow_sessions").select("id").eq(
                "user_id", user_id
            ).eq("channel", "workspace").eq("session_key", user_id).limit(1).execute()
            session_rows = getattr(sessions, "data", None) or []
            if not session_rows:
                return []
            session_id = session_rows[0]["id"]
        result = client.table("workflow_events").select("*").eq(
            "workflow_session_id", session_id
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
    _flatten_launch_counters(campaigns)
    return {
        "campaigns": list(campaigns.values()),
        "drafts": list(drafts.values()),
        "approved_leads": list(approved_leads.values()),
    }


def _flatten_launch_counters(campaigns: dict[str, dict[str, Any]]) -> None:
    """Mirror _load_canonical_state's flat launch_sent/total/failed fields.

    The events fallback merges ``campaign.updated`` updates as ``launch`` (the
    nested dict), but the API only reads the flat fields. Without this the
    fallback view loses launch progress during a transient canonical failure.
    """
    for campaign in campaigns.values():
        launch = campaign.get("launch") or {}
        if isinstance(launch, dict):
            campaign["launch_sent"] = int(launch.get("sent", 0))
            campaign["launch_total"] = int(launch.get("total", 0))
            campaign["launch_failed"] = int(launch.get("failed", 0))


def load_workspace_state(user_id: str, include_details: bool = True) -> dict[str, Any]:
    """Return {campaigns, drafts, approved_leads} for the user's workspace.

    Prefers canonical tables when seeded; falls back to the event projection
    until backfill completes or Supabase is unavailable.

    ``include_details=False`` skips the per-lead profile, company and strategy
    fan-out (campaigns carry ``lead_count`` but empty ``leads`` and
    ``strategy=None``).  Use it for summary/tabular endpoints that only need
    counts and step state — it cuts the workspace-graph load roughly in half.
    """
    client = get_supabase_client()
    if client is not None:
        try:
            projection = _run_sync(_load_canonical_state(user_id, include_details=include_details))
            if projection is not None:
                return projection
        except Exception as error:
            print(f"[workspace_state] canonical read failed, falling back: {error}")
    return _project_from_events(_events(user_id))


def load_drafts_only(user_id: str) -> list[dict[str, Any]]:
    """Return just the workspace's draft dicts — one query, no graph fan-out.

    Same per-draft shape as ``load_workspace_state()["drafts"]`` so list/edit/
    approve endpoints no longer pay for leads, profiles, companies and
    strategies.
    """
    client = get_supabase_client()
    workspace_id = _run_sync(_async_workspace(user_id))
    if client is not None and workspace_id:
        try:
            rows = _run_sync(DraftRepository().list_for_workspace(workspace_id))
            if rows is not None:
                return [_draft_as_dict(d) for d in rows]
        except Exception as error:
            print(f"[workspace_state] drafts-only read failed, falling back: {error}")
    return _project_from_events(_events(user_id)).get("drafts", [])


def load_campaign_state(user_id: str, campaign_id: str) -> dict[str, Any] | None:
    """Return one campaign with its leads and strategy — no whole-graph load.

    Uses the same canonical fan-out scoped to a single campaign (links,
    profiles, companies, strategy).  Returns None when the campaign is not
    part of the user's workspace.
    """
    client = get_supabase_client()
    if client is not None:
        try:
            campaign = _run_sync(_load_canonical_state(user_id, campaign_id=campaign_id))
            if campaign is not None:
                return campaign
        except Exception as error:
            print(f"[workspace_state] single-campaign read failed, falling back: {error}")
    state = _project_from_events(_events(user_id))
    return next((c for c in state.get("campaigns", []) if c.get("id") == campaign_id), None)


async def _load_canonical_state(
    user_id: str,
    campaign_id: str | None = None,
    include_details: bool = True,
) -> Any:
    workspace_id = await _async_workspace(user_id)
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

    if campaign_id is not None:
        campaigns_rows = [c for c in campaigns_rows if c.id == campaign_id]
        if not campaigns_rows:
            return None

    # Fetch the remaining independent data with a single pass of parallel
    # reads instead of a per-campaign sequential chain:
    #   campaigns → links → workspace-leads → profiles / companies / strategies
    # Repos use ``asyncio.to_thread`` for their I/O, so gathering the
    # coroutines runs the queries concurrently (one thread per query).
    drafts_rows, links_by_campaign = await asyncio.gather(
        draft_repo.list_for_workspace(workspace_id),
        asyncio.gather(*[cl_repo.list_for_campaign(c.id) for c in campaigns_rows]),
    )

    if not include_details:
        approved: list[dict[str, Any]] = []
        campaigns = []
        for campaign, links in zip(campaigns_rows, links_by_campaign):
            if campaign.status == "deleted":
                continue
            campaigns.append({
                "id": campaign.id,
                "name": campaign.name,
                "objective": campaign.objective,
                "status": campaign.status,
                "search_query": campaign.search_query,
                "discovery_id": campaign.discovery_id or "",
                "lead_count": len(links),
                "leads": [],
                "strategy": None,
                "generation": (campaign.settings or {}).get("generation"),
                "launch": (campaign.settings or {}).get("launch") or {},
                "launch_sent": int(((campaign.settings or {}).get("launch") or {}).get("sent", 0)),
                "launch_total": int(((campaign.settings or {}).get("launch") or {}).get("total", 0)),
                "launch_failed": int(((campaign.settings or {}).get("launch") or {}).get("failed", 0)),
                "created_at": _utc_iso(campaign.created_at),
                "updated_at": _utc_iso(campaign.updated_at),
            })
    else:
        link_ids = list(dict.fromkeys(l.lead_id for links in links_by_campaign for l in links))
        ws_lead_rows = (
            [w for w in (await asyncio.gather(*[ws_lead_repo.get(i) for i in link_ids])) if w is not None]
            if link_ids else []
        )
        ws_lead_by_id = {w.id: w for w in ws_lead_rows}

        lead_ids = list(dict.fromkeys(w.lead_id for w in ws_lead_rows if w.lead_id))
        profiles = (
            {p.id: p for p in (await asyncio.gather(*[lead_repo.get(i) for i in lead_ids])) if p is not None}
            if lead_ids else {}
        )

        company_ids = list(dict.fromkeys(w.company_id for w in ws_lead_rows if w.company_id))
        companies = (
            {c.id: c for c in (await asyncio.gather(*[company_repo.get(i) for i in company_ids])) if c is not None}
            if company_ids else {}
        )

        async def _safe_strategy(campaign_id: str) -> Strategy | None:
            try:
                return await strategy_repo.current_for_campaign(campaign_id)
            except Exception:
                return None

        strategies: dict[str, Strategy | None] = dict(zip(
            [c.id for c in campaigns_rows],
            await asyncio.gather(*[_safe_strategy(c.id) for c in campaigns_rows]),
        ))

        campaigns: list[dict[str, Any]] = []
        for campaign, links in zip(campaigns_rows, links_by_campaign):
            if campaign.status == "deleted":
                continue
            ws_leads = [ws_lead_by_id[l.lead_id] for l in links if l.lead_id in ws_lead_by_id]
            campaigns.append({
                "id": campaign.id,
                "name": campaign.name,
                "objective": campaign.objective,
                "status": campaign.status,
                "search_query": campaign.search_query,
                "discovery_id": campaign.discovery_id or "",
                "lead_count": len(ws_leads),
                "leads": [
                    _lead_as_dict(ws_lead, profiles.get(ws_lead.lead_id), companies)
                    for ws_lead in ws_leads
                ],
                "strategy": _strategy_as_dict(strategies[campaign.id]),
                "generation": (campaign.settings or {}).get("generation"),
                "launch": (campaign.settings or {}).get("launch") or {},
                "launch_sent": int(((campaign.settings or {}).get("launch") or {}).get("sent", 0)),
                "launch_total": int(((campaign.settings or {}).get("launch") or {}).get("total", 0)),
                "launch_failed": int(((campaign.settings or {}).get("launch") or {}).get("failed", 0)),
                "created_at": _utc_iso(campaign.created_at),
                "updated_at": _utc_iso(campaign.updated_at),
            })

        approved: list[dict[str, Any]] = []
        for campaign in campaigns:
            for lead in campaign.get("leads", []):
                if lead.get("lead_status") in ("approved", "selected"):
                    approved.append(lead)

    drafts: list[dict[str, Any]] = []
    for draft in drafts_rows:
        drafts.append(_draft_as_dict(draft))

    if campaign_id is not None:
        return campaigns[0] if campaigns else None

    return {
        "campaigns": campaigns,
        "drafts": drafts,
        "approved_leads": approved,
    }


def _draft_as_dict(draft: Any) -> dict[str, Any]:
    return {
        "id": draft.id,
        "campaign_id": draft.campaign_id or "",
        "lead_id": draft.lead_id or "",
        "lead": dict(draft.lead_snapshot or {}),
        "subject": draft.subject,
        "body_preview": draft.preview or draft.body[:200],
        "text": draft.body,
        "body": draft.body,
        "status": draft.status,
        "tone": draft.tone,
        "length": draft.length,
        "batch_id": draft.generation_metadata.get("batch_id"),
        "created_at": _utc_iso(draft.created_at),
        "updated_at": _utc_iso(draft.updated_at),
        "sent_at": _utc_iso(draft.sent_at) if draft.sent_at else None,
        "lead_intelligence": draft.generation_metadata.get("lead_intelligence"),
        "company_intelligence": draft.generation_metadata.get("company_intelligence"),
        "evidence_trace": draft.generation_metadata.get("evidence_trace"),
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
        "industry": company.industry if company else "",
        "city": company.city if company else "",
        "country": company.country if company else "",
        "location_label": company.location if company else "",
        "employee_count": company.employee_count if company else None,
        "revenue_band": company.revenue_band if company else "",
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
    # The full playbook is persisted in `raw`; the legacy projection columns
    # are kept as fallbacks for the fields raw may not carry. Serving the
    # playbook FLAT (never nested under `content`) is what every consumer —
    # draft generation, strategy rendering, context panels — reads.
    outer: dict[str, Any] = {
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
    }
    raw = strategy.raw
    if isinstance(raw, dict):
        outer = {**outer, **raw}
    return outer
