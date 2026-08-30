# SANAD — FINAL IMPLEMENTATION REPORT

Written after the run recorded below, from a database rebuilt out of the
migrations. Every number here is copied from that run's output, not restated
from an earlier one.

---

## 1. DEMO STATUS

**SANAD DEMO READY**

`just demo-check` exits 0 and prints `SANAD DEMO READY`. Every gate passed:
formatting, lint, strict types, the banned-terms lint, the CI guards, the whole
backend suite against real PostgreSQL, the 100 %-branch-coverage gate on the
deterministic core, the web lint/type/unit gates, and the critical path walked
in a real browser against a live API and a live web app.

The demo runs with **AI OFF**, which is a supported mode rather than a degraded
one: every teaching decision has a deterministic twin, and the AI inspector says
`قواعد ثابتة` rather than presenting a rule as a model. Live-provider
verification is externally blocked — see §14.

---

## 2. TEST RESULTS

| Suite | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Backend (`pytest -m "not live_ai"`, real Postgres + Redis) | **1264** | 0 | 0 |
| CI guards (`tools/guards/test_guards.py`) | **19** | 0 | 0 |
| Web unit (`vitest run`, 10 files) | **139** | 0 | 0 |
| Playwright `demo` project (1 setup + 5 critical-path) | **6** | 0 | 0 |
| **Total** | **1428** | **0** | **0** |

Nothing is skipped and nothing is xfailed. The `live_ai` marker is registered
and **no test carries it** — live-provider verification is reported as an
external blocker in §14 rather than hidden as a skipped test.

Static gates:

* `ruff format --check .` — 217 files already formatted
* `ruff check .` — All checks passed!
* `mypy --strict app` — Success: no issues found in 154 source files
* `banned_terms.py` — BANNED-TERMS PASS
* `coverage_gate.py` — **COVERAGE GATE PASS: 40 critical file(s) at 100 % branch coverage**
  (whole-repo line coverage 86 %; the gate is branch coverage on every
  `domain/` package and the guardrail layers, which is where the authoritative
  truth lives)

E2E timing: `demo-critical-path.spec.ts` 44.2 s, 6 passed in 52.9 s.

---

## 3. REQUIRED FEATURES

| # | Feature | Status |
|---|---|---|
| 1 | Authentication (OTP sign-in, refresh, logout, play-PIN) | **PASS** |
| 2 | Child persistence (create, list, archive, per-child rows) | **PASS** |
| 3 | Initial caregiver assessment (13 questions → priors) | **PASS** |
| 4 | Learner state creation from the assessment | **PASS** |
| 5 | AI Brain (per-activity teaching decision) | **PASS** (AI OFF verified; live provider blocked, §14) |
| 6 | Guardrails (schema / candidate-set / closed-enum, session limits) | **PASS** |
| 7 | Personalisation (four seeded children diverge measurably) | **PASS** |
| 8 | BKT / mastery (state machine + evidence test) | **PASS** |
| 9 | Activities (8 types, deterministic construction) | **PASS** |
| 10 | Drawing / tracing (real stroke scoring) | **PASS** |
| 11 | Speech (browser recogniser + server-side Arabic scoring) | **PASS** |
| 12 | Rewards (outcome-earned, idempotent, 6 achievements) | **PASS** |
| 13 | Session evaluation + caregiver report | **PASS** |
| 14 | AI Inspector (one card per real decision row) | **PASS** |
| 15 | Persistence (everything survives sign-out) | **PASS** |
| 16 | End-to-end critical path in a browser | **PASS** |

No feature is BLOCKED. One capability outside the demo scope is now refused
honestly rather than faked — see §13.

---

## 4. MIGRATIONS

One new migration this pass:

**`0014_tutor_runtime.py`** — creates six tables and extends one enum.

