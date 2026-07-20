from __future__ import annotations

from abc import ABC, abstractmethod

from services.agent_sdk.models import (
    AgentResult,
    AgentContext,
    AgentType,
)


class Agent(ABC):

    @property
    @abstractmethod
    def agent_type(self) -> AgentType:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    def description(self) -> str:
        return ""

    @abstractmethod
    async def process(self, context: AgentContext) -> AgentResult:
        ...
