import asyncio
import concurrent.futures

# TEMPORARY: shared executor for bridging sync→async.
# Remove once handle_message() and the workflow execution path
# become async-native and can directly await GmailAdapter.
# See backlog in AGENTS.md.
_ASYNC_BRIDGE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="async_bridge",
)


def _run_async(coro):
    """TEMPORARY — run a coroutine from a synchronous context.

    Python 3.12+ blocks all forms of nested loop execution within the
    same thread (even ``asyncio.run``, ``Runner.run``, or raw
    ``loop.run_until_complete`` on a fresh loop).  The only
    cross-version way to call async code from a sync function that may
    execute on the event-loop thread is to offload to a worker thread.

    This bridge exists only because handle_message() and the workflow
    dispatch path are still synchronous.  Once they become async-native
    (see backlog), callers should ``await adapter.execute(ctx)``
    directly and this function should be removed.
    """
    return _ASYNC_BRIDGE_EXECUTOR.submit(asyncio.run, coro).result()

from services.google_auth import refresh_access_token
from services.lead_provider import format_leads_message
from services.ai import generate_outreach_email, rewrite_message, analyze_draft, answer_draft_question, OpenAIError
from services.lead_provider import get_leads, search_with_expansion
from services.supabase import get_user, is_token_expired, store_leads, update_google_access_token
from services.conversation_store import record_workflow_event
from services.enrichment.enrichment_factory import get_enricher
from services.intelligence.lead_intelligence import generate_lead_intelligence
from services.adapters.google.gmail import GmailAdapter


VALID_TONES = {"casual", "formal", "aggressive", "friendly"}
VALID_LENGTHS = {"short", "medium", "long"}


def _is_relevant_lead(title: str, target: str) -> bool:
    normalized_title = (title or "").lower()
    keywords = (target or "").lower().split()
    return any(keyword in normalized_title for keyword in keywords)


def _infer_tone(input: dict) -> str:
    explicit_tone = (input.get("tone") or "").strip().lower()
    if explicit_tone in VALID_TONES:
        return explicit_tone

    text_parts = [
        input.get("edit_request") or "",
        * (input.get("conversation_context") or []),
    ]
    combined_text = " ".join(
        part for part in [
            *text_parts,
        ]
        if part
    ).lower()
    word_count = len(combined_text.split())

    if any(word in combined_text for word in ["sir", "madam", "regards", "sincerely", "professional", "formal"]):
        return "formal"
    if word_count and word_count <= 3:
        return "aggressive"
    if "aggressive" in combined_text or "stronger" in combined_text or "hard sell" in combined_text:
        return "aggressive"
    return "casual"


def _infer_length(input: dict) -> str:
    explicit_length = (input.get("length") or "").strip().lower()
    if explicit_length in VALID_LENGTHS:
        return explicit_length

    combined_text = " ".join(
        part for part in [
            input.get("edit_request") or "",
            " ".join(input.get("conversation_context") or []),
        ]
        if part
    ).lower()

    if "shorter" in combined_text or "short" in combined_text:
        return "short"
    if "longer" in combined_text or "long" in combined_text:
        return "long"
    return "medium"


def _normalize_edit_request(edit_request: str) -> str:
    normalized = edit_request.strip()
    lowered = normalized.lower()

    if lowered == "rewrite":
        return "Rewrite the message from scratch using the same goal."
    if "add urgency" in lowered:
        return "Add urgency and make the call to action more time-sensitive."
    return normalized


def _clean_lead_title(lead_title: str) -> str:
    return lead_title.replace("|", "").replace("  ", " ").strip()


def _simplify_lead_title(lead_title: str) -> str:
    title = _clean_lead_title(lead_title).lower()

    if "vp" in title or "vice president" in title:
        return "leading hiring"
    if "head" in title:
        return "leading hiring and people operations"
    if "talent" in title or "recruit" in title:
        return "focused on hiring and talent"
    if "account" in title:
        return "working in accounting"
    if "hr" in title or "human resource" in title:
        return "working in HR"

    return "working in your role"


