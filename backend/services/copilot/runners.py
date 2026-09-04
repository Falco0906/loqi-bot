"""Workspace-scoped Copilot runner adapters over canonical domain services.

The ordered R7 migration moves runner bodies here from ``main.py``. This
module owns execution adapters only; contracts and orchestrator state remain
in their existing modules.
"""


def _discovery_query_from_search_context(search_context: dict) -> str:
    industries = [str(value).strip() for value in search_context.get("industry", []) if str(value).strip()]
    roles = [str(value).strip().replace("_", " ") for value in search_context.get("decision_makers", []) if str(value).strip()]
    locations = [str(value).strip() for value in search_context.get("location", []) if str(value).strip()]
    parts = (["industries: " + ", ".join(industries)] if industries else []) + (["decision makers: " + ", ".join(roles)] if roles else []) + (["locations: " + ", ".join(locations)] if locations else [])
    if isinstance(search_context.get("quantity"), int) and search_context["quantity"] > 0:
        parts.append(f"quantity: {search_context['quantity']}")
    return "Find leads matching " + "; ".join(parts) if parts else "Find leads"


def _discovery_title_from_search_context(search_context: dict) -> str:
    def values(key: str) -> list[str]:
        raw = search_context.get(key, [])
        return [str(value).strip() for value in ([raw] if isinstance(raw, str) else raw) if str(value).strip()]
    def natural(items: list[str]) -> str:
        rendered = [item.replace("_", " ").strip() for item in items]
        return (rendered[0][0].upper() + rendered[0][1:]) if len(rendered) == 1 else (", ".join(rendered[:-1]) + " and " + rendered[-1] if rendered else "")
    industries, roles, locations = values("industry"), values("decision_makers"), values("location")
    if roles:
        normalized = []
        for role in roles:
            words = role.replace("_", " ").split()
            if words and words[-1].lower() not in {"s", "ss"}:
                words[-1] += "s"
            normalized.append(" ".join(words))
        label = natural(normalized)
    elif industries:
        label = f"{natural([item[:-1] if item.lower().endswith('s') and not item.lower().endswith('ss') else item for item in industries])} leads"
    else:
        label = "Leads"
    quantity = search_context.get("quantity")
    if isinstance(quantity, int) and quantity > 0:
        label = f"{quantity} {label[0].lower() + label[1:]}"
    return label + (f" in {natural(locations)}" if locations else "")


async def run_discovery(user_id: str, search_context: dict, session_token: str, *, workspace_id: str) -> dict:
    from services.discovery.service import create_search_run
    return await create_search_run(user_id, _discovery_query_from_search_context(search_context), session_token, display_title=_discovery_title_from_search_context(search_context), workspace_id=workspace_id)
