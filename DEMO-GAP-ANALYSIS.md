# DEMO-GAP-ANALYSIS

_Written 2026-08-30, from the code, migrations and tests — not from `PROGRESS.md`._

Classification per requirement of the final demo specification.
Legend: **IMPLEMENTED** · **PARTIAL** · **MISSING** · **BROKEN** · **BLOCKED** · **NEEDS VALIDATION**

---

## 0. What the repository actually is today

The platform tier is real and good: identity (OTP → RS256 → `/me`), children +
consent ledger, a PGEE milestone assessment with a basal/ceiling engine, a BKT
domain package, a candidate/planning package, a voice gateway with a real
Arabic pronunciation scorer, a progress rollup, an LLM gateway with fixture
replay, and a guardrail chain. 30 files at 100 % branch coverage.

**The demo does not run on that tier.** Three structural facts break the target
demo, and each is confirmed by reading the code rather than the docs:

1. **The child app decides correctness.** `apps/web/src/components/play/games.tsx`
   calls `onAnswer(choice.skill_id, choice.correct ? "correct" : "incorrect")`,
   and `apps/web/src/app/(play)/play/page.tsx::record()` celebrates
   unconditionally (`advance()` → `<Celebration/>`, `setStickers(...)`) before
   any server round trip. The backend stores whatever `result` the client sends
   (`play/service.py::_attempt_values`). This violates §11 and §22 outright.
2. **The AI Brain is orphaned code.** `app/modules/tutor_ai/brain.py`,
   `loop.py`, `audit.py` are complete and tested — and `run_step` has **zero
   callers** outside its own unit test (`grep -rn run_step app/` → only its own
   module). `ai_decisions` and `activity_outcomes` (migration 0013) are written
   by nothing. The running system is `play/service.py::_build_plan`, a
   `SELECT … ORDER BY intro_order LIMIT n` with `plan_source =
   "deterministic_fallback"` hardcoded.
3. **The session is a manifest, not a loop.** `POST /play/sessions` returns the
   whole plan up front and the client walks it. There is no per-activity
   decision, so nothing can adapt inside a session (§5, §10).

And a fourth, which is a live product defect:

4. **`loadSession()` silently falls back to a fully client-side session**
   (`apps/web/src/lib/play-session.ts` → `buildLocalSession`). A demo run
   against a broken API looks identical to a working one and persists nothing.

---

## 1. Authentication — **IMPLEMENTED**

Exists: `app/modules/identity/*` (OTP, RS256 access token, refresh rotation,
rate limiting, `caregiver_child` role matrix), `apps/web/src/lib/session.ts`
(httpOnly cookies), `require_child_access` + CI guard.
Gap: none for the demo. Verified by 87 existing unit tests; child-scoping needs
a real-Postgres cross-tenant test (§19) which does not exist yet.
Tests to add: `Caregiver A cannot read/modify Child B` against real Postgres.

## 2. Persistent child profiles — **IMPLEMENTED**

`children` table + `caregiver_child` link + `/children` CRUD + consent gate.
Gap: the caregiver app has no "pick a child, see their different learner state"
screen — `children/page.tsx` links to `/child/{id}/coach` only, and `/play`
never receives a child id (`startSession()` posts `{}`).
Work: a child-picker that sets the active child and starts *that child's*
session; `POST /tutor/sessions` must take `child_id`.

## 3. Initial caregiver assessment — **PARTIAL / MISSING for the demo**

Exists: the PGEE engine (`assessment/domain/*`, 100 % branch), persistence
(`assessments`, `assessment_answers`), replay-on-write, idempotency,
`finalise()` → `domain_da` per domain.
Missing: the assessment the specification asks for. The PGEE bank is 6
developmental domains of **synthetic placeholder** items
(`seeds/item_bank.py`, `WATERMARK = "PLACEHOLDER — NOT FOR CLINICAL USE"`); it
produces developmental ages, **not** starting points for numbers / colours /
shapes / letters / words / matching / following-instructions / speech /
drawing, and **nothing anywhere converts an assessment into learner state.**
`skill_states` has exactly one writer (`learning/service.py`, at session end);
a brand-new child starts every skill at `not_started`, `p_known = 0.15`,
identical for every child.
Work: a new bounded `starting_assessment` covering the ten required areas,
persisted, whose finalisation writes **initial skill priors and support/modality
preferences** into `skill_states` + a new `learner_profiles` row. Keep the PGEE
engine untouched.

