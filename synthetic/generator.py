#!/usr/bin/env python3
"""
Deterministic synthetic company generator.

Generates realistic companies from template vocabularies.
Usage:
    python3 generator.py --companies 5000
    python3 generator.py --companies 3000 --industries Restaurant,Cafe,Gym --seed 42
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

TEMPLATE_DIR = Path(__file__).parent / "templates"
OUTPUT_DIR = Path(__file__).parent / "output"


class Generator:
    """Deterministic company generator using template vocabularies."""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.templates = self._load_templates()
        self._company_counter = 0
        self._lead_counter = 0

    def _load_templates(self) -> dict[str, Any]:
        templates = {}
        for f in TEMPLATE_DIR.glob("*.json"):
            with open(f) as fh:
                templates[f.stem] = json.load(fh)
        return templates

    def _next_company_id(self) -> str:
        self._company_counter += 1
        return f"cmp_{self._company_counter:06d}"

    def _next_lead_id(self) -> str:
        self._lead_counter += 1
        return f"lead_{self._lead_counter:06d}"

    def _pick(self, lst: list, weights: list[int] | None = None) -> Any:
        if weights:
            return self.rng.choices(lst, weights=weights, k=1)[0]
        return self.rng.choice(lst)

    def _pick_n(self, lst: list, n: int) -> list:
        n = min(n, len(lst))
        return self.rng.sample(lst, k=n)

    def _weighted_pick(self, items: list, weights: list[int]) -> str:
        return self.rng.choices(items, weights=weights, k=1)[0]

    def _pick_city(self) -> dict:
        regions = [
            self.templates["cities"]["us_cities"],
            self.templates["cities"]["canada_cities"],
            self.templates["cities"]["uk_cities"],
            self.templates["cities"]["europe_cities"],
            self.templates["cities"]["asia_cities"],
            self.templates["cities"]["oceania_cities"],
            self.templates["cities"]["latam_cities"],
            self.templates["cities"]["africa_cities"],
        ]
        # Weight toward US/UK/Europe/Australia for B2B relevance
        weights = [30, 10, 15, 15, 15, 5, 5, 5]
        region = self.rng.choices(regions, weights=weights, k=1)[0]
        return self.rng.choice(region)

    def _pick_name(self, industry: str, config: dict) -> str:
        prefix = self.rng.choice(config["name_prefixes"])
        suffix = self.rng.choice(config["name_suffixes"])
        return f"{prefix} {suffix}"

    def _pick_first_name(self) -> str:
        pools = list(self.templates["first_names"].values())
        pool = self.rng.choice(pools)
        return self.rng.choice(pool)

    def _pick_last_name(self) -> str:
        pools = list(self.templates["last_names"].values())
        pool = self.rng.choice(pools)
        return self.rng.choice(pool)

    def _make_email(self, name: str, domain: str) -> str:
        parts = name.lower().split()
        username = ".".join(parts)
        return f"{username}@{domain}"

    def _make_linkedin(self, name: str) -> str:
        slug = name.lower().replace(" ", "-")
        return f"https://linkedin.com/in/{slug}"

    def _make_website(self, name: str) -> str:
        slug = name.lower().replace(" ", "").replace("&", "and").replace("'", "")
        tlds = [".com", ".io", ".co", ".net", ".us"]
        tld = self.rng.choice(tlds)
        return f"https://{slug}{tld}"

    def _make_domain(self, website: str) -> str:
        return website.replace("https://", "").split("/")[0]

    def _generate_description(self, name: str, industry: str, config: dict,
                               city: str, country: str, locations: int) -> str:
        extra = self.templates["extra"]
        adjective = self.rng.choice(extra["description_adjectives"].get(industry, ["innovative"]))
        focus = self.rng.choice(extra["description_focuses"].get(industry, ["quality"]))
        audience = self.rng.choice(extra["description_audiences"].get(industry, ["businesses"]))
        feature = self.rng.choice(extra["description_features"].get(industry, ["excellence"]))

        # Get 2-3 templates for this industry
        templates = config.get("description_templates", [
            "{name} is a {adjective} {sub_industry} in {city} serving {audience}."
        ])

        template = self.rng.choice(templates)

        features_list = config.get("description_features", [feature])
        features = self.rng.choice([feature, ", ".join(self._pick_n(features_list, 2))])

        desc = template.format(
            name=name,
            adjective=adjective,
            sub_industry=config.get("sub_industries", ["business"])[0],
            sub=config.get("sub_industries", ["business"])[0],
            city=city,
            country=country,
            locations=locations,
            employee_count=self.rng.randint(10, 200),
            audience=audience,
            focus=focus,
            feature=feature,
            features=features,
            food=self.rng.choice(["authentic cuisine", "fresh ingredients", "traditional dishes"]),
            coffee_type=self.rng.choice(["single-origin", "specialty", "artisan", "cold brew"]),
            origin=self.rng.choice(["Ethiopia", "Colombia", "Guatemala", "Brazil"]),
            room_count=self.rng.randint(20, 300),
            sq_ft=f"{self.rng.randint(20, 500)}K",
            vehicles=self.rng.randint(20, 200),
            machines=self.rng.randint(10, 100),
            attorney_count=self.rng.randint(5, 50),
            funding_round=self.rng.choice(["Seed funding", "Series A", "Series B", "Pre-Seed"]),
            region=self.rng.choice(["regional", "metro", "tri-state", "national"]),
            products=self.rng.choice(["products", "goods", "solutions", "services"]),
            services=self.rng.choice(["services", "solutions", "expertise", "support"]),
            agent_count=self.rng.randint(10, 80),
        )
        return desc

    def _generate_pain_points(self, config: dict) -> list[str]:
        all_pains = config.get("pain_points", [])
        n = self.rng.randint(3, min(5, len(all_pains)))
        return self._pick_n(all_pains, n)

    def _generate_buying_signals(self, config: dict) -> list[str]:
        all_signals = config.get("buying_signals", [])
        n = self.rng.randint(2, min(3, len(all_signals)))
        return self._pick_n(all_signals, n)

    def _generate_events(self, config: dict, city: str, locations: int = 1) -> list[str]:
        all_events = config.get("events", [])
        n = self.rng.randint(2, min(4, len(all_events)))
        events = self._pick_n(all_events, n)
        fmt_vars = {
            "city": city,
            "locations": locations,
            "funding_round": self.rng.choice(["Seed funding", "Series A", "Series B"]),
            "funding": self.rng.choice(["$2M Seed", "$5M Series A", "$10M Series B"]),
        }
        return [e.format(**fmt_vars) for e in events]

    def _generate_decision_makers(self, config: dict, domain: str,
                                    city: str, country: str) -> list[dict]:
        roles = config.get("roles", [])
        n = self.rng.randint(3, min(6, len(roles)))
        selected_roles = self._pick_n(roles, n)
        makers = []
        for role in selected_roles:
            title, dept, auth_base = role[0], role[1], role[2]
            first = self._pick_first_name()
            last = self._pick_last_name()
            full_name = f"{first} {last}"
            auth = min(100, max(50, auth_base + self.rng.randint(-10, 10)))
            makers.append({
                "lead_id": self._next_lead_id(),
                "name": full_name,
                "title": title,
                "department": dept,
                "email": self._make_email(full_name, domain),
                "linkedin_url": self._make_linkedin(full_name),
                "buying_authority": auth,
            })
        return makers

    def _generate_tech_stack(self, config: dict) -> dict:
        tech = config.get("technologies", {})
        return {
            "crm": self.rng.choice(tech.get("crm", [None])),
            "website_platform": self.rng.choice(tech.get("website_platform", ["WordPress"])),
            "marketing_platform": self.rng.choice(tech.get("marketing_platform", ["Google Ads"])),
            "automation_level": self._weighted_pick(
                self.templates["extra"]["automation_levels"],
                self.templates["extra"]["automation_level_weights"]
            ),
        }

    def _generate_business_profile(self) -> dict:
        extra = self.templates["extra"]
        return {
            "franchise": self.rng.random() < 0.15,
            "expanding_locations": self.rng.random() < 0.6,
            "hiring": self.rng.random() < 0.7,
            "online_presence": self._weighted_pick(
                extra["online_presence_levels"],
                extra["online_presence_weights"]
            ),
            "delivery": self.rng.random() < 0.35,
            "multi_location": self.rng.random() < 0.45,
        }

    def _generate_company(self, industry: str, config: dict) -> dict:
        city_data = self._pick_city()
        city = city_data["city"]
        country = city_data["country"]
        region = city_data["region"]

        name = self._pick_name(industry, config)
        website = self._make_website(name)
        domain = self._make_domain(website)

        sub_industry = self.rng.choice(config.get("sub_industries", [industry]))

        emp_min, emp_max = config.get("employee_range", [10, 100])
        employees = self.rng.randint(emp_min, emp_max)

        loc_min, loc_max = config.get("location_range", [1, 5])
        locations = self.rng.randint(loc_min, loc_max)

        fd_min, fd_max = config.get("founded_range", [2010, 2024])
        founded = self.rng.randint(fd_min, fd_max)

        growth_stage = self._weighted_pick(
            self.templates["extra"]["growth_stages"],
            self.templates["extra"]["growth_stage_weights"]
        )

        revenue_band = self.rng.choice(config.get("revenue_bands", ["$1M-$5M"]))

        description = self._generate_description(
            name, industry, config, city, country, locations
        )

        return {
            "company_id": self._next_company_id(),
            "name": name,
            "industry": industry,
            "sub_industry": sub_industry,
            "description": description,
            "website": website,
            "city": city,
            "country": country,
            "employees": employees,
            "locations": locations,
            "founded": founded,
            "growth_stage": growth_stage,
            "revenue_band": revenue_band,
            "business_profile": self._generate_business_profile(),
            "technology": self._generate_tech_stack(config),
            "pain_points": self._generate_pain_points(config),
            "buying_signals": self._generate_buying_signals(config),
            "recent_events": self._generate_events(config, city, locations),
            "decision_makers": self._generate_decision_makers(
                config, domain, city, country
            ),
        }

    def generate(self, n_companies: int,
                 industries: list[str] | None = None) -> list[dict]:
        industries_data = self.templates["industries"]

        if industries:
            # Validate requested industries exist
            valid = [i for i in industries if i in industries_data]
            if not valid:
                print(f"Error: No valid industries found. Available: {list(industries_data.keys())}",
                      file=sys.stderr)
                sys.exit(1)
            industry_names = valid
        else:
            industry_names = list(industries_data.keys())

        # Distribute companies across selected industries
        n_industries = len(industry_names)
        base_count = n_companies // n_industries
        remainder = n_companies % n_industries

        companies = []
        for i, ind in enumerate(industry_names):
            count = base_count + (1 if i < remainder else 0)
            config = industries_data[ind]
            for _ in range(count):
                companies.append(self._generate_company(ind, config))

        # Shuffle deterministically
        self.rng.shuffle(companies)

        return companies


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic companies from templates"
    )
    parser.add_argument(
        "--companies", "-n", type=int, default=100,
        help="Number of companies to generate (default: 100)"
    )
    parser.add_argument(
        "--industries", "-i", type=str, default=None,
        help="Comma-separated list of industries to include (default: all)"
    )
    parser.add_argument(
        "--seed", "-s", type=int, default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output file path (default: synthetic/output/companies.json)"
    )
    parser.add_argument(
        "--pretty", action="store_true", default=True,
        help="Pretty-print JSON output (default: True)"
    )
    parser.add_argument(
        "--compact", action="store_true", default=False,
        help="Compact JSON output (no indentation)"
    )

    args = parser.parse_args()

    industries = None
    if args.industries:
        industries = [i.strip() for i in args.industries.split(",")]

    start = time.time()

    gen = Generator(seed=args.seed)
    companies = gen.generate(
        n_companies=args.companies,
        industries=industries,
    )

    elapsed = time.time() - start

    # Determine output path
    output_path = Path(args.output) if args.output else OUTPUT_DIR / "companies.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write output
    indent = None if args.compact else 2
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(companies, f, indent=indent, ensure_ascii=False)

    file_size = output_path.stat().st_size

    # Summary
    total_leads = sum(len(c["decision_makers"]) for c in companies)
    industries_found = {}
    for c in companies:
        industries_found[c["industry"]] = industries_found.get(c["industry"], 0) + 1

    print(f"Generated {len(companies):,} companies with {total_leads:,} decision makers")
    print(f"Industries: {len(industries_found)}")
    for ind, count in sorted(industries_found.items()):
        print(f"  {ind}: {count}")
    print(f"Output: {output_path} ({file_size:,} bytes)")
    print(f"Time: {elapsed:.3f}s")
    print(f"Seed: {args.seed}")

    # Schema validation
    sample = companies[0] if companies else {}
    expected_keys = {
        "company_id", "name", "industry", "sub_industry", "description",
        "website", "city", "country", "employees", "locations", "founded",
        "growth_stage", "revenue_band", "business_profile", "technology",
        "pain_points", "buying_signals", "recent_events", "decision_makers"
    }
    actual_keys = set(sample.keys())
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys

    if missing or extra:
        print(f"\nSchema check: MISSING={missing or 'none'}, EXTRA={extra or 'none'}", file=sys.stderr)
    else:
        print("Schema check: PASS")


if __name__ == "__main__":
    main()
