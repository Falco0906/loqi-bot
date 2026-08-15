"""Durable atomic JSON file persistence (PR10.8).

Shared low-level backend used by the conversation store and the
communication store. Provides:

- atomic writes (temp file -> fsync -> ``os.replace``) so a crash cannot
  leave a half-written state file
- a stale-write guard: snapshots carry a monotonic ``sequence`` and an
  older snapshot can never overwrite a newer one on disk
- corruption handling: a malformed state file is never silently replaced;
  it is renamed to ``<file>.corrupt.<timestamp>`` (preserved for operator
  recovery) and a structured ``persistence_corrupt_state`` event is logged
- parent-directory creation and stale temp-file cleanup

This module never logs record contents, credentials, or bodies.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

_write_lock = threading.RLock()


class JsonFileStatus(str, Enum):
    ABSENT = "absent"
    OK = "ok"
    CORRUPT = "corrupt"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preserve_corrupt(path: str, category: str, error: BaseException | None = None) -> None:
    """Rename a malformed state file out of the way instead of overwriting it."""
    if not os.path.exists(path):
        return
    backup = f"{path}.corrupt.{int(time.time())}"
    try:
        os.replace(path, backup)
    except Exception as exc:
        logger.error(
            "persistence_corrupt_state_preserve_failed category=%s path=%s error=%s",
            category, path, exc,
        )
        return
    logger.error(
        "persistence_corrupt_state category=%s path=%s preserved=%s",
        category, path, backup,
    )
    if error is not None:
        logger.error("persistence_corrupt_state_detail category=%s error_type=%s", category, type(error).__name__)


def _fsync_directory(directory: str) -> None:
    """Best-effort fsync of the containing directory after a rename."""
    if not directory or directory == ".":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _extract_sequence(data: Any, key: str) -> int | None:
    if isinstance(data, dict):
        try:
            return int(data.get(key) or 0)
        except (TypeError, ValueError):
            return None
    return None


def _current_sequence(path: str, key: str) -> int | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return int(data.get(key) or 0)
    except Exception:
        return None


def _cleanup_stale_tmp(path: str) -> None:
    """Remove leftover temp files from crashed writes (best effort)."""
    directory = os.path.dirname(path) or "."
    prefix = f"{os.path.basename(path)}.tmp-"
    try:
        entries = os.listdir(directory)
    except OSError:
        return
    cutoff = time.time() - 3600  # older than an hour
    for name in entries:
        if not name.startswith(prefix):
            continue
        full = os.path.join(directory, name)
        try:
            if os.path.getmtime(full) < cutoff:
                os.remove(full)
        except OSError:
            pass


def read_json(path: str, *, category: str = "") -> tuple[Any | None, JsonFileStatus]:
    """Read a JSON state file.

    Returns ``(data, status)`` where status is one of ``ABSENT``, ``OK``,
    ``CORRUPT``. A corrupt file is preserved (renamed) and never exposed.
    """
    if not os.path.exists(path):
        return None, JsonFileStatus.ABSENT
    _cleanup_stale_tmp(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data, JsonFileStatus.OK
    except Exception as e:
        _preserve_corrupt(path, category, error=e)
        return None, JsonFileStatus.CORRUPT


def atomic_write_json(
    path: str,
    data: Any,
    *,
    sequence_key: str = "sequence",
    category: str = "",
) -> bool:
    """Atomically write ``data`` to ``path`` (tmp file + fsync + replace).

    When ``data`` carries a monotonic ``sequence`` under ``sequence_key``,
    an older snapshot never overwrites a newer one on disk (stale-write
    guard). Returns True when the file was replaced, False when a newer
    snapshot was already on disk (write skipped).

    Raises on failure — callers must not silently treat a failed write as
    success.
    """
    with _write_lock:
        directory = os.path.dirname(path) or "."
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)

        _cleanup_stale_tmp(path)

        if os.path.exists(path):
            _current_data = _safe_peek(path)
            if _current_data is None:
                # Existing file is unparseable — preserve it rather than
                # silently overwriting operator state.
                _preserve_corrupt(path, category)

        sequence = _extract_sequence(data, sequence_key)
        if sequence is not None:
            current = _current_sequence(path, sequence_key)
            if current is not None and sequence <= current:
                return False

        prefix = f"{os.path.basename(path)}.tmp-"
        fd, tmp_path = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=directory or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            _fsync_directory(directory)
            return True
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise


def _safe_peek(path: str) -> Any | None:
    """Return parsed contents or None when unparseable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def preserve_corrupt(path: str, category: str) -> None:
    """Public wrapper to preserve a malformed file for operator recovery."""
    _preserve_corrupt(path, category)
