import os

from serpapi import GoogleSearch


def search_free_leads(query: str) -> list[dict]:
    print("[free_leads] query:", query)

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise Exception("Missing SERPAPI_API_KEY")

    params = {
        "q": f"{query} site:linkedin.com/in",
        "num": 10,
        "api_key": api_key,
    }

    search = GoogleSearch(params)
    results = search.get_dict()

    leads = []

    for result in results.get("organic_results", []):
        title = result.get("title", "")
        link = result.get("link", "")

        if "linkedin.com/in/" not in link:
            continue

        parts = title.split(" - ")

        if len(parts) < 2:
            continue

        name = parts[0].strip()
        role = parts[1].strip()

        company = ""
        if len(parts) >= 3:
            company = parts[2].replace("| LinkedIn", "").strip()

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

    print("[free_leads] results:", leads)

    if not leads:
        raise Exception("No leads found. Try a more specific query.")

    return leads
