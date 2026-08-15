"""Development Reply Simulator — pluggable inbound event producer.

Dev-only: enabled exclusively when SIMULATE_REPLIES=true. Production
behavior is unchanged when disabled (all public hooks are no-ops).

Whenever an outbound email is sent (Send Now or campaign launch), the
simulator schedules a synthetic inbound reply. When due, the reply is fed
through the EXACT same pipeline a real Gmail reply uses:

    ProviderMessage
      -> _process_provider_message()   (dedup, thread mapping, normalize,
                                        reply intelligence, MESSAGE_RECEIVED)
      -> conversations.handle_reply()  (classification, status, timeline)

The Inbox never branches on whether an event came from Gmail or the
simulator. Swapping producers later only requires a Gmail webhook to build
the same ProviderMessage and call the same two functions.

No-reply outcomes schedule a follow-up timer instead (conversation moves to
FOLLOW_UP_PENDING when it stays unanswered).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.communication.communication_store import store
from services.communication.gmail_sync import _process_provider_message
from services.communication.provider_models import MessageDirection, ProviderMessage
from services.conversations.conversation_models import ConversationStatus, ConversationSummary
from services.conversations.conversation_store import conversation_store
from services.conversations.followup_planner import followup_planner_service
from services.conversations.integration import handle_reply
from services.conversations.state_machine import transition as state_transition
from services.conversations.timeline import TimelineEventType, build_timeline_event

logger = logging.getLogger(__name__)

SIM_PROVIDER_ID = "sim_reply"

STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".simulate_replies.json",
)

# ── Scenario configuration (configurable constants; env-overridable) ──


@dataclass(frozen=True)
class Scenario:
    key: str
    weight: int
    delay_min_minutes: int
    delay_max_minutes: int


# Default probabilities per spec: no reply ~70%, interested ~10%,
# pricing ~6%, referral ~4%, competitor ~4%, OOO ~3%, not interested ~3%.
SCENARIOS: list[Scenario] = [
    Scenario("no_reply", 70, 0, 0),
    Scenario("interested", 10, 60, 240),        # 1-4 hours
    Scenario("pricing_request", 6, 20, 60),     # 20-60 mins
    Scenario("referral", 4, 360, 1440),         # 6-24 hours
    Scenario("competitor", 4, 120, 480),        # 2-8 hours
    Scenario("out_of_office", 3, 0, 2),         # immediately
    Scenario("not_interested", 3, 30, 180),
]

# Follow-up timer delay when the outcome is "no reply" (2-3 days).
FOLLOW_UP_DELAY_MINUTES: tuple[int, int] = (2880, 4320)

# Accelerated mode (SIMULATE_ACCELERATED=true): seconds instead of hours.
ACCELERATED_REPLY_SECONDS: tuple[int, int] = (10, 45)
ACCELERATED_OOO_SECONDS: tuple[int, int] = (5, 15)
ACCELERATED_FOLLOW_UP_SECONDS: tuple[int, int] = (60, 120)

rng = random.Random()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


def is_enabled() -> bool:
    """True when SIMULATE_REPLIES=true (development-only gate)."""
    return _env_bool("SIMULATE_REPLIES")


def _multiplier() -> float:
    try:
        return max(0.0, float(os.getenv("SIMULATE_REPLY_MULTIPLIER", "1.0")))
    except ValueError:
        return 1.0


def _weights() -> dict[str, int]:
    """Scenario weights; SIMULATE_REPLY_WEIGHTS (JSON) overrides defaults."""
    default = {s.key: s.weight for s in SCENARIOS}
    raw = os.getenv("SIMULATE_REPLY_WEIGHTS", "")
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                if key in default:
                    default[key] = max(0, int(value))
    except (ValueError, TypeError):
        logger.warning("[sim] Ignoring invalid SIMULATE_REPLY_WEIGHTS=%r", raw)
    return default


# ── Provider facade (gmail_sync only touches provider_id/_provider_id) ──


class SimProvider:
    """Minimal provider facade for the shared ingestion pipeline."""

    def __init__(self) -> None:
        self._provider_id = SIM_PROVIDER_ID

    @property
    def provider_id(self) -> str:
        return self._provider_id


_sim_provider = SimProvider()

# ── Personalization ──


def _first_name(full_name: str) -> str:
    return full_name.split()[0] if full_name else ""


def _company_from_email(email: str) -> str:
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    domain = domain.rsplit(".", 1)[0] if "." in domain else domain
    return domain.replace("-", " ").replace("_", " ").title()


_TEMPLATES: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "interested": [
        ("Thanks {first}. We're interested — currently evaluating options at {company} for the next quarter, so happy to hear your approach.", ()),
        ("Hey {first}, this is actually relevant to what we're working on — we're interested in a quick call to dig into it.", ()),
        ("Sounds good. We've been meaning to look at this — could you share more on how it fits {company}?", ()),
        ("Thanks {first}. We're interested, but implementation timeline is our biggest concern. How fast could this be live for {company}?", ("operations", "ops", "manager")),
        ("This looks promising for our team — we're interested. When do you have time to walk us through it?", ("marketing",)),
    ],
    "pricing_request": [
        ("Could you share pricing before we schedule a call? Want to make sure it fits our budget first.", ()),
        ("What does this cost? Send over your pricing tiers if you have them.", ()),
        ("Before we go further — do you have a pricing page or a ballpark quote for {company}?", ()),
    ],
    "referral": [
        ("We're set for now, but a colleague at {company} might be interested — I'll forward your email to them.", ()),
        ("Not for us at the moment. I know a few teams who could use this though — happy to refer you to them.", ()),
        ("Thanks for reaching out. I'll refer you to our {role} — they handle this for {company}.", ()),
    ],
    "competitor": [
        ("We're already working with another automation provider, so we're covered — but thanks.", ()),
        ("We just signed with a vendor for this last month, so not in the market right now.", ()),
        ("Appreciate the note — we went with someone else a few weeks ago. Good luck.", ()),
    ],
    "out_of_office": [
        ("I'm currently out of office and will return on Monday. I'll get back to your message as soon as I'm back.", ()),
        ("Out of office until next week — I'll respond to your email when I return.", ()),
        ("Thanks for your email. I'm out of office this week — I'll reply when I'm back.", ()),
    ],
    "not_interested": [
        ("Not interested, thanks. Please remove me from your list.", ()),
        ("Thanks for reaching out, but it's not relevant to {company} right now.", ()),
        ("Please take us off your mailing list — we're not interested right now.", ()),
    ],
}


def generate_reply_body(scenario_key: str, context: dict[str, Any]) -> str:
    """Produce a believable reply for the scenario using lead context."""
    pool = _TEMPLATES.get(scenario_key, _TEMPLATES["interested"])
    role = (context.get("role") or "").lower()
    variant: Optional[str] = None
    for text, role_hints in pool:
        if role_hints and any(hint in role for hint in role_hints):
            variant = text
            break
    if variant is None:
        variant = rng.choice([text for text, _ in pool])

    first = _first_name(context.get("lead_name", ""))
    company = context.get("company", "")
    role_label = context.get("role", "") or "team"
    if not first:
        first = "there"
    if not company:
        company = "us"
    return variant.format(first=first, company=company, role=role_label)


# ── Pending queue (dev-only, persisted so restarts keep scheduled replies) ──

_pending: list[dict[str, Any]] = []
_loaded = False


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _valid_entry(entry: dict) -> bool:
    return bool(entry.get("kind")) and _parse_dt(entry.get("fire_at")) is not None


def _load_state() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _pending[:] = [e for e in data if isinstance(e, dict) and _valid_entry(e)]
    except Exception as e:
        logger.warning("[sim] state load failed: %s", e)


def _persist() -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_pending, f, indent=2)
    except Exception as e:
        logger.warning("[sim] state persist failed: %s", e)


def pending_count() -> int:
    _load_state()
    return len(_pending)


# ── Scheduling ──


def maybe_schedule(context: dict[str, Any]) -> None:
    """Public hook after a successful outbound send. No-op when disabled."""
    if not is_enabled():
        return
    try:
        _schedule(context)
    except Exception as e:
        logger.error("[sim] Scheduling failed: %s", e, exc_info=True)


def _schedule(context: dict[str, Any]) -> None:
    _load_state()
    weights = _weights()
    if sum(weights.values()) <= 0:
        return

    total = float(sum(weights.values()))
    roll = rng.uniform(0.0, total)
    accrued = 0.0
    chosen = SCENARIOS[0]
    for scenario in SCENARIOS:
        accrued += weights[scenario.key]
        if roll <= accrued:
            chosen = scenario
            break

    if chosen.key == "no_reply":
        entry = _base_entry(context)
        entry.update({"kind": "follow_up", "fire_at": _follow_up_fire_at().isoformat()})
        _pending.append(entry)
        logger.info(
            "[sim] no-reply scenario | conversation=%s follow_up_timer=%s",
            context.get("conversation_id", "")[:12], entry["fire_at"],
        )
    else:
        entry = _base_entry(context)
        entry.update({"kind": "reply", "scenario": chosen.key, "fire_at": _reply_fire_at(chosen).isoformat()})
        _pending.append(entry)
        logger.info(
            "[sim] %s scenario scheduled | conversation=%s reply_at=%s",
            chosen.key, context.get("conversation_id", "")[:12], entry["fire_at"],
        )
    _persist()


def _base_entry(context: dict[str, Any]) -> dict[str, Any]:
    lead = context.get("lead", {}) or {}
    return {
        "conversation_id": context.get("conversation_id", ""),
        "external_thread_id": context.get("external_thread_id", ""),
        "subject": context.get("subject", ""),
        "from_email": context.get("from_email", ""),
        "from_name": context.get("from_name", ""),
        "to_email": context.get("to_email", ""),
        "to_name": context.get("to_name", ""),
        "outbound_body": context.get("body", ""),
        "campaign_id": context.get("campaign_id", ""),
        "workflow_id": context.get("workflow_id", ""),
        "lead": lead,
        "objective": context.get("objective", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _reply_fire_at(scenario: Scenario) -> datetime:
    now = datetime.now(timezone.utc)
    if _env_bool("SIMULATE_ACCELERATED"):
        seconds_range = (
            ACCELERATED_OOO_SECONDS if scenario.key == "out_of_office" else ACCELERATED_REPLY_SECONDS
        )
        return now + timedelta(seconds=rng.uniform(*seconds_range))
    minutes = rng.uniform(scenario.delay_min_minutes, scenario.delay_max_minutes)
    return now + timedelta(seconds=minutes * 60.0 * _multiplier())


def _follow_up_fire_at() -> datetime:
    now = datetime.now(timezone.utc)
    if _env_bool("SIMULATE_ACCELERATED"):
        return now + timedelta(seconds=rng.uniform(*ACCELERATED_FOLLOW_UP_SECONDS))
    minutes = rng.uniform(*FOLLOW_UP_DELAY_MINUTES)
    return now + timedelta(seconds=minutes * 60.0 * _multiplier())


# ── Scheduler loop ──

_task: Optional[asyncio.Task] = None


def start_scheduler() -> asyncio.Task:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run_loop())
    return _task


def stop_scheduler() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()


async def _run_loop() -> None:
    logger.info("[sim] Reply simulator scheduler started")
    while True:
        try:
            fire_due()
        except Exception as e:
            logger.error("[sim] fire pass failed: %s", e, exc_info=True)
        await asyncio.sleep(5.0)


def fire_due(now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Fire all due entries through the shared pipelines. Idempotent."""
    _load_state()
    now = now or datetime.now(timezone.utc)
    fired: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for entry in _pending:
        if _parse_dt(entry.get("fire_at")) <= now:
            fired.append(entry)
        else:
            remaining.append(entry)
    if not fired:
        return []
    _pending[:] = remaining
    for entry in fired:
        try:
            if entry.get("kind") == "follow_up":
                _fire_follow_up(entry)
            else:
                _fire_reply(entry)
        except Exception as e:
            logger.error("[sim] firing %s failed: %s", entry.get("kind"), e, exc_info=True)
    _persist()
    return fired


