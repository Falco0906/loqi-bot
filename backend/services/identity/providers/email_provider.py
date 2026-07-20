from __future__ import annotations

from abc import ABC, abstractmethod


class EmailProvider(ABC):

    @abstractmethod
    async def send_verification_email(
        self, to: str, verification_url: str,
    ) -> None:
        ...

    @abstractmethod
    async def send_password_reset_email(
        self, to: str, reset_url: str,
    ) -> None:
        ...


class ConsoleEmailProvider(EmailProvider):
    """Logs emails to console. Suitable for development/testing."""

    async def send_verification_email(
        self, to: str, verification_url: str,
    ) -> None:
        print(f"[ConsoleEmailProvider] To: {to}")
        print(f"[ConsoleEmailProvider] Verification URL: {verification_url}")

    async def send_password_reset_email(
        self, to: str, reset_url: str,
    ) -> None:
        print(f"[ConsoleEmailProvider] To: {to}")
        print(f"[ConsoleEmailProvider] Password Reset URL: {reset_url}")
