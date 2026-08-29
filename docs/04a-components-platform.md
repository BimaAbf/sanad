# 04a — Components: Platform Core

Covers **C01 Identity & Access**, **C02 Child Profile & Consent**, **C09 Progress & Analytics**, **C10 Notifications & Scheduling**, **C15 LLM Gateway**.

Every component below follows the same internal shape:

```
app/modules/<name>/
  router.py        FastAPI routes — thin, no logic
  service.py       business logic — the only place with rules
  repository.py    SQLAlchemy queries — the only place with SQL
  schemas.py       Pydantic request/response models
  domain.py        pure functions, no I/O — the unit-testable core
  events.py        emitted domain events
  tests/
```

The rule that keeps this honest: **`domain.py` may not import anything from the project except other `domain.py` modules.** That is what makes the scoring and mastery logic testable without a database.

---

## C01 — Identity & Access

### Purpose
Authenticate caregivers, authorise access to children, and gate the child kiosk mode. Children never authenticate.

### Responsibilities
1. Phone + OTP registration and login; email + password as a secondary path.
2. JWT issuance, refresh-token rotation with reuse detection.
3. Authorisation: a caregiver may only touch a child they are linked to, with a role that permits it.
4. Play-PIN: a 4-digit PIN that locks *exit* from the child app.
5. Rate limiting and abuse protection on OTP.

### Interfaces

| Method | Path | Notes |
|---|---|---|
| `POST` | `/auth/otp/request` | `{phone_e164}` → 202 always (never reveals whether the number exists) |
| `POST` | `/auth/otp/verify` | `{phone_e164, code}` → tokens; creates the caregiver on first success |
| `POST` | `/auth/refresh` | rotating; reuse of a consumed token revokes the whole family |
| `POST` | `/auth/logout` | revokes the family |
| `GET`/`PATCH` | `/me` | caregiver profile |
| `PUT` | `/me/play-pin` | set/change the kiosk PIN |
| `POST` | `/me/play-pin/verify` | unlock exit from the child app |

### Key rules

- **OTP:** 6 digits, TTL 5 minutes, max 3 verify attempts, max 3 requests per number per hour and 10 per IP per hour (Redis sliding window). The code is stored as `sha256(code || server_pepper)` — never in plaintext, never in logs. Verification is constant-time.
- **Enumeration resistance:** `/auth/otp/request` always returns 202 with the same latency profile (a random 80–140 ms jitter on the "no-send" path).
- **Tokens:** access JWT 15 min (`sub`, `cgid`, `jti`, `scope`), RS256, key in AWS Secrets Manager with rotation. Refresh token: 30 days, opaque, `httpOnly` + `Secure` + `SameSite=Lax` cookie, hashed at rest, rotated on every use. **Reuse detection**: if a hash that is already `consumed` is presented, revoke every token in the `family_id` and force re-auth — this is how a stolen refresh token gets neutered.
- **Authorisation:** a single dependency `require_child_access(child_id, min_role)` resolves `caregiver_child` and raises 403. Every child-scoped route depends on it. A CI test enumerates the OpenAPI spec and **fails the build if any route containing `{child_id}` lacks that dependency** — this is how you prevent the single most likely serious bug in the system.
- **Play-PIN:** argon2id, 5 wrong attempts → 15-minute lockout, and the caregiver's account password/OTP is always an escape hatch. The PIN never protects data; it protects against a child leaving the app.

### Failure modes handled

| Case | Behaviour |
|---|---|
| SMS provider down | 202 to the client; a retry job tries an alternate provider; after 60 s the UI offers email login |
| Clock skew on device | JWT `nbf` given 60 s leeway |
| Caregiver changes phone number | Requires OTP on both old and new numbers |
| Shared device, two caregivers | Sessions are per-browser; explicit "switch account" clears local state including the IndexedDB outbox |

### Definition of done
Contract tests green; the route-authorisation CI check green; OTP brute force (100 codes) blocked; refresh reuse revokes the family; no secret appears in any log at `DEBUG`.

---

