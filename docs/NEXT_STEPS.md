# Loqi Next Steps

Engineering priorities in order. Each item includes why it matters, architecture direction, expected files, and implementation notes.

---

## Priority 1: Lead Ranking Pipeline

### Why It Matters
Currently leads are returned in SerpAPI order with no relevance scoring. Users get random results regardless of how well a lead matches their ICP.

### Architecture Direction
- Add scoring function that compares lead attributes (title, company) against ICP (industries, target_roles)
- Score = weighted match between lead profile and ICP
- Sort leads by score before returning

### Expected Files
- New: `backend/services/lead_ranker.py` - Scoring logic
- Update: `backend/services/lead_provider.py` - Integrate ranking
- Update: `backend/services/supabase.py` - Store scores

### Implementation Notes
```
Input: [leads], ICP
Output: [leads] sorted by relevance_score

Scoring algorithm:
- industry_match: +10 if company/title contains industry keyword
- role_match: +20 if title matches target_roles
- company_type_match: +5 if company type matches
- baseline: +1 per lead
```

### Risks
- Over-engineering scoring before enough data
- Initial rankings may feel arbitrary

### Recommendation
Start simple with keyword matching before adding ML-based scoring.

---

## Priority 2: Enrichment Architecture

### Why It Matters
Current leads only have LinkedIn profile URLs. Need company data, verified emails, and social signals for better outreach.

### Architecture Direction
- Build enrichment provider abstraction (like lead provider)
- Start with one provider (Apollo or Clearbit)
- Store enriched data in `leads` table
- Graceful degradation if enrichment fails

### Expected Files
- New: `backend/services/enrichment.py` - Provider abstraction
- New: `backend/services/enrichment_providers/` - Provider implementations
- Update: `backend/services/lead_provider.py` - Call enrichment after search
- Update: `backend/services/supabase.py` - Add enrichment fields to leads

### Implementation Notes
```
Lead enrichment flow:
1. Search returns base leads
2. For each lead, call enrichment provider
3. Merge enrichment data (emails, company info, social)
4. Update lead record in Supabase
5. Return enriched leads
```

### Risks
- Cost per enrichment (need quota management)
- Data quality variability
- Provider rate limits

### Recommendation
Start with Apollo for enrichment since they're already a lead provider target.

---

## Priority 3: Gmail Production Hardening

### Why It Matters
Gmail integration works but has edge cases: OAuth failures, send failures not tracked, reply detection missing.

### Architecture Direction
- Add send status tracking (queued → sent → delivered → failed)
- Add retry logic for transient failures
- Implement basic inbox sync for reply detection
- Store Gmail message IDs for tracking

### Expected Files
- Update: `backend/services/gmail.py` - Add status tracking, retry logic
- Update: `backend/services/supabase.py` - Add email_tracking table
- Update: `backend/workflows.py` - Handle send status in send_email workflow

### Implementation Notes
```
Email tracking table:
- id, user_id, lead_id, message_id, status, sent_at, delivered_at, opened_at, replied_at

Statuses: pending, sent, delivered, bounced, failed
```

### Risks
- Gmail API rate limits
- OAuth token expiry during long sessions

---

## Priority 4: Reply Detection

### Why It Matters
Users have no visibility into replies. Can't automate follow-ups without knowing when someone responds.

### Architecture Direction
- Poll Gmail inbox for new messages in sent thread
- Classify replies: positive, negative, out_of_office, not_interested
- Trigger workflow events on reply detection
- Update UI to show reply status

### Expected Files
- Update: `backend/services/gmail.py` - Add inbox polling, reply classification
- Update: `backend/services/conversation_engine.py` - Handle reply events
- Update: frontend - Add reply status to lead cards

### Implementation Notes
```
Reply classification (using AI):
- positive: wants to talk, asking questions
- negative: not interested, wrong person
- out_of_office: auto-reply
- not_interested: explicit rejection
```

### Risks
- Polling frequency vs API quota
- False positives in classification
- Privacy concerns with inbox access

---

## Priority 5: Personalization Memory

### Why It Matters
Current drafts don't learn from user preferences. Each outreach starts fresh with no context about what works.

### Architecture Direction
- Store user preferences: preferred tone, accepted phrases, rejected phrases
- Track industry patterns from successful leads
- Use memory in draft generation as context
- Build preference profile over time

### Expected Files
- New: `backend/services/memory.py` - Memory storage and retrieval
- Update: `backend/services/ai.py` - Include memory context in prompts
- Update: `backend/services/supabase.py` - Add user_preferences table

### Implementation Notes
```
user_preferences table:
- id, user_id, tone, accepted_phrases[], rejected_phrases[], industries[], top_performing_drafts[]
```

### Risks
- Privacy implications of storing preferences
- Memory could become stale/wrong

---

## Priority 6: Analytics Dashboard

### Why It Matters
No visibility into performance. Can't optimize outreach without metrics.

### Architecture Direction
- Track: messages_sent, replies_received, reply_rate, leads_generated
- Store metrics in Supabase
- Build simple dashboard in frontend
- Start with basic counts before complex metrics

### Expected Files
- New: `backend/services/analytics.py` - Metrics computation
- Update: `backend/services/supabase.py` - Add analytics tables
- Update: frontend - Add analytics view

### Implementation Notes
```
Metrics to track:
- campaigns_sent: count of email campaigns
- messages_sent: total emails sent
- replies_received: total replies
- reply_rate: replies / messages_sent
- leads_generated: leads found
- pipeline_value: estimated opportunity value
```

### Risks
- Complexity creep in metrics
- Need historical data for meaningful metrics

---

## Priority 7: Stripe + Auth

### Why It Matters
Currently no authentication or payment. Need proper auth before scaling.

### Architecture Direction
- Integrate Supabase Auth
- Add Stripe checkout for subscriptions
- Protect API routes with auth
- Add user roles (free, pro, team)

### Expected Files
- New: `backend/middleware/auth.py` - Auth middleware
- New: `backend/services/stripe.py` - Stripe integration
- Update: `backend/main.py` - Add auth routes
- Update: frontend - Add auth UI, subscription management

### Implementation Notes
```
Stripe tiers (example):
- Free: 10 leads/month, 5 emails/day
- Pro: 100 leads/month, 50 emails/day, enrichment
- Team: unlimited, multiple users
```

### Risks
- Payment complexity
- Need terms/legal
- API key management

---

## Long-Term Direction

### Adaptive Outbound Intelligence
- AI that learns which leads convert
- Automatic follow-up timing optimization
- Dynamic subject line/hook generation

### Multi-Provider Lead Routing
- Route to different providers based on industry
- Fallback chains when providers fail
- Quality-based provider selection

### Autonomous Followups
- Auto-generate follow-ups based on reply context
- Multi-step sequences
- Meeting booking integration

### CRM Memory Graph
- Track every interaction with leads
- Build relationship timeline
- Surface context for next outreach

### Multi-Agent Orchestration
- Separate agents for: lead search, enrichment, drafting, sending, followup
- Agent coordination layer
- Parallel processing of leads