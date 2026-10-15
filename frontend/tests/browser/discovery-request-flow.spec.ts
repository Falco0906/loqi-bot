import { test, expect, ids } from "./fixtures";

const discovery = `/discovery?workspace_id=${ids.a}&fresh=1`;
const query = "Find heads of sales at growing startups";

test("Search submits a scoped Discovery POST and renders its completed results", async ({ page, api }) => {
  await page.goto(discovery);
  await expect(page.getByRole("heading", { name: "Who are you looking for?" })).toBeVisible();
  await expect.poll(() => api.calls.filter(call => call.path === "/api/v1/beta/features").length).toBeGreaterThan(0);
  await page.getByRole("textbox", { name: "Describe the leads you're looking for" }).fill(query);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Select Ada Person 1", exact: true })).toBeVisible();
  const starts = api.calls.filter(call => call.path === "/api/discoveries" && call.method === "POST");
  expect(starts).toHaveLength(1);
  expect(starts[0].workspace).toBe(ids.a);
  expect(starts[0].body.initiation).toBe("manual");
  expect(starts[0].body.query).toContain("heads of sales");
  const reads = api.calls.filter(call => call.path === "/api/web/session/_/leads");
  expect(reads.length).toBeGreaterThan(0);
  expect(reads.every(call => call.method === "GET" && call.workspace === ids.a)).toBe(true);
  expect(reads.some(call => call.url.searchParams.get("discovery_id") === ids.run)).toBe(true);
});

test("unavailable capability policy never silently sends the search sentence to the lead-list GET", async ({ page, api }) => {
  let failPolicy = true;
  api.override = async call => call.path === "/api/v1/beta/features" && failPolicy
    ? { status: 503, json: { detail: "Fixture policy unavailable" } }
    : undefined;
  await page.goto(discovery);
  await expect(page.getByRole("heading", { name: "Who are you looking for?" })).toBeVisible();
  await page.getByRole("textbox", { name: "Describe the leads you're looking for" }).fill(query);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("Search capabilities could not be confirmed. Reload the page and try again.", { exact: true })).toBeVisible();
  expect(api.calls.filter(call => call.path === "/api/discoveries" && call.method === "POST")).toHaveLength(0);
  expect(api.calls.filter(call => call.path === "/api/web/session/_/leads")).toHaveLength(0);
  failPolicy = false;
  await page.reload();
  await expect(page.getByRole("heading", { name: "Who are you looking for?" })).toBeVisible();
  await page.getByRole("textbox", { name: "Describe the leads you're looking for" }).fill(query);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
  expect(api.calls.filter(call => call.path === "/api/discoveries" && call.method === "POST")).toHaveLength(1);
});

test("Lead Database and Discovery result reads use the same workspace-scoped lead endpoint", async ({ page, api }) => {
  await page.goto(`/contacts?workspace_id=${ids.a}`);
  await expect(page.getByRole("cell", { name: "Ada Person 1", exact: true })).toBeVisible();
  const databaseRead = api.calls.find(call => call.path === "/api/web/session/_/leads");
  expect(databaseRead?.workspace).toBe(ids.a);
  expect(databaseRead?.url.searchParams.get("q")).toBe("");
  await page.goto(discovery);
  await page.getByRole("textbox", { name: "Describe the leads you're looking for" }).fill(query);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
  const discoveryRead = api.calls.find(call => call.path === databaseRead?.path && call.url.searchParams.get("discovery_id") === ids.run);
  expect(discoveryRead?.workspace).toBe(databaseRead?.workspace);
  expect(discoveryRead?.method).toBe(databaseRead?.method);
});
