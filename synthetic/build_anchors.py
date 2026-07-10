#!/usr/bin/env python3
"""Generate anchor_companies.json – 100 high-quality synthetic anchor companies."""

import json, sys
from pathlib import Path

OUT = Path("data") / "anchor_companies.json"
companies = []
cid_counter = 0
lid_counter = 0

def cid():
    global cid_counter; cid_counter += 1
    return f"anchor_{cid_counter:03d}"

def lid():
    global lid_counter; lid_counter += 1
    return f"lead_{lid_counter:05d}"

def dm(name, title, dept, email, li_url, auth):
    return {"lead_id": lid(), "name": name, "title": title, "department": dept,
            "email": email, "linkedin_url": li_url, "buying_authority": auth}

def co(name, industry, sub, desc, website, city, country, employees, locations,
       founded, growth, revenue, bp, tech, pains, signals, dms):
    companies.append({"company_id": cid(), "name": name, "industry": industry,
        "sub_industry": sub, "description": desc, "website": website, "city": city,
        "country": country, "employees": employees, "locations": locations,
        "founded": founded, "growth_stage": growth, "revenue_band": revenue,
        "business_profile": bp, "technology": tech, "pain_points": pains,
        "buying_signals": signals, "decision_makers": dms})

# Load company data from JSON
data = json.loads(sys.stdin.read())
for d in data:
    co(**d)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(companies, f, indent=2, ensure_ascii=False)

print(f"Generated {len(companies)} anchor companies, {lid_counter} leads.")
