import assert from "node:assert";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const { createJobPollingLoop } = require("../hooks/useJobPolling.ts") as {
  createJobPollingLoop: typeof import("../hooks/useJobPolling").createJobPollingLoop;
};

type JobResponse = {
  id: string;
  user_id: string;
  type: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  stage: string;
  progress: number;
  query: string;
  error_message: string | null;
  result_ready: boolean;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: Error) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

class FakeTimers {
  delays: number[] = [];
  private callbacks = new Map<number, () => void>();
  private nextId = 1;

  setTimeout = (callback: () => void, delay: number) => {
    const id = this.nextId++;
    this.delays.push(delay);
    this.callbacks.set(id, callback);
    return id as unknown as ReturnType<typeof setTimeout>;
  };

  clearTimeout = (handle: ReturnType<typeof setTimeout>) => {
    this.callbacks.delete(handle as unknown as number);
  };

  fireNext() {
    const next = this.callbacks.entries().next().value as [number, () => void] | undefined;
    assert.ok(next, "expected a scheduled poll");
    this.callbacks.delete(next[0]);
    next[1]();
  }

  get pending() {
    return this.callbacks.size;
  }
}

const runningJob = (id = "job-1"): JobResponse => ({
  id,
  user_id: "user-1",
  type: "search",
  status: "running",
  stage: "searching",
  progress: 50,
  query: "query",
  error_message: null,
  result_ready: false,
  created_at: "",
  updated_at: "",
  completed_at: null,
});

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

function loop(timers: FakeTimers, fetchJob: (id: string) => Promise<JobResponse>, callbacks = {}) {
  return createJobPollingLoop({
    jobId: "job-1",
    getJob: fetchJob,
    getJobResults: async () => ({ ok: true, leads: [{ id: "lead-1" }] }),
    onJob: () => {},
    onCompleted: () => {},
    onTerminal: () => {},
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
    ...callbacks,
  });
}

test("starts the first status poll immediately", async () => {
  const timers = new FakeTimers();
  const first = deferred<JobResponse>();
  let calls = 0;
  const stop = loop(timers, async () => {
    calls += 1;
    return first.promise;
  });

  assert.strictEqual(calls, 1);
  assert.strictEqual(timers.pending, 0);
  first.resolve(runningJob());
  await flush();
  assert.deepStrictEqual(timers.delays, [1000]);
  stop();
});

test("backs off after failures and resets after a successful status response", async () => {
  const timers = new FakeTimers();
  const attempts = [
    deferred<JobResponse>(), deferred<JobResponse>(), deferred<JobResponse>(),
    deferred<JobResponse>(), deferred<JobResponse>(), deferred<JobResponse>(),
  ];
  let call = 0;
  const stop = loop(timers, async () => attempts[call++].promise);

  for (const delay of [2000, 4000, 6000, 8000, 8000]) {
    attempts[call - 1].reject(new Error("network"));
    await flush();
    assert.strictEqual(timers.delays.at(-1), delay);
    timers.fireNext();
  }

  attempts[call - 1].resolve(runningJob());
  await flush();
  assert.strictEqual(timers.delays.at(-1), 1000);
  stop();
});

test("does not overlap a slow status request", async () => {
  const timers = new FakeTimers();
  const first = deferred<JobResponse>();
  let calls = 0;
  const stop = loop(timers, async () => {
    calls += 1;
    return first.promise;
  });

  await flush();
  assert.strictEqual(calls, 1);
  assert.strictEqual(timers.pending, 0);
  first.resolve(runningJob());
  await flush();
  timers.fireNext();
  await flush();
  assert.strictEqual(calls, 2);
  stop();
});

test("terminal completion stops scheduling and returns results", async () => {
  const timers = new FakeTimers();
  const completed: Record<string, unknown>[][] = [];
  const terminal = { called: false };
  const stop = loop(timers, async () => ({ ...runningJob(), status: "completed", progress: 100 }), {
    onCompleted: (leads: Record<string, unknown>[]) => completed.push(leads),
    onTerminal: () => { terminal.called = true; },
  });

  await flush();
  assert.strictEqual(timers.pending, 0);
  assert.deepStrictEqual(completed, [[{ id: "lead-1" }]]);
  assert.strictEqual(terminal.called, false);
  stop();
});

test("failed and cancelled jobs stop scheduling immediately", async () => {
  for (const status of ["failed", "cancelled"] as const) {
    const timers = new FakeTimers();
    let terminalCalls = 0;
    const stop = loop(timers, async () => ({ ...runningJob(), status, error_message: "done" }), {
      onTerminal: () => { terminalCalls += 1; },
    });

    await flush();
    assert.strictEqual(terminalCalls, 1, `${status} must mark the job terminal`);
    assert.strictEqual(timers.pending, 0, `${status} must not schedule another poll`);
    stop();
  }
});

test("cleanup clears scheduled work and suppresses stale response callbacks", async () => {
  const timers = new FakeTimers();
  const first = deferred<JobResponse>();
  let updates = 0;
  const stop = loop(timers, async () => first.promise, {
    onJob: () => { updates += 1; },
  });

  stop();
  first.resolve(runningJob());
  await flush();
  assert.strictEqual(updates, 0);
  assert.strictEqual(timers.pending, 0);
});
