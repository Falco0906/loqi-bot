/**
 * Regression tests for the Settings Connected Accounts UI logic (PR10.8.2).
 *
 * Run with: node tests/gmail-settings.test.mts
 */

import assert from "node:assert";
import { test } from "node:test";
import {
  gmailProviders,
  hasGmailProvider,
  shouldShowConnectButton,
  isReauthRequired,
  statusTone,
  type ProviderInfo,
} from "../lib/gmail-settings.ts";

const gmailHealthy: ProviderInfo = {
  id: "p1",
  provider_type: "gmail",
  status: "healthy",
  email: "faisal96kp@gmail.com",
};

const gmailAuthFailed: ProviderInfo = {
  id: "p2",
  provider_type: "gmail",
  status: "auth_failed",
  email: "faisal96kp@gmail.com",
};

test("A. gmailProviders filters to gmail only", () => {
  assert.strictEqual(gmailProviders([gmailHealthy, { id: "m1", provider_type: "manual", status: "healthy", email: "" }]).length, 1);
});

test("B. hasGmailProvider true when a gmail provider exists", () => {
  assert.strictEqual(hasGmailProvider([gmailHealthy]), true);
  assert.strictEqual(hasGmailProvider([gmailAuthFailed]), true);
  assert.strictEqual(hasGmailProvider([]), false);
});

test("C. Connect Gmail button hidden when any Gmail connection exists", () => {
  assert.strictEqual(shouldShowConnectButton([gmailHealthy]), false);
  assert.strictEqual(shouldShowConnectButton([gmailAuthFailed]), false);
});

test("D. Connect Gmail button shown only when no Gmail connection exists", () => {
  assert.strictEqual(shouldShowConnectButton([]), true);
  assert.strictEqual(shouldShowConnectButton([{ id: "m1", provider_type: "manual", status: "healthy", email: "" }]), true);
});

test("E. auth_failed is reauth-required and never rendered as healthy", () => {
  assert.strictEqual(isReauthRequired("auth_failed"), true);
  assert.strictEqual(isReauthRequired("expired_token"), true);
  assert.strictEqual(isReauthRequired("healthy"), false);
  assert.strictEqual(statusTone("auth_failed"), "text-error");
  assert.strictEqual(statusTone("healthy"), "text-success");
  assert.notStrictEqual(statusTone("auth_failed"), statusTone("healthy"));
});

test("F. status tones cover known backend statuses", () => {
  assert.strictEqual(statusTone("healthy"), "text-success");
  assert.strictEqual(statusTone("disconnected"), "text-on-surface-variant/50");
  assert.strictEqual(statusTone("scope_insufficient"), "text-error");
  assert.strictEqual(statusTone("unknown-thing"), "text-warning");
});
