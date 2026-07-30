from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import uuid4

from services.identity.config import IDENTITY_CONFIG
from services.identity.events import IdentityEvent
from services.identity.exceptions import (
    EmailAlreadyExistsException,
    EmailNotVerifiedException,
    InvalidCredentialsException,
    RegistrationSessionExpiredException,
    RegistrationSessionNotFoundException,
    RegistrationSessionWrongStatusException,
    UserNotFoundException,
)
from services.identity.contracts import ExternalIdentity as ExternalIdentityDTO
from services.identity.models import (
    EmailIdentity,
    ExternalIdentity as ExternalIdentityModel,
    RegistrationSession,
    RegistrationSessionStatus,
    Session,
    User,
    VerificationTokenPurpose,
)
from services.identity.providers import EmailProvider
from services.identity.providers.registry import IdentityProviderRegistry, get_provider_registry
from services.identity.repositories import (
    EmailIdentityRepository,
    ExternalIdentityRepository,
    RefreshTokenRepository,
    RegistrationSessionRepository,
    SessionRepository,
    VerificationTokenRepository,
)
from services.identity.services.membership_service import MembershipService
from services.identity.services.organization_service import OrganizationService
from services.identity.services.password_service import PasswordService
from services.identity.services.session_service import SessionService
from services.identity.services.token_service import TokenService
from services.identity.services.user_service import UserService
from services.identity.services.verification_service import VerificationService
from services.identity.schemas import MeOrganizationResponse, MeResponse
from services.security.crypto import CryptoService


class RegistrationResult:
    def __init__(self) -> None:
        self.registration_session: RegistrationSession | None = None
        self.raw_token: str = ""


class VerificationResult:
    def __init__(self) -> None:
        self.email_identity: EmailIdentity | None = None
        self.events: list[IdentityEvent] = []


class CompletionResult:
    def __init__(self) -> None:
        self.user: User | None = None
        self.organization: Organization | None = None
        self.session: Session | None = None
        self.refresh_token: str = ""
        self.events: list[IdentityEvent] = []


class LoginResult:
    def __init__(self) -> None:
        self.session: Session | None = None
        self.refresh_token: str = ""
        self.events: list[IdentityEvent] = []


class RefreshResult:
    def __init__(self) -> None:
        self.access_token: str = ""
        self.refresh_token: str = ""
        self.session: Session | None = None
        self.event: IdentityEvent | None = None