def generate_leads(input: dict) -> dict:
    import time; _t0 = time.time()
    service = input.get("service") or ""
    target = input.get("target") or ""
    user_id = input.get("user_id")
    workflow_session_id = input.get("workflow_session_id")
    print(f"[TRACE] 5b | ENTERED workflows.generate_leads | +0ms")

    result = search_with_expansion(service, target)
    print(f"[TRACE] 7 | search_with_expansion DONE | +{int((time.time()-_t0)*1000)}ms | {len(result.get('leads',[]))} leads | ok={result.get('ok')}")
    leads = result.get("leads", [])
    icp = result.get("icp")

    if icp:
        print(f"[workflows] Storing ICP: mode={icp.get('mode')}, offer='{icp.get('offer')}'")
        try:
            if workflow_session_id:
                record_workflow_event(
                    session_id=workflow_session_id,
                    event_type="icp.extracted",
                    payload={"structured_icp": icp},
                )
        except Exception as e:
            print(f"[workflows] Failed to store ICP: {e}")

    filtered = [
        lead for lead in leads
        if _is_relevant_lead(lead.get("title", ""), target)
    ]
    if len(filtered) >= 3:
        leads = filtered

    if not result.get("ok") or not leads:
        error = result.get("error") or "unknown_error"
        friendly_error = (
            "I couldn't find strong matches with that search. "
            "Want me to broaden the search or try a slightly different audience?"
        )
        return {
            "ok": False,
            "type": "generate_leads",
            "source": result.get("source", "lead_provider"),
            "leads": [],
            "stored_leads": [],
            "message": friendly_error,
            "error": error,
        }

    stored_leads = store_leads(user_id, leads) if user_id else []

    return {
        "ok": True,
        "type": "generate_leads",
        "source": result.get("source", "lead_provider"),
        "leads": leads,
        "stored_leads": stored_leads,
        "message": format_leads_message(leads),
        "error": None,
    }


def draft_message(input: dict) -> dict:
    lead = input.get("lead") or {}
    lead_name = ((lead.get("name") or "there").split() or ["there"])[0]
    title = _clean_lead_title(lead.get("title") or "")
    company = (lead.get("company") or "").replace("Unknown Company", "").strip()
    edit_request = _normalize_edit_request((input.get("edit_request") or "").strip())
    tone = _infer_tone(input)
    length = _infer_length(input)
    previous_message = input.get("previous_message") or ""
    context = input.get("context") or {}

    company_intelligence = None
    lead_intelligence = None
    try:
        enricher = get_enricher()
        if enricher.health_check().get("ok"):
            company_intelligence = enricher.enrich_lead(lead)
    except Exception as e:
        print(f"[workflows] Enrichment failed (proceeding without): {e}")

    try:
        lead_intelligence = generate_lead_intelligence(lead, company_intelligence)
    except Exception as e:
        print(f"[workflows] Lead intelligence generation failed (proceeding without): {e}")

    subject = ""
    if edit_request and previous_message:
        try:
            llm_message = rewrite_message(edit_request, previous_message, context)
            message = f"Draft ready:\n\n---\n{llm_message}\n---"
        except OpenAIError as e:
            return {
                "ok": False,
                "type": "draft_message",
                "message": f"Couldn't rewrite the draft due to a generation error. Want to try a different instruction or start fresh?",
                "lead": lead,
                "edit_request": edit_request,
                "tone": tone,
                "length": length,
                "error": str(e),
                "company_intelligence": company_intelligence,
                "lead_intelligence": lead_intelligence,
            }
    else:
        try:
            draft = generate_outreach_email(lead, company_intelligence, lead_intelligence)
            message = f"Draft ready:\n\n---\n{draft.get('body', '')}\n---"
            subject = draft.get("subject", "")
        except OpenAIError as e:
            return {
                "ok": False,
                "type": "draft_message",
                "message": f"I wasn't able to generate a draft right now. Try again or adjust the targeting.",
                "lead": lead,
                "edit_request": edit_request,
                "tone": tone,
                "length": length,
                "error": str(e),
                "company_intelligence": company_intelligence,
                "lead_intelligence": lead_intelligence,
            }

    return {
        "ok": True,
        "type": "draft_message",
        "message": message,
        "lead": lead,
        "subject": subject,
        "edit_request": edit_request,
        "tone": tone,
        "length": length,
        "company_intelligence": company_intelligence,
        "lead_intelligence": lead_intelligence,
    }


def analyze_draft_workflow(input: dict) -> dict:
    """Analyze a draft and return structured coaching feedback. Does NOT modify the draft."""
    draft_text = input.get("draft_text") or ""
    context = input.get("context") or {}
    try:
        analysis = analyze_draft(draft_text, context)
        return {
            "ok": True,
            "type": "draft_analysis",
            "analysis": analysis,
            "draft_text": draft_text,
        }
    except OpenAIError as e:
        return {
            "ok": False,
            "type": "draft_analysis",
            "error": str(e),
            "draft_text": draft_text,
        }


def draft_question_workflow(input: dict) -> dict:
    """Answer an educational question about the draft. Does NOT modify the draft."""
    question = input.get("question") or ""
    draft_text = input.get("draft_text") or ""
    context = input.get("context") or {}
    try:
        answer = answer_draft_question(question, draft_text, context)
        return {"ok": True, "type": "draft_question", "answer": answer}
    except OpenAIError as e:
        return {"ok": False, "type": "draft_question", "answer": str(e)}