| Object | What it holds |
|---|---|
| `ALTER TYPE ai_decision_point ADD VALUE 'tutor_brain'` | the per-activity teaching decision point |
| `starting_assessments` | the 13-question caregiver form, one open per child (`starting_assessments_one_open` partial UNIQUE index) |
| `learner_profiles` | derived support level, comfortable minutes, area preferences |
| `tutor_activities` | one row per delivered activity: type, skill, difficulty, support, choice count, **server-only answer key**, state |
| `reward_events` | append-only stars, `reward_events_idempotency_key` UNIQUE |
| `achievements` | UNIQUE `(child_id, code)` — unlocked once per child |
| `session_summaries` | the computed facts and the narrative, with its source (`ai` / `template`) |

Constraints that carry rules rather than describing them: `activity_type` is a
CHECK over the closed set of eight types; `difficulty BETWEEN 1 AND 5`;
`comfortable_minutes BETWEEN 3 AND 20`; `tutor_activities_session_ordinal`
UNIQUE `(session_id, ordinal)`; `tutor_activities_one_pending` partial UNIQUE so
a session cannot have two activities in flight.

The migration deliberately does **not** widen `play_sessions.plan_source` — that
would mean dropping and re-adding a CHECK, which the destructive-migration guard
correctly refuses. The inspector derives `plan_source` from the decision rows
instead.

Migrations 0001–0013 are unchanged.

---

## 5. NEW / CHANGED ENDPOINTS

**New — the tutor loop** (`app/modules/tutor/router.py`):

| Method | Path |
|---|---|
| POST | `/tutor/sessions` |
| POST | `/tutor/sessions/{session_id}/next` |
| POST | `/tutor/sessions/{session_id}/respond` |
| POST | `/tutor/sessions/{session_id}/end` |
| GET | `/tutor/sessions/{session_id}/report` |
| GET | `/tutor/sessions/{session_id}/inspector` |
| GET | `/children/{child_id}/sessions` |
| GET | `/children/{child_id}/rewards` |

**New — the starting assessment** (`app/modules/starting/router.py`):

| Method | Path |
|---|---|
| POST | `/starting-assessments` |
| GET | `/starting-assessments/{assessment_id}` |
| POST | `/starting-assessments/{assessment_id}/answers` |
| POST | `/starting-assessments/{assessment_id}/finalise` |
| GET | `/children/{child_id}/starting-assessment` |

**Changed:**

* `GET /me` now returns each child's real `display_name` (it returned `""`).
* `GET /auth/otp/latest` — new, `include_in_schema=False`, and served **only**
  when the environment is not `production` **and** the null SMS provider is
  configured. It 404s otherwise. It exists so the runbook does not depend on
  reading the API's console.
* `POST /children/{id}/export` and `DELETE /children/{id}?erase=true` now return
  **503 with the reason** instead of 202 with a job id. See §13.
* The whole client-authoritative `/api/play/*` path in the web app was deleted,
  along with `manifest.ts`, `play-session.ts` and `play-client.ts`.

---

## 6. AI BRAIN

The brain **selects**; deterministic code **decides truth**.

* Decision point `tutor_brain`, one call per activity, through the single
  gateway choke point in `app/ai/gateway.py` (effort `low`, 512 max tokens).
* It receives `LearnerEvidence`: the last 20 attempts, per-modality accuracy
  computed from `split_part(activity_code, ':', 1)` over the four teaching
  modalities, recent activity types, and the candidate skills the deterministic
  scheduler already selected.
* It returns a `BrainDecision`: skill **from the candidate set**, activity type
  from `ActivityType`, difficulty 1–5, support level, whether to demonstrate,
  and a bounded Arabic explanation. Every field is a closed enum or an index
  into a set the server built.
* Guardrail chain for this point: `SchemaLayer`, `CandidateSetLayer`,
  `ClosedEnumLayer` — enforced by `tools/guards/required_guardrail_layer.py`,
  which now reports **PASS** across eleven decision points.
* It **cannot** compute mastery, invent an attempt, grant a star, bypass a
  prerequisite or consent, or write learner truth. Those are separate modules
  that never take model input.
