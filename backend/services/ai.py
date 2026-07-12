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
        _log(f"_send_openai_request payload: {payload}")
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
        body = response.text if 'response' in dir() else None
        _log(f"_send_openai_request error: {error}")
        _log(f"_send_openai_request exact response body: {body}")
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


def generate_outreach_email(
    lead: dict,
    company_intelligence: dict | None = None,
    lead_intelligence: dict | None = None,
) -> dict:
    """Generate a personalized outreach email. Returns email dict or raises OpenAIError.

    When company_intelligence and/or lead_intelligence are provided, the AI
    receives structured business context *and* lead-level sales intelligence
    (fit score, buying stage, urgency, objection risk, why selected, etc.)
    so the email is grounded in real intelligence.

    The lead_intelligence provides *explainability* — why this lead was chosen,
    what to pitch, and what risks exist — enabling the AI to write emails
    that reference actual qualification reasoning rather than guessing.
    """
    _log(f"generate_outreach_email called: lead={lead}")

    first_name = ((lead.get("name") or "").split() or [""])[0]
    company = (lead.get("company") or "").strip()
    title = (lead.get("title") or "").strip()
    pain_points = lead.get("pain_points") or (
        "manual outbound, low reply rates, poor personalization"
    )

    intelligence_block = ""

    if company_intelligence:
        system_text = (
            "You write short personalized cold emails based on company intelligence.\n"
            "Return valid JSON only with exactly these keys:\n"
            "{\"subject\":\"...\",\"body\":\"...\"}\n\n"
            "Rules:\n"
            "- Keep the email concise and natural\n"
            "- Do not use markdown\n"
            "- Do not invent detailed facts about the recipient\n"
            "- Use the provided company intelligence to write a relevant pitch\n"
            "- Reference the recommended pitch angle when appropriate\n"
            "- Mention one believable pain point from the intelligence\n"
            "- End with a simple low-friction call to action"
        )

        ci = company_intelligence
        intelligence_block += (
            f"\n\n=== COMPANY INTELLIGENCE ===\n"
            f"Summary: {ci.get('company_summary', 'N/A')}\n"
            f"Recommended pitch angle: {ci.get('recommended_pitch_angle', 'N/A')}\n"
            f"Business pain: {ci.get('business_pain_summary', 'N/A')}\n"
            f"Technology: {ci.get('technology_summary', 'N/A')}\n"
            f"Growth: {ci.get('growth_summary', 'N/A')}\n"
            f"Decision context: {ci.get('decision_context', 'N/A')}\n"
            f"Buying signals: {ci.get('buying_signal_summary', 'N/A')}\n"
            f"Recent events: {ci.get('recent_events_summary', 'N/A')}\n"
            f"Qualification reason: {ci.get('qualification_reason', 'N/A')}\n"
            f"Confidence: {ci.get('confidence_score', 'N/A')}/100\n"
            f"=============================="
        )

    if lead_intelligence:
        li = lead_intelligence
        if not company_intelligence:
            system_text = (
                "You write short personalized cold emails based on sales intelligence.\n"
                "Return valid JSON only with exactly these keys:\n"
                "{\"subject\":\"...\",\"body\":\"...\"}\n\n"
                "Rules:\n"
                "- Keep the email concise and natural\n"
                "- Do not use markdown\n"
                "- Do not invent detailed facts about the recipient\n"
                "- Use the provided lead intelligence to write a relevant pitch\n"
                "- Reference the recommended pitch when appropriate\n"
                "- Mention one believable pain point\n"
                "- End with a simple low-friction call to action"
            )
        intelligence_block += (
            f"\n\n=== LEAD INTELLIGENCE ===\n"
            f"Fit score: {li.get('fit_score', 'N/A')}/100\n"
            f"Confidence: {li.get('confidence', 'N/A')}/100\n"
            f"Buying stage: {li.get('buying_stage', 'N/A')}\n"
            f"Urgency: {li.get('urgency', 'N/A')}\n"
            f"Decision authority: {li.get('decision_authority_summary', 'N/A')}\n"
            f"Business need: {li.get('estimated_business_need', 'N/A')}\n"
            f"Objection risk: {li.get('objection_risk', 'N/A')}\n"
            f"Best contact reason: {li.get('best_contact_reason', 'N/A')}\n"
            f"Recommended pitch: {li.get('recommended_pitch', 'N/A')}\n"
            f"Why selected: {'; '.join(li.get('why_selected', ['N/A']))}\n"
            f"Summary: {li.get('summary', 'N/A')}\n"
            f"========================"
        )

    if not company_intelligence and not lead_intelligence:
        system_text = (
            "You write short personalized cold emails.\n"
            "Return valid JSON only with exactly these keys:\n"
            "{\"subject\":\"...\",\"body\":\"...\"}\n\n"
            "Rules:\n"
            "- Keep the email concise and natural\n"
            "- Do not use markdown\n"
            "- Do not invent detailed facts about the recipient\n"
            "- Mention one believable pain point\n"
            "- End with a simple low-friction call to action"
        )

    user_text = (
        "Write a cold outreach email for this lead.\n\n"
        f"First name: {first_name or 'there'}\n"
        f"Title: {title or 'unknown'}\n"
        f"Company: {company or 'unknown company'}\n"
        f"Pain points: {pain_points}\n"
        f"{intelligence_block}"
    )

    result = _send_openai_request(system_text, user_text)

    try:
        data = json.loads(result)
    except json.JSONDecodeError as error:
        _log(f"generate_outreach_email parse error: {error}")
        _log(f"generate_outreach_email raw result: {result}")
        raise OpenAIError(f"Failed to parse AI response as JSON: {error}")

    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    if not subject or not body:
        raise OpenAIError("AI response missing subject or body")

    return {"subject": subject, "body": body}


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
        data = json.loads(result)
    except json.JSONDecodeError as error:
        _log(f"analyze_draft parse error: {error}, raw: {result}")
        raise OpenAIError(f"Failed to parse analysis as JSON: {error}")
    required = {"quality_score", "strengths", "weaknesses", "biggest_opportunity", "estimated_reply_rate", "recommended_actions"}
    if not all(k in data for k in required):
        raise OpenAIError(f"Analysis missing required keys. Got: {list(data.keys())}")
    return data