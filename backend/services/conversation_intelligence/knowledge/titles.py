"""Decision-maker titles and role patterns.

No extraction logic. Data only.
"""

DECISION_MAKER_TITLES: list[str] = [
    "ceo", "cto", "cfo", "coo", "cmo", "chief",
    "vp", "vice president",
    "director", "head of", "president",
    "founder", "owner", "partner",
    "managing director", "svp", "evp", "senior director",
    "manager", "team lead", "engineer",
]

TITLE_NORMALIZATIONS: dict[str, str] = {
    "ceo": "Chief Executive Officer",
    "chief executive officer": "Chief Executive Officer",
    "chief exec officer": "Chief Executive Officer",
    "cto": "Chief Technology Officer",
    "chief technology officer": "Chief Technology Officer",
    "cfo": "Chief Financial Officer",
    "chief financial officer": "Chief Financial Officer",
    "coo": "Chief Operating Officer",
    "chief operating officer": "Chief Operating Officer",
    "cmo": "Chief Marketing Officer",
    "chief marketing officer": "Chief Marketing Officer",
    "vp": "Vice President",
    "vice president": "Vice President",
    "svp": "Senior Vice President",
    "senior vice president": "Senior Vice President",
    "evp": "Executive Vice President",
    "executive vice president": "Executive Vice President",
    "director": "Director",
    "senior director": "Senior Director",
    "head of": "Head of",
    "president": "President",
    "founder": "Founder",
    "owner": "Owner",
    "partner": "Partner",
    "managing director": "Managing Director",
    "manager": "Manager",
    "team lead": "Team Lead",
    "engineer": "Engineer",
}
