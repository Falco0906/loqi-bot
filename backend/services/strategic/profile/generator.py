"""Strategic Intelligence Service for generating organization profiles from onboarding data."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from services.intelligence.ai import OpenAIError, _send_openai_request


class StrategicProfileGenerator:
    """Generates structured strategic profiles from onboarding conversation data."""

    _TEXT_FIELDS = (
        "COMPANY_SUMMARY", "INDUSTRY", "BUSINESS_MODEL", "PRODUCT", "ICP",
        "DIFFERENTIATION", "MARKET_POSITION", "COMPETITIVE_LANDSCAPE",
        "PRIMARY_OBJECTIVE", "CURRENT_CONSTRAINTS", "MESSAGING",
    )
    _LIST_FIELDS = ("RISKS", "GROWTH_OPPORTUNITIES", "KNOWN_UNKNOWNS")
    RESPONSE_FORMAT = {
        "type": "json_schema",
        "name": "onboarding_strategic_profile",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                **{key: {"type": "string"} for key in _TEXT_FIELDS},
                **{key: {"type": "array", "items": {"type": "string"}} for key in _LIST_FIELDS},
                "BUYER_PERSONAS": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {key: {"type": "string"} for key in ("name", "title", "motivation", "objections")},
                        "required": ["name", "title", "motivation", "objections"],
                        "additionalProperties": False,
                    },
                },
                "CONFIDENCE_LEVELS": {
                    "type": "object",
                    "properties": {"overall": {"type": "string"}},
                    "required": ["overall"],
                    "additionalProperties": False,
                },
            },
            "required": [
                *_TEXT_FIELDS, *_LIST_FIELDS, "BUYER_PERSONAS", "CONFIDENCE_LEVELS",
            ],
            "additionalProperties": False,
        },
    }

    SYSTEM_PROMPT = """You are Loqi, an AI Chief of Staff for B2B companies. Your task is to analyze onboarding conversation data and generate a structured strategic organization profile.

Analyze only the following user-provided information:
- Company description (what they do)
- Ideal customer (who buys from them)
- Differentiation (why they're better)
- Annual goal (what they want to achieve)
- Biggest obstacle (what's blocking them)
- Website URL (if provided; its contents have NOT been retrieved)

Separate user statements from interpretation. Do not invent market research,
competitors, customer pain, or industry facts absent from these answers.
Use "Unknown" or KNOWN_UNKNOWNS when the evidence is insufficient.

Generate a strategic profile with the following structure:

1. COMPANY_SUMMARY: One-sentence summary grounded in their answer; do not invent a market position

2. INDUSTRY: Industry category only if supported by the answers, otherwise "Unknown"

3. BUSINESS_MODEL: How they make money if stated or clear from the answer, otherwise "Unknown"

4. PRODUCT: Core product/service offering in 1-2 sentences

5. ICP: Ideal Customer Profile using only stated size, industry, titles, and pains; mark unknowns plainly

6. BUYER_PERSONAS: Personas only where the answers support them; never invent real names or details; use [] if unknown

7. DIFFERENTIATION: Their competitive advantage expressed as strategic positioning (not just features)

8. MARKET_POSITION: Where they sit only if supported, otherwise "Unknown"

9. COMPETITIVE_LANDSCAPE: Known alternatives only; otherwise "Unknown"

10. PRIMARY_OBJECTIVE: Their stated goal translated into strategic terms

11. CURRENT_CONSTRAINTS: What's blocking them, expressed as strategic dependencies

12. RISKS: Strategic risks based on their situation

13. GROWTH_OPPORTUNITIES: Where they could expand or improve

14. MESSAGING: Recommended value proposition and key messages

15. CONFIDENCE_LEVELS: Confidence (high/medium/low) for each major section

16. KNOWN_UNKNOWNS: What information is missing that would improve the profile

Output ONLY valid JSON with these exact keys. Keep each string concise. Use "Unknown" for unsupported text claims and [] for unsupported lists. For CONFIDENCE_LEVELS, provide an overall high/medium/low assessment. Think like a founder-level operator giving strategic advice, not a chatbot summarizing inputs."""

    def _parse_profile_json(self, content: str) -> dict[str, Any]:
        text = content.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()
        profile = json.loads(text)
        # These are the fields the onboarding review actually needs. Secondary
        # sections can be absent when the model has no evidence for them.
        required_text = (
            "COMPANY_SUMMARY", "ICP", "DIFFERENTIATION",
            "PRIMARY_OBJECTIVE", "CURRENT_CONSTRAINTS",
        )
        if (not isinstance(profile, dict)
                or any(not isinstance(profile.get(key), str) or not profile[key].strip()
                       for key in required_text)):
            raise OpenAIError("Strategic profile response was incomplete", kind="invalid_output")
        optional_text = (
            "INDUSTRY", "BUSINESS_MODEL", "PRODUCT", "MARKET_POSITION",
            "COMPETITIVE_LANDSCAPE", "MESSAGING",
        )
        optional_lists = ("BUYER_PERSONAS", "RISKS", "GROWTH_OPPORTUNITIES", "KNOWN_UNKNOWNS")
        for key in optional_text:
            if not isinstance(profile.get(key), str) or not profile[key].strip():
                profile[key] = "Unknown"
        for key in optional_lists:
            if not isinstance(profile.get(key), list):
                profile[key] = []
        if not isinstance(profile.get("CONFIDENCE_LEVELS"), dict):
            profile["CONFIDENCE_LEVELS"] = {}
        return profile

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
                self.RESPONSE_FORMAT,
            )
            return self._parse_profile_json(content)
        except json.JSONDecodeError as error:
            raise OpenAIError("Strategic profile response was not valid JSON", kind="invalid_output") from error


_profile_generator: StrategicProfileGenerator | None = None


def get_profile_generator() -> StrategicProfileGenerator:
    """Get or create the global profile generator instance."""
    global _profile_generator
    if _profile_generator is None:
        _profile_generator = StrategicProfileGenerator()
    return _profile_generator
