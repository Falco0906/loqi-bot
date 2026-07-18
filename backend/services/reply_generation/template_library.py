from __future__ import annotations
from services.reply_generation.generation_models import GenerationContext, GenerationTemplate

TEMPLATE_REGISTRY: dict[str, str] = {}


def register_template(name: str, instructions: str) -> None:
    TEMPLATE_REGISTRY[name] = instructions


def select_template(context: GenerationContext) -> str:
    """Select the best template based on context signals."""
    goal = context.primary_goal.lower()

    if "pricing" in goal or "budget" in goal:
        return "pricing_response"
    if "demo" in goal:
        return "demo_confirmation"
    if "meeting" in goal or "schedule" in goal:
        return "meeting_scheduling"
    if "objection" in goal or "overcome" in goal:
        return "objection_handling"
    if "question" in goal or "technical" in goal or "information" in context.decision_type:
        return "technical_question" if context.buying_signals else "clarification"
    if "engage" in goal or "follow" in goal:
        return "re_engagement"
    if "confirm" in goal or "interest" in goal:
        return "thank_you"
    if context.decision_type in ("wait", "continue_nurturing"):
        return "follow_up"

    return "general_reply"


def get_template_instructions(context: GenerationContext) -> str:
    """Get full template instructions for the selected template."""
    template_name = select_template(context)
    instructions = TEMPLATE_REGISTRY.get(template_name, TEMPLATE_REGISTRY.get("general_reply", ""))
    return _fill_template(instructions, context)


def _fill_template(template: str, context: GenerationContext) -> str:
    """Fill template placeholders with context values.
    
    Every placeholder key must be handled here.
    No literal placeholder syntax should ever reach the LLM.
    """
    replacements = {
        "{primary_goal}": context.primary_goal.replace("_", " ").title(),
        "{alternative_goal}": context.alternative_goal.replace("_", " ").title() if context.alternative_goal else "Nurture",
        "{decision_type}": context.decision_type.replace("_", " ").title(),
        "{conversation_stage}": context.conversation_stage.replace("_", " ").title() if context.conversation_stage else "Active",
        "{risk_level}": context.risk_level.title() if context.risk_level else "Low",
        "{health_score}": str(context.health_score),
        "{decision_confidence:.0%}": f"{context.decision_confidence:.0%}",
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


register_template("pricing_response", """
Primary goal: Provide pricing information to {primary_goal}.
Decision confidence: {decision_confidence:.0%}.
Include relevant pricing tiers or ranges.
Address any budget concerns directly.
Offer to schedule a call for detailed discussion if needed.
Do not make up specific prices — use ranges where exact figures are unknown.
""")

register_template("demo_confirmation", """
Primary goal: Confirm and schedule a product demonstration for {primary_goal}.
Decision confidence: {decision_confidence:.0%}.
Confirm interest and propose specific times.
Briefly mention what the demo will cover.
Make it easy for the prospect to confirm.
""")

register_template("objection_handling", """
Primary goal: Address prospect objections for {primary_goal}.
Decision confidence: {decision_confidence:.0%}.
Acknowledge the concern before addressing it.
Use evidence and case studies where appropriate.
Keep the tone empathetic and solution-oriented.
""")

register_template("meeting_scheduling", """
Primary goal: Schedule a meeting for {primary_goal}.
Decision confidence: {decision_confidence:.0%}.
Propose 2-3 specific time options.
Mention meeting duration and agenda briefly.
Confirm timezone and preferred format (video/call).
""")

register_template("technical_question", """
Primary goal: Answer technical questions for {primary_goal}.
Decision confidence: {decision_confidence:.0%}.
Provide clear, accurate technical information.
Reference documentation or specifications where relevant.
Offer to connect with engineering team if deeper questions.
""")

register_template("general_reply", """
Primary goal: Respond professionally to prospect for {primary_goal}.
Decision confidence: {decision_confidence:.0%}.
Keep the response concise and relevant.
Maintain a helpful and professional tone.
End with a clear next step or question.
""")

register_template("follow_up", """
Primary goal: Follow up and keep conversation alive for {primary_goal}.
Decision confidence: {decision_confidence:.0%}.
Reference previous conversation briefly.
Add value — new information, case study, or insight.
Keep it short and respectful of their time.
""")

register_template("re_engagement", """
Primary goal: Re-engage prospect for {primary_goal}.
Decision confidence: {decision_confidence:.0%}.
Acknowledge their previous response respectfully.
Provide new value — recent update, relevant content.
Make it easy to re-engage without pressure.
""")

register_template("thank_you", """
Primary goal: Express gratitude and confirm interest for {primary_goal}.
Decision confidence: {decision_confidence:.0%}.
Thank the prospect for their response.
Reinforce key value propositions.
Define clear next steps.
""")

register_template("clarification", """
Primary goal: Ask clarifying questions for {primary_goal}.
Decision confidence: {decision_confidence:.0%}.
Ask specific, relevant questions.
Keep it brief — respect their time.
Explain why the information helps them.
""")
