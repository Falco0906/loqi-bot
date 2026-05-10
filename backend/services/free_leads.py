import os
import re


class SerpAPIError(Exception):
    """Raised when SerpAPI fails and should not return fake data"""
    pass


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
        seen_names = set()

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
                continue
                
            if name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
                
            role = clean_text(role)
            if not company:
                company = extract_company(title, snippet)

            if not name or not role:
                continue

            leads.append(
                {
                    "name": name,
                    "title": role,
                    "company": company,
                    "email": "",
                    "linkedin_url": link,
                }
            )

            if len(leads) >= 5:
                break

        print(f"[free_leads] leads extracted: {len(leads)}")

        if not leads:
            print("[free_leads] ERROR: No leads found for query")
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