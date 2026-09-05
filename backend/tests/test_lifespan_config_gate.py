"""Characterization tests for the lifespan configuration gate."""

from __future__ import annotations

import asyncio

import pytest

import main


class _StopAfterConfiguration(Exception):
    """Stops the lifespan immediately after the configuration gate."""


async def _enter_lifespan() -> None:
    async with main.lifespan(object()):
        pass


def test_lifespan_logs_configuration_warnings_then_allows_startup(monkeypatch, caplog):
    calls: list[str] = []
    monkeypatch.setattr(main.app_lifespan, "begin_startup", lambda app: 0.0)
    monkeypatch.setattr(
        "services.config_validation.validate_config",
        lambda: ([], ["OPTIONAL_PROVIDER is not configured"]),
    )
    monkeypatch.setattr(
        "services.config_validation.assert_valid_startup_config",
        lambda: calls.append("asserted"),
    )
    monkeypatch.setattr("services.migration.apply_migrations", lambda: None)
    monkeypatch.setattr(
        main,
        "_register_outbound_providers",
        lambda: (_ for _ in ()).throw(_StopAfterConfiguration()),
    )

    with caplog.at_level("INFO", logger="loqi"):
        with pytest.raises(_StopAfterConfiguration):
            asyncio.run(_enter_lifespan())

    assert calls == ["asserted"]
    assert "config: OPTIONAL_PROVIDER is not configured" in caplog.text
    assert "Configuration validated successfully" in caplog.text


def test_lifespan_marks_failed_and_reraises_invalid_configuration(monkeypatch, caplog):
    failures: list[str] = []
    monkeypatch.setattr(main.app_lifespan, "begin_startup", lambda app: 0.0)
    monkeypatch.setattr(
        "services.config_validation.validate_config",
        lambda: ([], ["OPTIONAL_PROVIDER is not configured"]),
    )
    monkeypatch.setattr(
        "services.config_validation.assert_valid_startup_config",
        lambda: (_ for _ in ()).throw(RuntimeError("INVALID_CONFIGURATION")),
    )
    monkeypatch.setattr("services.lifecycle.set_failed", lambda: failures.append("failed"))

    with caplog.at_level("WARNING", logger="loqi"):
        with pytest.raises(RuntimeError, match="INVALID_CONFIGURATION"):
            asyncio.run(_enter_lifespan())

    assert failures == ["failed"]
    assert "config: OPTIONAL_PROVIDER is not configured" in caplog.text
    assert "Configuration validation failed — refusing to start: INVALID_CONFIGURATION" in caplog.text
