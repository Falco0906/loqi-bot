import assert from "node:assert";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const draftReview = await readFile(new URL("../components/draft/DraftReviewWorkspace.tsx", import.meta.url), "utf8");
const icon = await readFile(new URL("../components/shared/Icon.tsx", import.meta.url), "utf8");

test("Draft Review provides separate user-initiated subject and message copy actions", () => {
  assert.match(draftReview, /async function copyDraftText/);
  assert.match(draftReview, /aria-label="Copy subject"/);
  assert.match(draftReview, /aria-label="Copy message"/);
  assert.match(draftReview, /navigator\.clipboard\.writeText/);
  assert.match(draftReview, /event\.stopPropagation\(\)/);
  assert.match(icon, /content_copy:/);
});

test("Copy actions only report clipboard state and do not invoke delivery", () => {
  const copySection = draftReview.slice(draftReview.indexOf("async function copyDraftText"), draftReview.indexOf("async function saveEdit"));
  assert.doesNotMatch(copySection, /sendDraft|scheduleDraft|Gmail/);
  assert.match(copySection, /copied to clipboard/);
});
