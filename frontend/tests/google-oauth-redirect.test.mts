import assert from "node:assert/strict";
import test from "node:test";
import { localGoogleOAuthCallbackUri } from "../lib/auth-api.ts";

test("local Google sign-in sends an explicit callback URI for supported loopback hosts", () => {
  assert.equal(
    localGoogleOAuthCallbackUri("http://localhost:3000"),
    "http://localhost:3000/auth/google/callback",
  );
  assert.equal(
    localGoogleOAuthCallbackUri("http://127.0.0.1:3000"),
    "http://127.0.0.1:3000/auth/google/callback",
  );
});

test("production and malformed origins do not request a local callback override", () => {
  assert.equal(localGoogleOAuthCallbackUri("https://app.example.test"), undefined);
  assert.equal(localGoogleOAuthCallbackUri("not a URL"), undefined);
  assert.equal(localGoogleOAuthCallbackUri("http://user@localhost:3000"), undefined);
});
