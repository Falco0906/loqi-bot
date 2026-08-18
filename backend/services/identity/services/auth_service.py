from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from uuid import uuid4

log = logging.getLogger("loqi.identity.auth_service")

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
    PasswordResetRequest,
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
    PasswordResetRepository,
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
        self.is_new_user: bool = False


class RefreshResult:
    def __init__(self) -> None:
        self.access_token: str = ""
        self.refresh_token: str = ""
        self.session: Session | None = None
        self.event: IdentityEvent | None = None


class _CompletionTracker:
    """App-layer transaction for email registration completion.

    PostgREST has no multi-statement transactions, so completion is made
    atomic by tracking every row it creates and, on failure, compensating:
    the created rows are hard-deleted (reverse creation order), the existing
    verified email identity's user link is reverted, and the registration
    session is restored to its pre-completion state. This prevents failed or
    partial completions from leaving orphaned identity_users (or any other
    half-created identity/org/credential/session rows).
    """

    def __init__(self, svc: "AuthService") -> None:
        self._svc = svc
        self._user_ids: list[str] = []
        self._credential_ids: list[str] = []
        self._org_ids: list[str] = []
        self._membership_ids: list[str] = []
        self._session_ids: list[str] = []
        self._refresh_ids: list[str] = []
        self._email_link: tuple[str, str] | None = None
        self._reg_session_snapshot: tuple[str, object, str, str] | None = None

    def record_user(self, user_id: str) -> None:
        self._user_ids.append(user_id)

    def record_credential(self, credential_id: str) -> None:
        self._credential_ids.append(credential_id)

    def record_org(self, org_id: str) -> None:
        self._org_ids.append(org_id)

    def record_membership(self, membership_id: str) -> None:
        self._membership_ids.append(membership_id)

    def record_session(self, session_id: str) -> None:
        self._session_ids.append(session_id)

    def record_refresh(self, refresh_id: str) -> None:
        self._refresh_ids.append(refresh_id)

    def record_email_link(self, email_identity_id: str, prev_user_id: str) -> None:
        self._email_link = (email_identity_id, prev_user_id)

    def snapshot_reg_session(self, reg_session: RegistrationSession) -> None:
        self._reg_session_snapshot = (
            reg_session.id, reg_session.status, reg_session.user_id, reg_session.organization_id,
        )

    async def rollback(self) -> None:
        svc = self._svc
        for rid in reversed(self._refresh_ids):
            try:
                await svc._token._refresh_token_repo.delete(rid)
            except Exception:  # noqa: BLE001 — best-effort compensation
                pass
        for sid in reversed(self._session_ids):
            try:
                await svc._session_svc._session_repo.delete(sid)
            except Exception:  # noqa: BLE001
                pass
        for mid in reversed(self._membership_ids):
            try:
                await svc._org._membership_repo.delete(mid)
            except Exception:  # noqa: BLE001
                pass
        for oid in reversed(self._org_ids):
            try:
                await svc._org._org_repo.delete(oid)
            except Exception:  # noqa: BLE001
                pass
        for cid in reversed(self._credential_ids):
            try:
                await svc._password._credential_repo.delete(cid)
            except Exception:  # noqa: BLE001
                pass
        if self._email_link:
            ei_id, prev_user_id = self._email_link
            try:
                ei = await svc._email_identity_repo.get(ei_id)
                if ei is not None:
                    ei.user_id = prev_user_id
                    await svc._email_identity_repo.save(ei)
            except Exception:  # noqa: BLE001
                pass
        for uid in reversed(self._user_ids):
            try:
                await svc._user._user_repo.delete(uid)
            except Exception:  # noqa: BLE001
                pass
        if self._reg_session_snapshot:
            rs_id, status, user_id, org_id = self._reg_session_snapshot
            try:
                rs = await svc._reg_session_repo.get(rs_id)
                if rs is not None:
                    rs.status = status
                    rs.user_id = user_id
                    rs.organization_id = org_id
                    await svc._reg_session_repo.save(rs)
            except Exception:  # noqa: BLE001
                pass


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
        password_reset_repo: PasswordResetRepository | None = None,
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
        if password_reset_repo is None:
            from services.identity.repositories import InMemoryPasswordResetRepository
            password_reset_repo = InMemoryPasswordResetRepository()
        self._pr_repo = password_reset_repo
        self._provider_registry = provider_registry or get_provider_registry()

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Canonicalize an email before lookup/storage.

        Emails are compared and stored in lowercase so ``User@Example.com``
        and ``user@example.com`` resolve to the same identity (prevents
        duplicate-account creation via case variants).
        """
        return (email or "").strip().lower()

    async def _reclaim_abandoned_registration(self, email: str) -> None:
        """Reclaim an email blocked only by expired abandoned registration
        state (no canonical account). Uses the exact same conservative
        predicate as the periodic cleanup job and the operator CLI.

        Fail-closed: this request-path cleanup only runs when the runtime gate
        is satisfied (explicitly production AND
        ABANDONED_REGISTRATION_CLEANUP_ENABLED=true). In any other context
        (development, tests, missing flag) it is skipped, so a test or a dev
        process connecting to a shared Supabase project can never trigger a
        destructive cleanup."""
        from services.identity.registration_cleanup import (
            cleanup_abandoned_email,
            resolve_automatic_cleanup_client,
        )

        client = resolve_automatic_cleanup_client()
        if client is None:
            log.debug("abandoned-registration lazy reclaim skipped: runtime gate not satisfied")
            return

        _plan, summary = await asyncio.to_thread(
            cleanup_abandoned_email, email, dry_run=False, require_expired=True, client=client,
        )
        cleaned = summary.get("total_rows", 0)
        if cleaned:
            log.info("abandoned-registration lazy reclaim cleaned_rows=%d", cleaned)

    async def begin_registration(
        self, email: str,
    ) -> RegistrationResult:
        email = self._normalize_email(email)
        if "@" not in email or "." not in email.split("@")[-1]:
            from services.identity.exceptions import InvalidCredentialsException
            raise InvalidCredentialsException("Invalid email format")

        # Lazy abandoned-registration reclaim: if this exact email is blocked
        # only by EXPIRED abandoned registration state (no canonical account),
        # reclaim it so a legitimate user can retry signup without operator
        # intervention. Uses the same conservative predicate as the periodic
        # cleanup job. Refusals are silent and fall through to the normal
        # duplicate checks below (a real account or an active registration is
        # never touched).
        try:
            await self._reclaim_abandoned_registration(email)
        except Exception as exc:  # noqa: BLE001
            log.warning("abandoned-registration lazy reclaim skipped: %s", exc)

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

        # Reuse an existing verified-but-unlinked email identity for the same
        # address (e.g. a second signup session created before the first was
        # completed) instead of inserting a duplicate — the email_identities
        # unique index (migration 022) would otherwise reject the second row.
        existing_ei = await self._email_identity_repo.find_by_email(matching.target)
        if existing_ei is not None and not existing_ei.user_id:
            saved_ei = existing_ei
        else:
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
        if reg_session.status == RegistrationSessionStatus.COMPLETED:
            # Idempotent retry of an already-completed registration: recover
            # the canonical user and issue a fresh auth session rather than
            # creating a second user/identity.
            return await self._recover_completed(reg_session)
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

        tracker = _CompletionTracker(self)
        events: list[IdentityEvent] = []
        try:
            # 1. Canonical user. Reuse a user already created for this session
            # (e.g. an interrupted attempt) so we never create multiple
            # identity_users per registration session.
            if reg_session.user_id:
                user = await self._user.get_user(reg_session.user_id)
            else:
                tracker.record_email_link(email_identity.id, prev_user_id=email_identity.user_id)
                user, linked_ei, user_event = await self._user.create_user(
                    display_name, str(email_identity.email),
                    email_identity_id=email_identity.id,
                )
                tracker.record_user(user.id)
                email_identity = linked_ei
                events.append(user_event)

            # 2. Ensure the verified email identity is linked to this user
            # (UPDATE, never INSERT — no duplicate email identity).
            if email_identity.user_id != user.id:
                tracker.record_email_link(email_identity.id, prev_user_id=email_identity.user_id)
                email_identity.user_id = user.id
                email_identity.is_verified = True
                email_identity.is_primary = True
                email_identity.verified_at = email_identity.verified_at or datetime.now(timezone.utc)
                await self._email_identity_repo.save(email_identity)

            # 3. Password credential (skip if already set by a partial attempt).
            if await self._password.has_password(user.id):
                events.append(IdentityEvent.password_set(user.id))
            else:
                cred, password_event = await self._password.set_password(user.id, password)
                tracker.record_credential(cred.id)
                events.append(password_event)

            # 4. Organization (reuse one already created for this session).
            if reg_session.organization_id:
                org = await self._org.get_organization(reg_session.organization_id)
            else:
                org, membership, org_event = await self._org.create_organization(
                    organization_name, user.id,
                )
                tracker.record_org(org.id)
                tracker.record_membership(membership.id)
                events.append(org_event)

            # 5. Auth session + refresh token.
            session, session_event = await self._session_svc.create_session(
                user_id=user.id,
                organization_id=org.id,
                provider_type="email",
            )
            tracker.record_session(session.id)
            events.append(session_event)
            refresh_token, raw_refresh = await self._token.create_refresh_token(
                session.id,
            )
            tracker.record_refresh(refresh_token.id)

            # 6. Finalize: mark the registration session completed.
            tracker.snapshot_reg_session(reg_session)
            reg_session.mark_completed(user.id, org.id)
            await self._reg_session_repo.save(reg_session)
        except Exception:
            await tracker.rollback()
            raise

        result = CompletionResult()
        result.user = user
        result.organization = org
        result.session = session
        result.refresh_token = raw_refresh
        result.events = events
        return result

    async def _recover_completed(self, reg_session: RegistrationSession) -> CompletionResult:
        """Issue a fresh session for an already-completed registration.

        Called when completion is retried after the canonical user was already
        created and the session marked COMPLETED. No second user or email
        identity is created; the existing user simply receives a new auth
        session (equivalent to a login) so the client can continue.
        """
        user = await self._user.get_user(reg_session.user_id)
        org = await self._org.get_organization(reg_session.organization_id)

        session, session_event = await self._session_svc.create_session(
            user_id=user.id,
            organization_id=org.id,
            provider_type="email",
        )
        refresh_token, raw_refresh = await self._token.create_refresh_token(session.id)

        result = CompletionResult()
        result.user = user
        result.organization = org
        result.session = session
        result.refresh_token = raw_refresh
        result.events = [session_event]
        return result

    async def login(self, email: str, password: str) -> LoginResult:
        email = self._normalize_email(email)
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
        external_dto.email = self._normalize_email(external_dto.email)

        legacy_user = await self._resolve_legacy_oauth_user(external_dto)
        if legacy_user is not None:
            user, is_new_user = legacy_user
            existing_ei = None
        else:
            existing_ei = await self._resolve_external_identity(external_dto)
            is_new_user = False

        if legacy_user is not None:
            pass
        elif existing_ei is not None:
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

        await self._sync_external_identity(user.id, external_dto)

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
        result.is_new_user = is_new_user
        return result

    async def _resolve_legacy_oauth_user(
        self, external_dto: ExternalIdentityDTO,
    ) -> tuple[User, bool] | None:
        """Recover OAuth identities from the pre-identity-platform users table."""
        try:
            from services.supabase import get_or_create_oauth_user

            row, is_new = await asyncio.to_thread(
                get_or_create_oauth_user,
                external_dto.provider.value,
                external_dto.provider_user_id,
                email=external_dto.email,
                username=external_dto.name,
            )
            if not row or not row.get("id"):
                return None

            user_id = str(row["id"])
            try:
                user = await self._user.get_user(user_id)
            except UserNotFoundException:
                user = User(
                    id=user_id,
                    display_name=str(row.get("username") or external_dto.name or ""),
                    avatar_url=external_dto.avatar_url,
                )
                await self._user.save_user(user)

            # The OAuth bridge uses the stable legacy users row, while the
            # identity user aggregate (including onboarding state) lives in
            # the durable identity repository. Pre-existing users are
            # backfilled on first login by the save above.

            existing_email = await self._email_identity_repo.find_by_email(
                external_dto.email,
            )
            if existing_email is None:
                await self._email_identity_repo.save(EmailIdentity(
                    user_id=user.id,
                    email=external_dto.email,
                    is_verified=True,
                    is_primary=True,
                    verified_at=datetime.now(timezone.utc),
                ))
            return user, is_new
        except Exception:
            # The legacy bridge is best-effort. The identity-platform path
            # remains the source of truth once its migration is installed.
            return None

    async def _sync_external_identity(
        self, user_id: str, external_dto: ExternalIdentityDTO,
    ) -> None:
        """Best-effort upsert into the canonical external_identities table."""
        try:
            from services.persistence.launch import ExternalIdentity, ExternalIdentityRepository
            repo = ExternalIdentityRepository()
            subject = external_dto.provider_user_id or external_dto.email
            existing = await repo.find_by_provider_subject(external_dto.provider.value, subject)
            if existing is None:
                await repo.save(ExternalIdentity(
                    user_id=user_id,
                    provider=external_dto.provider.value,
                    provider_subject=subject,
                    email=external_dto.email,
                    username=external_dto.name,
                    metadata={
                        "avatar_url": external_dto.avatar_url or "",
                        "provider_user_id": external_dto.provider_user_id or "",
                    },
                ))
        except Exception:
            pass

    async def _resolve_external_identity(
        self, external_dto: ExternalIdentityDTO,
    ) -> ExternalIdentityModel | None:
        if self._external_identity_repo is not None:
            ei = await self._external_identity_repo.find_by_provider(
                external_dto.provider.value, external_dto.provider_user_id,
            )
            if ei is not None:
                return ei
        # Durable fallback: the identity-provider repo is in-memory in the
        # current wiring. Consult the durable external_identities store (005)
        # so a Google identity survives restarts / multi-instance and is
        # reused rather than duplicated.
        try:
            from services.persistence.launch import ExternalIdentityRepository
            row = await ExternalIdentityRepository().find_by_provider_subject(
                external_dto.provider.value, external_dto.provider_user_id,
            )
        except Exception:
            return None
        if row is None:
            return None
        return ExternalIdentityModel(
            user_id=row.user_id,
            provider_type=row.provider,
            provider_subject=row.provider_subject,
            email=row.email,
            display_name=row.username,
            avatar_url="",
            provider_metadata=row.metadata or {},
            linked_at=datetime.now(timezone.utc),
            last_login_at=datetime.now(timezone.utc),
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

    async def get_session(self, session_id: str) -> Session:
        """Fetch a session by id (raises SessionNotFoundException if absent)."""
        return await self._session_svc.get_session(session_id)

    async def change_password(
        self, user_id: str, current_password: str, new_password: str,
        keep_session_id: str = "",
    ) -> IdentityEvent:
        """Change the user's password and invalidate all other sessions/tokens.

        ``keep_session_id`` (when provided) survives the change; every other
        session and refresh-token family for the user is revoked so a leaked
        credential cannot outlive the change.
        """
        _, event = await self._password.change_password(
            user_id, current_password, new_password,
        )
        await self._revoke_other_sessions(user_id, keep_session_id=keep_session_id)
        return event

    async def request_password_reset(self, email: str) -> None:
        """Issue a single-use password-reset token and email it to the user.

        Uniform response whether or not the account exists (no enumeration).
        """
        email = self._normalize_email(email)
        email_identity = await self._email_identity_repo.find_by_email(email)
        if email_identity is None or not email_identity.user_id:
            return

        user_id = email_identity.user_id
        raw_token = self._crypto.random_token(
            IDENTITY_CONFIG.tokens.password_reset_token_bytes,
        )
        token_hash = self._crypto.hash_token(raw_token)

        await self._pr_repo.invalidate_all_for_user(user_id)

        pr = PasswordResetRequest(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(
                seconds=IDENTITY_CONFIG.tokens.password_reset_ttl_seconds,
            ),
        )
        await self._pr_repo.save(pr)

        reset_url = (
            f"{self._app_url}/reset-password?token={raw_token}&email={email}"
        )
        await self._email.send_password_reset_email(email, reset_url)

    async def confirm_password_reset(
        self, email: str, raw_token: str, new_password: str,
    ) -> IdentityEvent:
        """Validate the single-use reset token, set the new password, and
        invalidate every session/token for the user."""
        email = self._normalize_email(email)
        email_identity = await self._email_identity_repo.find_by_email(email)
        if email_identity is None or not email_identity.user_id:
            raise InvalidCredentialsException("Invalid or expired reset token")

        user_id = email_identity.user_id
        token_hash = self._crypto.hash_token(raw_token)
        pr = await self._pr_repo.find_valid_by_user_id(user_id)
        if pr is None or str(pr.token_hash) != str(token_hash):
            raise InvalidCredentialsException("Invalid or expired reset token")
        if pr.is_expired:
            raise InvalidCredentialsException("Invalid or expired reset token")

        pr.mark_used()
        await self._pr_repo.save(pr)
        await self._pr_repo.invalidate_all_for_user(user_id)

        _, event = await self._password.reset_password(user_id, new_password)

        await self._session_svc.revoke_all_user_sessions(user_id)
        return event

    async def _revoke_other_sessions(
        self, user_id: str, keep_session_id: str,
    ) -> None:
        """Revoke all of a user's sessions except ``keep_session_id`` (when
        given) along with their refresh tokens."""
        sessions = await self._session_svc.list_active_sessions(user_id)
        for session in sessions:
            if keep_session_id and session.id == keep_session_id:
                continue
            await self._session_svc.revoke_session(session.id)

    async def logout(self, raw_refresh_token: str) -> IdentityEvent:
        token_hash = self._crypto.hash_token(raw_refresh_token)
        rt = await self._refresh_token_repo.find_by_hash(str(token_hash))
        if rt is None:
            raise InvalidCredentialsException("Invalid refresh token")

        session, event = await self._session_svc.revoke_session(rt.session_id)
        return event

    async def validate_access_token(self, access_token: str) -> Session:
        """Validate the opaque access token and return its owning session."""
        return await self._session_svc.validate_session(access_token)

    async def list_sessions(self, user_id: str) -> list[Session]:
        return await self._session_svc.list_active_sessions(user_id)

    async def revoke_session(self, session_id: str) -> IdentityEvent:
        _, event = await self._session_svc.revoke_session(session_id)
        return event

    async def get_registration_status(self, reg_session_id: str) -> RegistrationSession | None:
        return await self._reg_session_repo.get(reg_session_id)
