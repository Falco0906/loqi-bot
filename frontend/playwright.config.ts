import { defineConfig } from "@playwright/test";

const target = process.env.LOQI_BROWSER_BASE_URL;
const requestedBrowser = process.env.LOQI_BROWSER || "firefox";
if (requestedBrowser !== "firefox" && requestedBrowser !== "chromium") {
  throw new Error("LOQI_BROWSER must be firefox or chromium.");
}
if (target) {
  const url = new URL(target);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("LOQI_BROWSER_BASE_URL must be an explicit HTTP loopback origin.");
  }
}

export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  reporter: "list",
  outputDir: "/tmp/loqi-browser-results",
  use: {
    baseURL: target,
    browserName: requestedBrowser,
    serviceWorkers: "block",
    trace: "off",
    screenshot: "off",
    video: "off",
    viewport: { width: 1440, height: 1000 },
    launchOptions: {
      ...(process.env.LOQI_BROWSER_EXECUTABLE ? { executablePath: process.env.LOQI_BROWSER_EXECUTABLE } : {}),
    },
  },
  // No webServer: the repository requires a user-managed frontend.
});
