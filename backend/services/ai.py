import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _log(message: str) -> None:
    print(f"[ai] {message}")


def _extract_response_text(data: dict) -> str | None:
    try:
        return data["output"][0]["content"][0]["text"].strip()
    except Exception:
        output_text = data.get("output_text")
        if output_text:
            return output_text.strip()
        return None


def _parse_json_result(result: str) -> dict:
    """Parse LLM JSON output, tolerating markdown code fences.

    The model sometimes wraps its JSON in ```json ... ``` fences, which makes
    `json.loads` fail at line 1 column 1. Strip the fence before parsing.
    """
    text = (result or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    return json.loads(text)


class OpenAIError(Exception):
    """Raised when OpenAI fails and should not return fake data"""
    pass


def _send_openai_request(system_text: str, user_text: str) -> str:
    """Send request to OpenAI API. Returns the response text or raises OpenAIError."""
    if not OPENAI_API_KEY:
        raise OpenAIError("OPENAI_API_KEY not configured. AI unavailable.")

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_text}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_text}],
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        import time; _t0 = time.time()
        _log(f"_send_openai_request model={payload.get('model', 'unknown')} input_messages={len(payload.get('input') or [])}")
        print(f"[TRACE] AI-REQ-START | _send_openai_request | +0ms")
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )
        
        # Handle HTTP errors
        if response.status_code == 401:
            raise OpenAIError("OpenAI API key is invalid")
        if response.status_code == 429:
            raise OpenAIError("OpenAI API quota exceeded")
        if response.status_code >= 500:
            raise OpenAIError(f"OpenAI API server error: {response.status_code}")
            
        response.raise_for_status()
        
        data = response.json()
        print(f"[TRACE] AI-REQ-END | _send_openai_request | +{int((time.time()-_t0)*1000)}ms | status={response.status_code}")
        _log(f"_send_openai_request status: {response.status_code}")
        
        output_text = _extract_response_text(data)
        if output_text:
            return output_text.strip()

        raise OpenAIError("OpenAI response missing output text")
        
    except requests.Timeout:
        raise OpenAIError("OpenAI request timed out")
    except requests.ConnectionError as e:
        raise OpenAIError(f"OpenAI connection failed: {e}")
    except OpenAIError:
        raise
    except Exception as error:
        status = response.status_code if 'response' in dir() else "unknown"
        _log(f"_send_openai_request error: {error} status={status}")
        raise OpenAIError(f"OpenAI request failed: {error}")


def classify_intent(user_message: str, context: dict) -> str:
    """Classify user intent. Returns intent string or raises OpenAIError."""
    _log(f"classify_intent called: user_message={user_message}, context={context}")

    normalized_msg = user_message.strip().lower()
    if normalized_msg.isdigit():
        num = int(normalized_msg)
        if 1 <= num <= 20:
            _log(f"classify_intent numeric input detected ({num}) — forcing select_lead")
            return "select_lead"

    lead_list_active = context.get("lead_list_active", False)
    if lead_list_active and normalized_msg.isdigit():
        _log(f"classify_intent lead_list_active with numeric input — forcing select_lead")
        return "select_lead"

    system_text = (
        "Classify the user's intent into exactly one label.\n"
        "Allowed labels only:\n"
        "- new_search\n"
        "- refine_message\n"
        "- select_lead\n"
        "- send\n\n"
        "Rules:\n"
        "- If the context shows 'lead_list_active: true' and the user replied with a number, it means they selected a lead — classify as 'select_lead'\n"
        "- If 'selected_lead_id' is set and the user sends a number, they want to switch to a different lead — classify as 'select_lead'\n"
        "- 'new_search' is ONLY when the user wants to search for a DIFFERENT audience with NEW search terms\n"
        "- Never classify a numeric reply as 'new_search'\n\n"
        "Return only the label. No explanation."
    )
    user_text = (
        f"User message: {user_message}\n"
        f"Context: {context}\n\n"
        "Choose the best label."
    )
    result = _send_openai_request(system_text, user_text)

    normalized = result.strip().lower()
    if normalized in {"new_search", "refine_message", "select_lead", "send"}:
        return normalized

    _log(f"classify_intent error: unexpected model output {normalized}")
    raise OpenAIError(f"Unexpected intent classification: {normalized}")


def rewrite_message(instruction: str, previous_message: str, context: dict | None = None) -> str:
    """Rewrite a message based on instruction. Returns rewritten text or raises OpenAIError."""
    print("[AI INSTRUCTION]:", instruction)
    system_text = (
        "You are an expert cold email editor. You rewrite outreach messages strictly following the instruction.\n"
        "You edit the existing message — you do not write a new one from scratch.\n"
        "If the instruction says 'make it longer', you MUST expand the message.\n"
        "If the instruction says 'shorter', you MUST shorten it.\n"
        "Always modify the message meaningfully."
    )

    context_block = ""
    if context:
        parts = []
        if context.get("company"):
            parts.append(f"Target company: {context['company']}")
        if context.get("contact"):
            parts.append(f"Contact name: {context['contact']}")
        if context.get("role"):
            parts.append(f"Contact role: {context['role']}")
        if context.get("industry"):
            parts.append(f"Industry: {context['industry']}")
        if context.get("campaign_name"):
            parts.append(f"Campaign: {context['campaign_name']}")
        if context.get("messaging_angle"):
            parts.append(f"Messaging angle: {context['messaging_angle']}")
        if context.get("business_summary"):
            parts.append(f"Business summary: {context['business_summary']}")
        if parts:
            context_block = "\n".join(parts) + "\n\n"

        knowledge_block = _knowledge_prompt_block(context.get("knowledge_context"))
        if knowledge_block:
            context_block += knowledge_block + "\n\n"

    user_text = (
        "Rewrite the following cold outreach message based on the instruction.\n\n"
        f"{context_block}"
        f"Instruction: {instruction}\n\n"
        "Message:\n"
        f"{previous_message}\n\n"
        "Rules:\n"
        "- Maintain personalization and context\n"
        "- Improve clarity and impact\n"
        "- Only change length if instruction asks\n"
        "- Keep the same recipient targeting\n"
        "- Return only the rewritten message — no explanation, no prefix"
    )
    rewritten = _send_openai_request(system_text, user_text)
    print("[AI OUTPUT]:", rewritten)

    if not rewritten or rewritten.strip() == previous_message.strip():
        raise OpenAIError("Message rewrite produced no meaningful changes")

    return rewritten


