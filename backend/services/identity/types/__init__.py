from __future__ import annotations

from dataclasses import dataclass
from typing import NewType

UserId = NewType("UserId", str)
OrganizationId = NewType("OrganizationId", str)
SessionId = NewType("SessionId", str)
MembershipId = NewType("MembershipId", str)
EmailIdentityId = NewType("EmailIdentityId", str)
ExternalIdentityId = NewType("ExternalIdentityId", str)
PasswordCredentialId = NewType("PasswordCredentialId", str)
RefreshTokenId = NewType("RefreshTokenId", str)
VerificationTokenId = NewType("VerificationTokenId", str)
InvitationId = NewType("InvitationId", str)
PasswordResetRequestId = NewType("PasswordResetRequestId", str)


@dataclass(frozen=True)
class EmailAddress:
    value: str

    def __post_init__(self) -> None:
        if "@" not in self.value or "." not in self.value.split("@")[-1]:
            raise ValueError(f"Invalid email address: {self.value}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PasswordHash:
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TokenHash:
    value: str

    def __str__(self) -> str:
        return self.value
