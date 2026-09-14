"""Grounded natural-language response generation for Copilot turns."""
from __future__ import annotations

import json

import services.ai as ai_service


def generate_copilot_response(
    user_message: str,
    copilot_context: dict | None = None,
    context: dict | None = None,
) -> str:
    """Generate a response for the Copilot.

    The frontend sends structured data. This function merges the system prompt,
    page context, workspace snapshot, workspace analysis, conversation history,
    and user message before calling the LLM.
    """
    ctx = copilot_context or {}
    if ctx.get("intent") == "conversation":
        # Conversation is a real terminal intent for this turn. Do not feed
        # workspace priorities/search state into the proactive operator prompt
        # or offer action markup for an operation the user did not request.
        return "I’m here to help with your Loqi workspace. What would you like to work on?"
    current_page = ctx.get("current_page", "unknown")
    page_context = ctx.get("page_context") or {}
    available_actions = ctx.get("available_actions") or []
    message_history = ctx.get("message_history") or []
    authoritative_result = ctx.get("authoritative_result")
    authoritative_only = bool(ctx.get("mvp_read_only") and authoritative_result is not None)

    system = (
        "You are Loqi's Strategic Assistant for the user's outbound workspace.\n"
        "You answer questions, analyze the supplied Loqi data, and make clearly labeled recommendations.\n"
        "Do not claim that an action was executed, completed, or failed: the application reports\n"
        "those states from the real operation. Never invent leads, campaign state, inbox events,\n"
        "metrics, or results that are not present in the supplied context.\n\n"
        "Core principles:\n"
        "- Answer the question directly using the supplied facts.\n"
        "- Separate facts from interpretation: use 'Fact:' and 'Recommendation:' when both are present.\n"
        "- Recommendations must be grounded in the supplied records and must not imply that a mutation occurred.\n"
        "- Never say \"There are\", \"The workspace contains\", \"Please provide more context\", or \"How can I help you today?\".\n"
        "- Speak like an experienced operator, but say when evidence is missing.\n"
        "- Do not add action buttons or suggest that a state-changing tool ran unless the user explicitly asks for it.\n"
        "- Keep responses concise (2-5 sentences). Use short paragraphs.\n"
        "- When user says \"this\" or \"it\", infer the referent from context or the last thing you discussed.\n\n"
        f"Page-aware behavior:\n"
        f"- When on Campaign page: talk about drafts, personalization quality, readiness to launch, lead sources.\n"
        f"- When on Draft Review page: act like a senior SDR writing coach. Identify problems, explain why they matter, and only rewrite when asked. Never start by saying you rewrote the draft. Start with observation and reasoning. Use the Draft Intelligence data to explain what to improve and why.\n"
        f"- When discussing drafts, think strategically: reference the buyer persona, company context, messaging strategy, predicted objections, and recommended CTA from Draft Intelligence. Ask questions like 'Would a CTO care about this?' or 'Should we address the budget concern?'\n"
        f"- Use buyer psychology to explain WHY a change matters, not just WHAT changed.\n"
        f"- When on Discovery page: talk about searches, lead quality, industries, campaign ideas.\n"
        f"- When on Mission Control: talk about overall priorities, health, next actions, cross-campaign insights.\n"
        f"- When on Campaign Intelligence: talk about performance, trends, what to optimize.\n"
        f"Current page: {current_page}\n"
        f"- Tailor everything to this page. If the user is on a Campaign page, do NOT talk about Discovery search results.\n"
        f"- If the user is on Draft Review, do NOT talk about finding leads.\n"
        f"- Reference things visible on the current page first, then mention related things elsewhere.\n\n"
    )

    if ctx.get("mvp_read_only"):
        system += (
            "\nMVP READ-ONLY MODE:\n"
            "- Use only the authoritative tool result below for claims about the user's data.\n"
            "- Do not propose or imply campaign creation, draft approval, sending, scheduling, or other mutations.\n"
            "- If the result is empty or unavailable, say that plainly; do not fill the gap from general knowledge.\n"
            "- Keep the response conversational and useful, with facts first and recommendations only when supported.\n"
        )

    if available_actions:
        system += "\nAvailable actions on this page:\n"
        for a in available_actions:
            system += f"- {a}\n"

    if page_context and not authoritative_only:
        system += f"\nPage context:\n{json.dumps(page_context, indent=2)}\n"

    wc = ctx.get("workspace_context", {})
    snapshot = wc.get("snapshot", {})
    analysis = wc.get("analysis", {})
    copilot_memory = wc.get("copilot_memory", {})

    if authoritative_result is not None:
        system += (
            "\n--- Authoritative Tool Result ---\n"
            f"Tool: {ctx.get('authoritative_tool', 'read')}\n"
            "This structured result is the source of truth for this answer.\n"
            f"{json.dumps(authoritative_result, ensure_ascii=False, default=str)[:18000]}\n"
        )

    if copilot_memory:
        remembered_turns = copilot_memory.get("conversation_turns") or []
        workspace_history = copilot_memory.get("workspace_history") or []
        unfinished_task = copilot_memory.get("unfinished_task")
        user_preferences = copilot_memory.get("user_preferences") or {}
        if remembered_turns or workspace_history or unfinished_task or user_preferences:
            system += (
                "\n--- Remembered Copilot Context ---\n"
                "This is bounded historical context, not current workspace truth. "
                "Verify any current-state claim through the authoritative tool result or canonical reads.\n"
            )
            if remembered_turns:
                for turn in remembered_turns[-6:]:
                    if isinstance(turn, dict):
                        system += f"  - {turn.get('role', 'user')}: {str(turn.get('text') or '')[:400]}\n"
            if unfinished_task:
                system += f"Prior unfinished task reference (unverified): {json.dumps(unfinished_task, default=str)}\n"
            if workspace_history:
                system += f"Recent completed Copilot operations: {json.dumps(workspace_history[-3:], default=str)}\n"
            if user_preferences:
                system += f"User preferences: {json.dumps(user_preferences, default=str)}\n"

    knowledge_context = wc.get("knowledge_context")
    if knowledge_context:
        from services.knowledge.context_adapter import format_knowledge_context
        knowledge_text = format_knowledge_context(knowledge_context)
        if knowledge_text:
            system += f"\n{knowledge_text}\n"

    if snapshot and not authoritative_only:
        campaigns = snapshot.get("campaigns", [])
        drafts = snapshot.get("drafts", {})
        timeline = snapshot.get("timeline", [])
        memory = snapshot.get("memory", {})
        jobs = snapshot.get("jobs", {})

        system += f"\n--- Workspace Snapshot ---\n"
        system += f"Total campaigns: {snapshot.get('campaign_count', 0)}\n"
        if campaigns:
            system += "Campaigns:\n"
            for c in campaigns:
                status_display = c.get("status", "?").replace("_", " ")
                system += (
                    f"  - {c.get('name', '?')} ({status_display}): "
                    f"{c.get('lead_count', 0)} leads, "
                    f"{c.get('pending_drafts', 0)} pending, "
                    f"{c.get('approved_drafts', 0)} approved\n"
                )
        system += f"Drafts: {drafts.get('total', 0)} total, {drafts.get('pending', 0)} pending, {drafts.get('approved', 0)} approved\n"
        system += f"Running jobs: {len(jobs.get('running', []))}\n"
        if timeline:
            system += "Recent activity:\n"
            for e in timeline[:5]:
                system += f"  - {e.get('text', '')}\n"
        if memory:
            system += f"Last action: {memory.get('last_action', 'none')}\n"
            if memory.get("last_campaign_name"):
                system += f"Last campaign: {memory['last_campaign_name']}\n"

    if analysis and not authoritative_only:
        cf = analysis.get("current_focus")
        if cf:
            system += f"\nCurrent focus: {cf.get('focus', 'unknown')}\n"
        rna = analysis.get("recommended_next_action")
        if rna:
            system += f"Recommended: {rna.get('title', '')}\n"
        priorities = analysis.get("campaign_priorities", [])
        if priorities:
            system += "Campaign priorities (highest first):\n"
            for cp in priorities[:5]:
                rank_label = cp.get("label", f"#{cp.get('rank', '?')}")
                system += f"  {rank_label}: {cp.get('name', '?')} ({', '.join(cp.get('reasons', []))})\n"
        wc_obj = analysis.get("workflow_continuation")
        if wc_obj:
            system += f"Next step: {wc_obj.get('where', 'Start something new')}\n"
        insights = analysis.get("cross_campaign_insights", [])
        if insights:
            system += "Cross-campaign insights:\n"
            for ins in insights:
                system += f"  - {ins.get('insight', '')}\n"
        attention = analysis.get("attention_items", [])
        if attention:
            system += "Items needing attention:\n"
            for a_item in attention[:3]:
                system += f"  - {a_item.get('title', '')}: {a_item.get('reason', '')}\n"

    current_draft = wc.get("current_draft") if not authoritative_only else None
    if current_draft:
        system += "\n--- Current Draft ---\n"
        system += f"Subject: {current_draft.get('subject', 'N/A')}\n"
        system += f"Recipient: {current_draft.get('lead_name', 'Unknown')} at {current_draft.get('lead_company', 'Unknown')}\n"
        system += f"Preview: {current_draft.get('text_preview', '')}...\n"
        intelligence = current_draft.get("draft_intelligence")
        if intelligence:
            system += "\nDraft Intelligence:\n"
            for cat_key in ["opening_strength", "personalization_quality", "pain_alignment", "relevance", "credibility", "cta_strength", "readability", "length", "tone", "confidence"]:
                cat = intelligence.get(cat_key)
                if cat:
                    label = cat.get("label", "N/A")
                    reason = cat.get("reason", "")
                    system += f"  {cat_key}: {label} — {reason}\n"
            if intelligence.get("patterns"):
                system += f"  Patterns: {', '.join(intelligence['patterns'][:5])}\n"
            if intelligence.get("strengths"):
                system += f"  Strengths: {'; '.join(intelligence['strengths'][:3])}\n"
            if intelligence.get("weaknesses"):
                system += f"  Weaknesses: {'; '.join(intelligence['weaknesses'][:3])}\n"
            if intelligence.get("opportunities"):
                system += f"  Opportunities: {'; '.join(intelligence['opportunities'][:3])}\n"

            persona = intelligence.get("persona")
            if persona:
                system += f"\n  Buyer Persona: {persona.get('role', 'unknown')} ({persona.get('seniority', 'unknown')})\n"
                system += f"  Goals: {'; '.join(persona.get('primary_goals', [])[:2])}\n"
                system += f"  Fears: {'; '.join(persona.get('primary_fears', [])[:2])}\n"
                system += f"  Communication: {', '.join(persona.get('communication_preferences', [])[:2])}\n"

            cc = intelligence.get("company_context")
            if cc:
                system += f"\n  Company: {cc.get('maturity', 'unknown')} — {cc.get('competitive_position', '')}\n"
                system += f"  Pain areas: {'; '.join(cc.get('potential_pain_areas', [])[:2])}\n"

            msg_strategy = intelligence.get("messaging_strategy")
            if msg_strategy:
                system += f"\n  Messaging angle: {msg_strategy.get('primary_angle', '')}\n"
                system += f"  Reasoning: {msg_strategy.get('reasoning', '')}\n"

            cta_rec = intelligence.get("cta_recommendation")
            if cta_rec:
                system += f"\n  Recommended CTA: {cta_rec.get('cta_type', '')}\n"

            objections = intelligence.get("objection_predictions", [])
            if objections:
                system += "\n  Predicted objections:\n"
                for o in objections[:2]:
                    system += f"    - {o.get('objection', '')} ({o.get('likelihood', '')})\n"

            framework = intelligence.get("framework_recommendation")
            if framework:
                system += f"\n  Framework: {framework.get('framework', '')}\n"
        rewrite_history = current_draft.get("rewrite_history", [])
        if rewrite_history:
            system += "\nRecent rewrites:\n"
            for entry in rewrite_history[:3]:
                summary = "; ".join(entry.get("change_summary", []))
                system += f"  - [{entry.get('strategy', 'custom')}] {summary}\n"

    if message_history:
        system += "\n--- Conversation History ---\n"
        for msg in message_history[-6:]:
            role = msg.get("role", "unknown")
            text = msg.get("text", "")[:200]
            system += f"{role}: {text}\n"

    conversation_intel = wc.get("conversation_intelligence") if not authoritative_only else None
    if conversation_intel:
        system += "\n--- Communication Intelligence ---\n"
        system += f"Stage: {conversation_intel.get('current_stage', 'unknown')}\n"
        system += f"Summary: {conversation_intel.get('summary', '')}\n"
        if conversation_intel.get('open_questions'):
            system += f"Open questions: {'; '.join(conversation_intel['open_questions'][:3])}\n"
        if conversation_intel.get('outstanding_objections'):
            system += f"Objections: {'; '.join(conversation_intel['outstanding_objections'][:3])}\n"
        if conversation_intel.get('pain_points'):
            system += f"Pain points: {'; '.join(conversation_intel['pain_points'][:3])}\n"
        if conversation_intel.get('business_goals'):
            system += f"Business goals: {'; '.join(conversation_intel['business_goals'][:3])}\n"
        if conversation_intel.get('buying_signals'):
            system += f"Buying signals: {'; '.join(conversation_intel['buying_signals'][:3])}\n"
        if conversation_intel.get('key_risks'):
            system += f"Risks: {'; '.join(conversation_intel['key_risks'][:3])}\n"
        if conversation_intel.get('key_opportunities'):
            system += f"Opportunities: {'; '.join(conversation_intel['key_opportunities'][:3])}\n"
        if conversation_intel.get('competitor_mentioned'):
            system += f"Competitor: {conversation_intel['competitor_mentioned']}\n"
        if conversation_intel.get('decision_confidence'):
            system += f"Decision confidence: {conversation_intel['decision_confidence']}/100\n"
        if conversation_intel.get('urgency'):
            system += f"Urgency: {conversation_intel['urgency']}\n"
        system += "\nWhen discussing conversations, reason like a Senior SDR. Don't just repeat what the lead said — interpret it. For example, instead of 'They asked about pricing', say 'Pricing requests usually indicate active evaluation rather than casual curiosity. Combined with the implementation questions, I'd classify this as a strong buying signal.' Use the structured intelligence above to provide strategic reasoning.\n"

    providers = wc.get("providers", []) if not authoritative_only else []
    if providers:
        system += "\n--- Connected Providers ---\n"
        for p in providers:
            system += f"  - {p.get('provider_type', '?')} ({p.get('status', '?')})"
            if p.get('email'):
                system += f" — {p['email']}"
            if p.get('last_sync'):
                system += f", last sync: {p['last_sync']}"
            system += "\n"
        ps = wc.get("provider_summary", {})
        if ps:
            system += f"Provider health: {ps.get('healthy', 0)} healthy, {ps.get('offline', 0)} offline\n"
        system += "You can discuss provider health, sync status, and connected accounts.\n"

    user_text = f"User message: {user_message.strip()}"

    ai_service._log(f"Copilot request: page={current_page}, campaigns={snapshot.get('campaign_count', 0)}, focus={analysis.get('current_focus', {}).get('focus', 'none') if analysis else 'none'}, history_len={len(message_history)}")
    response = ai_service.try_send_openai_request(system, user_text, timeout=20)

    if response and len(response.strip()) > 0:
        ai_service._log(f"Copilot response generated: {response[:80]}")
        return response.strip()

    return "I understand what you're looking at. What would you like me to do?"
