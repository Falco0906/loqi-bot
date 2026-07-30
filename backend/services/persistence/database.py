from __future__ import annotations

import os

from supabase import Client, create_client


class SupabaseConnectionManager:

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
    ) -> None:
        self._url = url if url is not None else os.getenv("SUPABASE_URL", "")
        self._key = key if key is not None else os.getenv("SUPABASE_KEY", "")
        self._client: Client | None = None

    def get_client(self) -> Client | None:
        if self._client is not None:
            return self._client
        if not self._url or not self._key:
            return None
        try:
            self._client = create_client(self._url, self._key)
            return self._client
        except Exception:
            return None

    @property
    def is_connected(self) -> bool:
        return self._client is not None or (
            bool(self._url) and bool(self._key)
        )


_manager: SupabaseConnectionManager | None = None


def get_connection_manager() -> SupabaseConnectionManager:
    global _manager
    if _manager is None:
        _manager = SupabaseConnectionManager()
    return _manager


def set_connection_manager(manager: SupabaseConnectionManager | None) -> None:
    global _manager
    _manager = manager


def reset_connection_manager() -> None:
    global _manager
    _manager = None
