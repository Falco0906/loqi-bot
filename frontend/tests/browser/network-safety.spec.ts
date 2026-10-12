import { test, expect } from "@playwright/test";
import { isolate, MockApi } from "./fixtures";

test("unknown production/provider/database requests are aborted without network", async ({ context, page }) => {
  const api = new MockApi();
  await isolate(context, api);
  await page.goto("about:blank");
  for (const url of ["https://api.tryloqi.com/unmocked", "https://production.supabase.co/rest/v1/leads", "https://api.openai.com/v1/responses"]) {
    expect(await page.evaluate(async target => { try { await fetch(target); return "unexpected success"; } catch { return "blocked"; } }, url)).toBe("blocked");
  }
  expect(api.blocked).toHaveLength(3);
});

test("mocked API requests are fulfilled without contacting a backend", async ({ context, page }) => {
  const api = new MockApi();
  await isolate(context, api);
  await page.goto("about:blank");
  const result = await page.evaluate(async () => (await fetch("https://api.tryloqi.com/health")).json());
  expect(result).toEqual({ status: "ok" });
  expect(api.blocked).toEqual([]);
  expect(api.calls).toHaveLength(1);
});
