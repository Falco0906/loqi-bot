"""Action Registry — maps ActionType to executor functions.

Executor only dispatches through this registry.
Business services are never called directly by the executor.
"""

from services.workflow_models import ActionType, WorkflowStep


def _log(msg: str) -> None:
    print(f"[workflow_registry] {msg}")


def _execute_search_leads(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_search_leads: {step.title}")
    return {"ok": True, "action": "search_leads", "message": f"Searching: {step.title}"}


def _execute_expand_search(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_expand_search: {step.title}")
    return {"ok": True, "action": "expand_search", "message": f"Expanding search: {step.title}"}


def _execute_filter_leads(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_filter_leads: {step.title}")
    return {"ok": True, "action": "filter_leads", "message": "Filtering leads"}


def _execute_select_leads(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_select_leads: {step.title}")
    return {"ok": True, "action": "select_leads", "message": "Leads selected"}


def _execute_create_campaign(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_create_campaign: {step.title}")
    return {"ok": True, "action": "create_campaign", "message": f"Creating campaign: {step.title}"}


def _execute_update_campaign(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_update_campaign: {step.title}")
    return {"ok": True, "action": "update_campaign", "message": "Campaign updated"}


def _execute_generate_drafts(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_generate_drafts: {step.title}")
    return {"ok": True, "action": "generate_drafts", "message": "Generating drafts..."}


def _execute_review_drafts(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_review_drafts: {step.title}")
    return {"ok": True, "action": "review_drafts", "message": "Drafts reviewed"}


def _execute_rewrite_drafts(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_rewrite_drafts: {step.title}")
    return {"ok": True, "action": "rewrite_drafts", "message": "Drafts rewritten"}


def _execute_launch_campaign(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_launch_campaign: {step.title}")
    return {"ok": True, "action": "launch_campaign", "message": f"Launching: {step.title}"}


def _execute_navigate(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_navigate: {step.title}")
    return {"ok": True, "action": "navigate", "message": f"Navigating: {step.title}"}


def _execute_analyze_campaign(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_analyze_campaign: {step.title}")
    return {"ok": True, "action": "analyze_campaign", "message": "Analyzing campaign"}


def _execute_wait_for_user(step: WorkflowStep, session_token: str, context: dict) -> dict:
    _log(f"execute_wait_for_user: {step.title}")
    return {"ok": True, "action": "wait_for_user", "message": step.title, "requires_approval": True}


EXECUTOR_REGISTRY: dict[ActionType, callable] = {
    ActionType.SEARCH_LEADS: _execute_search_leads,
    ActionType.EXPAND_SEARCH: _execute_expand_search,
    ActionType.FILTER_LEADS: _execute_filter_leads,
    ActionType.SELECT_LEADS: _execute_select_leads,
    ActionType.CREATE_CAMPAIGN: _execute_create_campaign,
    ActionType.UPDATE_CAMPAIGN: _execute_update_campaign,
    ActionType.GENERATE_DRAFTS: _execute_generate_drafts,
    ActionType.REVIEW_DRAFTS: _execute_review_drafts,
    ActionType.REWRITE_DRAFTS: _execute_rewrite_drafts,
    ActionType.LAUNCH_CAMPAIGN: _execute_launch_campaign,
    ActionType.NAVIGATE: _execute_navigate,
    ActionType.ANALYZE_CAMPAIGN: _execute_analyze_campaign,
    ActionType.WAIT_FOR_USER: _execute_wait_for_user,
}


def dispatch(action_type: ActionType, step: WorkflowStep, session_token: str, context: dict | None = None) -> dict:
    executor = EXECUTOR_REGISTRY.get(action_type)
    if not executor:
        return {"ok": False, "error": f"No executor registered for {action_type}"}
    try:
        return executor(step, session_token, context or {})
    except Exception as e:
        return {"ok": False, "error": str(e)}
