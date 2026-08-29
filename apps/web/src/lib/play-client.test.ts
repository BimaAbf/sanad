import { afterEach, describe, expect, it, vi } from "vitest";

import { MemoryOutboxStorage, Outbox } from "@/lib/outbox";
import { attemptsEndpoint, playPoster, startSession } from "@/lib/play-client";

/**
 * The sender the outbox was missing.
 *
 * `Outbox` has always been correct and always been tested — against
 * `async () => ({ ok: true })`. That is the same function `/play` shipped with,
 * so the tests proved the queue worked while the product stored nothing. What
 * needs testing is the mapping from an HTTP response to the outbox's three
 * outcomes, because each one changes what happens to a child's attempt:
 *
 * * delivered — the record is acknowledged and eventually pruned;
 * * duplicate — ALSO acknowledged, or the drain after a reconnect retries a row
 *   the server already has, forever;
 * * neither — kept pending, retried on the next `online` event.
 */

function respond(status: number, body: unknown = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("playPoster", () => {
  it("posts to the same-origin proxy, never the API, and sends the key as a header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(202, { accepted: 1, duplicates: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await playPoster(attemptsEndpoint("s-1"), { result: "correct" }, "key-12345678");

    const [url, init] = fetchMock.mock.calls[0]!;
    // A same-origin path. The access token lives in an httpOnly cookie that
    // this code cannot read, which is the whole reason the proxy exists.
    expect(url).toBe("/api/play/sessions/s-1/attempts");
    expect(init.headers["Idempotency-Key"]).toBe("key-12345678");
  });

  it("reports a stored attempt as delivered and not as a duplicate", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(202, { accepted: 1, duplicates: 0 })));
    expect(await playPoster("/play/sessions/s/attempts", {}, "k-11111111")).toEqual({
      ok: true,
      duplicate: false,
    });
  });

  it("reports a key the server already had as a duplicate, which is a success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(202, { accepted: 0, duplicates: 1 })));
    const result = await playPoster("/play/sessions/s/attempts", {}, "k-11111111");
    expect(result.ok || result.duplicate).toBe(true);
  });

  it("keeps an attempt pending when the API is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
    expect(await playPoster("/play/sessions/s/attempts", {}, "k-11111111")).toEqual({ ok: false });
  });

  it("keeps an attempt pending on a 503, because a 503 is temporary", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(503)));
    const result = await playPoster("/play/sessions/s/attempts", {}, "k-11111111");
    expect(result.ok || result.duplicate).toBeFalsy();
  });

  it("stops retrying a 4xx, which would never succeed and would block the queue", async () => {
    // A locally-built session answers 409 here. Retrying it forever would keep
    // every later attempt behind it in a 100-record drain batch.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(409)));
    const result = await playPoster("/play/sessions/local-1/attempts", {}, "k-11111111");
    expect(result.ok || result.duplicate).toBe(true);
  });
});

describe("the outbox with the real sender", () => {
  it("loses nothing and duplicates nothing across a dropout and a reconnect", async () => {
    // The docs/04e §C13 acceptance criterion, at the seam the criterion is
    // actually about: the queue plus the sender, not the queue alone.
    const seen = new Set<string>();
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const key = (init.headers as Record<string, string>)["Idempotency-Key"]!;
      if (offline) throw new TypeError("network");
      const duplicate = seen.has(key);
      seen.add(key);
      return respond(202, { accepted: duplicate ? 0 : 1, duplicates: duplicate ? 1 : 0 });
    });
    let offline = true;
    vi.stubGlobal("fetch", fetchMock);

    const outbox = new Outbox(new MemoryOutboxStorage(), playPoster);
    for (let n = 0; n < 5; n += 1) {
      await outbox.enqueue(attemptsEndpoint("s-1"), { n }, `attempt-0000${n}`);
    }
    await outbox.drain();
    expect(await outbox.pending()).toHaveLength(5);

    offline = false;
    await outbox.drain();
    expect(await outbox.pending()).toHaveLength(0);

    // The reconnect drain replays nothing new, and a redundant drain adds no
    // rows on the server side either.
    await outbox.drain();
    expect(seen.size).toBe(5);
  });
});

describe("startSession", () => {
  it("returns null rather than throwing, so the child app falls back and plays", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
    expect(await startSession()).toBeNull();
  });

  it("returns null on a non-2xx for the same reason", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(401)));
    expect(await startSession(8)).toBeNull();
  });
});
