import { test, expect, ids, backendRequest, session } from "./isolated-discovery.fixture";

test.skip(process.env.LOQI_RUN_DISCOVERY_HTTP !== "1", "Requires reviewed, user-started isolated backend");

async function submit(page: import("@playwright/test").Page) {
  const policy = page.waitForResponse(response => response.url().includes("/api/v1/beta/features") && response.status() === 200);
  await page.goto(`/discovery?workspace_id=${ids.a}&fresh=1`);
  await expect(page.getByRole("heading", { name: "Who are you looking for?" })).toBeVisible();
  // Wait for the real backend policy response, not a fabricated feature flag.
  expect((await (await policy).json()).features.lead_search).toBe(true);
  await page.getByRole("textbox", { name: "Describe the leads you're looking for" }).fill("Find operations leaders at e-commerce companies");
  const started = page.waitForResponse(response => response.url().includes("/api/discoveries") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const response = await started;
  expect(response.status()).toBe(200);
  return (await response.json()).discovery_id as string;
}

test("real isolated Discovery worker renders persisted synonyms, filters and unique pages", async ({ page }) => {
  const identity = await submit(page);
  await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /^Select Synthetic Person / })).toHaveCount(50);
  await expect(page.getByRole("table").getByText("Head of Operations", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("table").getByText("Operations Manager", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("table").getByText("COO", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("table").getByText("Engineer", { exact: true })).toHaveCount(0);
  const names = () => page.getByRole("checkbox", { name: /^Select Synthetic Person / }).evaluateAll(nodes => nodes.map(node => node.getAttribute("aria-label")));
  const first = await names();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: /^Select Synthetic Person / })).toHaveCount(6);
  const second = await names();
  expect(new Set([...first, ...second]).size).toBe(56);
  // Apply an explicit filter through the actual UI; missing location must fail it.
  await page.getByRole("button", { name: /^Location\b/ }).click();
  await page.getByRole("textbox", { name: "Filter by Location", exact: true }).fill("London");
  await expect(page.getByRole("checkbox", { name: /^Select Synthetic Person / })).toHaveCount(50);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: /^Select Synthetic Person / })).toHaveCount(4);
  const persisted = await backendRequest("GET", `/api/discoveries/${identity}`, undefined, { authorization: `Bearer ${session}`, "x-workspace-id": ids.a });
  expect(JSON.parse(persisted.body).discovery.discovery_leads).toHaveLength(56);
  await page.reload();
  await expect(page.getByRole("checkbox", { name: /^Select Synthetic Person / })).toHaveCount(4);
  await page.goto(`/contacts?workspace_id=${ids.b}`);
  await expect(page.getByRole("checkbox", { name: /^Select Synthetic Person / })).toHaveCount(1);
  await expect(page.getByText("Synthetic Person 59", { exact: true }).first()).toBeVisible();
});

for (const mode of ["fail-staging", "truncate-staging"]) {
  test(`${mode} cannot render Research complete`, async ({ page }) => {
    await backendRequest("POST", "/__loqi_test/fault", JSON.stringify({ mode }), { authorization: `Bearer ${session}`, "content-type": "application/json" });
    const identity = await submit(page);
    await expect.poll(async () => {
      const response = await backendRequest("GET", `/api/discoveries/${identity}`, undefined, { authorization: `Bearer ${session}`, "x-workspace-id": ids.a });
      return JSON.parse(response.body).discovery.status;
    }).toBe("failed");
    await expect(page.getByText(mode === "fail-staging"
      ? /This search did not complete/
      : /Results may be incomplete/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toHaveCount(0);
  });
}
