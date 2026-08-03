from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from services.providers.capabilities import Capability, CapabilitySet
from services.providers.health import HealthCheckResult
from services.providers.interface import Provider, ProviderSetupError
from services.providers.google.drive.mapper import DriveMapper
from services.providers.google.oauth import GoogleOAuthFlow
from services.providers.oauth import OAuthTokenStore, TokenManager, TokenRefreshError

logger = logging.getLogger(__name__)

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"


class DriveProvider(Provider):
    """Google Drive provider — file metadata sync, folder sync, document discovery.

    Uses the Drive REST API directly.
    """

    def __init__(
        self,
        token_store: OAuthTokenStore,
        oauth_flow: GoogleOAuthFlow | None = None,
        provider_id: str = "drive",
    ) -> None:
        self._provider_id = provider_id
        self._token_store = token_store
        self._flow = oauth_flow or GoogleOAuthFlow(
            scopes="https://www.googleapis.com/auth/drive.readonly "
                   "https://www.googleapis.com/auth/drive.metadata.readonly",
            provider_id=provider_id,
        )
        self._token_manager = TokenManager(self._flow, token_store)
        self._connected = False
        self._mapper = DriveMapper()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def display_name(self) -> str:
        return f"Drive ({self._provider_id})"

    @property
    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            Capability.DRIVE_SYNC,
            Capability.DOCUMENT_DISCOVERY,
            Capability.OAUTH,
        )

    def connect(self) -> None:
        token = self._get_token()
        if not token.access_token:
            raise ProviderSetupError("Drive: no access token available")

        resp = requests.get(
            f"{DRIVE_API_BASE}/about",
            params={"fields": "user"},
            headers=self._auth_headers(token.access_token),
            timeout=10,
        )
        if resp.status_code == 401:
            try:
                token = self._token_manager.get_valid_token(self._provider_id)
                resp = requests.get(
                    f"{DRIVE_API_BASE}/about",
                    params={"fields": "user"},
                    headers=self._auth_headers(token.access_token),
                    timeout=10,
                )
            except TokenRefreshError as e:
                raise ProviderSetupError(f"Drive: token refresh failed: {e}") from e

        if resp.status_code != 200:
            raise ProviderSetupError(
                f"Drive: failed to connect — HTTP {resp.status_code}: {resp.text[:200]}"
            )
        self._connected = True
        logger.info("DriveProvider connected")

    def disconnect(self) -> None:
        self._connected = False
        logger.info("DriveProvider disconnected")

    def health(self) -> HealthCheckResult:
        if not self._connected:
            return HealthCheckResult(
                ok=False, provider_id=self._provider_id,
                status="offline", error="Not connected",
            )
        try:
            token = self._get_token()
            start = time.time()
            resp = requests.get(
                f"{DRIVE_API_BASE}/about",
                params={"fields": "storageQuota"},
                headers=self._auth_headers(token.access_token),
                timeout=5,
            )
            elapsed = (time.time() - start) * 1000
            if resp.status_code == 200:
                quota = resp.json().get("storageQuota", {})
                return HealthCheckResult(
                    ok=True, provider_id=self._provider_id,
                    latency_ms=elapsed,
                    details={
                        "usage": quota.get("usage", "unknown"),
                        "limit": quota.get("limit", "unknown"),
                    },
                )
            return HealthCheckResult(
                ok=False, provider_id=self._provider_id,
                latency_ms=elapsed, error=f"HTTP {resp.status_code}",
            )
        except Exception as e:
            return HealthCheckResult(
                ok=False, provider_id=self._provider_id, error=str(e),
            )

    def sync(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []

        events: list[dict[str, Any]] = []
        files = self._list_files()

        for raw in files:
            doc = self._mapper.file_to_document(raw, self._provider_id)
            event_type = "DOCUMENT_UPDATED"
            if self._is_newly_added(raw):
                event_type = "DOCUMENT_ADDED"
            events.append(self._build_event(event_type, doc.to_dict()))

        return events

    def list_folder(self, folder_id: str = "root") -> list[dict[str, Any]]:
        files = self._list_files(
            query=f"'{folder_id}' in parents and trashed=false"
        )
        return [
            self._mapper.file_to_document(f, self._provider_id).to_dict()
            for f in files
        ]

    def discover_documents(
        self,
        mime_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        mime_types = mime_types or [
            "application/vnd.google-apps.document",
            "application/vnd.google-apps.spreadsheet",
            "application/vnd.google-apps.presentation",
            "text/plain",
            "application/pdf",
        ]

        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for mime in mime_types:
            files = self._list_files(query=f"mimeType='{mime}' and trashed=false", page_size=50)
            for raw in files:
                fid = raw.get("id", "")
                if fid not in seen:
                    seen.add(fid)
                    doc = self._mapper.file_to_document(raw, self._provider_id)
                    results.append(doc.to_dict())

        return results

    def _list_files(
        self,
        query: str = "trashed=false",
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        token = self._get_token()
        params: dict[str, Any] = {
            "q": query,
            "pageSize": page_size,
            "fields": "files(id,name,mimeType,size,webViewLink,createdTime,modifiedTime,parents)",
        }
        resp = requests.get(
            f"{DRIVE_API_BASE}/files",
            params=params,
            headers=self._auth_headers(token.access_token),
            timeout=15,
        )
        if resp.status_code == 401:
            token = self._token_manager.get_valid_token(self._provider_id)
            resp = requests.get(
                f"{DRIVE_API_BASE}/files",
                params=params,
                headers=self._auth_headers(token.access_token),
                timeout=15,
            )
        if resp.status_code != 200:
            logger.warning("Drive: failed to list files — HTTP %s", resp.status_code)
            return []
        return resp.json().get("files", [])

    def _is_newly_added(self, raw: dict[str, Any]) -> bool:
        created = raw.get("createdTime", "")
        modified = raw.get("modifiedTime", "")
        if not created or not modified:
            return False
        try:
            from datetime import timedelta
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            return (now - created_dt) < timedelta(hours=24)
        except Exception:
            return False

    def _get_token(self):
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            self._token_manager.get_valid_token(self._provider_id)
        )

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _build_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": "drive",
            "data": data,
        }
