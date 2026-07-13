"""Workflow Locks — per-resource locking to prevent double execution.

Example: Two workflows cannot both launch the same campaign.
"""

from threading import Lock
from services.workflow_runtime import acquire_lock as _acquire, release_lock as _release, has_active_lock as _has_active


_resource_locks: dict[str, str] = {}  # resource -> workflow_id
_lock = Lock()


def try_lock(workflow_id: str, resource: str) -> bool:
    with _lock:
        if resource in _resource_locks:
            owner = _resource_locks[resource]
            if owner != workflow_id:
                return False
            return True
        _resource_locks[resource] = workflow_id
    _acquire(workflow_id, resource)
    return True


def unlock(workflow_id: str, resource: str) -> bool:
    with _lock:
        if _resource_locks.get(resource) == workflow_id:
            del _resource_locks[resource]
    _release(workflow_id, resource)
    return True


def unlock_all(workflow_id: str) -> None:
    with _lock:
        to_remove = [r for r, owner in _resource_locks.items() if owner == workflow_id]
        for r in to_remove:
            del _resource_locks[r]
            _release(workflow_id, r)


def is_locked(resource: str) -> bool:
    with _lock:
        return resource in _resource_locks


def get_lock_owner(resource: str) -> str | None:
    with _lock:
        return _resource_locks.get(resource)


def clear() -> None:
    with _lock:
        _resource_locks.clear()
