"""Planning Engine exception hierarchy.

All planning errors inherit from PlanningError and carry structured context
for debugging, logging, and frontend/execution consumption.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanningError(Exception):
    """Base exception for all Planning Engine errors."""

    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "context": self.context,
        }


class PlanningValidationError(PlanningError):
    """Raised when a plan fails structural, scheduling, or integrity validation."""

    def __init__(self, message: str, context: dict[str, Any] | None = None):
        super().__init__(
            message,
            context or {},
        )


class PlanningStrategyError(PlanningError):
    """Raised when strategy selection or task generation fails."""


class PlanningGraphError(PlanningError):
    """Raised when dependency resolution or DAG construction fails."""


class PlanningSchedulingError(PlanningError):
    """Raised when scheduling/trigger assignment fails."""


class PlanningPipelineError(PlanningError):
    """Raised for unexpected pipeline failures not covered by specific errors."""
