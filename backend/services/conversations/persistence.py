"""Isolated persistence backend for the conversation store.

The conversation store only depends on two functions — ``save(snapshot)``
and ``load()``.  The file backend here is the default implementation;
replacing it with Supabase later only requires re-implementing this
module's interface (the store and the conversation APIs stay untouched).

The snapshot is an explicit JSON document (never pickled): every entity is
serialized through the existing ``to_dict()`` serializers and restored
through ``from_dict()``, so ids, timestamps, statuses, classifications and
all relationships survive the round trip verbatim.

Durability (PR10.8): writes are atomic (tmp file + fsync + ``os.replace``)
with a stale-write guard on the snapshot ``sequence``; malformed state is
preserved to ``<file>.corrupt.<timestamp>`` instead of being silently
replaced. Write failures raise — callers must not treat them as success.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, Tuple

from services.persistence import json_file

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1

CATEGORY = "conversations"


def _default_state_file() -> str:
    # Up three levels from this file: services/conversations -> backend.
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, ".conversations.json")


STATE_FILE = os.getenv("CONVERSATIONS_STATE_FILE", "") or _default_state_file()


def save(snapshot: dict[str, Any]) -> None:
    """Atomically persist the store snapshot (tmp file + fsync + rename).

    Raises on failure; the previous on-disk snapshot is left intact. A
    snapshot older than the one already on disk is skipped (stale guard).
    """
    json_file.atomic_write_json(
        STATE_FILE,
        snapshot,
        sequence_key="sequence",
        category=CATEGORY,
    )


def load() -> Optional[dict[str, Any]]:
    """Load the last persisted snapshot, or None when absent/corrupt.

    A corrupt file is preserved (never destroyed) and the store is left
    empty — the caller may then rehydrate a fresh snapshot on next save.
    """
    data, status = json_file.read_json(STATE_FILE, category=CATEGORY)
    if status is json_file.JsonFileStatus.OK:
        if isinstance(data, dict):
            return data
        logger.warning("persistence_read_invalid_shape category=%s", CATEGORY)
        json_file.preserve_corrupt(STATE_FILE, CATEGORY)
        return None
    if status is json_file.JsonFileStatus.CORRUPT:
        return None
    return None


def load_state() -> Tuple[Optional[dict[str, Any]], json_file.JsonFileStatus]:
    """Return ``(data, status)`` for accurate corruption handling by callers."""
    data, status = json_file.read_json(STATE_FILE, category=CATEGORY)
    if status is json_file.JsonFileStatus.OK and not isinstance(data, dict):
        logger.warning("persistence_read_invalid_shape category=%s", CATEGORY)
        json_file.preserve_corrupt(STATE_FILE, CATEGORY)
        return None, json_file.JsonFileStatus.CORRUPT
    return data, status
