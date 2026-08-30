# ADR 014 — Caregiver app, and a contrast defect in the design tokens

- **Status:** accepted, with gates open
- **Date:** 2026-08-29
- **Component:** P12 — C12 caregiver web app
- **Context docs:** `docs/04e` §C12 · `docs/06` (entire) · `docs/05` · `docs/10` T12

## Decisions

### D1 — The invariants live in TypeScript modules, not only in Playwright specs

Playwright has never run here: no browser binary is installed and CI has never
executed a job. A suite that has never run is not evidence, so everything that
*can* be checked without a browser is checked without one, in `src/lib/*.ts`
with Vitest: contrast over the shipped stylesheet, the touch-target arithmetic,
the prompt ladder, the monotonic progress range, the outbox, the console role
matrix. 87 tests, all passing.

The Playwright specs are written and every file opens with a NEVER EXECUTED
banner. → PROGRESS.md

### D2 — The progress range is clamped in one place

docs/04e §C12 requires a range that never widens. The engine's estimate
legitimately moves in both directions — the assessment is adaptive — so `narrow()`
takes the estimate and refuses to raise the ceiling. The engine's real estimate
still goes to telemetry; only the *display* is clamped, so a persistently
under-estimating engine shows up in the data rather than being hidden.

Proved over adversarial input: a sequence where every estimate tries to widen
still renders monotonically.

### D3 — The API never sends caregiver-facing Arabic

Both `domain/views.py` and `lib/progress-range.ts` emit **copy keys**. A rendered
Arabic sentence from the API would bypass the banned-terms lint that runs over
the i18n bundle — which is the only thing standing between a parent and the word
"متأخر".

## The finding

### F1 — `globals.css` claimed 7:1 for every pair. It was not true.

The file carried the comment *"Every foreground/background pair meets ≥ 7:1
(WCAG AAA)"*. Measured against the shipped values:

| Token | On `--c-surface` | 4.5:1? | 3:1? |
|---|---|---|---|
| `--c-practising` `#c77e1f` | **3.26:1** | ✗ | ✓ |
| `--c-resting` `#7a8b86` | **3.58:1** | ✗ | ✓ |

Both are fine as the *fill* of a skill-map tile: WCAG 2.2 SC 1.4.11 asks 3:1 of
a non-text indicator, and they clear it. Neither is usable as *text*, and the
skill map wanted to render the state as a word.

**Resolution:** the pair list now distinguishes a `graphic` audience at 3:1 from
a `caregiver` audience at 4.5:1, and two text-safe tokens were added
(`--c-practising-text` `#7d4c0e` at 7.21:1, `--c-resting-text` `#4a5a55` at
7.28:1). `SkillMapGrid` renders the swatch from one and the label from the
other — which also satisfies WCAG 1.4.1, because state is now conveyed by shape
*and* word, never by colour alone.

The alternative — darkening `--c-practising` itself — would have put the token
out of step with docs/06 §2, which `tokens.test.ts` asserts against the
document. This way both stay true.

## Not built

Stated plainly rather than deferred quietly:

- **Storybook**, with an LTR and an RTL story per component (docs/06 §8). The
  requirement stands and is unmet.
- **The report screen** exists as components (`ReportSection`, `NormPanel`) but
  not as a wired route; the Playwright spec for it will fail until it is.
- **PWA / offline.** `next-pwa`, the app-shell precache and the install prompt
  after the second successful session are not implemented. The IndexedDB outbox
  that offline writes depend on *is* built and tested.
- **`REVIEWED-BY` in the locale file is empty**, and must stay empty until a
  native Egyptian Arabic speaker has read all of it. Every string in
  `ar-EG.json` is agent-drafted placeholder. → REVIEW-QUEUE
