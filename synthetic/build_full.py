#!/usr/bin/env python3
"""Generate all 100 anchor companies with full metadata."""
import json, sys
from pathlib import Path

OUT = Path("data") / "anchor_companies.json"
OUT.parent.mkdir(exist_ok=True)

cid = 0
lid = 0

def L():
    global lid; lid += 1; return f"lead_{lid:05d}"

def M(name, title, dept, email, li_url, auth):
    return {"lead_id": L(), "name": name, "title": title, "department": dept,
            "email": email, "linkedin_url": li_url, "buying_authority": auth}

def C(name, industry, sub, desc, website, city, country, employees, locations,
      founded, growth, revenue, bp, tech, pains, signals, dms):
    global cid; cid += 1
    return {"company_id": f"anchor_{cid:03d}", "name": name, "industry": industry,
            "sub_industry": sub, "description": desc, "website": website, "city": city,
            "country": country, "employees": employees, "locations": locations,
            "founded": founded, "growth_stage": growth, "revenue_band": revenue,
            "business_profile": bp, "technology": tech, "pain_points": pains,
            "buying_signals": signals, "decision_makers": dms}

data = []

data.append(C(
  "Blue Orchid Coffee Roasters","Cafe","Specialty Coffee",
  "Blue Orchid Coffee Roasters is a third-wave specialty coffee company sourcing single-origin beans directly from growers in Ethiopia, Colombia, and Guatemala. They operate artisanal cafes focused on pour-over and espresso craft, with a wholesale roasting program supplying 40+ local offices and restaurants. Known for their seasonal tasting flights and barista education workshops, they have built a loyal following among coffee enthusiasts in the Pacific Northwest.",
  "https://blueorchidcoffee.com","Portland","USA",28,3,2016,"Growing","$1M-$5M",
  {"franchise":False,"expanding_locations":True,"hiring":True,"online_presence":"strong","delivery":True,"multi_location":True},
  {"crm":"HubSpot","website_platform":"Squarespace","marketing_platform":"Mailchimp","automation_level":"medium"},
  ["Roast profile consistency across batches","Wholesale order management","Barista retention and training","Seasonal menu planning inventory"],
  ["Opening two new locations in Seattle","Hiring a Head Roaster","Expanding wholesale distribution to 60+ accounts"],
  [M("Elena Vasquez","Founder & CEO","Executive","elena@blueorchidcoffee.com","https://linkedin.com/in/elenavasquez",100),
   M("Marcus Chen","Head Roaster & Operations","Operations","marcus@blueorchidcoffee.com","https://linkedin.com/in/marcuschen",85),
   M("Sophie Tran","Retail Manager","Retail","sophie@blueorchidcoffee.com","https://linkedin.com/in/sophietran",75),
   M("Jake Morrison","Wholesale Director","Sales","jake@blueorchidcoffee.com","https://linkedin.com/in/jakemorrison",80)]))

data.append(C(
  "Canopy Brew Collective","Cafe","Coffee Shop Chain",
  "Canopy Brew Collective runs a network of plant-filled, co-working-friendly cafes across Austin and Denver. Each location features high-speed WiFi, meeting pods, and locally sourced pastries. They position themselves as a third place for remote workers and freelancers, with membership plans that include unlimited drip coffee and dedicated desk space. Their locations frequently host tech meetups and networking events.",
  "https://canopybrew.com","Austin","USA",45,5,2018,"Scaling","$2M-$8M",
  {"franchise":False,"expanding_locations":True,"hiring":True,"online_presence":"strong","delivery":False,"multi_location":True},
  {"crm":"Salesforce","website_platform":"Webflow","marketing_platform":"HubSpot","automation_level":"medium"},
  ["Foot traffic analytics across locations","Membership billing and churn","Staff scheduling across multiple sites","WiFi network security and management"],
  ["Opening three new locations in Denver","Building a membership mobile app","Hiring a Director of Operations"],
  [M("Derek Sullivan","CEO","Executive","derek@canopybrew.com","https://linkedin.com/in/dereksullivan",95),
   M("Priya Anand","COO","Operations","priya@canopybrew.com","https://linkedin.com/in/priyaanand",95),
   M("Liam Foster","Marketing Director","Marketing","liam@canopybrew.com","https://linkedin.com/in/liamfoster",70),
   M("Taylor Reed","Membership Manager","Customer Success","taylor@canopybrew.com","https://linkedin.com/in/taylorreed",65),
   M("Jordan Kim","District Manager","Operations","jordan@canopybrew.com","https://linkedin.com/in/jordankim",80)]))

with open(OUT, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print(f"Written {len(data)} companies, {lid} leads.")
