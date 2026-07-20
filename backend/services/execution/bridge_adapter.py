"""BridgeAdapter — adapts an Adapter SDK ExecutionAdapter for the
Execution Engine.

Implements ``services.execution.base_adapter.ExecutionAdapter`` by
wrapping a concrete SDK adapter (e.g. ``GmailAdapter``) and
translating between the two type systems without modifying either
frozen interface.

Responsibilities:
  - ExecutionTask  → AdapterContext
  - AdapterResult  → TaskResult
  - Error classification
  - Metadata propagation
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from services.adapters.adapter_context import AdapterContext
from services.adapters.base_adapter import ExecutionAdapter as SdkAdapter
from services.adapters.models import AdapterMetadata, AdapterResult
from services.execution.base_adapter import ExecutionAdapter
from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import ExecutionTask, TaskResult
from services.planner.planning_models import TaskType


CredentialsFactory = Callable[[ExecutionTask, ExecutionContext], dict[str, str]]


class BridgeAdapter(ExecutionAdapter):
    """Adapter that bridges the Execution Engine and Adapter SDK type systems.

    Wraps an SDK ``ExecutionAdapter`` (e.g. ``GmailAdapter``) and
    exposes it through the execution engine's ``ExecutionAdapter``
    interface.  Task-type dispatch and credential resolution are
    configurable so the same bridge can wrap any SDK adapter.

    Args:
        sdk_adapter:
            The SDK adapter instance to wrap.
        action_mapping:
            Maps each ``TaskType`` the bridge handles to the
            corresponding SDK action string (e.g.
            ``{TaskType.SEND_EMAIL: "gmail_send_email"}``).
        credentials_factory:
            Optional callable that returns a credentials dict for a
            given task and context.  Receives the raw execution task
            and context at invocation time so it can resolve per-user
            credentials (e.g. via ``CredentialResolver``).  Defaults to
            returning an empty dict.
        credentials:
            Static credentials dict used when no factory is provided.
            Overridden if ``credentials_factory`` is set.
    """

    def __init__(
        self,
        sdk_adapter: SdkAdapter,
        action_mapping: dict[TaskType, str],
        credentials_factory: CredentialsFactory | None = None,
        credentials: dict[str, str] | None = None,
    ) -> None:
        self._sdk = sdk_adapter
        self._action_map = action_mapping
        self._creds_factory = credentials_factory
        self._static_creds = credentials or {}
        self._sdk_meta: AdapterMetadata = sdk_adapter.metadata

    # ── Execution Engine interface ──────────────────────────────────────

    @property
    def adapter_type(self) -> str:
        return self._sdk_meta.name

    @property
    def supported_task_types(self) -> list[TaskType]:
        return list(self._action_map.keys())

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        action = self._action_map.get(task.plan_task.type)
        if action is None:
            return _permanent_error(
                task,
                f"No action mapped for task type {task.plan_task.type.value!r}",
            )

        adapter_ctx = self._build_adapter_context(task, context, action)
        sdk_result = await self._sdk.execute(adapter_ctx)
        return self._to_task_result(sdk_result, task)

    def validate(self) -> Optional[list[str]]:
        return None

    # ── Optional lifecycle hooks ────────────────────────────────────────

    def shutdown(self) -> None:
        pass

    async def compensate(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> Optional[TaskResult]:
        return None

    # ── Internal mapping helpers ────────────────────────────────────────

    def _build_adapter_context(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
        action: str,
    ) -> AdapterContext:
        return AdapterContext.build(
            execution_session_id=context.session_id,
            execution_task_id=task.id,
            action=action,
            params=dict(task.plan_task.params),
            credentials=self._resolve_credentials(task, context),
            config={},
            user_context={},
        )

    def _resolve_credentials(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> dict[str, str]:
        if self._creds_factory is not None:
            return self._creds_factory(task, context)
        return dict(self._static_creds)

    @staticmethod
    def _to_task_result(
        sdk_result: AdapterResult,
        task: ExecutionTask,
    ) -> TaskResult:
        if sdk_result.success:
            return TaskResult(
                task_id=task.id,
                attempt=task.attempts,
                success=True,
                output=sdk_result.data or {},
                metadata=dict(sdk_result.metadata),
            )

        error_type = _classify_error(sdk_result)

        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=False,
            error=sdk_result.error or "Adapter execution failed",
            error_type=error_type,
            metadata=dict(sdk_result.metadata),
        )


# ── Helpers ────────────────────────────────────────────────────────


def _permanent_error(task: ExecutionTask, message: str) -> TaskResult:
    return TaskResult(
        task_id=task.id,
        attempt=task.attempts,
        success=False,
        error=message,
        error_type="permanent",
    )


def _classify_error(result: AdapterResult) -> str:
    """Classify an adapter error as transient or permanent.

    Error classification is based on the error_type recorded in
    result metadata (set by the SDK adapter's error mapping) and
    on HTTP status codes.

    Transient:
      - 5xx server errors
      - 429 rate limit
      - Network-level errors (connection refused, timeout)
      - Errors tagged ``TransientAdapterError`` in metadata

    Permanent:
      - 4xx client errors (except 429)
      - Auth failures
      - Invalid requests
      - Errors tagged ``FatalAdapterError``, ``AuthenticationError``,
        etc. in metadata
    """
    meta = result.metadata or {}
    error_type = meta.get("error_type", "")

    # Explicit transient markers from the SDK adapter
    if error_type in ("TransientAdapterError", "RateLimitError"):
        return "transient"

    # Explicit permanent markers
    if error_type in (
        "FatalAdapterError",
        "AuthenticationError",
        "AuthorizationError",
        "PermissionError",
        "ConfigurationError",
        "CredentialNotFoundError",
        "ValidationError",
        "ResourceNotFoundError",
        "MessageNotFoundError",
        "ThreadNotFoundError",
        "LabelNotFoundError",
    ):
        return "permanent"

    # HTTP status code heuristic
    status = meta.get("status_code", 0)
    if status >= 500:
        return "transient"
    if status == 429:
        return "transient"
    if 400 <= status < 500:
        return "permanent"

    # Default: permanent — safety first for unknown errors
    return "permanent"
