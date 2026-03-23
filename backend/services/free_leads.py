import urllib.parse

import requests
from bs4 import BeautifulSoup


def _normalize_lead(name: str, title: str, company: str, linkedin_url: str) -> dict:
    return {
        "name": name.strip(),
        "title": title.strip(),
        "company": company.strip(),
        "email": "",
        "linkedin_url": linkedin_url.strip(),
    }


def search_free_leads(query: str) -> list[dict]:
    print("[free_leads] query:", query)

    search_query = f"{query} site:linkedin.com/in"
    encoded_query = urllib.parse.quote(search_query)
    url = f"https://www.google.com/search?q={encoded_query}&num=10"
    headers = {
        "User-Agent": "Mozilla/5.0",
    }

    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results = []

    for result in soup.select("div.g"):
        link_tag = result.find("a", href=True)
        title_tag = result.find("h3")

        if not link_tag or not title_tag:
            continue

        link = link_tag["href"]
        title_text = title_tag.get_text(strip=True)

        if "linkedin.com/in/" not in link:
            continue

        parts = [part.strip() for part in title_text.split(" - ")]
        if len(parts) < 2:
            continue

        name = parts[0]
        title = parts[1]
        company = parts[2].replace("| LinkedIn", "").strip() if len(parts) >= 3 else ""

        results.append(_normalize_lead(name, title, company, link))
        if len(results) >= 5:
            break

    print("[free_leads] results:", results)

    if not results:
        raise Exception("No leads found. Try a different query.")

    return results
