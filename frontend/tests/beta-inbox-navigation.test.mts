import assert from "node:assert";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const sidebar = await readFile(new URL("../components/layout/Sidebar.tsx", import.meta.url), "utf8");

test("Inbox remains visible in Beta as a read-only navigation surface", () => {
  assert.match(sidebar, /\{ label: "Inbox", href: "\/inbox", icon: "inbox" \}/);
  assert.doesNotMatch(sidebar, /item\.href !== "\/inbox" \|\| outboundDeliveryEnabled/);
});
