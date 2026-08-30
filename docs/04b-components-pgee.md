# 04b — Components: PGEE Assessment

Covers **C03 Assessment Engine** (deterministic) and **C04 PGEE AI Orchestrator** (LangGraph).

The split is the whole point. C03 could ship alone as a plain digital checklist and be clinically correct. C04 makes it 40% shorter and much kinder to a tired parent — and if C04 fails entirely, C03 still ships a valid assessment.

---

## C03 — Assessment Engine

### Purpose
Own the item bank, administer items according to basal/ceiling rules, propagate evidence, and compute developmental age, developmental quotient, and deltas. **Zero AI. Zero I/O in the core.**

### Module layout

```
app/modules/assessment/
  domain/
    bands.py          band arithmetic, age-equivalent interpolation
    basal_ceiling.py  the administration rules
    scoring.py        DA / DQ / deltas
    propagation.py    implied-pass expansion
    state.py          frozen dataclasses — the entire engine state
  service.py          orchestrates domain + repository, transactional
  repository.py
  router.py
  schemas.py
```

`domain/` is pure. Given the same `AssessmentState` it always returns the same result. This is what makes 100% branch coverage on scoring achievable and meaningful.

### Core state

```python
@dataclass(frozen=True, slots=True)
class ItemRef:
    id: str
    domain: str
    band: int
    sequence: int
    ordinal: int          # global position within the domain, across bands

@dataclass(frozen=True, slots=True)
class DomainState:
    domain: str
    entry_band: int
    answered: Mapping[str, str]        # item_id -> verdict
    basal_ordinal: int | None          # highest ordinal where the basal run ends
    ceiling_ordinal: int | None
    cursor_up: int                     # next ordinal to try going up
    cursor_down: int                   # next ordinal to try going down
    complete: bool

@dataclass(frozen=True, slots=True)
class AssessmentState:
    child_months: float                # corrected age
    bank_version: str
    rules: Rules
    domains: Mapping[str, DomainState]
```

### Administration algorithm

```python
def next_candidates(state: AssessmentState, bank: Bank, limit: int = 5) -> list[ItemRef]:
    """Deterministic. Returns the items that are legal to ask right now.

    Order of business per domain:
      1. Establish a basal: walk DOWN from the entry band until `basal_consecutive`
         consecutive `yes` answers exist. Items below a confirmed basal are credited
         without being asked.
      2. Then walk UP until `ceiling_consecutive` consecutive non-`yes` answers exist.
         Items above a confirmed ceiling are scored `no` without being asked.
    """
    out: list[ItemRef] = []
    for ds in _incomplete_domains(state):
        if ds.basal_ordinal is None:
            nxt = bank.at(ds.domain, ds.cursor_down)
        else:
            nxt = bank.at(ds.domain, ds.cursor_up)
        if nxt is not None:
            out.append(nxt)
    # Interleave so a parent is never asked 20 motor questions in a row,
    # but keep the current domain first so the AI ranker can prefer continuity.
    return _interleave_preferring_current(out, state)[:limit]


def record(state: AssessmentState, item: ItemRef, verdict: str,
           bank: Bank) -> AssessmentState:
    ds = state.domains[item.domain]
    answered = {**ds.answered, item.id: verdict}

    if ds.basal_ordinal is None:
        basal = _find_basal(answered, bank, ds.domain, state.rules.basal_consecutive)
        if basal is not None:
            ds = replace(ds, basal_ordinal=basal,
                         cursor_up=basal + 1, answered=answered)
        elif item.ordinal == 0:
            # Floor of the bank reached without a basal: treat ordinal 0 as the basal.
            ds = replace(ds, basal_ordinal=0, cursor_up=1, answered=answered)
        else:
            ds = replace(ds, cursor_down=item.ordinal - 1, answered=answered)
    else:
        ceiling = _find_ceiling(answered, bank, ds.domain,
                               state.rules.ceiling_consecutive, ds.basal_ordinal)
        ds = replace(ds, answered=answered, cursor_up=item.ordinal + 1,
                     ceiling_ordinal=ceiling,
                     complete=ceiling is not None or
                              item.ordinal >= bank.max_ordinal(ds.domain))
    return replace(state, domains={**state.domains, item.domain: ds})
```

**Design notes**

- `emerging` counts as a **non-pass for ceiling purposes** but earns partial credit in scoring. This is the conservative reading and prevents a run of "sort of" answers from inflating a ceiling.
- `not_applicable` (e.g. a motor item for a child who uses a wheelchair) is excluded from both runs and from the denominator, and is recorded with a caregiver note.
- `skipped` (caregiver declines, or a red flag suppressed the item) breaks a consecutive run without contributing to it — the run restarts.
- If the caregiver corrects an earlier answer, a **new** `assessment_responses` row is written with `superseded_by` set on the old one, and the engine **replays from scratch**. Replay is cheap (< 5 ms for 600 items) and it is the only way to keep basal/ceiling consistent after an edit. Never mutate in place.

### Evidence propagation

