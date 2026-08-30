# DEMO-IMPLEMENTATION-STATUS

`[ ]` not started · `[~]` in progress · `[x]` implemented **and tested** ·
`[!]` blocked · `[H]` human validation required

Nothing is `[x]` because code exists. Every `[x]` names the tests that were run
and what they returned.

_Gate command: `just demo-check`. Last full run recorded at the bottom._

---

## 1. Authentication `[x]`

**Implementation.** Pre-existing: OTP → RS256 access token → refresh rotation,
`caregiver_child` role matrix, `require_child_access` plus the CI guard that
fails the build on a `{child_id}` route without it.

**Changed this pass.**
- `identity/sms.py` — `NullSms.send` printed the Arabic OTP message to stdout,
  which raised `UnicodeEncodeError` on a Windows cp1252 console **inside the
  request**. Every sign-in on Windows was a 500 for a message that had in fact
  been sent. Now prints the ASCII code only, and falls back to a byte write.
- The same line then filtered on `str.isdigit()`, which is true for Arabic-Indic
  digits, so the printed code picked up the `٥` from "صالح ٥ دقايق" and was one
  character too long.
- `identity/repository.py` — `/me` returned `display_name: ""` for every child
  ("filled by the children module once it exists"; it has existed since 0003).
  Added `list_links_with_names`. The child picker was three unnamed cards.
- `GET /auth/otp/latest` — development-only OTP readback, gated on
  `environment != production` **and** the null SMS provider, `include_in_schema
  =False`. It exists so the end-to-end test can sign in through the real form
  rather than through a bypass.

**Tests.** `tests/unit/test_identity_router.py` (33), `test_identity_service.py`,
`test_identity_units.py` — including a test that the printed line is ASCII and
equals the code, and three for the dev route (returns it, 404 for an unknown
number, 404 when a real SMS provider is configured).
`tests/integration/test_tutor_loop.py::test_a_caregiver_cannot_reach_another_familys_child`
walks all eight tutor routes with the wrong token and asserts 403/404 on each,
then asserts nothing was written.

---

## 2. Persistent child profiles `[x]`

**Implementation.** Pre-existing tables; new caregiver-facing picker at
`/children` showing each child's stars, achievements and assessed bands, and a
server action that sets the active-child cookie before `/play`.

`/onboarding` now opens on the child step when the caregiver is already signed
in — adding a second child previously demanded a fresh OTP, and the limit is
three an hour, so it could simply refuse.

**Tests.** E2E `existing children have different learner states` — the four
seeded children addressed by id, each named, star totals not all equal, and four
distinct band sets.

---

## 3. Initial caregiver assessment `[x]` `[H]`

**Implementation.** New module `app/modules/starting/`:
- `domain/form.py` — thirteen questions covering the ten areas the specification
  names, each with the concrete example docs/04e §C12 requires; derivation to
  per-area bands, per-category skill seeds with BKT priors, and a support
  profile (support level, modality, demonstration, duration, speech comfort).
- `repository.py`, `service.py`, `router.py`, `schemas.py`.
- Migration `0014`: `starting_assessments` with a partial unique index making
  one open assessment per child, `learner_profiles`.

`shapes` derives no prior — the curriculum has no shapes. The answer is stored
and the gap is reported in the response as `unmapped_areas`. → REVIEW-QUEUE #15

**Defect found and fixed.** React's development strict mode runs the mount
effect twice, so two `POST /starting-assessments` raced between the
"is there an open one" check and the INSERT, and the loser got a 500 — roughly
half the time a caregiver opened the form. The unique index is what made it
safe; the service now catches the violation and resumes the assessment the
winner created.

**Tests.** `tests/unit/test_starting_form.py` (24) at 100 % branch coverage on
`domain/form.py`, including the top band being below the mastery threshold and
every seeded state being `introduced` or `practising`.
Integration: `a new child gets an assessment, a learner state and a first
decision` (priors present on every seeded row), and
`the caregiver assessment can never produce mastery`.

**Human validation.** The questions, the Arabic, and every constant in the
derivation. → REVIEW-QUEUE #15

---

## 4. Initial learner-state creation `[x]`

**Implementation.** `starting/service.finalise` writes `skill_states` rows with
`p_prior` set per area band, `due_at = now`, and `ON CONFLICT DO NOTHING` — a
form filled in after a child has played never overwrites what they did.

Migration `0014` adds `skill_states.p_prior`, and
`learning/service.py` now seeds the BKT fold from it instead of the population
default. That is what makes the assessment change anything: the fold recomputes
`p_known` from the whole attempt history on every run, so a prior that was not
stored would have been erased by the first attempt.

