"""PR10 — Railway /data volume ownership entrypoint regression tests.

Guards the production persistence fix for:

PermissionError: [Errno 13] Permission denied: '/data/communication.json.tmp-...'

Root cause: the Dockerfile chowns /data at BUILD time, but Railway mounts the
persistent volume at /data at RUNTIME, overriding the image-layer ownership.
The entrypoint runs as root only to fix the mounted volume's ownership, then
permanently drops to appuser before exec'ing the application.

Tests:
- the Dockerfile wires the entrypoint and keeps a non-root appuser
- the entrypoint chowns every path under /data (non-destructive) and drops
  privileges when started as root
- it skips the chown when already non-root
- it fails fast (no exec) if /data cannot be prepared
- file contents are untouched (chown only)
- atomic_write_json can create its temporary file and the communication /
  conversation stores can save once the target directory is writable

Deterministic sentinels only; no real credentials.
"""
import importlib.util
import os
import sys
import types
import uuid

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
ENTRYPOINT_PATH = os.path.join(BACKEND_DIR, "entrypoint.py")


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location("loqi_entrypoint", ENTRYPOINT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _clean_communication_persistence():
    from services.communication import communication_store as cs
    yield
    cs.PERSISTENCE_ENABLED = False


class TestDockerfileWiring:
    def test_dockerfile_uses_entrypoint_and_keeps_appuser(self):
        with open(os.path.join(BACKEND_DIR, "Dockerfile")) as f:
            content = f.read()
        assert "ENTRYPOINT [\"python\", \"/app/entrypoint.py\"]" in content
        assert "COPY main.py workflows.py workflow_dispatcher.py entrypoint.py ./" in content
        assert "useradd --create-home --uid 10001 appuser" in content
        # No world-writable /data.
        assert "chmod 777" not in content
        assert "chmod -R 777" not in content

    def test_dockerignore_does_not_exclude_entrypoint(self):
        with open(os.path.join(BACKEND_DIR, ".dockerignore")) as f:
            content = f.read()
        assert "entrypoint.py" not in content


class TestEntrypointBehavior:
    def test_root_path_chowns_tree_and_drops_privileges(self, monkeypatch):
        ep = _load_entrypoint()
        tree = [
            ("/data", ["sub"], ["conversations.json", "communication.json"]),
            ("/data/sub", [], ["nested.json"]),
        ]
        calls = []

        def _walk(path):
            return iter(tree)

        def _chown(path, uid, gid):
            calls.append(("chown", path, uid, gid))

        def _exec(cmd, args):
            calls.append(("exec", cmd, args))

        monkeypatch.setattr(ep.os, "geteuid", lambda: 0)
        monkeypatch.setattr(ep.os, "makedirs", lambda path, exist_ok=False: None)
        monkeypatch.setattr(ep.os, "walk", _walk)
        monkeypatch.setattr(ep.os, "chown", _chown)
        monkeypatch.setattr(ep.os, "setgroups", lambda g: calls.append(("setgroups", g)))
        monkeypatch.setattr(ep.os, "setgid", lambda g: calls.append(("setgid", g)))
        monkeypatch.setattr(ep.os, "setuid", lambda u: calls.append(("setuid", u)))
        monkeypatch.setattr(ep.os, "execvp", _exec)
        monkeypatch.setattr(ep.pwd, "getpwnam", lambda n: types.SimpleNamespace(pw_uid=10001))
        monkeypatch.setattr(ep.grp, "getgrnam", lambda n: types.SimpleNamespace(gr_gid=10001))
        monkeypatch.setattr(sys, "argv", ["entrypoint.py", "uvicorn", "main:app"])

        assert ep.main() == 0
        # Every path in /data (files + dirs) is re-owned to appuser.
        owned = {c[1] for c in calls if c[0] == "chown"}
        assert owned == {
            "/data", "/data/conversations.json", "/data/communication.json",
            "/data/sub", "/data/sub/nested.json",
        }
        assert all(uid == 10001 and gid == 10001 for c in calls if c[0] == "chown" for uid, gid in [(c[2], c[3])])
        assert any(c[0] == "setuid" for c in calls)
        assert any(c[0] == "setgid" for c in calls)
        # The application command is exec'd (as appuser after setuid).
        assert ("exec", "uvicorn", ["uvicorn", "main:app"]) in calls

    def test_non_root_path_skips_chown_and_execs(self, monkeypatch):
        ep = _load_entrypoint()
        calls = []
        monkeypatch.setattr(ep.os, "geteuid", lambda: 1000)
        monkeypatch.setattr(ep.os, "execvp", lambda cmd, args: calls.append(("exec", cmd, args)))
        monkeypatch.setattr(sys, "argv", ["entrypoint.py", "uvicorn", "main:app"])
        assert ep.main() == 0
        assert calls == [("exec", "uvicorn", ["uvicorn", "main:app"])]

    def test_chown_failure_fails_fast_without_exec(self, monkeypatch):
        ep = _load_entrypoint()
        calls = []

        def _chown(path, uid, gid):
            raise PermissionError("read-only volume")

        monkeypatch.setattr(ep.os, "geteuid", lambda: 0)
        monkeypatch.setattr(ep.os, "makedirs", lambda path, exist_ok=False: None)
        monkeypatch.setattr(ep.os, "walk", lambda path: iter([("/data", [], [])]))
        monkeypatch.setattr(ep.os, "chown", _chown)
        monkeypatch.setattr(ep.os, "execvp", lambda cmd, args: calls.append(("exec", cmd, args)))
        monkeypatch.setattr(ep.pwd, "getpwnam", lambda n: types.SimpleNamespace(pw_uid=10001))
        monkeypatch.setattr(ep.grp, "getgrnam", lambda n: types.SimpleNamespace(gr_gid=10001))
        monkeypatch.setattr(sys, "argv", ["entrypoint.py", "uvicorn", "main:app"])
        assert ep.main() == 1
        assert calls == []

    def test_contents_are_not_modified(self, monkeypatch):
        """chown changes ownership only; file bytes are never touched."""
        ep = _load_entrypoint()
        import tempfile
        tmp = tempfile.mkdtemp()
        payload = b"PR10_PERSIST_VOLUME_SENTINEL"
        target = os.path.join(tmp, "state.json")
        with open(target, "wb") as f:
            f.write(payload)
        calls = []

        def _walk(path):
            for root, dirs, files in os.walk(path):
                yield root, dirs, files

        def _chown(path, uid, gid):
            calls.append(path)

        monkeypatch.setattr(ep.os, "geteuid", lambda: 0)
        monkeypatch.setattr(ep.os, "makedirs", lambda path, exist_ok=False: None)
        monkeypatch.setattr(ep.os, "walk", _walk)
        monkeypatch.setattr(ep.os, "chown", _chown)
        monkeypatch.setattr(ep.os, "setgroups", lambda g: None)
        monkeypatch.setattr(ep.os, "setgid", lambda g: None)
        monkeypatch.setattr(ep.os, "setuid", lambda u: None)
        monkeypatch.setattr(ep.os, "execvp", lambda cmd, args: None)
        monkeypatch.setattr(ep.pwd, "getpwnam", lambda n: types.SimpleNamespace(pw_uid=10001))
        monkeypatch.setattr(ep.grp, "getgrnam", lambda n: types.SimpleNamespace(gr_gid=10001))
        monkeypatch.setattr(sys, "argv", ["entrypoint.py", "uvicorn", "main:app"])

        ep.DATA_DIR = tmp
        ep.main()
        with open(target, "rb") as f:
            assert f.read() == payload


class TestDataWritePath:
    def test_atomic_write_json_creates_tmp_and_succeeds_in_writable_dir(self, tmp_path):
        from services.persistence import json_file
        path = str(tmp_path / "communication.json")
        assert json_file.atomic_write_json(path, {"sequence": 1, "cursors": {}}, category="test") is True
        assert os.path.isfile(path)
        leftovers = [f for f in os.listdir(str(tmp_path)) if "communication.json.tmp-" in f]
        assert leftovers == []

    def test_communication_store_save_state_writes_when_dir_writable(self, monkeypatch, tmp_path):
        """The exact failing operation: save_state writes /data/communication.json."""
        from services.communication import communication_store as cs
        from services.communication.communication_store import store
        monkeypatch.setattr(cs, "PERSISTENCE_ENABLED", True)
        monkeypatch.setattr(cs, "STATE_FILE", str(tmp_path / "communication.json"))
        store.save_cursor("p1", "history-1")
        store.mark_message_seen("ext-1")
        store.save_state()
        assert os.path.isfile(str(tmp_path / "communication.json"))

    def test_conversation_persistence_save_writes_when_dir_writable(self, tmp_path):
        from services.conversations import persistence
        from services.conversations.persistence import save
        path = str(tmp_path / "conversations.json")
        old = persistence.STATE_FILE
        persistence.STATE_FILE = path
        try:
            save({"version": 1, "sequence": 1, "conversations": [], "threads": [], "messages": [], "timeline": {}})
            assert os.path.isfile(path)
        finally:
            persistence.STATE_FILE = old
