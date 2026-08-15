"""load_all_provider_credentials must skip connected_accounts rows without a
real refresh token (placeholders like 'xx' break provider restoration and
provider selection at startup)."""
from types import SimpleNamespace

import pytest

from services import supabase


def _fake_client(rows: list[dict]):
    class Builder:
        def __init__(self) -> None:
            self._rows = rows

        def neq(self, *_a, **_k):
            return self

        def is_(self, *_a, **_k):
            return self

        def order(self, *_a, **_k):
            return self

        def execute(self):
            return SimpleNamespace(data=self._rows)

    def select(*_a, **_k):
        return Builder()

    return SimpleNamespace(table=lambda _name: SimpleNamespace(select=select))


REAL = {
    "user_id": "u-owner",
    "provider": "google",
    "email": "owner@example.com",
    "display_name": "Owner",
    "access_token": "a" * 250,
    "refresh_token": "1//" + "x" * 100,
    "token_expires_at": "2026-08-12T05:08:47+00:00",
    "status": "active",
}
GARBAGE = {
    "user_id": "u-garbage",
    "provider": "google",
    "email": "ev@example.com",
    "display_name": "EV",
    "access_token": "xx",
    "refresh_token": "xx",
    "token_expires_at": "",
    "status": "active",
}


def test_skips_rows_without_real_refresh_token(monkeypatch):
    monkeypatch.setattr(supabase, "get_supabase_client", lambda: _fake_client([REAL, GARBAGE]))
    rows = supabase.load_all_provider_credentials()
    assert len(rows) == 1
    assert rows[0]["id"] == "u-owner"
    assert rows[0]["google_refresh_token"] == "1//" + "x" * 100


def test_all_placeholder_rows_returns_empty(monkeypatch):
    monkeypatch.setattr(supabase, "get_supabase_client", lambda: _fake_client([GARBAGE]))
    assert supabase.load_all_provider_credentials() == []


def test_empty_result(monkeypatch):
    monkeypatch.setattr(supabase, "get_supabase_client", lambda: _fake_client([]))
    assert supabase.load_all_provider_credentials() == []