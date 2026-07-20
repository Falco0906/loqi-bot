"""Strategy registry for the Planning Engine.

Registration is thread-safe, idempotent, and deterministic.
Default strategies are initialized exactly once per process.
"""

from __future__ import annotations
import logging
import threading
from typing import Optional

from services.planner.planning_models import PlanGoal
from services.planner.strategies.strategy_base import Strategy

logger = logging.getLogger(__name__)

# Global strategy store.  The registry lock protects all mutations.
_strategies: dict[str, Strategy] = {}
_registry_lock = threading.Lock()

# Initialization guard for default strategies.
_default_strategies_initialized = False
_default_strategies_lock = threading.Lock()


def register_strategy(name: str, strategy: Strategy) -> None:
    """Register a strategy. Idempotent: duplicate registrations are ignored."""
    if not name or not isinstance(name, str):
        raise ValueError("strategy name must be a non-empty string")
    if not isinstance(strategy, Strategy):
        raise TypeError("strategy must inherit from Strategy")

    with _registry_lock:
        if name in _strategies:
            logger.debug("Strategy '%s' already registered; skipping", name)
            return
        _strategies[name] = strategy
        logger.info("Registered planning strategy: %s", name)


def get_strategy(name: str) -> Optional[Strategy]:
    with _registry_lock:
        return _strategies.get(name)


def list_strategies() -> list[str]:
    with _registry_lock:
        return list(_strategies.keys())


def clear_strategies() -> None:
    """Clear all registered strategies. Intended for testing only."""
    global _default_strategies_initialized
    with _registry_lock:
        _strategies.clear()
    with _default_strategies_lock:
        _default_strategies_initialized = False


def select_strategy(goal: PlanGoal) -> Optional[Strategy]:
    with _registry_lock:
        strategies_snapshot = dict(_strategies)

    best_score = 0.0
    best_strategy: Optional[Strategy] = None
    for name, strategy in strategies_snapshot.items():
        score = strategy.matches(goal)
        if score > best_score:
            best_score = score
            best_strategy = strategy

    if best_strategy:
        logger.info(
            "Selected strategy '%s' with score %.2f for goal '%s'",
            best_strategy.name, best_score, goal.target_action,
        )
    else:
        logger.warning(
            "No matching strategy found for goal '%s', falling back to general_engagement",
            goal.target_action,
        )
        best_strategy = strategies_snapshot.get("general_engagement")
    return best_strategy


def ensure_default_strategies_registered() -> None:
    """Register default strategies exactly once, in a deterministic order."""
    global _default_strategies_initialized

    with _default_strategies_lock:
        if _default_strategies_initialized:
            return

        # Import here to avoid circular imports at module load time.
        from services.planner.strategies.demo_booking import demo_booking_strategy
        from services.planner.strategies.pricing_objection import pricing_objection_strategy
        from services.planner.strategies.nurture import nurture_strategy
        from services.planner.strategies.cold_outreach import cold_outreach_strategy
        from services.planner.strategies.follow_up import follow_up_strategy
        from services.planner.strategies.re_engagement import re_engagement_strategy
        from services.planner.strategies.general_engagement import general_engagement_strategy
        from services.planner.strategies.escalation import escalation_strategy
        from services.planner.strategies.booking import booking_strategy
        from services.planner.strategies.follow_up_v2 import follow_up_v2_strategy
        from services.planner.strategies.draft_revision import draft_revision_strategy
        from services.planner.strategies.pipeline_outreach import pipeline_outreach_strategy
        from services.planner.strategies.opportunity_development import opportunity_development_strategy
        from services.planner.strategies.next_best_action import next_best_action_strategy
        from services.planner.strategies.memory_outreach import memory_outreach_strategy
        from services.planner.strategies.memory_nba import memory_nba_strategy
        from services.coordinator.strategy import coordinator_strategy

        default_strategies = [
            ("general_engagement", general_engagement_strategy),
            ("demo_booking", demo_booking_strategy),
            ("booking", booking_strategy),
            ("pricing_objection", pricing_objection_strategy),
            ("nurture", nurture_strategy),
            ("cold_outreach", cold_outreach_strategy),
            ("follow_up", follow_up_strategy),
            ("re_engagement", re_engagement_strategy),
            ("escalation", escalation_strategy),
            ("adaptive_follow_up", follow_up_v2_strategy),
            ("draft_revision", draft_revision_strategy),
            ("pipeline_outreach", pipeline_outreach_strategy),
            ("opportunity_development", opportunity_development_strategy),
            ("next_best_action", next_best_action_strategy),
            ("memory_outreach", memory_outreach_strategy),
            ("memory_nba", memory_nba_strategy),
            ("coordinator", coordinator_strategy),
        ]

        for name, strategy in default_strategies:
            register_strategy(name, strategy)

        _default_strategies_initialized = True
        logger.info("Default planning strategies initialized (%d)", len(default_strategies))