```python
def propagate(state, item, verdict, bank) -> list[tuple[ItemRef, str]]:
    """A `yes` on a higher-order skill implies `yes` on its prerequisites."""
    if verdict != "yes":
        return []
    implied, seen = [], {item.id}
    stack = list(bank.implies_pass(item.id))
    while stack:
        iid = stack.pop()
        if iid in seen or iid in state.domains[bank.domain_of(iid)].answered:
            continue
        seen.add(iid)
        implied.append((bank.ref(iid), "yes"))
        stack.extend(bank.implies_pass(iid))
    return implied
```

Propagated answers are written with `source='evidence_propagated'`, are **excluded from basal and ceiling run detection** (they were not observed), but **are counted in scoring**. Every one is listed on the review screen with a one-tap "actually, no" correction. This removes 15–25% of items from a typical session.

### Scoring

```python
def domain_score(ds: DomainState, bank: Bank, rules: Rules,
                 child_months: float) -> DomainScore:
    below_basal = ds.basal_ordinal or 0            # all credited as pass
    yes_count      = sum(1 for v in ds.answered.values() if v == "yes")
    emerging_count = sum(1 for v in ds.answered.values() if v == "emerging")

    raw = below_basal + yes_count + rules.emerging_credit * emerging_count
    raw = min(raw, bank.count(ds.domain))

    da_months = age_equivalent(raw, bank.cumulative_by_band(ds.domain))
    dq = (da_months / child_months * 100) if child_months > 0 else 0.0
    return DomainScore(domain=ds.domain, raw=raw,
                       developmental_age_months=round(da_months, 2),
                       developmental_quotient=round(dq, 1), ...)


def age_equivalent(raw: float, cumulative: list[tuple[int, int, int, int]]) -> float:
    """cumulative = [(band_id, cum_items_through_band, min_months, max_months), ...]

    Linear interpolation inside the band the raw score lands in. Deliberately simple
    and fully explainable to a clinician — no smoothing, no IRT, no black box.
    """
    prev_cum, prev_max = 0, 0
    for _band, cum, lo, hi in cumulative:
        if raw <= cum:
            span = cum - prev_cum
            frac = (raw - prev_cum) / span if span else 0.0
            return lo + frac * (hi - lo)
        prev_cum, prev_max = cum, hi
    return float(prev_max)
```

**Deltas.** For each domain, `delta_da_months = DA_now − DA_prev` and `elapsed_months` between assessments. The caregiver-facing framing is *"في الست شهور اللي فاتت، تقدّم بـ X شهور في اللغة"* — growth in the child's own terms. DQ change is computed but is **not** shown on the dashboard (assumption B7).

### Reassessment gating
`POST /assessments` is refused with 409 if the last completed assessment is younger than `min_days_between` (150), unless the caller has the `therapist` role and supplies `override_reason`, which is written to `audit_log`.

### Failure modes

| Case | Behaviour |
|---|---|
| Caregiver abandons at item 12 | Status `paused`; resumable for 14 days from the LangGraph checkpoint; then `abandoned` and excluded from scoring |
| Item bank version changes mid-assessment | The assessment pins `bank_version` at creation; migrations never touch in-flight assessments |
| A domain has no items in the entry band | Falls back to the nearest band with items; logged |
| Child age outside the bank's range | Clamp to the nearest band and mark the report `out_of_range=true`, which suppresses DQ entirely |
| Division by zero (CA = 0) | DQ suppressed, DA still reported |

### Definition of done
100% branch coverage on `domain/`. A property-based test (Hypothesis) asserts: replaying any answer sequence in any order that respects the administration rules yields identical scores; DA is monotonically non-decreasing in the number of passes; DQ is never negative or > 200 without a warning flag.

---

## C04 — PGEE AI Orchestrator

### Purpose
Wrap C03 in a LangGraph session that lets a caregiver answer in their own words, asks a good clarifying question when the answer is ambiguous, chooses a considerate question order, and produces a warm Arabic report from numbers the engine computed.

### Graph definition

```python
# app/modules/assessment_ai/graph.py
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

class PgeeState(TypedDict):
    assessment_id: str
    child_ctx: dict            # pseudonymised, stable across the session (cache-friendly)
    engine: dict               # serialised AssessmentState
    candidates: list[dict]
    current_item: dict | None
    pending_answer: dict | None
    probes_used: int
    transcript: list[dict]     # for the AI's short-term memory, trimmed to last 8 turns
    ai_degraded: bool
    red_flags: list[dict]
    result: dict | None

g = StateGraph(PgeeState)
g.add_node("candidates",  node_candidates)    # C03, pure
g.add_node("rank",        node_rank)          # DP2
g.add_node("present",     node_present)       # SSE emit, then interrupt
g.add_node("classify",    node_classify)      # DP0
g.add_node("interpret",   node_interpret)     # DP1
g.add_node("probe",       node_probe)         # emit clarifier, then interrupt
g.add_node("record",      node_record)        # C03 record + propagate, transactional
g.add_node("escalate",    node_escalate)      # C11
g.add_node("finalise",    node_finalise)      # C03 scoring
g.add_node("report",      node_report)        # DP4 + L4/L5

g.set_entry_point("candidates")
g.add_conditional_edges("candidates",
    lambda s: "finalise" if not s["candidates"] else "rank")
g.add_edge("rank", "present")
g.add_conditional_edges("present",
    lambda s: "record" if s["pending_answer"]["source"] == "tap" else "classify")
g.add_conditional_edges("classify",
    lambda s: "escalate" if s["red_flags"] else "interpret")
g.add_conditional_edges("interpret",
    lambda s: "probe" if s["needs_probe"] and s["probes_used"] < 2 else "record")
g.add_edge("probe", "classify")
g.add_edge("escalate", "record")
g.add_edge("record", "candidates")
g.add_edge("finalise", "report")
g.add_edge("report", END)

graph = g.compile(checkpointer=AsyncPostgresSaver(pool),
                  interrupt_before=["classify", "record"])
```

