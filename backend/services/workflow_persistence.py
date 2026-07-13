"""Workflow Persistence — save/load runtime state to survive restarts.

Persists after every state transition, not only at completion.
File-based JSON storage for Phase 3.4.2B.
"""

import json
import os
from datetime import datetime, timezone
from threading import Lock

from services.workflow_runtime import RuntimeEntry, restore_runtime


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "workflows")
_persist_lock = Lock()


def _ensure_dir() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


def _file_path(workflow_id: str) -> str:
    return os.path.join(_ensure_dir(), f"{workflow_id}.json")


def persist(entry: RuntimeEntry) -> bool:
    try:
        path = _file_path(entry.workflow_id)
        data = entry.to_dict()
        data["_persisted_at"] = datetime.now(timezone.utc).isoformat()
        with _persist_lock:
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        return True
    except Exception as e:
        print(f"[workflow_persistence] persist error: {e}")
        return False


def load(workflow_id: str) -> RuntimeEntry | None:
    try:
        path = _file_path(workflow_id)
        if not os.path.exists(path):
            return None
        with _persist_lock:
            with open(path) as f:
                data = json.load(f)
        return RuntimeEntry.from_dict(data)
    except Exception as e:
        print(f"[workflow_persistence] load error: {e}")
        return None


def remove(workflow_id: str) -> bool:
    try:
        path = _file_path(workflow_id)
        if os.path.exists(path):
            os.remove(path)
            return True
    except Exception as e:
        print(f"[workflow_persistence] remove error: {e}")
    return False


def list_persisted() -> list[str]:
    try:
        ensure_dir = _ensure_dir()
        return [f.replace(".json", "") for f in os.listdir(ensure_dir) if f.endswith(".json")]
    except Exception as e:
        print(f"[workflow_persistence] list error: {e}")
        return []


def load_all() -> list[RuntimeEntry]:
    entries = []
    for wid in list_persisted():
        entry = load(wid)
        if entry:
            entries.append(entry)
    return entries


def persist_and_restore(entry: RuntimeEntry) -> None:
    persist(entry)
    restore_runtime(entry)


def persist_all_active() -> int:
    from services.workflow_runtime import get_all_workflows
    count = 0
    for entry in get_all_workflows():
        if persist(entry):
            count += 1
    return count


def clear_all_persisted() -> None:
    for wid in list_persisted():
        remove(wid)