* `propose()` never raises. No candidates, a refusal, invalid JSON, a timeout or
  no provider at all all return `Proposal(None, reason, "deterministic_fallback")`
  and the session continues. There is no configuration in which a provider
  outage stops a child's session.
* With AI OFF the fallback picks the same shape of decision from the same
  candidate set, and the inspector labels it `قواعد ثابتة` rather than
  pretending a rule was a model.

---

## 7. MASTERY

`app/modules/learning/domain/mastery.py`.

The state machine is `not_started → introduced → practising → mastered →
retained`, with `lapsed` reachable from `mastered`/`retained`. The caregiver
assessment can seed any state **except** `mastered` — a parent's opinion is a
prior, not evidence.

Two defects were found and fixed this pass, both documented in the module
docstring:

1. **The mastery guard was mathematically unreachable.** It used a Hoeffding
   bound with a union correction whose margin exceeded 1.0 for every attempt
   count the product can produce, so no child could ever be promoted. It is now
   an **anytime-valid sequential test**: a mixture likelihood-ratio martingale
   over `ALTERNATIVES = (0.60, 0.70, 0.80, 0.90, 0.95)`, compared against
   `log(1/ACCURACY_ALPHA)` with `ACCURACY_ALPHA = 1e-5` (Ville's inequality —
   valid at every stopping time, so peeking after each attempt is sound). Plus a
   hard `ACCURACY_FLOOR = 0.80` and `MIN_SCORED_ATTEMPTS = 12`.
   `MasteryDecision` now carries `evidence_log_ratio` and `evidence_threshold`
   so the caregiver console shows why, not just what.
2. **`apply_session` advanced every earlier skill one rung per answer.** It now
   takes `only=(skill_id, modality)` and folds evidence for the skill that was
   actually practised.

BKT priors come from the caregiver assessment (`BAND_PRIOR = 0.12 / 0.25 / 0.45
/ 0.65`) and `_prior(row)` seeds `BktState(p_known=row.p_prior)` — previously
every child started from the same constant. Prompt levels discount evidence: a
correct answer after a full model is not evidence of independent knowledge.

`test_mastery_matrix.py` (29 tests) covers the matrix; the two tests that had
encoded the broken Hoeffding boundary were **strengthened**, not deleted.

---

## 8. DRAWING

Real stroke geometry, no simulation. `app/modules/tutor/domain/drawing.py`.

Pipeline: canvas normalisation → moving-average smoothing (`SMOOTHING_WINDOW =
5`) → arc-length resampling at `SAMPLE_SPACING = 0.01` → bounded translation
search (`TRANSLATION_LIMIT = 0.06`, `TRANSLATION_STEP = 0.02`) → spatial-grid
nearest-neighbour matching at `TOLERANCE = 0.10`.

Score = `coverage × (1 − outside_ratio) × length_penalty`, with the low-side
length penalty **squared**. `PASS_THRESHOLD = 0.62`.

The two numbers the test file exists to hold apart, measured across **every**
reference glyph in `seeds/tracing.py` rather than one convenient letter:

```
highest-scoring negative   0.590
lowest-scoring positive    0.906
threshold                  0.62
```