## C02 — Child Profile & Consent

### Purpose
Own the child record, the caregiver-child graph, the accessibility profile, and the versioned consent ledger.

### Responsibilities
1. CRUD for children, including the accessibility profile (`wait_time_ms`, `max_choices`, `audio_rate_pct`, `calm_mode`, `session_minutes`).
2. Age computation, including **corrected age** for children born before 37 weeks, applied until 24 months chronological.
3. Consent capture, withdrawal, and enforcement — consent state is a *precondition* checked by other components, not a UI concern.
4. Co-caregiver invitations.
5. Data export and erasure.

### Interfaces

| Method | Path | Notes |
|---|---|---|
| `POST` | `/children` | creates child + mandatory consents in one transaction |
| `GET`/`PATCH` | `/children/{id}` | |
| `GET` | `/children/{id}/consents` | current state of all 7 keys |
| `POST` | `/children/{id}/consents` | grant/withdraw; append-only |
| `POST` | `/children/{id}/invites` | invite a co-caregiver or therapist by phone |
| `POST` | `/invites/{token}/accept` | |
| `POST` | `/children/{id}/export` | async job → signed URL, 24 h TTL |
| `DELETE` | `/children/{id}` | soft archive; `?erase=true` triggers the erasure job |

### Key algorithms

**Corrected age**
```python
def age_months(dob: date, today: date, gestational_weeks: int | None) -> tuple[float, float]:
    chrono = (today - dob).days / 30.4375
    if gestational_weeks and gestational_weeks < 37 and chrono < 24:
        corrected = chrono - (37 - gestational_weeks) * 7 / 30.4375
        return chrono, max(corrected, 0.0)
    return chrono, chrono
```
Assessment entry bands use **corrected** age; the report displays both and explains the difference in one sentence.

**Consent enforcement.** A `ConsentGate` dependency is injected into the components that need it:

| Consent key | Gates |
|---|---|
| `ai_processing` | every C15 call for this child — without it, the whole product runs deterministic-only |
| `voice_asr` | C08 transcription; expressive activities substitute tap equivalents |
| `voice_retention` | S3 audio persistence; default is delete-immediately-after-transcribe |
| `clinician_share` | report visibility in C14 |

Withdrawal takes effect **within the same request** (the gate reads through a 60-second Redis cache that is explicitly busted on write), and triggers cleanup: withdrawing `voice_retention` purges that child's S3 audio prefix within 5 minutes.

### Edge cases
- Two caregivers editing the same child: optimistic concurrency via `updated_at` in an `If-Unmodified-Since` header → 409 with a merge-friendly diff.
- A therapist role can read reports and add clinical notes but cannot edit the profile or withdraw consent.
- DOB in the future or > 8 years ago → 422 with an Arabic message.
- Deleting the last owner is refused; ownership must be transferred first.

---

## C09 — Progress & Analytics

### Purpose
Turn raw attempts and assessments into the two views a caregiver actually cares about: *is my child moving forward*, and *what should we do next*.

### Responsibilities
1. Ingest first-party events (`events` table, partitioned monthly).
2. Maintain `progress_rollups` — incrementally on session end, and fully rebuilt nightly (the nightly rebuild is the correctness backstop for the incremental path).
3. Serve dashboard queries with zero client-side aggregation.
4. Produce the longitudinal assessment comparison series.

### The four caregiver-facing views

| View | Content | Query |
|---|---|---|
| **Today** | last session summary, streak, one suggested activity | `progress_rollups` `day:*` + last `play_sessions` |
| **Skills map** | 88 skills as a grid, coloured by `mastery_state`, grouped by category | `skill_states` join `skills` |
| **Journey** | line chart of skills mastered over time + DA per domain across assessments | `mastery_events` + `assessment_domain_scores` |
| **Report** | full PGEE report with a diff against the previous one | `assessment_reports` |

### Design rules that matter here

