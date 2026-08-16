from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


# ─── Request models ────────────────────────────────────────────────────

class EmailSignupRequest(BaseModel):
    email: str


class EmailVerifyRequest(BaseModel):
    token: str


class EmailCompleteRequest(BaseModel):
    registration_session_id: str
    display_name: str
    password: str
    organization_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordResetRequestPayload(BaseModel):
    email: str


class PasswordResetConfirmRequest(BaseModel):
    email: str
    token: str
    new_password: str


# ─── Response models ───────────────────────────────────────────────────

class SignupResponse(BaseModel):
    registration_session_id: str
    expires_at: datetime


class StatusResponse(BaseModel):
    registration_session_id: str
    email: str
    status: str


class VerifyResponse(BaseModel):
    ok: bool = True
    message: str = "Email verified successfully"


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    session_id: str
    user_id: str
    org_id: str
    expires_at: datetime


class LoginResponse(TokenResponse):
    """Alias for TokenResponse — returned by login endpoint."""


class LogoutResponse(BaseModel):
    ok: bool = True
    message: str = "Logged out successfully"


class SessionRevokeResponse(BaseModel):
    ok: bool = True
    message: str = "Session revoked"


class SessionInfo(BaseModel):
    id: str
    device_info: str
    created_at: datetime
    last_activity_at: datetime
    is_active: bool


class SessionListResponse(BaseModel):
    sessions: list[SessionInfo]


# ─── OAuth models ─────────────────────────────────────────────────────

class OAuthRedirectResponse(BaseModel):
    authorize_url: str


class OAuthCallbackResponse(BaseModel):
    access_token: str
    refresh_token: str
    session_id: str
    user_id: str
    org_id: str
    expires_at: datetime
    is_new_user: bool = False


# ─── Error response ────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    code: str
    message: str
    detail: str | None = None
    request_id: str = ""


# ─── /me response ──────────────────────────────────────────────────────

class MeOrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: str
    onboarding_complete: bool = False
    organization: MeOrganizationResponse | None = None