## 4. Initial learner-state creation — **MISSING**

See §3. No code path creates `skill_states` before the first session ends.

## 5. AI-assisted personalised teaching decisions — **PARTIAL (orphaned)**

Exists and is good: `tutor_ai/brain.py` (`BrainDecision` strict schema,
`_fallback`, `guard_decision`), `tutor_ai/loop.py::run_step`,
`TutorAuditRepository`, migration 0013 tables, `app/ai/gateway.py`
(`call_structured`, fixtures, AI ON/OFF, refusal/schema/timeout outcomes).
Missing: (a) any caller; (b) a live-provider path that produces a
`BrainDecision` (the gateway is never asked for one); (c) the evidence bundle
built from the real database — `tutor_ai/evidence.py` is fed by nothing;
(d) persistence of the *resulting activity* and *resulting outcome* on the
decision row.
Work: an HTTP `POST /tutor/sessions/{id}/next` that assembles evidence from
Postgres, calls the gateway for `tutor_brain`, guards, persists, and returns an
activity contract.

## 6. Adaptive activities / dynamic activity system — **MISSING**

Exists: five client-side game components, a client-side manifest builder, a
server-side `listen_point`-only plan builder.
Missing: a generic activity contract, backend construction of the activity from
the guarded decision, and the request/respond loop. The eight required activity
types (selection, counting, matching, listening, speaking, sorting, sequence,
drawing) do not exist as a server contract at all.

## 7. BKT / mastery updates — **BROKEN (confirmed by arithmetic)**

The mastery accuracy guard in `learning/domain/mastery.py` uses a Hoeffding
margin with the confidence divided across looks:

    margin(n, looks) = sqrt(ln(looks / 1e-5) / (2n)),  window capped at 40

