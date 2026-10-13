"""Regression for the generate-strategy 422: a live request produced a
FastAPI/Pydantic validation error — "Input should be a valid dictionary or
object to extract fields from", input `'{"force":false}'` — meaning the
server received the JSON TEXT as a Python string rather than a parsed
object. A TestClient-based reproduction of the same route did not trigger
this (points at real-socket transport through this app's stacked
BaseHTTPMiddleware chain, not application logic), so the fix moves off
FastAPI's automatic Optional[Model] body-binding and parses the body
manually and defensively instead.
"""
from __future__ import annotations

import json

from services.campaigns.api import _parse_optional_json_body


def test_recovers_from_the_exact_double_encoded_body_seen_live():
    # The literal scenario from the production 422: the wire body was the
    # JSON-encoded STRING '{"force":false}', not the object {force: false}.
    double_encoded = json.dumps('{"force":false}').encode()
    assert _parse_optional_json_body(double_encoded) == {"force": False}


def test_parses_a_normal_well_formed_body():
    assert _parse_optional_json_body(b'{"force": true}') == {"force": True}


def test_empty_body_yields_empty_dict_not_an_error():
    assert _parse_optional_json_body(b"") == {}


def test_garbage_body_yields_empty_dict_not_an_error():
    assert _parse_optional_json_body(b"not json at all") == {}


def test_doubly_encoded_garbage_still_does_not_raise():
    assert _parse_optional_json_body(json.dumps("still not json").encode()) == {}
