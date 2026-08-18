from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from services.onboarding.config import ONBOARDING_CONFIG
from services.onboarding.events import OnboardingEvent
from services.onboarding.exceptions import (
    InvalidTransitionException,
    LifecycleStateNotFound,
    OnboardingSessionExpired,
    OnboardingSessionNotFound,
    StepAlreadyCompletedException,
    StepNotAllowedException,
    StepNotFoundException,
)
from services.onboarding.models import (
    LIFECYCLE_ORDER,
    LIFECYCLE_TO_STEP,
    STEP_ORDER,
    STEP_TO_LIFECYCLE,
    LifecycleState,
    OnboardingSession,
    StepId,
    StepRecord,
    UserLifecycle,
    is_valid_transition,
)
from services.onboarding.repositories import (
    LifecycleRepository,
    OnboardingSessionRepository,
)

if TYPE_CHECKING:
    from services.identity.services.user_service import UserService
    from services.organizations.services import OrganizationService


# ─── Wizard validation constants ───────────────────────────────────────

INDUSTRIES: frozenset[str] = frozenset({
    "technology", "healthcare", "finance", "education",
    "real_estate", "ecommerce", "manufacturing", "media",
    "consulting", "legal", "nonprofit", "other",
})

ROLES: frozenset[str] = frozenset({
    "founder", "ceo", "cto", "cmo", "vp_sales",
    "sales_rep", "marketing", "operations", "product",
    "engineering", "data", "other",
})

VALID_GOALS: frozenset[str] = frozenset({
    "lead_generation", "brand_awareness", "customer_engagement",
    "market_research", "sales_outreach", "partner_discovery",
    "event_promotion", "product_feedback", "content_distribution",
    "competitive_intelligence", "other",
})

# ─── AI Personalization validation constants ──────────────────────────

PRICING_MODELS: frozenset[str] = frozenset({
    "saas", "agency", "consulting", "marketplace", "services", "other",
})

TARGET_INDUSTRIES: frozenset[str] = frozenset({
    "technology", "healthcare", "finance", "education",
    "real_estate", "ecommerce", "manufacturing", "media",
    "consulting", "legal", "nonprofit", "other",
})

TARGET_COMPANY_SIZES: frozenset[str] = frozenset({
    "startup", "small", "medium", "enterprise",
})

TARGET_TITLES: frozenset[str] = frozenset({
    "founder", "ceo", "head_of_sales", "marketing_director",
    "hr_manager", "cto", "vp_engineering", "product_manager",
    "operations_head", "other",
})

PRIMARY_MARKETS: frozenset[str] = frozenset({
    "united_states", "india", "europe", "global", "latin_america",
    "asia_pacific", "middle_east", "africa", "other",
})

COMMUNICATION_TONES: frozenset[str] = frozenset({
    "professional", "friendly", "technical", "executive",
    "consultative", "founder_led",
})

AI_GOALS: frozenset[str] = frozenset({
    "generate_qualified_leads", "book_meetings", "research_prospects",
    "personalize_outreach", "automate_follow_up", "build_pipeline",
    "competitive_analysis", "account_planning", "other",
})


# ─── LifecycleService ────────────────────────────────────────────────


