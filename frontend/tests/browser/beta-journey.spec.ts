import { test, expect, ids, lead } from "./fixtures";

const discovery = `/discovery?workspace_id=${ids.a}&fresh=1`;
const searchInput = "Describe the leads you're looking for";

test("CSV confirmation refreshes the mounted canonical lead table", async ({ page, api }) => {
  api.rows = []; api.count = 0;
  await page.goto(`/contacts?workspace_id=${ids.a}`);
  await expect(page.getByText("No leads yet.", { exact: true })).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles({ name: "leads.csv", mimeType: "text/csv", buffer: Buffer.from("first_name,last_name,email,company,title\nAda,Person 1,person1@example.invalid,Acme,Founder\n") });
  await expect(page.getByText("1 detected · 1 ready · 0 invalid")).toBeVisible();
  expect(api.calls.filter(call => call.path.endsWith("csv-import"))).toHaveLength(0);
  await page.getByRole("button", { name: "Confirm import 1 leads", exact: true }).click();
  await expect(page.getByText(/1 imported · 0 duplicates skipped · 0 invalid/)).toBeVisible();
  await expect(page.getByRole("cell", { name: "Ada Person 1", exact: true })).toBeVisible();
  expect(api.calls.filter(call => call.path.endsWith("csv-import"))).toHaveLength(1);
  expect(api.calls.filter(call => call.path.includes("/leads")).every(call => call.workspace === ids.a)).toBe(true);
});

test("explicit search, pagination selection, filter reset and history navigation", async ({ page, api }) => {
  api.rows = Array.from({ length: 51 }, (_, index) => lead(index + 1)); api.count = 51;
  await page.goto(discovery);
  await expect(page.getByRole("heading", { name: "Who are you looking for?" })).toBeVisible();
  expect(api.calls.filter(call => call.path === "/api/discoveries" && call.method === "POST")).toHaveLength(0);
  await page.getByRole("textbox", { name: searchInput }).fill("SaaS founders");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "Select Ada Person 1", exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: "Select Ada Person 1", exact: true }).check();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "Select Ada Person 51", exact: true })).toBeVisible();
  await expect(page.getByText("1 selected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "Select Ada Person 1", exact: true })).toBeChecked();
  await page.getByRole("button", { name: /Industry expand_more/ }).click();
  await page.getByRole("textbox", { name: "Filter by Industry" }).fill("SaaS");
  await expect(page.getByText("1 selected", { exact: true })).toHaveCount(0);
  await expect(page).toHaveURL(/industry=SaaS/);
  await page.reload();
  await expect(page.getByRole("textbox", { name: searchInput })).toHaveValue("SaaS founders");
  const activeSearchUrl = page.url();
  await page.getByRole("link", { name: /Search history/i }).click();
  await expect(page).toHaveURL(/discovery\/history/);
  await page.goBack();
  await expect(page).toHaveURL(activeSearchUrl);
  await expect(page.getByRole("textbox", { name: searchInput })).toHaveValue("SaaS founders");
  await page.goForward();
  await expect(page).toHaveURL(/discovery\/history/);
});

test("selected canonical leads generate explicitly; refresh recovers only by GET and copy works", async ({ page, api, context }) => {
  await context.addInitScript(() => {
    let copied = "";
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: {
      writeText: async (value: string) => { copied = value; (window as any).__loqiCopied = copied; },
      readText: async () => copied,
    } });
  });
  await page.goto(`/discovery?workspace_id=${ids.a}&q=SaaS`);
  await page.getByRole("checkbox", { name: "Select Ada Person 1", exact: true }).check();
  await page.getByRole("button", { name: "Analyze with Loqi", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`lead_ids=${lead(1).id}`));
  expect(api.calls.filter(call => call.path.endsWith("/analyze") || call.path.endsWith("generate-strategy"))).toHaveLength(0);
  await page.getByRole("button", { name: "Analyze with Loqi", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Facts", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Generate strategy & draft", exact: true }).click();
  await expect(page.getByText("AI-generated strategy and outreach draft", { exact: true })).toBeVisible();
  const generations = () => api.calls.filter(call => call.path.endsWith("generate-strategy"));
  expect(generations()).toHaveLength(1);
  expect(generations()[0].body.lead_ids).toEqual([lead(1).id]);
  await page.reload();
  await expect(page.getByText("AI-generated strategy and outreach draft", { exact: true })).toBeVisible();
  expect(generations()).toHaveLength(1);
  await page.getByRole("button", { name: "Copy draft", exact: true }).click();
  await expect(page.getByText("Draft copied to clipboard.")).toBeVisible();
  expect(await page.evaluate(() => (window as any).__loqiCopied)).toContain("Subject: A question");
  expect(api.calls.some(call => /send|schedule|launch|follow-up/.test(call.path))).toBe(false);
});

