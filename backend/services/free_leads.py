import os
import re

from serpapi import GoogleSearch


def build_search_query(query: str) -> str:
    return (
        '("HR Manager" OR "Head of HR" OR "People Operations" OR "Talent Acquisition") '
        f"{query} site:linkedin.com/in"
    )


def clean_text(text: str) -> str:
    return text.replace("...", "").replace("|", "").strip()


def extract_company(title: str, snippet: str) -> str:
    title = title.replace("| LinkedIn", "").strip()

    parts = [part.strip() for part in title.split(" - ") if part.strip()]

    if len(parts) >= 3:
        return clean_text(parts[2])

    match = re.search(r"at ([A-Za-z0-9&.\- ]+)", title)
    if match:
        return clean_text(match.group(1))

    if snippet:
        match = re.search(r"at ([A-Za-z0-9&.\- ]+)", snippet)
        if match:
            return clean_text(match.group(1))

    return ""


def search_free_leads(query: str) -> list[dict]:
    print("[free_leads] query:", query)

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise Exception("Missing SERPAPI_API_KEY")

    built_query = build_search_query(query)
    print("[free_leads] built_query:", built_query)

    params = {
        "engine": "google",
        "q": built_query,
        "num": 10,
        "api_key": api_key,
    }

    search = GoogleSearch(params)
    results = search.get_dict()

    leads = []

    for result in results.get("organic_results", []):
        title = result.get("title", "")
        snippet = result.get("snippet", "")
        link = result.get("link", "")

        if "linkedin.com/in/" not in link:
            continue

        title = title.replace("| LinkedIn", "").strip()
        parts = [part.strip() for part in title.split(" - ") if part.strip()]

        name = parts[0] if len(parts) > 0 else ""
        role = parts[1] if len(parts) > 1 else ""
        role = clean_text(role)
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

    print("[free_leads] leads:", leads)

    if not leads:
        raise Exception("No leads found. Try a more specific query.")

    return leads
