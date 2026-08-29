# REVIEW-QUEUE

**Read this file first.** Every entry is an open gate that only a person can
close. Each is written to be actionable without reading any transcript: what to
look at, what question to answer, and what it unblocks.

Nothing here has been closed by the orchestrator, and nothing here will be.

_Last updated: 2026-08-29 · opened during P00_

---

## #1 — Arabic UI strings are agent-written placeholders

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | Stage 5 content sign-off. Does **not** block P01–P15 development. |
| **Who** | Native Egyptian Arabic speaker (SETUP §3) |
| **Effort** | 10 minutes now; the full ~3 days comes at Stage 3 and Stage 5 |

**What I built.** `apps/web/src/messages/ar-EG.json` — five user-facing strings so
the three route groups render and the banned-terms lint has something to lint.
The file carries a `PLACEHOLDER — NOT FOR CLINICAL USE` header in `_meta`.

**What I need.** Nothing yet — this is registered now so it cannot be forgotten
later. At Stage 3 and Stage 5 you will be asked to review every string in the
bundle. **What matters now is only that you know no Arabic copy in this
repository has been seen by a native speaker.**

**What happens next.** P12/P13 will grow this bundle substantially. Each addition
stays a placeholder until signed off.

---

## #2 — Decision O1: Portage Guide licensing

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | PGEE **go-live**, not the build. P04 works on any item bank. |
| **Who** | You (a licensing question, not an engineering one) |
| **Effort** | Unknown — depends on the licensor |

**What I need.** Licensed Portage, or an original PGEE-compatible bank authored
with your clinician? `SETUP.md` §1 flags this as week-1 urgent.

**Why it is urgent even though it does not block me.** Every hour spent on the AI
layer is wasted if the assessment content cannot legally ship. I will build P04
against a synthetic 120-item bank watermarked `NOT FOR CLINICAL USE` and swap it
later, which is fine — but the swap has to be *possible*.

**Default if you say nothing.** Synthetic bank, watermarked, engine built to
accept any bank.

---

## #3 — Decision O2: the named clinician

| | |
|---|---|
| **Status** | 🔴 open · 0 days |
| **Blocks** | **Stage 2 gate** — the earliest hard human dependency in the project |
| **Who** | You, then them |
| **Effort** | Recruiting time; then ~2 days of their time spread across the build |

**What I need.** A named developmental paediatrician or early-intervention
specialist who will (a) verify six hand-calculated scoring cases at the Stage 2
gate, (b) sign the item bank and report template, and (c) staff the escalation
rota behind the 48-hour promise.

**Why this one is different.** Stage 2 cannot be crossed without (a). I can build
P04 completely and I can run an independent-oracle comparison against it — but a
disagreement between two sessions I ran is evidence, not verification. A wrong
developmental age reaching a parent is silent until it is not.

**What happens if you delay.** I keep building — P01, P02, P15, then P06/P07 on
the Stage 3 track. P04 will sit finished and unverified. Nothing after Stage 2
ships.

**Also note:** the escalation copy in SETUP §4 must be human-written and
clinician-reviewed, **never model-generated**. I will not draft it.

---

## Not open, for the record

These are *not* in the queue because they are mechanical and mine to close:

- The random-tapper-never-reaches-mastery test (P07) — mechanical, and it is the
  real safety net. I will run it and report the number.
- Every guard check, lint rule and coverage gate.
- `terraform plan` in P15. `terraform apply` is never run unattended.