**Tests.** Integration: `skills_seeded > 0` and every seeded row carries a
prior; `test_a_strong_answer_opens_more_skills_at_a_higher_prior_than_a_weak_one`.

---

## 5. AI Brain / the runtime loop `[x]`

**Implementation.** New module `app/modules/tutor/`. `POST
/tutor/sessions/{id}/next` assembles evidence from Postgres (skill state,
`p_known`, recent attempts and their prompt levels, per-modality accuracy,
support effectiveness, recent strategies and activity types, the learner
profile, session minutes, fatigue), calls the gateway at decision point
`tutor_brain`, guards the result, builds the activity, and persists the decision
to `ai_decisions` with the resulting activity.

Before this pass `tutor_ai/loop.py::run_step` had **no callers**, `ai_decisions`
and `activity_outcomes` (migration 0013) were written by nothing, and the
running system was `SELECT … ORDER BY intro_order LIMIT n`.

**Defects found and fixed on the way.**
- `tutor_ai/audit.py` — `UUID(row.id)` on an asyncpg `pgproto.UUID` raises. The
  module had never been executed.
- `tutor_ai/brain.py` named four activity types of which the runtime implements
  one, so the deterministic fallback tripped its own
  `unsupported_activity_corrected` guardrail on **every** decision.
- The fallback's difficulty was `1 if struggling else 2`, making levels 3–5,
  the four-choice activities and half of `CHOICES_FOR_DIFFICULTY` unreachable
  whenever the model was not answering — which is the default configuration.
- `modality_accuracy` was keyed on the `modality` ENUM
  (receptive/expressive/productive) while the brain reasons in teaching terms
  (visual/audio/expressive/productive), so `visual_strong` was permanently
  false. Pointing at a picture and listening to a word are both `receptive`.

**AI ON / AI OFF.** Both work. With `SANAD_AI_LIVE=0` (the default) the gateway
makes no network call and every decision is the deterministic one, recorded as
`deterministic_fallback` and shown as such in the inspector. Every gateway
outcome — no fixture, timeout, refusal, schema error, provider error, budget,
flag off — returns `None` from `brain_call.propose` and the session continues.

**Tests.** `test_tutor_brain.py`, `test_personalisation.py` (29),
`test_tutor_domain.py` (81), integration `test_tutor_loop.py` (20).
Live-provider verification is **externally blocked**: no API key on this
machine. → §Blocked

---

## 6. Guardrails `[x]`

**Implementation.** Two layers. `tutor_ai/brain.guard_decision` (pre-existing,
100 % branch) covers unknown skill, unsupported modality, unsupported activity
type, a new skill being advanced past, fatigue, and a repeated-strategy streak.
New `tutor/domain/guardrails.py` covers the rest of the specification's list:
prerequisites, difficulty jumps (`MAX_DIFFICULTY_JUMP`, which was declared and
never used), the session activity cap, consecutive repetition, a category that
cannot support the chosen type, a microphone without consent, a tracing
activity with no reference path, and the hardest-difficulty-with-least-support
combination.

Registered at `chain.REQUIRED_LAYERS["tutor_brain"] = [SchemaLayer,
CandidateSetLayer, ClosedEnumLayer]`, in the CI guard's table, and in the
guard's control fixture.

**AI cannot grant mastery** is structural — `BrainDecision` has no mastery
field — and asserted three ways: a schema test, `next_state`'s behaviour under
every state, and the `ai_cannot_grant` CHECK exercised against real Postgres.

**Tests.** `test_tutor_domain.py::TestGuardrails` (12) and `TestPromptFloor` (5),
100 % branch on `domain/guardrails.py`; `test_guardrails.py` registry test.

---

## 7. Personalisation `[x]`

**Implementation.** Falls out of §5. Four seeded children with genuinely
different evidence produce four different sessions — verified against the live
API:

| child | first activities |
|---|---|
| أحمد | `count_objects:num_1`, `select_picture:letter_alef`, `match_pair:color_red` |
| ليلى | `speak_word:color_red`, `match_pair:color_blue`, `count_objects:num_2` |
| عمر | `select_picture:color_blue` (high support), `trace_letter:letter_alef` |
| سارة | `trace_letter:letter_alef` |

**Defects found.** Two session-shape bugs, both visible only by running whole
sessions:
- the session marched through fourteen different skills and repeated none,
  because the assessment opens twenty-five as due and an answered one drops to
  the back. Capped at `MAX_SKILLS_PER_SESSION = 4`.
