#!/usr/bin/env python3
"""Loqi backend container entrypoint (production persistence fix).

Railway mounts a persistent volume at /data at runtime. The mounted volume
does NOT inherit the image-layer ownership set by ``chown`` during
``docker build``, so the non-root ``appuser`` cannot write to it (atomic
JSON writes fail with PermissionError).

This entrypoint:

1. runs as root,
2. makes /data (and any files already in it) owned by ``appuser`` —
   NON-DESTRUCTIVE: only ownership changes, file contents are untouched,
3. permanently drops privileges to ``appuser``,
4. executes the real command (uvicorn).

The application itself always runs as the non-root ``appuser``.
"""

from __future__ import annotations

import grp
import os
import pwd
import sys

APP_USER = "appuser"
DATA_DIR = "/data"


def _chown_owned_tree(path: str, uid: int, gid: int) -> None:
    for root, dirs, files in os.walk(path):
        os.chown(root, uid, gid)
        for name in dirs:
            os.chown(os.path.join(root, name), uid, gid)
        for name in files:
            os.chown(os.path.join(root, name), uid, gid)


def main() -> int:
    if os.geteuid() == 0:
        try:
            uid = pwd.getpwnam(APP_USER).pw_uid
            gid = grp.getgrnam(APP_USER).gr_gid
            os.makedirs(DATA_DIR, exist_ok=True)
            _chown_owned_tree(DATA_DIR, uid, gid)
        except Exception as exc:  # noqa: BLE001
            # Fail loudly rather than silently running degraded.
            print(f"[entrypoint] failed to prepare /data: {exc}", file=sys.stderr)
            return 1
        # Drop privileges permanently before running the application.
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)

    if len(sys.argv) < 2:
        print("usage: entrypoint.py <command> [args...]", file=sys.stderr)
        return 1
    os.execvp(sys.argv[1], sys.argv[1:])
    return 0  # unreachable


if __name__ == "__main__":
    sys.exit(main())
