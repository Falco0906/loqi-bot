# Loqi Provider Architecture

The provider layer isolates Loqi's lead retrieval logic from any specific lead source. Changing providers requires zero changes outside `backend/services/providers/`.

---

## Architecture

```
workflows.py / conversation_engine.py
            |
            v
      lead_provider.py               ← Orchestrates: ICP extraction,
            |                           search expansion, provider call,
            v                           commercial qualification
    provider_factory.py              ← Reads LEAD_PROVIDER env var
            |
            v
    +-----+------+------+
    |     |      |      |
   synthetic  apollo  (future)
```

**Key rule:** No code outside `backend/services/providers/` ever imports a concrete provider class. The factory is the only entry point.

---

## BaseProvider

`backend/services/providers/base_provider.py`

Abstract interface every provider must implement:

| Member | Type | Returns |
|--------|------|---------|
| `capabilities` | `@property` | `{"supports_email": bool, "supports_company_lookup": bool, "supports_enrichment": bool, "supports_live_search": bool}` |
| `health_check()` | method | `{"ok": bool}` |
| `search_leads(icp, search_expansion, limit)` | method | `{"ok", "provider", "leads", "error", "stats"}` |
| `get_lead(lead_id)` | method | Canonical lead dict or None |
| `get_company(company_id)` | method | Company dict or None |

### Capabilities

The `capabilities` property lets the UI and workflow adapt automatically to whatever provider is plugged in:

| Flag | Meaning |
|------|---------|
| `supports_email` | Provider can return email addresses |
| `supports_company_lookup` | `get_company()` returns rich metadata |
| `supports_enrichment` | Provider can do on-the-fly enrichment |
| `supports_live_search` | Provider makes live API calls (vs static dataset) |

Call `get_provider_capabilities()` from anywhere — no need to import a concrete class.

### Canonical Lead Schema

Every provider returns exactly this schema. Downstream code never knows which provider produced a lead.

```python
{
    "lead_id": str,
    "first_name": str,
    "last_name": str,
    "name": str,
    "title": str,
    "department": str,
    "email": str,
    "linkedin_url": str,
    "buying_authority": int,

    "company": str,
    "company_industry": str,
    "company_sub_industry": str,
    "company_description": str,
    "company_website": str,
    "company_city": str,
    "company_country": str,
    "company_employees": int,
    "company_locations": int,
    "company_founded": int,
    "company_growth_stage": str,
    "company_revenue_band": str,
    "company_technology": dict,

    "pain_points": list[str],
    "buying_signals": list[str],
    "recent_events": list[str],

    "provider": str,
}
```

The `company` field matches the old `lead.get("company")` used by workflows. The `pain_points` field matches `lead.get("pain_points")` in the AI draft generator.

---

## ProviderFactory

`backend/services/providers/provider_factory.py`

Single function `get_provider()`:

1. Reads `LEAD_PROVIDER` from environment
2. Caches the provider instance (singleton per name)
3. Returns the provider

Supported values:

| Value | Provider | Status |
|-------|----------|--------|
| `synthetic` | `SyntheticProvider` | Full implementation |
| `apollo` | `ApolloProvider` | Stub — returns `{"ok": False}` |

An unknown value raises `ValueError` with a clear message listing supported providers.

---

## SyntheticProvider

`backend/services/providers/synthetic_provider.py`

### Data Loading

- Reads `synthetic/output/companies.json`
- Loaded **once** at module level (not per request)
- Built on first `SyntheticProvider()` construction
- Data path auto-detected relative to project root

### In-Memory Indexes

| Index | Key | Value |
|-------|-----|-------|
| `companies_by_industry` | lowercased industry name | List of company dicts |
| `companies_by_sub_industry` | lowercased sub_industry | List of company dicts |
| `companies_by_id` | company_id string | Company dict |
| `companies_by_name_lower` | lowercased company name | Company dict |
| `leads_by_id` | lead_id string | Flat lead dict |

### Search Algorithm

```
1. INDUSTRY FILTER
   Buyer industries from ICP are normalized to synthetic
   industry names via _INDUSTRY_MAP.
   
   Companies outside target industries are excluded.
   If no buyer_industries specified, all companies are candidates.

2. EXCLUDED ROLE FILTER
   Decision makers whose title matches any excluded_role are skipped.

3. ROLE MATCHING
   For each buyer_role, significant keywords (len >= 3) are
   extracted. A title matches if at least one keyword from a
   buyer_role appears in it.

4. KEYWORD SCORING
   Additional score from ICP keywords matching company
   description, pain_points, buying_signals, recent_events,
   company name, and industry.

5. SORT + LIMIT
   Score = role_matches * 10 + keyword_matches * 2 + buying_authority * 0.1
   Sorted descending. Top `limit` returned.
```

### Industry Normalization

The ICP extractor returns normalized industry names like "restaurants", "healthcare", "dental". The synthetic data uses display names like "Restaurant", "Healthcare", "Dental Clinic". `_INDUSTRY_MAP` handles the mapping:

| ICP Industry | Synthetic Industry |
|---|---|
| restaurants, restaurant, cafe | Restaurant, Cafe |
| hospitality, hotel, hotels | Hotel |
| dental, dentist | Dental Clinic |
| legal, law firm | Law Firm |
| saas, tech | SaaS |
| [see full map in source] | ... |

### Performance

5,000 companies, 22,502 decision makers: **< 10ms** per search.

---

## ApolloProvider (Stub)

`backend/services/providers/apollo_provider.py`

Not yet implemented. All methods return `{"ok": False, "error": "stub"}`. Exposes capabilities declaring `supports_email`, `supports_enrichment`, `supports_live_search` — these take effect once the real implementation lands.

To implement ApolloProvider:

1. Inherit from `BaseProvider`
2. Implement `health_check()` using `APOLLO_API_KEY`
3. Implement `search_leads()` using Apollo's `mixed_people/search` endpoint
4. Map Apollo's response to the canonical lead schema
5. Implement `get_lead()` and `get_company()` via Apollo's person/company endpoints
6. Done — no changes needed anywhere else in Loqi

---

## How to Add a New Provider

### 1. Create the provider class

```
backend/services/providers/
    my_provider.py
```

```python
from .base_provider import BaseProvider

class MyProvider(BaseProvider):
    def __init__(self):
        # Initialize API clients, load data, etc.
        pass

    def health_check(self) -> dict:
        ...

    def search_leads(self, icp, search_expansion, limit=20) -> dict:
        ...

    def get_lead(self, lead_id) -> dict | None:
        ...

    def get_company(self, company_id) -> dict | None:
        ...
```

### 2. Register in the factory

In `provider_factory.py`:

```python
if name == "my_provider":
    from .my_provider import MyProvider
    provider = MyProvider()
```

### 3. Set the environment variable

```
LEAD_PROVIDER=my_provider
```

That's it. `lead_provider.py`, `workflows.py`, `conversation_engine.py` — zero changes.


