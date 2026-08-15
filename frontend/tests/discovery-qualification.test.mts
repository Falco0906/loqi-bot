import assert from "node:assert";
import { test } from "node:test";
import { qualificationFromPersistedMetadata } from "../lib/discovery-qualification.ts";

test("Discovery mapping parses persisted JSON-string workspace metadata", () => {
  const qualification = qualificationFromPersistedMetadata(JSON.stringify({
    qualification: {
      prospect_evidence: [{ field: "title", value: "Sales Manager" }],
      structured_icp_match: {
        matched_roles: ["Sales Manager"],
        influenced_dimensions: ["relevance_score"],
      },
      knowledge_context: {
        knowledge_item_ids: [],
        knowledge_source_ids: [],
        guidance_only: true,
      },
      strategic_observations: {
        strategic_update_ids: ["update-1"],
        observations: [{
          id: "update-1",
          title: "Observed pattern",
          observation: "A real observed pattern.",
          observation_only: true,
        }],
        guidance_only: true,
      },
    },
  }));

  assert.ok(qualification);
  assert.deepStrictEqual(
    (qualification?.structured_icp_match as { matched_roles?: string[] })?.matched_roles,
    ["Sales Manager"],
  );
  assert.deepStrictEqual(
    (qualification?.strategic_observations as { strategic_update_ids?: string[] })?.strategic_update_ids,
    ["update-1"],
  );
  assert.strictEqual(
    (qualification?.prospect_evidence as Array<{ value: string }>)?.[0].value,
    "Sales Manager",
  );
});
