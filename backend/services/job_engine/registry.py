from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class WorkflowRegistration:
    type: str
    description: str
    stages: list[str] = field(default_factory=list)
    runner_fn: Optional[Callable] = None


STAGES_SEARCH = [
    "Analyzing your target audience...",
    "Extracting buyer profile...",
    "Finding similar companies...",
    "Ranking opportunities...",
    "Preparing results...",
]


class JobRegistry:
    def __init__(self):
        self._workflows: dict[str, WorkflowRegistration] = {}

    def register(self, reg: WorkflowRegistration) -> None:
        self._workflows[reg.type] = reg

    def get(self, type_: str) -> Optional[WorkflowRegistration]:
        return self._workflows.get(type_)

    def has(self, type_: str) -> bool:
        return type_ in self._workflows

    def list_types(self) -> list[str]:
        return list(self._workflows.keys())


_registry = JobRegistry()


def get_registry() -> JobRegistry:
    return _registry