At n = 20 perfect independent attempts at 2 choices this demands accuracy ≥
0.5 + 0.602 = **1.102** — unreachable. The window cap means the margin never
falls below `sqrt(ln(looks/1e-5)/80)`; at 500 looks that is 0.471, so a
two-choice skill needs 0.971 accuracy *and* is still bounded away at any n.
Requirement (B) of §4 of the specification is therefore false today, and
REVIEW-QUEUE #5 records the same measurement.
Requirement (A) holds (`test_bkt_random_tapper.py`, 1000 sims).
Work: replace the fixed-alternative Hoeffding bound with an **anytime-valid
mixture likelihood-ratio martingale** (Ville's inequality). It handles the
per-attempt varying chance level natively, needs no Bonferroni, keeps
P(chance behaviour ever passes) ≤ 1e-5, and lets 20 perfect independent
two-choice attempts pass. Add the full regression matrix from §4.

## 8. Different strategies for different learners / personalisation — **MISSING**

Nothing reads a learner's evidence to choose strategy/support/modality at
runtime. `_build_plan` is `ORDER BY intro_order` for every child.
Work: falls out of §5 + §6 once the brain is wired; plus ≥ 20 synthetic
scenarios asserting different evidence ⇒ different decisions.

## 9. Correct/incorrect evaluation — **BROKEN**

The frontend decides. See §0.1.
Work: backend `respond` endpoint that owns correctness for every activity type
and returns an authoritative result the client renders without re-deciding.

## 10. Speech activities — **PARTIAL**

Exists and is real: `voice/domain/{normalize,g2p,similarity,scoring}.py`,
`AsrChain` with Qwen → Groq Whisper → caregiver confirmation, upload validation
by magic bytes, unconditional audio deletion, `POST /voice/attempt`.
Missing: the speech outcome never reaches `attempts`, `skill_states` or a
session; the child app's `say_it` game records `caregiver_confirmed` locally
and posts nothing to `/voice/attempt`; there is no wiring of "low confidence ⇒
retry/caregiver-confirm" into the activity loop.
Work: a `speak` activity type in the tutor loop whose response goes through
`VoiceService.score_attempt` and whose verdict becomes an authoritative
attempt.

## 11. Drawing / tracing evaluation — **MISSING** (nothing exists)

No canvas, no stroke capture, no reference path, no metric, no threshold, no
table. Work: a pure `drawing.py` domain (normalise → coverage / mean distance /
outside-ratio / IoU → score), a backend threshold, persistence into
`activity_outcomes`, and the full mandatory test table from §12.

## 12. Persistent rewards — **MISSING**

No table, no rule, no endpoint. The child app keeps `stickers` in React state
and loses them on refresh. Work: migration + deterministic reward rule +
idempotent reward events keyed to the source attempt.

## 13. Session evaluation / caregiver report — **PARTIAL**

Exists: `play_sessions.activities_done/correct_count`, a `session_end` event,
progress rollups, and `tutor_ai/session.py::resolve_summary` (template + AI
constraints) — again with no caller.
Missing: persisted session facts (independent vs supported, skills practised,
mastery changes, rewards, duration) and a caregiver-readable report endpoint.

## 14. Persistent progress between sessions — **PARTIAL**

`attempts` and `skill_states` persist and the mastery fold is idempotent. But
because nothing writes learner state before the first session end and rewards
do not exist, "log out, log in, everything is still there" is only true for
attempts and the rollup.

## 15. Explainable AI decisions / AI Inspector — **MISSING**

`ai_decisions` exists and is empty. There is no endpoint and no panel.
`apps/web/src/app/(console)/console/ai-calls/page.tsx` renders static text.

## 16. Guardrails — **PARTIAL**

`brain.guard_decision` covers unsupported skill/modality/activity, new-skill
advance, fatigue, repeat streak. Missing from the §7 list: prerequisite skips,
difficulty jump > 1 (`MAX_DIFFICULTY_JUMP` is declared and **never used**),
session limits, consent, schema failure → fallback (that lives in the gateway
but is not joined up), and "AI attempts to modify mastery" (structurally
impossible — `BrainDecision` has no mastery field — worth an explicit test).

## 17. Failure handling — **PARTIAL**

The gateway has every outcome; nothing consumes them. The client hides failures
by design (`endSession().catch(() => undefined)`, `loadSession` local fallback,
`playPoster` treating 4xx as delivered) — appropriate for "no failure state for
the child", but it currently also hides *persistence* failure, which §18/§22
forbid.

## 18. Database integration testing — **PARTIAL**

Six integration tests exist with an excellent rollback harness
(`tests/integration/test_assessment_and_play.py`). Missing: every test in §19
except attempt idempotency and `ai_cannot_grant`.

## 19. Demo seed data — **MISSING**

`sanad seed` loads the 88-skill curriculum only. No caregiver, no children, no
histories. `just seed` cannot produce Ahmed / Laila / Omar.

## 20. Frontend flow — **PARTIAL**

Login/onboarding, home, children, skills, journey, coach chat and console pages
exist and build (13 routes). Missing: child picker → session, the server-driven
play loop, the starting assessment runner, the session result, the caregiver
report, the AI inspector panel.

## 21. Activity state machine — **MISSING**

`play/page.tsx` uses four ad-hoc phases and has the contradictory state §23
forbids (celebration with no server verdict).

## 22. Idempotency / double submission — **PARTIAL**

`attempts.idempotency_key` unique index + `ON CONFLICT DO NOTHING` is real and
tested. Missing: idempotency for rewards (they do not exist) and for the
`respond` endpoint (it does not exist); no control-disabling during submit.

## 23. E2E — **MISSING**

Three Playwright specs exist, each opening with a `NEVER EXECUTED` banner, and
no browser binary is installed. They test the *old* client-authoritative flow.

## 24. demo-check — **MISSING**

## 25. Environment — **BLOCKED → RESOLVED**

Docker Desktop's service is stopped and cannot be started without
administrator rights on this machine (`Start-Service com.docker.service` →
"Cannot open com.docker.service service"). Resolved inside the repository's
constraints by provisioning the same dependency versions in WSL2 Ubuntu 22.04:
PostgreSQL 16.15 + pgvector on `localhost:55432`, Redis on `localhost:56379`,
MinIO on `localhost:59000` — the exact ports `.env` and `.env.test` already
name, so no code or configuration changes. `just up` / `docker compose` remain
the documented path for machines with a working daemon.

---

## Implementation order

1. Mastery/BKT correction + regression matrix (everything downstream reads it).
2. Migration `0014`: learner profiles, starting assessment, rewards,
   achievements, session summaries, activity delivery.
3. `app/modules/tutor` — evidence → brain (gateway + fallback) → guardrails →
   activity contract → authoritative evaluation → attempt → BKT → rewards →
   inspector → session report.
4. Drawing domain + tests. Speech wiring. Rewards.
5. Starting assessment → initial learner state.
6. Seed command (Ahmed / Laila / Omar).
7. Frontend: child picker, starting assessment, server-driven session,
   result, report, inspector.
8. Integration tests, personalisation scenarios, Playwright E2E, `just
   demo-check`, runbook.
