from __future__ import annotations

import os

from supabase import Client
from services.platform.test_runtime import (
    create_supabase_client,
    is_test_runtime,
    validate_test_database_authorization,
    validate_supabase_client,
    UnsafeTestDatabaseConfiguration,
)


class SupabaseConnectionManager:

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        *,
        client: Client | None = None,
        authorization=None,
    ) -> None:
        self._authorization = None
        self._url = url if url is not None else ("" if is_test_runtime() else os.getenv("SUPABASE_URL", ""))
        self._key = key if key is not None else ("" if is_test_runtime() else os.getenv("SUPABASE_KEY", ""))

        if is_test_runtime():
            if client is not None:
                if url or key:
                    raise RuntimeError("Injected test clients cannot be combined with URL/key arguments")
                is_sdk_client = validate_supabase_client(client, authorization)
                self._client = client
                if is_sdk_client:
                    self._authorization = validate_test_database_authorization(authorization)
                return
            if url or key:
                self._authorization = validate_test_database_authorization(
                    authorization, url=url or "", key=key or ""
                )
                self._client = create_supabase_client(
                    url or "", key or "", authorization=self._authorization
                )
                return
            if authorization is not None:
                self._authorization = validate_test_database_authorization(authorization)
                self._url = authorization.url
                self._key = authorization.key
            else:
                self._url = self._key = ""
            self._client = None
            return

        self._client = client

    def get_client(self) -> Client | None:
        if self._client is not None:
            validate_supabase_client(self._client, self._authorization)
            return self._client
        if not self._url or not self._key:
            return None
        try:
            self._client = create_supabase_client(
                self._url, self._key, authorization=self._authorization
            )
            return self._client
        except UnsafeTestDatabaseConfiguration:
            raise
        except Exception:
            return None

    def validate_test_runtime_client(self) -> None:
        """Ensure a shared manager cannot smuggle application credentials into tests."""
        if not is_test_runtime():
            return
        if self._client is not None:
            is_sdk_client = validate_supabase_client(self._client, self._authorization)
            if not is_sdk_client and (self._url or self._key):
                raise RuntimeError("Injected test doubles cannot carry external connection settings")
        elif self._url or self._key:
            validate_test_database_authorization(
                self._authorization, url=self._url, key=self._key
            )

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
    if manager is not None and is_test_runtime():
        manager.validate_test_runtime_client()
    _manager = manager


def reset_connection_manager() -> None:
    global _manager
    _manager = None
