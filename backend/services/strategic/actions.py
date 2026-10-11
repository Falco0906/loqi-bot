"""Human-approved Strategic Action proposals and execution (PR6.1)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from services.persistence.launch import (
    AuditLogRepository,
    StrategicAction,
    StrategicActionRepository,
    StrategicUpdateRepository,
)


ACTION_TYPES = {"update_messaging", "refine_icp", "create_campaign"}
ACTIVE_ACTION_STATUSES = {"proposed", "approved", "executing", "completed", "failed"}


def action_to_dict(action: StrategicAction) -> dict[str, Any]:
    return {
        "id": action.id,
        "workspace_id": action.workspace_id,
        "strategic_update_id": action.strategic_update_id,
        "action_type": action.action_type,
        "status": action.status,
        "proposal": action.proposal,
        "created_by": action.created_by,
        "created_at": action.created_at.isoformat(),
        "approved_at": action.approved_at.isoformat() if action.approved_at else None,
        "executed_at": action.executed_at.isoformat() if action.executed_at else None,
        "dismissed_at": action.dismissed_at.isoformat() if action.dismissed_at else None,
        "error": action.error,
        "result": action.result,
        "metadata": action.metadata,
        "updated_at": action.updated_at.isoformat(),
    }


class StrategicActionError(ValueError):
    pass


class StrategicActionService:
    async def list_actions(self, owner_id: str, update_id: str) -> list[dict[str, Any]]:
        workspace_id = await self._workspace(owner_id)
        if not workspace_id:
            return []
        update = await self._owned_update(workspace_id, update_id)
        if update is None:
            return []
        actions = await StrategicActionRepository().list_for_update(workspace_id, update_id)
        return [action_to_dict(action) for action in actions if action.deleted_at is None]

    async def propose(
        self, owner_id: str, update_id: str, action_type: str,
    ) -> dict[str, Any]:
        workspace_id = await self._workspace(owner_id)
        if not workspace_id:
            raise StrategicActionError("Workspace could not be resolved")
        update = await self._owned_update(workspace_id, update_id)
        if update is None or update.deleted_at is not None:
            raise StrategicActionError("Strategic Update not found")
        if not update.evidence:
            raise StrategicActionError("This Strategic Update has insufficient evidence for an action")
        if action_type not in self.actions_for_update(update.update_type):
            raise StrategicActionError("This action is not available for the Strategic Update")

        repo = StrategicActionRepository()
        existing = await repo.list_for_update(workspace_id, update_id)
        for action in existing:
            if action.action_type == action_type and action.status in ACTIVE_ACTION_STATUSES:
                return action_to_dict(action)

        proposal = await self._build_proposal(owner_id, workspace_id, update, action_type)
        action = StrategicAction(
            workspace_id=workspace_id,
            strategic_update_id=update_id,
            action_type=action_type,
            proposal=proposal,
            created_by=owner_id,
            metadata={"evidence_count": len(update.evidence)},
        )
        await repo.save(action)
        await self._audit(owner_id, workspace_id, "strategic_action.proposed", action)
        return action_to_dict(action)

    async def approve(self, owner_id: str, action_id: str) -> dict[str, Any]:
        action, workspace_id = await self._owned_action(owner_id, action_id)
        if action is None:
            raise StrategicActionError("Strategic Action not found")
        if action.status == "completed":
            return action_to_dict(action)
        if action.status == "dismissed":
            raise StrategicActionError("Dismissed actions cannot be approved")
        if action.status not in {"proposed", "failed"}:
            raise StrategicActionError(f"Action cannot be approved from status {action.status}")
        action.status = "approved"
        action.approved_at = datetime.now(timezone.utc)
        action.error = ""
        action.updated_at = datetime.now(timezone.utc)
        await StrategicActionRepository().save(action)
        await self._audit(owner_id, workspace_id, "strategic_action.approved", action)
        return action_to_dict(action)

    async def dismiss(self, owner_id: str, action_id: str) -> dict[str, Any]:
        action, workspace_id = await self._owned_action(owner_id, action_id)
        if action is None:
            raise StrategicActionError("Strategic Action not found")
        if action.status == "dismissed":
            return action_to_dict(action)
        if action.status not in {"proposed", "failed"}:
            raise StrategicActionError(f"Action cannot be dismissed from status {action.status}")
        now = datetime.now(timezone.utc)
        action.status = "dismissed"
        action.dismissed_at = now
        action.updated_at = now
        await StrategicActionRepository().save(action)
        await self._audit(owner_id, workspace_id, "strategic_action.dismissed", action)
        return action_to_dict(action)

    async def refine(
        self, owner_id: str, action_id: str, changes: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(changes, dict) or not changes:
            raise StrategicActionError("Refinement changes are required")
        action, workspace_id = await self._owned_action(owner_id, action_id)
        if action is None:
            raise StrategicActionError("Strategic Action not found")
        if action.status not in {"proposed", "failed"}:
            raise StrategicActionError("Only proposed or failed actions can be refined")
        allowed = {"title", "summary", "content", "tags", "name", "objective", "search_query", "strategy"}
        safe_changes = {key: value for key, value in changes.items() if key in allowed}
        if not safe_changes:
            raise StrategicActionError("No supported refinement fields were supplied")
        action.proposal["proposed_change"] = {
            **(action.proposal.get("proposed_change") or {}),
            **safe_changes,
        }
        action.metadata["refined"] = True
        action.updated_at = datetime.now(timezone.utc)
        await StrategicActionRepository().save(action)
        await self._audit(owner_id, workspace_id, "strategic_action.refined", action)
        return action_to_dict(action)

    async def execute(self, owner_id: str, action_id: str) -> dict[str, Any]:
        action, workspace_id = await self._owned_action(owner_id, action_id)
        if action is None:
            raise StrategicActionError("Strategic Action not found")
        if action.status == "completed":
            return action_to_dict(action)
        if action.status == "dismissed":
            raise StrategicActionError("Dismissed actions cannot be executed")
        if action.status == "proposed":
            raise StrategicActionError("Action approval is required before execution")
        if action.status == "executing":
            return action_to_dict(action)
        if action.status not in {"approved", "failed"}:
            raise StrategicActionError(f"Action cannot be executed from status {action.status}")
        if action.status == "failed" and action.result:
            return action_to_dict(action)

        action.status = "executing"
        action.error = ""
        action.updated_at = datetime.now(timezone.utc)
        repo = StrategicActionRepository()
        await repo.save(action)
        await self._audit(owner_id, workspace_id, "strategic_action.executing", action)
        try:
            result = await self._execute_payload(owner_id, workspace_id, action)
            action.status = "completed"
            action.result = result
            action.executed_at = datetime.now(timezone.utc)
            action.updated_at = action.executed_at
            await repo.save(action)
            await self._audit(owner_id, workspace_id, "strategic_action.completed", action)
        except Exception as error:
            action.status = "failed"
            action.error = str(error)
            action.updated_at = datetime.now(timezone.utc)
            await repo.save(action)
            await self._audit(owner_id, workspace_id, "strategic_action.failed", action)
        return action_to_dict(action)

    @staticmethod
    def actions_for_update(update_type: str) -> list[str]:
        normalized = (update_type or "").lower()
        if normalized == "messaging":
            return ["update_messaging"]
        if normalized == "icp":
            return ["refine_icp"]
        if normalized in {"campaign", "performance", "follow_up", "opportunity"}:
            return ["create_campaign"]
        return []

    async def _build_proposal(self, owner_id, workspace_id, update, action_type):
        common = {
            "strategic_update_id": update.id,
            "observation": update.observation,
            "interpretation": update.interpretation,
            "recommendation": update.recommendation,
            "evidence": update.evidence,
        }
        if action_type in {"update_messaging", "refine_icp"}:
            from services.knowledge.service import KnowledgeService
            category = "messaging" if action_type == "update_messaging" else "icp"
            current = await KnowledgeService().list_items(workspace_id, category=category)
            return {
                **common,
                "current_items": current,
                "what_changes": f"Create a new {category} Knowledge version; existing records are not overwritten.",
                "proposed_change": {
                    "title": f"Strategic refinement: {update.title}",
                    "summary": update.recommendation,
                    "content": {
                        "observation": update.observation,
                        "interpretation": update.interpretation,
                        "structured_analysis": update.structured_analysis,
                        "evidence_signal_ids": [item.get("signal_id") for item in update.evidence],
                    },
                    "tags": ["strategic_action"],
                },
            }
        analysis = update.structured_analysis or {}
        return {
            **common,
            "what_changes": "Create a planning campaign only. No leads, drafts, launch, or sends are created.",
            "proposed_change": {
                "name": f"Strategic follow-on: {update.title}"[:160],
                "objective": update.recommendation or update.summary,
                "search_query": str(analysis.get("segment") or ""),
                "strategy": {"messaging_angle": str(analysis.get("angle") or "")},
            },
        }

    async def _execute_payload(self, owner_id: str, workspace_id: str, action: StrategicAction) -> dict[str, Any]:
        if action.action_type in {"update_messaging", "refine_icp"}:
            return await self._execute_knowledge(owner_id, workspace_id, action)
        if action.action_type == "create_campaign":
            return await self._execute_campaign(owner_id, workspace_id, action)
        raise StrategicActionError("Unsupported action type")

    async def _execute_knowledge(self, owner_id, workspace_id, action):
        from services.knowledge.service import KnowledgeService
        category = "messaging" if action.action_type == "update_messaging" else "icp"
        proposed = action.proposal.get("proposed_change") or {}
        content = dict(proposed.get("content") or {}) if isinstance(proposed.get("content"), dict) else {}
        content["strategic_action_id"] = action.id
        content["strategic_update_id"] = action.strategic_update_id
        existing = await KnowledgeService().list_items(workspace_id, category=category)
        for item in existing:
            if item.get("source_id") == action.strategic_update_id:
                return {"entity_type": "knowledge_item", "entity_id": item["id"], "category": category, "idempotent": True}
        item = await KnowledgeService().create_item(
            owner_id=owner_id,
            workspace_id=workspace_id,
            category=category,
            title=str(proposed.get("title") or f"Strategic refinement: {action.strategic_update_id}"),
            summary=str(proposed.get("summary") or ""),
            content=content,
            tags=[str(tag) for tag in (proposed.get("tags") or [])],
            source_type="system_generated",
            source_id=action.strategic_update_id,
        )
        return {"entity_type": "knowledge_item", "entity_id": item["id"], "category": category}

    async def _execute_campaign(self, owner_id: str, workspace_id: str, action: StrategicAction):
        from services.campaigns.creation import creation_identity, persist_creation, recover_creation
        from services.workspace.access import resolve_workspace_context

        # A durable action ID identifies this approved creation intent. Scope is
        # still membership-authorized, not granted by possession of the action.
        await asyncio.to_thread(resolve_workspace_context, None, owner_id, workspace_id)
        proposed = action.proposal.get("proposed_change") or {}
        now = datetime.now(timezone.utc).isoformat()
        campaign = {
            "name": str(proposed.get("name") or "Strategic follow-on campaign")[:160],
            "objective": str(proposed.get("objective") or "")[:4000],
            "search_query": str(proposed.get("search_query") or "")[:500],
            "discovery_id": "",
            "lead_count": 0,
            "leads": [],
            "status": "planning",
            "strategy": proposed.get("strategy") if isinstance(proposed.get("strategy"), dict) else {},
            "metadata": {"strategic_action_id": action.id, "strategic_update_id": action.strategic_update_id},
            "created_at": now,
            "updated_at": now,
        }
        identity, fingerprint = creation_identity(workspace_id, owner_id, f"strategic-action:{action.id}", campaign)
        campaign["id"] = identity
        if await recover_creation(workspace_id, owner_id, identity, fingerprint) is not None:
            return {"entity_type": "campaign", "entity_id": identity, "idempotent": True}
        created = await persist_creation(workspace_id, owner_id, identity, fingerprint, campaign)
        return {"entity_type": "campaign", "entity_id": identity, "status": "planning", "idempotent": not created}

    async def _workspace(self, owner_id: str) -> str | None:
        from services.workspace.state import _async_workspace
        return await _async_workspace(owner_id) if owner_id else None

    async def _owned_update(self, workspace_id: str, update_id: str):
        update = await StrategicUpdateRepository().get_for_workspace(update_id, workspace_id)
        if update is None:
            return None
        return update

    async def _owned_action(self, owner_id: str, action_id: str):
        workspace_id = await self._workspace(owner_id)
        if not workspace_id:
            return None, None
        action = await StrategicActionRepository().get_for_workspace(action_id, workspace_id)
        if action is None or action.deleted_at is not None:
            return None, workspace_id
        return action, workspace_id

    async def _audit(self, owner_id, workspace_id, action_name, action, *, before=None):
        try:
            await AuditLogRepository().record(
                workspace_id=workspace_id,
                user_id=owner_id,
                action=action_name,
                entity_type="strategic_action",
                entity_id=action.id,
                before=before,
                after=action_to_dict(action),
                metadata={"strategic_update_id": action.strategic_update_id, "action_type": action.action_type},
            )
        except Exception:
            pass