def _resolve_gmail_credentials(user: dict, user_id: str) -> dict | None:
    access_token = user.get("google_access_token") or ""
    if is_token_expired(user.get("token_expiry")):
        try:
            refreshed = refresh_access_token(user["google_refresh_token"])
            access_token = refreshed.get("access_token", "")
            updated_user = update_google_access_token(
                user_id,
                access_token=access_token,
                token_expiry=refreshed.get("token_expiry"),
            )
            if updated_user:
                user = updated_user
        except Exception:
            return None
    return {"access_token": access_token, "_user": user}


def send_outreach(input: dict) -> dict:
    lead = input.get("lead") or {}
    user_id = input.get("user_id")

    user = get_user(user_id) if user_id else None
    if user is None:
        return {
            "ok": False,
            "type": "send_outreach",
            "message": "Something went wrong on my end. Mind trying again?",
            "error": "missing_user",
        }

    if not user.get("google_refresh_token"):
        return {
            "ok": False,
            "type": "send_outreach",
            "message": "Gmail isn't connected yet. Connect it once and I'll be able to send outreach directly from Loqi.",
            "error": "missing_google_tokens",
        }

    creds = _resolve_gmail_credentials(user, user_id)
    if creds is None:
        return {
            "ok": False,
            "type": "send_outreach",
            "message": "Your Gmail connection expired. Connect it again with /connect and I'll be ready to send.",
            "error": "token_refresh_failed",
        }
    user = creds.get("_user", user)

    company_intelligence = None
    lead_intelligence = None
    try:
        enricher = get_enricher()
        if enricher.health_check().get("ok"):
            company_intelligence = enricher.enrich_lead(lead)
    except Exception as e:
        print(f"[workflows] Enrichment failed during send (proceeding without): {e}")

    try:
        lead_intelligence = generate_lead_intelligence(lead, company_intelligence)
    except Exception as e:
        print(f"[workflows] Lead intelligence failed during send (proceeding without): {e}")

    try:
        draft = generate_outreach_email(lead, company_intelligence, lead_intelligence)

        # Route through Execution Engine via single-task Plan.
        # The globally registered Gmail BridgeAdapter (with its
        # credentials_factory) resolves per-user credentials from
        # credential_user_id — no per-request adapter construction.
        from services.execution.execution_pipeline import get_pipeline
        from services.execution.adapter_registry_resolver import get_planner_resolver
        from services.planner.planning_models import Plan, PlanStatus, Task, TaskType

        send_task = Task(
            type=TaskType.SEND_EMAIL,
            label="Send outreach email",
            instructions=f"Send outreach email to {lead.get('name', 'Unknown')}",
            params={
                "payload_type": "MessagePayload",
                "channel": "email",
                "template": "",
                "to": [lead.get("email", "")],
                "subject": draft.get("subject", "Sent"),
                "body_plain": draft.get("body", ""),
                "credential_user_id": user_id,
            },
        )
        plan = Plan(tasks=[send_task], status=PlanStatus.VALIDATED, strategy="direct_outreach")
        send_task.plan_id = plan.id

        resolver = get_planner_resolver()
        if resolver is None:
            raise Exception("Planner resolver not available — global registry not initialised")

        session = _run_async(get_pipeline().execute(plan, resolver=resolver))

        etask = session.tasks.get(send_task.id)
        if not etask or not etask.result or not etask.result.success:
            raise Exception(
                (etask and etask.result and etask.result.error) or "Send failed"
            )
    except OpenAIError as e:
        return {
            "ok": False,
            "type": "send_outreach",
            "message": "I couldn't generate the email content. Let me try again — or adjust the draft first.",
            "error": f"openai_error: {e}",
        }
    except Exception:
        return {
            "ok": False,
            "type": "send_outreach",
            "message": "The email didn't go through. Gmail may need reconnecting — try /connect to set it up again.",
            "error": "send_failed",
        }

    company = (lead.get("company") or "").replace("Unknown Company", "").strip()
    company_part = f" @ {company}" if company else ""
    subject = draft.get("subject", "Sent")

    return {
        "ok": True,
        "type": "send_outreach",
        "message": (
            "Looks good — I'll send this from your connected Gmail.\n\n"
            f"To: {lead.get('name', 'Unknown')}{company_part}\n"
            f"Subject: {subject}"
        ),
        "result": draft,
    }


def run_workflow(input: dict) -> dict:
    workflow_type = input.get("type")

    if workflow_type == "generate_leads":
        return generate_leads(input)

    if workflow_type == "draft_message":
        return draft_message(input)

    if workflow_type == "draft_analysis":
        return analyze_draft_workflow(input)

    if workflow_type == "draft_question":
        return draft_question_workflow(input)

    if workflow_type == "send_outreach":
        return send_outreach(input)

    return {
        "ok": False,
        "type": workflow_type,
        "message": "Unknown workflow.",
        "error": "unknown_workflow",
    }