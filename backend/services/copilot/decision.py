"""Intent and bounded read classification for a Copilot turn."""
from __future__ import annotations

import json
import re

import services.ai as ai_service


def decide_copilot_intent(
    user_message: str,
    *,
    workspace_context: dict | None = None,
    message_history: list[dict] | None = None,
    active_search: dict | None = None,
) -> dict:
    """Make the agent's intent/tool decision before response generation."""
    ai_service._log(f"COPILOT_INTENT_ROUTER_ENTER message_chars={len(user_message)} history_len={len(message_history or [])}")
    system = (
        "You are Loqi's intent and goal router. Return JSON only with keys intent, mode, action, plan, "
        "search_context, lead_ids, filters, sort, limit, campaign_id, draft_id, draft_ids, conversation_id, knowledge_query, knowledge_categories, knowledge_item_id, analytics_scope, edit_request, send_at, reply_body, confirmed, reason. Omit fields that do not apply.\n"
        "Allowed intent values: conversation, discovery, discovery_refinement, read, action, clarification.\n"
        "Use conversation for greetings, acknowledgements, and ordinary chat.\n"
        "Use discovery for a new explicit request to find/source/provide leads, prospects, or companies.\n"
        "Use discovery_refinement only when the user explicitly changes an existing Discovery request.\n"
        "Use read for questions about existing results. When the user asks to inspect or transform existing "
        "leads, set the appropriate lead action: lead.read for showing them, lead.rank for strongest/best/top "
        "results (including a requested limit), and lead.filter for applying criteria to existing results.\n"
        "Use action when the user requests another product operation, even if that capability is not available yet.\n"
        "For lead operations, set action to exactly one of lead.read, lead.filter, lead.rank, lead.save, "
        "lead.approve, lead.reject, or lead.attach. Use lead.read/filter/rank for reading existing leads; "
        "use lead.save/approve/reject/attach only when the user explicitly requests that mutation.\n"
        "For lead operations, include lead_ids when the user refers to selected leads, filters for field filters, "
        "sort for ranking and campaign_id for attaching. Never invent lead IDs; resolve references from active_search "
        "and page context. The server, not your confirmed field, is the authority for mutation confirmation.\n"
        "For campaign operations, set action to campaign.list/read/drafts for reads, campaign.create for creating "
        "a campaign from current leads, campaign.refine for explicit changes to the active campaign, campaign.plan "
        "for strategy planning, and campaign.generate_drafts for drafting outreach. Include campaign_id and a "
        "structured campaign or campaign_updates object when needed. Use the active campaign/page context for "
        "references such as 'this campaign' or 'these leads'.\n"
        "For outreach/draft operations, set action to outreach.drafts.read to inspect drafts, "
        "outreach.draft.generate to start existing draft generation, outreach.draft.refine to rewrite a draft, "
        "outreach.draft.approve to approve, outreach.draft.schedule to schedule, or outreach.draft.send to send. "
        "Include draft_id, campaign_id, edit_request, and send_at as applicable. Sending and scheduling "
        "always require explicit confirmation; never infer confirmation. Resolve draft references from page context.\n"
        "For Inbox/conversation operations, set action to inbox.conversation.read/summary/analyze/recommend, "
        "inbox.reply.generate, or inbox.reply.send. Include conversation_id and reply_body when applicable. "
        "Reading, summarizing, analyzing, recommending, and generating a reply never send anything. Sending "
        "must use the existing reply path and requires explicit user confirmation validated by the server.\n"
        "For Knowledge requests, use knowledge.search for grounded workspace Knowledge retrieval and knowledge.read "
        "when reading a specific item. Include knowledge_query and optional knowledge_categories (company, icp, "
        "messaging, sales_offer). Use current page/company/lead/campaign context to focus the query when available. "
        "Never claim Knowledge was used when retrieval returns no items or sources.\n"
        "For Analytics requests, use only read-only registered tools: analytics.workspace.summary, "
        "analytics.campaign.summary, or analytics.leads.summary. Use campaign_id from the current page/context "
        "when the user asks about a specific campaign. Return only metrics present in the authoritative result; "
        "do not infer rates, totals, trends, or performance when the backend does not provide them.\n"
        "Strategic read examples: 'which replies need attention?' -> inbox.conversation.recommend; "
        "'why is this campaign underperforming?' -> analytics.campaign.summary; "
        "'which leads should I prioritize?' -> lead.rank when a Discovery is selected; "
        "'what should I change in my outreach?' -> outreach.drafts.read or analytics.campaign.summary "
        "using the current campaign/draft context; 'rewrite this draft' -> outreach.draft.refine with an edit_request; "
        "'what happened with this prospect?' -> inbox.conversation.analyze/read using the selected conversation.\n"
        "Use clarification only when the user's goal is genuinely ambiguous.\n"
        "For a compound request that needs more than one existing tool, include plan as an ordered list of no more "
        "than three objects. Each object must contain action and only the fields needed by that registered tool. "
        "Plan read/retrieval steps before at most one mutation. Do not include a later step after discovery.search "
        "or discovery.refine because those return an asynchronous job. Do not include plan for a single-tool request. "
        "Never include workspace_id, user_id, confirmation authority, or invented resource IDs in a plan.\n"
        "CRITICAL: active_search is context, not an instruction. It must never turn an unrelated message "
        "such as 'hi' into discovery or discovery_refinement. Only use it for an explicit refinement or read request.\n"
        "mode is new or refine. For discovery_refinement, preserve existing structured fields and apply only "
        "the requested changes. For a new discovery, replace the prior context.\n"
        "search_context must use only these fields: industry (list of strings), location (list of strings), "
        "decision_makers (list of strings), quantity (integer or null).\n"
        "Never claim that a job ran or completed.\n"
        "Examples of the decision contract:\n"
        "- active Discovery + 'find the best 5' -> {intent:'read', action:'lead.rank', sort:'best'}\n"
        "- active Discovery + 'show the strongest leads' -> {intent:'read', action:'lead.rank', sort:'best'}\n"
        "- active Discovery + 'only restaurant owners' -> {intent:'read', action:'lead.filter', filters:{...}}\n"
        "- 'show my campaigns' -> {intent:'read', action:'campaign.list'}\n"
        "- 'create a campaign for these leads' -> {intent:'action', action:'campaign.create', campaign:{...}}\n"
        "- active campaign + 'draft outreach for these' -> {intent:'action', action:'campaign.generate_drafts'}\n"
        "- 'show my drafts' -> {intent:'read', action:'outreach.drafts.read'}\n"
        "- 'make this draft shorter' or 'rewrite this draft' -> {intent:'action', action:'outreach.draft.refine', draft_id:'...', edit_request:'...'}\n"
        "- 'summarize this conversation' -> {intent:'read', action:'inbox.conversation.summary'}\n"
        "- 'draft a reply to this' -> {intent:'read', action:'inbox.reply.generate'}\n"
        "- 'send that reply' -> {intent:'action', action:'inbox.reply.send', confirmed:true}\n"
        "- 'what is our ICP?' -> {intent:'read', action:'knowledge.search', knowledge_categories:['icp']}\n"
        "- 'what do we know about this company?' -> {intent:'read', action:'knowledge.search'}\n"
        "- 'how are my campaigns performing?' -> {intent:'read', action:'analytics.workspace.summary'}\n"
        "- active campaign + 'show performance' -> {intent:'read', action:'analytics.campaign.summary'}\n"
        "These examples describe goals and tool selection; infer the structured filter from the available lead "
        "schema and context. Do not copy message text into a Discovery query.\n"
    )
    user = json.dumps({
        "message": user_message,
        "history": (message_history or [])[-12:],
        "active_search": active_search or {},
        "workspace_context": workspace_context or {},
    }, ensure_ascii=False, default=str)
    raw = ai_service.try_send_openai_request(system, user, timeout=20)
    if not raw:
        ai_service._log("COPILOT_INTENT_ROUTER_EMPTY reason=model_unavailable_or_error")
        return {"intent": "clarification", "mode": "new", "search_context": {}, "reason": "Intent router unavailable"}
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").removeprefix("json").strip()
        decision = json.loads(cleaned)
    except (TypeError, ValueError, json.JSONDecodeError):
        ai_service._log(f"Copilot intent router returned invalid JSON: {raw[:200]}")
        return {"intent": "clarification", "mode": "new", "search_context": {}, "reason": "Invalid intent decision"}
    intent_aliases = {"lead_discovery": "discovery", "informational": "conversation"}
    if not isinstance(decision, dict):
        ai_service._log("COPILOT_INTENT_ROUTER_INVALID decision_shape=true")
        return {"intent": "clarification", "mode": "new", "search_context": {}, "reason": "Invalid intent decision"}
    intent = intent_aliases.get(str(decision.get("intent") or ""), str(decision.get("intent") or ""))
    if intent not in {"conversation", "discovery", "discovery_refinement", "read", "action", "clarification"}:
        ai_service._log("COPILOT_INTENT_ROUTER_INVALID intent=true")
        return {"intent": "clarification", "mode": "new", "search_context": {}, "reason": "Invalid intent decision"}
    raw_context = decision.get("search_context") or {}
    if not isinstance(raw_context, dict):
        raw_context = {}

    def _string_list(value):
        return [str(item).strip() for item in (value or []) if str(item).strip()]

    context = {
        "industry": _string_list(raw_context.get("industry")),
        "location": _string_list(raw_context.get("location")),
        "decision_makers": _string_list(raw_context.get("decision_makers")),
        "quantity": int(raw_context["quantity"]) if str(raw_context.get("quantity") or "").isdigit() else None,
    }
    normalized = {
        "intent": intent,
        "mode": "refine" if decision.get("mode") == "refine" else "new",
        "search_context": context,
        "action": str(decision.get("action") or decision.get("tool") or "").strip(),
        "lead_ids": [str(item).strip() for item in (decision.get("lead_ids") or []) if str(item).strip()],
        "filters": decision.get("filters") if isinstance(decision.get("filters"), dict) else {},
        "sort": str(decision.get("sort") or "").strip(),
        "limit": int(decision["limit"]) if str(decision.get("limit") or "").isdigit() else None,
        "campaign_id": str(decision.get("campaign_id") or "").strip(),
        "draft_id": str(decision.get("draft_id") or "").strip(),
        "draft_ids": [str(item).strip() for item in (decision.get("draft_ids") or []) if str(item).strip()],
        "conversation_id": str(decision.get("conversation_id") or "").strip(),
        "edit_request": str(decision.get("edit_request") or "").strip(),
        "send_at": str(decision.get("send_at") or "").strip(),
        "reply_body": str(decision.get("reply_body") or decision.get("body") or "").strip(),
        "knowledge_query": str(decision.get("knowledge_query") or "").strip(),
        "knowledge_categories": [str(item).strip() for item in (decision.get("knowledge_categories") or []) if str(item).strip()],
        "knowledge_item_id": str(decision.get("knowledge_item_id") or decision.get("item_id") or "").strip(),
        "analytics_scope": str(decision.get("analytics_scope") or "").strip(),
        "campaign": decision.get("campaign") if isinstance(decision.get("campaign"), dict) else {},
        "campaign_updates": decision.get("campaign_updates") if isinstance(decision.get("campaign_updates"), dict) else {},
        "force": bool(decision.get("force")),
        "confirmed": bool(decision.get("confirmed")),
        "reason": str(decision.get("reason") or "").strip(),
        "plan": decision.get("plan") if isinstance(decision.get("plan"), list) else [],
    }
    if intent == "discovery_refinement" and not active_search:
        normalized = {
            "intent": "clarification", "mode": "new", "search_context": {}, "action": "",
            "reason": "A Discovery refinement requires an active Discovery context.",
        }
    ai_service._log(f"COPILOT_INTENT_ROUTER_DECISION intent={normalized['intent']} mode={normalized['mode']} context={context}")
    return normalized