# ── Firing (the exact Gmail reply path) ──


def _fire_reply(entry: dict[str, Any]) -> None:
    conversation_id = entry.get("conversation_id", "")
    thread_id = entry.get("external_thread_id", "")
    if not conversation_id or not thread_id:
        logger.warning("[sim] fire skipped: missing conversation/thread id")
        return

    convo = conversation_store.get_conversation(conversation_id)
    if convo is None:
        logger.info("[sim] fire skipped: conversation %s no longer exists", conversation_id[:12])
        return
    if convo.message_count > 1:
        logger.info("[sim] fire skipped: conversation %s already has inbound activity", conversation_id[:12])
        return

    lead = entry.get("lead", {}) or {}
    lead_email = entry.get("to_email", "")
    lead_name = entry.get("to_name", "") or lead.get("name", "")
    agent_email = entry.get("from_email", "")
    agent_name = entry.get("from_name", "")
    company = lead.get("company", "") or _company_from_email(lead_email)
    received_at = _parse_dt(entry.get("fire_at")) or datetime.now(timezone.utc)
    scenario_key = entry.get("scenario", "interested")
    reply_subject = f"Re: {entry.get('subject', '')}"

    body = generate_reply_body(scenario_key, {
        "lead_name": lead_name,
        "company": company,
        "role": lead.get("role", "") or lead.get("title", ""),
        "objective": entry.get("objective", ""),
        "outbound_body": entry.get("outbound_body", ""),
    })

    # 1. Thread mapping — same as Gmail sync's first contact with a thread.
    if not store.get_thread_mapping(thread_id):
        store.map_thread(
            external_thread_id=thread_id,
            conversation_id=conversation_id,
            provider_id=_sim_provider.provider_id,
            subject=reply_subject,
        )

    # 2. ProviderMessage through the shared Gmail ingestion pipeline.
    external_id = f"sim_{uuid.uuid4().hex[:16]}"
    provider_msg = ProviderMessage(
        provider_id=_sim_provider.provider_id,
        external_id=external_id,
        thread_id=thread_id,
        direction=MessageDirection.INCOMING,
        raw_headers={
            "from": f"{lead_name} <{lead_email}>" if lead_name else lead_email,
            "to": f"{agent_name} <{agent_email}>" if agent_name else agent_email,
            "subject": reply_subject,
            "message-id": external_id,
        },
        raw_body=body,
        received_at=received_at.isoformat(),
        provider_metadata={"simulated": True, "scenario": scenario_key},
    )
    try:
        _process_provider_message(_sim_provider, provider_msg)
    except Exception as e:
        logger.error("[sim] intelligence pipeline failed for %s: %s", external_id, e)

    # 3. Conversations module: classification, status transition, timeline.
    try:
        handle_reply(
            conversation_id=conversation_id,
            external_message_id=external_id,
            from_email=lead_email,
            from_name=lead_name,
            to_email=agent_email,
            to_name=agent_name,
            subject=reply_subject,
            body=body,
            timestamp=received_at,
        )
    except Exception as e:
        logger.error("[sim] handle_reply failed: %s", e, exc_info=True)

    # 4. Inbox summary + follow-up planning through the existing planner.
    _record_follow_up_plan(
        conversation_id,
        lead_name=lead_name,
        company=company,
        body=body,
        category=conversation_store.get_conversation(conversation_id).metadata.get("last_reply_category", ""),
    )

    logger.info(
        "[sim] synthetic reply fired | conversation=%s scenario=%s body=%r",
        conversation_id[:12], scenario_key, body[:90],
    )


