from __future__ import annotations
import os
from typing import AsyncGenerator, Optional

from services.reply_generation.provider_base import LLMProvider, ProviderResponse


class DeepSeekProvider(LLMProvider):
    """DeepSeek provider.

    Environment variables:
        DEEPSEEK_API_KEY  — required
        DEEPSEEK_MODEL    — optional, defaults to "deepseek-chat"
    """

    @property
    def provider_name(self) -> str:
        return "deepseek"

    @property
    def default_model(self) -> str:
        return os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    def _get_api_key(self) -> str:
        return os.getenv("DEEPSEEK_API_KEY", "")

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        return ProviderResponse(text="", model=self.default_model, token_usage={"note": "DeepSeek provider not yet implemented"})

    async def generate_async(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        return ProviderResponse(text="", model=self.default_model, token_usage={"note": "DeepSeek provider not yet implemented"})

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        yield ""

    def validate_connection(self) -> bool:
        return bool(self._get_api_key())
