# ADR 012 — Progress: one rollup function, and where the product rules live

- **Status:** accepted
- **Date:** 2026-08-29
- **Component:** P10 — C09 progress & analytics
- **Context docs:** `docs/04a` §C09 · `docs/02` §8 · `docs/05` §5 · `docs/10` T10

## Decisions

### D1 — Both rollup paths call the same function

docs/04a §C09 calls the nightly rebuild "the correctness backstop for the
incremental path". A backstop is only a backstop if the two paths *can*
disagree — so they differ in which sessions they are handed, and in nothing
else. `compute()` takes a period and its member sessions; `rebuild_all` and
`rebuild_for_session` differ only in what they pass it.

The test runs a 30-session history through both and diffs field by field. The
history deliberately contains same-day sessions and a gap week, which are the
two shapes where a delta-based incremental path silently diverges.

### D2 — Recompute a period in full rather than adding a delta

This is what makes replay a no-op *by construction* rather than by a guard. A
delta-based version would need an exactly-once guarantee that ARQ does not
provide and that this system should not need.

### D3 — `accuracy` is nullable, and null is not zero

A week with no play has `accuracy = NULL`, not `0.0`. A dashboard rendering 0%
accuracy for a quiet week tells a parent their child failed everything, which is
the opposite of what happened.

### D4 — The three product rules live on the server

docs/04a §C09 lists them under "Design rules that matter here" and they are
implemented in `domain/views.py`, not in the client:

1. **No trend under three data points.** `build_journey` returns
   `insufficient_data` plus a copy key. The client cannot decide to draw a
   two-point line anyway.
2. **No percentile, norm or DQ on a dashboard.** Checked over the *entire*
   generated OpenAPI document, so a future endpoint in another module cannot
   reintroduce one. Report payloads are explicitly exempt — DQ belongs there, in
   context, behind the opt-in panel.
3. **A regression always carries exactly three activities.** And if the engine
   cannot offer three, the regression is *not surfaced at all*: one or two
   activities would present a regression together with an inadequate answer to
   it, which is worse than saying nothing.

A rule that lives in the UI is a rule the next client forgets.

### D5 — Periods are keyed in the family's civil day

`day:` keys use Africa/Cairo, not UTC. A session at 01:00 local is 23:00 UTC the
previous day; rolling it into yesterday breaks a streak for a family that did
nothing wrong. Weeks are ISO — the key is an identifier, and the caregiver app
labels the week however it likes.

### D6 — Two additions to the docs/02 §8 DDL

- **`events.idempotency_key`.** docs/05 §5 has the client drain an offline
  outbox into `POST /events`, so the same batch arrives more than once by
  design. The unique index is on `(idempotency_key, server_ts)` because a
  partitioned table's unique index must contain the partition key — Postgres
  refuses otherwise, and that refusal is why the pair is what it is.
- **A `period` shape CHECK.** `day:` / `week:` / `all` and nothing else. Two
  spellings of one week is exactly how the nightly rebuild starts disagreeing
  with the incremental path in a way that takes a day to find.

### D7 — A streak survives until the end of the next day

A streak that breaks at midnight punishes a family for the clock rather than for
anything they did. The first thing a streak must not become is another source of
pressure.

## Consequences

`progress/repository.py` is at 0% coverage: it is entirely SQL and needs a
database, which is blocked (BLOCKED.md #1). The partition-creation job, the
upserts and the `ON CONFLICT DO NOTHING` idempotency have never run.
