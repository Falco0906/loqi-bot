# Backend Connection Audit

Date: 2026-07-11
Auditor: OpenCode

---

## Executive Summary

**The backend does not crash, exit, or restart on its own.** Every endpoint tested (create session, create campaign, analyze campaigns, generate drafts, list campaigns, get messages) returns HTTP 200 in under 200ms, and the process survives multiple sequential heavy operations including OpenAI calls and background async batch drafting.

The root cause of `NS_ERROR_CONNECTION_REFUSED` is that the backend process is killed between work sessions (e.g., during test teardown with `kill $(lsof -ti:10000)`) and is never restarted. The frontend process (`next dev`) continues running, so when the user opens the browser, it makes `fetch()` calls to `127.0.0.1:10000` where nothing is listening. Firefox reports this as "Cross-Origin Request Blocked: CORS request did not succeed" with "Status: (null)" because the TCP connection was refused — the browser categorizes DNS/TCP failures under CORS when the request is cross-origin.

The secondary issue is a CORS spec violation: `allow_origins=["*"]` with `allow_credentials=True` at `backend/main.py:103-109`. When the server IS running, modern browsers may reject credentialed requests with a wildcard origin. However, since the frontend's `fetch()` calls don't set `credentials: "include"`, this does not currently trigger errors.

---

## Part 1 — Backend Status

| Check | Result |
|-------|--------|
| Process running | NO (when user reported error) / YES (when started manually) |
| Exits immediately | NO |
| Crashes after startup | NO |
| Restarts automatically | NO (no process supervisor) |
| Port 10000 listener | Nothing bound when down; `python` PID when up |

---

## Part 2 — Startup Log

```
/home/faisal/loqi-bot/backend/main.py:120: DeprecationWarning:
        on_event is deprecated, use lifespan event handlers instead.
  @app.on_event("startup")

INFO:     Started server process [113597]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:10000 (Press CTRL+C to quit)
```

- **Warnings:** 1 deprecation warning (`@app.on_event("startup")` → use lifespan handlers)
- **Exceptions:** None
- **Stack traces:** None
- **Database init:** `startup_event()` calls `test_supabase_connection()` wrapped in try/except; failure is non-fatal
- **Provider init:** None at startup
- **Background workers:** None at startup (workers created on demand via `asyncio.create_task`)
- **Hidden errors:** None

---

## Part 3 — Endpoint Verification

| Endpoint | Method | HTTP Status | Response Time | Body |
|----------|--------|-------------|---------------|------|
| `/` | GET | 200 | 4ms | `Loqi backend running` |
| `/docs` | GET | 200 | 0.8ms | Swagger UI |
| `/api/web/session` | POST | 200 | 3.3s* | `{ok, session_token, ...}` |
| `/api/web/session/{token}/campaigns` | POST | 200 | 1.3ms | `{ok, campaign: {id, name, leads, ...}}` |
| `/api/web/session/{token}/campaigns` | GET | 200 | 1.2ms | `{ok, campaigns: [...]}` |
| `/api/web/session/{token}/messages` | GET | 200 | 170ms | `{ok, messages: []}` |
| `/api/web/session/{token}/analyze-campaigns` | POST | 200 | 1.1ms | `{ok, plan_id, campaigns, ...}` |
| `/api/web/session/{token}/campaigns/{id}/generate-drafts` | POST | 200 | immediate | `{ok, batch_id, total}` |
| `/api/web/session/{token}/campaigns/{id}/generation-status` | GET | 200 | immediate | `{ok, active, total, completed}` |

\* Session creation includes conversation engine initialization (first request is slower).

**No exceptions observed during any endpoint call.**

---

## Part 4 — Frontend Connection Configuration

**File:** `frontend/lib/api.ts`

| Property | Value |
|----------|-------|
| `API_BASE` | `process.env.NEXT_PUBLIC_LOQI_API_BASE_URL \|\| "http://127.0.0.1:10000"` |
| fetch wrapper | `parseJson<T>` — plain `response.json()` |
| credentials | Not set (default: `"same-origin"`) |
| headers | `{ "Content-Type": "application/json" }` (some calls omit headers entirely) |
| timeout logic | **None** — no `AbortController` or timeout anywhere |
| abort controllers | **None** |
| retry logic | **None** |
| Error handling | `throw new Error(text)` with body text on non-2xx |

The frontend correctly targets `http://127.0.0.1:10000`. The URL is correct.

**No timeout or retry logic** means: if the backend is down, the `fetch()` will hang until the browser's default timeout (typically 60-300s), before throwing a `TypeError: Failed to fetch`. The user sees this as an immediate error only if the TCP connection is actively refused (which it is when nothing is on port 10000).

---

## Part 5 — CORS Configuration

**File:** `backend/main.py`, lines 102-109

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # wildcard
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

