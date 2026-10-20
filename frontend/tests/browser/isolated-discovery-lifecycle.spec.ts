import { test, expect, ids, backendRequest, session, type IsolatedCall } from "./isolated-discovery.fixture";
import type { Page } from "@playwright/test";

test.skip(process.env.LOQI_RUN_DISCOVERY_HTTP !== "1", "Requires approved synthetic backend");
const query = "Find operations leaders at e-commerce companies";
const starts = (calls: IsolatedCall[]) => calls.filter(call => call.method === "POST" && call.path === "/api/discoveries");

function gate() {
  let release!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; });
  return { wait, release };
}

async function ready(page: Page) {
  const policy = page.waitForResponse(response => response.url().includes("/api/v1/beta/features") && response.status() === 200);
  await page.goto(`/discovery?workspace_id=${ids.a}&fresh=1`);
  await expect(page.getByRole("heading", { name: "Who are you looking for?" })).toBeVisible();
  expect((await (await policy).json()).features.lead_search).toBe(true);
  await page.getByRole("textbox", { name: "Describe the leads you're looking for" }).fill(query);
}

test("rejected synthetic session on POST shows failure and allows explicit recovery", async ({ page, transport }) => {
  let rejected = true;
  transport.before = async call => call.method === "POST" && call.path === "/api/discoveries" && rejected
    ? { status: 401, body: JSON.stringify({ detail: "Invalid or expired session" }) } : undefined;
  await ready(page);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("Discovery search could not be started.", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toHaveCount(0);
  expect(starts(transport.calls)).toHaveLength(1);
  // Simulate restored authorization; recovery still needs an explicit click.
  rejected = false;
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
  expect(starts(transport.calls)).toHaveLength(2);
  await expect(page.getByRole("checkbox", { name: /^Select Synthetic Person / })).toHaveCount(50);
  console.log("Rejected POST recovery: 2 dispatched POSTs, first rejected locally, second accepted");
});

test("a rejected later results GET is recoverable without another Discovery POST", async ({ page, transport }) => {
  let rejected = true;
  transport.before = async call => call.method === "GET" && call.path === "/api/web/session/_/leads" && rejected
    ? { status: 401, body: JSON.stringify({ detail: "Invalid or expired session" }) } : undefined;
  await ready(page);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("Could not load search results. Please try again.", { exact: true })).toBeVisible();
  // The durable run may have completed; inability to read results is not job failure.
  await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
  const rejectedReads = transport.calls.filter(call => call.path === "/api/web/session/_/leads").length;
  expect(rejectedReads).toBeGreaterThan(0);
  rejected = false;
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: /^Select Synthetic Person / })).toHaveCount(50);
  await expect(page.getByText("Could not load search results. Please try again.", { exact: true })).toHaveCount(0);
  expect(starts(transport.calls)).toHaveLength(1);
  console.log("Later GET recovery: 1 Discovery POST; explicit results retry, no resubmission");
});

test("two rapid submit events produce exactly one accepted POST", async ({ page, transport }) => {
  const accepted = gate(), release = gate();
  transport.after = async (call, reply) => {
    if (call.method === "POST" && call.path === "/api/discoveries") {
      expect(reply.status).toBe(200);
      accepted.release();
      await release.wait;
    }
  };
  await ready(page);
  try {
    await page.getByRole("button", { name: "Search", exact: true }).evaluate(button => {
      const form = button.closest("form");
      if (!form) throw new Error("Search must be submitted through its form");
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await accepted.wait;
    expect(starts(transport.calls)).toHaveLength(1);
  } finally { release.release(); }
  await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /^Select Synthetic Person / })).toHaveCount(50);
  expect(starts(transport.calls)).toHaveLength(1);
  console.log("Double submission: 2 rapid form events, 1 accepted Discovery POST");
});

test("old query response delivered last cannot replace the newer query", async ({ page, transport }) => {
  const held = gate(), release = gate(), delivered = gate();
  let oldCall: IsolatedCall | undefined;
  transport.after = async (call, reply) => {
    if (!oldCall && call.path === "/api/web/session/_/leads" && call.workspace === ids.a
      && call.url.searchParams.get("discovery_id") && JSON.parse(reply.body).leads?.length > 0) {
      expect(reply.status).toBe(200);
      oldCall = call;
      held.release();
      await release.wait;
      delivered.release();
    }
  };
  await ready(page);
  try {
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await held.wait;
    // A different query uses the actual mounted form, not a navigation/reload.
    await page.getByRole("textbox", { name: "Describe the leads you're looking for" }).fill("CTO");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.getByText("No leads match this search.", { exact: true })).toBeVisible();
    await expect(page).toHaveURL(/q=CTO/);
    const current = transport.delivered.findIndex(call => call.path === "/api/web/session/_/leads" && call.url.searchParams.get("q") === "CTO");
    expect(current).toBeGreaterThanOrEqual(0);
    release.release();
    await delivered.wait;
    await expect.poll(() => transport.delivered.indexOf(oldCall!)).toBeGreaterThan(current);
    await expect(page.getByText("No leads match this search.", { exact: true })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: /^Select Synthetic Person / })).toHaveCount(0);
    await expect(page.getByRole("checkbox", { name: "Select Synthetic Person 1", exact: true })).toHaveCount(0);
    expect(starts(transport.calls)).toHaveLength(2);
    console.log(`Query race: 2 POSTs; current response index ${current}, old response index ${transport.delivered.indexOf(oldCall!)}`);
  } finally { release.release(); }
});

test("accepted search timeout is ambiguous and history recovery never resubmits", async ({ page, transport }) => {
  const accepted = gate(), release = gate();
  let identity = "";
  transport.after = async (call, reply) => {
    if (call.method === "POST" && call.path === "/api/discoveries") {
      expect(reply.status).toBe(200);
      identity = JSON.parse(reply.body).discovery_id;
      accepted.release();
      await release.wait;
    }
  };
  await ready(page);
  await page.clock.install();
  try {
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await accepted.wait;
    await page.clock.runFor(20_001);
    await expect(page.getByText("The search-start response timed out. The search may already be running; check Search history before starting another.", { exact: true })).toBeVisible();
    expect(starts(transport.calls)).toHaveLength(1);
    release.release();
    await expect.poll(async () => {
      const response = await backendRequest("GET", `/api/discoveries/${identity}`, undefined,
        { authorization: `Bearer ${session}`, "x-workspace-id": ids.a });
      return JSON.parse(response.body).discovery.status;
    }).toBe("completed");
    await page.getByRole("link", { name: /Search history/ }).click();
    await page.locator(`a[href*="provider_discovery=${identity}"]`).click();
    await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: /^Select Synthetic Person / })).toHaveCount(50);
    await page.reload();
    await expect(page.getByRole("heading", { name: "Research complete", exact: true })).toBeVisible();
    expect(starts(transport.calls)).toHaveLength(1);
    expect(transport.calls.some(call => call.method === "GET" && call.path === "/api/discoveries")).toBe(true);
    console.log("Ambiguous timeout: 1 accepted POST; history/detail/refresh recovery issued 0 extra POSTs");
  } finally { release.release(); }
});
