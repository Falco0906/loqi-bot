# Loqi Environment Variables

All environment variables required to run Loqi, separated by category.

---

## Backend Variables

### Required (Production)

| Variable | Description | Example |
|----------|-------------|---------|
| `SUPABASE_URL` | Supabase project URL | `https://xyzabc.supabase.co` |
| `SUPABASE_KEY` | Supabase anon/public key | `eyJhbGciOiJIUzI1NiIs...` |
| `SESSION_SECRET` | Secret for session tokens | `random-uuid-or-string` |
| `LEAD_PROVIDER` | Lead provider to use | `free` (or `apollo`) |

### Required (Gmail)

| Variable | Description | Example |
|----------|-------------|---------|
| `GMAIL_CLIENT_ID` | Google OAuth client ID | `123456789-xxx.apps.googleusercontent.com` |
| `GMAIL_CLIENT_SECRET` | Google OAuth client secret | `GOCSPX-xxx` |

### Optional (AI)

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | (not set - fallback mode) |
| `OPENAI_MODEL` | Model to use | `gpt-4o-mini` |

### Optional (Leads)

| Variable | Description | Default |
|----------|-------------|---------|
| `SERPAPI_KEY` | SerpAPI key for lead search | (not set - will fail) |
| `APOLLO_API_KEY` | Apollo API key | (not set) |
| `APOLLO_SEARCH_URL` | Apollo search endpoint | `https://api.apollo.io/api/v1/mixed_people/search` |

---

## Frontend Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `NEXT_PUBLIC_API_URL` | Backend API URL | `http://localhost:10000` or production URL |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase URL for client | (optional) |
| `NEXT_PUBLIC_SUPABASE_KEY` | Supabase anon key for client | (optional) |

---

## Deployment Variables

### Render (Backend)

```
SUPABASE_URL=...
SUPABASE_KEY=...
SESSION_SECRET=...
LEAD_PROVIDER=free
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
OPENAI_API_KEY=... (optional)
SERPAPI_KEY=... (required for leads)
```

### Vercel (Frontend)

```
NEXT_PUBLIC_API_URL=https://loqi-backend.onrender.com
```

---

## Example .env File

```bash
# Supabase (required)
SUPABASE_URL=https://xyzabc.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIs...

# Session (required)
SESSION_SECRET=your-secret-key-here

# Lead Provider (required)
LEAD_PROVIDER=free

# Gmail OAuth (required for email)
GMAIL_CLIENT_ID=123456789-xxx.apps.googleusercontent.com
GMAIL_CLIENT_SECRET=GOCSPX-xxx

# OpenAI (optional - fallback works without)
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# SerpAPI (required for lead search)
SERPAPI_KEY=xxx

# Apollo (optional - for future)
APOLLO_API_KEY=xxx
```

---

## Where to Get Each Variable

### Supabase
1. Go to https://supabase.com
2. Project → Settings → API
3. URL from "Project URL"
4. Key from "anon public" (not service_role)

### Gmail OAuth
1. Go to https://console.cloud.google.com
2. Create project → APIs & Services → Credentials
3. Create OAuth Client ID
4. Web application type
5. Authorized redirect: `http://localhost:10000/google/callback`

### OpenAI
1. Go to https://platform.openai.com
2. API Keys → Create new secret key

### SerpAPI
1. Go to https://serpapi.com
2. Sign up → Dashboard → API Key

### Apollo
1. Go to https://apollo.io
2. Developer → API → Get API Key

---

## Security Notes

- Never commit `.env` to git (already in .gitignore)
- Use different keys for production vs development
- Keep `SUPABASE_KEY` and `SESSION_SECRET` secure
- Rotate API keys periodically

---

## Future Variables

These are not yet implemented but planned:

| Variable | Purpose |
|----------|---------|
| `STRIPE_SECRET_KEY` | Payment processing |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook verification |
| `REDIS_URL` | Caching and sessions |
| `SENTRY_DSN` | Error tracking |
| `LOG_LEVEL` | Logging configuration |