def _strategy_block(strategy: dict | None) -> str:
    """Render the campaign Sales Playbook into a compact briefing block."""
    if not isinstance(strategy, dict) or not strategy:
        return ""
    s = strategy
    lines: list[str] = []
    if icp := str(s.get("icp") or s.get("audience") or "").strip():
        lines.append(f"- ICP: {icp}")
    if angle := str(s.get("messaging_angle") or "").strip():
        lines.append(f"- Lead angle: {angle}")
    if pains := s.get("pain_points"):
        if isinstance(pains, list) and pains:
            lines.append(f"- Priority pains: {', '.join(str(p) for p in pains[:3])}")
    if signals := s.get("buying_signals"):
        if isinstance(signals, list) and signals:
            lines.append(f"- Buying signals to reference: {', '.join(str(x) for x in signals[:3])}")
    if proofs := s.get("proof_points"):
        if isinstance(proofs, list) and proofs:
            lines.append(f"- Assertable proof points: {'; '.join(str(p) for p in proofs[:3])}")
    if diff := s.get("differentiators"):
        if isinstance(diff, list) and diff:
            lines.append(f"- Differentiators: {'; '.join(str(x) for x in diff[:3])}")
    if objections := s.get("objection_handling") or s.get("objections"):
        if isinstance(objections, list) and objections:
            lines.append(f"- Anticipate objections: {'. '.join(str(o) for o in objections[:3])}")
    if cta := str(s.get("cta") or "").strip():
        lines.append(f"- Campaign CTA: {cta}")
    if personalization := str(s.get("personalization") or "").strip():
        lines.append(f"- Personalization guidance: {personalization}")
    if confidence := str(s.get("confidence") or "").strip():
        lines.append(f"- Playbook confidence: {confidence}")
    if not lines:
        return ""
    return "\n\n=== CAMPAIGN SALES PLAYBOOK ===\n" + "\n".join(lines)


def _knowledge_prompt_block(context: dict | None) -> str:
    if not isinstance(context, dict):
        return ""
    from services.knowledge.context_adapter import format_knowledge_context
    return format_knowledge_context(context.get("knowledge_context"))


_EVIDENCE_FIRST_RULES = (
    "Writing rules:\n"
    "- ANSWER WHY THIS COMPANY FIRST. Open by acknowledging something observed "
    "about the recipient's company or role (industry, size, location, visible "
    "technology, documented signal) BEFORE anything about your own product.\n"
    "- PERSONALIZATION LADDER: lead with the highest-priority evidence that "
    "actually exists. Company-specific signals (recent events, hiring, "
    "business changes, technology, buying signals) outrank documented pain; "
    "documented pain outranks generic role/industry observations. Only when "
    "NO company-specific signal exists may you open with industry- or "
    "role-level observation — and keep it short and honest.\n"
    "- A field that reads 'N/A', 'No data available', 'Limited growth data', "
    "'No technology data' or similar is NOT evidence. Treat it as absent and "
    "never write from it. If no company signal exists, say nothing about the "
    "company — never pad or invent.\n"
    "- Ground EVERY claim in the evidence provided. NEVER assume the lead has "
    "manual outreach, poor efficiency, low reply rates, staff shortages, or "
    "customer engagement problems unless the evidence says so.\n"
    "- NEVER invent company facts, names, metrics, funding, or initiatives.\n"
    "- If the evidence is thin, say LESS — a short, honest opening written "
    "without fabrication beats a generic one. Do not pad with invented pains.\n"
    "- Never use vacuous openers like 'I hope this finds you well', "
    "'I wanted to reach out', or 'I came across your company'.\n"
    "- Never use generic filler: 'improve efficiency', 'streamline operations', "
    "'modernize operations', 'personalized engagement', 'better results', "
    "'game-changing', 'innovative', 'solutions that empower'.\n"
    "- Transition from the company-specific observation to the offer with one "
    "clear sentence — no formulaic pivots like 'That's why I'm reaching out' "
    "or 'I believe'.\n"
    "- DIVERSITY: this email is one of many in a campaign; each must feel "
    "hand-written. Follow the OPENING / TRANSITION / CTA / PACING assignment "
    "in the brief exactly. Never reuse the same opening pattern, transition "
    "phrasing, or CTA wording across leads. Vary sentence lengths and rhythm.\n"
    "- Write like a senior sales consultant: specific, calm, human. Short "
    "sentences.\n"
    "- SUBJECT LINE RULES: follow the assigned subject style, make it "
    "curiosity-driven and specific — reference the observed signal or the "
    "concrete situation. Mix lengths and casing; never title-case a template "
    "like 'Modernizing Operations At {Company}';\n"
    "- End with a single low-friction CTA derived from the playbook when given, "
    "phrased per the assigned CTA style while preserving the ask."
)


_NO_DATA_MARKERS = (
    "n/a", "none", "unknown", "not available", "no data available",
    "no technology data available", "no tech data available",
    "limited growth data available", "no specific decision context",
    "no detailed data available", "-",
)


def _evidence_value(value: object) -> str:
    """Normalize an evidence field; empty when it is a no-data placeholder."""
    text = str(value or "").strip()
    low = text.lower()
    if not text or any(text.lower() == m or low.startswith(m) for m in _NO_DATA_MARKERS):
        return ""
    return text