`interrupt_before` is what makes "close the tab and come back on Thursday" work: the graph halts holding a durable checkpoint, and resuming replays from exactly that node.

### Node contracts

| Node | Calls | Guardrails | Fallback |
|---|---|---|---|
| `candidates` | C03 `next_candidates` | — | n/a (pure) |
| `rank` | DP2, `effort=low` | L3 in-set | `candidates[0]` |
| `classify` | DP0, `effort=low` | fails closed | treat as flagged |
| `interpret` | DP1, `effort=medium` | L2 schema, L3 verdict enum + probe allow-list, L1 injection wrap | show the 3 tap buttons |
| `probe` | template lookup by `probe_id` | probes are **pre-written by the clinical partner**, never AI-authored | skip to `record` with `unclear` |
| `record` | C03 `record` + `propagate` | transactional; idempotent by `(assessment_id, item_id, client_seq)` | retry once, then 500 |
| `finalise` | C03 scoring | — | n/a |
| `report` | DP4, `effort=high` | L4 numeric equality, L5 safety, reading level | template report, `is_template=true`, clinician flag |

**Probes are templates, not generated text.** The AI selects a `probe_id` from a per-item list written by a clinician (typically 2–3 per item, e.g. *"لما بتقوليله، بيعمل كده لوحده ولا محتاج مساعدة؟"*). This eliminates an entire class of risk — an AI cannot ask a leading, distressing, or clinically inappropriate follow-up if it can only pick from a reviewed list.

### Streaming to the client

Server-Sent Events on `GET /assessments/{id}/stream`:

| Event | Payload |
|---|---|
| `item` | `{item_id, prompt_ar, example_ar, criterion_ar, domain, progress: {answered, estimated_total}}` |
| `probe` | `{probe_id, text_ar}` |
| `interpreted` | `{verdict, confidence, rationale_ar}` — shown as a confirmable chip, not silently applied |
| `propagated` | `{items: [{id, prompt_ar}], count}` — "we also filled in 4 answers for you" |
| `progress` | `{percent, domains_complete}` |
| `escalation` | `{category, message_ar}` — fixed human copy |
| `scoring` | `{}` — engine is finalising |
| `report_ready` | `{report_url}` |
| `degraded` | `{reason}` — the UI switches to tap-only and says so plainly |

**Interpretation is always confirmable.** When the AI reads "he does it if I remind him" as `emerging`, the caregiver sees a chip: *"فهمت إن ده **بيحصل بمساعدة**"* with a one-tap change. This is not a UX nicety — it is the mechanism by which the caregiver, not the model, remains the source of truth, and it generates the labelled data that improves the eval set.

### Progress estimation
Total item count is unknown until ceilings are found. The UI shows a **range that only ever narrows** (`"حوالي ٢٠–٣٠ سؤال"` → `"فاضل حوالي ٨"`), computed from the median session length for children in the same entry band. A progress bar that goes backwards is a trust-destroying bug; the range framing makes it structurally impossible.

### Report generation
Runs as an ARQ job, not in the request. Input to DP4 is strictly:

```json
{
  "child": {"age_months": 42, "sex": "male", "comms_level": "single_words",
            "assessment_number": 2},
  "domains": [{"domain": "language", "da_months": 24.5, "dq": 58.3,
               "delta_da_months": 4.1, "elapsed_months": 6.0,
               "top_passes": ["...", "..."], "first_fails": ["...", "..."]}],
  "previous": {"date": "2026-02-20", "domains": [...]},
  "linked_skills_to_focus": ["color_red", "body_eye", "..."]
}
```

Every number the model may write is in that object. L4 then verifies that every numeral in the output is one of them. Output is persisted to `assessment_reports` and the caregiver is pushed a `report_ready` notification.

### Definition of done
The whole graph runs end-to-end against **recorded LLM fixtures** with no network. A chaos test that forces every AI node to fail still produces a valid, scored, template-reported assessment. Resume-after-14-days replays correctly. The eval gates in [03](03-ai-architecture.md) §8 are green.
