from __future__ import annotations


class IdentityException(Exception):
    """Base exception for all Identity Platform errors."""

    def __init__(self, message: str = "An identity error occurred") -> None:
        self.message = message
        super().__init__(self.message)


class AuthenticationException(IdentityException):
    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message)


class InvalidCredentialsException(AuthenticationException):
    def __init__(self, message: str = "Invalid credentials") -> None:
        super().__init__(message)


class EmailAlreadyExistsException(IdentityException):
    def __init__(self, email: str = "") -> None:
        msg = f"Email already registered: {email}" if email else "Email already registered"
        super().__init__(msg)
        self.email = email


class EmailNotVerifiedException(IdentityException):
    def __init__(self, message: str = "Email not verified") -> None:
        super().__init__(message)


class InvalidVerificationTokenException(IdentityException):
    def __init__(self, message: str = "Invalid verification token") -> None:
        super().__init__(message)


class VerificationTokenExpiredException(IdentityException):
    def __init__(self, message: str = "Verification token has expired") -> None:
        super().__init__(message)


class UserNotFoundException(IdentityException):
    def __init__(self, user_id: str = "") -> None:
        msg = f"User not found: {user_id}" if user_id else "User not found"
        super().__init__(msg)
        self.user_id = user_id


class OrganizationNotFoundException(IdentityException):
    def __init__(self, organization_id: str = "") -> None:
        msg = f"Organization not found: {organization_id}" if organization_id else "Organization not found"
        super().__init__(msg)
        self.organization_id = organization_id


class MembershipNotFoundException(IdentityException):
    def __init__(self, message: str = "Membership not found") -> None:
        super().__init__(message)


class SessionNotFoundException(IdentityException):
    def __init__(self, session_id: str = "") -> None:
        msg = f"Session not found: {session_id}" if session_id else "Session not found"
        super().__init__(msg)
        self.session_id = session_id


class SessionRevokedException(IdentityException):
    def __init__(self, message: str = "Session has been revoked") -> None:
        super().__init__(message)


class RefreshTokenExpiredException(IdentityException):
    def __init__(self, message: str = "Refresh token has expired") -> None:
        super().__init__(message)


class RefreshTokenRevokedException(IdentityException):
    def __init__(self, message: str = "Refresh token has been revoked") -> None:
        super().__init__(message)


class PasswordPolicyViolationException(IdentityException):
    def __init__(self, message: str = "Password does not meet policy requirements") -> None:
        super().__init__(message)


class InvitationNotFoundException(IdentityException):
    def __init__(self, message: str = "Invitation not found") -> None:
        super().__init__(message)


class InvitationExpiredException(IdentityException):
    def __init__(self, message: str = "Invitation has expired") -> None:
        super().__init__(message)


class PasswordResetRequestNotFoundException(IdentityException):
    def __init__(self, message: str = "Password reset request not found") -> None:
        super().__init__(message)


class PasswordResetTokenExpiredException(IdentityException):
    def __init__(self, message: str = "Password reset token has expired") -> None:
        super().__init__(message)


class EmailIdentityNotFoundException(IdentityException):
    def __init__(self, email: str = "") -> None:
        msg = f"Email identity not found: {email}" if email else "Email identity not found"
        super().__init__(msg)
        self.email = email


class SessionLimitExceededException(IdentityException):
    def __init__(self, max_sessions: int = 0) -> None:
        msg = f"Maximum active sessions exceeded ({max_sessions})" if max_sessions else "Maximum active sessions exceeded"
        super().__init__(msg)
        self.max_sessions = max_sessions


class InvalidProviderStateException(AuthenticationException):
    def __init__(self, message: str = "Invalid OAuth provider state") -> None:
        super().__init__(message)


class RegistrationSessionNotFoundException(IdentityException):
    def __init__(self, message: str = "Registration session not found") -> None:
        super().__init__(message)


class RegistrationSessionExpiredException(IdentityException):
    def __init__(self, message: str = "Registration session has expired") -> None:
        super().__init__(message)


class RegistrationSessionWrongStatusException(IdentityException):
    def __init__(self, message: str = "Registration session is in wrong status") -> None:
        super().__init__(message)