def _variation_steer(lead: dict, has_company_signals: bool) -> dict:
    """Deterministic per-lead variation assignment (stable across retries).

    Hashes the lead identity so every lead in a campaign gets a different
    opening / transition / CTA / pacing / subject combination, while any
    single lead always receives the same assignment — the model's diversity
    instructions are enforced by construction, not by chance.
    """
    import hashlib
    identity = "|".join(
        str(lead.get(k) or "")
        for k in ("id", "email", "linkedin_url", "company", "title")
    )
    digits = int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10], 16)

    if has_company_signals:
        openings = (
            "direct observation: open with ONE observed company-specific fact "
            "(a recent event, a hiring move, a visible technology, a business "
            "change or buying signal) stated plainly, with no preamble.",
            "specific question: open with a short question about the company's "
            "own situation that the evidence supports—never hypothetical.",
            "stated change: open with the concrete business change or signal "
            "the evidence shows (growth, tech adoption, expansion) in one "
            "quiet sentence.",
            "scene-setting: open with the recipient's company context drawn "
            "strictly from evidence—tech stack or recent events—before any "
            "pitch.",
        )
    else:
        openings = (
            "role observation: open with a single true observation about the "
            "recipient's title or documented company facts only—no invented "
            "detail.",
            "plain start: open with a short, honest sentence naming the "
            "company and why their situation (as documented) prompted the "
            "message—if nothing is documented, omit it.",
            "purpose-led: open by stating the one purpose of the email in a "
            "single line, no filler.",
        )

    transitions = (
        "direct: bridge with one plain sentence stating what prompted the "
        "email.",
        "because-led: bridge with 'Because ...' referring to the opening "
        "observation only.",
        "contrast: bridge by contrasting the observed situation with what the "
        "offer changes—only where the contrast is grounded.",
        "minimal: bridge in under eight words, no throat-clearing.",
    )

    cta_styles = (
        "offer-first: CTA offers the specific next action from the playbook "
        "directly (a 15-minute call, a short reply), phrased as a question.",
        "reply-led: CTA asks for a yes/no reply about the specific ask — "
        "low effort, one line.",
        "contextual: CTA ties to the opening evidence (e.g. 'worth a look at "
        "the ordering flow?') while preserving the playbook ask.",
        "candid: CTA states plainly what you want and why it is small — no "
        "hedging, no 'just'.",
    )

    pacings = (
        "short: mostly short sentences; never more than 9 words in a row.",
        "steady: mix of short and medium sentences; no run-ons.",
        "snappy: punchy rhythm, one clause per line where sensible.",
    )

    subject_styles = (
        "question: subject as a short curiosity question tied to the evidence.",
        "observation: subject states the observed fact as a fragment.",
        "direct: subject names the topic plainly, lower case, no clickbait.",
        "two-part: subject with a colon between topic and concrete detail.",
    )

    def pick(bucket: tuple[str, ...], salt: int) -> str:
        return bucket[(digits + salt) % len(bucket)]

    return {
        "opening": pick(openings, 1),
        "transition": pick(transitions, 7),
        "cta": pick(cta_styles, 13),
        "pacing": pick(pacings, 19),
        "subject": pick(subject_styles, 31),
    }


