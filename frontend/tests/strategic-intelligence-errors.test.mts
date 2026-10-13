import assert from "node:assert/strict";
import { generateStrategicProfile } from "../lib/strategic-intelligence-api.ts";

(globalThis as any).localStorage = { getItem: () => "offline-test-token" };
(globalThis as any).fetch = async () => new Response(
  JSON.stringify({ detail: "Internal Server Error" }),
  { status: 502, headers: { "Content-Type": "application/json" } },
);

const request = {
  company_description: "A planning tool", ideal_customer: "Founders",
  differentiation: "Faster setup", annual_goal: "Grow", biggest_obstacle: "Awareness",
};
await assert.rejects(generateStrategicProfile(request), /retry or continue without a profile/);

(globalThis as any).fetch = async () => new Response("Internal Server Error", { status: 500 });
await assert.rejects(generateStrategicProfile(request), /answers are saved; you can continue/);
