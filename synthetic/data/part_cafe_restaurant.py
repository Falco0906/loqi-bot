import json

data = [
    {
        "company_id": None,
        "name": "Blue Orchid Coffee Roasters",
        "industry": "Cafe",
        "sub_industry": "Specialty Coffee Roaster",
        "description": "Artisan roastery sourcing single-origin beans directly from smallholder farms in Ethiopia, Colombia, and Guatemala. Blue Orchid supplies 40+ independent cafes across the Pacific Northwest and runs a flagship tasting room in Portland's Pearl District. Their nitrogen-cold-brew line recently landed distribution in 60 Whole Foods locations.",
        "website": "https://blueorchidcoffee.com",
        "city": "Portland",
        "country": "United States",
        "employees": 28,
        "locations": 3,
        "founded": 2014,
        "growth_stage": "Growing",
        "revenue_band": "$2M-$5M",
        "business_profile": {
            "franchise": False,
            "expanding_locations": True,
            "hiring": True,
            "online_presence": "moderate",
            "delivery": True,
            "multi_location": True
        },
        "technology": {
            "crm": "HubSpot",
            "website_platform": "Shopify",
            "marketing_platform": "Mailchimp",
            "automation_level": "medium"
        },
        "pain_points": [
            "Roast profile consistency across seasonal bean lots requires manual cupping adjustments each batch",
            "Wholesale account onboarding is paper-heavy and slows down new cafe client acquisition",
            "Cold-brew distribution logistics with Whole Foods demand unpredictable spoilage risk"
        ],
        "buying_signals": [
            "Recently posted two production manager job openings on LinkedIn",
            "Upgraded Shopify plan to Plus tier indicating higher ecommerce volume",
            "Started searching for wholesale inventory management software"
        ],
        "decision_makers": [
            {
                "name": "Elena Vasquez",
                "title": "Owner & Head Roaster",
                "department": "Executive",
                "email": "elena@blueorchidcoffee.com",
                "linkedin_url": "https://linkedin.com/in/elenavasquez",
                "buying_authority": 100
            },
            {
                "name": "Marcus Chen",
                "title": "Director of Operations",
                "department": "Operations",
                "email": "marcus@blueorchidcoffee.com",
                "linkedin_url": "https://linkedin.com/in/marcuschen",
                "buying_authority": 85
            },
            {
                "name": "Sophia Park",
                "title": "Wholesale Account Manager",
                "department": "Sales",
                "email": "sophia@blueorchidcoffee.com",
                "linkedin_url": "https://linkedin.com/in/sophiapark",
                "buying_authority": 60
            }
        ]
    },
    {
        "company_id": None,
        "name": "Canopy Brew Collective",
        "industry": "Cafe",
        "sub_industry": "Coworking Cafe Chain",
        "description": "Hybrid coworking-cafe chain with five locations across Austin, each featuring sound-booth phone rooms, gigabit wifi, and pour-over coffee bars. Canopy Brew sells day passes and monthly memberships alongside a full espresso and pastry menu. They recently secured Series A funding to expand into Dallas and Houston.",
        "website": "https://canopybrew.com",
        "city": "Austin",
        "country": "United States",
        "employees": 85,
        "locations": 5,
        "founded": 2019,
        "growth_stage": "Startup",
        "revenue_band": "$3M-$8M",
        "business_profile": {
            "franchise": False,
            "expanding_locations": True,
            "hiring": True,
            "online_presence": "strong",
            "delivery": False,
            "multi_location": True
        },
        "technology": {
            "crm": "Salesforce",
            "website_platform": "Webflow",
            "marketing_platform": "ActiveCampaign",
            "automation_level": "high"
        },
        "pain_points": [
            "Member churn spikes during summer months when remote workers travel or switch to outdoor venues",
            "Inventory forecasting for both cafe supplies and office consumables is done manually in spreadsheets",
            "Space utilization data is siloed — no integration between booking system and POS for demand planning"
        ],
        "buying_signals": [
            "Series A announcement press release mentions hiring a VP of Growth",
            "Recently launched a referral program offering one month free for new member signups",
            "Following LinkedIn profiles of commercial real estate brokers in Dallas and Houston"
        ],
        "decision_makers": [
            {
                "name": "Jordan Teller",
                "title": "CEO & Co-Founder",
                "department": "Executive",
                "email": "jordan@canopybrew.com",
                "linkedin_url": "https://linkedin.com/in/jordanteller",
                "buying_authority": 95
            },
            {
                "name": "Riley Nakamura",
                "title": "COO",
                "department": "Operations",
                "email": "riley@canopybrew.com",
                "linkedin_url": "https://linkedin.com/in/rileynakamura",
                "buying_authority": 95
            },
            {
                "name": "Avery Singh",
                "title": "Head of Growth",
                "department": "Marketing",
                "email": "avery@canopybrew.com",
                "linkedin_url": "https://linkedin.com/in/averysingh",
                "buying_authority": 70
            },
            {
                "name": "Morgan Kim",
                "title": "Director of Operations",
                "department": "Operations",
                "email": "morgan@canopybrew.com",
                "linkedin_url": "https://linkedin.com/in/morgankim",
                "buying_authority": 85
            }
        ]
    },
    {
        "company_id": None,
        "name": "Miel Cafe & Creperie",
        "industry": "Cafe",
        "sub_industry": "French Cafe & Bakery",
        "description": "Authentic French creperie and cafe in Montreal's Mile End neighborhood, specializing in buckwheat galettes and honey-infused desserts made from Quebec-sourced ingredients. Miel operates a sister location in Old Montreal and supplies their house-made jams to 12 local boutique hotels. They host weekly French pastry workshops that sell out within hours.",
        "website": "https://mielcafe.ca",
        "city": "Montreal",
        "country": "Canada",
        "employees": 18,
        "locations": 2,
        "founded": 2016,
        "growth_stage": "Established",
        "revenue_band": "$1M-$3M",
        "business_profile": {
            "franchise": False,
            "expanding_locations": False,
            "hiring": False,
            "online_presence": "weak",
            "delivery": True,
            "multi_location": True
        },
        "technology": {
            "crm": None,
            "website_platform": "Wix",
            "marketing_platform": "Instagram",
            "automation_level": "low"
        },
        "pain_points": [
            "No CRM or reservation system — workshop bookings are managed via Instagram DMs and Google Forms",
            "Jam wholesale orders are tracked on paper and invoices are handwritten, causing occasional billing disputes",
            "Their Wix site has no ecommerce capability so customers cannot order jam or gift cards online"
        ],
        "buying_signals": [
            "Recently inquired with a local POS provider about adding online ordering",
            "Hired a part-time social media manager to improve digital presence",
            "Posted on Instagram that they are overwhelmed with crepe festival orders and need better systems"
        ],
        "decision_makers": [
            {
                "name": "Camille Dubois",
                "title": "Owner & Head Chef",
                "department": "Executive",
                "email": "camille@mielcafe.ca",
                "linkedin_url": "https://linkedin.com/in/camilledubois",
                "buying_authority": 100
            },
            {
                "name": "Luc Beaumont",
                "title": "General Manager",
                "department": "Operations",
                "email": "luc@mielcafe.ca",
                "linkedin_url": "https://linkedin.com/in/lucbeaumont",
                "buying_authority": 85
            },
            {
                "name": "Marie-Louise Tremblay",
                "title": "Wholesale Coordinator",
                "department": "Sales",
                "email": "mlt@mielcafe.ca",
                "linkedin_url": "https://linkedin.com/in/marielouisetremblay",
                "buying_authority": 50
            }
        ]
    },
    {
        "company_id": None,
        "name": "BrewLab",
        "industry": "Cafe",
        "sub_industry": "Experimental Micro-Roastery",
        "description": "Science-driven micro-roastery in Berlin's Kreuzberg district that applies statistical process control to coffee roasting. BrewLab publishes open-source roast profiles and sells monthly subscription boxes to 1,200 members across Europe. Their lab-grade tasting room doubles as a training facility for aspiring Q-graders and hosts cupping sessions with visiting producers.",
        "website": "https://brewlab.coffee",
        "city": "Berlin",
        "country": "Germany",
        "employees": 9,
        "locations": 1,
        "founded": 2020,
        "growth_stage": "Growing",
        "revenue_band": "$500K-$1.5M",
        "business_profile": {
            "franchise": False,
            "expanding_locations": False,
            "hiring": True,
            "online_presence": "strong",
            "delivery": True,
            "multi_location": False
        },
        "technology": {
            "crm": "Notion",
            "website_platform": "Craft CMS",
            "marketing_platform": "ConvertKit",
            "automation_level": "medium"
        },
        "pain_points": [
            "Subscription churn is 12% monthly — retention campaigns are manual and lack personalization",
            "Roast data is recorded in a local SQLite database with no cloud backup or remote access for the team",
            "Shipping EU-wide from Berlin is expensive and they lack volume discounts with DHL and DPD"
        ],
        "buying_signals": [
            "Began following logistics and shipping software companies on LinkedIn",
            "Posted a call on their blog for beta testers of a new subscription customization tool",
            "Hired a part-time data analyst to improve retention metrics"
        ],
        "decision_makers": [
            {
                "name": "Felix Brandt",
                "title": "Founder & Head Roaster",
                "department": "Executive",
                "email": "felix@brewlab.coffee",
                "linkedin_url": "https://linkedin.com/in/felixbrandt",
                "buying_authority": 100
            },
            {
                "name": "Ingrid Svensson",
                "title": "Operations & Subscription Manager",
                "department": "Operations",
                "email": "ingrid@brewlab.coffee",
                "linkedin_url": "https://linkedin.com/in/ingridsvensson",
                "buying_authority": 85
            },
            {
                "name": "Tobias Lehmann",
                "title": "Marketing Lead",
                "department": "Marketing",
                "email": "tobias@brewlab.coffee",
                "linkedin_url": "https://linkedin.com/in/tobiaslehmann",
                "buying_authority": 70
            }
        ]
    },
    {
        "company_id": None,
        "name": "The Daily Grind Cafe Co.",
        "industry": "Cafe",
        "sub_industry": "Franchise Cafe Chain",
        "description": "Midwest-born franchise cafe chain with 14 company-owned and 8 franchise locations across Illinois, Indiana, and Wisconsin. Daily Grind serves breakfast sandwiches, specialty lattes, and grab-and-go lunch bowls with a loyalty program counting 45,000 active members. They are in the process of standardizing operations ahead of a 30-unit expansion into Ohio and Michigan.",
        "website": "https://dailygrindcafe.com",
        "city": "Chicago",
        "country": "United States",
        "employees": 320,
        "locations": 22,
        "founded": 1998,
        "growth_stage": "Mature",
        "revenue_band": "$15M-$30M",
        "business_profile": {
            "franchise": True,
            "expanding_locations": True,
            "hiring": True,
            "online_presence": "strong",
            "delivery": True,
            "multi_location": True
        },
        "technology": {
            "crm": "Salesforce",
            "website_platform": "WordPress",
            "marketing_platform": "HubSpot",
            "automation_level": "medium"
        },
        "pain_points": [
            "Franchisee compliance with standardized recipes and branding varies widely across 8 independently owned locations",
            "Legacy POS system does not support centralized menu updates pushing changes to all locations simultaneously",
            "Loyalty program data is fragmented — no cross-channel view between in-store, app, and third-party delivery orders"
        ],
        "buying_signals": [
            "Issued RFP for a new enterprise POS and kitchen display system across all 22 locations",
            "Hired a Director of Franchise Operations to improve franchisee training and compliance tracking",
            "Recently launched mobile app with order-ahead capability signaling investment in digital infrastructure"
        ],
        "decision_makers": [
            {
                "name": "Patricia Holloway",
                "title": "CEO",
                "department": "Executive",
                "email": "pholloway@dailygrindcafe.com",
                "linkedin_url": "https://linkedin.com/in/patriciaholloway",
                "buying_authority": 95
            },
            {
                "name": "James Kowalski",
                "title": "VP of Operations",
                "department": "Operations",
                "email": "jkowalski@dailygrindcafe.com",
                "linkedin_url": "https://linkedin.com/in/jameskowalski",
                "buying_authority": 90
            },
            {
                "name": "Diana Reyes",
                "title": "Director of Franchise Operations",
                "department": "Operations",
                "email": "dreyes@dailygrindcafe.com",
                "linkedin_url": "https://linkedin.com/in/dianareyes",
                "buying_authority": 85
            },
            {
                "name": "Tom Fletcher",
                "title": "Chief Technology Officer",
                "department": "IT",
                "email": "tfletcher@dailygrindcafe.com",
                "linkedin_url": "https://linkedin.com/in/tomfletcher",
                "buying_authority": 80
            },
            {
                "name": "Lisa Nguyen",
                "title": "Marketing Director",
                "department": "Marketing",
                "email": "lnguyen@dailygrindcafe.com",
                "linkedin_url": "https://linkedin.com/in/lisanguyen",
                "buying_authority": 70
            },
            {
                "name": "Robert Okafor",
                "title": "Supply Chain Manager",
                "department": "Supply Chain",
                "email": "rokafot@dailygrindcafe.com",
                "linkedin_url": "https://linkedin.com/in/robertokafor",
                "buying_authority": 65
            }
        ]
    },
    {
        "company_id": None,
        "name": "Brick & Mortar Kitchen",
        "industry": "Restaurant",
        "sub_industry": "Farm-to-Table Fine Dining",
        "description": "Award-winning farm-to-table restaurant group operating three distinct venues in New York's Hudson Valley: a fine dining tasting room in Rhinebeck, a casual bistro in Hudson, and a seasonal outdoor supper club in Red Hook. Brick & Mortar partners with 25 local farms and forages wild mushrooms and ramps for their rotating menus. They were semi-finalists for a James Beard Award in 2025.",
        "website": "https://brickandmortarkitchen.com",
        "city": "Hudson Valley",
        "country": "United States",
        "employees": 65,
        "locations": 3,
        "founded": 2012,
        "growth_stage": "Established",
        "revenue_band": "$5M-$10M",
        "business_profile": {
            "franchise": False,
            "expanding_locations": False,
            "hiring": True,
            "online_presence": "moderate",
            "delivery": False,
            "multi_location": True
        },
        "technology": {
            "crm": "Toast",
            "website_platform": "Squarespace",
            "marketing_platform": "Mailchimp",
            "automation_level": "low"
        },
        "pain_points": [
            "Local farm supply is unpredictable — menu changes must be communicated across three venues in real time",
            "Reservation no-show rate averages 18% and they lack automated waitlist or deposit tools",
            "Farm partnerships require manual invoicing and reconciliation with no centralized vendor management system"
        ],
        "buying_signals": [
            "Posted job listing for a Supply Chain & Local Sourcing Coordinator",
            "Recently switched reservation platforms from Resy to OpenTable and is evaluating add-on tools",
            "Chef-owner mentioned in local press that they need better vendor management software"
        ],
        "decision_makers": [
            {
                "name": "Daniel Hawthorne",
                "title": "Owner & Executive Chef",
                "department": "Executive",
                "email": "dan@brickandmortarkitchen.com",
                "linkedin_url": "https://linkedin.com/in/danielhawthorne",
                "buying_authority": 100
            },
            {
                "name": "Megan O'Sullivan",
                "title": "General Manager",
                "department": "Operations",
                "email": "megan@brickandmortarkitchen.com",
                "linkedin_url": "https://linkedin.com/in/meganosullivan",
                "buying_authority": 85
            },
            {
                "name": "Alex Reinhardt",
                "title": "Director of Events & Partnerships",
                "department": "Marketing",
                "email": "alex@brickandmortarkitchen.com",
                "linkedin_url": "https://linkedin.com/in/alexreinhardt",
                "buying_authority": 70
            },
            {
                "name": "Sarah Jennings",
                "title": "Sous Chef & Menu Planner",
                "department": "Kitchen",
                "email": "sarah@brickandmortarkitchen.com",
                "linkedin_url": "https://linkedin.com/in/sarahjennings",
                "buying_authority": 55
            }
        ]
    },
    {
        "company_id": None,
        "name": "Wok & Roll Noodle Bar",
        "industry": "Restaurant",
        "sub_industry": "Asian Fusion Fast Casual",
        "description": "Fast-casual Asian fusion chain with 14 locations across Los Angeles County, serving customizable noodle bowls, bao buns, and Korean fried chicken. Wok & Roll operates a central commissary kitchen in Koreatown that preps sauces and proteins for all locations. Their mobile app accounts for 40% of orders and they recently launched a ghost kitchen concept in Santa Monica.",
        "website": "https://wokandrollnoodlebar.com",
        "city": "Los Angeles",
        "country": "United States",
        "employees": 210,
        "locations": 14,
        "founded": 2015,
        "growth_stage": "Scaling",
        "revenue_band": "$10M-$25M",
        "business_profile": {
            "franchise": False,
            "expanding_locations": True,
            "hiring": True,
            "online_presence": "strong",
            "delivery": True,
            "multi_location": True
        },
        "technology": {
            "crm": "Lightspeed",
            "website_platform": "Toast",
            "marketing_platform": "Klaviyo",
            "automation_level": "high"
        },
        "pain_points": [
            "Commissary-to-store inventory tracking relies on paper manifests causing frequent stockouts of popular items",
            "Third-party delivery commissions eat 28% of online orders and they lack leverage to negotiate lower rates",
            "Kitchen staff turnover is 70% annually making recipe standardization and training a constant drain on managers"
        ],
        "buying_signals": [
            "CEO posted on LinkedIn about evaluating multi-location inventory management platforms",
            "Hired a Head of Business Operations role focused on vendor management and procurement systems",
            "Recently engaged a consulting firm to audit third-party delivery cost structure"
        ],
        "decision_makers": [
            {
                "name": "Kevin Tran",
                "title": "CEO & Founder",
                "department": "Executive",
                "email": "kevin@wokandrollnoodlebar.com",
                "linkedin_url": "https://linkedin.com/in/kevintran",
                "buying_authority": 95
            },
            {
                "name": "Michelle Park",
                "title": "COO",
                "department": "Operations",
                "email": "michelle@wokandrollnoodlebar.com",
                "linkedin_url": "https://linkedin.com/in/michellepark",
                "buying_authority": 95
            },
            {
                "name": "David Kim",
                "title": "Director of Technology",
                "department": "IT",
                "email": "david@wokandrollnoodlebar.com",
                "linkedin_url": "https://linkedin.com/in/davidkim",
                "buying_authority": 80
            },
            {
                "name": "Angela Cruz",
                "title": "Head of Marketing",
                "department": "Marketing",
                "email": "angela@wokandrollnoodlebar.com",
                "linkedin_url": "https://linkedin.com/in/angelacruz",
                "buying_authority": 70
            },
            {
                "name": "James Park",
                "title": "Supply Chain Manager",
                "department": "Supply Chain",
                "email": "jpark@wokandrollnoodlebar.com",
                "linkedin_url": "https://linkedin.com/in/jamespark",
                "buying_authority": 65
            }
        ]
    },
    {
        "company_id": None,
        "name": "Olea Taverna",
        "industry": "Restaurant",
        "sub_industry": "Mediterranean Restaurant Group",
        "description": "Boston-based Mediterranean restaurant group operating four establishments: a fine-dining Greek taverna in Back Bay, a casual mezze bar in Cambridge, a rooftop ouzo lounge in Seaport, and a fast-casual takeout concept in Somerville. Olea imports olive oil directly from a family grove in Kalamata and bakes their pita and phyllo in-house daily. They are developing a retail line of house-made dressings and dips for New England Whole Foods.",
        "website": "https://oleataverna.com",
        "city": "Boston",
        "country": "United States",
        "employees": 145,
        "locations": 4,
        "founded": 2009,
        "growth_stage": "Established",
        "revenue_band": "$8M-$18M",
        "business_profile": {
            "franchise": False,
            "expanding_locations": False,
            "hiring": False,
            "online_presence": "moderate",
            "delivery": True,
            "multi_location": True
        },
        "technology": {
            "crm": "TouchBistro",
            "website_platform": "Wix",
            "marketing_platform": "Constant Contact",
            "automation_level": "medium"
        },
        "pain_points": [
            "Olive oil import supply chain is fragile — single-grove dependency creates risk during off-years and tariff fluctuations",
            "Retail product development for Whole Foods requires batch traceability that their current kitchen systems cannot provide",
            "Four distinct venues operate on separate POS instances with no consolidated sales or labor reporting",
            "Online ordering is managed through a clunky third-party widget with no integration to their loyalty program"
        ],
        "buying_signals": [
            "Hired a Director of Retail Operations to lead the Whole Foods product launch",
            "Requested demos from unified POS and restaurant management platforms that support multi-venue reporting",
            "Held exploratory conversations with a supply chain consulting firm about diversifying olive oil sourcing"
        ],
        "decision_makers": [
            {
                "name": "Nico Demetriou",
                "title": "Owner & Chef",
                "department": "Executive",
                "email": "nico@oleataverna.com",
                "linkedin_url": "https://linkedin.com/in/nicodemetriou",
                "buying_authority": 100
            },
            {
                "name": "Eleni Papadakis",
                "title": "Director of Operations",
                "department": "Operations",
                "email": "eleni@oleataverna.com",
                "linkedin_url": "https://linkedin.com/in/elenipapadakis",
                "buying_authority": 85
            },
            {
                "name": "George Katsaros",
                "title": "CFO",
                "department": "Finance",
                "email": "george@oleataverna.com",
                "linkedin_url": "https://linkedin.com/in/georgekatsaros",
                "buying_authority": 90
            },
            {
                "name": "Sofia Markos",
                "title": "Director of Retail Operations",
                "department": "Sales",
                "email": "sofia@oleataverna.com",
                "linkedin_url": "https://linkedin.com/in/sofiamarkos",
                "buying_authority": 75
            }
        ]
    },
    {
        "company_id": None,
        "name": "Smoke & Brine BBQ",
        "industry": "Restaurant",
        "sub_industry": "Barbecue Restaurant",
        "description": "Nashville's fastest-growing barbecue group with two full-service smokehouses and a food truck fleet serving 8-12 events weekly. Smoke & Brine is known for their dry-rub ribs, smoked briset with a coffee-chile crust, and house-fermented pickles and hot sauces sold in 30 Tennessee grocery stores. They are building a 6,000 sq ft central smokehouse and production facility in East Nashville to triple capacity.",
        "website": "https://smokeandbrinebbq.com",
        "city": "Nashville",
        "country": "United States",
        "employees": 55,
        "locations": 2,
        "founded": 2017,
        "growth_stage": "Growing",
        "revenue_band": "$4M-$9M",
        "business_profile": {
            "franchise": False,
            "expanding_locations": True,
            "hiring": True,
            "online_presence": "moderate",
            "delivery": True,
            "multi_location": True
        },
        "technology": {
            "crm": "Square",
            "website_platform": "Square Online",
            "marketing_platform": "Mailchimp",
            "automation_level": "low"
        },
        "pain_points": [
            "Smokehouse buildout project management is handled via email and texts with no construction tracking software",
            "Hot sauce retail distribution to grocery stores requires batch-level traceability and nutritional labeling compliance",
            "Food truck scheduling and event coordination is manual on a shared Google Calendar causing double-bookings",
            "Catering inquiries come through Instagram DMs, website form, and phone with no centralized lead management"
        ],
        "buying_signals": [
            "Owner posted on LinkedIn about frustrations managing the smokehouse construction project timeline",
            "Applied for a Tennessee Department of Agriculture grant for food processing facility upgrades",
            "Hired a part-time admin specifically to handle catering and event coordination"
        ],
        "decision_makers": [
            {
                "name": "Caleb Beauregard",
                "title": "Owner & Pitmaster",
                "department": "Executive",
                "email": "caleb@smokeandbrinebbq.com",
                "linkedin_url": "https://linkedin.com/in/caleb.beauregard",
                "buying_authority": 100
            },
            {
                "name": "Hannah Whitfield",
                "title": "General Manager",
                "department": "Operations",
                "email": "hannah@smokeandbrinebbq.com",
                "linkedin_url": "https://linkedin.com/in/hannahwhitfield",
                "buying_authority": 85
            },
            {
                "name": "Trey Morgan",
                "title": "Director of Retail & Distribution",
                "department": "Sales",
                "email": "trey@smokeandbrinebbq.com",
                "linkedin_url": "https://linkedin.com/in/treymorgan",
                "buying_authority": 75
            },
            {
                "name": "Jordan Hayes",
                "title": "Marketing & Events Coordinator",
                "department": "Marketing",
                "email": "jordan@smokeandbrinebbq.com",
                "linkedin_url": "https://linkedin.com/in/jordanhayes",
                "buying_authority": 60
            }
        ]
    },
    {
        "company_id": None,
        "name": "Umaji Ramen House",
        "industry": "Restaurant",
        "sub_industry": "Ramen Shop",
        "description": "London-based authentic ramen shop with three locations in Soho, Shoreditch, and Borough Market, each featuring a Japanese-trained head chef and a tonkotsu broth that simmers for 18 hours daily. Umaji imports most ingredients directly from Fukuoka and Kyushu, including their noodles, tare, and nori. They publish a quarterly zine about Japanese food culture and run a sold-out ramen masterclass series on Sundays.",
        "website": "https://umajiramen.co.uk",
        "city": "London",
        "country": "United Kingdom",
        "employees": 42,
        "locations": 3,
        "founded": 2018,
        "growth_stage": "Growing",
        "revenue_band": "$3M-$7M",
        "business_profile": {
            "franchise": False,
            "expanding_locations": False,
            "hiring": True,
            "online_presence": "strong",
            "delivery": True,
            "multi_location": True
        },
        "technology": {
            "crm": "HubSpot",
            "website_platform": "Cargo",
            "marketing_platform": "Omnisend",
            "automation_level": "medium"
        },
        "pain_points": [
            "Importing from Japan involves complex customs paperwork and air freight costs that fluctuate wildly month to month",
            "Broth consistency across three locations is hard to maintain when each chef prepares it independently",
            "Sunday masterclasses are booked through a manual email-and-Google-Forms workflow with no automated payment collection",
            "Delivery partners (Deliveroo, Uber Eats) provide no customer data making it impossible to build direct relationships"
        ],
        "buying_signals": [
            "Following UK food import logistics software vendors on LinkedIn",
            "Recently purchased a domain for an online shop to sell packaged ramen kits and merchandise",
            "Started posting job ads for a full-time supply chain and logistics coordinator"
        ],
        "decision_makers": [
            {
                "name": "Takeshi Yamamoto",
                "title": "Founder & Head Chef",
                "department": "Executive",
                "email": "takeshi@umajiramen.co.uk",
                "linkedin_url": "https://linkedin.com/in/takeshiyamamoto",
                "buying_authority": 100
            },
            {
                "name": "Charlotte Evans",
                "title": "Managing Director",
                "department": "Operations",
                "email": "charlotte@umajiramen.co.uk",
                "linkedin_url": "https://linkedin.com/in/charlotteevans",
                "buying_authority": 95
            },
            {
                "name": "Ryo Tanaka",
                "title": "Head of Operations (UK)",
                "department": "Operations",
                "email": "ryo@umajiramen.co.uk",
                "linkedin_url": "https://linkedin.com/in/ryotanaka",
                "buying_authority": 85
            },
            {
                "name": "Priya Sharma",
                "title": "Marketing Manager",
                "department": "Marketing",
                "email": "priya@umajiramen.co.uk",
                "linkedin_url": "https://linkedin.com/in/priyasharma",
                "buying_authority": 70
            },
            {
                "name": "Hiroshi Kato",
                "title": "Supply Chain & Logistics Coordinator",
                "department": "Supply Chain",
                "email": "hiroshi@umajiramen.co.uk",
                "linkedin_url": "https://linkedin.com/in/hiroshikato",
                "buying_authority": 65
            }
        ]
    }
]

print(json.dumps(data, indent=2))