def generate_outreach_email(
    lead: dict,
    company_intelligence: dict | None = None,
    lead_intelligence: dict | None = None,
    strategy: dict | None = None,
    knowledge_context: dict | None = None,
) -> dict:
    """Generate a personalized outreach email. Returns email dict or raises OpenAIError.

    Grounds the first paragraph in the *why this company* evidence available
    (company intelligence, lead intelligence, campaign playbook) and forbids
    generic filler. See ``_EVIDENCE_FIRST_RULES``. Every lead is issued a
    deterministic variation assignment so campaign drafts diverge in opening,
    transition, CTA phrasing and pacing while staying evidence-first.
    """
    _log(f"generate_outreach_email called: lead={lead}")

    first_name = ((lead.get("name") or "").split() or [""])[0]
    company = (lead.get("company") or "").strip()
    title = (lead.get("title") or "").strip()
    pain_points = str(lead.get("pain_points") or "").strip()

    ci = {k: v for k, v in (company_intelligence or {}).items()}
    li = {k: v for k, v in (lead_intelligence or {}).items()}
    has_intelligence = bool(ci) or bool(li)

    # Personalization ladder tier 1: company-specific signals (highest
    # priority). Fields that read "no data" are filtered to absent — the
    # model never sees them, so it can never invent from them.
    company_signals: list[str] = []
    for label, key in (
        ("Recent events", "recent_events_summary"),
        ("Buying signals", "buying_signal_summary"),
        ("Technology", "technology_summary"),
        ("Business changes / growth", "growth_summary"),
        ("Why this company", "qualification_reason"),
    ):
        text = _evidence_value(ci.get(key))
        if text:
            company_signals.append(f"- {label}: {text}")

    # Tier 2: documented pain.
    pain = _evidence_value(ci.get("business_pain_summary"))
    # Tier 3: company facts baseline.
    company_facts = _evidence_value(ci.get("company_summary"))
    confidence_score = ci.get("confidence_score")
    confidence_line = (
        f"- Confidence: {confidence_score}/100"
        if isinstance(confidence_score, (int, float)) else ""
    )

    lead_lines: list[str] = []
    for label, value in (
        ("Buying stage", li.get("buying_stage")),
        ("Urgency", li.get("urgency")),
        ("Decision authority", li.get("decision_authority_summary")),
        ("Business need", li.get("estimated_business_need")),
        ("Best contact reason", li.get("best_contact_reason")),
        ("Recommended pitch", li.get("recommended_pitch")),
        ("Summary", li.get("summary")),
    ):
        text = _evidence_value(value)
        if text and text != "N/A":
            lead_lines.append(f"- {label}: {text}")
    why_selected = li.get("why_selected")
    if isinstance(why_selected, list) and why_selected:
        lead_lines.append("- Why selected: " + "; ".join(str(x) for x in why_selected))

    system_text = (
        "You write short personalized cold emails based on company intelligence.\n"
        "Return valid JSON only with exactly these keys:\n"
        "{\"subject\":\"...\",\"body\":\"...\"}\n"
        f"{_EVIDENCE_FIRST_RULES}"
        "\nKnowledge is business guidance only; it is not prospect evidence. "
        "Do not turn a generic Knowledge claim into a claim about this lead. "
        "Do not invent customers, results, integrations, metrics, testimonials, or ROI."
    )

    user_text = (
        "Write a cold outreach email for this lead.\n\n"
        f"First name: {first_name or 'there'}\n"
        f"Title: {title or 'unknown'}\n"
        f"Company: {company or 'unknown company'}\n"
        f"Pain points: {pain_points or 'none observed — do not invent any'}\n"
        f"Known evidence about the company: "
        f"{'see the ladder below' if has_intelligence else 'none beyond the above — do not invent any'}"
    )

    if company_signals or pain or company_facts:
        ladder = "\n\n=== PERSONALIZATION LADDER (order of preference) ===\n"
        ladder += "1. COMPANY-SPECIFIC SIGNALS (lead with these when present):\n"
        ladder += "\n".join(company_signals) if company_signals else "   (none present)"
        if pain:
            ladder += "\n2. DOCUMENTED PAIN:\n" + pain
        if company_facts:
            ladder += "\n3. COMPANY BASELINE (role/industry facts only):\n" + company_facts
        if confidence_line:
            ladder += "\n" + confidence_line
        ladder += "\n========================================"
        user_text += ladder
    elif lead_lines:
        user_text += (
            "\n\n=== LEAD INTELLIGENCE (evidence only) ===\n"
            + "\n".join(lead_lines)
            + "\n========================"
        )

    strategy_block = _strategy_block(strategy)
    if strategy_block:
        user_text += f"\n{strategy_block}"

    knowledge_block = _knowledge_prompt_block({"knowledge_context": knowledge_context})
    if knowledge_block:
        user_text += f"\n{knowledge_block}"

    steer = _variation_steer(lead, has_company_signals=bool(company_signals))
    user_text += (
        "\n\n=== VARIATION ASSIGNMENT FOR THIS EMAIL (follow exactly) ===\n"
        f"- Opening style: {steer['opening']}\n"
        f"- Transition: {steer['transition']}\n"
        f"- CTA style: {steer['cta']}\n"
        f"- Pacing: {steer['pacing']}\n"
        f"- Subject style: {steer['subject']}\n"
        "==================================="
    )

    result = _send_openai_request(system_text, user_text)

    try:
        data = _parse_json_result(result)
    except json.JSONDecodeError as error:
        _log(f"generate_outreach_email parse error: {error}")
        _log(f"generate_outreach_email raw result: {result}")
        raise OpenAIError(f"Failed to parse AI response as JSON: {error}")

    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    if not subject or not body:
        raise OpenAIError("AI response missing subject or body")

    return {"subject": subject, "body": body}


def _plan_block_from_context(context: dict | None) -> str:
    """Render the persisted Discovery Plan as a briefing block."""
    if not isinstance(context, dict):
        return ""
    plan = context.get("discovery_plan")
    if not isinstance(plan, dict):
        return ""
    lines = []
    offering = str(plan.get("offering") or "").strip()
    if offering:
        lines.append(f"- Offering: {offering}")
    primary = plan.get("primary_services") or []
    if primary:
        lines.append(f"- Primary services: {', '.join(str(x) for x in primary[:6])}")
    industries = plan.get("industries") or []
    if industries:
        lines.append(f"- Target industries: {', '.join(str(x) for x in industries[:6])}")
    roles = plan.get("decision_maker_roles") or []
    if roles:
        lines.append(f"- Decision makers: {', '.join(str(x) for x in roles[:8])}")
    segments = str(plan.get("target_list_segment") or "").strip()
    if segments:
        lines.append(f"- Business size: {segments}")
    geography = plan.get("geography") or []
    if geography:
        lines.append(f"- Geography: {', '.join(str(x) for x in geography[:4])}")
    pains = plan.get("pain_points") or []
    if pains:
        lines.append(f"- Known pain points: {', '.join(str(x) for x in pains[:6])}")
    signals = plan.get("buying_signals") or []
    if signals:
        lines.append(f"- Buying signals: {', '.join(str(x) for x in signals[:6])}")
    tech = plan.get("technologies") or []
    if tech:
        lines.append(f"- Likely tech stack: {', '.join(str(x) for x in tech[:6])}")
    negatives = plan.get("negative_keywords") or []
    if negatives:
        lines.append(f"- Exclude companies matching: {', '.join(str(x) for x in negatives[:6])}")
    angle = str(plan.get("messaging_angle") or "").strip()
    if angle:
        lines.append(f"- Intended angle: {angle}")
    if not lines:
        return ""
    return "Discovery plan (derived from the objective):\n" + "\n".join(lines)


