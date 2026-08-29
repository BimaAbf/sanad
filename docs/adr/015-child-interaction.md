# ADR 015 — Child play app: a document disagreement, and no failure state

- **Status:** accepted, with gates open
- **Date:** 2026-08-29
- **Component:** P13 — C13 child play app
- **Context docs:** `docs/04e` §C13 · `docs/06` §4 · `docs/04c` · `docs/04d` · `docs/10` T13

## The disagreement

**docs/04e §C13 says touch targets are ≥ 80 × 80 px with a ≥ 16 px gap.
docs/06 §5 and docs/09 P13 say ≥ 88 × 88 px with ≥ 20 px gaps.**

The stricter pair is used. Taking the larger value cannot violate either
document, and the acceptance criterion CI actually asserts (docs/09 P13) names
88. Recorded at the constant in `lib/interaction.ts` rather than resolved
silently, because a future reader comparing the code to docs/04e will otherwise
think the code is wrong.

One consequence worth knowing before it is discovered in a browser: **four 88 px
targets with 20 px gaps do not fit across a 320 px viewport.** Two do, with 124
px to spare. That is why a 4-choice activity is a 2×2 grid and not a row, and
there is a test asserting the arithmetic so nobody re-derives it under time
pressure.

## Decisions

### D1 — Every rule is a constant with a test, not a number in JSX

docs/09 P13 says "this is the component where the accessibility requirements ARE
the functional requirements". So the 88 px, the 5-word limit, the 3 Hz ceiling,
the 400 ms tap tolerance, the 800 ms calm and the retuned VAD parameters live in
`lib/interaction.ts` and are asserted against the documents. A number written
inline in a component is a number a refactor changes without anyone noticing.

### D2 — There is no failure state, so there is no styling for one

`ChoiceCard` has no disabled state and no error state. Nothing a child can tap
is wrong. `NourCharacter` has exactly four states and none of them is sad — a
character with a disappointed face is a failure state wearing a smile.

### D3 — Write to the outbox first, then post

Not the other way round. Post-then-write means a request that succeeded on the
server but never returned gets replayed as a *second* attempt and the child is
recorded as having answered twice. The acceptance criterion — a 30-second
dropout loses zero attempts and creates zero duplicates — is satisfiable only in
this order.

The idempotency key is `sessionId:activityId:attemptNo`, deterministic. A random
UUID would be regenerated on a component remount and the same answer would reach
the server twice under two keys, which is the one duplicate the server cannot
detect.

An acknowledged record is *kept* for five minutes rather than deleted, so that a
remount that re-enqueues finds the key and does nothing.

### D4 — A `duplicate` response is a success

The server already has the attempt. Treating it as a failure would retry
forever.

### D5 — The ladder is a pure function of elapsed time

`rungAt(elapsed, waitMs)` never returns null. A child who sits for ten minutes is
at `full_model`, which auto-selects, which is a success. There is no state in
which doing nothing is invalid, because doing nothing is a valid way to answer.

### D6 — A tap on a *different* target always counts

The 400 ms tolerance suppresses a repeat tap on the same card — tremor,
perseveration. A tap on a different card is a child changing their mind, and it
is not our place to refuse it.

### D7 — A plain `<img>`, not `next/image`

The manifest supplies absolute R2/CDN URLs already preloaded into the Cache API.
Routing them through the image optimiser would re-fetch them at render time and
defeat the offline guarantee.

### D8 — The animation is one keyframe at 1.5 Hz

Half the 3 Hz ceiling docs/06 §4 sets for seizure risk, which is elevated in
this population. The opacity range is narrow on purpose: a hint that draws the
eye, not a flash that demands it. The `prefers-reduced-motion` block in
`globals.css` disables it entirely.

## Not built

- **Zustand store, Cache API preload, Background Sync, wake-lock beyond the
  basic request, PIN-gated exit, fullscreen kiosk behaviour.** The page holds
  local state and an in-memory outbox; the IndexedDB implementation of
  `OutboxStorage` is not written, only its interface and its in-memory sibling.
- **Activity renderers** for `match_pair`, `sort_category` and `story_moment`.
  Only `listen_point` and the expressive path render.
- **Real-device audio.** docs/10 T13 §23 requires iOS Safari on hardware. The
  spec is `test.skip` with the reason stated, not approximated on an emulator.
  → REVIEW-QUEUE, alongside the OT accessibility review.
