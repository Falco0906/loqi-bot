from services.world_model.events import EventType, WorkspaceEvent
from services.world_model.store import InMemoryWorldModelStore

_world_model_store = InMemoryWorldModelStore()


def get_store() -> InMemoryWorldModelStore:
    return _world_model_store


def publish(
    session_id: str,
    event_type: EventType,
    data: dict,
    actor: str = "system",
    parent_id: str | None = None,
) -> str:
    event = WorkspaceEvent(
        type=event_type,
        session_id=session_id,
        actor=actor,
        data=data,
        parent_id=parent_id,
    )
    return _world_model_store.append_event(event)
