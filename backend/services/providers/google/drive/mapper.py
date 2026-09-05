from __future__ import annotations

from typing import Any

from services.providers.models import ProviderDocument


class DriveMapper:
    """Maps raw Google Drive API responses to normalized domain models."""

    @staticmethod
    def file_to_document(
        raw: dict[str, Any],
        provider_id: str = "drive",
    ) -> ProviderDocument:
        return ProviderDocument(
            name=raw.get("name", ""),
            mime_type=raw.get("mimeType", ""),
            size_bytes=int(raw.get("size", 0)),
            url=raw.get("webViewLink", raw.get("alternateLink", "")),
            parent_folder="",
            provider_id=provider_id,
            external_id=raw.get("id", ""),
        )

    @staticmethod
    def folder_name_from_parents(
        raw: dict[str, Any],
        parents_field: str = "parents",
    ) -> str:
        parents = raw.get(parents_field, [])
        return parents[0] if parents else ""