def _research_block_from_context(context: dict | None) -> str:
    """Render the aggregated market research (actual discovered companies)."""
    if not isinstance(context, dict):
        return ""
    research = context.get("market_research")
    if not isinstance(research, dict):
        return ""
    lines: list[str] = []
    companies = research.get("companies") or []
    if companies:
        lines.append(f"- {len(companies)} companies were surfaced during research; the recommendation list above is grounded in them")
        for company in companies[:10]:
            company = company if isinstance(company, dict) else {}
            name = str(company.get("company") or company.get("name") or "unknown")
            industry = str(company.get("company_industry") or company.get("industry") or "").strip()
            city = str(company.get("company_city") or company.get("city") or "").strip()
            stack = company.get("company_technology") or company.get("technology") or {}
            tech = ", ".join(str(v) for v in stack.values() if v) if isinstance(stack, dict) else ""
            parts = [name]
            if industry:
                parts.append(industry)
            if city:
                parts.append(city)
            if tech:
                parts.append(f"using {tech[:80]}")
            lines.append(f"  - {', '.join(parts)}")
    for key, label in (
        ("industry_distribution", "Dominant industries"),
        ("size_distribution", "Company sizes"),
        ("location_distribution", "Locations"),
    ):
        distribution = research.get(key)
        if isinstance(distribution, dict) and distribution:
            parts = ", ".join(f"{k} ({v})" for k, v in list(distribution.items())[:5])
            if parts:
                lines.append(f"- {label}: {parts}")
    observed = research.get("observed_pain_points") or []
    if observed:
        lines.append(f"- Observed pain points in the market: {', '.join(str(x) for x in observed[:6])}")
    observed_signals = research.get("observed_buying_signals") or []
    if observed_signals:
        lines.append(f"- Observed buying signals: {', '.join(str(x) for x in observed_signals[:6])}")
    if len(lines) <= 1:
        return ""
    return "Market research (real companies found during discovery):\n" + "\n".join(lines)


def _plan_from_context(context: dict | None) -> dict:
    if not isinstance(context, dict):
        return {}
    plan = context.get("discovery_plan")
    return plan if isinstance(plan, dict) else {}


def _research_from_context(context: dict | None) -> dict:
    if not isinstance(context, dict):
        return {}
    research = context.get("market_research")
    return research if isinstance(research, dict) else {}


def _fallback_icp(objective: str, context: dict | None = None) -> str:
    """Derive an ICP from the discovery plan (or objective) instead of placeholder copy."""
    plan = _plan_from_context(context)
    plan = _plan_from_context(context)
    roles = [str(r) for r in (plan.get("decision_maker_roles") or []) if str(r).strip()][:4]
    industries = [str(i) for i in (plan.get("industries") or []) if str(i).strip()][:4]
    if roles and industries:
        return f"{', '.join(roles)} at companies in {', '.join(industries)}."
    if industries:
        return f"Decision makers at companies in {', '.join(industries)}."
    research = _research_from_context(context)
    industries = [str(i) for i in (research.get("industry_distribution") or {}) if str(i).strip()][:4]
    if industries:
        return f"Decision makers at companies in {', '.join(industries)}."
    return f"Ideal contacts for {objective.strip() or 'this outreach'}."


def _fallback_messaging_angle(objective: str, context: dict | None = None, icp: str = "") -> str:
    """Derive a lead angle from the plan (intended angle, pains, signals) instead of placeholder copy."""
    plan = _plan_from_context(context)
    if angle := str(plan.get("messaging_angle") or "").strip():
        return angle
    pains = [str(p) for p in (plan.get("pain_points") or []) if str(p).strip()][:3]
    signals = [str(s) for s in (plan.get("buying_signals") or []) if str(s).strip()][:3]
    if pains:
        lead = "; ".join(pains)
        return f"Open on the pains this audience is trying to solve: {lead}."
    if signals:
        lead = "; ".join(signals)
        return f"Open on the buying signals this audience is showing: {lead}."
    return f"Open on the outcome behind {objective.strip()[:100]}."


