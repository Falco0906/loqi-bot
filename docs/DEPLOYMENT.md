# Loqi Deployment

Complete deployment documentation for backend and frontend.

---

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Vercel    │────▶│   Render    │────▶│  Supabase   │
│  (Frontend) │     │  (Backend)  │     │ (Database)  │
└─────────────┘     └─────────────┘     └─────────────┘
      │                   │                    │
      │                   ▼                    │
      │            ┌─────────────┐             │
      │            │   Gmail     │             │
      │            │    API      │             │
      │            └─────────────┘             │
      │                   │
      ▼                   ▼
┌─────────────┐     ┌─────────────┐
│   OpenAI    │     │  SerpAPI   │
│    API      │     │            │
└─────────────┘     └─────────────┘
```

---

## Render Backend Deployment

### 1. Connect Repository

1. Go to https://render.com
2. "New" → "Web Service"
3. Connect GitHub repo: `Falco0906/loqi-bot`
4. Select branch: `main`

### 2. Configure Service

| Setting | Value |
|---------|-------|
| Name | loqi-backend |
| Root Directory | `backend` |
| Build Command | (leave empty) |
| Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |

### 3. Environment Variables

Add these in Render dashboard:

```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIs...
SESSION_SECRET=your-random-secret
LEAD_PROVIDER=free
GMAIL_CLIENT_ID=xxx
GMAIL_CLIENT_SECRET=xxx
SERPAPI_KEY=xxx
OPENAI_API_KEY=sk-xxx (optional)
```

### 4. Deploy

- Auto-deploys on push to `main`
- Check logs for errors

---

## Vercel Frontend Deployment

### 1. Connect Repository

1. Go to https://vercel.com
2. "Add New" → "Project"
3. Import GitHub repo: `Falco0906/loqi-bot`

### 2. Configure

| Setting | Value |
|---------|-------|
| Framework | Next.js |
| Root Directory | `frontend` |
| Build Command | `next build` |

### 3. Environment Variables

```
NEXT_PUBLIC_API_URL=https://loqi-backend.onrender.com
```

### 4. Deploy

- Auto-deploys on push to `main`

---

## Supabase Setup

### 1. Create Project

1. https://supabase.com → "New Project"
2. Name: `loqi-bot`
3. Database password: save for .env

### 2. Run Migrations

1. Project → SQL Editor
2. Copy contents of `backend/supabase/multi_client_mvp.sql`
3. Run

### 3. Get Credentials

- URL: Project Settings → API → Project URL
- Key: Project Settings → API → anon public

---

## Production Checklist

### Pre-Deploy

- [ ] All environment variables set in Render
- [ ] All environment variables set in Vercel
- [ ] Supabase schema deployed
- [ ] Gmail OAuth redirect updated to production URL

### Post-Deploy

- [ ] Backend health check: `curl https://your-backend.onrender.com/`
- [ ] Frontend loads correctly
- [ ] Session creation works
- [ ] Lead search works
- [ ] Gmail OAuth works

---

## Environment Update for Production

### Backend .env (Production)

```
SUPABASE_URL=https://xyz.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIs...
SESSION_SECRET=production-secret
LEAD_PROVIDER=free
GMAIL_CLIENT_ID=xxx
GMAIL_CLIENT_SECRET=xxx
SERPAPI_KEY=xxx
OPENAI_API_KEY=sk-xxx
```

### Frontend .env.local

```
NEXT_PUBLIC_API_URL=https://loqi-backend.onrender.com
```

---

## Troubleshooting

### Backend Not Starting

Check Render logs:
- Python version compatibility
- Missing environment variables
- Import errors

### Frontend Can't Reach Backend

- Check NEXT_PUBLIC_API_URL in Vercel
- Check CORS settings in backend
- Verify backend is running

### Database Connection Failed

- Verify SUPABASE_URL and SUPABASE_KEY
- Check Supabase project is active
- Verify tables exist

---

## Rollback

To rollback:
1. Render: Go to "Deploys" → find last working → "Promote"
2. Vercel: Go to "Deployments" → find last working → "Promote"

---

## Monitoring

### Backend Logs
- Render dashboard → "Logs"

### Frontend Errors
- Vercel dashboard → "Edge Functions" or "Serverless Functions"

### Database
- Supabase dashboard → "Table Editor" or "Logs"