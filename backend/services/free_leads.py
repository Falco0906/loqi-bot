import os
import re


class SerpAPIError(Exception):
    """Raised when SerpAPI fails and should not return fake data"""
    pass


def _log_quality(lead: dict, passed: bool, reason: str) -> None:
    if not passed:
        print(f"[free_leads] REJECTED: {lead.get('name', 'N/A')} @ {lead.get('company', 'N/A')} — {reason}")


def _is_valid_name(name: str) -> bool:
    """Check if name is valid (not a junk pattern)."""
    if not name or len(name.strip()) < 2:
        return False

    name_lower = name.lower()
    junk_patterns = [
        r"^actually\s",
        r"^the\s",
        r"^\d+",
        r"^linkedin",
        r"profile$",
        r"^view\s",
        r"^my\s",
        r"^see\s",
        r"^more\s",
    ]
    for pattern in junk_patterns:
        if re.search(pattern, name_lower):
            return False

    if name_lower in ["unknown", "none", "n/a", "na", ".", "-", ""]:
        return False

    if len(name) > 60:
        return False

    return True


def _is_valid_title(title: str) -> bool:
    """Check if title is valid and plausible."""
    if not title or len(title.strip()) < 2:
        return False

    title_lower = title.lower()
    junk_titles = [
        "unknown",
        "none",
        "n/a",
        "na",
        "linkedin",
        "...",
        "placeholder",
    ]
    for junk in junk_titles:
        if junk in title_lower:
            return False

    if len(title) > 100:
        return False

    return True


def _is_valid_company(company: str) -> bool:
    """Check if company is valid and not a junk value."""
    if not company or len(company.strip()) < 1:
        return False

    company_lower = company.lower()
    junk_companies = [
        "unknown",
        "unknown company",
        "none",
        "n/a",
        "",
        "linkedin",
        "linkedin.com",
        "...",
    ]
    for junk in junk_companies:
        if junk in company_lower:
            return False

    if len(company) > 80:
        return False

    return True


def _is_service_provider_company(company: str, title: str) -> bool:
    """Check if company is a service provider/vendor (semantic drift prevention)."""
    company_lower = company.lower()
    title_lower = title.lower()

    vendor_keywords = [
        "agency",
        "consulting",
        "solutions",
        "services",
        "digital",
        "marketing",
        "creative",
        "software",
        "technology",
        "tech",
        "dev",
        "design",
        "web",
        "platform",
        "automation",
        "saas",
        "cloud",
    ]

    provider_title_keywords = [
        "developer",
        "designer",
        "consultant",
        "freelancer",
        "agency",
        "writer",
        "coach",
    ]

    has_vendor_company = any(kw in company_lower for kw in vendor_keywords)
    has_provider_title = any(kw in title_lower for kw in provider_title_keywords)

    if has_vendor_company and has_provider_title:
        return True

    service_patterns = [
        r"(agency|consulting|solutions)\s+for\s",
        r"(marketing|creative|digital)\s+(agency|firm)",
        r"(software|tech|ai)\s+(company|startup|provider)",
        r"(restaurant|hotel|hospitality)\s+(tech|saas|software)",
    ]
    for pattern in service_patterns:
        if re.search(pattern, company_lower):
            return True

    return False


def build_search_query(query: str) -> str:
    """Build a proper LinkedIn people search query"""
    return f'site:linkedin.com/in "{query}"'


def clean_text(text: str) -> str:
    return text.replace("...", "").replace("|", "").strip()


def extract_company(title: str, snippet: str) -> str:
    title = title.replace("| LinkedIn", "").strip()

    parts = [part.strip() for part in title.split(" - ") if part.strip()]

    if len(parts) >= 3:
        return clean_text(parts[2])

    match = re.search(r"at\s+([A-Za-z0-9&.\- ]+?)(?:\s*[-|]|$)", title, re.IGNORECASE)
    if match:
        return clean_text(match.group(1).strip())

    match = re.search(r",\s*([A-Z][A-Za-z0-9&\- ]+?)(?:\s*$|\s*[-|])", title)
    if match:
        return clean_text(match.group(1).strip())

    if snippet:
        match = re.search(r"at\s+([A-Za-z0-9&.\- ]+?)(?:\s*[-|]|$)", snippet, re.IGNORECASE)
        if match:
            return clean_text(match.group(1).strip())

    return ""


def _validate_lead(lead: dict) -> tuple[bool, str]:
    """Validate a single lead. Returns (is_valid, reason)."""
    name = lead.get("name", "").strip()
    title = lead.get("title", "").strip()
    company = lead.get("company", "").strip()
    linkedin_url = lead.get("linkedin_url", "").strip()

    if not name:
        return False, "empty_name"

    if not _is_valid_name(name):
        return False, f"invalid_name:{name[:30]}"

    if not title:
        return False, "empty_title"

    if not _is_valid_title(title):
        return False, f"invalid_title:{title[:30]}"

    if not company:
        return False, "empty_company"

    if not _is_valid_company(company):
        return False, f"invalid_company:{company[:30]}"

    if not linkedin_url or "linkedin.com/in/" not in linkedin_url:
        return False, "missing_linkedin_url"

    if _is_service_provider_company(company, title):
        return False, "service_provider_company"

    return True, "valid"