def _fallback_playbook(objective: str, context: dict | None = None) -> dict:
    """Plan-grounded fallback playbook used when the AI path fails.

    Every field is derived from the Discovery Plan / research when present,
    never from placeholder copy. Mirrors the shape of a successful
    ``generate_campaign_strategy`` response so the UI renders identically.
    """
    plan = _plan_from_context(context)
    research = _research_from_context(context)
    icp = _fallback_icp(objective, context)
    angle = _fallback_messaging_angle(objective, context, icp)

    roles = [str(r) for r in (plan.get("decision_maker_roles") or []) if str(r).strip()]
    industries = [str(i) for i in (plan.get("industries") or []) if str(i).strip()]
    pains = [str(p) for p in (plan.get("pain_points") or []) if str(p).strip()]
    signals = [str(s) for s in (plan.get("buying_signals") or []) if str(s).strip()]
    tech = [str(t) for t in (plan.get("technologies") or []) if str(t).strip()]
    negatives = [str(n) for n in (plan.get("negative_keywords") or []) if str(n).strip()]
    segment = str(plan.get("target_list_segment") or "").strip()

    companies = research.get("companies") or []
    observed_patterns: list[str] = []
    for company in companies[:6]:
        if not isinstance(company, dict):
            continue
        name = str(company.get("company") or company.get("name") or "").strip()
        industry = str(company.get("company_industry") or company.get("industry") or "").strip()
        if industry:
            line = f"{industry} operators" + (f" like {name}" if name else "")
            if line not in observed_patterns:
                observed_patterns.append(line)
    observed_pain = [str(p) for p in (research.get("observed_pain_points") or []) if str(p).strip()]
    observed_signals = [str(s) for s in (research.get("observed_buying_signals") or []) if str(s).strip()]

    personas: list[dict] = []
    for role in roles[:3]:
        personas.append({
            "persona": role,
            "priorities": pains[:2] or ["Running operations in their market"],
            "incentives": ["Operational impact visible in their metrics"],
            "kpis": ["Time spent on manual work", "Conversion of inbound interest"],
            "fears": ["Wasted spend on tools that don't fit their operation"],
            "likely_objections": ["Already managing this manually", "No budget this quarter"],
            "authority_level": "Decision maker",
        })

    market_summary = ". ".join(
        p for p in [
            " ".join(industries),
            segment,
            " - ".join(str(g) for g in (plan.get("geography") or [])[:3]),
        ] if p
    )

    outreach_strategy = {
        "first_touch_goal": "Open on the pain this audience is trying to solve: "
                            f"{(pains or observed_pain)[0][:120] if pains or observed_pain else ('the operational gap behind ' + objective[:80])}.",
        "first_touch_cta": "Reply with the one thing that would make this worth 15 minutes.",
        "follow_up_strategy": "Follow up once with a concrete example, then a final value-led check-in.",
        "personalization_opportunities": observed_patterns[:2] or [
            "Reference their documented industry / tech directly"
        ],
        "topics_to_avoid": [f"Anything matching: {', '.join(negatives[:3])}"] if negatives else [],
    }

    pain_prioritization: list[dict] = []
    for p in (pains or observed_pain)[:3]:
        pain_prioritization.append({
            "pain": p,
            "why": "This recurs across the researched companies, so it is likely top-of-mind.",
        })

    return {
        "campaign_objective": objective,
        "icp": icp,
        "audience": icp,
        "channel": "email",
        "messaging_angle": angle,
        "sequence": ["Personalized introduction", "Value-led follow-up", "Final check-in"],
        "objections": [],
        "tone": "direct",
        "persona": "Loqi sales operator",
        "offer": {},
        "market_summary": market_summary,
        "market_attractiveness": (
            f"This market is worth pursuing now: {'; '.join(signals[:3]).lower()}."
            if signals else "This market is worth pursuing: the researched companies match the objective's profile."
        ),
        "market_common_patterns": observed_patterns or [],
        "market_technologies": tech,
        "market_maturity": f"Typically '{segment}' — established operations." if segment else "",
        "observed_patterns": observed_patterns or [],
        "buying_signals": signals or observed_signals,
        "pain_points": pains or observed_pain,
        "pain_prioritization": pain_prioritization,
        "personas": personas,
        "value_proposition": (
            f"Aligned with the opportunity observed: {'; '.join((pains or observed_pain)[:2]).lower()}"
        ),
        "positioning": "",
        "differentiators": [],
        "proof_points": (
            ([f"Observed stack: {', '.join(tech[:3]).lower()}"] if tech else [])
            + ([f"Buying signals: {'; '.join(signals[:2]).lower()}"] if signals else [])
        ),
        "why_now": "; ".join(signals[:3]).lower() if signals else "",
        "outreach_strategy": outreach_strategy,
        "messaging_angles": [angle] if angle else [],
        "objection_handling": [],
        "outreach_sequence": ["Personalized introduction", "Value-led follow-up", "Final check-in"],
        "personalization": (
            f"Ground the opening in the prospect's own context: "
            f"{', '.join(industries) or 'their industry'}."
        ),
        "cta": "",
        "success_metrics": [],
        "risks": (
            [f"Unqualified matches ({'; '.join(negatives[:3]).lower()})"] if negatives else []
        ) + ([f"Segment capped at '{segment}'"] if segment else []),
        "confidence": "Low — plan-derived playbook, no AI synthesis",
    }


