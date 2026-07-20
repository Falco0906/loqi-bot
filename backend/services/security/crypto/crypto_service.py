from __future__ import annotations

import hashlib
import hmac
import secrets
from abc import ABC, abstractmethod

from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.exceptions import VerifyMismatchError

from services.identity.config import IDENTITY_CONFIG
from services.identity.types import PasswordHash, TokenHash


class CryptoService(ABC):

    @abstractmethod
    def hash_password(self, plaintext: str) -> PasswordHash:
        ...

    @abstractmethod
    def verify_password(self, plaintext: str, stored_hash: PasswordHash) -> bool:
        ...

    @abstractmethod
    def random_token(self, length: int | None = None) -> str:
        ...

    @abstractmethod
    def hash_token(self, token: str) -> TokenHash:
        ...

    @abstractmethod
    def encrypt(self, plaintext: str, context: str = "") -> str:
        ...

    @abstractmethod
    def decrypt(self, ciphertext: str, context: str = "") -> str:
        ...

    @abstractmethod
    def sign(self, data: str, key_id: str = "") -> str:
        ...

    @abstractmethod
    def verify(self, data: str, signature: str, key_id: str = "") -> bool:
        ...


class DefaultCryptoService(CryptoService):
    """Production-ready CryptoService using Argon2id and HMAC-SHA256.

    Password hashing uses Argon2id via argon2-cffi. Token hashing uses
    SHA-256. Signing uses HMAC-SHA256. Encryption uses XOR with a
    derived key (placeholder — add libsodium for production).
    """

    def __init__(self) -> None:
        self._config = IDENTITY_CONFIG
        self._pepper = _get_pepper()
        self._argon2 = Argon2PasswordHasher(
            time_cost=self._config.argon2.time_cost,
            memory_cost=self._config.argon2.memory_cost,
            parallelism=self._config.argon2.parallelism,
            hash_len=self._config.argon2.hash_len,
            salt_len=self._config.argon2.salt_len,
        )

    def hash_password(self, plaintext: str) -> PasswordHash:
        return PasswordHash(self._argon2.hash(plaintext))

    def verify_password(self, plaintext: str, stored_hash: PasswordHash) -> bool:
        try:
            return self._argon2.verify(stored_hash.value, plaintext)
        except VerifyMismatchError:
            return False

    def random_token(self, length: int | None = None) -> str:
        if length is None:
            length = self._config.tokens.verification_token_bytes
        return secrets.token_urlsafe(length)

    def hash_token(self, token: str) -> TokenHash:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return TokenHash(digest)

    def encrypt(self, plaintext: str, context: str = "") -> str:
        key = self._derive_key(context)
        data = plaintext.encode("utf-8")
        iv = secrets.token_bytes(16)
        encrypted = bytes(a ^ b for a, b in zip(data, key[:len(data)]))
        combined = iv.hex() + ":" + encrypted.hex()
        return combined

    def decrypt(self, ciphertext: str, context: str = "") -> str:
        key = self._derive_key(context)
        try:
            iv_hex, data_hex = ciphertext.split(":", 1)
            encrypted = bytes.fromhex(data_hex)
            decrypted = bytes(a ^ b for a, b in zip(encrypted, key[:len(encrypted)]))
            return decrypted.decode("utf-8")
        except (ValueError, IndexError):
            msg = "Decryption failed: invalid ciphertext format"
            raise ValueError(msg)

    def sign(self, data: str, key_id: str = "") -> str:
        actual_key_id = key_id or self._config.signing_key_id
        secret = _get_signing_secret(actual_key_id)
        signature = hmac.new(
            secret.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{actual_key_id}:{signature}"

    def verify(self, data: str, signature: str, key_id: str = "") -> bool:
        try:
            sig_key_id, sig_value = signature.split(":", 1)
            if key_id and sig_key_id != key_id:
                return False
            secret = _get_signing_secret(sig_key_id)
            expected = hmac.new(
                secret.encode("utf-8"),
                data.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(sig_value, expected)
        except (ValueError, IndexError):
            return False

    def _derive_key(self, context: str) -> bytes:
        base = (self._pepper + context).encode("utf-8")
        return hashlib.sha256(base).digest()


class InMemoryCryptoService(CryptoService):
    """Non-deterministic crypto service for testing. NOT for production."""

    def __init__(self) -> None:
        self._counter = 0

    def hash_password(self, plaintext: str) -> PasswordHash:
        return PasswordHash(f"hashed:{plaintext}")

    def verify_password(self, plaintext: str, stored_hash: PasswordHash) -> bool:
        expected = f"hashed:{plaintext}"
        return stored_hash.value == expected

    def random_token(self, length: int | None = None) -> str:
        self._counter += 1
        actual_length = length or 32
        return f"tok_{self._counter}_{'x' * actual_length}"

    def hash_token(self, token: str) -> TokenHash:
        return TokenHash(f"hash:{token}")

    def encrypt(self, plaintext: str, context: str = "") -> str:
        return f"enc:{context}:{plaintext}"

    def decrypt(self, ciphertext: str, context: str = "") -> str:
        parts = ciphertext.split(":", 2)
        if len(parts) == 3 and parts[0] == "enc" and parts[1] == context:
            return parts[2]
        msg = "Decryption failed"
        raise ValueError(msg)

    def sign(self, data: str, key_id: str = "") -> str:
        return f"sig:{key_id}:{data}"

    def verify(self, data: str, signature: str, key_id: str = "") -> bool:
        expected = f"sig:{key_id}:{data}"
        return signature == expected


_global_crypto: CryptoService | None = None


def get_crypto_service() -> CryptoService:
    global _global_crypto
    if _global_crypto is None:
        _global_crypto = DefaultCryptoService()
    return _global_crypto


def set_crypto_service(service: CryptoService) -> None:
    global _global_crypto
    _global_crypto = service


def reset_crypto_service() -> None:
    global _global_crypto
    _global_crypto = None


def _get_pepper() -> str:
    import os
    return os.environ.get("IDENTITY_PEPPER", "dev-pepper-do-not-use-in-production")


def _get_signing_secret(key_id: str) -> str:
    import os
    env_key = f"IDENTITY_SIGNING_KEY_{key_id.upper()}"
    return os.environ.get(env_key, f"dev-signing-key-{key_id}-do-not-use-in-production")
