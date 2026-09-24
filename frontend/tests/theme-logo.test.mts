import assert from "node:assert";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const sidebar = await readFile(new URL("../components/layout/Sidebar.tsx", import.meta.url), "utf8");
const copilot = await readFile(new URL("../components/copilot/CopilotPanel.tsx", import.meta.url), "utf8");
const manifest = await readFile(new URL("../public/site.webmanifest", import.meta.url), "utf8");

test("light mode selects the supplied black Loqi mark", () => {
  const expected = 'theme === "light" ? "/android-chrome-light-512x512.png" : "/android-chrome-512x512.png"';
  assert.ok(sidebar.includes(expected));
  assert.ok(copilot.includes(expected));
});

test("light-surface PWA metadata uses the supplied light icon assets", () => {
  assert.match(manifest, /android-chrome-light-192x192\.png/);
  assert.match(manifest, /android-chrome-light-512x512\.png/);
});
