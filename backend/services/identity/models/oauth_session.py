from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class OAuthSession:
    id: str = field(default_factory=lambda: str(uuid4()))
    provider_type: str = ""
    state: str = ""
    code_verifier: str = ""
    nonce: str = ""
    redirect_uri: str = ""
    used_at: datetime | None = None
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    def mark_used(self) -> None:
        self.used_at = datetime.now(timezone.utc)
