"""Exclusive local suite ownership; crash markers require operator review."""
from contextlib import contextmanager
import json
import os
import stat
from threading import RLock
from uuid import uuid4

from tests.postgres.harness import UnsafeLocalPostgres, validate_target

_ACTIVE = None
_LOCK = RLock()
MARKER = "suite-owner.json"


def reject_parallel_workers(env=None):
    values = os.environ if env is None else env
    if any(key.startswith("PYTEST_XDIST_") for key in values):
        raise UnsafeLocalPostgres("Parallel pytest workers are forbidden for the disposable database")


def require_suite_ownership(target):
    """Independent worker connections share only their process's held lease."""
    with _LOCK:
        if _ACTIVE is None or _ACTIVE[0] != target or _ACTIVE[1] != os.getpid():
            raise UnsafeLocalPostgres("An exclusive disposable-database suite lease is required")
        _, _, path, identity, contents = _ACTIVE
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != identity
                    or info.st_uid != os.getuid() or info.st_mode & 0o077
                    or path.read_bytes() != contents):
                raise UnsafeLocalPostgres("Suite ownership marker changed; operator review is required")
        except OSError as error:
            raise UnsafeLocalPostgres("Suite ownership marker missing or unreadable; operator review is required") from error


@contextmanager
def exclusive_suite(target):
    """Atomic file creation arbitrates suites; never reclaim a stale marker.

    A dead PID is not proof of safe recovery (PID reuse/remaining workers).
    Normal release removes only our exact marker; abnormal exit retains it.
    """
    global _ACTIVE
    reject_parallel_workers()
    validate_target(target)
    with _LOCK:
        if _ACTIVE is not None:
            raise UnsafeLocalPostgres("A disposable suite already owns this process")
        path = target.root / MARKER
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise UnsafeLocalPostgres("Existing suite ownership marker: active, stale or ambiguous; operator review required") from None
        # Failed writes deliberately leave a marker, never broaden cleanup.
        with os.fdopen(descriptor, "wb") as output:
            contents = json.dumps({"run_id": target.run_id, "database": target.database,
                "target_digest": target.digest, "pid": os.getpid(), "nonce": str(uuid4())}).encode()
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
            info = os.fstat(output.fileno())
        _ACTIVE = (target, os.getpid(), path, (info.st_dev, info.st_ino), contents)
    try:
        yield
    finally:
        with _LOCK:
            try:
                require_suite_ownership(target)
                path.unlink()  # Exact, current operation-owned local marker only.
            finally:
                _ACTIVE = None
