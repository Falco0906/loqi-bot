from __future__ import annotations

from datetime import datetime, timezone

from services.capabilities.config import CapabilityConfig
from services.capabilities.events import CapabilityDomainEvent, CapabilityEventType
from services.capabilities.exceptions import (
    CapabilityAlreadyDisabled,
    CapabilityAlreadyEnabled,
    CapabilityNotRegistered,
    DuplicateCapabilityRegistration,
)
from services.capabilities.models import (
    CapabilityDefinition,
    CapabilityUsage,
    OrganizationCapability,
)
from services.capabilities.repositories import (
    CapabilityDefinitionRepository,
    CapabilityLimitsRepository,
    CapabilityUsageRepository,
    OrganizationCapabilityRepository,
)


class CapabilityService:

    def __init__(
        self,
        definition_repo: CapabilityDefinitionRepository,
        org_capability_repo: OrganizationCapabilityRepository,
        usage_repo: CapabilityUsageRepository,
        limits_repo: CapabilityLimitsRepository,
        config: CapabilityConfig | None = None,
    ) -> None:
        self._definition_repo = definition_repo
        self._org_capability_repo = org_capability_repo
        self._usage_repo = usage_repo
        self._limits_repo = limits_repo
        self._config = config or CapabilityConfig()
        self._events: list[CapabilityDomainEvent] = []

    @property
    def events(self) -> list[CapabilityDomainEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    # ── Registration ─────────────────────────────────────────────────

    async def register_capability(
        self,
        slug: str,
        name: str,
        category: str = "",
        description: str = "",
        default_enabled: bool = False,
        beta: bool = False,
    ) -> CapabilityDefinition:
        existing = await self._definition_repo.find_by_slug(slug)
        if existing is not None:
            raise DuplicateCapabilityRegistration(slug)

        capability = CapabilityDefinition(
            slug=slug,
            name=name,
            category=category,
            description=description,
            default_enabled=default_enabled,
            beta=beta,
        )
        capability = await self._definition_repo.save(capability)

        self._events.append(
            CapabilityDomainEvent.capability_registered(slug, name, category)
        )
        return capability

    async def seed_capabilities(self) -> list[CapabilityDefinition]:
        existing = await self._definition_repo.list_all()
        if existing:
            return existing

        seeded: list[CapabilityDefinition] = []
        for spec in self._config.seed_capabilities:
            capability = CapabilityDefinition(
                slug=spec["slug"],
                name=spec["name"],
                category=spec.get("category", ""),
                description=spec.get("description", ""),
                default_enabled=spec.get("default_enabled", False),
                beta=spec.get("beta", False),
            )
            seeded.append(await self._definition_repo.save(capability))
        return seeded

    # ── Lookup ───────────────────────────────────────────────────────

    async def get_capability(self, slug: str) -> CapabilityDefinition:
        capability = await self._definition_repo.find_by_slug(slug)
        if capability is None:
            raise CapabilityNotRegistered(slug)
        return capability

    async def list_capabilities(self) -> list[CapabilityDefinition]:
        capabilities = await self._definition_repo.list_all()
        if not capabilities:
            return await self.seed_capabilities()
        return capabilities

    async def capability_exists(self, slug: str) -> bool:
        capability = await self._definition_repo.find_by_slug(slug)
        return capability is not None

    # ── Organization Capabilities ────────────────────────────────────

    async def get_organization_capabilities(
        self, organization_id: str,
    ) -> list[OrganizationCapability]:
        org_caps = await self._org_capability_repo.list_by_organization(
            organization_id,
        )
        if org_caps:
            return org_caps

        all_defs = await self.list_capabilities()
        activated: list[OrganizationCapability] = []
        for definition in all_defs:
            org_cap = OrganizationCapability(
                organization_id=organization_id,
                capability_slug=definition.slug,
                enabled=definition.default_enabled,
                activated_at=datetime.now(timezone.utc) if definition.default_enabled else None,
            )
            org_cap = await self._org_capability_repo.save(org_cap)
            activated.append(org_cap)
        return activated

    async def get_organization_capability(
        self, organization_id: str, slug: str,
    ) -> OrganizationCapability:
        await self.get_capability(slug)

        org_cap = await self._org_capability_repo.find_by_organization_and_slug(
            organization_id, slug,
        )
        if org_cap is not None:
            return org_cap

        definition = await self.get_capability(slug)
        org_cap = OrganizationCapability(
            organization_id=organization_id,
            capability_slug=slug,
            enabled=definition.default_enabled,
            activated_at=datetime.now(timezone.utc) if definition.default_enabled else None,
        )
        org_cap = await self._org_capability_repo.save(org_cap)
        return org_cap

    async def enable_capability(
        self,
        organization_id: str,
        slug: str,
        activated_by: str = "",
    ) -> OrganizationCapability:
        await self.get_capability(slug)

        org_cap = await self._org_capability_repo.find_by_organization_and_slug(
            organization_id, slug,
        )
        if org_cap is not None:
            if org_cap.enabled:
                raise CapabilityAlreadyEnabled(slug, organization_id)
            org_cap.enabled = True
            org_cap.activated_at = datetime.now(timezone.utc)
            org_cap.activated_by = activated_by
            org_cap = await self._org_capability_repo.save(org_cap)
        else:
            org_cap = OrganizationCapability(
                organization_id=organization_id,
                capability_slug=slug,
                enabled=True,
                activated_at=datetime.now(timezone.utc),
                activated_by=activated_by,
            )
            org_cap = await self._org_capability_repo.save(org_cap)

        self._events.append(
            CapabilityDomainEvent.capability_enabled(slug, organization_id, activated_by)
        )
        return org_cap

    async def disable_capability(
        self,
        organization_id: str,
        slug: str,
    ) -> OrganizationCapability:
        await self.get_capability(slug)

        org_cap = await self._org_capability_repo.find_by_organization_and_slug(
            organization_id, slug,
        )
        if org_cap is None:
            org_cap = OrganizationCapability(
                organization_id=organization_id,
                capability_slug=slug,
                enabled=False,
            )
            org_cap = await self._org_capability_repo.save(org_cap)
        elif not org_cap.enabled:
            raise CapabilityAlreadyDisabled(slug, organization_id)
        else:
            org_cap.enabled = False
            org_cap = await self._org_capability_repo.save(org_cap)

        self._events.append(
            CapabilityDomainEvent.capability_disabled(slug, organization_id)
        )
        return org_cap

    # ── Usage ────────────────────────────────────────────────────────

    async def get_usage(
        self, organization_id: str, slug: str,
    ) -> CapabilityUsage:
        await self.get_capability(slug)

        usage = await self._usage_repo.find_by_organization_and_slug(
            organization_id, slug,
        )
        if usage is not None:
            return usage

        usage = CapabilityUsage(
            organization_id=organization_id,
            capability_slug=slug,
        )
        usage = await self._usage_repo.save(usage)
        return usage

    async def increment_usage(
        self,
        organization_id: str,
        slug: str,
        requests: int = 0,
        executions: int = 0,
        storage_bytes: int = 0,
        api_calls: int = 0,
    ) -> CapabilityUsage:
        usage = await self.get_usage(organization_id, slug)

        if requests:
            usage.increment_requests(requests)
        if executions:
            usage.increment_executions(executions)
        if storage_bytes:
            usage.increment_storage(storage_bytes)
        if api_calls:
            usage.increment_api_calls(api_calls)

        usage = await self._usage_repo.save(usage)

        fields = []
        if requests:
            fields.append(("requests", requests))
        if executions:
            fields.append(("executions", executions))
        if storage_bytes:
            fields.append(("storage_bytes", storage_bytes))
        if api_calls:
            fields.append(("api_calls", api_calls))
        for field, value in fields:
            self._events.append(
                CapabilityDomainEvent.usage_incremented(
                    slug, organization_id, field, value,
                )
            )
        return usage

    async def reset_usage(self, organization_id: str, slug: str) -> CapabilityUsage:
        usage = await self.get_usage(organization_id, slug)
        usage.reset()
        usage = await self._usage_repo.save(usage)

        self._events.append(
            CapabilityDomainEvent(
                event_type=CapabilityEventType.USAGE_RESET,
                entity_id=slug,
                organization_id=organization_id,
            )
        )
        return usage

    # ── Validation ───────────────────────────────────────────────────

    async def validate_capability_exists(self, slug: str) -> CapabilityDefinition:
        return await self.get_capability(slug)
