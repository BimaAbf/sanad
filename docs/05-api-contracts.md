# 05 — API Contracts

Base: `https://api.misk.app/v1`. OpenAPI 3.1 is generated from FastAPI and is the **source of truth** — the TypeScript client in `packages/api-client` is code-generated from it in CI, so a backend change that breaks the frontend fails the build rather than production.

## 1. Conventions

| Concern | Rule |
|---|---|
| Auth | `Authorization: Bearer <access_jwt>`; refresh token in an `httpOnly` cookie |
| Versioning | URL major version. Additive changes only within `v1`; a removed field is a new major |
| IDs | UUID v7 strings |
| Time | RFC 3339 UTC (`2026-08-29T12:00:00Z`); the client renders in Africa/Cairo |
| Language | `Accept-Language: ar-EG` default; all user-facing strings returned pre-localised |
| Idempotency | `Idempotency-Key` header required on `POST /play/sessions/{id}/attempts` and `POST /assessments/{id}/answers`; keys are stored 24 h |
| Concurrency | `If-Unmodified-Since` on `PATCH /children/{id}` → 409 on conflict |
| Pagination | Cursor: `?limit=50&cursor=<opaque>` → `{items, next_cursor}` |
| Rate limits | Per-caregiver token bucket; `429` with `Retry-After`. OTP endpoints have their own tighter budget |
| Errors | RFC 9457 Problem Details |

### Error model

```jsonc
{
  "type": "https://api.misk.app/errors/assessment-too-soon",
  "title": "Assessment not yet due",
  "status": 409,
  "detail": "Last assessment completed 96 days ago; minimum interval is 150 days.",
  "instance": "/v1/assessments",
  "code": "ASSESSMENT_TOO_SOON",
  "message_ar": "لسه بدري على التقييم الجديد. التقييم الجاي هيكون متاح يوم ١٢ ديسمبر.",
  "meta": { "next_eligible_at": "2026-12-12T00:00:00Z" }
}
```

`message_ar` is always present and is always safe to show to a caregiver verbatim. `detail` is for engineers and is never displayed.

Registered codes: `OTP_INVALID`, `OTP_EXPIRED`, `OTP_RATE_LIMITED`, `TOKEN_REUSED`, `CHILD_ACCESS_DENIED`, `CONSENT_REQUIRED`, `ASSESSMENT_TOO_SOON`, `ASSESSMENT_EXPIRED`, `ITEM_OUT_OF_SEQUENCE`, `SESSION_ALREADY_ENDED`, `BUDGET_EXCEEDED`, `AI_DEGRADED` (informational, 200), `VALIDATION_ERROR`, `CONFLICT`, `RATE_LIMITED`, `INTERNAL`.

## 2. Auth & identity (C01)

```http
POST /auth/otp/request        { "phone_e164": "+201001234567" }              → 202 {}
POST /auth/otp/verify         { "phone_e164": "...", "code": "483920" }
     → 200 { "access_token": "...", "expires_in": 900, "is_new_user": true }
POST /auth/refresh            (cookie)                                        → 200 { access_token, expires_in }
POST /auth/logout                                                             → 204
GET  /me                      → 200 { id, display_name, phone_e164, relationship,
                                       governorate, locale, has_play_pin, children:[…] }
PATCH /me                     { display_name?, relationship?, governorate?, locale? }
PUT  /me/play-pin             { "pin": "1234" }                               → 204
POST /me/play-pin/verify      { "pin": "1234" }                               → 200 { ok: true }
```

## 3. Children & consent (C02)

