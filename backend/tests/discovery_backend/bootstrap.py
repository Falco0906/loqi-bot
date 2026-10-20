"""Opt-in loopback HTTP composition for synthetic Discovery integration only.

No main.py/startup, database, OAuth, providers or recovery workers are mounted.
Run only using the documented clean-environment command after operator review.
"""
import os
from contextlib import asynccontextmanager, ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

HOST, PORT = "127.0.0.1", 19876
MARKER = "loqi-isolated-discovery-v1"


def prepare_runtime():
    if os.getenv("LOQI_ISOLATED_DISCOVERY_ENABLED") != "1":
        raise RuntimeError("Isolated backend requires explicit opt-in")
    # Reject inherited service configuration by NAME, without reading its value.
    forbidden = [key for key in os.environ if key.startswith(("SUPABASE_", "PG", "OPENAI_", "GOOGLE_", "GMAIL_"))
                 or key in {"DATABASE_URL", "REDIS_URL", "TELEGRAM_BOT_TOKEN"}]
    if forbidden:
        raise RuntimeError("Use the documented clean environment; inherited service configuration is forbidden")
    from tests.discovery_backend.datasets import validate_profile
    profile = validate_profile(os.environ.get("LOQI_ISOLATED_DISCOVERY_PROFILE", "small"))
    import dotenv
    dotenv.load_dotenv = lambda *_a, **_k: False  # Never load application .env.
    from services.platform.test_runtime import activate_test_runtime
    activate_test_runtime()
    import sys
    def audit(event, _args):
        # Block new connections and sendto, not sendmsg: asyncio uses sendmsg
        # for buffered responses on accepted TCP sockets. This hook does not
        # distinguish or block explicit-destination sends made via sendmsg.
        if event in {"socket.connect", "socket.sendto", "subprocess.Popen", "os.system", "os.posix_spawn"}:
            raise RuntimeError("Outbound connections and child processes are forbidden in the isolated backend")
        if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"} and _args[0] not in {HOST, "localhost", "::1", None}:
            raise RuntimeError("Unapproved DNS lookup in the isolated backend")
    sys.addaudithook(audit)  # Process-owned; covers imports before lifespan starts.
    return profile


