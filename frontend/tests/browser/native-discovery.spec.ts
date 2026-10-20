import { test, expect, frontend, backend, workspace, session } from "./native-discovery.fixture";

test("native preflight, Discovery POST and paginated GETs return real synthetic results", async ({ native }) => {
  const query = "operations leaders at ecommerce companies";
  const start = await native.call("/api/discoveries", { method: "POST", body: { query, initiation: "manual" } });
  expect(start.status).toBe(200);
  const identity = start.body.discovery_id;
  let run: any;
  await expect.poll(async () => {
    const response = await native.call(`/api/discoveries/${identity}`);
    expect(response.status).toBe(200);
    run = response.body.discovery;
    return run.status;
  }).toBe("completed");
  expect(run.summary.lead_count).toBe(56);
  expect(run.discovery_leads).toHaveLength(56);
  const counts = run.summary.candidate_outcomes;
  expect(counts.retrieved_count).toBe(58);
  expect(counts.matched_count).toBe(56);
  expect(counts.retrieved_count).toBe(counts.matched_count + Object.values(counts.exclusions).reduce<number>((sum, value) => sum + Number(value), 0));
  const ids: string[] = [];
  for (const page of [1, 2]) {
    const params = new URLSearchParams({ q: query, discovery_id: identity, page: String(page) });
    const response = await native.call(`/api/web/session/_/leads?${params}`);
    expect(response.status).toBe(200);
    expect(response.body.total).toBe(56);
    expect(response.body.leads).toHaveLength(page === 1 ? 50 : 6);
    ids.push(...response.body.leads.map((lead: any) => lead.id));
  }
  expect(new Set(ids).size).toBe(56);
  expect(new Set(ids)).toEqual(new Set(Array.from({ length: 56 }, (_, i) => `70000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`)));
  await native.flush();
  const preflight = native.evidence.find(row => row.method === "OPTIONS" && row.path === "/api/discoveries");
  expect(preflight).toMatchObject({ status: 200, origin: frontend, allowOrigin: frontend });
  expect(preflight!.requestedHeaders!.toLowerCase()).toContain("x-loqi-test-run-id");
  expect(preflight!.allowHeaders!.toLowerCase()).toContain("x-loqi-test-run-id");
  expect(preflight!.allowMethods).toContain("POST");
  for (const row of native.evidence) expect(row.allowOrigin).toBe(frontend);
  const post = native.evidence.findIndex(row => row.method === "POST" && row.path === "/api/discoveries");
  expect(post).toBeGreaterThan(native.evidence.indexOf(preflight!));
  expect(native.evidence.some(row => row.method === "GET" && row.path === `/api/discoveries/${identity}`)).toBe(true);
  expect(native.evidence.some(row => row.method === "GET" && row.path.endsWith("/leads"))).toBe(true);
});

test("native CORS exposes authentication and missing/invalid approval errors", async ({ native }) => {
  for (const auth of ["missing", "invalid"] as const) {
    const response = await native.call("/api/discoveries", { method: "POST", auth,
      body: { query: "COO", initiation: "manual" } });
    expect(response.status).toBe(401);
    expect(response.body.detail).toBe("Unknown synthetic session");
  }
  for (const approval of ["missing", "invalid"] as const) {
    const response = await native.call("/api/discoveries", { method: "POST", approval,
      body: { query: "COO", initiation: "manual" } });
    expect(response.status).toBe(412);
    expect(response.body.detail).toBe("Isolated run approval mismatch");
  }
  await native.flush();
  const errors = native.evidence.filter(row => row.method === "POST");
  expect(errors.map(row => row.status)).toEqual([401, 401, 412, 412]);
  for (const row of errors) expect(row.allowOrigin).toBe(frontend);
});

test("opaque unapproved origin fails native preflight before Discovery POST", async ({ page, native }) => {
  await page.evaluate(() => {
    const frame = document.createElement("iframe");
    frame.id = "opaque-probe";
    frame.sandbox.add("allow-scripts"); // Deliberately omit allow-same-origin.
    frame.srcdoc = "<!doctype html><title>Opaque CORS probe</title>";
    document.body.append(frame);
  });
  const handle = await page.locator("#opaque-probe").elementHandle();
  const frame = await handle!.contentFrame();
  await frame!.waitForLoadState();
  expect(await frame!.evaluate(() => window.origin)).toBe("null");
  const result = await frame!.evaluate(async ({ backend, runId, workspace, session }) => {
    try {
      const response = await fetch(`${backend}/api/discoveries`, { method: "POST", mode: "cors", credentials: "omit", redirect: "error",
        headers: { authorization: `Bearer ${session}`, "content-type": "application/json", "x-workspace-id": workspace, "x-loqi-test-run-id": runId },
        body: JSON.stringify({ query: "COO", initiation: "manual" }), signal: AbortSignal.timeout(5000) });
      return { readable: true, status: response.status, error: "" };
    } catch (error) {
      return { readable: false, status: 0, error: error instanceof Error ? error.name : "unknown" };
    }
  }, { backend, runId: native.runId, workspace, session });
  expect(result).toEqual({ readable: false, status: 0, error: "TypeError" });
  await native.flush();
  const denied = native.evidence.filter(row => row.method === "OPTIONS" && row.path === "/api/discoveries");
  expect(denied).toHaveLength(1);
  expect(denied[0]).toMatchObject({ status: 400, origin: "null", allowOrigin: null });
  expect(native.evidence.filter(row => row.method === "POST")).toHaveLength(0);
});