Both fixes were measurements, not guesses: a half-drawn م passed at 0.68 under a
linear length penalty (م is a ring 0.14 across, so most of its reference sits
inside its own first half's tolerance) — squaring the penalty took it to 0.53.
Hand tremor inflated `length_ratio` fourfold until smoothing was added before
measurement. Performance: 0.42 s → 0.055 s per evaluation via the spatial grid.

54 tests in `test_drawing.py`. If a change closes the gap,
`test_the_threshold_separates_every_case` fails and names the case that moved.

The 18 reference paths are geometric approximations and are **watermarked as
placeholders** — see §14.

---

## 9. VOICE

The microphone is real. The browser's Web Speech API recogniser produces a
transcript and a confidence; the client feature-detects and falls back to typing
or caregiver confirmation where it is unavailable. There is no server-side ASR
provider configured (`asr_no_providers_configured` in the startup log) and none
is faked.

Scoring is server-side and deterministic: Arabic normalisation → grapheme-to-
phoneme → weighted Levenshtein over the phoneme inventory.

The honest handling of uncertainty, in `evaluate.py`:

* `MIN_SPEECH_CONFIDENCE = 0.35`, applied **only when a positive confidence was
  actually reported**. A recogniser that reports no confidence is not punished
  for it.
* Below it the outcome is `UNCERTAIN`, which maps to `no_response` — "try
  again", **not** "wrong". A recogniser that could not make out a child with an
  atypical speech profile must never be recorded as that child failing.
* **Caregiver confirmation is checked first and is final.** A caregiver saying
  the child said it beats the recogniser, and produces `caregiver_confirmed`.

`test_voice_scoring.py` (104 tests), `test_voice_service.py` (39),
`test_voice_render.py` (31).

---

## 10. REWARDS

`app/modules/tutor/domain/rewards.py`. Pure, deterministic, and the only thing
that grants a star.

A star is earned by an **outcome**, never by an interaction — tapping is worth
nothing.

| Event | Stars |
|---|---:|
| Independent correct | 2 |
| Supported correct | 1 |
| Correct after a full model | 0 |
| Session completed (any accuracy) | 3 |

`full_model` pays zero on purpose: otherwise the fastest route to a full sticker
chart is to wait for the prompt ladder to answer for you. Session completion
pays for *finishing*, not for accuracy.

Idempotency is structural, not remembered: `attempt:{attempt_key}` and
`session_complete:{session_id}` against a UNIQUE index with `ON CONFLICT DO
NOTHING`. Totals are `SUM` reads, never counters. A double-tap, a retried POST
and an outbox draining after a dropped connection all produce one star.

Six achievements (`first_session`, `five_in_a_row`, `first_word_spoken`,
`first_letter_traced`, `skill_mastered`, `three_day_streak`), each with UNIQUE
`(child_id, code)`. `achievements_earned()` returns what is **true**; deciding
what is **new** is the repository's job, because "new" is a fact about the
database.

---

## 11. PERSISTENCE

Everything the demo shows is a row.

* No `localStorage` anywhere in the required path. The client-authoritative
  play path (`manifest.ts`, `play-session.ts`, `play-client.ts`,
  `src/components/play/*`, `src/app/api/play/*`) was **deleted**, not disabled.
* Sessions, activities (with the answer key server-side only), attempts,
  mastery state, mastery events, AI decisions, rewards, achievements and session
  summaries are all persisted and all read back.
* The client is never sent the answer — `Presentation` structurally cannot
  contain it, and `test_the_client_is_never_sent_the_answer` asserts it over the
  wire.
* Idempotency: `tutor_activities_session_ordinal`,
  `tutor_activities_one_pending`, `reward_events_idempotency_key`,
  `achievements (child_id, code)`, `starting_assessments_one_open`.
* Verified end-to-end by the browser test "rewards, the report and the inspector
  survive a sign-out".

---

## 12. E2E

`apps/web/e2e/demo-critical-path.spec.ts`, Playwright `demo` project, run
against a live API and a live web app. **6 passed (52.9 s)** — one storage-state
setup plus five tests:

1. **existing children have different learner states** — the four seeded
   children differ in stars, achievements and assessed band, and every number is
   read from that child's own rows.
2. **a session is server-driven and never celebrates a wrong answer** — a wrong
   answer produces no celebration, no star, and a next activity at lower
   difficulty with support raised.
3. **a poor drawing fails and a faithful one passes** — a dot fails; a faithful
   trace passes. Real strokes through the real scorer.
4. **a new child is assessed, gets a learner state, and plays** — the thirteen
   questions write that child's own priors, and the very next session is built
   from them.
5. **rewards, the report and the inspector survive a sign-out** — sign out, sign
   back in, everything is still there.

The suite runs behind a storage-state setup project so the whole run costs two
sign-ins, and `demo-check` clears the OTP rate-limit counter first
(`RATE_OTP_PER_PHONE_PER_HOUR = 3`) so a second run inside an hour cannot fail
for a reason that has nothing to do with the product.

---

## 13. REMAINING TODO / FIXME

The full sweep for `TODO`, `FIXME`, `HACK`, `NOT_IMPLEMENTED`,
`NotImplementedError`, `stub`, `fake` and `mock` across `services/api/app`,
`services/api/seeds`, `apps/web/src` and `tools` returns **six** occurrences.
None is in the demo path.

| Location | What | Why it stays |
|---|---|---|
| `identity/sms.py` ×2 | `TwilioSms.send` / `LocalAggregatorSms.send` raise `NotImplementedError` | They need credentials. They raise rather than silently pretending to send — a provider that claims success without sending is worse than one that fails. `SANAD_SMS_PROVIDER=null` is the working demo path. |
| `tools/guards/prompt_cache_hit.py` | `TODO(Gate 4)` | The structural half of the guard **passes**; the empirical half needs a real recorded double call against a live provider. Deliberately not faked — it reports `GUARD SKIP` with that exact reason. |
| `tools/guards/_common.py` | prose | Explains that a guard's SKIP names the P-prompt that resolves it. Not code. |
| `children/router.py` ×2 | `TODO(P10)`, inside the comments explaining the 503s below | The worker pool is a separate module. |

Searches for `stub` / `fake` / `mock` in shipped code return five hits, **all of
them prose asserting the absence of a stub** ("Do not stub a passing result
here", "Absence is a documented mode, never a stub"). There are no stubbed
implementations.

**One thing changed as a result of this sweep.** `POST /children/{id}/export`
and `DELETE /children/{id}?erase=true` returned **202 ACCEPTED with a freshly
minted job id** for jobs that no worker exists to run. A caregiver was told
their data-export or erasure request had been accepted when nothing would ever
act on it — a false success about a data-subject request, which is the one place
it is least acceptable. Both now raise `ServiceUnavailable` with the reason.
Archiving (`DELETE` without `?erase=true`) is real and keeps its 202.
`test_export_and_erasure_refuse_rather_than_returning_a_job_that_will_never_run`
locks it.

`PLACEHOLDER` appears widely and on purpose: it is the content-provenance
watermark on agent-written Arabic, the mechanically generated curriculum, the
item bank, the tracing reference paths and the phoneme mappings. Each one
surfaces to the UI as a visible watermark and points at REVIEW-QUEUE.md. That is
§14, not unfinished code.

---

## 14. HUMAN VALIDATION REQUIRED

These cannot be resolved from inside the repository. Every one of them is
watermarked in the code **and** rendered to the screen, so nothing here can be
mistaken for reviewed content.

| # | What | Who is needed |
|---|---|---|
| 1 | All Arabic copy — activity instructions, achievement labels, the fallback narrative, the character's lines, the 13 assessment questions | A native Egyptian-Arabic speaker, ideally one who works with children |
| 2 | The 13-question starting assessment as an instrument | A clinician. `WATERMARK = "PLACEHOLDER — not reviewed by a clinician or a native speaker"` is rendered by `StartingAssessment.tsx` |
| 3 | The 18 tracing reference paths — shape, stroke order, stroke direction | A handwriting or occupational-therapy specialist. → REVIEW-QUEUE #14 |
| 4 | The 88-skill curriculum: ordering, difficulty, transliterations, alt text | A curriculum specialist. Ships as `PLACEHOLDER-NOT-REVIEWED:{code}` |
| 5 | The item bank | A clinician — `WATERMARK = "PLACEHOLDER — NOT FOR CLINICAL USE"` |
| 6 | Phoneme mappings and vowelised labels | A speech therapist |
| 7 | Mastery thresholds (`ACCURACY_FLOOR`, `MIN_SCORED_ATTEMPTS`, `ALTERNATIVES`) as clinical policy | The maths is sound and tested; whether 0.80 over 12 attempts is the right bar for this population is a clinical judgement |
| 8 | The drawing pass threshold (0.62) against real children's tracing | The corpus separation is measured; the bar is a judgement |

**Externally blocked, not incomplete:**

* **Live AI provider verification.** No `ANTHROPIC_API_KEY` / `SANAD_GROQ_API_KEY`
  is available in this environment, and none was hardcoded or committed. The
  gateway, the guardrail chain, the fallback and the inspector are all exercised
  with AI OFF, which is a first-class mode. To verify live: set `SANAD_AI_LIVE=1`
  and a provider key in `.env` (gitignored) and restart the API. The one gate
  that needs a live call, `prompt_cache_hit`, reports `GUARD SKIP` with that
  reason rather than a fabricated pass.
* **Docker → resolved.** Docker Desktop's service could not be started without
  administrator rights on the build machine. PostgreSQL 16 + pgvector, Redis and
  MinIO were provisioned in WSL2 on **the same ports `.env` already names**, so
  no configuration differs. Documented in DEMO-RUNBOOK.md §2.

---

## 15. RUN COMMAND

```bash
just db-reset && just up
```

`db-reset` drops the schema, re-applies every migration, loads the 88-skill
curriculum and creates the demo family. It refuses when `SANAD_ENVIRONMENT` is
`production` and when the database is not on localhost. `up` starts both
processes in one colour-coded stream.

Sign in at <http://localhost:3000/onboarding> as **`01000000000`**. No SMS
provider is configured, so the code is printed by the API; if its console is not
in front of you:

```bash
curl "http://localhost:8000/auth/otp/latest?phone_e164=%2B201000000000"
```

The nine-step demo order is DEMO-RUNBOOK.md §6. The short version: four children
with visibly different sessions, سارة opens on a tracing activity because months
of accurate tracing make `productive` her strongest measured modality, a wrong
answer earns nothing and lowers the next difficulty, and "ليه سند عمل كده؟" shows
one card per real teaching decision.

---

## 16. DEMO CHECK

```bash
just demo-check
```

One command. Rebuilds the database from the migrations, seeds it, starts the API
and the web app if they are not already up, clears the OTP rate limiter, then
runs every gate in order: `format`, `lint`, `types`, `banned-terms`, `guards`,
`api-tests`, `coverage`, `web-lint`, `web-types`, `web-tests`, `e2e`. It ends
with `SANAD DEMO READY` or `SANAD DEMO NOT READY` **and the exact failing
gates**.

```bash
just demo-check --skip-e2e
```

Everything except the browser gate, for a fast inner loop. It can **never** print
READY — a run that did not exercise the critical path does not get to say the
demo is ready.

Last run, complete output tail:

```
=== e2e =========================================================
$ pnpm exec playwright test --project=demo --reporter=line
  6 passed (52.9s)

====================================================================
SANAD DEMO READY
```

---

## Deliverables

| File | What |
|---|---|
| `DEMO-GAP-ANALYSIS.md` | What was missing, and the three structural gaps |
| `DEMO-IMPLEMENTATION-STATUS.md` | 23 numbered requirements, each with evidence |
| `DEMO-RUNBOOK.md` | Exact commands, including the no-Docker path |
| `FINAL-IMPLEMENTATION-REPORT.md` | This file |
| `REVIEW-QUEUE.md` | #14–#18 added — everything needing a human |
| `services/api/migrations/versions/0014_tutor_runtime.py` | The migration |
| `services/api/seeds/demo.py`, `demo_loader.py` | Four children, built by the real services |
| `tools/dev/demo_check.py`, `tools/dev/reset_db.py` | The one command, and the reset |
