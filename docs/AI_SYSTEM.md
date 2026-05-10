# Loqi AI System

Documenting how AI is used throughout Loqi, including deterministic fallback philosophy.

---

## Overview

Loqi uses OpenAI for multiple functions:
1. ICP extraction
2. Semantic search expansion
3. Draft generation
4. Intent classification

All AI operations have deterministic fallback to ensure the system NEVER crashes.

---

## ICP Extraction

### AI Mode

**File:** `backend/services/icp_extractor.py`

Uses OpenAI `gpt-4o-mini` via `/v1/responses` endpoint.

**Prompt:**
```
You are an ICP extraction engine for B2B sales.
Given user input about what they sell and who they target, extract:
- offer: product/service name
- industries: relevant industries
- target_roles: job titles of buyers
- keywords: search-friendly terms
- search_hints: lead search hints
```

**Example:**
```
Input: "CRM for startups"
Output: {"offer": "CRM", "industries": ["SaaS", "startups"], "target_roles": ["RevOps", "CRM Manager", "Founder"]}
```

### Fallback Mode

When OpenAI unavailable (quota, missing key, errors), uses deterministic rules:

1. **Offer extraction:** Parse "for", "to", "targeting" from input
2. **Industry detection:** Match keywords (restaurants, healthcare, startups)
3. **Industry-first roles:** Map industries to relevant job titles:
   - restaurants → Restaurant Owner, Operations Manager
   - startups → Founder, COO
   - healthcare → Practice Manager, Clinic Director
4. **Keyword generation:** Combine offer + industry

**Critical:** Fallback NEVER invents data. Only uses what's in user input + industry mappings.

---

## Semantic Search Expansion

### AI Mode

**File:** `backend/services/search_expansion.py`

Uses OpenAI to expand ICP into search queries.

**Prompt:**
```
Given product/service and ICP data, generate:
- roles: job titles
- industries: sectors
- keywords: search terms
- search_queries: LinkedIn-formatted queries
```

### Fallback Mode

1. Take ICP keywords directly
2. Format as LinkedIn queries: `site:linkedin.com/in "keyword"`

---

## Draft Generation

### Implementation

**File:** `backend/services/ai.py` - `generate_outreach_email()`

Uses OpenAI to generate personalized outreach emails.

**Prompt includes:**
- Lead info (name, title, company)
- User's product/service
- Tone preference (casual, formal, aggressive, friendly)
- Conversation context

### Fallback

No fallback for drafts - requires AI. If fails, return error message.

---

## Intent Classification

### Implementation

**File:** `backend/services/ai.py` - `classify_intent()`

Classifies user message into:
- `new_search` - wants new leads
- `select_lead` - selecting from list
- `draft_message` - wants to draft
- `send` - send email
- `refine_message` - edit draft
- `chitchat` - general conversation

---

## Fallback Philosophy

### CRITICAL CONCEPT: Fallback != Fake AI

**What Fallback Does:**
- Uses deterministic rules (industry mappings, keyword parsing)
- Never generates fake leads
- Never fabricates company data
- Preserves existing SerpAPI functionality
- Always returns valid output

**What Fallback Does NOT Do:**
- Pretend to be AI
- Invent people or companies
- Generate fake enrichment data
- Create hallucinations

### Why This Matters

1. **Trust:** Users know they're getting real data, not fabricated
2. **Debugging:** Deterministic is predictable and traceable
3. **Quality:** Real SerpAPI leads > fake AI-generated leads
4. **Graceful Degradation:** System never crashes, just uses simpler logic

---

## Graceful Degradation

The system degrades gracefully in this order:

1. **Full AI:** OpenAI works → AI extraction + expansion + ranking
2. **Partial AI:** OpenAI fails → fallback extraction + SerpAPI search
3. **Basic:** SerpAPI fails → error message (can't find leads)

Never:
- Return fake leads
- Invent data
- Crash on API failure

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENAI_API_KEY` | (none) | API key for all AI operations |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model used for ICP + expansion |

---

## Future AI Systems

### Lead Ranking (Planned)
- Score leads based on ICP match
- Use title, company, industry matching
- Sort results by relevance

### Personalization Memory (Planned)
- Store user preferences (tone, phrases)
- Learn from accepted/rejected drafts
- Use memory in draft prompts

### Reply Engine (Planned)
- Classify replies (positive, negative, OOO)
- Detect reply intent
- Trigger follow-up workflows

---

## Files Reference

```
backend/services/
├── icp_extractor.py       # ICP extraction (AI + fallback)
├── search_expansion.py    # Query expansion (AI + fallback)
├── ai.py                  # Draft generation, intent classification
├── lead_provider.py       # Lead orchestration with fallback
└── conversation_engine.py # Uses AI for workflow routing
```