class AuthService:

    def __init__(
        self,
        email_provider: EmailProvider,
        crypto: CryptoService,
        registration_session_repo: RegistrationSessionRepository,
        verification_token_repo: VerificationTokenRepository,
        email_identity_repo: EmailIdentityRepository,
        refresh_token_repo: RefreshTokenRepository,
        user_svc: UserService,
        org_svc: OrganizationService,
        membership_svc: MembershipService,
        verification_svc: VerificationService,
        password_svc: PasswordService,
        session_svc: SessionService,
        token_svc: TokenService,
        app_url: str = "http://localhost:3000",
        external_identity_repo: ExternalIdentityRepository | None = None,
        provider_registry: IdentityProviderRegistry | None = None,
    ) -> None:
        self._email = email_provider
        self._app_url = app_url.rstrip("/")
        self._crypto = crypto
        self._reg_session_repo = registration_session_repo
        self._verification_token_repo = verification_token_repo
        self._email_identity_repo = email_identity_repo
        self._refresh_token_repo = refresh_token_repo
        self._user = user_svc
        self._org = org_svc
        self._membership = membership_svc
        self._verification = verification_svc
        self._password = password_svc
        self._session_svc = session_svc
        self._token = token_svc
        self._external_identity_repo = external_identity_repo
        self._provider_registry = provider_registry or get_provider_registry()

    async def begin_registration(
        self, email: str,
    ) -> RegistrationResult:
        if "@" not in email or "." not in email.split("@")[-1]:
            from services.identity.exceptions import InvalidCredentialsException
            raise InvalidCredentialsException("Invalid email format")

        existing = await self._email_identity_repo.find_by_email(email)
        if existing is not None:
            raise EmailAlreadyExistsException(email)

        pending = await self._reg_session_repo.find_pending_by_email(email)
        for rs in pending:
            if not rs.is_expired:
                raise EmailAlreadyExistsException(email)

        token, raw = await self._verification.create_verification_token(
            email, VerificationTokenPurpose.VERIFY_EMAIL,
        )

        ttl = IDENTITY_CONFIG.tokens.verification_token_ttl_seconds
        now = datetime.now(timezone.utc)
        reg_session = RegistrationSession(
            email=email,
            verification_token_id=token.id,
            expires_at=now + timedelta(seconds=ttl),
        )
        saved =         await self._reg_session_repo.save(reg_session)

        verification_url = f"{self._app_url}/verify-email?token={raw}"
        await self._email.send_verification_email(email, verification_url)

        result = RegistrationResult()

        result.registration_session = saved
        result.raw_token = raw
        return result

    async def verify_email(self, raw_token: str) -> VerificationResult:
        token_hash = self._crypto.hash_token(raw_token)
        matching = await self._verification_token_repo.find_by_hash(str(token_hash))

        if matching is None:
            raise InvalidCredentialsException("Invalid verification token")
        if matching.is_expired:
            raise InvalidCredentialsException("Verification token has expired")
        if matching.is_used:
            raise InvalidCredentialsException("Verification token already used")

        matching.mark_used()
        await self._verification_token_repo.save(matching)

        reg_sessions = await self._reg_session_repo.find_pending_by_email(matching.target)
        if not reg_sessions:
            raise RegistrationSessionNotFoundException()
        reg_session = reg_sessions[0]

        email_identity = EmailIdentity(
            user_id="",
            email=matching.target,
            is_verified=True,
            is_primary=True,
            verified_at=datetime.now(timezone.utc),
        )
        saved_ei = await self._email_identity_repo.save(email_identity)

        reg_session.mark_verified(saved_ei.id)
        await self._reg_session_repo.save(reg_session)

        events = [
            IdentityEvent.email_verified("", matching.target),
        ]

        result = VerificationResult()
        result.email_identity = saved_ei
        result.events = events
        return result

    async def complete_registration(
        self, registration_session_id: str,
        display_name: str, password: str, organization_name: str,
    ) -> CompletionResult:
        reg_session = await self._reg_session_repo.get(registration_session_id)
        if reg_session is None:
            raise RegistrationSessionNotFoundException()
        if reg_session.status != RegistrationSessionStatus.VERIFIED:
            raise RegistrationSessionWrongStatusException(
                f"Expected VERIFIED, got {reg_session.status.value}",
            )
        if reg_session.is_expired:
            raise RegistrationSessionExpiredException()

        email_identity = await self._email_identity_repo.get(
            reg_session.email_identity_id,
        )
        if email_identity is None:
            raise EmailNotVerifiedException("Verified email identity not found")

        email_str = str(email_identity.email)

        user, _, user_event = await self._user.create_user(
            display_name, email_str,
        )

        email_identity.user_id = user.id
        await self._email_identity_repo.save(email_identity)

        cred, password_event = await self._password.set_password(user.id, password)

        org, membership, org_event = await self._org.create_organization(
            organization_name, user.id,
        )

        session, session_event = await self._session_svc.create_session(
            user_id=user.id,
            organization_id=org.id,
            provider_type="email",
        )

        refresh_token, raw_refresh = await self._token.create_refresh_token(
            session.id,
        )

        reg_session.mark_completed(user.id, org.id)
        await self._reg_session_repo.save(reg_session)

        result = CompletionResult()
        result.user = user
        result.organization = org
        result.session = session
        result.refresh_token = raw_refresh
        result.events = [user_event, password_event, org_event, session_event]
        return result

    async def login(self, email: str, password: str) -> LoginResult:
        email_identity = await self._email_identity_repo.find_by_email(email)
        if email_identity is None:
            raise InvalidCredentialsException("Invalid email or password")
        if not email_identity.is_verified:
            raise EmailNotVerifiedException("Email not verified")

        user_id = email_identity.user_id
        if not user_id:
            raise InvalidCredentialsException("Invalid email or password")

        valid = await self._password.verify_password(user_id, password)
        if not valid:
            raise InvalidCredentialsException("Invalid email or password")

        memberships = await self._membership.list_user_memberships(user_id)
        active_memberships = [m for m in memberships if m.is_active]
        if not active_memberships:
            raise InvalidCredentialsException("No active organization membership")

        org_id = active_memberships[0].organization_id

        session, session_event = await self._session_svc.create_session(
            user_id=user_id,
            organization_id=org_id,
            provider_type="email",
        )

        refresh_token, raw_refresh = await self._token.create_refresh_token(
            session.id,
        )

        login_event = IdentityEvent.login_success(user_id, session.id)

        result = LoginResult()
        result.session = session
        result.refresh_token = raw_refresh
        result.events = [session_event, login_event]
        return result

    async def oauth_login(
        self,
        provider_type: str,
        code: str,
        state: str,
        code_verifier: str,
    ) -> LoginResult:
        provider = self._provider_registry.get(provider_type)
        external_dto = await provider.handle_callback(code, state, code_verifier)

        existing_ei = await self._resolve_external_identity(external_dto)
        is_new_user = False

        if existing_ei is not None:
            user = await self._user.get_user(existing_ei.user_id)
            existing_ei.last_login_at = datetime.now(timezone.utc)
            if self._external_identity_repo is not None:
                await self._external_identity_repo.save(existing_ei)
        else:
            existing_by_email = await self._email_identity_repo.find_by_email(
                external_dto.email,
            )
            if existing_by_email is not None:
                user = await self._user.get_user(existing_by_email.user_id)
                if user is None:
                    raise InvalidCredentialsException("User not found for email identity")
                await self._link_external(user.id, external_dto)
            else:
                user = await self._create_oauth_user(external_dto)
                is_new_user = True

        if is_new_user:
            org, membership, org_event = await self._org.create_organization(
                f"{user.display_name}'s Organization", user.id,
            )
            org_id = org.id
            events = [org_event]
            events.append(IdentityEvent.oauth_linked(user.id, provider_type))
        else:
            memberships = await self._membership.list_user_memberships(user.id)
            active = [m for m in memberships if m.is_active]
            if not active:
                org, membership, org_event = await self._org.create_organization(
                    f"{user.display_name}'s Organization", user.id,
                )
                org_id = org.id
                events = [org_event]
            else:
                org_id = active[0].organization_id
                events = []

        session, session_event = await self._session_svc.create_session(
            user_id=user.id,
            organization_id=org_id,
            provider_type=provider_type,
        )

        refresh_token, raw_refresh = await self._token.create_refresh_token(session.id)

        login_event = IdentityEvent.oauth_login(user.id, provider_type)
        events += [session_event, login_event]

        result = LoginResult()
        result.session = session
        result.refresh_token = raw_refresh
        result.events = events
        return result

    async def _resolve_external_identity(
        self, external_dto: ExternalIdentityDTO,
    ) -> ExternalIdentityModel | None:
        if self._external_identity_repo is None:
            return None
        return await self._external_identity_repo.find_by_provider(
            external_dto.provider.value, external_dto.provider_user_id,
        )

    async def _link_external(
        self, user_id: str, external_dto: ExternalIdentityDTO,
    ) -> ExternalIdentityModel:
        ei = ExternalIdentityModel(
            user_id=user_id,
            provider_type=external_dto.provider.value,
            provider_subject=external_dto.provider_user_id,
            email=external_dto.email,
            display_name=external_dto.name,
            avatar_url=external_dto.avatar_url,
            provider_metadata=external_dto.raw_attributes,
            linked_at=datetime.now(timezone.utc),
            last_login_at=datetime.now(timezone.utc),
        )
        if self._external_identity_repo is not None:
            await self._external_identity_repo.save(ei)
        return ei

    async def _create_oauth_user(self, external_dto: ExternalIdentityDTO) -> User:
        name = external_dto.name or external_dto.email.split("@")[0]
        saved_user, email_identity, _ = await self._user.create_user(
            name, external_dto.email,
        )
        email_identity.is_verified = True
        email_identity.verified_at = datetime.now(timezone.utc)
        await self._email_identity_repo.save(email_identity)

        await self._link_external(saved_user.id, external_dto)
        return saved_user

    async def get_current_user_info(self, user_id: str) -> MeResponse:
        user = await self._user.get_user(user_id)
        if user is None:
            raise UserNotFoundException(user_id)

        email_identity = await self._email_identity_repo.find_primary_by_user_id(user_id)

        memberships = await self._membership.list_user_memberships(user_id)
        org_info = None
        if memberships:
            m = memberships[0]
            org = await self._org.get_organization(m.organization_id)
            if org:
                org_info = MeOrganizationResponse(
                    id=org.id,
                    name=org.name,
                    slug=org.slug,
                    role=m.role,
                )

        return MeResponse(
            id=user.id,
            email=str(email_identity.email) if email_identity else "",
            display_name=user.display_name,
            avatar_url=user.avatar_url or "",
            onboarding_complete=user.is_onboarding_complete,
            organization=org_info,
        )

    async def refresh(self, raw_refresh_token: str) -> RefreshResult:
        new_token, new_raw = await self._token.rotate_refresh_token(raw_refresh_token)
        session = await self._session_svc.get_session(new_token.session_id)
        refresh_event = IdentityEvent.token_refreshed(
            session.user_id, session.id, new_token.family,
        )

        result = RefreshResult()
        result.access_token = new_token.session_id
        result.refresh_token = new_raw
        result.session = session
        result.event = refresh_event
        return result

    async def logout(self, raw_refresh_token: str) -> IdentityEvent:
        token_hash = self._crypto.hash_token(raw_refresh_token)
        rt = await self._refresh_token_repo.find_by_hash(str(token_hash))
        if rt is None:
            raise InvalidCredentialsException("Invalid refresh token")

        session, event = await self._session_svc.revoke_session(rt.session_id)
        return event

    async def list_sessions(self, user_id: str) -> list[Session]:
        return await self._session_svc.list_active_sessions(user_id)

    async def revoke_session(self, session_id: str) -> IdentityEvent:
        _, event = await self._session_svc.revoke_session(session_id)
        return event

    async def get_registration_status(self, reg_session_id: str) -> RegistrationSession | None:
        return await self._reg_session_repo.get(reg_session_id)
