# Loqi Workflows

Detailed documentation of each workflow in the system.

---

## 1. Lead Search Workflow

**Location:** `backend/workflows.py` - `generate_leads()`

### Trigger
User has provided both:
- `service` - what they sell (e.g., "CRM software")
- `target` - who they want to reach (e.g., "startups")

### Input
```python
{
    "type": "generate_leads",
    "service": "CRM software",
    "target": "startups",
    "user_id": "uuid",
    "workflow_session_id": "uuid"
}
```

### Flow

```
1. Combine service + target → "CRM software startups"
2. Call extract_structured_icp() → returns ICP object
3. Call expand_search_intent() → returns search queries
4. For each query → call search_free_leads()
5. Deduplicate by linkedin_url
6. Store leads in Supabase
7. Store ICP in workflow_events
8. Return leads
```

### Output
```python
{
    "ok": True,
    "type": "generate_leads",
    "source": "free",
    "leads": [
        {"name": "...", "title": "...", "company": "...", "linkedin_url": "..."}
    ],
    "stored_leads": [...],
    "message": "Found these leads:\n\n1. Name...",
    "error": None
}
```

### Fallback Behavior
If OpenAI unavailable:
1. ICP extraction uses deterministic fallback (industry-first mapping)
2. Search expansion uses deterministic fallback (service + target keywords)
3. SerpAPI still used for actual search
4. Never fails - always returns leads

### Error Handling
- If SerpAPI fails → return error message
- If no leads found → return "No leads found" message
- Never crash on provider failures

---

## 2. ICP Extraction Workflow

**Location:** `backend/services/icp_extractor.py`

### Input
```python
extract_structured_icp("CRM for startups")
```

### Flow

```
1. If OPENAI_API_KEY exists:
   a. Call OpenAI /v1/responses with gpt-4o-mini
   b. Parse JSON response
   c. Return AI-extracted ICP

2. If OPENAI_API_KEY missing/invalid/quota-exceeded:
   a. Use deterministic fallback
   b. Extract offer (parse "for", "to", etc.)
   c. Detect industries from keywords
   d. Map industries → roles (industry-first)
   e. Generate industry-aware keywords
   f. Return fallback ICP
```

### Output (AI Mode)
```python
{
    "offer": "CRM",
    "industries": ["SaaS", "startups"],
    "target_roles": ["RevOps", "CRM Manager", "VP Sales"],
    "company_types": ["startups", "enterprise"],
    "pain_points": ["pipeline management", "sales tracking"],
    "keywords": ["CRM for startups", "startup CRM software"],
    "search_hints": ["RevOps startups"],
    "mode": "ai"
}
```

### Output (Fallback Mode)
```python
{
    "offer": "CRM",
    "industries": ["startups"],
    "target_roles": ["Founder", "COO", "Head of Operations"],
    "company_types": [],
    "pain_points": [],
    "keywords": ["CRM startups", "CRM for startups"],
    "search_hints": ["Founder startups"],
    "mode": "fallback"
}
```

### Key Concept
**Fallback != Fake AI**
- Fallback uses deterministic rules (industry mappings)
- Never generates fake leads or companies
- Only uses data extractable from user input
- Preserves existing SerpAPI functionality

---

## 3. Semantic Search Expansion

**Location:** `backend/services/search_expansion.py`

### Input
```python
expand_search_intent("CRM", "startups", icp)
```

### Flow

```
1. If OPENAI_API_KEY exists:
   a. Call OpenAI with ICP context
   b. Generate expanded keywords and roles
   c. Return expansion

2. If unavailable:
   a. Use ICP keywords directly
   b. Generate LinkedIn-formatted queries
   c. Format: site:linkedin.com/in "search terms"
```

### Output
```python
{
    "roles": ["Founder", "COO", "RevOps"],
    "industries": ["startups", "SaaS"],
    "keywords": ["CRM startups", "startup CRM software"],
    "search_queries": [
        "site:linkedin.com/in \"CRM startups\"",
        "site:linkedin.com/in \"startup CRM software\""
    ]
}
```

---

## 4. Lead Selection Workflow

**Location:** `backend/services/conversation_engine.py`

### Trigger
User replies with a number (e.g., "1") after seeing lead list

### Flow
```
1. Parse number from message
2. Match to lead in session
3. Store selected lead ID in context
4. Ask "Write your outreach message?"
```

### Error Handling
- Invalid number → "Invalid selection. Reply with a number."
- Lead not found → "Couldn't find that lead. Try again."

---

## 5. Draft Generation Workflow

**Location:** `backend/workflows.py` - `draft_message()`

### Trigger
User provides message or requests rewrite

### Input
```python
{
    "type": "draft_message",
    "lead": {...},
    "user_id": "uuid",
    "tone": "casual" | "formal" | "aggressive" | "friendly",
    "edit_request": "make it shorter" | None,
    "conversation_context": [...]
}
```

### Flow
```
1. Extract lead info (name, title, company)
2. Get tone preference
3. Get conversation context
4. Call generate_outreach_email() in ai.py
5. Return draft
```

### Output
```python
{
    "ok": True,
    "type": "draft_message",
    "draft": "Hi {name},...",
    "message": "Here's your draft..."
}
```

---

## 6. Email Send Workflow

**Location:** `backend/workflows.py` - `send_email_workflow()`

### Trigger
User confirms draft is ready to send

### Input
```python
{
    "type": "send_email",
    "lead": {...},
    "draft": "Hi {name},...",
    "user_id": "uuid"
}
```

### Flow
```
1. Get user's Gmail token from Supabase
2. If no token → return Gmail connect URL
3. Send email via Gmail API
4. Update lead status to "contacted"
5. Return success message
```

### Error Handling
- No token → "Connect Gmail to send emails"
- Send failed → "Email failed to send. Try again."
- Rate limited → "Rate limited. Try again later."

---

## 7. Session Management

**Location:** `backend/services/conversation_engine.py` - `handle_message()`

### Flow
```
1. Get user from session token
2. Load session context from Supabase
3. Process message based on state:
   a. No service → prompt "What do you sell?"
   b. No target → prompt "Who do you want to reach?"
   c. Have both → run workflow
4. Generate response
5. Log to conversations table
6. Return messages + events
```

### Context State
```python
{
    "service": "CRM software",      # what they sell
    "target": "startups",          # who they want
    "selected_lead_id": "uuid",    # selected lead
    "user_messages": [...],        # message history
    "assistant_messages": [...]     # bot history
}
```