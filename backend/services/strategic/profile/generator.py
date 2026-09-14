"""Strategic Intelligence Service for generating organization profiles from onboarding data."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from services.ai import OpenAIError, _send_openai_request


class StrategicProfileGenerator:
    """Generates structured strategic profiles from onboarding conversation data."""

    SYSTEM_PROMPT = """You are Loqi, an AI Chief of Staff for B2B companies. Your task is to analyze onboarding conversation data and generate a structured strategic organization profile.

Analyze the following information:
- Company description (what they do)
- Ideal customer (who buys from them)
- Differentiation (why they're better)
- Annual goal (what they want to achieve)
- Biggest obstacle (what's blocking them)
- Website content (if provided)

Generate a strategic profile with the following structure:

1. COMPANY_SUMMARY: One-sentence executive summary of what they do (not just repeating their description, but synthesizing it into a market position)

2. INDUSTRY: Industry category with specific vertical (e.g., "B2B SaaS - Sales Automation")

3. BUSINESS_MODEL: How they make money (e.g., "SaaS subscription", "Agency services", "Product + Services")

4. PRODUCT: Core product/service offering in 1-2 sentences

5. ICP: Ideal Customer Profile - who they sell to, including:
   - Company size/tier
   - Industry focus
   - Job titles of buyers
   - Key pain points they solve

6. BUYER_PERSONAS: 2-3 specific buyer personas with names, titles, motivations, and objections

7. DIFFERENTIATION: Their competitive advantage expressed as strategic positioning (not just features)

8. MARKET_POSITION: Where they sit in the competitive landscape (e.g., "Challenger in a crowded market, differentiated by...")

9. COMPETITIVE_LANDSCAPE: Who they compete against and how

10. PRIMARY_OBJECTIVE: Their stated goal translated into strategic terms

11. CURRENT_CONSTRAINTS: What's blocking them, expressed as strategic dependencies

12. RISKS: Strategic risks based on their situation

13. GROWTH_OPPORTUNITIES: Where they could expand or improve

14. MESSAGING: Recommended value proposition and key messages

15. CONFIDENCE_LEVELS: Confidence (high/medium/low) for each major section

16. KNOWN_UNKNOWNS: What information is missing that would improve the profile

Output ONLY valid JSON with these exact keys. Be concise but insightful. Think like a founder-level operator giving strategic advice, not a chatbot summarizing inputs."""

    def _fallback_profile(
        self,
        company_description: str,
        ideal_customer: str,
        differentiation: str,
        annual_goal: str,
        biggest_obstacle: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        profile: dict[str, Any] = {
            "COMPANY_SUMMARY": (company_description or "")[:200],
            "INDUSTRY": "Technology",
            "BUSINESS_MODEL": "Unknown",
            "PRODUCT": (company_description or "")[:200],
            "ICP": (ideal_customer or "")[:200],
            "BUYER_PERSONAS": [],
            "DIFFERENTIATION": (differentiation or "")[:200],
            "MARKET_POSITION": "Undifferentiated",
            "COMPETITIVE_LANDSCAPE": "Not analyzed",
            "PRIMARY_OBJECTIVE": (annual_goal or "")[:200],
            "CURRENT_CONSTRAINTS": (biggest_obstacle or "")[:200],
            "RISKS": ["Unknown"],
            "GROWTH_OPPORTUNITIES": [],
            "MESSAGING": "To be determined",
            "CONFIDENCE_LEVELS": {"overall": "low"},
            "KNOWN_UNKNOWNS": ["Strategic profile generation failed"],
        }
        if error:
            profile["_error"] = error
        return profile

    def _parse_profile_json(self, content: str) -> dict[str, Any]:
        text = content.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()
        return json.loads(text)

    async def generate_profile(
        self,
        company_description: str,
        ideal_customer: str,
        differentiation: str,
        annual_goal: str,
        biggest_obstacle: str,
        website: str | None = None,
    ) -> dict[str, Any]:
        """Generate a strategic profile from onboarding data."""
        user_text = f"""Onboarding Data:

Company Description: {company_description}

Ideal Customer: {ideal_customer}

Differentiation: {differentiation}

Annual Goal: {annual_goal}

Biggest Obstacle: {biggest_obstacle}

{website if website else "No website provided."}

Generate a strategic organization profile based on this data."""

        try:
            content = await asyncio.to_thread(
                _send_openai_request,
                self.SYSTEM_PROMPT,
                user_text,
            )
            return self._parse_profile_json(content)
        except json.JSONDecodeError as e:
            return self._fallback_profile(
                company_description,
                ideal_customer,
                differentiation,
                annual_goal,
                biggest_obstacle,
                error=str(e),
            )
        except OpenAIError as e:
            return self._fallback_profile(
                company_description,
                ideal_customer,
                differentiation,
                annual_goal,
                biggest_obstacle,
                error=str(e),
            )
        except Exception as e:
            return self._fallback_profile(
                company_description,
                ideal_customer,
                differentiation,
                annual_goal,
                biggest_obstacle,
                error=str(e),
            )


_profile_generator: StrategicProfileGenerator | None = None


def get_profile_generator() -> StrategicProfileGenerator:
    """Get or create the global profile generator instance."""
    global _profile_generator
    if _profile_generator is None:
        _profile_generator = StrategicProfileGenerator()
    return _profile_generator