```http
POST /children
{ "display_name": "يوسف", "name_vowelised": "يُوسُف", "date_of_birth": "2022-03-14",
  "sex": "male", "gestational_weeks": 38, "comms_level": "single_words",
  "diagnosis_note": "متلازمة داون، تشخيص عند الولادة",
  "consents": [ { "key": "data_processing", "granted": true },
                { "key": "ai_processing",   "granted": true },
                { "key": "terms_not_medical","granted": true },
                { "key": "voice_asr",       "granted": true },
                { "key": "voice_retention", "granted": false },
                { "key": "clinician_share", "granted": false },
                { "key": "research_aggregate","granted": false } ] }
→ 201 { id, chronological_months: 41.5, corrected_months: 41.5,
        next_action: "run_first_assessment" }

GET   /children/{id}
PATCH /children/{id}          { wait_time_ms?, max_choices?, audio_rate_pct?,
                                calm_mode?, session_minutes?, comms_level?, ... }
GET   /children/{id}/consents → 200 { items: [{ key, version, status, text_ar,
                                                is_mandatory, granted_at }] }
POST  /children/{id}/consents { "key": "voice_retention", "granted": false } → 200
POST  /children/{id}/invites  { "phone_e164": "...", "role": "co_caregiver" } → 201 { invite_url }
POST  /invites/{token}/accept                                                 → 200
POST  /children/{id}/export                                                   → 202 { job_id }
DELETE /children/{id}?erase=true                                              → 202 { job_id }
```

## 4. Assessment (C03 + C04)

```http
POST /assessments             { "child_id": "..." }
→ 201 { id, sequence_no: 2, status: "in_progress", entry_bands: {...},
        estimated_items: { min: 22, max: 34 }, stream_url: "/v1/assessments/{id}/stream" }
→ 409 ASSESSMENT_TOO_SOON

GET  /assessments/{id}        → current state, for resume
GET  /assessments/{id}/stream → text/event-stream  (see §4.1)

POST /assessments/{id}/answers
Headers: Idempotency-Key: <uuid>
{ "item_id": "...", "source": "tap", "verdict": "emerging", "client_seq": 17 }
   -- or --
{ "item_id": "...", "source": "text",
  "text": "بيمسكها بس لازم أساعده في الأول", "client_seq": 17 }
→ 202 {}     // the result arrives on the SSE stream

POST /assessments/{id}/answers/{response_id}/correct
{ "verdict": "no" }                                       → 200  // append-only supersede

POST /assessments/{id}/pause                              → 200 { resume_before: "..." }
POST /assessments/{id}/finalise                           → 202 { job_id }
GET  /assessments/{id}/report
→ 200 { narrative_ar, strengths_ar: [...], focus_areas_ar: [...],
        home_activities: [{ title_ar, steps_ar: [...], skill_ids: [...], minutes }],
        domains: [{ domain, name_ar, developmental_age_months, developmental_quotient,
                    delta_da_months, items_administered }],
        is_template: false, generated_at, previous_assessment_id }
GET  /children/{id}/assessments  → list with DA series for the journey chart
```

### 4.1 Assessment SSE events

```
event: item
data: {"item_id":"…","prompt_ar":"بيشرب من الكوباية لوحده؟",
       "prompt_ar_msa":"…","example_ar":"يعني…","criterion_ar":"…",
       "domain":"self_help","domain_name_ar":"العناية بالنفس",
       "progress":{"answered":14,"estimated_min":22,"estimated_max":28}}

event: probe
data: {"probe_id":"p_help_needed","text_ar":"بيعمل كده لوحده ولا محتاج مساعدة؟"}

event: interpreted
data: {"item_id":"…","verdict":"emerging","confidence":0.82,
       "rationale_ar":"قلتِ «لازم أساعده في الأول»","confirmable":true}

event: propagated
data: {"count":4,"items":[{"item_id":"…","prompt_ar":"…","verdict":"yes"}]}

event: escalation
data: {"category":"regression","message_ar":"<fixed human-written copy>"}

event: degraded
data: {"reason":"ai_unavailable","message_ar":"هنكمل بالأزرار دلوقتي."}

event: scoring
data: {}

event: report_ready
data: {"assessment_id":"…","report_url":"/v1/assessments/…/report"}
```

Reconnection uses `Last-Event-ID`; the server replays from the LangGraph checkpoint, so a dropped connection resumes on the same item rather than restarting.

