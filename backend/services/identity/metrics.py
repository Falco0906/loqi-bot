from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class AuthMetrics:
    signup_total: Counter[str] = field(default_factory=lambda: Counter())      # ok, duplicate
    verify_total: Counter[str] = field(default_factory=lambda: Counter())      # ok, fail
    login_total: Counter[str] = field(default_factory=lambda: Counter())       # ok, fail
    refresh_total: Counter[str] = field(default_factory=lambda: Counter())     # ok, fail, replay
    logout_total: Counter[str] = field(default_factory=lambda: Counter())      # ok, fail
    session_revoked_total: Counter[str] = field(default_factory=lambda: Counter())  # ok, fail

    def snapshot(self) -> dict:
        return {
            "signup": dict(self.signup_total),
            "verify": dict(self.verify_total),
            "login": dict(self.login_total),
            "refresh": dict(self.refresh_total),
            "logout": dict(self.logout_total),
            "session_revoked": dict(self.session_revoked_total),
        }

    def merge(self, other: AuthMetrics) -> None:
        self.signup_total.update(other.signup_total)
        self.verify_total.update(other.verify_total)
        self.login_total.update(other.login_total)
        self.refresh_total.update(other.refresh_total)
        self.logout_total.update(other.logout_total)
        self.session_revoked_total.update(other.session_revoked_total)

    def reset(self) -> None:
        self.signup_total.clear()
        self.verify_total.clear()
        self.login_total.clear()
        self.refresh_total.clear()
        self.logout_total.clear()
        self.session_revoked_total.clear()


_metrics = AuthMetrics()


def get_metrics() -> AuthMetrics:
    return _metrics


def reset_metrics() -> None:
    _metrics.reset()
