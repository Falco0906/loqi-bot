from __future__ import annotations


class OrganizationException(Exception):
    def __init__(self, message: str = "An organization error occurred") -> None:
        self.message = message
        super().__init__(self.message)


class OrganizationNotFound(OrganizationException):
    def __init__(self, org_id: str = "") -> None:
        msg = f"Organization not found: {org_id}" if org_id else "Organization not found"
        super().__init__(msg)
        self.org_id = org_id


class OrganizationSlugTaken(OrganizationException):
    def __init__(self, slug: str = "") -> None:
        msg = f"Organization slug already taken: {slug}" if slug else "Organization slug already taken"
        super().__init__(msg)
        self.slug = slug


class OrganizationNameTaken(OrganizationException):
    def __init__(self, name: str = "") -> None:
        msg = f"Organization name already taken: {name}" if name else "Organization name already taken"
        super().__init__(msg)
        self.name = name


class MembershipNotFound(OrganizationException):
    def __init__(self, message: str = "Membership not found") -> None:
        super().__init__(message)


class MembershipAlreadyExists(OrganizationException):
    def __init__(self, user_id: str = "", org_id: str = "") -> None:
        msg = f"User {user_id} is already a member of organization {org_id}"
        super().__init__(msg)
        self.user_id = user_id
        self.org_id = org_id


class LastOwnerCannotLeave(OrganizationException):
    def __init__(self, message: str = "Cannot leave or remove the last owner of an organization") -> None:
        super().__init__(message)


class LastOwnerCannotBeRemoved(OrganizationException):
    def __init__(self, message: str = "Cannot remove the last owner") -> None:
        super().__init__(message)


class CannotManageOwner(OrganizationException):
    def __init__(self, message: str = "Admins cannot manage the organization owner") -> None:
        super().__init__(message)


class InsufficientRole(OrganizationException):
    def __init__(self, required_role: str = "") -> None:
        msg = f"Insufficient role. Required: {required_role}" if required_role else "Insufficient role"
        super().__init__(msg)
        self.required_role = required_role


class InvitationNotFound(OrganizationException):
    def __init__(self, message: str = "Invitation not found") -> None:
        super().__init__(message)


class InvitationExpired(OrganizationException):
    def __init__(self, message: str = "Invitation has expired") -> None:
        super().__init__(message)


class InvitationAlreadyAccepted(OrganizationException):
    def __init__(self, message: str = "Invitation has already been accepted") -> None:
        super().__init__(message)


class CannotInviteExistingMember(OrganizationException):
    def __init__(self, email: str = "") -> None:
        msg = f"User with email {email} is already a member" if email else "User is already a member"
        super().__init__(msg)
        self.email = email


class OrganizationNotActive(OrganizationException):
    def __init__(self, org_id: str = "") -> None:
        msg = f"Organization is not active: {org_id}" if org_id else "Organization is not active"
        super().__init__(msg)
        self.org_id = org_id