def classify_copilot_read_question(
    user_message: str,
    *,
    page_context: dict | None = None,
    active_search: dict | None = None,
    message_history: list[dict] | None = None,
) -> dict | None:
    """Route clear MVP read questions without a second model call."""
    text = " ".join(str(user_message or "").lower().split())
    page = page_context or {}
    active = active_search or {}
    campaign_id = str(page.get("campaign_id") or page.get("active_campaign_id") or "").strip()
    draft_id = str(page.get("draft_id") or page.get("active_draft_id") or "").strip()
    conversation_id = str(page.get("conversation_id") or page.get("active_conversation_id") or page.get("thread_id") or "").strip()
    discovery_id = str(active.get("discovery_id") or page.get("discovery_id") or "").strip()
    history = message_history or []
    prior = " ".join(
        str(item.get("text") or item.get("content") or "").lower()
        for item in history[-4:]
        if item.get("role") == "user"
    )
    subject = f"{text} {prior}".strip()
    result = {
        "intent": "read", "mode": "new", "search_context": {}, "action": "",
        "campaign_id": campaign_id, "draft_id": draft_id, "conversation_id": conversation_id,
        "reason": "bounded MVP read classification",
    }
    if re.search(r"\b(repl(?:y|ies)|inbox|prospect conversations?)\b", subject) and re.search(r"attention|follow.?up|urgent|need", subject):
        result["action"] = "inbox.conversation.recommend"
        return result
    if re.search(r"\b(what happened|history|conversation|prospect)\b", text):
        result["action"] = "inbox.conversation.analyze" if conversation_id else "inbox.conversation.recommend"
        return result
    if re.search(r"\b(rewrite|refine|edit)\b", text):
        return None
    if re.search(r"\b(review|improve|shorter|better messaging|draft)\b", text):
        result["action"] = "outreach.drafts.read"
        return result
    if re.search(r"\b(leads?|prospects?)\b", text) and re.search(r"prioriti[sz]|best|strongest|top|focus", text):
        if not discovery_id:
            return None
        result["action"] = "lead.rank"
        result["sort"] = "best"
        return result
    if re.search(r"\b(underperform\w*|perform\w*|performance|metrics?|results?)\b", subject) and re.search(r"campaign|outreach", subject):
        result["action"] = "analytics.campaign.summary" if campaign_id else "analytics.workspace.summary"
        return result
    if re.search(r"\b(what should i do next|next step|what should i change|change in my outreach)\b", text):
        result["action"] = "analytics.campaign.summary" if campaign_id else "analytics.workspace.summary"
        return result
    if text in {"why", "why?", "how so", "tell me more"} and prior:
        if re.search(r"campaign|performance|underperform", prior):
            result["action"] = "analytics.campaign.summary" if campaign_id else "analytics.workspace.summary"
            return result
        if re.search(r"draft|outreach|messaging", prior):
            result["action"] = "outreach.drafts.read"
            return result
        if re.search(r"reply|prospect|conversation", prior):
            result["action"] = "inbox.conversation.analyze" if conversation_id else "inbox.conversation.recommend"
            return result
    return None