def generate_campaign_strategy(objective: str, context: dict | None = None) -> dict:
    """Generate a structured outbound strategy for a campaign objective.

    Consumes the objective, the campaign's Discovery Plan (when one exists),
    and the market research gathered during discovery. Returns the legacy
    artifact keys (audience, channel, messaging_angle, sequence, tone,
    persona, offer, objections) PLUS the full 16-section Sales Playbook
    under ``content``. Raises OpenAIError when the model fails.
    """
    _log(f"generate_campaign_strategy called: objective={objective}")

    leads = context.get("leads") if isinstance(context, dict) else None
    lead_block = ""
    if leads:
        lines = []
        for lead in leads[:8]:
            parts = [
                str(lead.get("name") or "").strip(),
                str(lead.get("title") or "").strip(),
                str(lead.get("company") or lead.get("company_name") or "").strip(),
                str(lead.get("domain") or "").strip(),
            ]
            line = ", ".join(p for p in parts if p)
            if line:
                lines.append(f"- {line}")
        if lines:
            lead_block = "\n".join(lines)

    profile_block = ""
    if isinstance(context, dict):
        profile = context.get("audience_profile")
        if isinstance(profile, dict) and (profile.get("lead_count") or 0) > 0:
            lines = [f"- {profile['lead_count']} target companies attached from research"]
            companies = profile.get("companies")
            if companies:
                lines.append(f"- Companies: {', '.join(str(x) for x in companies[:8])}")
            for key, label in (
                ("industry_distribution", "Dominant industries"),
                ("size_distribution", "Company sizes"),
                ("location_distribution", "Locations"),
            ):
                distribution = profile.get(key)
                if isinstance(distribution, dict) and distribution:
                    parts = ", ".join(
                        f"{k} ({v})" for k, v in list(distribution.items())[:4]
                    )
                    if parts:
                        lines.append(f"- {label}: {parts}")
            if len(lines) > 1:
                profile_block = "\n".join(lines)

    plan_block = _plan_block_from_context(context)
    research_block = _research_block_from_context(context)
    knowledge_block = _knowledge_prompt_block(context)

    system_text = (
        "You are the outbound Sales Playbook architect for a B2B sales operator.\n"
        "You turn a campaign objective, its structured Discovery Plan, and the "
        "actual companies discovered during research into one grounded playbook.\n"
        "Return valid JSON ONLY with exactly these keys:\n"
        "{\"campaign_objective\":\"...\", \"icp\":\"...\", \"channel\":\"email\", \n"
        " \"market_summary\":\"...\", \"market_attractiveness\":\"...\", \n"
        " \"market_common_patterns\":[\"...\",\"...\"], \n"
        " \"market_technologies\":[\"...\",\"...\"], \"market_maturity\":\"...\",\n"
        " \"observed_patterns\":[\"...\",\"...\"],\n"
        " \"buying_signals\":[\"...\",\"...\"], \"pain_points\":[\"...\",\"...\"],\n"
        " \"pain_prioritization\":[{\"pain\":\"...\",\"why\":\"...\"}],\n"
        " \"personas\":[{\"persona\":\"...\",\"priorities\":[\"...\"],\"incentives\":[\"...\"],\"kpis\":[\"...\"],\"fears\":[\"...\"],\"likely_objections\":[\"...\"],\"authority_level\":\"...\"}],\n"
        " \"value_proposition\":\"...\", \"positioning\":\"...\",\n"
        " \"differentiators\":[\"...\",\"...\"], \"proof_points\":[\"...\",\"...\"], \"why_now\":\"...\",\n"
        " \"outreach_strategy\":{\"first_touch_goal\":\"...\",\"first_touch_cta\":\"...\",\"follow_up_strategy\":\"...\",\"personalization_opportunities\":[\"...\"],\"topics_to_avoid\":[\"...\"]},\n"
        " \"messaging_angles\":[\"...\",\"...\"], \"objection_handling\":[\"Objection: ... Response: ...\"],\n"
        " \"outreach_sequence\":[\"...\",\"...\"], \"personalization\":\"...\",\n"
        " \"cta\":\"...\", \"success_metrics\":[\"...\",\"...\"],\n"
        " \"risks\":[\"...\",\"...\"], \"confidence\":\"High|Medium|Low + why\",\n"
        " \"tone\":\"direct|consultative|friendly\", \"persona\":\"...\",\n"
        " \"offer\":{\"type\":\"...\",\"detail\":\"...\"}}\n\n"
        "Rules:\n"
        "- Ground EVERY output in the Discovery Plan and the discovered companies. Do NOT hallucinate facts.\n"
        "- Do not paraphrase the objective; think from the evidence: what was found, what pains/signals were observed, who the decision makers are.\n"
        "- icp: concrete decision-maker roles + the exact company profile (size band, locations, segment) the research actually surfaced — e.g. 'Restaurant chains with 3-20 locations', never vague phrases like 'Prospects matching the research profile'.\n"
        "- market_summary: what the discovered market looks like (industry mix, sizes, locations, tech).\n"
        "- market_attractiveness: why THIS market and THESE companies are worth pursing now.\n"
        "- market_common_patterns: shared characteristics seen across the discovered companies (operational patterns included).\n"
        "- pain_prioritization: rank the pains; every entry must explain WHY it matters to these companies.\n"
        "- personas: for each decision maker role — priorities, incentives, KPIs, fears, likely objections, authority level.\n"
        "- proof_points: things a salesperson can actually assert given the observed evidence (e.g. discovered tech, hiring, growth), so an outreach writer can cite them in drafts.\n"
        "- why_now: why this audience acts now.\n"
        "- value_proposition + positioning: outcome-led, tied to observed pains, never generic.\n"
        "- messaging_angles: 2-3 specific, differentiated angles.\n"
        "- outreach_strategy.first_touch_goal: what the first email should achieve; first_touch_cta: the specific ask; topics_to_avoid: subjects likely to annoy this audience.\n"
        "- objection_handling: 2-3 real objections this audience would raise, each as \"Objection: ..., Response: ...\".\n"
        "- confidence: honest assessment with the reasoning behind it; set Low when no research was provided.\n"
        "- If no research was provided, explicitly say the playbook is drafted from the Discovery Plan alone.\n"
        "- Treat Knowledge Context as business guidance and approved messaging, not as research about a prospect.\n"
        "- Do not invent customers, results, integrations, metrics, testimonials, ROI, or prospect facts from Knowledge.\n"
        "- Never use \"improve efficiency\", \"streamline operations\", \"drive growth\", \"modernize operations\" as a substitute for a reasoning.\n"
    )

    user_text = f"Campaign objective: {objective}"
    if plan_block:
        user_text += f"\n\n{plan_block}"
    if research_block:
        user_text += f"\n\n{research_block}"
    if lead_block:
        user_text += f"\n\nKnown target leads (first {min(len(leads), 8)}):\n{lead_block}"
    if profile_block:
        user_text += f"\n\nAudience profile from attached research:\n{profile_block}"
    if knowledge_block:
        user_text += f"\n\n{knowledge_block}"

    result = _send_openai_request(system_text, user_text)

    try:
        data = _parse_json_result(result)
    except json.JSONDecodeError as error:
        _log(f"generate_campaign_strategy parse error: {error}")
        _log(f"generate_campaign_strategy raw result: {result}")
        raise OpenAIError(f"Failed to parse AI response as JSON: {error}")

    def _strings(key: str, limit: int = 6) -> list[str]:
        value = data.get(key)
        if isinstance(value, list):
            return [str(x) for x in value if str(x).strip()][:limit]
        return []

    sequence = _strings("outreach_sequence", 5) or [
        "Personalized introduction", "Value-led follow-up", "Final check-in"
    ]
    objections = _strings("objection_handling", 5)
    offer = data.get("offer")
    if not isinstance(offer, dict):
        offer = {}
    tone = str(data.get("tone") or "direct")
    persona = str(data.get("persona") or "Loqi sales operator")
    icp = str(data.get("icp") or _fallback_icp(objective, context)).strip()
    angles = data.get("messaging_angles")
    first_angle = ""
    if isinstance(angles, list) and angles:
        first_angle = str(angles[0])
    messaging_angle = str(first_angle or data.get("icp") or _fallback_messaging_angle(objective, context, icp))

    channel = str(data.get("channel") or "email")

    def _object_list(key: str, limit: int = 5) -> list[dict]:
        value = data.get(key)
        if not isinstance(value, list):
            return []
        items = []
        for item in value:
            if not isinstance(item, dict) or not item:
                continue
            items.append({k: v for k, v in item.items()})
        return items[:limit]

    pain_prioritization = _object_list("pain_prioritization", 6)
    personas = _object_list("personas", 5)
    outreach_strategy_raw = data.get("outreach_strategy")
    outreach_strategy = {}
    if isinstance(outreach_strategy_raw, dict):
        outreach_strategy = {
            str(k): (v if not isinstance(v, list) else [str(x) for x in v if str(x).strip()][:6])
            for k, v in outreach_strategy_raw.items()
            if v
        }

    content = {
        "campaign_objective": str(data.get("campaign_objective") or objective),
        "icp": icp,
        "market_summary": str(data.get("market_summary") or ""),
        "market_attractiveness": str(data.get("market_attractiveness") or ""),
        "market_common_patterns": _strings("market_common_patterns"),
        "market_technologies": _strings("market_technologies"),
        "market_maturity": str(data.get("market_maturity") or ""),
        "observed_patterns": _strings("observed_patterns"),
        "buying_signals": _strings("buying_signals"),
        "pain_points": _strings("pain_points"),
        "pain_prioritization": pain_prioritization,
        "personas": personas,
        "value_proposition": str(data.get("value_proposition") or ""),
        "positioning": str(data.get("positioning") or ""),
        "differentiators": _strings("differentiators"),
        "proof_points": _strings("proof_points"),
        "why_now": str(data.get("why_now") or ""),
        "outreach_strategy": outreach_strategy,
        "messaging_angles": _strings("messaging_angles", 3),
        "objection_handling": objections,
        "outreach_sequence": sequence,
        "personalization": str(data.get("personalization") or ""),
        "cta": str(data.get("cta") or ""),
        "success_metrics": _strings("success_metrics", 4),
        "risks": _strings("risks", 4),
        "confidence": str(data.get("confidence") or "Medium"),
        "channel": channel,
    }

    artifact = {
        "objective": objective,
        "audience": icp,
        "channel": channel,
        "messaging_angle": messaging_angle,
        "sequence": sequence,
        "tone": tone,
        "persona": persona,
        "offer": offer,
        "objections": objections,
    }
    artifact.update(content)
    return artifact