- with the cap, the session then locked onto ONE skill, because the deterministic
  fallback takes the head of the candidate list and the head never changed. The
  session's own skills are now ordered least-recently-practised first.

**Tests.** `test_personalisation.py` — 22 numbered scenarios plus three property
tests, and **no child's name anywhere in the file**: every scenario is an
evidence bundle, so a `if child.name == …` shortcut would not make a single one
of them pass. Integration:
`test_the_demo_children_get_measurably_different_sessions` asserts four distinct
stored profiles, at least three distinct first-activity signatures, differing
star totals, and that at least one child is offered tracing first.

---

## 8. BKT / mastery `[x]` `[H]`

**The defect.** The accuracy guard used a Hoeffding margin with the confidence
divided across looks, capped to a 40-attempt window. At twenty flawless
independent two-choice attempts it demanded accuracy
`0.5 + sqrt(ln(20/1e-5)/40) = 1.102`, which is unreachable; and the window put a
floor under the margin, so the requirement stayed above 0.97 at two choices
**forever**. Half the requirement was false: random guessing was excluded, and so
was everybody else.

**The fix.** An anytime-valid mixture likelihood-ratio martingale (Ville's
inequality) over the whole scored history, plus a lifetime accuracy floor. Both
in `learning/domain/mastery.py` with the derivation in the module docstring.

Measured after the change:

| behaviour | outcome |
|---|---|
| flawless independent, 2 / 3 / 4 choices | mastered at attempt 20 / 13 / 13 |
| 90 % at 2 choices | mastered |
| 70 % at 2 choices, 500 attempts | never — clears the martingale, fails the floor |
| random tapping, 40 seeds × 500 attempts × 3 choice counts | never |
| exactly 50/50, 400 attempts | never |
| ten errors then flawless | recovers at attempt 57 |
| 200 correct answers at `full_model` | never; evidence is exactly zero |
| every answer at `gestural` | never; independent-ratio unmet |

**Tests.** `test_mastery_matrix.py` (29 new) covering every behaviour the
specification lists; `test_bkt_random_tapper.py` updated (the two assertions
that encoded the old broken boundary now encode the measured one);
`test_learning_scheduling_candidates.py`. 100 % branch on `domain/mastery.py`.

**Human validation.** ALPHA, the alternative mixture, the accuracy floor and the
minimum-attempt count are engineering choices that decide who is told their
child has mastered something. → REVIEW-QUEUE #17

---

## 9. Activities `[x]`

**Implementation.** `tutor/domain/contract.py` — one schema, eight types:
selection, counting, matching, listening, speaking, sorting, sequence, tracing.
`Presentation` is what the client receives and **never contains the answer**;
`AnswerKey` is a separate column. `tutor/domain/build.py` constructs both,
deterministically from `(session_id, ordinal)`.

Frontend: one renderer per type in `components/tutor/activities.tsx`, all
driven by `ActivityView`, all reading `enabled` from the state machine.

**Tests.** `test_tutor_domain.py::TestBuilder` — including a parametrised test
over **every** type that serialises the presentation and asserts the answer is
not in it. Integration `test_the_client_is_never_sent_the_answer` does the same
over the real HTTP response.

---

## 10. Authoritative evaluation `[x]`

**Implementation.** `tutor/domain/evaluate.py`. One function, one `match` over
the eight types, reading the answer key from the row the server wrote.
`POST /tutor/sessions/{id}/respond` is the only path from a response to a
result. A malformed response is a 422, never a stored `incorrect` — a client
defect must not become a line in a child's record.

The client-side half: `lib/activity-machine.ts` is a tagged union in which a
celebration is derivable in exactly one state and reads `result.correct` from
the server.

**Tests.** `TestEvaluation` (17), `TestMalformedResponses` (9),
`activity-machine.test.ts` (18) — including an exhaustive walk of every event
against every state reachable in three steps, asserting no contradictory state
exists. Integration `test_an_incorrect_answer_is_incorrect_and_earns_nothing`.
E2E asserts no celebration element exists on a wrong answer.

---

## 11. Drawing / tracing `[x]` `[H]`

**Implementation.** `tutor/domain/drawing.py` — normalise by the canvas the
child drew on, smooth, resample, bounded translation search, four metrics
(coverage, mean distance, outside ratio, length ratio), one score as their
**product**, one threshold. Scale is deliberately not fitted: fitting it makes a
4 mm dot a perfect ب. `seeds/tracing.py` holds eighteen reference paths.
`components/tutor/TracingPad.tsx` is a real canvas with pointer capture.

