from __future__ import annotations


class OnboardingException(Exception):
    def __init__(self, message: str = "An onboarding error occurred") -> None:
        self.message = message
        super().__init__(self.message)


class LifecycleException(OnboardingException):
    pass


class InvalidTransitionException(LifecycleException):
    def __init__(self, from_state: str, to_state: str) -> None:
        self.from_state = from_state
        self.to_state = to_state
        msg = f"Invalid lifecycle transition: {from_state} → {to_state}"
        super().__init__(msg)


class LifecycleStateNotFound(LifecycleException):
    def __init__(self, user_id: str = "") -> None:
        msg = f"Lifecycle state not found for user: {user_id}" if user_id else "Lifecycle state not found"
        super().__init__(msg)
        self.user_id = user_id


class OnboardingSessionNotFound(OnboardingException):
    def __init__(self, session_id: str = "") -> None:
        msg = f"Onboarding session not found: {session_id}" if session_id else "Onboarding session not found"
        super().__init__(msg)
        self.session_id = session_id


class OnboardingSessionExpired(OnboardingException):
    def __init__(self, message: str = "Onboarding session has expired") -> None:
        super().__init__(message)


class StepNotFoundException(OnboardingException):
    def __init__(self, step_id: str = "") -> None:
        msg = f"Step not found: {step_id}" if step_id else "Step not found"
        super().__init__(msg)
        self.step_id = step_id


class StepNotAllowedException(OnboardingException):
    def __init__(self, step_id: str = "") -> None:
        msg = f"Step not allowed in current lifecycle state: {step_id}" if step_id else "Step not allowed"
        super().__init__(msg)
        self.step_id = step_id


class StepAlreadyCompletedException(OnboardingException):
    def __init__(self, step_id: str = "") -> None:
        msg = f"Step already completed: {step_id}" if step_id else "Step already completed"
        super().__init__(msg)
        self.step_id = step_id


class ProfileSetupRequired(OnboardingException):
    def __init__(self, message: str = "Profile setup must be completed first") -> None:
        super().__init__(message)


class WorkspaceSetupRequired(OnboardingException):
    def __init__(self, message: str = "Workspace setup must be completed first") -> None:
        super().__init__(message)


class PlanSelectionRequired(OnboardingException):
    def __init__(self, message: str = "Plan selection must be completed first") -> None:
        super().__init__(message)


class OnboardingNotActive(OnboardingException):
    def __init__(self, message: str = "Onboarding is not active for this user") -> None:
        super().__init__(message)
