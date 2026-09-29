import assert from "node:assert";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const copilotContext = await readFile(new URL("../contexts/CopilotContext.tsx", import.meta.url), "utf8");
const dashboardLayout = await readFile(new URL("../app/(dashboard)/layout.tsx", import.meta.url), "utf8");
const topbar = await readFile(new URL("../components/layout/Topbar.tsx", import.meta.url), "utf8");

test("Copilot is opt-in and Discover keeps the shared sidebar layout", () => {
  assert.match(copilotContext, /const \[open, setOpen\] = useState\(false\)/);
  assert.match(dashboardLayout, /isDiscoveryPage = pathname === "\/discovery"/);
  assert.match(dashboardLayout, /--copilot-w.*copilotOpen.*COPILOT_PANEL_WIDTH/s);
  assert.match(dashboardLayout, /<CopilotPanel width=\{COPILOT_PANEL_WIDTH\} \/>/);
  assert.match(topbar, /onClick=\{\(\) => setOpen\(!open\)\}/);
});
