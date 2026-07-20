from __future__ import annotations

from services.email.exceptions import (
    UnknownTemplateError,
)


class TemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[str, dict[str, str]] = {}

    def register(
        self,
        name: str,
        *,
        display_name: str = "",
        description: str = "",
    ) -> None:
        self._templates[name] = {
            "name": name,
            "display_name": display_name or name.replace("_", " ").title(),
            "description": description,
        }

    def get(self, name: str) -> dict[str, str]:
        info = self._templates.get(name)
        if info is None:
            raise UnknownTemplateError(f"Template not registered: {name!r}")
        return info

    def list(self) -> list[dict[str, str]]:
        return list(self._templates.values())

    def has(self, name: str) -> bool:
        return name in self._templates

    def remove(self, name: str) -> None:
        if name not in self._templates:
            raise UnknownTemplateError(f"Template not registered: {name!r}")
        del self._templates[name]

    def register_builtins(self) -> None:
        builtins = {
            "plain": {
                "display_name": "Plain",
                "description": "Minimal text-based email with clean formatting",
            },
            "professional": {
                "display_name": "Professional",
                "description": "Clean corporate style for business communications",
            },
            "recruiting": {
                "display_name": "Recruiting",
                "description": "Talent outreach with prominent call-to-action",
            },
            "newsletter": {
                "display_name": "Newsletter",
                "description": "Multi-section layout for periodic updates",
            },
            "proposal": {
                "display_name": "Proposal",
                "description": "Formal proposal layout with metadata header",
            },
            "product_launch": {
                "display_name": "Product Launch",
                "description": "Hero section layout for product announcements",
            },
        }
        for name, info in builtins.items():
            self._templates[name] = {"name": name, **info}