def _record_follow_up_plan(
    conversation_id: str,
    lead_name: str = "",
    company: str = "",
    body: str = "",
    category: str = "",
) -> None:
    convo = conversation_store.get_conversation(conversation_id)
    if not convo:
        return
    plan = followup_planner_service.plan(convo)
    convo.metadata["follow_up_plan"] = {
        "should_follow_up": plan.should_follow_up,
        "priority": plan.priority.value,
        "objective": plan.objective.value if plan.objective else "",
        "suggested_timing": plan.suggested_timing.isoformat() if plan.suggested_timing else "",
        "reason": plan.reason,
        "confidence": plan.confidence,
    }
    summary = convo.summary or ConversationSummary()
    summary.company = summary.company or company
    summary.contact_name = summary.contact_name or lead_name
    summary.interest_level = category or summary.interest_level
    summary.next_action = plan.objective.value if plan.objective else ""
    summary.last_summary = body[:200] or summary.last_summary
    summary.updated_at = datetime.now(timezone.utc)
    convo.summary = summary
    if plan.should_follow_up:
        conversation_store.add_timeline_event(build_timeline_event(
            conversation_id=conversation_id,
            event_type=TimelineEventType.FOLLOW_UP_SUGGESTED,
            title="Follow-up suggested",
            description=plan.reason,
            metadata={
                "priority": plan.priority.value,
                "objective": plan.objective.value if plan.objective else "",
                "suggested_timing": plan.suggested_timing.isoformat() if plan.suggested_timing else "",
            },
        ))
    conversation_store.update_conversation(convo)


