"""Runtime projection between connected communication and outbound providers."""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from services.adapters.credential_registry import CredentialRegistry
from services.adapters.credentials import CredentialInstance
from services.communication.provider_registry import get_provider
from services.outbound.outbound_registry import register_instance as register_outbound_instance


log = logging.getLogger("loqi")

# Compatibility projection only. Durable connected-account credentials remain
# authoritative; this registry supplies the legacy execution bridge.
credential_registry = CredentialRegistry()


def register_google_oauth_credential_instance(
    access_token: str,
    refresh_token: str,
    email: str,
) -> None:
    """Expose a connected Gmail account to the legacy execution bridge."""
    instance = CredentialInstance(
        credential_id=f"google_oauth2::{email}",
        descriptor_name="google_oauth2",
        values={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "email": email,
        },
    )
    log.info("Credential instance registered: %s", instance.credential_id)


def register_outbound_gmail_instance(
    communication_provider_id: str,
    *,
    token_expiry: float | None = None,
) -> None:
    """Configure an outbound Gmail runtime provider from a connected Inbox provider."""
    from services.outbound.gmail_outbound import GmailOutboundProvider

    communication_provider = get_provider(communication_provider_id)
    if not communication_provider:
        log.warning("[outbound] No communication provider found for %s", communication_provider_id)
        return

    access_token = getattr(communication_provider, "_access_token", "")
    refresh_token = getattr(communication_provider, "_refresh_token", "")
    if not access_token and not refresh_token:
        log.warning("[outbound] No tokens available for provider %s", communication_provider_id)
        return

    outbound_provider = GmailOutboundProvider()
    outbound_provider.configure(
        provider_id=communication_provider_id,
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=getattr(communication_provider, "_client_id", ""),
        client_secret=getattr(communication_provider, "_client_secret", ""),
        token_expiry=(
            getattr(communication_provider, "_token_expiry", 0.0)
            if token_expiry is None
            else token_expiry
        ),
        user_id=getattr(communication_provider, "_user_id", ""),
    )
    register_outbound_instance(communication_provider_id, outbound_provider)
    log.info(
        "[outbound] Registered GmailOutboundProvider instance for %s",
        communication_provider_id,
    )


def restore_gmail_providers() -> None:
    """Restore durable Gmail connections into communication and outbound runtime registries."""
    from services.communication.gmail_provider import GmailProvider
    from services.communication.provider_registry import register_instance
    from services.gmail_auth_failure import GmailReauthRequired
    from services.google_auth import refresh_access_token
    from services.supabase import (
        load_all_provider_credentials,
        reconcile_connected_account_duplicates,
        update_google_access_token,
    )

    log.info("[startup] Attempting provider restoration from Supabase")
    try:
        reconcile_connected_account_duplicates()
    except Exception as error:
        log.warning("[startup] Connected-account duplicate reconciliation failed: %s", error)

    records = load_all_provider_credentials()
    if not records:
        log.info("[startup] No saved provider credentials found")
        return

    restored = 0
    reauth_restored = 0
    seen_user_providers: set[tuple[str, str]] = set()
    for row in records:
        try:
            user_id = row.get("id", "")
            provider_id = row.get("google_provider_id", "") or str(uuid.uuid4())
            refresh_token = row.get("google_refresh_token", "")
            access_token = row.get("google_access_token", "")
            email = row.get("email", "")
            account_id = row.get("account_id", "") or email
            client_id = row.get("google_client_id", "") or os.getenv("GOOGLE_CLIENT_ID", "")
            client_secret = row.get("google_client_secret", "") or os.getenv("GOOGLE_CLIENT_SECRET", "")
            token_expiry_str = row.get("token_expiry", "")
            account_status = row.get("status", "active")
            key = (user_id, "google")
            if key in seen_user_providers:
                log.warning(
                    "[startup] Skipping duplicate provider restore for user %s (already restored)",
                    user_id[:8],
                )
                continue
            seen_user_providers.add(key)

            token_expiry = 0.0
            if token_expiry_str:
                try:
                    token_expiry = datetime.fromisoformat(
                        token_expiry_str.replace("Z", "+00:00")
                    ).timestamp()
                except Exception:
                    token_expiry = 0.0
            if not refresh_token:
                log.warning("[startup] No refresh_token for provider %s, skipping", provider_id[:12])
                continue

            if account_status == "auth_failed":
                provider = GmailProvider()
                record = provider.connect(
                    auth_token=access_token,
                    user_id=user_id,
                    email=email,
                    account_id=account_id,
                    refresh_token=refresh_token,
                    client_id=client_id,
                    client_secret=client_secret,
                )
                provider.mark_reauth_required()
                register_instance(record.id, provider)
                log.warning(
                    "gmail_auth_reauth_required provider_id=%s user_id=%s action=reauth_required restored=yes",
                    record.id[:12],
                    user_id,
                )
                reauth_restored += 1
                continue

            if token_expiry <= time.time() + 60:
                log.info("[startup] Token expired for provider %s, refreshing", provider_id[:12])
                try:
                    token_result = refresh_access_token(refresh_token)
                    if token_result and token_result.get("access_token"):
                        access_token = token_result["access_token"]
                        token_expiry = time.time() + token_result.get("expires_in", 3600)
                        update_google_access_token(
                            user_id,
                            access_token=access_token,
                            token_expiry=datetime.fromtimestamp(
                                token_expiry,
                                tz=timezone.utc,
                            ).isoformat(),
                        )
                except GmailReauthRequired:
                    log.warning(
                        "gmail_auth_reauth_required provider_id=%s user_id=%s action=reauth_required restored=yes",
                        provider_id[:12],
                        user_id,
                    )
                    provider = GmailProvider()
                    record = provider.connect(
                        auth_token=access_token,
                        user_id=user_id,
                        email=email,
                        refresh_token=refresh_token,
                        client_id=client_id,
                        client_secret=client_secret,
                    )
                    provider.mark_reauth_required()
                    register_instance(record.id, provider)
                    reauth_restored += 1
                    continue
                except Exception as error:
                    log.warning(
                        "[startup] Token refresh failed for provider %s: %s",
                        provider_id[:12],
                        error,
                    )
                    continue

            provider = GmailProvider()
            record = provider.connect(
                auth_token=access_token,
                user_id=user_id,
                email=email,
                account_id=account_id,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
            )
            register_instance(record.id, provider)
            register_outbound_gmail_instance(record.id, token_expiry=token_expiry)
            log.info("[startup] Restored provider %s (%s)", record.id[:12], email)
            restored += 1
        except Exception as error:
            log.warning("[startup] Failed to restore provider: %s", error)

    log.info(
        "[startup] Provider restoration complete: %d restored, %d reauth-required",
        restored,
        reauth_restored,
    )