def search_free_leads(query: str) -> list[dict]:
    print(f"[free_leads] query: {query}")

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        print("[free_leads] ERROR: SERPAPI_API_KEY not configured")
        raise SerpAPIError("SERPAPI_API_KEY not configured. Lead search unavailable.")

    try:
        from serpapi import Client
        print("[free_leads] Using serpapi package (Client API)")
    except ImportError as e:
        print(f"[free_leads] ERROR: serpapi package not installed: {e}")
        raise SerpAPIError(f"serpapi package not installed: {e}. Lead search unavailable.")

    built_query = build_search_query(query)
    print(f"[free_leads] search_query: {built_query}")

    try:
        client = Client(api_key=api_key)
        results = client.search(q=built_query, engine="google", num=15)

        print(f"[free_leads] API response received, keys: {list(results.keys())}")

        if hasattr(results, 'get') and results.get("error"):
            error_msg = results.get("error", "Unknown SerpAPI error")
            print(f"[free_leads] API error: {error_msg}")
            raise SerpAPIError(f"SerpAPI error: {error_msg}")

        organic_results = results.get("organic_results", []) if hasattr(results, 'get') else []
        print(f"[free_leads] organic_results count: {len(organic_results)}")

        leads = []
        seen_urls = set()
        rejected = {"empty_name": 0, "invalid_name": 0, "empty_title": 0, "invalid_title": 0,
                    "empty_company": 0, "invalid_company": 0, "missing_linkedin_url": 0, "service_provider_company": 0}

        for result in organic_results:
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            link = result.get("link", "")

            if "linkedin.com/in/" not in link:
                continue

            title = title.replace("| LinkedIn", "").strip()

            company = ""

            if " - " in title:
                parts = title.split(" - ", 1)
                name = parts[0].strip()
                role_with_company = parts[1].strip() if len(parts) > 1 else ""

                if " at " in role_with_company.lower():
                    role_parts = role_with_company.rsplit(" at ", 1)
                    role = role_parts[0].strip()
                    company = role_parts[1].strip()
                elif ", " in role_with_company:
                    comma_pos = role_with_company.rfind(", ")
                    if comma_pos > 0:
                        potential_company = role_with_company[comma_pos+2:].strip()
                        if potential_company and len(potential_company) < 40:
                            company = potential_company
                            role = role_with_company[:comma_pos].strip()
                        else:
                            role = role_with_company
                    else:
                        role = role_with_company
                else:
                    role = role_with_company
                    company = extract_company(title, snippet)
            else:
                name = title
                role = ""
                company = extract_company(title, snippet)

            if not name:
                rejected["empty_name"] += 1
                continue

            if name.lower() in seen_names:
                continue
            seen_names.add(name.lower())

            role = clean_text(role)
            if not company:
                company = extract_company(title, snippet)

            if not name or not role:
                if not name:
                    rejected["empty_name"] += 1
                elif not role:
                    rejected["empty_title"] += 1
                continue

            raw_lead = {
                "name": name,
                "title": role,
                "company": company,
                "email": "",
                "linkedin_url": link,
            }

            valid, reason = _validate_lead(raw_lead)
            if not valid:
                rejected[reason] = rejected.get(reason, 0) + 1
                _log_quality(raw_lead, False, reason)
                continue

            leads.append(raw_lead)

            if len(leads) >= 5:
                break

        print(f"[free_leads] leads extracted: {len(leads)} (rejected: {sum(rejected.values())})")
        print(f"[free_leads] rejection breakdown: {rejected}")

        if not leads:
            print("[free_leads] ERROR: No quality leads found for query")
            raise SerpAPIError("No leads found for this query. Try a different target.")

        print(f"[free_leads] SUCCESS: {len(leads)} leads returned")
        return leads

    except SerpAPIError:
        raise
    except Exception as e:
        error_msg = str(e)
        print(f"[free_leads] EXCEPTION: {error_msg}")

        lower_error = error_msg.lower()
        if "api_key" in lower_error or "unauthorized" in lower_error or "invalid" in lower_error:
            raise SerpAPIError("SerpAPI API key is invalid")
        if "quota" in lower_error or "limit" in lower_error:
            raise SerpAPIError("SerpAPI quota exceeded")
        if "timeout" in lower_error or "timed out" in lower_error:
            raise SerpAPIError("SerpAPI request timed out")
        raise SerpAPIError(f"SerpAPI request failed: {error_msg}")