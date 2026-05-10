# Loqi Multi-Client MVP

## What changed

- Added a channel-agnostic `ConversationEngine` in `backend/services/conversation_engine.py`
- Kept `backend/workflows.py` as the business-logic core
- Converted Telegram into an adapter over structured engine responses
- Added lightweight web session APIs
- Scaffolded a dark-mode-first Next.js web chat client in `frontend/`
- Added MVP Supabase schema for `workflow_sessions`, `workflow_messages`, and `workflow_events`

## Backend refactor map

- `backend/services/conversation_engine.py`
  - shared orchestration entrypoint for web and Telegram
- `backend/services/channel_adapters/telegram.py`
  - Telegram rendering adapter
- `backend/services/conversation_store.py`
  - lightweight session handling + optional workflow session persistence
- `backend/main.py`
  - new web APIs and shared Gmail callback handling

## Web API layer

- `POST /api/web/session`
- `GET /api/web/session/{session_token}`
- `GET /api/web/session/{session_token}/messages`
- `POST /api/web/session/{session_token}/messages`
- `GET /api/web/session/{session_token}/gmail`

## Session handling

- MVP sessions are backend-issued opaque tokens
- Web stores the token in `localStorage`
- Backend maps the token to a lightweight user record using the existing `users` table
- This is intentionally temporary and should be replaced later by real auth

## Telegram compatibility

- Telegram still posts to `/webhook`
- The webhook now calls the same conversation engine as the web UI
- Telegram rendering is handled in the adapter layer only

## Local development

### Backend

1. `cd backend`
2. `source venv/bin/activate`
3. `uvicorn main:app --reload --host 0.0.0.0 --port 10000`

Set:

- `FRONTEND_ORIGIN=http://localhost:3000`
- all existing provider keys and Supabase vars

### Frontend

1. `cd frontend`
2. `npm install`
3. `NEXT_PUBLIC_LOQI_API_BASE_URL=http://127.0.0.1:10000 npm run dev`

## Deployment

### Backend

- keep deploying FastAPI on Render
- add `FRONTEND_ORIGIN` for the web app origin

### Frontend

- deploy `frontend/` separately on Vercel
- set `NEXT_PUBLIC_LOQI_API_BASE_URL` to the deployed backend URL

## Future auth migration strategy

Later, replace the lightweight session token layer with:

1. Supabase Auth identity
2. `channel_accounts` table for Telegram / WhatsApp / web linkage
3. JWT-backed API auth for web/mobile
4. Gmail linkage per authenticated user instead of per browser session

The current structure is intentionally thin so this migration can happen without rewriting `workflows.py` or the conversation engine boundary.
