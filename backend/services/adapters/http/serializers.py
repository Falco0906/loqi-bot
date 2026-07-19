from __future__ import annotations

import json
import urllib.parse
from abc import ABC, abstractmethod
from typing import Any

from services.adapters.http.exceptions import SerializationError


class BodySerializer(ABC):
    """Abstract body serializer."""

    @abstractmethod
    def serialize(self, body: Any) -> bytes:
        """Serialize a body to bytes."""

    @abstractmethod
    def deserialize(self, data: bytes) -> Any:
        """Deserialize bytes to a Python object."""

    @property
    @abstractmethod
    def content_type(self) -> str:
        """The MIME content type this serializer produces."""


class JsonSerializer(BodySerializer):
    """JSON serializer."""

    def serialize(self, body: Any) -> bytes:
        try:
            return json.dumps(body).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SerializationError(
                f"Failed to serialize body as JSON: {exc}"
            ) from exc

    def deserialize(self, data: bytes) -> Any:
        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise SerializationError(
                f"Failed to deserialize JSON: {exc}"
            ) from exc

    @property
    def content_type(self) -> str:
        return "application/json"


class FormSerializer(BodySerializer):
    """Form URL-encoded serializer."""

    def serialize(self, body: Any) -> bytes:
        if isinstance(body, dict):
            try:
                return urllib.parse.urlencode(body, doseq=True).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise SerializationError(
                    f"Failed to serialize body as form data: {exc}"
                ) from exc
        raise SerializationError(
            f"Form serializer expects a dict, got {type(body).__name__}"
        )

    def deserialize(self, data: bytes) -> dict[str, str]:
        try:
            parsed = urllib.parse.parse_qs(data.decode("utf-8"))
            return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
        except (UnicodeDecodeError, ValueError) as exc:
            raise SerializationError(
                f"Failed to deserialize form data: {exc}"
            ) from exc

    @property
    def content_type(self) -> str:
        return "application/x-www-form-urlencoded"


class PlainTextSerializer(BodySerializer):
    """Plain text serializer."""

    def serialize(self, body: Any) -> bytes:
        try:
            if isinstance(body, bytes):
                return body
            return str(body).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SerializationError(
                f"Failed to serialize body as plain text: {exc}"
            ) from exc

    def deserialize(self, data: bytes) -> str:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SerializationError(
                f"Failed to deserialize plain text: {exc}"
            ) from exc

    @property
    def content_type(self) -> str:
        return "text/plain"


_CONTENT_TYPE_REGISTRY: dict[str, type[BodySerializer]] = {
    "application/json": JsonSerializer,
    "application/x-www-form-urlencoded": FormSerializer,
    "text/plain": PlainTextSerializer,
}


def get_serializer(content_type: str) -> BodySerializer | None:
    """Look up a serializer by content type string.

    Returns None if no serializer is registered for the content type.
    Matching is case-insensitive and ignores parameters (e.g.
    ``application/json; charset=utf-8`` matches ``application/json``).
    """
    base = content_type.split(";")[0].strip().lower()
    cls = _CONTENT_TYPE_REGISTRY.get(base)
    return cls() if cls else None


def detect_serializer(body: Any, content_type: str = "") -> BodySerializer:
    """Detect the best serializer for the given body and content type.

    If content_type is provided and registered, use that serializer.
    Otherwise, infer from body type: dict → JSON, str/bytes → PlainText.
    """
    if content_type:
        serializer = get_serializer(content_type)
        if serializer is not None:
            return serializer
    if isinstance(body, dict):
        return JsonSerializer()
    return PlainTextSerializer()