def analyze_draft(draft_text: str, context: dict | None = None) -> dict:
    """Analyze a draft and return structured coaching feedback. Returns dict or raises OpenAIError."""
    _log(f"analyze_draft called: draft_len={len(draft_text)}")
    context_block = ""
    if context:
        parts = []
        for key, label in [
            ("company", "Target company"),
            ("contact", "Contact name"),
            ("role", "Contact role"),
            ("industry", "Industry"),
            ("campaign_name", "Campaign"),
            ("messaging_angle", "Messaging angle"),
            ("business_summary", "Business summary"),
        ]:
            val = context.get(key)
            if val:
                parts.append(f"{label}: {val}")
        if parts:
            context_block = "\n".join(parts) + "\n\n"

    system_text = (
        "You are an expert B2B outbound coach. Analyze the cold outreach draft and return "
        "structured feedback as valid JSON with exactly these keys:\n"
        "{\n"
        '  "quality_score": <0-10>,\n'
        '  "strengths": ["<strength 1>", "<strength 2>", ...],\n'
        '  "weaknesses": ["<weakness 1>", "<weakness 2>", ...],\n'
        '  "biggest_opportunity": "<one-sentence advice>",\n'
        '  "estimated_reply_rate": "<Low|Medium|High|Very High>",\n'
        '  "recommended_actions": ["<action 1>", "<action 2>", ...]\n'
        "}\n\n"
        "Evaluate based on:\n"
        "- personalization quality\n"
        "- positioning and buyer psychology\n"
        "- messaging clarity\n"
        "- CTA strength\n"
        "- industry fit\n"
        "- objection handling\n"
        "- overall reply probability\n\n"
        "Return ONLY valid JSON. No markdown, no explanation outside JSON."
    )
    user_text = (
        f"{context_block}"
        f"Draft to analyze:\n\n{draft_text}\n\n"
        "Provide structured coaching feedback as JSON."
    )
    result = _send_openai_request(system_text, user_text)
    try:
        data = _parse_json_result(result)
    except json.JSONDecodeError as error:
        _log(f"analyze_draft parse error: {error}, raw: {result}")
        raise OpenAIError(f"Failed to parse analysis as JSON: {error}")
    required = {"quality_score", "strengths", "weaknesses", "biggest_opportunity", "estimated_reply_rate", "recommended_actions"}
    if not all(k in data for k in required):
        raise OpenAIError(f"Analysis missing required keys. Got: {list(data.keys())}")
    return data


def answer_draft_question(question: str, draft_text: str, context: dict | None = None) -> str:
    """Answer an educational question about outbound/copywriting, using the draft as example when helpful.
    Returns a plain-text answer. Never modifies the draft."""
    _log(f"answer_draft_question: question={question}")
    context_block = ""
    if context:
        parts = []
        for key, label in [
            ("company", "Target company"),
            ("contact", "Contact name"),
            ("role", "Contact role"),
            ("industry", "Industry"),
            ("campaign_name", "Campaign"),
            ("messaging_angle", "Messaging angle"),
        ]:
            val = context.get(key)
            if val:
                parts.append(f"{label}: {val}")
        if parts:
            context_block = "\n".join(parts) + "\n\n"

    system_text = (
        "You are an expert outbound/copywriting coach answering a user's educational question.\n"
        "Rules:\n"
        "- Answer clearly and concisely\n"
        "- When helpful, use the provided draft as a concrete example\n"
        "- NEVER rewrite or modify the draft\n"
        "- NEVER suggest that the draft was updated\n"
        "- Keep the answer educational, not directive\n"
        "- If the user asks about a term (e.g. 'what is CTA'), define it and show how it appears in the draft\n"
        "- Do NOT return JSON — return plain text"
    )
    user_text = (
        f"{context_block}"
        f"Current draft:\n{draft_text}\n\n"
        f"Question: {question}\n\n"
        "Answer the question educationally. Use the draft as an example when it helps."
    )
    return _send_openai_request(system_text, user_text)
