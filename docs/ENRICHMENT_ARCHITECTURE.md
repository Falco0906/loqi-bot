# Loqi Company Intelligence Layer

The enrichment layer transforms raw lead data into structured business
intelligence **before** draft generation. The AI never has to infer context
from only a name and title — it receives a complete picture of why this
company is a good prospect.

## Architecture

```
Lead selected (by user)
      |
      v
Enricher.enrich_lead(lead)      ← reads ENRICHMENT_PROVIDER env var
      |
      v
Canonical enrichment schema     ← 10 fields, same shape for every provider
      |
      v
generate_outreach_email(lead, company_intelligence)
      |
      v
AI prompt includes both lead + intelligence  ← better personalization
```

**Key rule:** No code outside `backend/services/enrichment/` ever imports
a concrete enricher class. The factory is the only entry point.

## Pipeline Integration

Enrichment happens in two places in `workflows.py`:

1. **`draft_message()`** — enriches the selected lead before calling
   `generate_outreach_email()`. This is the primary integration point.

2. **`send_outreach()`** — enriches again before regenerating the draft
   for sending (the draft is regenerated to ensure freshness).

If enrichment fails (e.g., ApolloEnricher stub, network error), the pipeline
continues without intelligence — graceful degradation. The AI still receives
the basic lead data as before.

## BaseEnricher

`backend/services/enrichment/base_enricher.py`

Every enricher implements:

| Method | Input | Returns |
|--------|-------|---------|
| `capabilities` | `@property` | Declares what the enricher can do |
| `health_check()` | — | `{"ok": bool}` |
| `enrich_company(company)` | Raw company dict | Canonical enrichment dict |
| `enrich_lead(lead)` | Canonical lead dict | Canonical enrichment dict |

## Canonical Enrichment Schema

Every enricher returns exactly this shape:

```python
{
    "company_summary": str,           # e.g. "Fork & Flame Grill is a Restaurant.
                                      #  Modern casual dining chain..."

    "recommended_pitch_angle": str,   # e.g. "Lead with how your solution addresses
                                      # 'high table turnover', which directly
                                      # relates to Fork & Flame Grill's current
                                      # challenges in the Restaurant space."

    "business_pain_summary": str,     # e.g. "Key pain points identified:
                                      #   - high table turnover
                                      #   - manual reservation management..."

    "technology_summary": str,        # e.g. "Toast POS, OpenTable, 7shifts"
                                      # or "No technology data available."

    "growth_summary": str,            # e.g. "Growth stage: Scaling Up |
                                      # Revenue: $10M-$50M | Team size: 200
                                      # (founded 2012)"

    "decision_context": str,          # e.g. "Decision maker role: General Manager"

    "buying_signal_summary": str,     # e.g. "Active buying signals detected:
                                      #   - Expanding to new locations
                                      #   - Recently hired operations director"

    "recent_events_summary": str,     # e.g. "Recent notable events:
                                      #   - Opened 3 new locations in Q4
                                      #   - Launched catering division"

    "qualification_reason": str,      # e.g. "Qualified because the decision maker
                                      # holds 'General Manager' role, operates in
                                      # Restaurant, faces relevant challenges
                                      # (high table turnover)."

    "confidence_score": int,          # 0-100, based on data completeness

    "provider": str,                  # enricher name (e.g. "synthetic")
}
```

## SyntheticEnricher

`backend/services/enrichment/synthetic_enricher.py`

Uses data **already present** in the canonical lead schema. No external
API calls. No AI calls. Simply transforms what the provider already returned
into structured intelligence.

### Data Sources

| Enrichment Field | Source in Lead Dict |
|-----------------|---------------------|
| `company_summary` | `company`, `company_industry`, `company_sub_industry`, `company_description`, `company_employees`, `company_locations` |
| `recommended_pitch_angle` | `pain_points`, `buying_signals`, `company`, `company_industry` |
| `business_pain_summary` | `pain_points`, `company_description` |
| `technology_summary` | `company_technology` |
| `growth_summary` | `company_growth_stage`, `company_revenue_band`, `company_employees`, `company_founded` |
| `decision_context` | `title` |
| `buying_signal_summary` | `buying_signals` |
| `recent_events_summary` | `recent_events` |
| `qualification_reason` | `title`, `company_industry`, `pain_points` |
| `confidence_score` | Data completeness across all fields |

### Performance

Sub-millisecond. Reads fields already in memory.

### Capabilities

```
supports_company_enrichment: True
supports_lead_enrichment:    True
uses_ai:                     False
```

## ApolloEnricher (Stub)

`backend/services/enrichment/apollo_enricher.py`

Not yet implemented. Returns `{"ok": False, "error": "stub"}`.

To implement:
1. In `enrich_lead()`, use Apollo's person enrichment endpoint to fetch
   additional company data beyond what the lead provider returned
2. Map to the canonical enrichment schema
3. Register in `enrichment_factory.py` — done

## EnrichmentFactory

`backend/services/enrichment/enrichment_factory.py`

| Function | Purpose |
|----------|---------|
| `get_enricher()` | Returns the configured enricher singleton (reads `ENRICHMENT_PROVIDER`) |
| `get_enricher_capabilities()` | Returns capabilities dict of the active enricher |

Supported `ENRICHMENT_PROVIDER` values:

| Value | Enricher | Status |
|-------|----------|--------|
| `synthetic` | `SyntheticEnricher` | Full implementation |
| `apollo` | `ApolloEnricher` | Stub |

An unknown value raises `ValueError` with a clear message listing supported
providers.

## Adding a New Enricher

### 1. Create the enricher class

```
backend/services/enrichment/
    linkedin_enricher.py
```

```python
from .base_enricher import BaseEnricher

class LinkedInEnricher(BaseEnricher):
    @property
    def capabilities(self) -> dict:
        return {
            "supports_company_enrichment": True,
            "supports_lead_enrichment": True,
            "uses_ai": False,
        }

    def health_check(self) -> dict:
        ...

    def enrich_company(self, company) -> dict:
        ...

    def enrich_lead(self, lead) -> dict:
        ...
```

### 2. Register in the factory

In `enrichment_factory.py`:

```python
elif name == "linkedin":
    from .linkedin_enricher import LinkedInEnricher
    enricher = LinkedInEnricher()
```

### 3. Set the environment variable

```
ENRICHMENT_PROVIDER=linkedin
```

Zero changes to `workflows.py`, `ai.py`, or any other file.

## How Enrichment Improves Personalization

Without enrichment, the AI receives:

```
First name: Sarah
Title: General Manager
Company: Fork & Flame Grill
Pain points: high table turnover, manual reservation management
```

The AI has no context about *why* this company matters. It guesses at the
pitch, often producing generic emails.

With enrichment, the AI receives everything above **plus**:

```json
{
  "company_summary": "Fork & Flame Grill is a Restaurant. Modern casual dining chain with 200 employees...",
  "recommended_pitch_angle": "Lead with how your solution addresses 'high table turnover'...",
  "business_pain_summary": "Key pain points identified: high table turnover, manual reservation...",
  "growth_summary": "Growth stage: Scaling Up | Revenue: $10M-$50M | Team size: 200",
  "buying_signal_summary": "Expanding to new locations",
  "qualification_reason": "Qualified because General Manager in Restaurant facing high table turnover..."
}
```

The AI can now:
- Reference specific growth signals
- Tailor the pitch to the qualification reason
- Speak to the company's specific technology stack
- Cite recent events as timely reasons to connect

Result: emails that sound researched, relevant, and personal.
