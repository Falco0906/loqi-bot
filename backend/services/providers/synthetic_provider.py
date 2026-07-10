import json
import re
import time
from pathlib import Path
from typing import Any

from .base_provider import BaseProvider, ProviderError

_INDUSTRY_MAP: dict[str, str] = {
    "restaurants": "Restaurant",
    "restaurant": "Restaurant",
    "cafe": "Cafe",
    "hospitality": "Hotel",
    "hotels": "Hotel",
    "hotel": "Hotel",
    "healthcare": "Healthcare",
    "dental": "Dental Clinic",
    "dentist": "Dental Clinic",
    "wellness": "Gym",
    "gym": "Gym",
    "fitness": "Gym",
    "saas": "SaaS",
    "startups": None,
    "startup": None,
    "tech": "SaaS",
    "real estate": "Real Estate",
    "realestate": "Real Estate",
    "finance": "Accounting Firm",
    "accounting": "Accounting Firm",
    "legal": "Law Firm",
    "law firm": "Law Firm",
    "education": "Education",
    "retail": "Retail",
    "manufacturing": "Manufacturing",
    "construction": "Construction",
    "logistics": "Logistics",
    "agencies": "Marketing Agency",
    "marketing agency": "Marketing Agency",
    "consulting": None,
    "automotive": "Automotive",
    "ecommerce": "E-commerce",
    "e-commerce": "E-commerce",
    "furniture": "Furniture",
    "travel agency": "Travel Agency",
    "travel": "Travel Agency",
    "accounting firm": "Accounting Firm",
    "auto": "Automotive",
    "automobile": "Automotive",
}


def _log(message: str) -> None:
    print(f"[synthetic_provider] {message}")


def _find_data_path() -> Path:
    """Find synthetic/output/companies.json relative to the project root."""
    candidates = [
        Path(__file__).parent.parent.parent.parent / "synthetic" / "output" / "companies.json",
        Path.cwd() / "synthetic" / "output" / "companies.json",
        Path.cwd() / "companies.json",
    ]
    for path in candidates:
        if path.exists():
            return path.resolve()
    raise ProviderError(
        "Synthetic data file not found. Run `python3 generator.py --companies 5000` "
        "in the synthetic/ directory first."
    )


def _normalize_industry(icp_industry: str) -> str | None:
    """Map an ICP buyer_industry string to a synthetic data industry name."""
    key = icp_industry.strip().lower()
    if key in _INDUSTRY_MAP:
        return _INDUSTRY_MAP[key]
    # Fallback: case-insensitive direct match
    for syn_ind in _INDUSTRY_MAP.values():
        if syn_ind and syn_ind.lower() == key:
            return syn_ind
    # Fallback: substring match (e.g. "restaurant" in "Restaurant")
    return None


def _title_matches_role(title: str, buyer_roles: list[str]) -> int:
    """Score how well a title matches buyer roles.

    Returns match count (number of buyer roles that share at least one
    significant keyword with the title).
    """
    if not buyer_roles or not title:
        return 0

    title_lower = title.lower()
    title_words = {w for w in re.findall(r"[a-z0-9]+", title_lower) if len(w) >= 3}

    matches = 0
    for role in buyer_roles:
        role_words = [w for w in re.findall(r"[a-z0-9]+", role.lower()) if len(w) >= 3]
        if not role_words:
            # Single-word roles like CEO, COO — check exact presence
            if role.lower() in title_lower:
                matches += 1
            continue
        if any(w in title_words for w in role_words):
            matches += 1
    return matches


def _is_excluded(title: str, excluded_roles: list[str]) -> bool:
    """Check if a title matches any excluded role pattern."""
    if not excluded_roles or not title:
        return False
    title_lower = title.lower()
    for excluded in excluded_roles:
        if excluded.lower() in title_lower:
            return True
    return False


def _compute_first_name(name: str) -> str:
    parts = name.split()
    return parts[0] if parts else name


def _compute_last_name(name: str) -> str:
    parts = name.split()
    return parts[-1] if len(parts) > 1 else ""


def _flatten_lead(decision_maker: dict, company: dict) -> dict:
    """Flatten a decision maker + company pair into the canonical lead schema."""
    name = (decision_maker.get("name") or "").strip()
    cid = (company.get("company_id") or "").strip()
    return {
        "lead_id": (decision_maker.get("lead_id") or "").strip(),
        "company_id": cid,
        "first_name": _compute_first_name(name),
        "last_name": _compute_last_name(name),
        "name": name or "Unknown",
        "title": (decision_maker.get("title") or "Professional").strip(),
        "department": (decision_maker.get("department") or "").strip(),
        "email": (decision_maker.get("email") or "").strip(),
        "linkedin_url": (decision_maker.get("linkedin_url") or "").strip(),
        "buying_authority": decision_maker.get("buying_authority", 50),
        "company": (company.get("name") or "Unknown Company").strip(),
        "company_industry": (company.get("industry") or "").strip(),
        "company_sub_industry": (company.get("sub_industry") or "").strip(),
        "company_description": (company.get("description") or "").strip(),
        "company_website": (company.get("website") or "").strip(),
        "company_city": (company.get("city") or "").strip(),
        "company_country": (company.get("country") or "").strip(),
        "company_employees": company.get("employees", 0),
        "company_locations": company.get("locations", 0),
        "company_founded": company.get("founded", 0),
        "company_growth_stage": (company.get("growth_stage") or "").strip(),
        "company_revenue_band": (company.get("revenue_band") or "").strip(),
        "company_technology": company.get("technology") or {},
        "pain_points": company.get("pain_points") or [],
        "buying_signals": company.get("buying_signals") or [],
        "recent_events": company.get("recent_events") or [],
        "provider": "synthetic",
    }