class LifecycleService:

    def __init__(
        self,
        lifecycle_repo: LifecycleRepository,
    ) -> None:
        self._lifecycle_repo = lifecycle_repo

    async def get_or_create(self, user_id: str) -> UserLifecycle:
        existing = await self._lifecycle_repo.find_by_user_id(user_id)
        if existing is not None:
            existing.touch()
            await self._lifecycle_repo.save(existing)
            return existing
        lc = UserLifecycle(user_id=user_id)
        await self._lifecycle_repo.save(lc)
        return lc

    async def get_current_state(self, user_id: str) -> LifecycleState:
        lc = await self._lifecycle_repo.find_by_user_id(user_id)
        if lc is None:
            raise LifecycleStateNotFound(user_id)
        return lc.state

    async def transition(
        self, user_id: str, target: LifecycleState,
    ) -> tuple[UserLifecycle, OnboardingEvent]:
        lc = await self._lifecycle_repo.find_by_user_id(user_id)
        if lc is None:
            lc = UserLifecycle(user_id=user_id)

        if not is_valid_transition(lc.state, target):
            raise InvalidTransitionException(lc.state.value, target.value)

        old_state = lc.state
        lc.transition_to(target)
        await self._lifecycle_repo.save(lc)

        event = OnboardingEvent.lifecycle_transitioned(
            user_id, old_state.value, target.value,
        )
        return lc, event

    async def force_transition(
        self, user_id: str, target: LifecycleState,
    ) -> tuple[UserLifecycle, OnboardingEvent]:
        lc = await self._lifecycle_repo.find_by_user_id(user_id)
        if lc is None:
            lc = UserLifecycle(user_id=user_id)

        old_state = lc.state
        lc.transition_to(target)
        await self._lifecycle_repo.save(lc)

        event = OnboardingEvent.lifecycle_transitioned(
            user_id, old_state.value, target.value,
        )
        return lc, event

    async def is_at_or_after(self, user_id: str, state: LifecycleState) -> bool:
        lc = await self._lifecycle_repo.find_by_user_id(user_id)
        if lc is None:
            return False
        current_idx = LIFECYCLE_ORDER.index(lc.state)
        target_idx = LIFECYCLE_ORDER.index(state)
        return current_idx >= target_idx

    async def get_previous_completed_state(self, user_id: str) -> LifecycleState | None:
        lc = await self._lifecycle_repo.find_by_user_id(user_id)
        if lc is None:
            return None
        current_idx = LIFECYCLE_ORDER.index(lc.state)
        if current_idx <= LIFECYCLE_ORDER.index(LifecycleState.AUTHENTICATED):
            return None
        return LIFECYCLE_ORDER[current_idx - 1]

    async def list_all(self) -> list[UserLifecycle]:
        return await self._lifecycle_repo.list_all()


# ─── OnboardingService ───────────────────────────────────────────────


