from __future__ import annotations

import json
import os
import secrets
from base64 import urlsafe_b64encode
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode

from services.identity.config import IDENTITY_CONFIG
from services.identity.contracts import (
    AuthRequest,
    ExternalIdentity,
    IdentityProvider,
    ProviderType,
)


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_code_verifier(length: int = 64) -> str:
    return _b64url(secrets.token_bytes(length))


def _generate_code_challenge(verifier: str) -> str:
    return _b64url(sha256(verifier.encode("ascii")).digest())


def _generate_state(length: int = 32) -> str:
    return _b64url(secrets.token_bytes(length))


def _generate_nonce(length: int = 16) -> str:
    return _b64url(secrets.token_bytes(length))


class GoogleIdentityProvider(IdentityProvider):

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.GOOGLE

    async def initiate_auth(self, redirect_uri: str) -> AuthRequest:
        cfg = IDENTITY_CONFIG.google_oauth
        verifier = _generate_code_verifier()
        challenge = _generate_code_challenge(verifier)
        state = _generate_state()
        nonce = _generate_nonce()

        params = {
            "client_id": cfg.client_id,
            "redirect_uri": redirect_uri or cfg.redirect_uri,
            "response_type": "code",
            "scope": cfg.scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "nonce": nonce,
            "access_type": "offline",
        }
        authorize_url = f"{cfg.auth_uri}?{urlencode(params)}"

        return AuthRequest(
            authorize_url=authorize_url,
            state=state,
            code_verifier=verifier,
            expires_at=datetime.now(timezone.utc) + timedelta(
                seconds=cfg.oauth_session_ttl_seconds,
            ),
        )

    async def handle_callback(
        self, code: str, state: str, code_verifier: str,
    ) -> ExternalIdentity:
        cfg = IDENTITY_CONFIG.google_oauth

        id_token = await self._exchange_code(code, code_verifier, cfg)

        payload = self._validate_id_token(id_token, cfg)
        email = payload.get("email", "")
        email_verified = payload.get("email_verified", False)
        if not email_verified:
            msg = "Google email not verified"
            raise ValueError(msg)

        return ExternalIdentity(
            provider=ProviderType.GOOGLE,
            provider_user_id=payload.get("sub", ""),
            email=email,
            name=payload.get("name", ""),
            avatar_url=payload.get("picture", ""),
            raw_attributes=payload,
        )

    async def _exchange_code(
        self, code: str, code_verifier: str, cfg: Any,
    ) -> dict[str, Any]:
        import httpx
        data = {
            "code": code,
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "redirect_uri": cfg.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(cfg.token_uri, data=data)
            resp.raise_for_status()
            token_data = resp.json()

        id_token_str = token_data.get("id_token")
        if not id_token_str:
            msg = "No id_token in Google token response"
            raise ValueError(msg)

        return self._decode_jwt_payload(id_token_str)

    def _decode_jwt_payload(self, token: str) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            msg = "Invalid JWT format"
            raise ValueError(msg)
        _, payload_b64, _ = parts
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        try:
            decoded = _b64url_decode(padded)
            return json.loads(decoded)
        except Exception as exc:
            msg = "Failed to decode JWT payload"
            raise ValueError(msg) from exc

    def _validate_id_token(
        self, payload: dict[str, Any], cfg: Any,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        skew = timedelta(seconds=cfg.clock_skew_seconds)

        exp = payload.get("exp", 0)
        if now > datetime.fromtimestamp(exp, tz=timezone.utc) + skew:
            msg = "ID token has expired"
            raise ValueError(msg)

        iss = payload.get("iss", "")
        if iss != cfg.issuer and iss != "accounts.google.com":
            msg = f"Invalid issuer: {iss}"
            raise ValueError(msg)

        aud = payload.get("aud", "")
        if aud != cfg.client_id:
            msg = f"Invalid audience: {aud}"
            raise ValueError(msg)

        email_verified = payload.get("email_verified", False)
        if not email_verified:
            msg = "Google email not verified"
            raise ValueError(msg)

        return payload

    async def link(self, user_id: str, external_identity: ExternalIdentity) -> bool:
        return True

    async def unlink(self, user_id: str, provider_type: ProviderType) -> bool:
        return True


def _b64url_decode(s: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(s)


# ─── Mock / Test provider ──────────────────────────────────────────────

class InMemoryGoogleIdentityProvider(GoogleIdentityProvider):
    """Deterministic Google provider for testing. No live HTTP calls."""

    def __init__(self) -> None:
        super().__init__()
        self._mock_id_token_payload: dict[str, Any] | None = None
        self._exchange_error: Exception | None = None
        self._counter = 0

    def set_mock_payload(self, payload: dict[str, Any]) -> None:
        self._mock_id_token_payload = dict(payload)

    def set_exchange_error(self, exc: Exception) -> None:
        self._exchange_error = exc

    async def initiate_auth(self, redirect_uri: str) -> AuthRequest:
        self._counter += 1
        cfg = IDENTITY_CONFIG.google_oauth
        verifier = f"verifier_{self._counter}"
        challenge = _generate_code_challenge(verifier)
        state = f"state_{self._counter}"
        nonce = f"nonce_{self._counter}"

        params = {
            "client_id": cfg.client_id or "mock_client_id",
            "redirect_uri": redirect_uri or cfg.redirect_uri or "http://localhost/callback",
            "response_type": "code",
            "scope": cfg.scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "nonce": nonce,
            "access_type": "offline",
        }
        authorize_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

        return AuthRequest(
            authorize_url=authorize_url,
            state=state,
            code_verifier=verifier,
            expires_at=datetime.now(timezone.utc) + timedelta(
                seconds=cfg.oauth_session_ttl_seconds,
            ),
        )

    async def handle_callback(
        self, code: str, state: str, code_verifier: str,
    ) -> ExternalIdentity:
        if self._exchange_error is not None:
            raise self._exchange_error

        if self._mock_id_token_payload is None:
            self._counter += 1
            payload: dict[str, Any] = {
                "sub": f"google_sub_{self._counter}",
                "email": f"user_{self._counter}@gmail.com",
                "name": f"User {self._counter}",
                "picture": f"https://example.com/avatar_{self._counter}.jpg",
                "email_verified": True,
                "iss": "https://accounts.google.com",
                "aud": IDENTITY_CONFIG.google_oauth.client_id or "mock_client_id",
                "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
            }
        else:
            payload = self._mock_id_token_payload

        self._validate_id_token(payload, IDENTITY_CONFIG.google_oauth)

        return ExternalIdentity(
            provider=ProviderType.GOOGLE,
            provider_user_id=payload.get("sub", ""),
            email=payload.get("email", ""),
            name=payload.get("name", ""),
            avatar_url=payload.get("picture", ""),
            raw_attributes=payload,
        )