- **No trend line before 3 data points.** A two-point "trend" in a developmental measure is noise, and presenting it to an anxious parent is harmful. The UI shows raw values with a "we'll show trends after your third check-in" note.
- **Never show a percentile or an age comparison on the dashboard.** DQ appears only inside the report, in context, with explanatory text, behind the opt-in norm panel (assumption B7).
- **Regression is surfaced gently and always with an action.** If `skills_mastered` falls or a domain DA drops, the copy is "let's revisit a few things together" with a specific 3-activity plan — never a red arrow.
- Rollup recomputation is idempotent and keyed by `(child_id, period)` with an upsert, so a replayed job cannot double-count.

### Interfaces
`GET /children/{id}/progress/today`, `/skills`, `/journey`, `/assessments`, `GET /children/{id}/assessments/{aid}/report`, `POST /events` (batch, from the client outbox).

---

## C10 — Notifications & Scheduling

### Purpose
Bring caregivers back at the right moments without becoming another anxiety source.

### Scheduled jobs (ARQ, cron-triggered)

| Job | Cadence | Behaviour |
|---|---|---|
| `pgee_due_scan` | daily 09:00 Africa/Cairo | For each child, if `now - last_completed_assessment ≥ 180 days` → schedule `pgee_due`. Nudge at 180, 194, 208 days, then stop. **Three nudges maximum, ever.** |
| `weekly_digest` | Fridays 18:00 | Only if ≥ 1 session that week. Contains: sessions, minutes, newly mastered skills, one suggested activity. Never contains a score. |
| `streak_encourage` | daily 17:00 | Only if the child played yesterday but not today, and only if opted in. Max 2 per week. |
| `report_ready` | event-driven | push + in-app |
| `escalation_sla` | hourly | Alerts ops when an escalation approaches its SLA |
| `rollup_rebuild` | nightly 02:00 | Full rebuild of `progress_rollups` |
| `bkt_decay` | nightly 02:30 | Applies forgetting to `p_known` for overdue skills (see [04c](04c-components-learning.md)) |
| `tts_pregen` | on content publish | Batch-generates missing audio |
| `cost_report` | daily 07:00 | Per-child spend, budget breaches, to ops |

### Anti-nagging rules (product-critical)
- Hard cap: **3 notifications per caregiver per week** across all kinds, enforced centrally in the send path, not per job.
- Quiet hours 21:00–08:00 Africa/Cairo; anything scheduled inside is deferred, not dropped.
- Every notification carries a `dedupe_key`; the unique index makes double-send structurally impossible.
- One-tap "fewer reminders" in every message, which sets a per-caregiver cap of 1/week.
- **Never** a notification that implies the child is falling behind, and never a comparison to other children.

### Channels
Web Push (VAPID) primary; SMS only for `pgee_due` after two ignored pushes and for escalation acknowledgements; in-app always.

---

## C15 — LLM Gateway

Fully specified in [03 — AI Architecture](03-ai-architecture.md) §3. Summarised here for completeness:

- **Single choke point.** A CI lint rule fails the build if `anthropic.Anthropic` or `AsyncAnthropic` is constructed anywhere outside `app/ai/gateway.py`.
- **Responsibilities:** pseudonymise → budget check → flag check → cache-optimal prompt assembly → call with adaptive thinking + effort tier + server-side refusal fallbacks → schema validate → guardrail chain → rehydrate → persist `ai_calls` + Langfuse trace.
- **Budget:** `BudgetGuard` reads `cost_ledger` for `(child_id, today)`. Soft limit $0.40/day logs a warning; hard limit $0.60/day returns `budget_exceeded` and the caller runs its deterministic path. Budgets are per-child so one runaway session cannot starve the platform.
- **Prompt source:** Langfuse by label, with the resolved prompt text baked into the container image as a fallback so a Langfuse outage cannot take the product down.
- **Retries:** SDK-level `max_retries=3` for 408/409/429/5xx; application-level single repair for schema violations. No retry on `refusal` — that routes through server-side fallbacks instead.
- **Observability:** every call emits a Langfuse generation with `decision_point`, `prompt_version`, token counts, cost, guardrail outcomes, and the deterministic value it was compared against.
