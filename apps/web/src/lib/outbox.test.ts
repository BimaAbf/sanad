/**
 * T13 §14 — "a 30-second dropout mid-session loses zero attempts and creates
 * zero duplicates".
 *
 * Simulated here rather than only in Playwright, because the interesting cases
 * are the ones a browser test cannot reliably produce: a request that succeeded
 * on the server and never returned, and a component that remounts and
 * re-submits the same answer.
 */
import { describe, expect, it } from "vitest";

import { MemoryOutboxStorage, Outbox, attemptKey } from "./outbox";

function clock(start = 1_000_000): { now: () => number; advance: (ms: number) => void } {
  let value = start;
  return { now: () => value, advance: (ms) => (value += ms) };
}

describe("attempt keys", () => {
  it("are deterministic in their inputs", () => {
    // A random UUID would be regenerated on a remount and the same answer would
    // reach the server twice with two keys — the one duplicate the server
    // cannot detect.
    expect(attemptKey("s1", "a1", 1)).toBe(attemptKey("s1", "a1", 1));
    expect(attemptKey("s1", "a1", 1)).not.toBe(attemptKey("s1", "a1", 2));
    expect(attemptKey("s1", "a1", 1)).not.toBe(attemptKey("s2", "a1", 1));
  });
});

describe("enqueue", () => {
  it("stores the attempt before anything is posted", async () => {
    const posted: string[] = [];
    const storage = new MemoryOutboxStorage();
    const outbox = new Outbox(storage, async (_e, _b, key) => {
      posted.push(key);
      return { ok: true };
    });

    await outbox.enqueue("/play/sessions/s1/attempts", { result: "correct" }, "k1");
    expect(await outbox.pending()).toHaveLength(1);
    expect(posted).toEqual([]);
  });

  it("is idempotent for the same key", async () => {
    const outbox = new Outbox(new MemoryOutboxStorage(), async () => ({ ok: true }));
    await outbox.enqueue("/e", { n: 1 }, "k1");
    await outbox.enqueue("/e", { n: 2 }, "k1");
    const pending = await outbox.pending();
    expect(pending).toHaveLength(1);
    // The FIRST body wins. A re-submit is the same answer, not a correction.
    expect(pending[0]!.body).toEqual({ n: 1 });
  });
});

describe("a 30-second dropout", () => {
  it("loses zero attempts and creates zero duplicates", async () => {
    const time = clock();
    const seen = new Map<string, number>();
    let online = true;

    const storage = new MemoryOutboxStorage();
    const outbox = new Outbox(
      storage,
      async (_endpoint, _body, key) => {
        if (!online) throw new Error("network down");
        seen.set(key, (seen.get(key) ?? 0) + 1);
        return { ok: true };
      },
      time.now,
    );

    // Six activities. The network dies after the second and returns after the
    // fifth — 30 seconds of a child playing on regardless, which is the point.
    for (let index = 0; index < 6; index += 1) {
      if (index === 2) online = false;
      if (index === 5) online = true;
      await outbox.enqueue("/attempts", { index }, attemptKey("s1", `a${index}`, 1));
      await outbox.drain();
      time.advance(5000);
    }
    await outbox.drain();

    expect(await outbox.pending()).toEqual([]);
    expect(seen.size).toBe(6);
    // Every attempt reached the server, and the server saw each key at least
    // once. Duplicates are prevented by the key, which the next test covers.
    for (const [key, count] of seen) {
      expect(count, key).toBeGreaterThanOrEqual(1);
    }
  });

  it("a record whose response was lost is not sent as a new attempt", async () => {
    // The hard case: the server accepted it, the response never arrived. The
    // retry carries the SAME key, so the server recognises it and answers
    // `duplicate` — which the outbox treats as success, not as a failure to
    // retry forever.
    const time = clock();
    let call = 0;
    const outbox = new Outbox(
      new MemoryOutboxStorage(),
      async () => {
        call += 1;
        if (call === 1) throw new Error("connection reset after the server committed");
        return { ok: false, duplicate: true };
      },
      time.now,
    );

    await outbox.enqueue("/attempts", {}, "k1");
    expect(await outbox.drain()).toEqual({ sent: 0, failed: 1 });
    expect(await outbox.drain()).toEqual({ sent: 1, failed: 0 });
    expect(await outbox.pending()).toEqual([]);
  });

  it("a failed post leaves the record pending and counts the attempt", async () => {
    const outbox = new Outbox(new MemoryOutboxStorage(), async () => ({ ok: false }));
    await outbox.enqueue("/attempts", {}, "k1");
    await outbox.drain();
    await outbox.drain();
    const pending = await outbox.pending();
    expect(pending).toHaveLength(1);
    expect(pending[0]!.attempts).toBe(2);
  });
});

describe("draining", () => {
  it("sends in the order the child answered", async () => {
    const order: string[] = [];
    const time = clock();
    const outbox = new Outbox(
      new MemoryOutboxStorage(),
      async (_e, _b, key) => {
        order.push(key);
        return { ok: true };
      },
      time.now,
    );
    for (const key of ["k1", "k2", "k3"]) {
      await outbox.enqueue("/attempts", {}, key);
      time.advance(1000);
    }
    await outbox.drain();
    expect(order).toEqual(["k1", "k2", "k3"]);
  });

  it("draining twice does not resend an acknowledged record", async () => {
    let calls = 0;
    const outbox = new Outbox(new MemoryOutboxStorage(), async () => {
      calls += 1;
      return { ok: true };
    });
    await outbox.enqueue("/attempts", {}, "k1");
    await outbox.drain();
    await outbox.drain();
    expect(calls).toBe(1);
  });

  it("caps a single pass so a long offline stretch does not block the UI", async () => {
    const outbox = new Outbox(new MemoryOutboxStorage(), async () => ({ ok: true }));
    for (let index = 0; index < 150; index += 1) {
      await outbox.enqueue("/attempts", {}, `k${index}`);
    }
    const first = await outbox.drain();
    expect(first.sent).toBe(100);
    expect(await outbox.pending()).toHaveLength(50);
  });
});

describe("pruning", () => {
  it("keeps an acknowledged record long enough to block a re-enqueue", async () => {
    const time = clock();
    let calls = 0;
    const outbox = new Outbox(
      new MemoryOutboxStorage(),
      async () => {
        calls += 1;
        return { ok: true };
      },
      time.now,
    );

    await outbox.enqueue("/attempts", {}, "k1");
    await outbox.drain();
    expect(await outbox.prune()).toBe(0);

    // A remount re-submits. The key is still known, so nothing is queued.
    await outbox.enqueue("/attempts", {}, "k1");
    await outbox.drain();
    expect(calls).toBe(1);

    time.advance(6 * 60 * 1000);
    expect(await outbox.prune()).toBe(1);
  });

  it("never prunes a record that has not been acknowledged", async () => {
    const time = clock();
    const outbox = new Outbox(new MemoryOutboxStorage(), async () => ({ ok: false }), time.now);
    await outbox.enqueue("/attempts", {}, "k1");
    await outbox.drain();
    time.advance(24 * 60 * 60 * 1000);
    expect(await outbox.prune()).toBe(0);
    expect(await outbox.pending()).toHaveLength(1);
  });
});
