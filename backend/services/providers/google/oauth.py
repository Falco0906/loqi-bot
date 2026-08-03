from __future__ import annotations

import json
import os
import secrets
import time
from base64 import urlsafe_b64encode
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode

import requests

from services.providers.oauth import OAuthFlow, OAuthToken


AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_code_verifier(length: int = 64) -> str:
    return _b64url(secrets.token_bytes(length))


def _generate_code_challenge(verifier: str) -> str:
    return _b64url(sha256(verifier.encode("ascii")).digest())


def _generate_state(length: int = 32) -> str:
    return _b64url(secrets.token_bytes(length))


def _read_client_config() -> dict[str, str]:
    return {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": os.environ.get(
            "GOOGLE_REDIRECT_URI",
            os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback"),
        ),
    }


_GOOGLE_KNOWN_SCOPES = {
    "gmail": [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.labels",
        "https://www.googleapis.com/auth/gmail.readonly",
    ],
    "calendar": [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events.readonly",
    ],
    "drive": [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ],
}


def _scopes_for(*providers: str) -> str:
    seen: set[str] = set()
    for p in providers:
        for s in _GOOGLE_KNOWN_SCOPES.get(p, []):
            seen.add(s)
    return " ".join(sorted(seen))


class GoogleOAuthFlow(OAuthFlow):
    """Google OAuth 2.0 with PKCE.

    Reads client_id / client_secret from environment:
        GOOGLE_CLIENT_ID
        GOOGLE_CLIENT_SECRET
        GOOGLE_REDIRECT_URI (optional, defaults to localhost callback)
    """

    def __init__(
        self,
        scopes: str | None = None,
        provider_id: str = "google",
        client_id: str = "",
        client_secret: str = "",
        redirect_uri: str = "",
    ) -> None:
        config = _read_client_config()
        self._client_id = client_id or config["client_id"]
        self._client_secret = client_secret or config["client_secret"]
        self._redirect_uri = redirect_uri or config["redirect_uri"]
        self._scopes = scopes or _scopes_for("gmail")
        self._provider_id = provider_id

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def authorization_url(self, state: str = "", redirect_uri: str = "") -> str:
        state = state or _generate_state()
        uri = redirect_uri or self._redirect_uri
        verifier = _generate_code_verifier()
        challenge = _generate_code_challenge(verifier)

        params = {
            "client_id": self._client_id,
            "redirect_uri": uri,
            "response_type": "code",
            "scope": self._scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{AUTH_URI}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str = "") -> OAuthToken:
        uri = redirect_uri or self._redirect_uri
        data = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": uri,
            "grant_type": "authorization_code",
        }
        resp = requests.post(TOKEN_URI, data=data, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        return self._parse_token_response(body)

    async def refresh_token(self, token: OAuthToken) -> OAuthToken:
        if not token.refresh_token:
            raise RuntimeError("No refresh_token available to refresh")

        data = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": token.refresh_token,
            "grant_type": "refresh_token",
        }
        resp = requests.post(TOKEN_URI, data=data, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        new_token = self._parse_token_response(body)
        new_token.refresh_token = token.refresh_token
        return new_token

    async def revoke_token(self, token: OAuthToken) -> None:
        requests.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": token.access_token},
            timeout=10,
        )

    def _parse_token_response(self, body: dict[str, Any]) -> OAuthToken:
        expires_in = body.get("expires_in", 3600)
        return OAuthToken(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token", ""),
            expires_at=time.time() + expires_in,
            scope=body.get("scope", self._scopes),
            token_type=body.get("token_type", "Bearer"),
            provider_id=self._provider_id,
            raw=body,
        )


def build_gmail_flow() -> GoogleOAuthFlow:
    return GoogleOAuthFlow(
        scopes=_scopes_for("gmail"),
        provider_id="gmail",
    )


def build_calendar_flow() -> GoogleOAuthFlow:
    return GoogleOAuthFlow(
        scopes=_scopes_for("calendar"),
        provider_id="calendar",
    )


def build_drive_flow() -> GoogleOAuthFlow:
    return GoogleOAuthFlow(
        scopes=_scopes_for("drive"),
        provider_id="drive",
    )
