from __future__ import annotations
import asyncio
import json
import os
from typing import AsyncGenerator, Optional

import httpx
from dotenv import load_dotenv

from services.reply_generation.provider_base import LLMProvider, ProviderResponse

load_dotenv()

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


class AnthropicProvider(LLMProvider):
    RETRIES = 3
    RETRY_DELAY = 1.0

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    def _get_api_key(self) -> str:
        return os.getenv("ANTHROPIC_API_KEY", "")

    def _headers(self) -> dict:
        return {
            "x-api-key": self._get_api_key(),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _extract_text(self, data: dict) -> str:
        content = data.get("content", [])
        for block in content:
            if block.get("type") == "text":
                return block.get("text", "")
        return ""

    def _extract_usage(self, data: dict) -> dict:
        usage = data.get("usage", {})
        return {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }

    def _extract_model(self, data: dict) -> str:
        return data.get("model", self.default_model)

    async def _request_data(self, payload: dict) -> dict:
        last_error = None
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(self.RETRIES):
                try:
                    response = await client.post(
                        ANTHROPIC_API_URL,
                        headers=self._headers(),
                        json=payload,
                    )
                    if response.status_code == 429:
                        await asyncio.sleep(self.RETRY_DELAY * (2 ** attempt))
                        continue
                    if response.status_code == 401:
                        return {"error": "unauthorized", "detail": "Invalid API key"}
                    if response.status_code == 400:
                        err_body = response.json()
                        err_msg = err_body.get("error", {}).get("message", "Bad request")
                        return {"error": "bad_request", "detail": err_msg}
                    response.raise_for_status()
                    return response.json()
                except httpx.TimeoutException:
                    last_error = "timeout"
                    if attempt < self.RETRIES - 1:
                        await asyncio.sleep(self.RETRY_DELAY * (2 ** attempt))
                except httpx.RequestError as e:
                    last_error = str(e)
                    if attempt < self.RETRIES - 1:
                        await asyncio.sleep(self.RETRY_DELAY * (2 ** attempt))
        return {"error": "max_retries", "detail": last_error}

    def _do_request(self, payload: dict) -> dict:
        """Synchronous compatibility entry point for GenerationPipeline."""
        return asyncio.run(self._request_data(payload))

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        api_key = self._get_api_key()
        if not api_key:
            return ProviderResponse(text="", model=self.default_model)

        payload = {
            "model": model or self.default_model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        data = self._do_request(payload)
        if data.get("error"):
            return ProviderResponse(text="", model=self.default_model, token_usage={"error": data["error"]})

        return ProviderResponse(
            text=self._extract_text(data),
            model=self._extract_model(data),
            token_usage=self._extract_usage(data),
        )

    async def generate_async(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        api_key = self._get_api_key()
        if not api_key:
            return ProviderResponse(text="", model=self.default_model)

        payload = {
            "model": model or self.default_model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        data = await self._request_data(payload)
        if data.get("error"):
            return ProviderResponse(text="", model=self.default_model, token_usage={"error": data["error"]})
        return ProviderResponse(
            text=self._extract_text(data),
            model=self._extract_model(data),
            token_usage=self._extract_usage(data),
        )

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        api_key = self._get_api_key()
        if not api_key:
            return

        payload = {
            "model": model or self.default_model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream(
                    "POST", ANTHROPIC_API_URL,
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                return
                            try:
                                data = json.loads(data_str)
                                if data.get("type") == "content_block_delta":
                                    delta = data.get("delta", {})
                                    if delta.get("type") == "text_delta":
                                        yield delta.get("text", "")
                            except json.JSONDecodeError:
                                pass
        except httpx.RequestError:
            return

    def validate_connection(self) -> bool:
        api_key = self._get_api_key()
        if not api_key:
            return False
        return True