class OnboardingService:

    def __init__(
        self,
        lifecycle_service: LifecycleService,
        session_repo: OnboardingSessionRepository,
        org_service: OrganizationService | None = None,
        user_service: UserService | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service
        self._session_repo = session_repo
        self._org_service = org_service
        self._user_service = user_service
        self._events: list[OnboardingEvent] = []

    @property
    def events(self) -> list[OnboardingEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    def _track_event(self, event: OnboardingEvent) -> None:
        self._events.append(event)

    def _onboarding_started(self, user_id: str, session_id: str = "") -> None:
        self._track_event(OnboardingEvent.onboarding_started(user_id, session_id))

    def _step_completed(self, user_id: str, step_id: str, step_data: dict[str, Any] | None = None) -> None:
        self._track_event(OnboardingEvent.step_completed(user_id, step_id, ""))
        if step_id == StepId.ONBOARDING_WIZARD.value:
            self._track_event(OnboardingEvent.wizard_completed(user_id, step_data or {}))

    def _onboarding_completed(self, user_id: str) -> None:
        self._track_event(OnboardingEvent.onboarding_completed(user_id, ""))

    async def validate_wizard_data(self, data: dict[str, object]) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []

        industry = data.get("industry", "")
        if not isinstance(industry, str) or not industry:
            errors.append({"field": "industry", "message": "Industry is required"})
        elif industry not in INDUSTRIES:
            errors.append({"field": "industry", "message": f"Invalid industry: {industry}"})

        role = data.get("role", "")
        if not isinstance(role, str) or not role:
            errors.append({"field": "role", "message": "Role is required"})
        elif role not in ROLES:
            errors.append({"field": "role", "message": f"Invalid role: {role}"})

        goals = data.get("goals", [])
        if not isinstance(goals, list) or len(goals) < 1:
            errors.append({"field": "goals", "message": "At least one goal is required"})
        elif len(goals) > 10:
            errors.append({"field": "goals", "message": "Maximum 10 goals allowed"})
        else:
            invalid = [g for g in goals if not isinstance(g, str) or g not in VALID_GOALS]
            if invalid:
                errors.append({"field": "goals", "message": f"Invalid goals: {invalid}"})

        return errors

    async def start_or_resume(self, user_id: str) -> tuple[OnboardingSession, list[OnboardingEvent]]:
        events: list[OnboardingEvent] = []

        lc = await self._lifecycle.get_or_create(user_id)

        existing = await self._session_repo.find_active_by_user_id(user_id)
        if existing is not None:
            existing.touch()
            await self._session_repo.save(existing)
            events.append(OnboardingEvent.onboarding_resumed(user_id, existing.id))
            return existing, events

        session = OnboardingSession(
            user_id=user_id,
            lifecycle_state=lc.state,
            expires_at=datetime.now(timezone.utc).replace(
                second=0, microsecond=0,
            ).replace(hour=0, minute=0, second=0, microsecond=0) + __import__("datetime").timedelta(
                seconds=ONBOARDING_CONFIG.onboarding_session_ttl_seconds,
            ),
        )
        await self._session_repo.save(session)
        events.append(OnboardingEvent.onboarding_started(user_id, session.id))
        self._onboarding_started(user_id, session.id)
        return session, events

    async def get_current_step(self, user_id: str) -> OnboardingSession:
        session = await self._session_repo.find_active_by_user_id(user_id)
        if session is None:
            session, _ = await self.start_or_resume(user_id)
        return session

    async def complete_step(
        self, user_id: str, step_id: str, data: dict | None = None,
    ) -> tuple[OnboardingSession, list[OnboardingEvent]]:
        events: list[OnboardingEvent] = []

        session = await self._session_repo.find_active_by_user_id(user_id)
        if session is None:
            session, start_events = await self.start_or_resume(user_id)
            events.extend(start_events)

        if session.is_expired:
            raise OnboardingSessionExpired()

        if step_id not in [s.value for s in StepId]:
            raise StepNotFoundException(step_id)

        if session.is_step_completed(step_id):
            raise StepAlreadyCompletedException(step_id)

        step_enum = StepId(step_id)
        step_idx = STEP_ORDER.index(step_enum)
        for i in range(step_idx):
            prev_step = STEP_ORDER[i].value
            if not session.is_step_completed(prev_step):
                raise StepNotAllowedException(step_id)

        target_state = STEP_TO_LIFECYCLE.get(step_enum)
        current_state = session.lifecycle_state

        if target_state is not None and target_state != current_state:
            lc = await self._lifecycle.get_or_create(user_id)
            try:
                current_lc_state = lc.state
                lc_index = LIFECYCLE_ORDER.index(current_lc_state)
                target_index = LIFECYCLE_ORDER.index(target_state)
                for i in range(lc_index + 1, target_index + 1):
                    intermediate = LIFECYCLE_ORDER[i]
                    _, transition_event = await self._lifecycle.transition(
                        user_id, intermediate,
                    )
                    events.append(transition_event)
                session.lifecycle_state = target_state
            except InvalidTransitionException:
                raise StepNotAllowedException(step_id)

        record = StepRecord(
            step_id=step_id,
            data=data or {},
        )
        session.completed_steps.append(record)
        if data:
            session.step_data[step_id] = data
        session.touch()
        await self._session_repo.save(session)

        events.append(OnboardingEvent.step_completed(user_id, step_id, session.lifecycle_state.value))
        self._step_completed(user_id, step_id, data)

        if step_id == StepId.PROFILE_SETUP.value:
            events.append(OnboardingEvent.profile_completed(
                user_id, (data or {}).get("display_name", ""),
            ))
        elif step_id == StepId.WORKSPACE_SETUP.value:
            events.append(OnboardingEvent.workspace_completed(
                user_id, (data or {}).get("workspace_name", ""),
            ))

        if self._is_onboarding_complete(session):
            session.deactivate()
            await self._session_repo.save(session)
            events.append(OnboardingEvent.onboarding_completed(user_id, session.id))
            self._onboarding_completed(user_id)

        return session, events

    async def complete_profile(
        self, user_id: str, display_name: str, **extra: str,
    ) -> tuple[OnboardingSession, list[OnboardingEvent]]:
        data = {"display_name": display_name, **extra}
        return await self.complete_step(user_id, StepId.PROFILE_SETUP.value, data)

    async def complete_workspace(
        self, user_id: str, workspace_name: str, **extra: str,
    ) -> tuple[OnboardingSession, list[OnboardingEvent]]:
        if self._org_service is not None:
            try:
                await self._org_service.create_organization(
                    name=workspace_name,
                    created_by=user_id,
                    slug=extra.get("slug"),
                    display_name=workspace_name,
                )
            except Exception:
                pass
        data = {"workspace_name": workspace_name, **extra}
        return await self.complete_step(user_id, StepId.WORKSPACE_SETUP.value, data)

    async def get_progress(self, user_id: str) -> dict:
        lc = await self._lifecycle.get_or_create(user_id)
        # Completion is an account property on the durable identity user.
        # Rehydrate the completed state after a backend restart before
        # treating the user as new.
        durable_step: str | None = None
        if self._user_service is not None:
            try:
                user = await self._user_service.get_user(user_id)
                if user is not None and user.is_onboarding_complete:
                    completed_ids = [s.value for s in STEP_ORDER]
                    return {
                        "lifecycle_state": LifecycleState.ONBOARDING_COMPLETE.value,
                        "current_step": None,
                        "next_route": "/dashboard",
                        "progress_percentage": 100,
                        "completed_steps": completed_ids,
                        "remaining_steps": [],
                        "total_steps": len(completed_ids),
                        "onboarding_complete": True,
                    }
                if user is not None:
                    durable_step = (user.onboarding_data_dict or {}).get("onboarding_step")
            except Exception:
                pass

        # Restart recovery: the wizard's actual step is durably stored in
        # identity_users.onboarding_data. When that says the account reached
        # the onboarding wizard, reconstruct the wizard phase instead of
        # resetting to PROFILE_SETUP because the in-memory lifecycle/session
        # repositories were recreated. A failed Google Workspace connection
        # therefore remains retryable after a restart.
        _WIZARD_STEPS = ("knowledge-validation", "workspace-connection", "executive-briefing")
        if durable_step in _WIZARD_STEPS:
            completed_ids = [
                s.value for s in (StepId.PROFILE_SETUP, StepId.WORKSPACE_SETUP, StepId.ONBOARDING_WIZARD)
            ]
            return {
                "lifecycle_state": LifecycleState.ONBOARDING_COMPLETE.value,
                "current_step": StepId.ONBOARDING_WIZARD.value,
                "next_route": "/onboarding",
                "progress_percentage": 60,
                "completed_steps": completed_ids,
                "remaining_steps": [s.value for s in (StepId.PLAN_SELECTION, StepId.CHECKOUT)],
                "total_steps": len(STEP_ORDER),
                "onboarding_complete": False,
            }

        session = await self._session_repo.find_active_by_user_id(user_id)
        if session is None:
            if lc.state in (LifecycleState.ACTIVE, LifecycleState.ONBOARDING_COMPLETE, LifecycleState.SUBSCRIPTION_ACTIVE):
                completed_ids: set[str] = set()
                all_steps = [s.value for s in STEP_ORDER]
                return {
                    "lifecycle_state": lc.state.value,
                    "current_step": None,
                    "next_route": "/dashboard",
                    "progress_percentage": 100,
                    "completed_steps": all_steps,
                    "remaining_steps": [],
                    "total_steps": len(all_steps),
                    "onboarding_complete": True,
                }
            session, _ = await self.start_or_resume(user_id)

        completed_ids = {s.step_id for s in session.completed_steps}
        all_steps = [s.value for s in STEP_ORDER]
        completed = [s for s in all_steps if s in completed_ids]
        remaining = [s for s in all_steps if s not in completed_ids]
        progress_pct = int((len(completed) / len(all_steps)) * 100) if all_steps else 0

        current_step = self._determine_current_step(session)
        next_route = self._step_to_route(current_step)

        return {
            "lifecycle_state": session.lifecycle_state.value,
            "current_step": current_step.value if current_step else None,
            "next_route": next_route,
            "progress_percentage": progress_pct,
            "completed_steps": completed,
            "remaining_steps": remaining,
            "total_steps": len(all_steps),
            "onboarding_complete": self._is_onboarding_complete(session),
        }

    def _determine_current_step(self, session: OnboardingSession) -> StepId | None:
        completed_ids = {s.step_id for s in session.completed_steps}
        candidate = LIFECYCLE_TO_STEP.get(session.lifecycle_state)

        if candidate is not None and candidate.value not in completed_ids:
            return candidate

        for step in STEP_ORDER:
            if step.value not in completed_ids:
                return step

        return None

    def _step_to_route(self, step: StepId | None) -> str:
        if step is None:
            return "/dashboard"
        mapping = {
            StepId.PROFILE_SETUP: "/onboarding/profile",
            StepId.WORKSPACE_SETUP: "/onboarding/workspace",
            StepId.PLAN_SELECTION: "/onboarding/plan",
            StepId.CHECKOUT: "/onboarding/checkout",
            StepId.ONBOARDING_WIZARD: "/onboarding/wizard",
        }
        return mapping.get(step, "/onboarding")

    async def save_wizard_data(
        self, user_id: str, data: dict[str, object],
    ) -> dict[str, object]:
        if self._user_service is None:
            return data
        user = await self._user_service.get_user(user_id)
        merged = dict(user.onboarding_data_dict)
        merged.update(data)
        user.set_onboarding_data(merged)
        await self._user_service.save_user(user)
        return merged

    async def get_wizard_data(self, user_id: str) -> dict[str, object]:
        if self._user_service is not None:
            try:
                user = await self._user_service.get_user(user_id)
                if user is not None and user.onboarding_data_dict:
                    return dict(user.onboarding_data_dict)
            except Exception:
                pass
        return {}

    async def complete_wizard(
        self, user_id: str, data: dict[str, object],
    ) -> tuple[OnboardingSession, list[OnboardingEvent]]:
        merged = await self.save_wizard_data(user_id, data)

        # Auto-complete PROFILE_SETUP and WORKSPACE_SETUP if needed
        session = await self._session_repo.find_active_by_user_id(user_id)
        if session is not None and not session.is_step_completed(StepId.PROFILE_SETUP.value):
            display_name = ""
            if self._user_service is not None:
                user = await self._user_service.get_user(user_id)
                display_name = user.display_name or ""
            await self.complete_step(user_id, StepId.PROFILE_SETUP.value, {"display_name": display_name})

        if session is not None and not session.is_step_completed(StepId.WORKSPACE_SETUP.value):
            company_name = str(data.get("company_name", "") or "")
            await self.complete_step(user_id, StepId.WORKSPACE_SETUP.value, {"workspace_name": company_name})

        _, events = await self.complete_step(
            user_id, StepId.ONBOARDING_WIZARD.value, merged,
        )
        session = await self._session_repo.find_active_by_user_id(user_id)
        if session is None:
            session, _ = await self.start_or_resume(user_id)
        return session, events

    async def create_workspace_and_finalize(
        self, user_id: str, data: dict[str, object],
    ) -> dict[str, object]:
        workspace_name = str(data.get("workspace_name", "") or "My Workspace")
        slug = str(data.get("slug", "") or "")

        if self._org_service is None:
            raise RuntimeError("OrganizationService not configured")

        user = None
        if self._user_service is not None:
            user = await self._user_service.get_user(user_id)

        # SaaS-2.1: never create a second organization for a user. The
        # canonical organization comes from the user's active membership
        # (created by signup completion or an earlier onboarding run); reuse it
        # so a completed account owns exactly ONE organization. A new
        # organization is created only when none exists yet (e.g. a recovered
        # legacy account).
        orgs = await self._org_service.list_user_organizations(user_id)
        if orgs:
            org = orgs[0]
        else:
            org = await self._org_service.create_organization(
                name=workspace_name,
                created_by=user_id,
                slug=slug or None,
                display_name=workspace_name,
            )

        # Every user auto-owns a Personal Workspace within the org so the
        # canonical ownership chain (Org → Workspace → campaigns) holds.
        try:
            from services.workspace_state import ensure_workspace
            ensure_workspace(
                user_id,
                name=workspace_name,
                organization_id=org.id,
                slug=slug,
            )
        except Exception:
            pass

        if user is not None and self._user_service is not None:
            user.onboarding_completed_at = datetime.now(timezone.utc)
            user.set_onboarding_data(data)
            await self._user_service.save_user(user)

        # save_user() above is the single durable persistence path for
        # onboarding completion. It writes the User aggregate to the identity
        # platform repository; failure propagates so completion is never
        # acknowledged without a durable marker.

        self._onboarding_completed(user_id)

        return {
            "organization_id": org.id,
            "organization_name": org.name,
            "organization_slug": org.slug,
        }

    def _is_onboarding_complete(self, session: OnboardingSession) -> bool:
        all_steps = {s.value for s in STEP_ORDER}
        completed = {s.step_id for s in session.completed_steps}
        return all_steps.issubset(completed)

    # ─── AI Personalization ───────────────────────────────────────────

    async def validate_personalization_step(
        self, step_id: str, data: dict[str, object],
    ) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []

        if step_id == "about_business":
            name = data.get("company_name", "")
            if not isinstance(name, str) or not name.strip():
                errors.append({"field": "company_name", "message": "Company name is required"})

        elif step_id == "what_you_sell":
            offering = data.get("offering", "")
            if not isinstance(offering, str) or not offering.strip():
                errors.append({"field": "offering", "message": "Product or service description is required"})
            pricing = data.get("pricing_model", "")
            if pricing and pricing not in PRICING_MODELS:
                errors.append({"field": "pricing_model", "message": f"Invalid pricing model: {pricing}"})

        elif step_id == "icp":
            industries = data.get("target_industries", [])
            if not isinstance(industries, list) or len(industries) < 1:
                errors.append({"field": "target_industries", "message": "Select at least one target industry"})
            else:
                invalid = [i for i in industries if not isinstance(i, str) or i not in TARGET_INDUSTRIES]
                if invalid:
                    errors.append({"field": "target_industries", "message": f"Invalid industries: {invalid}"})
            sizes = data.get("target_company_sizes", [])
            if isinstance(sizes, list):
                invalid = [s for s in sizes if s not in TARGET_COMPANY_SIZES]
                if invalid:
                    errors.append({"field": "target_company_sizes", "message": f"Invalid company sizes: {invalid}"})
            titles = data.get("target_titles", [])
            if isinstance(titles, list):
                invalid = [t for t in titles if t not in TARGET_TITLES]
                if invalid:
                    errors.append({"field": "target_titles", "message": f"Invalid titles: {invalid}"})

        elif step_id == "geography":
            market = data.get("primary_market", "")
            if not isinstance(market, str) or not market.strip():
                errors.append({"field": "primary_market", "message": "Primary market is required"})
            elif market not in PRIMARY_MARKETS:
                errors.append({"field": "primary_market", "message": f"Invalid market: {market}"})

        elif step_id == "goals":
            goals = data.get("ai_goals", [])
            if not isinstance(goals, list) or len(goals) < 1:
                errors.append({"field": "ai_goals", "message": "Select at least one goal"})
            else:
                invalid = [g for g in goals if not isinstance(g, str) or g not in AI_GOALS]
                if invalid:
                    errors.append({"field": "ai_goals", "message": f"Invalid goals: {invalid}"})

        elif step_id == "communication":
            tone = data.get("tone", "")
            if not isinstance(tone, str) or not tone.strip():
                errors.append({"field": "tone", "message": "Communication tone is required"})
            elif tone not in COMMUNICATION_TONES:
                errors.append({"field": "tone", "message": f"Invalid tone: {tone}"})

        return errors

    async def get_personalization_context(self, user_id: str) -> dict[str, object]:
        data = await self.get_wizard_data(user_id)
        return {
            "business": {
                "company_name": data.get("company_name", ""),
                "website": data.get("website", ""),
                "description": data.get("description", ""),
            },
            "product": {
                "offering": data.get("offering", ""),
                "pricing_model": data.get("pricing_model", ""),
                "deal_size": data.get("deal_size", ""),
                "sales_cycle": data.get("sales_cycle", ""),
            },
            "icp": {
                "target_industries": data.get("target_industries", []),
                "target_company_sizes": data.get("target_company_sizes", []),
                "target_titles": data.get("target_titles", []),
                "competitors": data.get("competitors", ""),
            },
            "geography": {
                "primary_market": data.get("primary_market", ""),
                "language": data.get("language", ""),
                "timezone": data.get("timezone", ""),
            },
            "goals": {
                "ai_goals": data.get("ai_goals", []),
                "custom_goal": data.get("custom_goal", ""),
            },
            "communication": {
                "tone": data.get("tone", ""),
                "brand_voice": data.get("brand_voice", ""),
            },
        }