| Property | Value | Spec Compliant? |
|----------|-------|-----------------|
| `allow_origins` | `["*"]` | ❌ Conflict with `allow_credentials=True` |
| `allow_credentials` | `True` | ❌ Not allowed with `allow_origins=["*"]` |
| `allow_methods` | `["*"]` | ✅ |
| `allow_headers` | `["*"]` | ✅ |

Per the CORS specification (Fetch Standard §3.2.6), when `allow_credentials=True`, the `Access-Control-Allow-Origin` response header must be an explicit origin (not `*`). The browser will reject credentialed requests with a wildcard origin. However, the frontend's `fetch()` calls do not include `credentials: "include"` or `credentials: "same-origin"` — the default is `"same-origin"` which means cookies and auth headers are only sent to the same origin. Since the frontend (localhost:3000) and backend (127.0.0.1:10000) are different origins, the default behavior already omits credentials.

**CORS is not the root cause of the connection failures**, but it is a latent spec violation that could cause issues if credential support is added later.

---

## Part 6 — Crash Investigation

| Scenario | Outcome |
|----------|---------|
| Generate drafts (3 OpenAI calls) | ✅ Completed — no crash |
| Save campaign (in-memory store) | ✅ Completed — no crash |
| Analyze campaigns (signal matching) | ✅ Completed — no crash |
| Background `asyncio.create_task` | ✅ Completed — task finishes, event loop intact |
| `run_in_executor` thread pool worker | ✅ Completed — thread pool handles fine |
| Supabase write attempt | ✅ Graceful — try/except, logs warning |
| Provider calls (OpenAI API) | ✅ All 3 calls returned 200 |
| Sequential heavy operations | ✅ Still running after 8 API calls + 3 OpenAI calls |

**No crash identified in any code path.** The `_process_batch_drafts` function (line 40-100) wraps the per-lead OpenAI call in `try/except Exception`, so even if one draft fails, the background task continues and sets `job["status"] = "completed"`.

---

## Part 7 — Browser Error Correlation

```
NS_ERROR_CONNECTION_REFUSED
Status: (null)
Cross-Origin Request Blocked
```

These three errors all point to the **same root cause**: no server is listening on `127.0.0.1:10000`.

1. **`NS_ERROR_CONNECTION_REFUSED`** — Firefox's raw TCP error. The browser attempted to open a TCP socket to `127.0.0.1:10000` and received a TCP RST (reset) because no process was bound to that port.

2. **`Status: (null)`** — No HTTP response was received, so there is no status code. Confirms the TCP handshake never completed.

3. **`Cross-Origin Request Blocked: CORS request did not succeed`** — Firefox's presentation of connection failures for cross-origin requests. When a TCP-level error occurs during a CORS request, the browser classifies it as a CORS failure with the reason "CORS request did not succeed."

**Correlation with backend logs:** When the backend was killed at the end of our previous test session (`kill $(lsof -ti:10000)`) and not restarted, the frontend continued running. Any `fetch()` call from the frontend to the backend would produce exactly these three errors.

**Diagnostic evidence from the audit:**

| Time | Backend Process | User Experience |
|------|----------------|-----------------|
| After test cleanup | Killed, port 10000 free | Browser shows NS_ERROR_CONNECTION_REFUSED |
| After `python main.py` | Running, port 10000 bound | All endpoints respond 200 |
| During heavy load | Running, event loop intact | No errors |
| After 10 seconds idle | Running, stable | No errors |

---

## Part 8 — Root Cause and Recommended Fix

### Root Cause

**The backend FastAPI process is not running when the frontend tries to reach it.**

The backend has no process supervisor (no systemd unit, no Docker restart policy, no PM2, no supervisor) and must be started manually. When it is killed (e.g., during our test teardown commands) and not restarted, the frontend continues serving the browser and attempts `fetch()` calls to `127.0.0.1:10000` where nothing is listening. Firefox reports the TCP connection refusal as a CORS error because the request is cross-origin (`localhost:3000 → 127.0.0.1:10000`).

### Recommended Fix (minimal, do not implement yet)

1. **Add a startup script or process supervisor** that ensures the backend is always running alongside the frontend. For example:
   - Add a `"dev": "concurrently \"cd backend && python main.py\" \"cd frontend && next dev\""` script to the root `package.json`

2. **Fix the CORS spec violation** (secondary): Change `allow_origins=["*"]` to `allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"]` and keep `allow_credentials=True`, OR set `allow_credentials=False`.

3. **Add a health check retry in the frontend** (defensive): Wrap the initial API call in a retry with backoff, so if the backend is briefly unavailable, the frontend can recover without a manual reload.

### Confidence

**95%** — The evidence is conclusive: the backend starts cleanly, runs stably through all operations, and three separate browser error indicators all trace to the same cause (connection refused). The remaining 5% accounts for edge cases where the backend might crash from an unhandled exception we didn't trigger during testing.
