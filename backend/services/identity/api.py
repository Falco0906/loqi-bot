from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request

from services.identity.metrics import get_metrics
from services.identity.models import RegistrationSessionStatus
from services.identity.models.oauth_session import OAuthSession
from services.identity.providers import (
    ConsoleEmailProvider,
    EmailProvider,
    GoogleIdentityProvider,
    get_provider_registry,
)
from services.email.config import EmailConfig
from services.identity.repositories import (
    InMemoryEmailIdentityRepository,
    InMemoryExternalIdentityRepository,
    InMemoryMembershipRepository,
    InMemoryOAuthSessionRepository,
    InMemoryOrganizationRepository,
    InMemoryPasswordCredentialRepository,
    InMemoryPasswordResetRepository,
    InMemoryRefreshTokenRepository,
    InMemoryRegistrationSessionRepository,
    InMemorySessionRepository,
    InMemoryVerificationTokenRepository,
)
from services.persistence import (
    REPOSITORY_PROVIDER,
    RepositoryProvider,
)
from services.persistence.repositories import (
    SupabaseUserRepository,
    SupabaseSessionRepository,
    SupabaseRefreshTokenRepository,
    SupabaseVerificationTokenRepository,
    SupabasePasswordResetRepository,
)
from services.identity.services import (
    AuthService,
    MembershipService,
    OrganizationService,
    PasswordService,
    SessionService,
    TokenService,
    UserService,
    VerificationService,
)
from services.security.crypto import get_crypto_service