def register_gmail_provider() -> None:
    """Register the Gmail communication provider implementation."""
    from services.communication.gmail_provider import GmailProvider
    from services.communication.provider_registry import register_provider

    register_provider(GmailProvider)
    log.info("Gmail provider registered")


def register_gmail_credential_descriptors(credential_registry: Any) -> None:
    """Register Gmail's legacy execution credential descriptors once per process."""
    from services.adapters.credentials import CredentialDescriptor
    from services.adapters.google.gmail.gmail_adapter import CREDENTIAL_DESCRIPTORS

    for raw_descriptor in CREDENTIAL_DESCRIPTORS:
        descriptor = CredentialDescriptor(
            name=raw_descriptor["name"],
            display_name=raw_descriptor.get("display_name", raw_descriptor["name"]),
            description=raw_descriptor.get("description", ""),
            auth_type=raw_descriptor["auth_type"],
        )
        if not credential_registry.exists(descriptor.name):
            credential_registry.register(descriptor)
            log.info("Credential descriptor registered: %s", descriptor.name)


def reconcile_runtime_providers() -> None:
    """Keep one runtime provider instance per user and provider type."""
    from services.communication.communication_store import store as communication_store
    from services.communication.provider_registry import remove_instance
    from services.outbound.outbound_registry import remove_instance as remove_outbound_instance

    providers_by_key: dict[tuple[str, str], list[Any]] = {}
    for provider in communication_store.list_providers():
        provider_type = (
            provider.provider_type.value
            if hasattr(provider.provider_type, "value")
            else str(provider.provider_type)
        )
        providers_by_key.setdefault((provider.user_id, provider_type), []).append(provider)

    removed = 0
    unavailable_statuses = {
        "auth_failed",
        "expired_token",
        "scope_insufficient",
        "disconnected",
        "offline",
    }
    for (_, provider_type), providers in providers_by_key.items():
        if len(providers) <= 1:
            continue
        canonical = max(
            providers,
            key=lambda provider: (
                provider.status.value not in unavailable_statuses,
                provider.created_at or "",
            ),
        )
        for provider in providers:
            if provider.id == canonical.id:
                continue
            try:
                communication_store.remove_provider(provider.id)
            except Exception:
                pass
            try:
                remove_instance(provider.id)
            except Exception:
                pass
            try:
                remove_outbound_instance(provider.id)
            except Exception:
                pass
            removed += 1
            log.info(
                "runtime_provider_reconciled provider_id=%s user_id=%s provider_type=%s reason=duplicate",
                provider.id[:12],
                provider.user_id[:8] if provider.user_id else "",
                provider_type,
            )
    if removed:
        log.info("runtime_provider_reconcile removed=%d duplicate provider record(s)", removed)


def initialize_gmail_runtime() -> None:
    """Restore the Gmail runtime before workers consume communication providers."""
    try:
        register_gmail_provider()
    except Exception as error:
        log.warning("Gmail provider registration failed: %s", error)
    try:
        register_gmail_credential_descriptors(credential_registry)
    except Exception as error:
        log.warning("Credential descriptor registration failed: %s", error)
    try:
        restore_gmail_providers()
    except Exception as error:
        log.warning("Provider startup restoration failed: %s", error)
    try:
        reconcile_runtime_providers()
    except Exception as error:
        log.warning("Runtime provider reconciliation failed: %s", error)
