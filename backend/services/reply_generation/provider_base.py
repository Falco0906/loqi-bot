from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional


@dataclass
class ProviderResponse:
    text: str
    model: str = ""
    token_usage: dict = field(default_factory=dict)


class LLMProvider(ABC):
    """Abstract interface for LLM reply generation providers.

    Methods:
        generate() — synchronous reply generation
        generate_async() — async reply generation
        generate_stream() — streaming reply generation
        validate_connection() — lightweight health check
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        ...

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        """Generate a reply from prompts. Returns structured response."""
        ...

    @abstractmethod
    async def generate_async(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        """Async version of generate()."""
        ...

    @abstractmethod
    def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        """Stream a reply token by token."""
        ...

    @abstractmethod
    def validate_connection(self) -> bool:
        """Lightweight check if provider is configured. Should not call expensive APIs."""
        ...

    def get_usage(self) -> dict:
        """Return current token/request usage stats. Optional."""
        return {}