from services.identity.schemas import (
    EmailCompleteRequest,
    EmailSignupRequest,
    EmailVerifyRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    LogoutResponse,
    MeOrganizationResponse,
    MeResponse,
    OAuthCallbackResponse,
    OAuthRedirectResponse,
    RefreshRequest,
    SessionInfo,
    SessionListResponse,
    SessionRevokeResponse,
    SignupResponse,
    StatusResponse,
    TokenResponse,
    VerifyResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

log = logging.getLogger("loqi.auth")


# ─── Service wiring ────────────────────────────────────────────────────

def _make_identity_repositories():
    # The User aggregate is the account of record and is always durable
    # through Supabase (identity_users). The remaining identity repositories
    # follow the repository provider selection until their tables are applied.
    if REPOSITORY_PROVIDER == RepositoryProvider.SUPABASE:
        vt_repo = SupabaseVerificationTokenRepository()
        session_repo = SupabaseSessionRepository()
        rt_repo = SupabaseRefreshTokenRepository()
        pr_repo = SupabasePasswordResetRepository()
    else:
        vt_repo = InMemoryVerificationTokenRepository()
        session_repo = InMemorySessionRepository()
        rt_repo = InMemoryRefreshTokenRepository()
        pr_repo = InMemoryPasswordResetRepository()
    return {
        "reg_session_repo": InMemoryRegistrationSessionRepository(),
        "vt_repo": vt_repo,
        "ei_repo": InMemoryEmailIdentityRepository(),
        "user_repo": SupabaseUserRepository(),
        "pc_repo": InMemoryPasswordCredentialRepository(),
        "org_repo": InMemoryOrganizationRepository(),
        "mem_repo": InMemoryMembershipRepository(),
        "session_repo": session_repo,
        "rt_repo": rt_repo,
        "pr_repo": pr_repo,
        "ext_id_repo": InMemoryExternalIdentityRepository(),
    }


def _create_email_provider(config: EmailConfig | None = None) -> EmailProvider:
    if config is None:
        config = EmailConfig()
    if config.provider == "resend":
        from services.email.resend_provider import ResendEmailProvider
        return ResendEmailProvider(config)
    return ConsoleEmailProvider()


def _build_auth_service() -> AuthService:
    crypto = get_crypto_service()
    r = _make_identity_repositories()

    user_svc = UserService(r["user_repo"], r["ei_repo"])
    org_svc = OrganizationService(r["org_repo"], r["mem_repo"])
    mem_svc = MembershipService(r["mem_repo"], r["user_repo"], r["org_repo"])
    ver_svc = VerificationService(r["vt_repo"], r["ei_repo"], crypto)
    pwd_svc = PasswordService(r["pc_repo"], r["user_repo"], crypto)
    ses_svc = SessionService(r["session_repo"], r["rt_repo"])
    tok_svc = TokenService(r["rt_repo"], r["session_repo"], crypto)

    registry = get_provider_registry()
    try:
        registry.get("google")
    except Exception:
        registry.register(GoogleIdentityProvider())

    provider = os.getenv("EMAIL_PROVIDER", "console")
    api_key = os.getenv("RESEND_API_KEY", "")
    app_env = os.getenv("APP_ENV", "development")

    if provider == "resend" and not api_key:
        if app_env == "production":
            raise RuntimeError("EMAIL_PROVIDER is set to 'resend' but RESEND_API_KEY is missing.")
        log.warning("EMAIL_PROVIDER is set to 'resend' but RESEND_API_KEY is missing. Falling back to console.")
        provider = "console"

    email_config = EmailConfig(
        provider=provider,
        api_key=api_key,
        from_email=os.getenv("RESEND_FROM_EMAIL", "noreply@loqi.ai"),
        from_name="Loqi",
        reply_to="",
        app_url=os.getenv("FRONTEND_URL", "http://localhost:3000"),
        company_name="Loqi",
    )
    return AuthService(
        email_provider=_create_email_provider(email_config),
        crypto=crypto,
        registration_session_repo=r["reg_session_repo"],
        verification_token_repo=r["vt_repo"],
        email_identity_repo=r["ei_repo"],
        refresh_token_repo=r["rt_repo"],
        user_svc=user_svc,
        org_svc=org_svc,
        membership_svc=mem_svc,
        verification_svc=ver_svc,
        password_svc=pwd_svc,
        session_svc=ses_svc,
        token_svc=tok_svc,
        app_url=email_config.app_url,
        external_identity_repo=r["ext_id_repo"],
    )


_auth_service: AuthService | None = None


def _get_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = _build_auth_service()
    return _auth_service


async def get_authenticated_user_id(request: Request) -> str:
    """Resolve the authenticated user from the opaque session access token."""
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        session = await _get_service().validate_access_token(token.strip())
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
    return session.user_id


def get_auth_user_service() -> UserService | None:
    svc = _get_service()
    return svc._user if hasattr(svc, "_user") else None


def set_auth_service(svc: AuthService | None) -> None:
    global _auth_service
    _auth_service = svc


def reset_auth_service() -> None:
    set_auth_service(None)


# ─── Endpoints ─────────────────────────────────────────────────────────

_oauth_session_repo: InMemoryOAuthSessionRepository | None = None
_oauth_callback_results: dict[str, tuple[str, OAuthCallbackResponse]] = {}


def _get_oauth_session_repo() -> InMemoryOAuthSessionRepository:
    global _oauth_session_repo
    if _oauth_session_repo is None:
        _oauth_session_repo = InMemoryOAuthSessionRepository()
    return _oauth_session_repo


def reset_oauth_session_repo() -> None:
    global _oauth_session_repo, _oauth_callback_results
    _oauth_session_repo = None
    _oauth_callback_results = {}


@router.get(
    "/oauth/google",
    response_model=OAuthRedirectResponse,
    summary="Initiate Google OAuth",
    description="Generate Google OAuth authorization URL with PKCE. "
    "Redirect the user to this URL to authenticate with Google.",
    response_description="Google OAuth authorization URL",
)
async def oauth_google(redirect_uri: str = ""):
    registry = get_provider_registry()
    provider = registry.get("google")
    auth_req = await provider.initiate_auth(redirect_uri)

    oauth_session = OAuthSession(
        provider_type="google",
        state=auth_req.state,
        code_verifier=auth_req.code_verifier,
        expires_at=auth_req.expires_at,
    )
    repo = _get_oauth_session_repo()
    await repo.save(oauth_session)

    return OAuthRedirectResponse(authorize_url=auth_req.authorize_url)


@router.get(
    "/oauth/google/callback",
    response_model=OAuthCallbackResponse,
    summary="Google OAuth callback",
    description="Handle Google OAuth callback. Validates state, exchanges "
    "authorization code, resolves user, creates session, and returns tokens.",
    response_description="Access and refresh tokens",
)
async def oauth_google_callback(code: str = "", state: str = ""):
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    repo = _get_oauth_session_repo()
    oauth_session = await repo.find_by_state(state)
    if oauth_session is None:
        raise HTTPException(status_code=401, detail="Invalid state parameter")
    if oauth_session.is_expired:
        await repo.delete(oauth_session.id)
        raise HTTPException(status_code=401, detail="OAuth session expired")
    if oauth_session.is_used:
        cached = _oauth_callback_results.get(state)
        if cached is not None and cached[0] == code:
            # Browsers/dev-mode React can replay the callback URL after the
            # first request has already succeeded. Return the same issued
            # session rather than presenting a successful login as a failure.
            return cached[1]
        raise HTTPException(status_code=401, detail="OAuth state already used — possible replay attack")

    oauth_session.mark_used()
    await repo.save(oauth_session)

    svc = _get_service()
    try:
        result = await svc.oauth_login(
            provider_type="google",
            code=code,
            state=state,
            code_verifier=oauth_session.code_verifier,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    get_metrics().login_total["ok"] += 1
    response = OAuthCallbackResponse(
        access_token=result.session.id,
        refresh_token=result.refresh_token,
        session_id=result.session.id,
        user_id=result.session.user_id,
        org_id=result.session.organization_id,
        expires_at=result.session.expires_at,
        is_new_user=result.is_new_user,
    )
    _oauth_callback_results[state] = (code, response)
    if len(_oauth_callback_results) > 1000:
        oldest = next(iter(_oauth_callback_results))
        del _oauth_callback_results[oldest]
    return response


@router.post(
    "/signup/email",
    response_model=SignupResponse,
    summary="Begin email registration",
    description="Start the registration flow by providing an email address. "
    "Sends a verification email with a one-time token. Returns a session ID "
    "that can be polled for status.",
    response_description="Registration session created",
)
async def signup_email(payload: EmailSignupRequest):
    svc = _get_service()
    result = await svc.begin_registration(payload.email)
    rs = result.registration_session
    get_metrics().signup_total["ok"] += 1
    return SignupResponse(
        registration_session_id=rs.id,
        expires_at=rs.expires_at,
    )


@router.get(
    "/signup/email/status/{registration_session_id}",
    response_model=StatusResponse,
    summary="Get registration status",
    description="Poll the status of a registration session. Returns pending, "
    "verified, or completed. Used for cross-device verification flows.",
    response_description="Registration session status",
)
async def signup_status(registration_session_id: str):
    svc = _get_service()
    rs = await svc.get_registration_status(registration_session_id)
    if rs is None:
        raise HTTPException(status_code=404, detail="Registration session not found")
    return StatusResponse(
        registration_session_id=rs.id,
        email=rs.email,
        status=rs.status.value,
    )


@router.post(
    "/signup/email/verify",
    response_model=VerifyResponse,
    summary="Verify email with token",
    description="Complete email verification using the one-time token sent "
    "during registration. Marks the email as verified and transitions the "
    "registration session to verified status.",
    response_description="Email verification result",
)
async def signup_verify(payload: EmailVerifyRequest):
    svc = _get_service()
    await svc.verify_email(payload.token)
    get_metrics().verify_total["ok"] += 1
    return VerifyResponse()


@router.post(
    "/signup/email/complete",
    response_model=TokenResponse,
    summary="Complete registration",
    description="Finish registration by providing a display name, password, "
    "and organization name. Creates the user, organization, membership, and "
    "returns access and refresh tokens.",
    response_description="Access and refresh tokens",
)
async def signup_complete(payload: EmailCompleteRequest):
    svc = _get_service()
    result = await svc.complete_registration(
        payload.registration_session_id,
        payload.display_name,
        payload.password,
        payload.organization_name,
    )
    get_metrics().signup_total["ok"] += 1
    return TokenResponse(
        access_token=result.session.id,
        refresh_token=result.refresh_token,
        session_id=result.session.id,
        user_id=result.session.user_id,
        org_id=result.session.organization_id,
        expires_at=result.session.expires_at,
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login with email and password",
    description="Authenticate a user with their email and password. Returns "
    "a session-based access token (15min TTL) and a refresh token (30d TTL).",
    response_description="Access and refresh tokens",
)
async def login(payload: LoginRequest):
    svc = _get_service()
    result = await svc.login(payload.email, payload.password)
    get_metrics().login_total["ok"] += 1
    return TokenResponse(
        access_token=result.session.id,
        refresh_token=result.refresh_token,
        session_id=result.session.id,
        user_id=result.session.user_id,
        org_id=result.session.organization_id,
        expires_at=result.session.expires_at,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Exchange a valid refresh token for a new access token and "
    "a new refresh token (rotation-enabled). Single-use; replay detection "
    "revokes the entire token family.",
    response_description="New access and refresh tokens",
)
async def refresh(payload: RefreshRequest):
    svc = _get_service()
    result = await svc.refresh(payload.refresh_token)
    get_metrics().refresh_total["ok"] += 1
    session = result.session
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        session_id=session.id,
        user_id=session.user_id,
        org_id=session.organization_id,
        expires_at=session.expires_at,
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout and revoke session",
    description="Revoke the current session by providing its refresh token. "
    "All tokens in the family are invalidated.",
    response_description="Logout confirmation",
)
async def logout(payload: LogoutRequest):
    svc = _get_service()
    await svc.logout(payload.refresh_token)
    get_metrics().logout_total["ok"] += 1
    return LogoutResponse()


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get current user info",
    description="Returns the current user's profile and organization membership information.",
)
async def get_me(user_id: str = ""):
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id query parameter required")
    svc = _get_service()
    return await svc.get_current_user_info(user_id)


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="List active sessions",
    description="List all active sessions for a user. Used for session "
    "management and visibility into active devices.",
    response_description="List of active sessions",
)
async def list_sessions(user_id: str = ""):
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id query parameter required")
    svc = _get_service()
    sessions = await svc.list_sessions(user_id)
    return SessionListResponse(
        sessions=[
            SessionInfo(
                id=s.id,
                device_info=s.device_info,
                created_at=s.created_at,
                last_activity_at=s.last_activity_at,
                is_active=s.is_active,
            )
            for s in sessions
        ],
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=SessionRevokeResponse,
    summary="Revoke a session",
    description="Revoke a specific session by its ID. The session and all "
    "its refresh tokens are invalidated.",
    response_description="Session revocation confirmation",
)
async def revoke_session(session_id: str):
    svc = _get_service()
    await svc.revoke_session(session_id)
    get_metrics().session_revoked_total["ok"] += 1
    return SessionRevokeResponse()
