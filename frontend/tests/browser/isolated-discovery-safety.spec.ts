import { test, expect } from "@playwright/test";
import { backendRequest } from "./isolated-discovery.fixture";

// No browser/backend fixture is requested: rejected inputs never open a socket.
test("isolated HTTP forwarding rejects production, opt-out and unexpected paths", async () => {
  const saved = { ...process.env };
  try {
    process.env.LOQI_RUN_DISCOVERY_HTTP = "1";
    process.env.LOQI_ISOLATED_BACKEND_RUN_ID = "00000000-0000-4000-8000-000000000001";
    for (const target of ["http://127.0.0.1:10000", "https://production.invalid", "http://127.0.0.1:19877", "http://localhost:19876"]) {
      process.env.LOQI_ISOLATED_BACKEND_URL = target;
      await expect(backendRequest("POST", "/api/discoveries", "{}")).rejects.toThrow("Unapproved isolated request");
    }
    process.env.LOQI_ISOLATED_BACKEND_URL = "http://127.0.0.1:19876";
    await expect(backendRequest("POST", "/api/send-email", "{}")).rejects.toThrow("Unapproved isolated request");
    await expect(backendRequest("GET", "//production.invalid/api/discoveries")).rejects.toThrow("Unapproved isolated request");
    process.env.LOQI_RUN_DISCOVERY_HTTP = "0";
    await expect(backendRequest("GET", "/__loqi_test/identity")).rejects.toThrow("Unapproved isolated request");
  } finally {
    for (const key of ["LOQI_RUN_DISCOVERY_HTTP", "LOQI_ISOLATED_BACKEND_URL", "LOQI_ISOLATED_BACKEND_RUN_ID"]) {
      if (saved[key] === undefined) delete process.env[key]; else process.env[key] = saved[key];
    }
  }
});
