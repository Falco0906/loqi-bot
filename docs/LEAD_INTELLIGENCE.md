# Lead Intelligence Layer

The lead intelligence layer generates structured sales intelligence
**after** enrichment and **before** draft generation. It answers the
question: *"Why was this lead selected, and what should we do about it?"*

This is **not** draft generation. It is **explainability**.

## Architecture

```
Provider
    ↓
Qualification + Ranking       ← commercial_qualifier embeds scores in lead
    ↓
Enrichment                     ← synthetic_enricher (company intelligence)
    ↓
Lead Intelligence              ← generate_lead_intelligence()  ← NEW
    ↓
Draft Generation               ← AI receives lead + enrichment + intelligence
```

## Pipeline Integration

Lead intelligence is generated in two places in `workflows.py`:

1. **`draft_message()`** — after enrichment, before AI draft generation
2. **`send_outreach()`** — same, before AI draft regeneration for sending

If generation fails (exception), the pipeline continues without it — graceful
degradation. The AI still receives lead data and enrichment.

## Canonical Schema

```python
{
    # How well this lead matches the ICP (0-100)
    # Normalized from commercial_qualifier's final_score (0-150+)
    "fit_score": int,

    # Confidence in the assessment (0-100)
    # Derived from enrichment confidence or fit_score as fallback
    "confidence": int,

    # 3-5 bullet-point reasons explaining why this lead was selected
    # Uses commercial qualification highlights, role match,
    # buyer fit score, authority score, pain points, buying signals
    "why_selected": [str, str, str],

    # What to pitch to this specific lead
    # Based on pain points, title, industry, company
    "recommended_pitch": str,

    # Does this person have buying power?
    # Based on title and buying_authority score
    # e.g. "Holds 'General Manager' role (85/100 authority) —
    #       has significant decision-making power"
    "decision_authority_summary": str,

    # Where is the buyer in their journey?
    # "awareness", "consideration", or "decision"
    # Inferred from buying signals, recent events, growth stage
    "buying_stage": str,

    # How time-sensitive is this opportunity?
    # "high", "medium", or "low"
    # Based on growth signals, expansion, hiring, funding events
    "urgency": str,

    # What business need does this company likely have?
    # Based on pain points, growth stage, industry
    # e.g. "At Scaling Up stage, the primary need is addressing
    #       'high table turnover'..."
    "estimated_business_need": str,

    # What objections might this lead raise?
    # Based on title (CEO-time, Manager-authority),
    # company size, industry
    # e.g. "Owner has full authority but is protective of
    #       time — make it highly relevant"
    "objection_risk": str,

    # Why is this person the right contact?
    # Combines buyer fit + authority score
    # e.g. "'General Manager' at Fork & Flame Grill combines
    #       strong buyer fit (25) with high authority (20)..."
    "best_contact_reason": str,

    # One-paragraph summary of everything
    # Combines name, title, company, fit score, stage, urgency,
    # pain points, and buying signals
    "summary": str,
}
```

## Data Sources

| Intelligence Field | Source in Lead Dict |
|---|---|
| `fit_score` | `commercial_score` → normalized 0-100 |
| `confidence` | Enrichment `confidence_score` or fit_score fallback |
| `why_selected` | `commercial_score_breakdown.highlights`, `title`, `company`, `buyer_score`, `authority_score`, `pain_points`, `buying_signals`, `company_industry` |
| `recommended_pitch` | `pain_points`, `title`, `company_industry`, `company` |
| `decision_authority_summary` | `title`, `buying_authority` |
| `buying_stage` | `buying_signals`, `recent_events`, `company_growth_stage` |
| `urgency` | `buying_signals`, `recent_events`, `company_growth_stage` |
| `estimated_business_need` | `pain_points`, `company_growth_stage`, `company_industry` |
| `objection_risk` | `title`, `company`, `company_industry` |
| `best_contact_reason` | `title`, `company`, `buyer_score`, `authority_score` |
| `summary` | All of the above |

## Deterministic Design

Lead intelligence is generated **without any LLM calls**. Every field is
derived from data already present in the lead dict and enrichment dict
using deterministic heuristics:

- **Title matching** — maps titles to authority levels (CEO > VP > Director > Manager)
- **Keyword scoring** — buying signals, recent events, growth stage → stage/urgency
- **Composition** — why_selected is built from qualification highlights + role/pain/signal matches
- **Formatting** — summaries and descriptions are assembled from template strings

This means:
- No additional latency from AI calls
- No API costs
- Deterministic output (same input → same intelligence)
- Easy to debug and extend

## API Exposure

Lead intelligence is returned from the `draft_message` and `send_outreach`
workflow endpoints as a `lead_intelligence` key in the response dict.

The frontend can use these fields to render intelligence cards:

```typescript
interface LeadIntelligence {
    fit_score: number;
    confidence: number;
    why_selected: string[];
    recommended_pitch: string;
    decision_authority_summary: string;
    buying_stage: string;
    urgency: string;
    estimated_business_need: string;
    objection_risk: string;
    best_contact_reason: string;
    summary: string;
}
```

Future frontend cards can display:
- Fit score as a progress bar
- Why-selected as bullet list
- Buying stage as a badge
- Urgency as a colored indicator
- Objection risk as a warning
- Decision authority as a profile summary

## How Intelligence Improves the AI Draft

Without lead intelligence:

> "Hi Sarah, I noticed Fork & Flame Grill is a restaurant. We can help
> with your operations."

The AI has no context about *why* this lead matters. It guesses.

With lead intelligence, the AI receives:

```
Fit score: 85/100
Urgency: high
Why selected: Strong buyer fit, expanding to new locations,
              relevant pain: high table turnover
Objection risk: Owner is protective of time
```

The AI can now write:

> "Sarah, I see Fork & Flame is expanding — congrats on the 3 new
> locations. As you scale, I imagine managing reservations across
> 15 locations gets complex. Let me share how we help..."

The email references the specific buying signal, names the pain point,
and positions the solution against the growth context — all without
the AI guessing.

## File Location

```
backend/services/intelligence/
    __init__.py              # Exports generate_lead_intelligence
    lead_intelligence.py     # All deterministic logic (~280 lines)
```
