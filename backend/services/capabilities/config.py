from __future__ import annotations

from dataclasses import dataclass, field


SEED_CAPABILITIES: list[dict] = [
    {"slug": "memory", "name": "Memory", "category": "intelligence", "description": "Conversation memory and recall", "default_enabled": True, "beta": False},
    {"slug": "gmail", "name": "Gmail", "category": "communication", "description": "Gmail email integration", "default_enabled": False, "beta": False},
    {"slug": "calendar", "name": "Calendar", "category": "communication", "description": "Google Calendar integration", "default_enabled": False, "beta": False},
    {"slug": "drive", "name": "Drive", "category": "storage", "description": "Google Drive integration", "default_enabled": False, "beta": True},
    {"slug": "slack", "name": "Slack", "category": "communication", "description": "Slack messaging integration", "default_enabled": False, "beta": True},
    {"slug": "github", "name": "GitHub", "category": "developer", "description": "GitHub repository integration", "default_enabled": False, "beta": True},
    {"slug": "crm", "name": "CRM", "category": "sales", "description": "CRM contact and opportunity management", "default_enabled": False, "beta": False},
    {"slug": "outreach", "name": "Outreach", "category": "sales", "description": "Sales outreach automation", "default_enabled": False, "beta": False},
    {"slug": "research", "name": "Research", "category": "intelligence", "description": "Lead and company research", "default_enabled": True, "beta": False},
    {"slug": "execution", "name": "Execution Engine", "category": "infrastructure", "description": "Workflow execution engine", "default_enabled": True, "beta": False},
]


@dataclass
class CapabilityConfig:
    auto_seed: bool = True
    default_limits_enabled: bool = False
    seed_capabilities: list[dict] = field(default_factory=lambda: SEED_CAPABILITIES)
