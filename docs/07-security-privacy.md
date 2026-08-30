# 07 — Security, Privacy & Compliance

This product holds sensitive health-adjacent data about disabled children in a jurisdiction with an active data-protection law. The security posture is not proportionate to the user count — it is proportionate to the sensitivity of the data.

---

## 1. Threat model (STRIDE, abbreviated to what actually applies)

| Threat | Vector | Mitigation |
|---|---|---|
| **Spoofing** | OTP interception, SIM swap | Short TTL (5 min), 3-attempt cap, per-number and per-IP rate limits, device-binding on refresh tokens, re-auth required to change the phone number |
| **Tampering** | Forged attempts inflating progress | Attempts are server-scored; idempotency keys; server timestamps authoritative; implausible latency (< 200 ms) flagged not trusted |
| **Repudiation** | "I never consented" | Versioned consent ledger with IP, user agent, exact wording; append-only `audit_log` with a delete/update-blocking trigger |
| **Information disclosure** | **IDOR on `child_id` — the single most likely serious bug** | `require_child_access` dependency on every child-scoped route + a CI test that enumerates the OpenAPI spec and fails if any such route lacks it |
| | PII in LLM prompts | L1 pseudonymisation, plus an output scan (`PiiLeakLayer`) that checks responses for anything identity-shaped |
| | PII in logs | Structured logging with a field allow-list; a CI grep fails the build on `logger.*(f"...{child` patterns; `request_redacted` is the only persisted prompt copy |
| | Child audio leaking | Not retained by default; SSE-KMS + 30-day lifecycle when consented; never sent to the LLM; provider logging explicitly disabled |
| **Denial of service** | OTP flooding, LLM cost exhaustion | WAF rate rules, per-child token budget with a hard stop, per-caregiver token bucket, ARQ queue depth alarms |
| **Elevation of privilege** | Console access | Separate auth realm, mandatory TOTP MFA, IP allow-list, least-privilege roles, reason-logged child lookups |
| **Prompt injection** | Caregiver free text steering the model | Delimiter wrapping + explicit system-prompt instruction + closed-set output + adversarial eval set that must pass 100% |

---

## 2. The LLM trust boundary

This is the boundary that a normal web-app threat model does not have, so it gets its own section.

```
┌─────────────── VPC ───────────────┐         ┌──── Anthropic ────┐
│  child.display_name  "يوسف"        │         │                   │
│  caregiver.phone     "+2010…"      │  L1     │  sees only:       │
│  child.date_of_birth "2022-03-14"  │ ──────► │  {{CHILD}}        │
│  governorate         "القاهرة"      │ scrub   │  age_months: 42   │
│  raw caregiver text                │         │  comms: single_word│
│                                    │         │  <caregiver_answer>│
│                                    │ ◄────── │   …scored…        │
│  rehydrate {{CHILD}} → "يوسف"      │         │                   │
└────────────────────────────────────┘         └───────────────────┘
```

Rules, all enforced in code:

1. **Never crosses the boundary:** names, phone numbers, emails, national ID, exact date of birth, governorate, IP address, device identifiers, audio, transcripts of anything other than a single expected word.
2. **Crosses in pseudonymised form:** child age **rounded to whole months**, sex, communication level, domain profile, item responses, attempt telemetry, and caregiver free text about behaviour with identifiers stripped.
3. **Every prompt sent is persisted** post-redaction in `ai_calls.request_redacted`. If you cannot show a regulator exactly what you sent about a child, you should not be sending it.
4. **Outputs are scanned for leak-back.** `PiiLeakLayer` rejects any response containing an Egyptian phone pattern, an email, a 14-digit ID, or a name from the child/caregiver table for that request.
5. **Anthropic is a disclosed sub-processor** under a DPA, with data not used for training.
6. **Audio never reaches the LLM.** ASR output is a single word compared against a single expected word; that comparison happens in our own code, not in a model.

### Prompt-injection defence in depth