def _fire_follow_up(entry: dict[str, Any]) -> None:
    conversation_id = entry.get("conversation_id", "")
    convo = conversation_store.get_conversation(conversation_id)
    if convo is None:
        logger.info("[sim] follow-up timer skipped: conversation %s gone", conversation_id[:12])
        return
    if convo.status != ConversationStatus.SENT:
        logger.info(
            "[sim] follow-up timer skipped: conversation %s moved to %s",
            conversation_id[:12], convo.status.value,
        )
        return
    try:
        convo.status = state_transition(convo.status, ConversationStatus.FOLLOW_UP_PENDING)
    except ValueError:
        return
    plan = followup_planner_service.plan(convo)
    convo.metadata["follow_up_timer"] = {"scheduled": True, "due": entry.get("fire_at")}
    conversation_store.add_timeline_event(build_timeline_event(
        conversation_id=conversation_id,
        event_type=TimelineEventType.FOLLOW_UP_SUGGESTED,
        title="Follow-up timer due (no reply)",
        description="No reply received; conversation queued for follow-up.",
        metadata={"objective": plan.objective.value if plan.objective else "check_in"},
    ))
    conversation_store.update_conversation(convo)
    logger.info("[sim] follow-up timer fired | conversation=%s -> follow_up_pending", conversation_id[:12])
