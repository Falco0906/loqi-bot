# Loqi Known Issues

Honest documentation of current technical debt and limitations.

---

## Implemented But Not Working Well

### Gmail Integration - Partial

**Issue:** Inbox sync not fully functional, reply detection missing.

**Current state:**
- OAuth works
- Email sending works
- Inbox polling not implemented
- Reply detection not implemented

**Impact:** Users can't see replies in the app.

---

## Not Implemented

### Lead Ranking

**Issue:** No relevance scoring of leads.

**Current:** Results returned in SerpAPI order.
**Needed:** Sort by ICP match (industries, roles).

**File to create:** `backend/services/lead_ranker.py`

---

### Lead Enrichment

**Issue:** Only basic LinkedIn data available.

**Current:** name, title, company, linkedin_url
**Needed:** verified emails, company data, social profiles

**File to create:** `backend/services/enrichment.py`

---

### Reply Engine

**Issue:** No reply detection or classification.

**Impact:** Can't trigger follow-ups automatically.
**Needed:** Inbox polling + AI classification (positive/negative/OOO).

---

### Personalization Memory

**Issue:** No learning from user preferences.

**Current:** Each draft starts fresh.
**Needed:** Store tone preferences, accepted phrases, industry patterns.

---

### Analytics Dashboard

**Issue:** No metrics tracking.

**Needed:** messages_sent, replies_received, reply_rate, pipeline_value

---

### Stripe + Auth

**Issue:** No authentication or payments.

**Current:** Simple UUID session tokens.
**Needed:** Supabase Auth + Stripe subscriptions.

---

## Quality Issues

### Lead Quality Variability

**Issue:** SerpAPI returns mixed quality leads.

**Examples:**
- Some profiles incomplete
- Some titles are generic
- Some companies unknown

**Mitigation:** Basic filtering in `_is_relevant_lead()` but not comprehensive.

---

### Provider Noise

**Issue:** SerpAPI sometimes returns irrelevant results.

**Examples:**
- Wrong industry matches
- Generic titles
- Inactive profiles

**Current fix:** Deduplication by LinkedIn URL
**Future fix:** Ranking + enrichment filtering

---

### Quota Handling Limitations

**Issue:** OpenAI quota causes fallback frequently.

**Impact:** AI extraction not available when quota exceeded.
**Current fix:** Deterministic fallback works but less accurate.

**Future fix:** Better quota management, caching, or multiple API keys.

---

## Technical Debt

### Session Token Security

**Issue:** Session tokens are simple UUIDs, not cryptographically signed.

**Current:** `session_token = uuid.uuid4()`
**Risk:** Tokens can be guessed.

**Fix:** Use proper JWT or signed sessions.

---

### No Rate Limiting

**Issue:** No API rate limiting on endpoints.

**Risk:** Could be abused.
**Fix:** Add rate limiting middleware.

---

### Hardcoded Values

**Issue:** Some values should be configurable.

**Examples:**
- Max leads per search (currently ~10)
- Timeout values
- Max keywords

**Fix:** Move to environment variables.

---

### No Caching

**Issue:** Every search hits SerpAPI directly.

**Impact:** Slow on repeated searches, uses API quota.

**Fix:** Add Redis or in-memory caching.

---

## UX Issues

### Flow Interruptions

**Issue:** Session context can be lost on errors.

**Impact:** User has to restart from "What do you sell?"

**Fix:** Better error recovery, persist context more durably.

---

### No Undo

**Issue:** Can't undo draft edits.

**Impact:** Have to regenerate entire draft if unhappy.

**Fix:** Store draft history.

---

### Limited Tone Options

**Issue:** Only 4 tone options: casual, formal, aggressive, friendly.

**Impact:** May not fit all use cases.

**Fix:** Add custom tone or more options.

---

## Missing Documentation

### API Documentation

**Missing:** OpenAPI/Swagger docs for API.

**Impact:** Hard to integrate third parties.

---

### Error Code Reference

**Missing:** List of all error codes and meanings.

**Impact:** Hard to debug.

---

## Roadmap Alignment

These issues are tracked in priority order in `docs/NEXT_STEPS.md`:

1. Lead Ranking - HIGH PRIORITY
2. Enrichment Architecture - HIGH PRIORITY  
3. Gmail Production Hardening - MEDIUM
4. Reply Detection - MEDIUM
5. Personalization Memory - MEDIUM
6. Analytics - LOW
7. Stripe + Auth - LOW

---

## Not Bugs (By Design)

These are intentional limitations, not bugs:

- Fallback mode (deterministic when AI fails)
- SerpAPI-only leads (Apollo not wired)
- Single-session per browser (intentional design)
- No password auth (using session tokens)