# سند · SANAD — AI-Assisted Arabic Early-Learning & Developmental Tracking Platform

> Working name: **سند (Sanad)**. Arabic-first (Egyptian dialect) e-learning + developmental-progress platform for children with Down syndrome and their caregivers.

This folder is the complete architecture package: high-level design, per-component detailed design, data model, AI architecture with guardrails, API contracts, security/compliance, infrastructure, and **copy-paste build + test prompts** so each component can be developed and verified in isolation before integration.

## Reading order

| # | Document | What it answers |
|---|---|---|
| 00 | [Assumptions & Scope](00-assumptions.md) | Every detail I invented, why, and what a human must still decide |
| 01 | [High-Level Design](01-hld.md) | System context, containers, core flows, stack, NFRs, cost model |
| 02 | [Data Model](02-data-model.md) | ERD, full PostgreSQL DDL, retention, seed data |
| 03 | [AI Architecture](03-ai-architecture.md) | Model routing, LLM gateway, LangGraph graphs, 7-layer guardrails, prompts, evals |
| 04a | [Components — Platform Core](04a-components-platform.md) | C01 Identity, C02 Child Profile, C09 Progress, C10 Notifications, C15 LLM Gateway |
| 04b | [Components — PGEE Assessment](04b-components-pgee.md) | C03 Assessment Engine, C04 PGEE AI Orchestrator |
| 04c | [Components — Child Learning](04c-components-learning.md) | C05 Content, C06 Adaptive Engine (BKT), C07 Tutor Orchestrator |
| 04d | [Components — Voice](04d-components-voice.md) | C08 Voice Gateway: TTS, ASR, pronunciation scoring |
| 04e | [Components — Safety & Clients](04e-components-safety-clients.md) | C11 Guardrail/Audit, C12 Caregiver app, C13 Child app, C14 Clinician console |
| 05 | [API Contracts](05-api-contracts.md) | Every endpoint, request/response schema, error model, SSE events |
| 06 | [Frontend, UX & Accessibility](06-frontend-ux.md) | Down-syndrome-specific interaction design, Arabic RTL, design tokens |
| 07 | [Security, Privacy & Compliance](07-security-privacy.md) | Threat model, PII at the LLM boundary, Egypt PDPL/GDPR, consent |
| 08 | [Infrastructure & DevOps](08-infrastructure.md) | AWS topology, CI/CD, observability, cost controls, runbooks |
| 09 | [Build Prompts](09-build-prompts.md) | One self-contained development prompt per component |
| 10 | [Test Prompts & Test Plan](10-test-prompts.md) | Per-component test prompt, AI eval harness, red-team suite, UAT |
| 11 | [Integration Plan & Roadmap](11-integration-roadmap.md) | Wiring order, integration gates, 14-week MVP plan, launch checklist |
| **12** | **[Stack Revision: Groq & Self-Hosted Voice](12-stack-revision-groq-selfhosted-voice.md)** | **Supersedes the provider choices in 03, 04d, 08 and 00 §C/D1/D4.** Groq free-tier capacity analysis, per-decision-point model routing, VoxCPM2 voice cloning, Qwen3-ASR self-hosting, revised cost model |

### Not architecture, but next to it

| Folder | What |
|---|---|
| [`setup/`](setup/README.md) | Procedures for the things only a human can do — casting and recording the Nour voice, Groq's data terms and the two model licences, the remaining credentials. `SETUP.md` at the repo root is the register; this is the how. |
| [`runbooks/`](runbooks/README.md) | One file per operational situation from 08 §7. None rehearsed — there is no deployed environment. |
| [`adr/`](adr/) | Decision records. 001 and 011–017 exist; 002–010 are referenced by code and were deliberately not back-filled (BLOCKED.md #5). |

> **Read 12 alongside 03 and 04d.** The architecture is unchanged — every guardrail, fallback and closed-set constraint stands. Only the providers behind C15 (LLM Gateway) and C08 (Voice Gateway) change, which is exactly what those components were designed to allow.

## The one architectural idea that matters

> **Deterministic core, AI at bounded decision points.**

Every number a caregiver sees (developmental age, mastery %, domain score) is computed by deterministic, unit-tested code. The LLM never produces a score, never invents an assessment item, never diagnoses. The LLM does four things only:

1. **Interpret** free-form human input into a closed enum (`yes` / `emerging` / `no`).
2. **Rank** a candidate set that deterministic code produced (it may reorder; it may not add).
3. **Narrate** numbers that deterministic code already computed (validated by equality assertion).
4. **Flag** — raise concerns, lower confidence, escalate to a human. It may always be *more* conservative; it may never be *less*.

Every one of these is schema-constrained, allow-listed, and validated after the fact. If validation fails, the deterministic fallback ships. This is what makes an AI product in a clinical-adjacent, child-facing domain safe enough to launch.
