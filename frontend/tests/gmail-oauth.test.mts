/**
 * Regression tests for the PR10.9 Gmail OAuth popup flow.
 *
 * Root cause being guarded: the connect handler awaited the auth-URL fetch
 * BEFORE window.open, so the browser blocked the popup and the old fallback
 * navigated the main Loqi tab to the callback. The helper now opens the popup
 * synchronously within the click gesture and reports "blocked" instead of
 * navigating the main window.
 *
 * Run with: node tests/gmail-oauth.test.mts
 */

import assert from "node:assert";
import { test } from "node:test";
import {
  apiOrigin,
  isTrustedGmailOAuthMessage,
  openGmailAuthPopup,
} from "../lib/gmail-oauth.ts";

function fakeWindow() {
  return {
    location: { href: "" },
    closed: false,
    close() {
      this.closed = true;
    },
  } as unknown as Window;
}

test("A. popup is opened synchronously (blank) then navigated to the auth URL", async () => {
  const opened: string[] = [];
  const popup = fakeWindow();
  const open = (_url: string, name: string) => {
    opened.push(`${_url}|${name}`);
    return popup;
  };
  const result = await openGmailAuthPopup(
    async () => ({ ok: true, url: "https://accounts.google.com/o/oauth2/v2/auth?state=abc" }),
    open,
  );
  assert.strictEqual(result.status, "opened");
  // The popup must be opened with a blank URL first (synchronous gesture),
  // then navigated to the auth URL.
  assert.deepStrictEqual(opened, ["|gmail-oauth"]);
  assert.strictEqual(popup.location.href, "https://accounts.google.com/o/oauth2/v2/auth?state=abc");
});

test("B. blocked popup returns 'blocked' and never navigates the main window", async () => {
  const result = await openGmailAuthPopup(
    async () => ({ ok: true, url: "https://accounts.google.com/oauth" }),
    () => null, // window.open returns null (popup blocked)
  );
  assert.strictEqual(result.status, "blocked");
});

test("C. auth URL fetch failure closes the popup and returns 'error'", async () => {
  const popup = fakeWindow();
  const result = await openGmailAuthPopup(
    async () => ({ ok: false }),
    () => popup,
  );
  assert.strictEqual(result.status, "error");
  assert.strictEqual(popup.closed, true);
});

test("D. fetch throwing returns 'error' and closes the popup", async () => {
  const popup = fakeWindow();
  const result = await openGmailAuthPopup(
    async () => { throw new Error("network"); },
    () => popup,
  );
  assert.strictEqual(result.status, "error");
  assert.strictEqual(popup.closed, true);
});

test("E. strict origin validation accepts the API origin and rejects others", () => {
  const api = apiOrigin("https://api.tryloqi.com");
  assert.strictEqual(api, "https://api.tryloqi.com");
  assert.strictEqual(isTrustedGmailOAuthMessage({ origin: api }, api), true);
  assert.strictEqual(isTrustedGmailOAuthMessage({ origin: "https://evil.example" }, api), false);
  assert.strictEqual(isTrustedGmailOAuthMessage({ origin: "" }, api), false);
  assert.strictEqual(isTrustedGmailOAuthMessage({ origin: "https://app.tryloqi.com" }, api), false);
});
