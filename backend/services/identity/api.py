from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.identity.metrics import get_metrics
from services.identity.models import RegistrationSessionStatus
from services.identity.models.oauth_session import OAuthSession
from services.identity.providers import (
    ConsoleEmailProvider,
    GoogleIdentityProvider,
    get_provider_registry,
)
from services.identity.repositories import (
    InMemoryEmailIdentityRepository,
    InMemoryExternalIdentityRepository,
    InMemoryMembershipRepository,
    InMemoryOAuthSessionRepository,
    InMemoryOrganizationRepository,
    InMemoryPasswordCredentialRepository,
    InMemoryRefreshTokenRepository,
    InMemoryRegistrationSessionRepository,
    InMemorySessionRepository,
    InMemoryUserRepository,
    InMemoryVerificationTokenRepository,
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


# ─── Service wiring ────────────────────────────────────────────────────

def _build_auth_service() -> AuthService:
    crypto = get_crypto_service()
    reg_session_repo = InMemoryRegistrationSessionRepository()
    vt_repo = InMemoryVerificationTokenRepository()
    ei_repo = InMemoryEmailIdentityRepository()
    user_repo = InMemoryUserRepository()
    pc_repo = InMemoryPasswordCredentialRepository()
    org_repo = InMemoryOrganizationRepository()
    mem_repo = InMemoryMembershipRepository()
    session_repo = InMemorySessionRepository()
    rt_repo = InMemoryRefreshTokenRepository()
    ext_id_repo = InMemoryExternalIdentityRepository()

    user_svc = UserService(user_repo, ei_repo)
    org_svc = OrganizationService(org_repo, mem_repo)
    mem_svc = MembershipService(mem_repo, user_repo, org_repo)
    ver_svc = VerificationService(vt_repo, ei_repo, crypto)
    pwd_svc = PasswordService(pc_repo, user_repo, crypto)
    ses_svc = SessionService(session_repo, rt_repo)
    tok_svc = TokenService(rt_repo, session_repo, crypto)

    registry = get_provider_registry()
    try:
        registry.get("google")
    except Exception:
        registry.register(GoogleIdentityProvider())

    return AuthService(
        email_provider=ConsoleEmailProvider(),
        crypto=crypto,
        registration_session_repo=reg_session_repo,
        verification_token_repo=vt_repo,
        email_identity_repo=ei_repo,
        refresh_token_repo=rt_repo,
        user_svc=user_svc,
        org_svc=org_svc,
        membership_svc=mem_svc,
        verification_svc=ver_svc,
        password_svc=pwd_svc,
        session_svc=ses_svc,
        token_svc=tok_svc,
        external_identity_repo=ext_id_repo,
    )


_auth_service: AuthService | None = None


def _get_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = _build_auth_service()
    return _auth_service


def set_auth_service(svc: AuthService | None) -> None:
    global _auth_service
    _auth_service = svc


def reset_auth_service() -> None:
    set_auth_service(None)


# ─── Endpoints ─────────────────────────────────────────────────────────

_oauth_session_repo: InMemoryOAuthSessionRepository | None = None


def _get_oauth_session_repo() -> InMemoryOAuthSessionRepository:
    global _oauth_session_repo
    if _oauth_session_repo is None:
        _oauth_session_repo = InMemoryOAuthSessionRepository()
    return _oauth_session_repo


def reset_oauth_session_repo() -> None:
    global _oauth_session_repo
    _oauth_session_repo = None


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
        await repo.delete(oauth_session.id)
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
    return OAuthCallbackResponse(
        access_token=result.session.id,
        refresh_token=result.refresh_token,
        session_id=result.session.id,
        user_id=result.session.user_id,
        org_id=result.session.organization_id,
        expires_at=result.session.expires_at,
    )


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