## 5. Play & learning (C05, C06, C07)

```http
POST /play/sessions           { "child_id": "...", "minutes": 8 }
→ 201 { session_id, manifest: { ... }, plan_source: "ai" }   // full manifest, §4 of 04c

POST /play/sessions/{id}/attempts
Headers: Idempotency-Key: <uuid>
{ "activity_id":"…", "skill_id":"…", "modality":"receptive", "attempt_no":1,
  "result":"correct", "prompt_level":"independent", "latency_ms":4200,
  "choice_count":2, "selected_skill_id":"…", "client_ts":"2026-08-29T12:00:03Z" }
→ 202 {}                                     // fire and forget; client never waits

POST /play/sessions/{id}/attempts/batch      // outbox drain after reconnect
{ "attempts": [ … up to 100 … ] }            → 202 { accepted, duplicates }

POST /play/sessions/{id}/end  { "reason": "completed" }
→ 200 { summary_ar, activities_done, newly_mastered: [{skill_id,label_ar}],
        home_activity: { title_ar, steps_ar: [...] } }

GET  /children/{id}/skills    → 200 { items:[{ skill_id, code, label_ar, category,
                                                state, p_known, due_at, last_seen_at }] }
GET  /children/{id}/progress/today
GET  /children/{id}/progress/journey?from=&to=
POST /events                  { "events": [ { name, props, client_ts } ] }  → 202
```

## 6. Voice (C08)

```http
POST /voice/attempt           multipart/form-data
  audio: <blob audio/webm;codecs=opus>
  activity_id: <uuid>
  attempt_no: 1
→ 200 { "verdict":"accept"|"retry"|"unclear", "similarity":0.71,
        "heard":"الاحمر", "feedback_audio_url":"https://cdn/…/bravo2.opus" }

POST /voice/override          { "activity_id":"…" }   → 200 { recorded: true }
POST /voice/tts               { "text":"…","voice":"nour_child","rate":85 }  // admin
→ 200 { url, cached: true }
GET  /voice/health            → { providers:{azure:"up",openai:"up"}, cache_hit_rate:0.94 }
```

## 7. Console (C14)

```http
GET   /console/escalations?status=open&sort=sla
POST  /console/escalations/{id}/acknowledge   { "note": "..." }
POST  /console/escalations/{id}/respond       { "message_ar": "..." }
POST  /console/escalations/{id}/resolve       { "resolution_note": "..." }

GET   /console/items?bank_version=&domain=&band=
POST  /console/items                          // draft
POST  /console/items/{id}/review              { "reviewer": "Dr. …", "approved": true }
POST  /console/items/publish                  { "bank_version": "portage-licensed-v1" }

GET   /console/skills  · POST /console/skills · POST /console/content/publish
GET   /console/reports?flagged=true
POST  /console/reports/{aid}/release           { "narrative_ar": "..." }

GET   /console/ai-calls?decision_point=&outcome=&from=&to=
GET   /console/guardrail-events?layer=&outcome=
GET   /console/flags · PUT /console/flags/{key}   { enabled, rollout_pct }
GET   /console/cost?group_by=child|day
GET   /console/children/{id}?reason=<required>    // logged access
```

## 8. Health & ops

```http
GET /health         → 200 { status: "ok" }                       // liveness, no deps
GET /health/ready   → 200 { db, redis, s3, anthropic, azure }    // readiness
GET /metrics        → Prometheus, internal only
```

## 9. Contract testing

- `schemathesis run openapi.json` in CI — property-based fuzzing of every endpoint against the spec.
- The generated TypeScript client is committed; a diff in CI without a corresponding frontend change fails the build.
- Every `4xx` in the spec has at least one test asserting the exact `code` and the presence of `message_ar`.
- A test asserts that **every** path containing `{child_id}` or `{id}` under `/children`, `/assessments`, `/play` declares the `require_child_access` dependency.