**Measured**, over every glyph × seven negatives × six positives: highest
negative **0.590**, lowest positive **0.906**, threshold **0.62**.

Two findings the sweep produced: a moving-average smoothing window is required
or a tremor multiplies the path length and fails a child for their hands; and
the short-length penalty must be squared or a half-drawn م passes at 0.68.

Performance: 0.055 s per evaluation after replacing the O(n·m) nearest-neighbour
scan with a tolerance-sized spatial grid — it was 0.42 s, which is time a child
spends waiting.

**Tests.** `test_drawing.py` (54) — the specification's whole table, run against
every glyph, plus device-independence at four canvas sizes and the
scale-not-fitted case. Integration
`test_a_poor_drawing_fails_and_a_faithful_one_passes` asserts fail-then-pass over
real HTTP with the metrics and threshold persisted. E2E draws on the canvas with
real pointer events: blank cannot be submitted, a dot fails with no celebration
and no star, a faithful trace passes and celebrates.

**Human validation.** The reference paths and the thresholds.
→ REVIEW-QUEUE #14, #16

---

## 12. Speech `[x]` `[H]`

**Implementation.** The child's browser recogniser captures the utterance and
sends the transcript and the reported confidence; the server scores it with the
existing `voice/domain` Arabic pipeline (normalisation, g2p, weighted
Levenshtein, the three verdict bands, the closed-vocabulary rule) and returns
the authoritative outcome. No fake microphone: the button is rendered only when
the browser actually has a recogniser, and the caregiver-confirm button is
always on screen.

**Low confidence is not a wrong answer.** It is `uncertain`, recorded as
`no_response`, and asks for a retry or a caregiver confirmation. A confidence of
zero from a browser that does not estimate one is treated as an absence rather
than a low value — otherwise every attempt on Firefox and Safari would read as
uncertain.

**Tests.** `TestEvaluation` speech group (6), `speech.test.ts` confidence
passthrough, integration
`test_a_speech_attempt_the_recogniser_could_not_hear_is_not_a_wrong_answer` and
`test_a_caregiver_confirmation_carries_the_attempt`.

**Not done.** Server-side ASR (Qwen / Groq Whisper) is wired and unconfigured —
no credentials on this machine. The demo does not depend on it.
**Human validation:** no SLT has seen any of the scoring. → REVIEW-QUEUE #8

---

## 13. Rewards `[x]`

**Implementation.** `tutor/domain/rewards.py` + migration `0014`:
`reward_events` (append-only, `idempotency_key` UNIQUE) and `achievements`
(UNIQUE on `child_id, code`). Stars are a `SUM` over the table, read back
**after** the write — never a counter, and never the number the request meant to
add. Six achievements, each with caregiver-facing Arabic.

An independent correct answer is worth two stars, a supported one is worth one,
`full_model` is worth zero however it is recorded, and a wrong answer is worth
nothing.

**Tests.** `TestRewards` (10), 100 % branch on `domain/rewards.py`. Integration:
the same response posted six times produces one attempt, one reward row and an
unchanged total; ending a session twice does not double the completion bonus.
E2E asserts the star total is unchanged across a sign-out and sign-in.

---

## 14. Session evaluation and the caregiver report `[x]`

**Implementation.** `tutor/domain/report.py` computes the facts deterministically
and `session_summaries` stores them beside the narrative. The narrative may only
contain numbers the session produced — checked against Arabic-Indic digits as
well — and the template ships otherwise, with `narrative_source` recorded so a
caregiver is never told a template was written for them.

The child's closing screen shows stars, achievements and the skills practised.
No accuracy, no ratio, no comparison; the E2E asserts no "N out of M" text.

**Tests.** `TestReport` (11), integration
`test_a_finished_session_has_facts_a_report_and_an_inspector`, E2E on the report
screen.

---

## 15. AI inspector `[x]`

**Implementation.** `GET /tutor/sessions/{id}/inspector` reads `ai_decisions`,
`tutor_activities` and `attempts`. One card per decision: skill, difficulty,
strategy, support, modality, activity type, the estimate it was taken at, the
reason codes, the guardrail repairs, and whether a model or the deterministic
rule decided. A field with no stored value renders **غير متاح** — nothing is
recomputed for display.

**Tests.** Integration asserts the panel's reason codes are byte-identical to
the stored column and that `used_ai` is false with no provider configured. E2E
asserts the skill, strategy and reason codes are non-empty on a real session.

---

## 16. Persistence `[x]`