test("campaign creation and attachment preserve workspace; review edits and clears fields", async ({ page, api }) => {
  await page.goto(`/discovery?workspace_id=${ids.a}&q=SaaS`);
  await page.getByRole("checkbox", { name: "Select Ada Person 1", exact: true }).check();
  await page.getByRole("button", { name: "Add to existing campaign", exact: true }).click();
  await page.getByRole("combobox", { name: "Destination campaign" }).selectOption(ids.campaign);
  await page.getByRole("button", { name: "Attach selected leads", exact: true }).click();
  await expect(page.getByRole("link", { name: "View campaign", exact: true })).toBeVisible();
  expect(api.calls.find(call => call.path.endsWith(`/${ids.campaign}/leads`))?.body.lead.workspace_lead_id).toBe(lead(1).id);
  await page.getByRole("checkbox", { name: "Select Ada Person 2", exact: true }).check();
  await page.getByRole("button", { name: "Create campaign with selected leads", exact: true }).click();
  await expect(page).toHaveURL(url => url.pathname === "/campaigns/new"
    && url.searchParams.get("workspace_id") === ids.a
    && url.searchParams.get("lead_ids") === lead(2).id);
  await page.getByRole("textbox", { name: "Campaign name", exact: true }).fill("Selected prospects");
  await page.getByRole("textbox", { name: "Campaign description", exact: true }).fill("Introduce our product to selected SaaS prospects.");
  await page.getByRole("button", { name: "Create campaign", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`campaigns/${ids.campaign}\\?workspace_id=${ids.a}`));
  const creation = api.calls.find(call => call.path.endsWith("/campaigns") && call.body?.name === "Selected prospects");
  expect(creation?.body.objective).toBe("Introduce our product to selected SaaS prospects.");
  expect(creation?.body.leads).toEqual([{ id: lead(2).id, workspace_lead_id: lead(2).id }]);
  await expect(page.getByRole("heading", { name: "Selected prospects", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Open Draft Workspace →", exact: true }).click();
  await expect(page).toHaveURL(/\/draft\?/);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByPlaceholder("Email subject line...").fill("Changed subject");
  await page.locator("textarea").filter({ visible: true }).first().fill("Changed message");
  await page.getByRole("button", { name: "Save Changes", exact: true }).click();
  await expect(page.getByText("Changed message", { exact: true }).last()).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByPlaceholder("Email subject line...").fill("");
  await page.locator("textarea").filter({ visible: true }).first().fill("");
  await page.getByRole("button", { name: "Save Changes", exact: true }).click();
  await expect.poll(() => api.draft.subject).toBe("");
  expect(api.draft.text).toBe("");
  expect(api.draft.status).toBe("pending");
  expect(api.calls.filter(call => call.path.endsWith(`/drafts/${ids.draft}`)).every(call => call.workspace === ids.a)).toBe(true);
  expect(api.calls.some(call => /generate-strategy|send|schedule|launch/.test(call.path))).toBe(false);
  await expect(page.getByRole("button", { name: "Send Now", exact: true })).toHaveCount(0);
});

test("workspace changes remove stale records and inaccessible scopes are recoverable", async ({ page }) => {
  await page.goto(`/contacts?workspace_id=${ids.a}`);
  await expect(page.getByRole("cell", { name: "Ada Person 1", exact: true })).toBeVisible();
  await page.goto(`/contacts?workspace_id=${ids.b}`);
  await expect(page.getByRole("cell", { name: "Beta Person 101", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Ada Person 1", exact: true })).toHaveCount(0);
  await page.goto("/contacts?workspace_id=inaccessible");
  await expect(page.locator('main[role="alert"]')).toContainText("Choose an accessible workspace");
});

test("workspace picker shows the authorized selection and switches scoped page state", async ({ page, api }) => {
  await page.goto(`/contacts?workspace_id=${ids.a}`);
  await expect(page.getByRole("button", { name: "Workspace: Alpha Workspace" })).toBeVisible();
  await page.getByRole("button", { name: "Workspace: Alpha Workspace" }).click();
  await expect(page.getByRole("menuitemradio", { name: "Alpha Workspace" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("menuitemradio", { name: "Beta Workspace" }).click();
  await expect(page).toHaveURL(new RegExp(`/contacts\\?workspace_id=${ids.b}`));
  await expect(page.getByRole("button", { name: "Workspace: Beta Workspace" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Beta Person 101", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Ada Person 1", exact: true })).toHaveCount(0);
  const validation = api.calls.find(call => call.path.endsWith("/workspaces/select"));
  expect(validation?.method).toBe("POST");
  expect(validation?.workspace).toBe(ids.b);
  expect(api.calls.filter(call => call.path.endsWith("/leads")).every(call => call.workspace === ids.a || call.workspace === ids.b)).toBe(true);
  api.override = async call => call.path.endsWith("/workspaces/select") && call.workspace === ids.a
    ? { status: 404, json: { detail: "Workspace not found" } }
    : undefined;
  await page.getByRole("button", { name: "Workspace: Beta Workspace" }).click();
  await page.getByRole("menuitemradio", { name: "Alpha Workspace" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "That workspace is no longer accessible" })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/contacts\\?workspace_id=${ids.b}`));
});

test("campaign list and campaign navigation stay scoped to the selected workspace", async ({ page, api }) => {
  await page.goto(`/campaigns?workspace_id=${ids.a}`);
  await expect(page.getByRole("heading", { name: "Review campaign", exact: true })).toBeVisible();
  expect(api.calls.find(call => call.path.endsWith("/campaigns") && call.method === "GET")?.workspace).toBe(ids.a);
  await page.getByRole("link", { name: "Create Campaign", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/campaigns/new\\?workspace_id=${ids.a}`));
  await page.goto(`/campaigns?workspace_id=${ids.a}`);
  await page.getByRole("button", { name: "Workspace: Alpha Workspace" }).click();
  await page.getByRole("menuitemradio", { name: "Beta Workspace" }).click();
  await expect(page).toHaveURL(new RegExp(`/campaigns\\?workspace_id=${ids.b}`));
  await expect(page.getByRole("heading", { name: "Review campaign", exact: true })).toHaveCount(0);
  const campaignReads = api.calls.filter(call => call.path.endsWith("/campaigns") && call.method === "GET");
  expect(campaignReads.at(-1)?.workspace).toBe(ids.b);
});

test("workspace listing failure and inaccessible scope remain recoverable", async ({ page, api }) => {
  api.workspaceListFailure = true;
  await page.goto(`/contacts?workspace_id=inaccessible`);
  await expect(page.getByRole("button", { name: "Workspace: Workspace unavailable" })).toBeVisible();
  await page.getByRole("button", { name: "Workspace: Workspace unavailable" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Your workspace could not be loaded" })).toBeVisible();
  api.workspaceListFailure = false;
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.getByRole("menuitemradio", { name: "Alpha Workspace" })).toBeVisible();
  await page.getByRole("menuitemradio", { name: "Alpha Workspace" }).click();
  await expect(page).toHaveURL(new RegExp(`/contacts\\?workspace_id=${ids.a}`));
  await expect(page.getByRole("cell", { name: "Ada Person 1", exact: true })).toBeVisible();
  api.workspaceListEmpty = true;
  await page.goto("/contacts");
  await page.getByRole("button", { name: "Workspace: Choose workspace" }).click();
  await expect(page.getByText("No accessible workspaces are available for this account.", { exact: true })).toBeVisible();
});

test("late workspace validation cannot switch a newer navigation back to its old scope", async ({ page, api }) => {
  let release!: () => void;
  let arrived!: () => void;
  let validationCompleted = false;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const started = new Promise<void>(resolve => { arrived = resolve; });
  api.override = async call => {
    if (call.path.endsWith("/workspaces/select") && call.workspace === ids.b) {
      arrived();
      await pending;
      validationCompleted = true;
      return { json: { ok: true, workspace: { id: ids.b, name: "Beta Workspace" } } };
    }
  };
  await page.goto(`/contacts?workspace_id=${ids.a}`);
  await page.getByRole("button", { name: "Workspace: Alpha Workspace" }).click();
  await page.getByRole("menuitemradio", { name: "Beta Workspace" }).click();
  await started;
  await page.getByRole("link", { name: "Discover", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/discovery\\?workspace_id=${ids.a}`));
  release();
  await expect.poll(() => validationCompleted).toBe(true);
  await expect(page).toHaveURL(new RegExp(`/discovery\\?workspace_id=${ids.a}`));
});

test("out-of-order result reads cannot replace the active search", async ({ page, api }) => {
  let release!: () => void;
  let arrived!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const started = new Promise<void>(resolve => { arrived = resolve; });
  api.override = async call => {
    if (call.path.endsWith("/leads") && call.url.searchParams.get("q") === "Old") {
      arrived(); await pending;
      return { json: { ok: true, leads: [{ ...lead(1), first_name: "Obsolete" }], total: 1, page: 1, page_size: 50 } };
    }
  };
  await page.goto(`/discovery?workspace_id=${ids.a}&q=Old`);
  await started;
  await page.getByRole("textbox", { name: searchInput }).fill("New");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "Select Ada Person 1", exact: true })).toBeVisible();
  release();
  await expect(page.getByRole("checkbox", { name: /Obsolete/ })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: searchInput })).toHaveValue("New");
});

test("failed listing can recover without becoming a fake empty result", async ({ page, api }) => {
  api.listFailure = true;
  await page.goto(`/discovery?workspace_id=${ids.a}&q=SaaS`);
  await expect(page.getByText("Could not load search results. Please try again.", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("No leads match this search.", { exact: true })).toHaveCount(0);
  api.listFailure = false;
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "Select Ada Person 1", exact: true })).toBeVisible();
});
