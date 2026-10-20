import { test, expect, workspace, workspaceB } from "./large-discovery-ui.fixture";
import type { Page } from "@playwright/test";
import type { LargeUI } from "./large-discovery-ui.fixture";

test.skip(process.env.LOQI_RUN_DISCOVERY_HTTP !== "1", "Requires separately approved large-profile backend and frontend");
test.setTimeout(90_000);
const query = "operations leaders at ecommerce companies";
const canonical = (index: number) => `70000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
const ordered = (count: number) => Array.from({ length: count }, (_, i) => i + 1)
  .sort((a, b) => `person ${a}` < `person ${b}` ? -1 : 1);
const visible = (page: Page) => page.getByRole("checkbox", { name: /^Select Synthetic Person / });
const names = (page: Page) => visible(page).evaluateAll(nodes => nodes.map(node => node.getAttribute("aria-label")));
const labels = (indices: number[]) => indices.map(i => `Select Synthetic Person ${i}`);

async function open(page: Page) {
  const policy = page.waitForResponse(r => r.url().endsWith("/api/v1/beta/features") && r.status() === 200);
  await page.goto(`/discovery?workspace_id=${workspace}&fresh=1`);
  await expect(page.getByRole("heading", { name: "Who are you looking for?" })).toBeVisible();
  expect((await (await policy).json()).features.lead_search).toBe(true);
}

async function submit(page: Page, value = query) {
  const input = page.getByRole("textbox", { name: "Describe the leads you're looking for" });
  const search = page.getByRole("button", { name: "Search", exact: true });
  await input.fill(value);
  await expect(input).toHaveValue(value);
  await expect(search).toBeEnabled();
  const reply = page.waitForResponse(r => new URL(r.url()).pathname === "/api/discoveries" && r.request().method() === "POST");
  await search.click();
  const response = await reply;
  expect(response.status()).toBe(200);
  return (await response.json()).discovery_id as string;
}

async function pages(page: Page, count: number, id: string, largeUI: LargeUI, sinceRequest = 0) {
  const expected = ordered(count), actual: number[] = [], sizes: number[] = [];
  for (let offset = 0; offset < count; offset += 50) {
    const slice = expected.slice(offset, offset + 50);
    await expect.poll(() => names(page)).toEqual(labels(slice));
    // Compare actual native response IDs as well as rendered row identities.
    // Names alone would not prove the canonical IDs returned by the server.
    const read = () => largeUI.reads.find(row => row.requestIndex >= sinceRequest
      && row.workspace === workspace && row.status === 200 && row.url.searchParams.get("discovery_id") === id
      && Number(row.url.searchParams.get("page") || "1") === offset / 50 + 1
      && row.body.total === count);
    await expect.poll(() => read()?.body.leads.map(row => row.id)).toEqual(slice.map(canonical));
    actual.push(...(await names(page)).map(name => Number(name!.replace("Select Synthetic Person ", ""))));
    sizes.push(slice.length);
    if (offset + 50 < count) await page.getByRole("button", { name: "Next", exact: true }).click();
  }
  expect(actual.map(canonical)).toEqual(expected.map(canonical));
  expect(new Set(actual).size).toBe(count);
  await expect(page.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  return sizes;
}

async function freshResults(largeUI: LargeUI, sinceRequest: number, id: string, pageNumber: number, count: number) {
  const expected = ordered(count).slice((pageNumber - 1) * 50, pageNumber * 50).map(canonical);
  await expect.poll(() => largeUI.reads.find(row => row.requestIndex >= sinceRequest
    && row.workspace === workspace && row.status === 200
    && row.url.searchParams.get("discovery_id") === id
    && Number(row.url.searchParams.get("page") || "1") === pageNumber
    && row.body.total === count)?.body.leads.map(row => row.id)).toEqual(expected);
}

function assertWorkspaceReads(largeUI: LargeUI) {
  const allowed = new Map([
    [workspace, new Set(Array.from({ length: 604 }, (_, i) => canonical(i + 1)))],
    [workspaceB, new Set([canonical(605), canonical(606)])],
  ]);
  for (const read of largeUI.reads) {
    expect(allowed.has(read.workspace), "Every lead response must have an approved workspace header").toBe(true);
    for (const lead of read.body.leads) expect(allowed.get(read.workspace)!.has(lead.id), "No cross-workspace API rows").toBe(true);
  }
}

for (const scenario of [
  { name: "broad", count: 602 },
  { name: "London", count: 600, filter: "Location", value: "London" },
  { name: "ecommerce", count: 601, filter: "Industry", value: "ecommerce" },
]) {
  test(`actual UI native large search: ${scenario.name}`, async ({ page, largeUI }) => {
    await open(page);
    if (scenario.filter) {
      await page.getByRole("button", { name: new RegExp(`^${scenario.filter}\\b`) }).click();
      const filter = page.getByRole("textbox", { name: `Filter by ${scenario.filter}`, exact: true });
      await filter.fill(scenario.value!);
      await expect(page).toHaveURL(url => url.pathname === "/discovery"
        && url.searchParams.get("workspace_id") === workspace
        && url.searchParams.get(scenario.filter!.toLowerCase()) === scenario.value);
      await expect(filter).toHaveValue(scenario.value!);
    }
    const id = await submit(page);
    await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
    const firstResultURL = page.url();
    const sizes = await pages(page, scenario.count, id, largeUI);
    expect(sizes).toEqual([...Array(12).fill(50), ...(scenario.count % 50 ? [scenario.count % 50] : [])]);
    const persisted = (await largeUI.call(`/api/discoveries/${id}`)).discovery;
    // Filters are submitted through the UI and constrain the persisted run too.
    expect(persisted.status).toBe("completed");
    expect(new Set(persisted.discovery_leads.map((row: { lead_id: string }) => row.lead_id)))
      .toEqual(new Set(Array.from({ length: scenario.count }, (_, i) => canonical(i + 1))));
    expect(persisted.discovery_leads).toHaveLength(scenario.count);
    const outcomes = persisted.summary.candidate_outcomes;
    expect(outcomes.matched_count).toBe(scenario.count);
    expect(outcomes.retrieved_count).toBe(scenario.count + Object.values(outcomes.exclusions).reduce<number>((sum, n) => sum + Number(n), 0));
    expect(persisted.summary.candidate_outcomes.retrieved_count).toBe(604);
    const posts = () => largeUI.requests.filter(r => r.method === "POST" && r.path === "/api/discoveries").length;
    expect(posts()).toBe(1);
    const originalPosts = posts();
    const beforeReload = largeUI.requests.length;
    await page.reload();
    await freshResults(largeUI, beforeReload, id, sizes.length, scenario.count);
    await expect.poll(() => names(page)).toEqual(labels(ordered(scenario.count).slice(-sizes.at(-1)!)));
    expect(new URL(page.url()).searchParams.get("provider_discovery")).toBe(id);
    expect(posts()).toBe(originalPosts);
    if (scenario.name === "broad") {
      // Reopen the original page-one URL as a normal document navigation, then
      // traverse all 13 UI pages again. Pre-reload responses cannot satisfy it.
      const beforeReopen = largeUI.requests.length;
      await page.goto(firstResultURL);
      await freshResults(largeUI, beforeReopen, id, 1, 602);
      expect(await pages(page, 602, id, largeUI, beforeReopen)).toEqual([...Array(12).fill(50), 2]);
      expect(posts()).toBe(originalPosts);
      const beforeB = largeUI.requests.length;
      await page.getByRole("button", { name: "Workspace: Alpha Synthetic", exact: true }).click();
      await page.getByRole("menuitemradio", { name: /Beta Synthetic/ }).click();
      await expect.poll(() => new URL(page.url()).searchParams.get("workspace_id")).toBe(workspaceB);
      await expect(visible(page)).toHaveCount(0);
      await page.getByRole("link", { name: "Lead Database", exact: true }).click();
      await expect.poll(() => names(page)).toEqual(labels([605, 606]));
      await expect.poll(() => largeUI.reads.find(row => row.requestIndex >= beforeB
        && row.workspace === workspaceB && row.status === 200 && row.body.total === 2)
        ?.body.leads.map(row => row.id)).toEqual([canonical(605), canonical(606)]);
      expect(posts()).toBe(originalPosts);

      // Switch back from blank Discovery, not Contacts (which lists all saved
      // leads). Switching intentionally clears the search; history restores it.
      await page.getByRole("link", { name: "Discover", exact: true }).click();
      await page.getByRole("button", { name: "Workspace: Beta Synthetic", exact: true }).click();
      await page.getByRole("menuitemradio", { name: /Alpha Synthetic/ }).click();
      await expect.poll(() => new URL(page.url()).searchParams.get("workspace_id")).toBe(workspace);
      await expect(visible(page)).toHaveCount(0);
      const history = page.getByRole("link", { name: "Search history history", exact: true });
      await expect(history).toHaveAttribute("href", `/discovery/history?workspace_id=${workspace}`);
      await history.click();
      const runLink = page.locator(`a[href*="provider_discovery=${id}"]`);
      await expect(runLink).toHaveCount(1);
      const beforeReturn = largeUI.requests.length;
      await runLink.click();
      await expect.poll(() => new URL(page.url()).searchParams.get("provider_discovery")).toBe(id);
      await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
      await freshResults(largeUI, beforeReturn, id, 1, 602);
      expect(await pages(page, 602, id, largeUI, beforeReturn)).toEqual([...Array(12).fill(50), 2]);
      expect(posts()).toBe(originalPosts);
      await largeUI.flushReads();
      assertWorkspaceReads(largeUI);
    }
  });
}

test("actual UI native large search: completed zero is not failure", async ({ page, largeUI }) => {
  await open(page);
  const id = await submit(page, "CTO");
  await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
  await expect(page.getByText("No leads match this search.", { exact: true })).toBeVisible();
  await expect(visible(page)).toHaveCount(0);
  const run = (await largeUI.call(`/api/discoveries/${id}`)).discovery;
  expect(run.status).toBe("completed");
  expect(run.summary.lead_count).toBe(0);
  expect(run.discovery_leads).toEqual([]);
  expect(run.summary.candidate_outcomes.retrieved_count).toBe(604);
});

for (const mode of ["fail-staging", "truncate-staging"]) {
  test(`actual UI native large search: ${mode} is not success`, async ({ page, largeUI }) => {
    await open(page);
    await largeUI.call("/__loqi_test/fault", { mode });
    const id = await submit(page);
    await expect.poll(async () => (await largeUI.call(`/api/discoveries/${id}`)).discovery.status).toBe("failed");
    await expect(page.getByText(mode === "fail-staging" ? /This search did not complete/ : /Results may be incomplete/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toHaveCount(0);
  });
}
