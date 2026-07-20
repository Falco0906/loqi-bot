from __future__ import annotations

from typing import Any

from services.agent_sdk.models import (
    AgentResult,
    AgentContext,
    AgentType,
    ResearchReport,
)
from services.agent_sdk.agent_base import Agent
from services.intelligence.account_intelligence import generate_account_intelligence


class ResearchAgent(Agent):

    @property
    def agent_type(self) -> AgentType:
        return AgentType.RESEARCH

    @property
    def name(self) -> str:
        return "research_agent"

    @property
    def description(self) -> str:
        return "Researches companies, performs ICP matching, and produces structured ResearchReport."

    async def process(self, context: AgentContext) -> AgentResult:
        params = context.params
        company_name = params.get("company_name", "")
        company_domain = params.get("company_domain", "")
        industry = params.get("industry", "")

        company_data = {
            "name": company_name,
            "domain": company_domain,
            "industry": industry,
            "size": params.get("company_size", ""),
            "buying_signals": params.get("buying_signals", []),
            "recent_events": params.get("recent_events", []),
        }

        intelligence = generate_account_intelligence(company_data)
        competitors = _detect_competitors(industry)

        report = ResearchReport(
            company_name=company_name,
            company_domain=company_domain,
            industry=industry or intelligence.get("industry", ""),
            company_size=params.get("company_size", ""),
            account_tier=intelligence.get("account_tier", "unknown"),
            buying_intent=intelligence.get("buying_intent", "unknown"),
            icp_match_score=_compute_icp_score(intelligence),
            competitors=competitors,
            recent_news=params.get("recent_news", []),
            buying_signals=params.get("buying_signals", []),
            key_contacts=params.get("key_contacts", []),
            summary=intelligence.get("summary", ""),
        )

        return AgentResult(
            success=True,
            agent_type=self.agent_type,
            data={
                "research_report": {
                    "company_name": report.company_name,
                    "company_domain": report.company_domain,
                    "industry": report.industry,
                    "company_size": report.company_size,
                    "account_tier": report.account_tier,
                    "buying_intent": report.buying_intent,
                    "icp_match_score": report.icp_match_score,
                    "competitors": report.competitors,
                    "recent_news": report.recent_news,
                    "buying_signals": report.buying_signals,
                    "summary": report.summary,
                },
                "icp_match_score": report.icp_match_score,
                "account_tier": report.account_tier,
                "buying_intent": report.buying_intent,
            },
        )


def _detect_competitors(industry: str) -> list[str]:
    if not industry:
        return []
    industry_lower = industry.lower()
    mapping: dict[str, list[str]] = {
        "saas": ["Salesforce", "HubSpot", "Intercom", "Outreach"],
        "software": ["Microsoft", "Google", "Atlassian", "Salesforce"],
        "finance": ["Bloomberg", "FactSet", "S&P Global", "Moody's"],
        "healthcare": ["Epic", "Cerner", "Medtronic", "Philips"],
        "ecommerce": ["Shopify", "BigCommerce", "Magento", "WooCommerce"],
    }
    for key, competitors in mapping.items():
        if key in industry_lower:
            return competitors
    return []


def _compute_icp_score(intelligence: dict) -> float:
    tier = intelligence.get("account_tier", "")
    intent = intelligence.get("buying_intent", "")
    score = 0.5
    if tier in ("enterprise", "mid_market"):
        score += 0.2
    elif tier == "smb":
        score += 0.1
    if intent == "high":
        score += 0.2
    elif intent == "medium":
        score += 0.1
    return min(score, 1.0)
