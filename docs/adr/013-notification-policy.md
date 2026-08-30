# ADR 013 — Notifications: one gate, and the order of its checks

- **Status:** accepted
- **Date:** 2026-08-29
- **Component:** P11 — C10 notifications & scheduling
- **Context docs:** `docs/04a` §C10 · `docs/02` §8 · `docs/06` §3 · `docs/10` T11

## Context

docs/04a §C10 states the purpose in one sentence — bring caregivers back at the
right moments *without becoming another anxiety source* — and then gives four
anti-nagging rules. The parent of a child with Down syndrome already has a phone
full of appointment reminders.

## Decisions

### D1 — One `decide()` function, and every send passes through it

Not per job. Nine jobs each politely limiting themselves is how you end up
sending nine notifications. `NotificationSender.send` is the only function that
touches a transport, so a job cannot reach a provider directly.

### D2 — Content, then cap, then quiet hours. In that order.

The ordering is load-bearing:

1. **Content first.** A notification that must never be sent is not made
   acceptable by being under the cap or arriving at a civilised hour.
2. **Cap second, as a drop.** A fourth notification this week is not wanted
   tomorrow either.
3. **Quiet hours last, as a deferral.** The notification is fine; only the
   moment is wrong.

Checking quiet hours before the cap would defer a notification into next week
and quietly convert a drop into a delivery.

### D3 — The banned-terms check is a hard failure, not a filter

`check_body` raises. A job that composed a perfectly reasonable sentence
containing "متأخر" gets an exception, not a delivery, and the list it checks
against is imported from `tools/lint/banned_terms.py` — the same list the i18n
bundle is linted with. A term added to the lint is immediately a term the send
path refuses.

### D4 — Quiet-hour deferral is computed from a local date, not by adding hours

`next_allowed_moment` constructs 08:00 on the correct Cairo date and lets
zoneinfo resolve the offset. Egypt reintroduced DST in 2023, so adding a fixed
number of hours lands an hour out across the April and October transitions —
which is how a "morning" notification arrives at 07:00 for half the year. Both
directions are tested, because they fail differently and only one of them is
noticeable in staging.

### D5 — `pgee_nudge_state` is its own table

docs/04a §C10 caps `pgee_due` at three nudges **ever** per assessment cycle. That
count has to survive notification pruning, so it cannot be derived from the
`notifications` table. The row carries a CHECK constraint at three, so even an
application bug cannot send a fourth.

### D6 — `dedupe_key` is NOT NULL, unlike docs/02 §8

docs/02 declares it `text UNIQUE`, which is nullable — and a nullable unique
column admits any number of NULL rows. The dedupe guarantee would be vacuous for
exactly the jobs that forgot to set a key. Every send path builds one through
`policy.dedupe_key`, so NOT NULL costs nothing and closes the hole.

### D7 — Escalation acknowledgements bypass both the cap and quiet hours

A human replying to a worried parent is not marketing and does not wait for
morning. It is the only kind that bypasses either.

### D8 — The cron schedule is data, not nine decorated functions

Cadences in docs/04a are stated in Africa/Cairo local time. Keeping the schedule
as data puts the local-to-UTC conversion in one tested function instead of nine
hand-written constants that each drift by an hour twice a year.

## Consequences

The database-level guarantees — the unique index refusing a duplicate, the
CHECK refusing a fourth nudge — are asserted against the DDL text, not against
Postgres. That is a weaker claim and it is stated as such in the test's
docstring. BLOCKED.md #1.
