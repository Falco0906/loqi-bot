import assert from "node:assert/strict";
import { sendOnboardingTurn } from "../lib/onboarding-api.ts";

const storage = new Map([["loqi_access_token", "offline-test-token"]]);
(globalThis as any).localStorage = { getItem: (key: string) => storage.get(key) ?? null };

let captured: { url: string; options: RequestInit } | null = null;
(globalThis as any).fetch = async (url: string, options: RequestInit) => {
  captured = { url, options };
  return new Response(JSON.stringify({
    field: "companyDescription", answer: "A planning tool", reply: "Noted. Who buys it?",
    mode: "ai", next_field: "idealCustomer", complete: false,
  }), { status: 200, headers: { "Content-Type": "application/json" } });
};

const turn = await sendOnboardingTurn("user-1", "companyDescription", "A planning tool");
assert.equal(turn.mode, "ai");
assert.ok(captured?.url.includes("/api/v1/onboarding/conversation/turn?user_id=user-1"));
assert.equal((captured?.options.headers as Record<string, string>).Authorization, "Bearer offline-test-token");
assert.deepEqual(JSON.parse(String(captured?.options.body)), {
  field: "companyDescription", answer: "A planning tool",
});

(globalThis as any).fetch = async () => new Response(JSON.stringify({ detail: "Answer is out of date" }), {
  status: 409, headers: { "Content-Type": "application/json" },
});
await assert.rejects(
  sendOnboardingTurn("user-1", "companyDescription", "Different answer"),
  /Answer is out of date/,
);
