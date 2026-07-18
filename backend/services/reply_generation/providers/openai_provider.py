from __future__ import annotations
import json
import os
import time
from typing import AsyncGenerator, Optional

import requests
from dotenv import load_dotenv

from services.reply_generation.provider_base import LLMProvider, ProviderResponse

load_dotenv()

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIProvider(LLMProvider):
    RETRIES = 3
    RETRY_DELAY = 1.0

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _get_api_key(self) -> str:
        return os.getenv("OPENAI_API_KEY", "")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        return {
            "model": model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
            ],
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

    def _extract_text(self, data: dict) -> str:
        output = data.get("output", [])
        for item in output:
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        return content.get("text", "")
        return ""

    def _extract_usage(self, data: dict) -> dict:
        usage = data.get("usage", {})
        return {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    def _extract_model(self, data: dict) -> str:
        return data.get("model", self.default_model)

    def _do_request(self, payload: dict) -> dict:
        last_error = None
        for attempt in range(self.RETRIES):
            try:
                response = requests.post(
                    OPENAI_RESPONSES_URL,
                    headers=self._headers(),
                    json=payload,
                    timeout=30,
                )
                if response.status_code == 429:
                    wait = self.RETRY_DELAY * (2 ** attempt)
                    time.sleep(wait)
                    continue
                if response.status_code == 401:
                    return {"error": "unauthorized", "detail": "Invalid API key"}
                response.raise_for_status()
                return response.json()
            except requests.Timeout:
                last_error = "timeout"
                if attempt < self.RETRIES - 1:
                    time.sleep(self.RETRY_DELAY * (2 ** attempt))
            except requests.RequestException as e:
                last_error = str(e)
                if attempt < self.RETRIES - 1:
                    time.sleep(self.RETRY_DELAY * (2 ** attempt))
        return {"error": "max_retries", "detail": last_error}

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

        payload = self._build_payload(
            system_prompt, user_prompt,
            model or self.default_model,
            temperature, max_tokens,
        )

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
        import httpx

        api_key = self._get_api_key()
        if not api_key:
            return ProviderResponse(text="", model=self.default_model)

        payload = self._build_payload(
            system_prompt, user_prompt,
            model or self.default_model,
            temperature, max_tokens,
        )

        last_error = None
        for attempt in range(self.RETRIES):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(
                        OPENAI_RESPONSES_URL,
                        headers=self._headers(),
                        json=payload,
                    )
                    if response.status_code == 429:
                        import asyncio
                        await asyncio.sleep(self.RETRY_DELAY * (2 ** attempt))
                        continue
                    response.raise_for_status()
                    data = response.json()
                    return ProviderResponse(
                        text=self._extract_text(data),
                        model=self._extract_model(data),
                        token_usage=self._extract_usage(data),
                    )
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                last_error = str(e)
                if attempt < self.RETRIES - 1:
                    import asyncio
                    await asyncio.sleep(self.RETRY_DELAY * (2 ** attempt))

        return ProviderResponse(text="", model=self.default_model, token_usage={"error": last_error})

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        import httpx

        api_key = self._get_api_key()
        if not api_key:
            return

        payload = self._build_payload(
            system_prompt, user_prompt,
            model or self.default_model,
            temperature, max_tokens,
        )
        payload["stream"] = True

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream(
                    "POST", OPENAI_RESPONSES_URL,
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
                                for item in data.get("output", []):
                                    if item.get("type") == "message":
                                        for content in item.get("content", []):
                                            if content.get("type") == "output_text":
                                                yield content.get("text", "")
                            except json.JSONDecodeError:
                                yield data_str
        except httpx.RequestError:
            return

    def validate_connection(self) -> bool:
        api_key = self._get_api_key()
        if not api_key:
            return False
        return True
