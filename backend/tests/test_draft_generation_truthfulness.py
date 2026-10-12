import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import requests

from services.drafts import service as drafts
from services.intelligence import ai
from services.knowledge.context_adapter import KnowledgePromptContext
from services.job_engine.models import Job, BatchItem, BatchItemStatus
from services.job_engine.storage import JobStorage


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [
    {"ok": False, "message": "Provider unavailable"},
    {"ok": True, "body": ""},
    {"message": "Provider failed"},
])
async def test_failed_or_empty_model_output_cannot_be_a_completed_draft(monkeypatch, result):
    monkeypatch.setattr(drafts, "_recover_batch_draft", AsyncMock(return_value=None))
    item = BatchItem("job", "workspace", "", 0, {"id": "lead"}, "lead")
    failures = []
    class Storage:
        def list_batch_resume_items(self, *args, **kwargs): return [item]
        def list_batch_items(self, *args, **kwargs): return [item]
        def mark_batch_item_generating(self, *_args): return True
        def mark_batch_item_failed(self, identity, error):
            item.status = BatchItemStatus.FAILED; failures.append(error); return True
        def mark_batch_item_completed(self, *_args): pytest.fail("Failed output cannot complete")
    monkeypatch.setattr("services.job_engine.job_manager._storage", Storage())
    async def context(*args, **kwargs):
        assert kwargs["workspace_id"] == "workspace"
        return KnowledgePromptContext()
    monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", context)
    monkeypatch.setattr(drafts, "_run_draft_with_retry", AsyncMock(return_value=result))
    persist = AsyncMock()
    monkeypatch.setattr("services.workspace.state.persist_draft_awaited", persist)
    monkeypatch.setattr(drafts, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(drafts, "publish_draft_event", AsyncMock())
    response = await drafts.run_draft_batch_job(Job(id="job", user_id="actor", workspace_id="workspace"), lambda *_args: None)
    assert response["ok"] is False and response["result"]["generated"] == 0
    assert response["result"]["failed"] == 1 and failures
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_programming_error_is_not_retried_as_provider_failure(monkeypatch):
    calls = []
    def broken(_input): calls.append(1); raise TypeError("implementation defect")
    monkeypatch.setattr(drafts, "_draft_message_from_legacy_input", broken)
    with pytest.raises(TypeError, match="implementation defect"):
        await drafts._run_draft_with_retry(asyncio.get_running_loop(), {})
    assert calls == [1]


@pytest.mark.asyncio
async def test_failure_result_cannot_bypass_retry_helper_validation(monkeypatch):
    monkeypatch.setattr(drafts, "_draft_message_from_legacy_input", lambda *_args: {"ok": False, "message": "error fallback"})
    with pytest.raises(ai.OpenAIError): await drafts._run_draft_with_retry(asyncio.get_running_loop(), {})


@pytest.mark.asyncio
async def test_explicit_workspace_context_failure_is_not_empty_guidance(monkeypatch):
    class Storage:
        def list_batch_resume_items(self, *args, **kwargs): return []
        def list_batch_items(self, *args, **kwargs): return []
    monkeypatch.setattr("services.job_engine.job_manager._storage", Storage())
    error = RuntimeError("Knowledge repository unavailable")
    async def context(*args, **kwargs):
        assert kwargs["workspace_id"] == "workspace"
        raise error
    monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", context)
    with pytest.raises(RuntimeError) as caught:
        await drafts.run_draft_batch_job(Job(id="job", user_id="actor", workspace_id="workspace"), None)
    assert caught.value is error


@pytest.mark.parametrize("operation,args", [("get_job", ("job",)), ("list_batch_items", ("job", "workspace")), ("list_batch_resume_items", ("job", "workspace"))])
def test_strict_storage_unavailability_never_looks_like_empty_results(monkeypatch, operation, args):
    monkeypatch.setattr("services.job_engine.storage.get_supabase_client", lambda: None)
    with pytest.raises(RuntimeError): getattr(JobStorage(), operation)(*args, strict=True)


def test_transport_timeout_has_typed_failure_and_original_cause(monkeypatch):
    monkeypatch.setattr(ai, "OPENAI_API_KEY", "test-not-a-real-key")
    original = requests.Timeout("private request details")
    def fail(*args, **kwargs):
        assert kwargs["timeout"] == (5, 30)
        raise original
    monkeypatch.setattr(ai.requests, "post", fail)
    with pytest.raises(ai.OpenAIError) as caught: ai._request_openai_text("system", "data", timeout=30)
    assert caught.value.kind == "provider_timeout" and caught.value.__cause__ is original
    assert "private" not in str(caught.value)


def test_transport_does_not_disguise_programming_errors(monkeypatch):
    monkeypatch.setattr(ai, "OPENAI_API_KEY", "test-not-a-real-key")
    def fail(*args, **kwargs): raise TypeError("implementation defect")
    monkeypatch.setattr(ai.requests, "post", fail)
    with pytest.raises(TypeError): ai._request_openai_text("system", "data", timeout=30)


@pytest.mark.asyncio
async def test_committed_batch_draft_is_recovered_without_generation_or_overwrite(monkeypatch):
    item = BatchItem("job", "workspace", "", 0, {"id": "lead"}, "lead")
    completed = []
    class Storage:
        def list_batch_resume_items(self, *args, **kwargs): return [item]
        def list_batch_items(self, *args, **kwargs): return [item]
        def mark_batch_item_generating(self, *_args): return True
        def mark_batch_item_completed(self, job_id, key, draft_id):
            item.status = BatchItemStatus.COMPLETED; completed.append(draft_id); return True
    monkeypatch.setattr("services.job_engine.job_manager._storage", Storage())
    existing = SimpleNamespace(body="Original reviewed text", campaign_id=None, generation_metadata={"batch_id": "job"})
    async def read(_self, draft_id, workspace, *, strict):
        assert workspace == "workspace" and strict
        return existing
    monkeypatch.setattr("services.persistence.launch.DraftRepository.get_for_workspace", read)
    monkeypatch.setattr("services.knowledge.context_adapter.retrieve_knowledge_context", AsyncMock(return_value=KnowledgePromptContext()))
    provider = AsyncMock(side_effect=AssertionError("Do not regenerate a committed draft"))
    monkeypatch.setattr(drafts, "_run_draft_with_retry", provider)
    persist = AsyncMock(side_effect=AssertionError("Do not overwrite a committed draft"))
    monkeypatch.setattr("services.workspace.state.persist_draft_awaited", persist)
    result = await drafts.run_draft_batch_job(Job(id="job", user_id="actor", workspace_id="workspace"), lambda *_args: None)
    assert result["ok"] and completed and existing.body == "Original reviewed text"
    provider.assert_not_awaited(); persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_strict_draft_write_preserves_original_persistence_exception(monkeypatch):
    from services.workspace import state
    error = TypeError("unexpected persistence bug")
    monkeypatch.setattr(state, "_write_draft_row", AsyncMock(side_effect=error))
    with pytest.raises(TypeError) as caught:
        await state.persist_draft_awaited("actor", {}, workspace_id="workspace", strict=True)
    assert caught.value is error