**Tests.** Integration
`test_rewards_and_learner_state_survive_a_restart` builds a **second application
instance** with a **new token** against the same database and asserts stars,
achievements and the report are unchanged. E2E clears every cookie, signs in
again and asserts the star total matches. `GET /children/{child_id}/sessions`
serves the history from `play_sessions` + `session_summaries`.

Cross-child isolation is asserted over all eight tutor routes.

---

## 17. Idempotency and double submission `[x]`

Server: `attempts.idempotency_key` UNIQUE, `reward_events.idempotency_key`
UNIQUE, `achievements (child_id, code)` UNIQUE, and a partial unique index
making at most one pending activity per session — so asking for the next
activity twice returns the same activity rather than creating a second one.

Client: `SUBMITTING` is a machine state rather than a flag, so `canAnswer` is
false while a response is in flight; the idempotency key is derived from
`(session, activity)` so a retry carries the same key.

**Tests.** Six-fold repeated submission; `asking for the next activity twice
returns the same activity`; the state-machine double-submit tests.

---

## 18. Failure handling `[x]`

- provider unavailable / invalid / slow → deterministic decision, session
  continues (`brain_call.propose` returns `None` for every gateway outcome).
- ASR unavailable → `uncertain`, caregiver confirmation, never `incorrect`.
- next-activity request fails → recoverable `error` state that KEEPS the
  activity; the session does not end.
- response submission fails → no celebration, no star, the activity stays.
- duplicate request → identical response with `duplicate: true` and
  `reward_delta: 0`.
- **no local fallback session.** The previous child app built a session from a
  bundled curriculum whenever the API was slow, so a demo against a broken
  backend looked identical to a working one and persisted nothing. Removed.

---

## 19. Demo seed `[x]`

`just seed-demo` — one caregiver, four children, each with a starting assessment
DERIVED by the real form code and a history folded by the real mastery loop.
Idempotent: re-running changes no row, asserted by a test that counts attempts,
rewards, achievements and stars before and after.

`just db-reset` rebuilds from the migrations.

---

## 20. Frontend `[x]`

Child picker, starting-assessment runner, server-driven session with one
renderer per activity type, closing screen, caregiver report, AI inspector.
Removed: `lib/manifest.ts`, `lib/play-session.ts`, `lib/play-client.ts`,
`components/play/*` and `app/api/play/*` — the client-authoritative path.

**Tests.** `pnpm --filter @sanad/web test` — 139 passing; eslint, stylelint and
`tsc --noEmit` clean.

---

## 21. Activity state machine `[x]`

`lib/activity-machine.ts`. See §10.

---

## 22. End-to-end `[x]`

`apps/web/e2e/demo-critical-path.spec.ts`, project `demo`, six tests, run in
Chromium against the real API and the real database. **Passing.** See the run
record below.

---

## 23. `demo-check` `[x]`

`just demo-check`. See DEMO-RUNBOOK §8.

---

## Blocked

### Live AI provider verification `[!]`

**Blocker.** No Groq or Anthropic API key on this machine, and none can be
obtained from inside the repository.

**Affected.** Only the assertion "a real provider answered". The AI-ON code path
is exercised by the gateway's fixture replay and by every failure branch;
nothing else depends on it.

**Evidence.** `just up` prints the credential table on startup and reports
`ai_gateway_built provider=groq live=false keyed=false`.

**Smallest action needed from you.** A Groq key in `.env` as
`SANAD_GROQ_API_KEY`, plus `SANAD_AI_LIVE=1`. DEMO-RUNBOOK §7.

### Docker `[!] → resolved`

Docker Desktop's service could not be started without administrator rights
(`Start-Service com.docker.service` → "Cannot open com.docker.service service").
Resolved inside the repository's constraints by provisioning PostgreSQL 16 +
pgvector, Redis 7 and MinIO in WSL2 on the ports `.env` already names — so no
code or configuration changed and `docker compose` remains the documented path.
DEMO-RUNBOOK §2.

---

## Human validation required `[H]`

| What | Who | Reference |
|---|---|---|
| Tracing reference paths and stroke order | handwriting / OT | REVIEW-QUEUE #14 |
| Starting-assessment questions and derivation | clinician + native speaker | #15 |
| Drawing thresholds against real children's tracings | OT | #16 |
| Mastery constants — ALPHA, the mixture, the accuracy floor | clinician | #17 |
| The new caregiver- and child-facing Arabic | native Egyptian speaker | #18 |
| Curriculum vowelisation, phonemes, distractor pools | native speaker | #6 |
| Pronunciation scoring and the closed-vocabulary rule | SLT | #8 |
| Accessibility and touch-target review with real children | OT | #12 |

None of these blocks the engineering demo. All of them block a family.