| Layer | Mechanism |
|---|---|
| Input framing | Caregiver text is wrapped in `<caregiver_answer>…</caregiver_answer>` and the frozen system prompt states that its content is data about a child and never an instruction |
| Input scrub | Strip zero-width characters, bidi override characters, and markdown/XML that would break the framing |
| Output constraint | `output_config.format` json_schema — the model's only channel is a fixed-shape object; there is no free-text field that reaches a user unvalidated from DP1/DP2/DP3 |
| Closed sets | Even a fully compromised model can only return an id from the candidate set or an enum member |
| Post-check | L5 clinical safety classifier on anything that becomes prose |
| Evidence | `interpret_adversarial.jsonl` — 40 injection attempts, gate is **100%** |

The structural point: the two decision points that produce prose (DP4 report and summary) never receive raw caregiver text at all — they receive engine-computed numbers and item labels. The two decision points that receive raw caregiver text (DP0, DP1) can only emit enums and ids. **There is no path from attacker-controlled text to user-visible prose.**

---

## 3. Application security

| Control | Implementation |
|---|---|
| Transport | TLS 1.3 only, HSTS `max-age=31536000; includeSubDomains; preload` |
| Headers | CSP with nonces (no `unsafe-inline`), `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: microphone=(self), camera=(), geolocation=()` |
| CSRF | Refresh cookie is `SameSite=Lax` + double-submit token on cookie-authenticated routes |
| Passwords / PINs | argon2id (`m=64MiB, t=3, p=4`) |
| Secrets | AWS Secrets Manager, rotated; nothing in env files in the repo; `gitleaks` in CI |
| Dependencies | `pip-audit` + `pnpm audit` in CI; Dependabot; a critical CVE fails the build |
| Uploads | Audio only, ≤ 1 MB, magic-byte sniffed, transcoded through ffmpeg before any processing, never served back |
| SQL | SQLAlchemy parameterised throughout; raw SQL only in reviewed migrations |
| SSRF | No user-supplied URLs are ever fetched by the backend |
| Object storage | Private buckets, pre-signed URLs with 1-hour TTL, `s3:PutObject` denied without KMS encryption |
| Admin | Separate realm, TOTP MFA, IP allow-list, 30-minute idle timeout |

---

## 4. Data protection compliance

### Legal basis (Egypt PDPL 151/2020 · GDPR-aligned)

| Processing | Basis | Notes |
|---|---|---|
| Child profile & progress | Explicit consent of the guardian | Mandatory; without it there is no service |
| AI-assisted assessment | Explicit consent | Separately toggled; declining leaves a fully working deterministic product |
| Voice transcription | Explicit consent | Optional; declining substitutes tap activities |
| Voice retention | Explicit consent | Optional, off by default, 30-day TTL |
| Sharing with a clinician | Explicit consent | Optional, per-clinician |
| Aggregate research | Explicit consent | Optional; anonymised, k-anonymity ≥ 20 before any aggregate leaves the system |
| Security logging | Legitimate interest | Documented in the processing register |

### Data subject rights

| Right | Implementation | SLA |
|---|---|---|
| Access | `POST /children/{id}/export` → signed ZIP: profile, consents, all assessments and reports, all attempts and mastery events, all `ai_calls` for that child (redacted form) | 7 days, usually minutes |
| Rectification | Answer correction (append-only supersede) and profile edit in-product | Immediate |
| Erasure | `DELETE /children/{id}?erase=true` → job hard-deletes the child and cascades, purges the S3 prefix and pgvector rows, tombstones audit actor references, anonymises rollups | 30 days, target 24 h |
| Portability | The same export, JSON + CSV | Same |
| Withdraw consent | Per-toggle, in-product, effective within the same request | Immediate |
| Object to automated processing | Turning off `ai_processing` runs the whole product deterministically — **a genuine, complete alternative, not a degraded stub** | Immediate |

