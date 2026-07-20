from __future__ import annotations

from services.email.models import BrandKit
from services.email.exceptions import BrandKitNotFoundError


class BrandingManager:
    def __init__(self) -> None:
        self._kits: dict[str, BrandKit] = {}
        self._default_id: str | None = None

    def register(self, kit: BrandKit, kit_id: str = "") -> str:
        kit_id = kit_id or kit.company_name.lower().replace(" ", "_")
        self._kits[kit_id] = kit
        if self._default_id is None:
            self._default_id = kit_id
        return kit_id

    def get(self, kit_id: str) -> BrandKit:
        kit = self._kits.get(kit_id)
        if kit is None:
            raise BrandKitNotFoundError(f"BrandKit not found: {kit_id!r}")
        return kit

    def set_default(self, kit_id: str) -> None:
        if kit_id not in self._kits:
            raise BrandKitNotFoundError(f"BrandKit not found: {kit_id!r}")
        self._default_id = kit_id

    @property
    def default(self) -> BrandKit | None:
        if self._default_id is None:
            return None
        return self._kits.get(self._default_id)

    def remove(self, kit_id: str) -> None:
        self._kits.pop(kit_id, None)
        if self._default_id == kit_id:
            self._default_id = next(iter(self._kits)) if self._kits else None

    def list(self) -> dict[str, BrandKit]:
        return dict(self._kits)

    def has(self, kit_id: str) -> bool:
        return kit_id in self._kits
