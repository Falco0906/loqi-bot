"""Technology names organized by category.

No extraction logic. Data only.
This file is stable — reasoning engines never import it directly.
"""

TECHNOLOGIES: dict[str, list[str]] = {
    "crm": [
        "salesforce", "hubspot", "zoho", "pipedrive", "dynamics",
        "oracle crm", "sugar crm", "freshsales",
    ],
    "communication": [
        "slack", "teams", "zoom", "google meet", "skype",
        "discord", "telegram", "whatsapp",
    ],
    "cloud": [
        "aws", "azure", "gcp", "google cloud", "aws cloud",
        "amazon web services", "digitalocean", "heroku",
    ],
    "data_analytics": [
        "tableau", "looker", "mode", "metabase", "power bi",
        "snowflake", "bigquery", "redshift", "datadog", "sentry",
    ],
    "project_management": [
        "jira", "confluence", "notion", "asana", "monday.com",
        "trello", "basecamp", "linear", "clickup",
    ],
    "engineering": [
        "python", "javascript", "typescript", "react", "node",
        "graphql", "rest", "api", "docker", "kubernetes",
    ],
    "support": [
        "zendesk", "intercom", "freshdesk", "helpscout",
        "livechat", "drift",
    ],
    "enterprise": [
        "sap", "oracle", "ibm", "servicenow", "workday",
    ],
}

ALL_TECHNOLOGIES: list[str] = [
    tech for techs in TECHNOLOGIES.values() for tech in techs
]

TECHNOLOGY_NORMALIZATIONS: dict[str, str] = {
    "aws": "Amazon Web Services",
    "amazon web services": "Amazon Web Services",
    "gcp": "Google Cloud Platform",
    "google cloud": "Google Cloud Platform",
    "google cloud platform": "Google Cloud Platform",
    "ms teams": "Microsoft Teams",
    "power bi": "Microsoft Power BI",
    "monday.com": "Monday.com",
    "react.js": "React",
    "node.js": "Node.js",
    "nodejs": "Node.js",
}
