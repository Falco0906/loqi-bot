"""Authenticated encryption at rest for persisted provider credentials (PR10.7).

Design:
- AES-256-GCM (authenticated encryption) via the ``cryptography`` package.
- Encoded form: ``encv1.<key_id>.<urlsafe_b64(nonce || ciphertext || tag)>``.
- ``key_id`` is derived from the key so a future rotation can select the
  correct key (current + optional previous key are supported).
- Plaintext credentials are NEVER logged. Decryption happens only inside the
  provider credential-loading path.

In development, when no encryption key is configured, callers may persist
plaintext explicitly (dev-only). In production, config validation requires the
key, so plaintext is never written.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FORMAT_PREFIX = "encv1."
NONCE_LENGTH = 12
ENCRYPTED_SEPARATOR = "."


class CredentialDecryptionError(Exception):
    """Raised when a stored credential cannot be decrypted (tamper/wrong key)."""


def _key_bytes(key_hex: str) -> bytes:
    return bytes.fromhex(key_hex)


def _key_id(key_hex: str) -> str:
    digest = hashlib.sha256(_key_bytes(key_hex)).hexdigest()
    return digest[:8]


def _keys() -> dict[str, bytes]:
    """Return ``{key_id: key_bytes}`` for the configured current + previous keys."""
    keys: dict[str, bytes] = {}
    current = os.getenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if current:
        keys[_key_id(current)] = _key_bytes(current)
    previous = os.getenv("LOQI_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS", "").strip()
    if previous:
        keys[_key_id(previous)] = _key_bytes(previous)
    return keys


def encryption_key_configured() -> bool:
    return bool(os.getenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", "").strip())


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(FORMAT_PREFIX)


def encrypt_token(plaintext: str) -> str:
    """Encrypt a single credential value. Requires a configured key."""
    current = os.getenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if not current:
        raise CredentialDecryptionError("Encryption key is not configured")
    key = _key_bytes(current)
    nonce = os.urandom(NONCE_LENGTH)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    payload = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return f"{FORMAT_PREFIX}{_key_id(current)}.{payload}"


def decrypt_token(value: str) -> str:
    """Decrypt a stored credential value. Raises on tamper/wrong key."""
    if not is_encrypted(value):
        return value
    body = value[len(FORMAT_PREFIX):]
    key_id, _, payload = body.partition(ENCRYPTED_SEPARATOR)
    keys = _keys()
    key = keys.get(key_id)
    if key is None:
        raise CredentialDecryptionError(f"Unknown credential key id {key_id}")
    try:
        raw = base64.urlsafe_b64decode(payload)
    except (ValueError, TypeError) as error:
        raise CredentialDecryptionError("Malformed encrypted credential") from error
    if len(raw) < NONCE_LENGTH:
        raise CredentialDecryptionError("Malformed encrypted credential")
    nonce = raw[:NONCE_LENGTH]
    ciphertext = raw[NONCE_LENGTH:]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
    except InvalidTag as error:
        raise CredentialDecryptionError("Credential decryption failed (tampered or wrong key)") from error


def is_valid_key_format(value: str) -> bool:
    """AES-256 key as 64 lowercase/uppercase hex characters."""
    if not value or len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def is_placeholder_key(value: str) -> bool:
    """Reject obvious placeholder/example values in production."""
    lowered = value.strip().lower()
    if "replace" in lowered or "your_" in lowered or "example" in lowered:
        return True
    if lowered in {"0" * 64, "f" * 64, "deadbeef" * 8, "abcdef" * 11}:
        return True
    return len(set(lowered)) == 1  # a single repeated hex digit
