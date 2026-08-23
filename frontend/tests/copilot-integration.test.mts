import assert from "node:assert";
import { test } from "node:test";
import {
  extractCopilotCapabilityResult,
  leadIdsFromResult,
  mergeCopilotResourceContext,
  resultMatchesResource,
} from "../lib/copilot-integration.ts";

test("persisted resource context is flattened for backend page context", () => {
  const context = mergeCopilotResourceContext(
    { page: "Draft Review", draft_id: "page-draft" },
    { campaignId: "campaign-1", draftId: "saved-draft", conversationId: "conversation-1", selectedLeadIds: ["lead-1"] },
  );
  assert.equal(context.draft_id, "page-draft", "current page selection wins");
  assert.equal(context.campaign_id, "campaign-1");
  assert.equal(context.conversation_id, "conversation-1");
  assert.deepEqual(context.selected_lead_ids, ["lead-1"]);
});

test("an empty page selection does not erase ranked resource selection", () => {
  const context = mergeCopilotResourceContext(
    { selected_lead_ids: [] },
    { selectedLeadIds: ["lead-1", "lead-2", "lead-3", "lead-4", "lead-5"] },
  );
  assert.deepEqual(context.selected_lead_ids, ["lead-1", "lead-2", "lead-3", "lead-4", "lead-5"]);
});

test("capability results are accepted only from registered tool namespaces", () => {
  const result = { drafts: [{ id: "draft-1" }] };
  assert.deepEqual(extractCopilotCapabilityResult("outreach.draft.refine", result), result);
  assert.deepEqual(extractCopilotCapabilityResult("inbox.reply.generate", { generation: {} }), { generation: {} });
  assert.deepEqual(extractCopilotCapabilityResult("knowledge.search", { items: [] }), { items: [] });
  assert.deepEqual(extractCopilotCapabilityResult("analytics.workspace.summary", { metrics: {} }), { metrics: {} });
  assert.equal(extractCopilotCapabilityResult("conversation.text", result), undefined);
  assert.equal(extractCopilotCapabilityResult("lead.rank", result) !== undefined, true);
});

test("page synchronization only accepts results for the selected resource", () => {
  assert.equal(resultMatchesResource({ conversation_id: "conversation-1" }, "conversation-1", ["conversation_id"]), true);
  assert.equal(resultMatchesResource({ campaign_id: "campaign-2" }, "campaign-1", ["campaign_id"]), false);
  assert.equal(resultMatchesResource({ campaign_id: "" }, "campaign-1", ["campaign_id"]), false);
});

test("ranked lead results become the selected IDs for the next Copilot turn", () => {
  assert.deepEqual(
    leadIdsFromResult({ leads: [{ id: "lead-5" }, { id: "lead-2" }, { id: "" }] }),
    ["lead-5", "lead-2"],
  );
});
