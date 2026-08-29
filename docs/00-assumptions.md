# 00 — Assumptions, Scope & Open Questions

> **Revised by [12 — Stack Revision](12-stack-revision-groq-selfhosted-voice.md):** assumptions **C1, C2, C3, D1 and D4** have been superseded. TTS moves to a self-hosted VoxCPM2 voice clone, ASR to Qwen3-ASR, the LLM to per-decision-point routing between Claude Opus 5 and Groq, and hosting to Cloudflare Pages + Hetzner. The reasoning for each original choice is retained below because it still explains *why* the requirement exists.


You asked me to assume missing details and declare them. Everything below is a decision I made, not something you told me. Each is numbered so you can override it individually. Every one is reversible via configuration except where marked **structural**.

---

## A. Product & users

| # | Assumption | Rationale / impact |
|---|---|---|
| A1 | Primary market is **Egypt**. UI language is **Arabic** — Egyptian colloquial for the child, plain MSA + Egyptian for the caregiver. English is a later toggle, not MVP. | Drives voice vendor choice, RTL-first layout, phone-number auth, Bahrain AWS region. |
| A2 | Child age range **birth – 6 years** (matches PGEE coverage). Learning content targets the **2–6** slice; caregivers of under-2s get assessment + activity suggestions only. | Bounds content volume. The child-facing app assumes a child who can tap. |
| A3 | The **caregiver is always physically present** during a child session. This is not a babysitting product. | Lets us use the caregiver as a human-in-the-loop signal ("did he say it right?"), which rescues us from unreliable child ASR. **Structural** — much of the safety design rests on this. |
| A4 | One caregiver account may hold **multiple child profiles** (siblings). One child may be shared with a second caregiver (co-parent, therapist) by invite. | Drives a `caregiver_child` join table with roles. |
| A5 | MVP scale: **2,000 caregivers, 2,500 children, peak 80 concurrent child sessions.** This is not a scale problem — it is a correctness and UX problem. | Justifies a modular monolith over microservices. |
| A6 | Devices: **mid-range Android phones and tablets**, Chrome. Shipped as an **installable PWA**, not a native app. iOS Safari supported but second-class. | Faster to ship, no store review for a medical-adjacent app, OTA fixes. Cost: no background audio, so voice is turn-based. |
| A7 | Network is **intermittent 3G/4G**. The child app must survive a 30-second dropout mid-session without losing progress. | Drives offline asset precaching and an outbox queue for attempts. |
| A8 | Monetisation is **out of scope for MVP** (free / NGO-funded pilot). Billing tables exist but are unused. | Removes payments from the critical path. |
| A9 | There is a **clinical partner** — a developmental paediatrician or licensed early-intervention specialist — available to review flagged cases and sign off on the item bank. | **Structural.** If false, the PGEE feature cannot ship as designed. See [O1](#open-questions). |

## B. Clinical & pedagogical

| # | Assumption | Rationale / impact |
|---|---|---|
| B1 | **PGEE = Portage Guide to Early Education**: a criterion-referenced checklist of ~580 behaviours across 6 domains (Infant Stimulation, Socialisation, Language, Self-Help, Cognition, Motor) in 6 age bands (0–1 … 5–6 years). | Basis of the entire assessment engine. |
| B2 | **The Portage Guide is copyrighted** (Portage Project / CESA 5). We either ship a licensed copy **or** a clinically-authored "PGEE-compatible" bank that we own. The engine is bank-agnostic: items are database rows, never code. | **Structural + legal.** See [O1](#open-questions). The architecture is deliberately built so that swapping the item bank is a data migration, not a rewrite. |
| B3 | Basal rule = **8 consecutive passes** below the entry band. Ceiling rule = **6 consecutive fails** within a domain. Entry band = `min(chronological age band, prior developmental band)`; for a first assessment on a Down syndrome profile we enter **one band below chronological age**. | Stored as rows in `assessment_rules`, not constants in code, precisely because a licensed manual may specify different values. |
| B4 | Domain **Developmental Age (DA)** = age-equivalent of the highest fully-passed band, plus credit for scattered passes above it (`0.5 × band_width × pass_ratio`). **DQ = DA / CA × 100.** | Deterministic, unit-tested, LLM-free. |
| B5 | Reassessment cadence is **every 6 months minimum**; a new assessment is blocked before day 150 unless a clinician overrides. | From your brief. Prevents practice effects and caregiver-anxiety loops. |
| B6 | The platform is **educational and a progress-tracking aid — explicitly not a diagnostic device.** No IQ, no diagnosis, no prognosis, no medical advice, ever. Enforced in code by a guardrail classifier, not merely in prompts. | **Structural.** Regulatory posture: stays outside medical-device classification. |
| B7 | Reporting compares the child **to their own prior self first**. Norm comparison is a secondary, softly-worded panel the caregiver must opt into. | Evidence-based practice for DS families; reduces harm. |
| B8 | Child pedagogy assumes the documented Down syndrome learning profile: **visual-processing strength, auditory short-term-memory weakness, expressive language lagging receptive, longer response latency, motor imprecision.** | Drives whole-word sight reading over phonics-first; instructions ≤ 5 words; receptive tasks before expressive; 8-second default wait time; 80 px touch targets; errorless learning with a 4-step prompt hierarchy. |
| B9 | Mastery ground truth = **BKT posterior ≥ 0.90, sustained across ≥ 2 sessions on different days, plus ≥ 1 correct delayed retrieval after ≥ 3 days.** The AI judge may *withhold* mastery but may never *grant* it beyond this rule. | This is how "an AI decides whether it was learned" becomes safe. |

## C. Language & voice

| # | Assumption | Rationale / impact |
|---|---|---|
| C1 | **TTS: Azure AI Speech neural voices `ar-EG-SalmaNeural`** (child-facing character **"نور" / Nour**) and **`ar-EG-ShakirNeural`** (caregiver narration). Genuinely Egyptian; SSML-controllable rate, pitch and pauses. | Best true `ar-EG` coverage among the major vendors. Abstracted behind a `TtsProvider` interface with an **ElevenLabs multilingual** adapter as a drop-in alternative if you want a warmer character voice. |
| C2 | **~92% of all spoken audio is pre-generated at build time** and served from CDN. Only child-name insertions and a small praise pool are synthesised live, then cached forever by content hash. | Drives steady-state TTS cost to near zero and playback latency below 150 ms — which matters far more for this population than voice novelty. |
| C3 | **ASR: Azure Speech `ar-EG` streaming**, with **OpenAI `gpt-4o-transcribe`** as a fallback/second-opinion provider behind the same interface. | Two providers because child speech is hard, and disagreement between them is itself a useful signal. |
| C4 | **Child ASR is advisory, never a gate.** Children with Down syndrome frequently have reduced speech intelligibility (hypotonia, childhood apraxia, oro-facial structure); no commercial ASR is validated on this population in Egyptian Arabic. Expressive tasks therefore always offer: accept-on-effort after 2 attempts, a caregiver "he said it right ✅" override, and a tap-based equivalent of every voice task. | **Structural, and the single most important accessibility decision in this document.** A product that gates progress on ASR would fail its users. |
| C5 | Voice is **turn-based** (record → VAD endpoint → ASR → decide → play), not bidirectional realtime streaming. | Cheaper, controllable, auditable — and children with DS need slow, predictable turn-taking anyway. Realtime duplex is a post-MVP experiment. |
| C6 | Arabic text is stored twice: **fully vowelised (with tashkeel)** for TTS accuracy, and **unvowelised** for display. Numerals are displayed as **Eastern Arabic (١٢٣)**. | Prevents the classic Arabic TTS mispronunciation problem. |
| C7 | The character **نور (Nour)** is gender-ambiguous by name and is voiced by a single consistent voice for the entire product life. Voice identity is never changed after launch. | Voice consistency is a comprehension aid for this population, not a branding choice. |

## D. Technical

| # | Assumption | Rationale / impact |
|---|---|---|
| D1 | **LLM: Claude `claude-opus-5`** for every reasoning call. Cost is controlled by `output_config.effort` tiers (`low` / `medium` / `high`) plus prompt caching, **not** by downgrading models. | Quality where a wrong judgement affects a child. Effort tiering + caching lands at ≈ $0.14 per learning session. The model ID is a single config constant if you want to change it. |
| D2 | **Orchestration: LangGraph** (`langgraph` + `langchain-anthropic`) for the two stateful graphs (PGEE session, tutor session). Plain SDK calls for single-shot judgements. | You asked for LangChain; LangGraph is the right member of that family for stateful, checkpointed, resumable sessions with interrupts. |
| D3 | **Stack:** Next.js 15 (App Router, TypeScript, Tailwind) PWA for all three frontends; **FastAPI (Python 3.12)** modular monolith for the backend; PostgreSQL 16 + pgvector; Redis 7; S3-compatible object storage behind CloudFront. Monorepo via pnpm + Turborepo; Python deps via uv. | Python backend because the AI stack is Python-first. One language boundary, not three. |
| D4 | **Deployment: AWS `me-south-1` (Bahrain)** — lowest latency to Egypt, keeps data in-region. ECS Fargate + RDS + ElastiCache + S3 + CloudFront, provisioned with Terraform. | [08](08-infrastructure.md) includes a Hetzner + Coolify budget alternative at roughly one-fifth the cost. |
| D5 | **Auth: phone number + SMS OTP** primary (Egyptian norm), email + password secondary. JWT access token 15 min, rotating refresh 30 days. SMS via a local aggregator behind an `SmsProvider` interface. | Children never authenticate. The child app is entered from the caregiver's authenticated session and is PIN-locked on exit. |
| D6 | **Background jobs: ARQ** (async Redis queue) — report generation, TTS pre-generation, nightly BKT recomputation, reminder scheduling. | Async-native and far lighter than Celery. |
| D7 | **LLM observability: Langfuse** (self-hosted) for tracing, prompt versioning and eval datasets; OpenTelemetry → Grafana for everything else. | Prompt changes must be versioned and A/B-able without a deploy. |
| D8 | All AI-facing text is **pseudonymised at the LLM boundary** — child name → `{{CHILD}}`, caregiver name → `{{CAREGIVER}}` — and rehydrated on the way back. Raw child audio is **not retained by default**; opt-in only, 30-day TTL, used solely to build a per-child pronunciation reference. | See [07](07-security-privacy.md). |
| D9 | "Bug-free MVP" is operationalised as: **≥ 85% line coverage on the deterministic engines, 100% branch coverage on scoring and guardrail code, contract tests generated from the OpenAPI spec, a 120-case AI eval suite that must score ≥ 95% before any prompt ships, and a red-team suite that must pass 100%.** | See [10](10-test-prompts.md). |

## E. Compliance

| # | Assumption | Rationale / impact |
|---|---|---|
| E1 | **Egypt Personal Data Protection Law No. 151/2020** applies. We also build to **GDPR** and **COPPA-equivalent** standards because they are stricter and because NGO and EU funders will ask. | Explicit consent capture, data export, deletion, DPO contact, processing register. |
| E2 | Child data is **sensitive personal data**. Consent is given by the caregiver, is granular (7 separate toggles), is versioned, and each toggle is revocable without deleting the account. | See the consent model in [02](02-data-model.md) and [07](07-security-privacy.md). |
| E3 | **Zero third-party analytics, ad SDKs, or session-replay tools.** First-party event telemetry only. | Non-negotiable for a child-disability product. |
| E4 | Sub-processors (Anthropic, Microsoft Azure Speech, AWS, the SMS aggregator) are disclosed in the privacy notice, covered by DPAs, and configured for **no training on our data**. | Anthropic API data is not used for training by default. Azure Speech "no logging" must be explicitly enabled — it is not the default. |

---

## Decisions you should actively review

1. **The AI can withhold mastery but never grant it.** (B9) — the safest reading of "AI determines if it was learned."
2. **ASR never blocks a child.** (C4) — a correctness decision about your actual users that changes what the product *is*.
3. **A closed item bank the AI selects from and never authors.** (B2) — the difference between a defensible product and a liability.
4. **Turn-based voice, not realtime duplex.** (C5) — cheaper and better for the population, but less magical in a demo.
5. **PWA, not native.** (A6) — trades polish for speed and over-the-air fixes.
6. **Opus 5 everywhere with effort tiering, rather than a cheap-model tier.** (D1) — you can move the low-stakes calls to Haiku 4.5 with a one-line change; I did not, because misjudging a child's progress is not a low-stakes call.

## Open questions

These need a human answer. None of them block the *build* — each has a default that lets development proceed.

| # | Question | Blocks | Default if unanswered |
|---|---|---|---|
| **O1** | Do you hold a **licence for the Portage Guide**, or do we author an original PGEE-compatible bank with your clinical partner? | PGEE go-live (not the build — the engine works on any bank) | Build against a **120-item synthetic development bank** shipped as seed data and watermarked `NOT FOR CLINICAL USE`; swap at go-live. |
| **O2** | Who is the **named clinician** reviewing escalations and signing the report template? | Escalation workflow; GA launch | Escalations queue to an admin inbox and the caregiver is told a specialist will review within 48 hours. **Must not ship without a real human behind that promise.** |
| **O3** | Do you have **licensed illustration assets**, or do we commission them? Roughly 90 concepts × 1 hero image + 2 distractors. | Content pipeline | Assume commissioned flat-vector illustrations, culturally Egyptian (a *kobbaya* glass, a *ta'meya* plate), against a documented style guide. Generated assets are acceptable for internal testing only. |
| **O4** | Budget ceiling for AI spend per child per month? | Effort-tier configuration | Assume **$6 per child per month**. The design lands at ≈ $4.20. |
| **O5** | Is there existing brand, naming or visual identity? | Frontend | Assume greenfield. The design tokens in [06](06-frontend-ux.md) are a complete, accessible starting palette. |
| **O6** | Which centre, and how many families, for the first pilot? | UAT plan | Assume **8 families through one early-intervention centre in Cairo**, a 6-week supervised pilot before open registration. |