class _DataStore:
    """Immutable in-memory index of synthetic companies.

    Loaded once at module level and reused across all requests.
    """

    def __init__(self, data_path: Path):
        self.companies: list[dict] = []
        self.companies_by_industry: dict[str, list[dict]] = {}
        self.companies_by_sub_industry: dict[str, list[dict]] = {}
        self.companies_by_id: dict[str, dict] = {}
        self.leads_by_id: dict[str, dict] = {}
        self.companies_by_name_lower: dict[str, dict] = {}
        self.all_leads: list[dict] = []

        start = time.time()
        self._load(data_path)
        elapsed = time.time() - start
        _log(f"Loaded {len(self.companies)} companies, {len(self.all_leads)} leads in {elapsed*1000:.1f}ms")

    def _load(self, data_path: Path) -> None:
        with open(data_path) as f:
            raw = json.load(f)

        self.companies = raw

        for company in raw:
            cid = company.get("company_id")
            ind = (company.get("industry") or "").lower()
            sub = (company.get("sub_industry") or "").lower()
            name_lower = (company.get("name") or "").lower()

            if ind:
                self.companies_by_industry.setdefault(ind, []).append(company)
            if sub:
                self.companies_by_sub_industry.setdefault(sub, []).append(company)
            if cid:
                self.companies_by_id[cid] = company
            if name_lower:
                self.companies_by_name_lower[name_lower] = company

            for dm in company.get("decision_makers") or []:
                flat = _flatten_lead(dm, company)
                self.all_leads.append(flat)
                lid = dm.get("lead_id")
                if lid:
                    self.leads_by_id[lid] = flat


_DATA: _DataStore | None = None


def _get_data() -> _DataStore:
    global _DATA
    if _DATA is None:
        path = _find_data_path()
        _DATA = _DataStore(path)
    return _DATA


class SyntheticProvider(BaseProvider):
    """Lead provider backed by the synthetic companies dataset.

    Loads companies.json into memory once.
    Searches by industry, role keywords, and content fields.
    Returns the canonical lead schema — identical to what ApolloProvider will return.
    """

    def __init__(self) -> None:
        self._data = _get_data()
        _log("SyntheticProvider ready")

    @property
    def capabilities(self) -> dict:
        return {
            "supports_email": True,
            "supports_company_lookup": True,
            "supports_enrichment": False,
            "supports_live_search": False,
        }

    def health_check(self) -> dict:
        ds = self._data
        return {
            "ok": True,
            "companies": len(ds.companies),
            "leads": len(ds.all_leads),
            "industries": list(ds.companies_by_industry.keys()),
        }

    def search_leads(
        self,
        icp: dict,
        search_expansion: dict,
        limit: int = 20,
    ) -> dict:
        start = time.time()

        buyer_industries: list[str] = icp.get("buyer_industries") or []
        buyer_roles: list[str] = icp.get("buyer_roles") or []
        excluded_roles: list[str] = icp.get("excluded_roles") or []
        keywords: list[str] = icp.get("keywords") or []

        # Normalize industries from ICP to synthetic names
        target_industries: set[str] = set()
        for ind in buyer_industries:
            mapped = _normalize_industry(ind)
            if mapped:
                target_industries.add(mapped.lower())

        # Collect matching company IDs
        ds = self._data
        matched_cids: set[str] = set()

        if target_industries:
            for syn_ind, companies in ds.companies_by_industry.items():
                if syn_ind in target_industries:
                    for c in companies:
                        matched_cids.add(c.get("company_id"))
        else:
            # No industry filter — search all companies
            for c in ds.companies:
                matched_cids.add(c.get("company_id"))

        # Match and score
        scored: list[tuple[float, dict]] = []

        for lead in ds.all_leads:
            cid = lead.get("company_id") or ""
            if cid and cid not in matched_cids:
                continue

            title = lead.get("title") or ""
            if _is_excluded(title, excluded_roles):
                continue

            role_score = _title_matches_role(title, buyer_roles)
            keyword_score = self._score_keywords(lead, keywords)

            total = float(role_score * 10 + keyword_score * 2 + (lead.get("buying_authority") or 0) * 0.1)
            scored.append((total, lead))

        scored.sort(key=lambda x: x[0], reverse=True)

        leads = [lead for _, lead in scored[:limit]]
        elapsed = time.time() - start

        _log(
            f"SyntheticProvider search: "
            f"industries={buyer_industries}, "
            f"roles={len(buyer_roles)}, "
            f"matched={len(scored)} candidates, "
            f"returned={len(leads)}, "
            f"time={elapsed*1000:.1f}ms"
        )

        return {
            "ok": True,
            "provider": "synthetic",
            "leads": leads,
            "error": None,
            "stats": {
                "total_found": len(scored),
                "returned": len(leads),
                "search_time_ms": round(elapsed * 1000, 1),
            },
        }

    def _score_keywords(self, lead: dict, keywords: list[str]) -> int:
        """Score a lead by keyword matches in description, pain points, etc."""
        if not keywords:
            return 0

        text_fields = " ".join([
            lead.get("company_description") or "",
            " ".join(lead.get("pain_points") or []),
            " ".join(lead.get("buying_signals") or []),
            " ".join(lead.get("recent_events") or []),
            lead.get("company") or "",
            lead.get("company_industry") or "",
        ]).lower()

        score = 0
        for kw in keywords:
            for word in kw.lower().split():
                if len(word) >= 3 and word in text_fields:
                    score += 1
        return score

    def get_lead(self, lead_id: str) -> dict | None:
        return self._data.leads_by_id.get(lead_id)

    def get_company(self, company_id: str) -> dict | None:
        return self._data.companies_by_id.get(company_id)
