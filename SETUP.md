# SETUP — what the human supplies

Everything here is something an agent cannot produce for you. The orchestrator keeps the **Status** column current; you fill the gaps.

**The good news first: none of this is needed to start.** The architecture runs on fixtures and deterministic fallbacks by design, so P00–P15 can be built end to end with zero credentials. Keys are needed at four specific gates, listed below.

---

## 1. Decisions — the only two that are genuinely urgent

| # | Decision | Blocks | Default if you say nothing | Status |
|---|---|---|---|---|
| **O1** | **Portage Guide: licensed, or do we author an original PGEE-compatible bank with your clinician?** | PGEE **go-live** — not the build. The engine works on any bank. | Build on the synthetic 120-item bank, watermarked `NOT FOR CLINICAL USE`, swap later | ☐ open |
| **O2** | **Who is the named clinician** who reviews escalations and signs the report template? | Stage 2 gate; GA launch | Escalations queue to an admin inbox — **must not ship without a real person behind the 48-hour promise** | ☐ open |
| O3 | Licensed illustrations, or commission them? ~90 concepts × 3 images | Stage 5 content | Placeholder shapes; generated assets for internal testing only | ☐ open |
| O4 | Monthly AI budget ceiling per child | Effort-tier config | $6/child/month (design lands at $0.14–0.37 after the doc 12 revision) | ☐ open |
| O5 | Existing brand, name, visual identity? | Frontend | Greenfield; the tokens in `docs/06 §2` are a complete accessible palette | ☐ open |
| O6 | Which centre, how many families, for the pilot? | UAT plan | 8 families, one Cairo early-intervention centre, 6 weeks | ☐ open |

Answer **O1 and O2 in week 1.** O1 is a licensing question, not an engineering one — every hour spent on the AI layer is wasted if the assessment content cannot legally ship. The rest can ride on their defaults.

---

## 2. API keys — needed at four gates, not before

| Key | Needed for | Needed at | Without it | Status |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | DP1 interpret + DP4 report (`docs/12 §2` routing) | **Gate 4** — eval runs and live-AI smoke tests | Everything builds and tests on recorded fixtures | ☐ |
| `GROQ_API_KEY` | DP0, DP2, DP3, session summaries | **Gate 4** — same | Same | ☐ |
| Cloudflare R2 — account id, access key, secret | Audio + media hosting | **Gate 5** — P09 render, P06 publish | MinIO in docker-compose covers local dev completely | ☐ |
| GPU provider token (Thunder Compute or equivalent) | VoxCPM2 voice render, Qwen3-ASR host | **Gate 5** — P09 | Placeholder tones; the scoring logic still tests fully | ☐ |
| SMS aggregator credentials | OTP delivery | **Stage 1**, real-device testing only | `NullSms` prints the code to console — full auth flow works | ☐ |
| `AZURE_SPEECH_KEY` *(optional)* | Fallback TTS if VoxCPM2 loses the listening test | Gate 5, contingency | Not needed unless the listening test fails | ☐ |

**Not needed at all:** Langfuse (self-hosted in docker-compose), Postgres/Redis/MinIO (all local), OpenAI (dropped in the doc 12 revision).

**Before you paste any key:** confirm Groq's Services Agreement and DPA — no training on our data, a stated retention period, a signed DPA. This is child health-adjacent data in a PDPL jurisdiction. Blocking for the pilot, not for development. (`docs/12 §2`)

---

## 3. People — start recruiting now, they have lead times

| Role | Needed for | When | Time needed | Status |
|---|---|---|---|---|
| **Developmental paediatrician / early-intervention specialist** | Verify 6 hand-calculated scoring cases; sign the item bank and report template; staff the escalation rota | **Stage 2 gate** — earliest hard dependency | ~2 days spread over the build, then on-call | ☐ |
| **Native Egyptian Arabic speaker** | Review all 88 curriculum labels, every UI string, and the rendered audio corpus | Stage 3 and Stage 5 | ~3 days total | ☐ |
| **Voice talent — Egyptian woman, warm, used to speaking with small children** | 20–30 min studio recording → cloned as "نور" (Nour), frozen for the product's life | **Stage 5, but book early** | Half a day + a perpetual synthetic-reproduction release | ☐ |
| **Speech-language therapist** | Agree expected verdicts on the 60-pair pronunciation corpus; calibrate the 0.55 threshold | Stage 5 | ~1 day | ☐ |
| **Occupational therapist** | Accessibility review of the child app with real children | Stage 5 gate, and again before GA | ~1 day | ☐ |
| **Independent red-teamer** | Write the 60-case adversarial corpus — must not be whoever wrote the prompts | Stage 4 gate | ~1 day | ☐ |
| **Second annotator** | Double-annotate the 120-case `interpret_ar.jsonl` eval set | Stage 4 | ~2 days | ☐ |

The voice talent and the clinician are the two with real calendar lead time. Everything else can be arranged inside a week.

---

## 4. Content you supply

| Item | Detail | Status |
|---|---|---|
| Item bank | Licensed Portage, or original items authored with your clinician (per O1) | ☐ |
| Illustrations | ~90 concepts × 1 hero + 2 distractors, culturally Egyptian, flat vector, to a documented style guide | ☐ |
| Voice recording | 20–30 min, quiet room, 48 kHz, script provided by the agent | ☐ |
| Escalation copy | 7 category templates, human-written, clinician-reviewed — **never model-generated** | ☐ |

---

## 5. Environment

Already verified on this machine: `pandoc 3.9`, MiKTeX (xelatex/lualatex), `node`, `npm`, `python 3.11`.

Still needed: **Docker Desktop** (Postgres, Redis, MinIO, Langfuse), **uv**, **pnpm**, and **git init** — the orchestrator handles the last three in P00.

---

## 6. Your review rhythm

You are asked for five things, five times.

| Gate | What you review | Roughly |
|---|---|---|
| **Stage 1** | Auth and consent work; CI guards fail correctly when violated | Week 3 |
| **Stage 2** | **Clinician confirms 6 scoring cases.** The highest-consequence review in the project | Week 5 |
| **Stage 3** | A tap-only learning session; confirm the random tapper never reaches mastery | Week 7 |
| **Stage 4** | Independent red-team results; every AI switch degrades cleanly | Week 10 |
| **Stage 5** | OT accessibility review; native-speaker content and audio sign-off | Week 13 |

Between gates, the orchestrator works unattended and keeps `PROGRESS.md` and `REVIEW-QUEUE.md` current. **Read `REVIEW-QUEUE.md` first** — it is written to be actionable without reading any transcript.
