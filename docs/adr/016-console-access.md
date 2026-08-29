# ADR 016 — Console access control

- **Status:** accepted, with gates open
- **Date:** 2026-08-29
- **Component:** P14 — C14 clinician / admin console
- **Context docs:** `docs/04e` §C14 · `docs/05` §7 · `docs/10` T14

## Decisions

### D1 — The role matrix is a data table, in one file

`lib/console-access.ts` holds four roles against nine routes. The API enforces
it, the console renders its navigation from it, and the test walks it
exhaustively — every role against every route, both directions.

The reason it is data rather than a set of `if` statements is that docs/09 P14
asks for the expected answer to exist *independently of the code that enforces
it*. A permissions test whose expectation is derived from the enforcement code
proves only that the code agrees with itself.

### D2 — Deny by default

`canAccess` returns true only for a route a role explicitly lists. A route added
next year is forbidden to every non-admin role until someone grants it on
purpose. Tested against a route name that is not in the table at all.

### D3 — `CHILD_DATA_ROUTES` is named once

docs/09 P14's criterion is "a content_editor session cannot reach any child
data". Naming the set of child-data routes explicitly means that adding a route
which exposes child data is one deliberate edit here, rather than an oversight
spread across four role lists. `childDataLeaks()` then checks the invariant
structurally, so a future route added to `ops` cannot slip past.

### D4 — `ops` does not get the escalation queue

This is the least obvious entry in the table. Escalation *SLA* is an ops
concern, but the *contents* of an escalation are a child's own words. Ops sees
the timing through `cost`, `flags` and the AI explorers — which carry no
identifiers, because everything in `ai_calls` was pseudonymised before it left
the gateway — and not the queue itself.

### D5 — MFA is checked server-side; the layout only makes it visible

`(console)/layout.tsx` renders a gate when the session lacks MFA. That is not
the enforcement — a client-side gate is a suggestion. The API and the edge
enforce it; the layout exists so that an unauthenticated session renders as
unauthenticated rather than as an empty console.

## Not built

- **The auth realm itself.** TOTP enrolment and verification, the IP allow-list
  and the 30-minute idle timeout are specified and unimplemented. The console
  currently renders its MFA gate unconditionally, because `currentSession()`
  returns null.
- **The editors.** Item bank, content, report review and the flag panel are
  route stubs that state their rule in the page; none writes anything.
- **The audit trail.** `audit_log` has no migration in this branch. docs/10 T14
  §4 requires proving via raw SQL that it rejects UPDATE and DELETE, which needs
  Postgres — blocked (BLOCKED.md #1). The Playwright spec for it is `test.skip`
  with the reason stated.
- **The 30-second flag propagation** (docs/10 T14 §5) needs a running API and a
  real cache. Also `test.skip`: a test that toggles a flag in a mock and asserts
  the mock changed measures nothing about the guarantee.
