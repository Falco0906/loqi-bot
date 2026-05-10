# Loqi Debugging Guide

Common errors and their fixes.

---

## Backend Issues

### Backend Won't Start

**Symptom:** `uvicorn main:app` fails

**Causes & Fixes:**

1. **Port in use:**
```bash
lsof -i :10000
kill -9 <PID>
```

2. **Missing dependencies:**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

3. **Python version issue:**
```bash
python3 --version  # Should be 3.11+
```

### Import Errors

**Symptom:** `ModuleNotFoundError: No module named 'xxx'`

**Fix:**
```bash
source venv/bin/activate
pip install <missing-package>
```

---

## SerpAPI Issues

### "SerpAPI error"

**Check:**
```bash
# In .env
SERPAPI_KEY=your-key-here
```

**Verify key works:**
```python
from serpapi import Client
client = Client(api_key="your-key")
result = client.search({"q": "test", "engine": "google"})
```

### "Rate limit exceeded"

**Fix:** Wait and retry, or upgrade SerpAPI plan.

### "No results found"

**Cause:** Query too specific or SerpAPI blocked.

**Fix:** Use more generic keywords.

---

## OpenAI Issues

### "OpenAI API key is invalid"

**Check:**
```bash
# In .env
OPENAI_API_KEY=sk-...
```

**Verify:**
```python
import openai
openai.api_key = "sk-..."
openai.Model.list()  # Should not error
```

### "OpenAI API quota exceeded"

**Fix:** Wait for quota reset or add payment method at platform.openai.com

### "OpenAI request timed out"

**Fix:** Default timeout is 20s. Increase in `icp_extractor.py` if needed.

---

## Supabase Issues

### "Connection failed"

**Check:**
```bash
# In .env
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ...
```

**Verify:**
```python
from supabase import create_client
client = create_client(url, key)
client.table("users").select("*").limit(1).execute()
```

### "Table not found"

**Fix:** Run migrations in Supabase SQL Editor:
```sql
-- Run backend/supabase/multi_client_mvp.sql
```

### "Row not found"

**Cause:** Query returned no results.

**Fix:** Check data exists in Supabase dashboard.

---

## Gmail OAuth Issues

### "OAuth error"

**Check:**
1. GMAIL_CLIENT_ID in .env
2. GMAIL_CLIENT_SECRET in .env
3. Redirect URI in Google Console matches

**Redirect URIs to add:**
- http://localhost:10000/google/callback
- (production URL)/google/callback

### "Token refresh failed"

**Fix:** Re-authenticate by disconnecting and reconnecting Gmail in UI.

---

## Frontend Issues

### Frontend Shows Blank White Page

**Cause:** Next.js build issue.

**Fix:**
```bash
cd frontend
rm -rf .next
npm run dev
```

### "Cannot connect to backend"

**Check:**
```bash
# In frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:10000
```

**Verify backend is running:**
```bash
curl http://localhost:10000/
```

### CORS Error

**Check:** Backend CORS settings in `main.py`

---

## Deployment Issues

### Render 502 Error

**Check:**
1. Backend logs in Render dashboard
2. Environment variables set
3. Start command correct: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Vercel Build Failed

**Check:**
1. Next.js version compatibility
2. Environment variables
3. Build command: `next build`

### "Module not found" in Production

**Cause:** Dependencies not installed correctly.

**Fix:** Check `requirements.txt` and `package.json` are correct.

---

## Session Issues

### "Invalid session token"

**Cause:** Token malformed or expired.

**Fix:** Create new session via API.

### Session Lost on Refresh

**Check:** Frontend stores token in localStorage.

---

## Log Location

**Backend logs:**
```bash
# Local development
tail -f backend/server.log

# Render
# Render dashboard → Logs
```

**What to look for:**
- `[icp_extractor]` - ICP extraction logs
- `[lead_provider]` - Lead search logs
- `[search_expansion]` - Search expansion logs
- `[supabase]` - Database operation logs
- `[gmail]` - Email operation logs
- ERROR - Errors

---

## Quick Diagnostics

```bash
# 1. Backend running?
curl http://localhost:10000/

# 2. Session creation works?
curl -X POST http://localhost:10000/api/web/session \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}'

# 3. Can reach Supabase?
# Check backend logs for supabase errors

# 4. SerpAPI works?
# Check backend logs for serpapi errors

# 5. Frontend loads?
curl http://localhost:3000
```

---

## Common Error Messages

| Error | Cause | Fix |
|-------|-------|-----|
| `asyncio.run() cannot be called from a running event loop` | Called async from sync context | Make function sync |
| `OPENAI_API_KEY not configured` | Missing key | Add to .env |
| `SERPAPI_KEY not found` | Missing key | Add to .env |
| `No leads found` | SerpAPI failed | Check logs |
| `Invalid session token` | Token invalid | Create new session |
| `Gmail not connected` | No OAuth token | Reconnect in UI |