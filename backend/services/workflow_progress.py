"""Workflow Progress — pure calculation service.

Responsible ONLY for:
- current step
- completed steps
- percentage
- ETA estimation

No execution logic.
"""

from services.workflow_runtime import RuntimeEntry, RuntimeStatus


def calculate_progress(runtime: RuntimeEntry) -> dict:
    steps = runtime.plan.get("steps", [])
    total = len(steps)
    completed = len(runtime.completed_steps)
    failed = len(runtime.failed_steps)
    current = runtime.current_step_index

    if total == 0:
        return {
            "total_steps": 0,
            "completed_steps": 0,
            "current_step": -1,
            "current_step_title": "",
            "percentage": 0,
            "estimated_remaining": "unknown",
            "status": runtime.status.value,
        }

    percentage = round((completed / total) * 100) if total > 0 else 0

    current_step_title = ""
    current_action_type = ""
    if 0 <= current < total:
        step = steps[current]
        current_step_title = step.get("title", "")
        current_action_type = step.get("action_type", "")

    estimated_remaining = _estimate_remaining(runtime, total, completed)

    return {
        "total_steps": total,
        "completed_steps": completed,
        "failed_steps": failed,
        "current_step": current,
        "current_step_title": current_step_title,
        "current_action_type": current_action_type,
        "percentage": percentage,
        "estimated_remaining": estimated_remaining,
        "status": runtime.status.value,
    }


def _estimate_remaining(runtime: RuntimeEntry, total: int, completed: int) -> str:
    if runtime.status in (RuntimeStatus.COMPLETED, RuntimeStatus.FAILED, RuntimeStatus.CANCELLED):
        return "done"
    if runtime.status == RuntimeStatus.WAITING_APPROVAL:
        return "waiting for approval"

    pending = total - completed
    if pending <= 0:
        return "any moment"

    if completed == 0:
        return "calculating..."

    if runtime.started_at:
        try:
            from datetime import datetime, timezone
            start = datetime.fromisoformat(runtime.started_at.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            if elapsed > 0 and completed > 0:
                per_step = elapsed / completed
                remaining_secs = int(per_step * pending)
                if remaining_secs < 60:
                    return f"~{remaining_secs}s"
                return f"~{remaining_secs // 60}m {remaining_secs % 60}s"
        except (ValueError, TypeError):
            pass

    return "calculating..."
