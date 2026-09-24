import assert from "node:assert";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const sidebar = await readFile(new URL("../components/layout/Sidebar.tsx", import.meta.url), "utf8");
const copilot = await readFile(new URL("../components/copilot/CopilotPanel.tsx", import.meta.url), "utf8");
const themeHook = await readFile(new URL("../hooks/useTheme.ts", import.meta.url), "utf8");

test("light mode selects the supplied black Loqi mark", () => {
  const expected = 'theme === "light" ? "/android-chrome-light-512x512.png" : "/android-chrome-512x512.png"';
  assert.ok(sidebar.includes(expected));
  assert.ok(copilot.includes(expected));
});

test("all mounted theme consumers update when the preference changes", () => {
  assert.match(themeHook, /THEME_CHANGE_EVENT/);
  assert.match(themeHook, /window\.addEventListener\(THEME_CHANGE_EVENT, syncTheme\)/);
  assert.match(themeHook, /window\.dispatchEvent\(new Event\(THEME_CHANGE_EVENT\)\)/);
});
