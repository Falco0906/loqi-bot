"""Workflow Recovery — auto-restore workflows after process restart.

On FastAPI startup:
1. Load persisted workflows
2. Restore runtime entries
3. Inspect status:
   - RUNNING: resume execution
   - WAITING_APPROVAL: restore waiting state
   - COMPLETED/FAILED/CANCELLED: leave untouched
   - PAUSED: leave paused
"""

from services.workflow_runtime import RuntimeStatus, restore_runtime
from services.workflow_persistence import load_all
from services.workflow_events import emit_workflow_recovered, restore_events


def _log(msg: str) -> None:
    print(f"[workflow_recovery] {msg}")


def recover_all() -> dict:
    """Load and restore all persisted workflows.

    Returns summary of what was recovered.
    """
    entries = load_all()
    summary = {
        "total_recovered": len(entries),
        "resumed": 0,
        "waiting_approval_restored": 0,
        "left_untouched": 0,
        "paused_left": 0,
    }

    for entry in entries:
        restore_events(entry.workflow_id, entry.events)

        if entry.status == RuntimeStatus.RUNNING:
            _log(f"Resuming workflow {entry.workflow_id}: {entry.plan.get('goal', '')}")
            entry.status = RuntimeStatus.PLANNED
            restore_runtime(entry)
            entry.status = RuntimeStatus.RUNNING
            emit_workflow_recovered(entry.workflow_id)
            from services.workflow_executor import execute_remaining
            from services.workflow_models import WorkflowPlan
            plan = WorkflowPlan(**entry.plan)
            execute_remaining(plan, entry.session_token, entry.current_step_index)
            summary["resumed"] += 1

        elif entry.status == RuntimeStatus.WAITING_APPROVAL:
            _log(f"Restoring waiting approval for {entry.workflow_id}: {entry.plan.get('goal', '')}")
            restore_runtime(entry)
            emit_workflow_recovered(entry.workflow_id)
            summary["waiting_approval_restored"] += 1

        elif entry.status == RuntimeStatus.PAUSED:
            _log(f"Leaving paused workflow {entry.workflow_id}")
            restore_runtime(entry)
            emit_workflow_recovered(entry.workflow_id)
            summary["paused_left"] += 1

        else:
            _log(f"Restoring {entry.status.value} workflow {entry.workflow_id}")
            restore_runtime(entry)
            summary["left_untouched"] += 1

    if entries:
        _log(f"Recovery complete: {summary}")
    else:
        _log("No persisted workflows to recover")

    return summary