def create_app(*, profile="small"):
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from services.platform.test_runtime import is_test_runtime
    if not is_test_runtime():
        raise RuntimeError("Process-owned test runtime must precede application imports")
    from tests.discovery_backend.store import SyntheticStore, USER, ORG, SESSION
    from services.platform import supabase
    from services.persistence.database import SupabaseConnectionManager, set_connection_manager
    from services.discovery import api as discovery_api, service
    from services.leads import api as leads_api
    from services.workspace import api as workspace_api
    from services.identity import api as identity_api
    from services.identity.models import Session
    from services.identity.repositories.session_repository import InMemorySessionRepository
    from services.identity.services.session_service import SessionService
    from services.job_engine.manager import JobManager
    from services.knowledge.context_adapter import KnowledgePromptContext
    from services.capabilities.api import list_beta_features
    import socket

    # Offline tests inject a profile explicitly. Only prepare_runtime reads the
    # startup environment, after its opt-in and inherited-configuration checks.
    store = SyntheticStore(profile=profile)
    manager = JobManager()
    blocked = []
    def deny(*_a, **_k):
        blocked.append("outbound connection")
        raise RuntimeError("Outbound connections are forbidden in the isolated backend")
    original_resolver = socket.getaddrinfo
    def local_resolution(host, *args, **kwargs):
        if host not in {HOST, "localhost", "::1", None}:
            return deny()
        return original_resolver(host, *args, **kwargs)
    async def knowledge(owner, **kwargs):
        if owner != USER or not kwargs.get("workspace_id"):
            raise RuntimeError("Unscoped synthetic Knowledge read")
        return KnowledgePromptContext()
    async def updates(*_a, **_k): return []
    async def get_user(identity):
        if identity != USER:
            raise RuntimeError("Unknown synthetic user")
        return SimpleNamespace(display_name="Synthetic Operator")

    @asynccontextmanager
    async def lifespan(_app):
        import asyncio
        sessions = InMemorySessionRepository()
        await sessions.save(Session(id=SESSION, user_id=USER, organization_id=ORG,
                                    expires_at=datetime.now(timezone.utc) + timedelta(hours=24)))
        session_service = SessionService(sessions, None)
        auth = SimpleNamespace(validate_access_token=session_service.validate_session,
                               _session_svc=session_service, _user=SimpleNamespace(get_user=get_user))
        with ExitStack() as scope:
            scope.enter_context(patch.object(socket.socket, "connect", deny))
            scope.enter_context(patch.object(socket.socket, "connect_ex", deny))
            scope.enter_context(patch.object(socket, "create_connection", deny))
            scope.enter_context(patch.object(socket, "getaddrinfo", local_resolution))
            scope.enter_context(patch.object(identity_api, "_auth_service", auth))
            scope.enter_context(patch.object(service, "job_manager", manager))
            scope.enter_context(patch("services.discovery.context.retrieve_knowledge_context", knowledge))
            scope.enter_context(patch("services.strategic.service.StrategicIntelligenceService", lambda: SimpleNamespace(list_updates=updates)))
            # World Model publication is an unrelated projection, not search persistence.
            scope.enter_context(patch("services.world_model.publish", lambda *_a, **_k: None))
            supabase.install_test_double(store)
            set_connection_manager(SupabaseConnectionManager(client=store))
            try:
                yield
            finally:
                tasks = list(manager._runner._tasks.values())
                for task in tasks: task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                supabase.install_validated_test_client(None)
                set_connection_manager(None)

    app = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None, redoc_url=None)
    app.state.synthetic = store
    app.state.blocked = blocked
    approved = {("GET", "/health"), ("GET", "/__loqi_test/identity"), ("POST", "/__loqi_test/fault"),
                ("POST", "/api/v1/auth/refresh"),
                ("GET", "/api/v1/auth/me"), ("GET", "/api/v1/beta/features"),
                ("GET", "/api/web/session/_/workspaces"), ("GET", "/api/web/session/_/leads"),
                ("POST", "/api/web/session/_/workspaces/select"),
                ("GET", "/api/discoveries"), ("POST", "/api/discoveries")}
    @app.middleware("http")
    async def boundary(request: Request, next_handler):
        from fastapi.responses import JSONResponse
        path = request.url.path
        allowed = (request.method, path) in approved or (
            request.method == "GET" and path.startswith("/api/discoveries/") and len(path.split("/")) == 4)
        if not allowed:
            return JSONResponse({"detail": "Route unavailable in isolated backend"}, status_code=403)
        if path not in {"/health", "/__loqi_test/identity", "/api/v1/beta/features", "/api/v1/auth/refresh"}:
            if request.headers.get("authorization") != f"Bearer {SESSION}":
                return JSONResponse({"detail": "Unknown synthetic session"}, status_code=401)
        if request.headers.get("host") not in {f"{HOST}:{PORT}", "testserver"}:
            return JSONResponse({"detail": "Unapproved isolated host"}, status_code=400)
        if path not in {"/health", "/__loqi_test/identity"} and request.headers.get("x-loqi-test-run-id") != store.run_id:
            return JSONResponse({"detail": "Isolated run approval mismatch"}, status_code=412)
        return await next_handler(request)
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
                       allow_methods=["GET", "POST"], allow_headers=["authorization", "content-type", "x-workspace-id", "x-loqi-test-run-id"])
    app.include_router(discovery_api.router)
    app.include_router(leads_api.router)
    @app.get("/api/web/session/_/workspaces")
    async def workspaces(request: Request):
        return await workspace_api.list_workspaces("_", request)
    @app.post("/api/web/session/_/workspaces/select")
    async def select_workspace(request: Request):
        return await workspace_api.select_workspace("_", request)
    app.add_api_route("/api/v1/beta/features", list_beta_features, methods=["GET"])
    @app.get("/health")
    @app.get("/__loqi_test/identity")
    async def identity():
        return {"status": "ok", "marker": MARKER, "run_id": store.run_id, "persistence": "synthetic-memory", "outbound_blocked": True,
                "profile": store.profile, "fixture_counts": store.fixture_counts}
    @app.get("/api/v1/auth/me")
    async def me():
        return {"id": USER, "display_name": "Synthetic Operator", "email": "operator@example.invalid", "onboarding_complete": True,
                "organization": {"id": ORG, "name": "Synthetic", "role": "owner"}}
    @app.post("/api/v1/auth/refresh")
    async def refresh(request: Request):
        # Fixture-only credential exchange, not production refresh/OAuth behavior.
        if (await request.json()).get("refresh_token") != SESSION:
            raise HTTPException(401, "Unknown synthetic refresh token")
        await identity_api._get_service().validate_access_token(SESSION)
        return {"access_token": SESSION, "refresh_token": SESSION, "user_id": USER, "org_id": ORG}
    @app.post("/__loqi_test/fault")
    async def fault(request: Request):
        mode = (await request.json()).get("mode")
        if mode not in {"fail-staging", "truncate-staging"}:
            raise HTTPException(400, "Unknown synthetic fault")
        with store.lock: store.next_fault = mode
        return {"ok": True}
    return app


if __name__ == "__main__":
    startup_profile = prepare_runtime()
    import uvicorn
    application = create_app(profile=startup_profile)
    print(f"{MARKER} run_id={application.state.synthetic.run_id} target=http://{HOST}:{PORT} persistence=synthetic-memory", flush=True)
    uvicorn.run(application, host=HOST, port=PORT, workers=1, loop="asyncio", log_level="warning", access_log=False)
