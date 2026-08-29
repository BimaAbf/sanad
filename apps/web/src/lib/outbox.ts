/**
 * The offline outbox.
 *
 * docs/04e §C13: "Every attempt is written locally with an idempotency key
 * first, then posted. Network failures are invisible."
 *
 * The order is the design. Write-then-post means a dropped connection loses
 * nothing; post-then-write means a request that succeeded on the server but
 * never returned gets replayed as a second attempt, and a child is recorded as
 * having answered twice. The acceptance criterion — a 30-second dropout loses
 * zero attempts and creates zero duplicates — is satisfiable only in that
 * order.
 *
 * The storage is behind an interface so the whole thing is testable in Node.
 * IndexedDB is one implementation; a Map is the other, and the tests use it.
 *
 * Pure logic plus a storage port. No React, no fetch.
 */

export interface OutboxRecord {
  /** Client-generated, stable across every retry of the same attempt. */
  idempotencyKey: string;
  /** API path this record posts to. */
  endpoint: string;
  body: unknown;
  createdAtMs: number;
  attempts: number;
  /** Set once the server has acknowledged it. Kept, not deleted — see `prune`. */
  acknowledgedAtMs: number | null;
}

export interface OutboxStorage {
  put(record: OutboxRecord): Promise<void>;
  all(): Promise<OutboxRecord[]>;
  delete(idempotencyKey: string): Promise<void>;
}

export class MemoryOutboxStorage implements OutboxStorage {
  private readonly rows = new Map<string, OutboxRecord>();

  async put(record: OutboxRecord): Promise<void> {
    this.rows.set(record.idempotencyKey, record);
  }

  async all(): Promise<OutboxRecord[]> {
    return [...this.rows.values()].sort((a, b) => a.createdAtMs - b.createdAtMs);
  }

  async delete(idempotencyKey: string): Promise<void> {
    this.rows.delete(idempotencyKey);
  }
}

export type Poster = (
  endpoint: string,
  body: unknown,
  idempotencyKey: string,
) => Promise<{ ok: boolean; duplicate?: boolean }>;

/** How long an acknowledged record is kept before `prune` removes it. */
export const ACK_RETENTION_MS = 5 * 60 * 1000;

/** Records older than this that have never succeeded are still retried. */
export const MAX_DRAIN_BATCH = 100;

export class Outbox {
  constructor(
    private readonly storage: OutboxStorage,
    private readonly post: Poster,
    private readonly now: () => number = () => Date.now(),
  ) {}

  /**
   * Record an attempt locally. Always succeeds, always synchronously durable
   * before any network call is made.
   *
   * Re-enqueuing the same key is a no-op rather than a second row: a component
   * that re-renders and re-submits must not create a duplicate, and the key is
   * the only thing that can tell us it is the same answer.
   */
  async enqueue(endpoint: string, body: unknown, idempotencyKey: string): Promise<void> {
    const existing = (await this.storage.all()).find(
      (row) => row.idempotencyKey === idempotencyKey,
    );
    if (existing) return;
    await this.storage.put({
      idempotencyKey,
      endpoint,
      body,
      createdAtMs: this.now(),
      attempts: 0,
      acknowledgedAtMs: null,
    });
  }

  /** Everything still waiting to reach the server. */
  async pending(): Promise<OutboxRecord[]> {
    return (await this.storage.all()).filter((row) => row.acknowledgedAtMs === null);
  }

  /**
   * Try to send everything pending. Safe to call repeatedly and concurrently
   * with itself — the server deduplicates on the same key, and a record is only
   * marked acknowledged after the server said so.
   *
   * Returns how many were acknowledged in this pass. A failure is not an
   * error: the record stays pending and the next `online` event tries again.
   */
  async drain(): Promise<{ sent: number; failed: number }> {
    const pending = (await this.pending()).slice(0, MAX_DRAIN_BATCH);
    let sent = 0;
    let failed = 0;

    for (const record of pending) {
      let result: { ok: boolean; duplicate?: boolean };
      try {
        result = await this.post(record.endpoint, record.body, record.idempotencyKey);
      } catch {
        // A thrown fetch is a network failure, which is the normal case this
        // whole module exists for. Not logged as an error.
        result = { ok: false };
      }
      const next: OutboxRecord = { ...record, attempts: record.attempts + 1 };
      // A duplicate is a success: the server already has this attempt. Treating
      // it as a failure would retry forever.
      if (result.ok || result.duplicate) {
        next.acknowledgedAtMs = this.now();
        sent += 1;
      } else {
        failed += 1;
      }
      await this.storage.put(next);
    }
    return { sent, failed };
  }

  /**
   * Drop acknowledged records that are old enough to be safely forgotten.
   *
   * Acknowledged rows are kept for a while rather than deleted on the spot, so
   * that a component replaying a queue it already drained cannot re-enqueue an
   * attempt the server has: `enqueue` sees the key and does nothing.
   */
  async prune(): Promise<number> {
    const cutoff = this.now() - ACK_RETENTION_MS;
    const rows = await this.storage.all();
    let removed = 0;
    for (const row of rows) {
      if (row.acknowledgedAtMs !== null && row.acknowledgedAtMs <= cutoff) {
        await this.storage.delete(row.idempotencyKey);
        removed += 1;
      }
    }
    return removed;
  }
}

/**
 * A stable idempotency key for one attempt.
 *
 * Deterministic in its inputs on purpose. A random UUID would be regenerated on
 * a component remount and the same answer would reach the server twice with two
 * keys — which is precisely the duplicate the server cannot detect.
 */
export function attemptKey(
  sessionId: string,
  activityId: string,
  attemptNo: number,
): string {
  return `${sessionId}:${activityId}:${attemptNo}`;
}