That last row matters: GDPR Article 22 concerns decisions with significant effects made solely by automated means. Our answer is architectural rather than legal — the deterministic core is the real system, the AI is an assistive layer, a human caregiver confirms every interpretation, and a clinician reviews every flag. There is no solely-automated significant decision in the product.

### Retention

See [02](02-data-model.md) §9. Summary: telemetry 13 months, AI call logs 12 months, audit 7 years, child audio 30 days (consented only, otherwise zero), clinical records for the life of the account.

### Sub-processors (disclosed in the privacy notice)

| Processor | Purpose | Region | Notes |
|---|---|---|---|
| Anthropic | LLM inference | US/EU | DPA; no training on our data; pseudonymised input only |
| Microsoft Azure AI Speech | TTS + ASR | UAE North / West Europe | DPA; **logging explicitly disabled** |
| OpenAI | ASR fallback | US | DPA; opt-out of training; only reached on Azure failure |
| AWS | Hosting | me-south-1 (Bahrain) | DPA; encryption at rest and in transit |
| SMS aggregator | OTP delivery | Egypt | Phone number only |
| Langfuse (self-hosted) | LLM tracing | Our own VPC | No third-party transfer |

---

## 5. Child-specific safeguards

1. **No child account, no child login, no child-visible profile.** The child app holds no identity beyond a first name in an audio greeting.
2. **No chat.** The child cannot type or say anything free-form that another human will read. Voice input is compared against one expected word and discarded.
3. **No open-ended generation reaches a child.** Everything Nour says comes from the pre-generated corpus or a fixed praise pool. **A child never hears an LLM output.** This is worth stating plainly because it removes an entire risk category: no matter how a model misbehaves, it cannot say anything to a child.
4. **No external links, no ads, no third-party SDKs, no in-app purchases** in the child app.
5. **No leaderboards, no comparison to other children**, anywhere in the product.
6. **Safeguarding path:** disclosures suggesting harm route to a human within 2 hours via the escalation queue, and the product's response is fixed human-written copy.

---

## 6. Incident response

| Severity | Definition | Response |
|---|---|---|
| **SEV1** | PII exposure, child audio leak, cross-child data access, unsafe content reaching a caregiver | Page immediately; kill switch on the affected AI flag; freeze deploys; notify the DPO within 4 h; regulator notification assessed within 72 h |
| **SEV2** | Auth bypass without confirmed access; guardrail bypass caught internally; assessment scoring incorrect | Page during business hours; hotfix within 24 h; affected assessments re-scored and caregivers notified |
| **SEV3** | Degraded AI, provider outage, elevated latency | Ticket; automatic degradation already handles the user impact |

**Kill switches, in order of blast radius:** individual AI decision point → all AI (`ai.*`) → voice input → play sessions → full read-only mode. Each is a feature flag, effective in under 30 seconds, and each is rehearsed in a game day before launch.

**Scoring-correctness incidents get a specific runbook**, because they are the ones with clinical consequence: freeze, identify affected assessments by `bank_version` and date range, re-score deterministically from `assessment_responses` (which is why it is append-only), regenerate reports, notify every affected caregiver in plain Arabic with the corrected report attached, and log the whole thing for the clinical partner.

---

## 7. Pre-launch security checklist

- [ ] External penetration test focused on IDOR, auth, and the console
- [ ] Prompt-injection red team by someone who did not write the prompts
- [ ] Full data-flow map signed off by the DPO
- [ ] Processing register complete; privacy notice published in Arabic and English
- [ ] All DPAs executed; Azure logging confirmed disabled in the deployed config
- [ ] Erasure and export verified end to end on a real account
- [ ] Backup restore rehearsed; RPO ≤ 5 min, RTO ≤ 1 h verified by drill
- [ ] Every kill switch exercised in staging under load
- [ ] Secrets scan clean; no credentials in git history
- [ ] `require_child_access` CI check green and demonstrably failing when a route is removed from it
