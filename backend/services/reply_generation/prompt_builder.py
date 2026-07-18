from __future__ import annotations
from services.reply_generation.generation_models import GenerationContext, GenerationStyle, PROMPT_BUILDER_VERSION
from services.reply_generation.template_library import get_template_instructions
from services.reply_generation.style_engine import get_style_instructions


INDUSTRY_CONTEXT = (
    "You are a sales reply generator for Loqi, an AI-native outbound operating system. "
    "Your role is to draft replies that help salespeople communicate effectively with prospects.\n\n"
    "Rules:\n"
    "- Never make up specific prices, dates, or commitments.\n"
    "- Never claim features that don't exist.\n"
    "- Never use placeholders like [Name] or [Company].\n"
    "- Keep replies concise unless Detailed style is selected.\n"
    "- Always include a clear next step or question.\n"
    "- Match the prospect's tone and communication style.\n"
    "- Reference previous context when available.\n"
    "- Do not apologize for following up — provide value instead.\n"
    "- Proofread: no typos, no markdown artifacts, no trailing spaces.\n"
    "- Never output markdown formatting, headings, or code blocks."
)


def build_system_prompt(context: GenerationContext) -> str:
    """Build the system prompt from generation context.
    
    All prompt construction is isolated here.
    Providers receive only pre-built prompts.
    """
    parts = [INDUSTRY_CONTEXT]

    style_instructions = get_style_instructions(
        GenerationStyle(context.style_name)
        if context.style_name else GenerationStyle.PROFESSIONAL
    )
    parts.append(f"\nStyle Instructions:\n{style_instructions}")

    template_instructions = get_template_instructions(context)
    parts.append(f"\nTemplate Instructions:\n{template_instructions}")

    return "\n\n".join(parts)


def build_user_prompt(context: GenerationContext) -> str:
    """Build the user prompt containing conversation context."""
    sections = []

    sections.append("## Conversation Context")
    sections.append(f"Stage: {context.conversation_stage or 'Active'}")
    sections.append(f"Summary: {context.executive_summary or 'No summary available.'}")
    if context.health_score:
        sections.append(f"Health: {context.health_score}/100")

    if context.latest_messages:
        sections.append("\n## Recent Messages")
        for msg in context.latest_messages[-3:]:
            sections.append(f"- {msg[:200]}")

    if context.buying_signals:
        sections.append("\n## Buying Signals Detected")
        for signal in context.buying_signals:
            sections.append(f"- {signal}")

    if context.objections:
        sections.append("\n## Objections")
        for obj in context.objections:
            cat = obj.get("category", "unknown")
            sev = obj.get("severity", "medium")
            sections.append(f"- {cat} ({sev})")

    if context.key_entities:
        sections.append("\n## Key Entities")
        for entity in context.key_entities:
            sections.append(f"- {entity}")

    if context.memory_facts:
        sections.append("\n## Known Facts")
        for fact in context.memory_facts:
            sections.append(f"- {fact}")

    if context.policy_results:
        sections.append("\n## Policy Results")
        for policy in context.policy_results:
            sections.append(f"- {policy}")

    sections.append("\n## Reasoning Summary")
    sections.append(f"Decision: {context.decision_type.replace('_', ' ').title()}")
    sections.append(f"Priority: {context.decision_priority.title()}")
    sections.append(f"Goal: {context.primary_goal.replace('_', ' ').title()}")
    if context.alternative_goal:
        sections.append(f"Alternative Goal: {context.alternative_goal.replace('_', ' ').title()}")
    sections.append(f"Confidence: {context.decision_confidence:.0%}")
    sections.append(f"Target Action: {context.target_action}")
    if context.risk_level:
        sections.append(f"Risk Level: {context.risk_level.title()}")

    sections.append("\n## Task")
    sections.append("Generate a reply to the prospect based on the above context. "
                    "Follow the style and template instructions precisely. "
                    "Output only the reply content — no preamble, no explanation, no markdown.")

    return "\n".join(sections)
