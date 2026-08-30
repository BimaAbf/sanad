# 04c — Components: Child Learning

Covers **C05 Content Service**, **C06 Adaptive Learning Engine** (deterministic), **C07 Tutor Orchestrator** (LangGraph).

---

## C05 — Content Service

### Purpose
Own the curriculum: 88 skills, 9 activity templates, ~500 generated activities, media assets, and the audio manifest. Serve a **complete, self-contained session manifest** so the child app can run a whole session with no further network calls.

### Responsibilities
1. Curriculum CRUD (via C14 console; content editors are not engineers).
2. Activity instantiation: `template × skill × distractors → activity`.
3. Distractor selection.
4. Session manifest assembly with pre-signed CDN URLs.
5. TTS pre-generation orchestration (delegates synthesis to C08).
6. Content versioning and publish/rollback.

### Distractor selection — the errorless-learning rule

Wrong answers are not random. For a child with Down syndrome, a distractor that is too similar turns a comprehension task into a visual-discrimination task and manufactures failure.

```python
def choose_distractors(skill: Skill, n: int, tier: int,
                       child_state: SkillStates) -> list[Skill]:
    pool = [s for s in skill.distractor_pool if s.is_active]

    if tier <= 2:
        # Maximum contrast: different category, different colour family,
        # different word length, different initial phoneme.
        pool = [s for s in pool
                if s.category != skill.category
                and _colour_distance(s, skill) > 0.4
                and s.phonemes[0] != skill.phonemes[0]]
        pool.sort(key=lambda s: -_visual_distance(s, skill))
    else:
        # Tier 3+: deliberately introduce near-misses, but only for skills the
        # child has already mastered — confusion should be informative, not defeating.
        near = [s for s in pool if child_state.is_mastered(s.id)]
        pool = near or pool
        pool.sort(key=lambda s: _visual_distance(s, skill))

    # Never repeat a distractor that was used in the last 3 activities.
    return _dedupe_recent(pool, child_state.recent_distractors)[:n]
```

A red card never sits beside an orange card at tier 1. A `فرشة سنان` never sits beside a `مشط` until both are mastered.

### Session manifest

```jsonc
{
  "session_id": "0192...",
  "child": { "wait_time_ms": 8000, "max_choices": 2,
             "audio_rate_pct": 85, "calm_mode": false },
  "activities": [
    {
      "id": "…", "kind": "listen_point", "skill_id": "color_red",
      "instruction_ar": "وريني الأحمر",
      "instruction_audio": "https://cdn/…/a3f9.opus",
      "choices": [
        { "skill_id": "color_red",  "image": "https://cdn/…/red.webp",
          "alt_ar": "مربع أحمر", "correct": true },
        { "skill_id": "body_eye",   "image": "https://cdn/…/eye.webp",
          "alt_ar": "عين", "correct": false }
      ],
      "prompt_ladder": [
        { "level": "gestural",       "audio": "…/hint1.opus", "highlight": "correct" },
        { "level": "partial_verbal", "audio": "…/hint2.opus" },
        { "level": "full_model",     "audio": "…/model.opus", "auto_select": true }
      ],
      "success_audio": ["…/bravo1.opus", "…/bravo2.opus"],
      "retry_audio":   ["…/tryagain1.opus"]
    }
  ],
  "closing_audio": "…/goodbye.opus",
  "expires_at": "2026-08-29T15:40:00Z"
}
```

Everything the session needs is in this document. The child app preloads all of it into the Cache API **before playing the first prompt**, then runs offline. This is why a 30-second network drop is invisible.

### Content publishing
Content lives in a `draft → review → published` workflow. Publishing triggers `tts_pregen` for any new or changed text and does not go live until every referenced audio file exists. A published version is immutable; edits create a new version. Rollback is a pointer change.

### Definition of done
Every skill has a hero image with Arabic alt text, a vowelised label, phonemes, and ≥ 4 distractor candidates. Every activity resolves to real, reachable media. A manifest for any child validates against the JSON schema and every URL returns 200.

---

## C06 — Adaptive Learning Engine

### Purpose
Decide what a child should practise, and know — deterministically — whether they have learned it. No AI in this component at all.

### Bayesian Knowledge Tracing

Per `(child, skill, modality)`:

```python
def bkt_update(st: SkillState, correct: bool, choice_count: int,
               prompt_level: str) -> SkillState:
    # Guess probability is the real chance of a lucky tap, not a constant.
    p_guess = 1.0 / max(choice_count, 2)

    # A success under prompting is weaker evidence. Discount it rather than
    # discard it — discarding loses the fact that the child engaged at all.
    prompt_discount = {"independent": 1.0, "gestural": 0.6,
                       "partial_verbal": 0.35, "full_model": 0.0}[prompt_level]

    L = st.p_known
    if correct:
        num = L * (1 - st.p_slip)
        den = num + (1 - L) * p_guess
    else:
        num = L * st.p_slip
        den = num + (1 - L) * (1 - p_guess)
    posterior = num / den if den > 0 else L

    # Blend toward the posterior in proportion to how independent the response was.
    posterior = L + (posterior - L) * prompt_discount

    # Learning transition
    p_known = posterior + (1 - posterior) * st.p_transit
    return replace(st, p_known=clamp(p_known, 0.001, 0.999))
```

**Parameter choices and why they differ from the literature defaults**

| Param | Default | Ours | Reason |
|---|---|---|---|
| `p_L0` initial known | 0.10 | **0.15** | Many concepts are already familiar from home life (colours, body parts). |
| `p_transit` | 0.10 | **0.25** | Sessions are short and highly repetitive by design; per-opportunity learning is higher than in a classroom study. |
| `p_slip` | 0.10 | **0.25** | Motor imprecision, attention variability, and mis-taps are common and are *not* evidence of not knowing. This is the single most important tuning decision — a low slip rate would punish children for their hands. |
| `p_guess` | 0.20 | **1/n** | Computed from actual choice count. |

These are stored **per skill-state row**, not as global constants, so they can be tuned per category and later fitted from real data (an offline job estimates them by EM once ≥ 200 children have ≥ 30 attempts each).

### Forgetting

Nightly, for every `skill_state` overdue by more than one interval:

```python
def apply_decay(st: SkillState, days_overdue: float) -> SkillState:
    half_life = 14.0 * st.ease_factor / 2.3         # easier skills decay slower
    factor = 0.5 ** (days_overdue / half_life)
    p = 0.15 + (st.p_known - 0.15) * factor          # decays toward prior, never below
    new_state = "lapsed" if st.state in ("mastered", "retained") and p < 0.70 else st.state
    return replace(st, p_known=p, state=new_state)
```

A `lapsed` skill re-enters the review queue at high priority with a lower tier. The caregiver sees this framed as *"نراجع مع بعض"* (let's review together), never as regression.

### Spaced repetition

SM-2 derived, deliberately gentled — intervals grow more slowly than in an adult flashcard system because over-long gaps in this population produce loss, not consolidation.

```python
INTERVALS = [1, 2, 4, 7, 12, 21, 35]     # days, capped

def schedule(st: SkillState, correct: bool, latency_ratio: float) -> SkillState:
    if not correct:
        return replace(st, interval_days=1,
                       ease_factor=max(1.5, st.ease_factor - 0.2),
                       due_at=tomorrow())
    quality = 5 if latency_ratio < 0.6 else 4 if latency_ratio < 1.0 else 3
    ef = clamp(st.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)),
               1.5, 2.6)
    idx = min(bisect(INTERVALS, st.interval_days), len(INTERVALS) - 1)
    return replace(st, ease_factor=ef, interval_days=INTERVALS[idx],
                   due_at=now() + timedelta(days=INTERVALS[idx] * ef / 2.3))
```

### The mastery rule (deterministic ground truth)

```python
def mastery_rule(st: SkillState, attempts: list[Attempt]) -> bool:
    return (
        st.p_known >= 0.90
        and st.distinct_days >= 2
        and st.last_delayed_pass_at is not None      # ≥ 3 days after first correct
        and _independent_ratio(attempts) >= 0.60     # not carried by prompting
    )
```

This is the *only* way `mastery_state` becomes `mastered`. The AI judge in C07 may return `withhold` and block the transition; it can never cause one. Enforced by the `ai_cannot_grant` DB constraint.

`retained` is a further state: a correct independent response ≥ 21 days after mastery. That is the state the caregiver dashboard celebrates, because it is the one that actually means something.

### Candidate generation

```python
def candidates(child_id, now, limit=8) -> list[Candidate]:
    due       = due_reviews(child_id, now, limit=5)          # highest priority
    lapsed    = lapsed_skills(child_id, limit=2)
    new_skill = next_eligible_new(child_id)                  # prerequisites satisfied,
                                                             # lowest intro_order,
                                                             # seeded by PGEE linked_skills
    confidence = random_mastered(child_id, limit=1)          # always end on a win

    return _cap(_dedupe([*lapsed, *due, new_skill, confidence]), limit)
```

**Composition rule:** at most **one new skill per session**. Introducing two competing new items in one 8-minute session is how you get interference and frustration in this population. If the child has ≥ 3 skills in `practising`, no new skill is introduced at all until one graduates.

### Prompt hierarchy (errorless learning)

Every activity has a fixed ladder. The engine records which rung produced the response, and BKT discounts accordingly.

| Rung | Trigger | What happens |
|---|---|---|
| `independent` | first ask | prompt audio, then wait `child.wait_time_ms` |
| `gestural` | no response after wait | repeat the *identical* prompt, gently pulse the correct choice |
| `partial_verbal` | still no response | prompt + first phoneme of the answer (*"الأح…"*) |
| `full_model` | still no response | Nour says the answer, the correct choice highlights and auto-selects, and the child taps to celebrate |

The child **never** reaches a dead end and never sees a failure state. The result is recorded honestly (`prompt_level='full_model'`, which contributes ~nothing to BKT) but the *experience* is a success. That gap between honest measurement and kind presentation is the core of the design.

### Definition of done
Property tests: `p_known` stays in (0,1) over 10,000 random attempt sequences; a child who answers everything correctly at `independent` reaches mastery in a bounded number of sessions; a child who answers randomly **never** reaches mastery, at any choice count, over 500 simulated attempts. That last test is the one that matters — run it in CI.

---

## C07 — Tutor Orchestrator

### Purpose
Run the play session: plan it, react to how it is going, judge what was learned, and tell the caregiver something useful in four lines.

### Graph

```python
class PlayState(TypedDict):
    session_id: str
    child_ctx: dict           # pseudonymised: age band, comms level, calm mode
    candidates: list[dict]
    plan: list[str]
    cursor: int
    attempts: list[dict]
    affect: dict              # rolling engagement signals
    rescued: bool
    verdicts: dict
    summary_ar: str | None

g.add_node("candidates", node_candidates)   # C06
g.add_node("plan",       node_plan)         # DP2, effort=low
g.add_node("manifest",   node_manifest)     # C05
g.add_node("ingest",     node_ingest)       # BKT update, deterministic, per attempt
g.add_node("affect",     node_affect)       # heuristic, no AI
g.add_node("rescue",     node_rescue)
g.add_node("judge",      node_judge)        # DP3, effort=medium, batched
g.add_node("clamp",      node_clamp)        # L6
g.add_node("commit",     node_commit)
g.add_node("summary",    node_summary)      # DP4, effort=low
```

### Session planning (DP2)

The AI receives the candidate set and may **reorder only**. Its constraints, stated in the prompt and enforced by L3:

- Return a permutation of a subset of the given ids. Nothing else is valid.
- Open with a mastered skill (a guaranteed win in the first 20 seconds).
- Do not place the single new skill first or last — it belongs in position 3–5, when attention is highest but the child is warmed up.
- Alternate receptive and expressive; never two expressive tasks in a row.
- Never two activities on the same skill back to back.
- Close with a mastered skill.

If any constraint is violated, the deterministic ordering ships. In practice the AI's value here is small but real: it uses the previous session's fatigue point and time of day to decide length and difficulty ramp.

### Engagement heuristic (no AI — it must be instant)

```python
def engagement(attempts: list[Attempt], baseline_ms: int) -> Affect:
    last5 = attempts[-5:]
    signals = {
        "latency_drift": mean(a.latency_ms for a in last5) / baseline_ms,
        "error_run":     _trailing_run(last5, lambda a: a.result != "correct"),
        "no_response":   sum(1 for a in last5 if a.result == "no_response"),
        "prompt_climb":  sum(1 for a in last5
                             if a.prompt_level in ("partial_verbal", "full_model")),
    }
    if signals["no_response"] >= 2 or signals["error_run"] >= 3:
        return Affect("struggling", signals)
    if signals["latency_drift"] > 1.8 or signals["prompt_climb"] >= 3:
        return Affect("tiring", signals)
    if signals["latency_drift"] < 0.7 and signals["error_run"] == 0:
        return Affect("flowing", signals)
    return Affect("steady", signals)
```

| Affect | Response |
|---|---|
| `struggling` | Insert a mastered skill immediately; drop `choice_count` to 2; move the prompt ladder one rung earlier; cap the session at 3 more activities |
| `tiring` | Cap at 4 more activities; skip the new skill if it has not appeared yet; lengthen wait time by 25% |
| `flowing` | Allow up to 2 extra activities beyond plan; permit `choice_count + 1` on mastered skills |
| `steady` | Continue |

**Hard limits that override everything:** 10 minutes wall clock, 15 activities, or 3 consecutive `no_response` → end warmly with the closing audio. There is no path where the session continues past a child who has disengaged.

### Mastery judgement (DP3)

Runs once at session end. Evidence bundle per skill:

```json
{
  "skill_code": "color_red",
  "modality": "receptive",
  "deterministic_rule_met": true,
  "p_known": 0.93,
  "attempts": [
    {"day_offset": -6, "result": "correct", "latency_ms": 4100,
     "prompt_level": "independent", "choice_count": 2, "position": 1},
    {"day_offset": -3, "result": "incorrect", "latency_ms": 900,
     "prompt_level": "independent", "choice_count": 3, "position": 2,
     "selected": "color_orange"},
    {"day_offset": 0,  "result": "correct", "latency_ms": 3800,
     "prompt_level": "independent", "choice_count": 3, "position": 3}
  ],
  "baseline_latency_ms": 4300,
  "distinct_days": 3,
  "delayed_retrieval_days": 6
}
```

Note what is *included*: choice position (to detect position bias), the specific wrong choice (to distinguish a meaningful confusion from a random tap), and latency relative to that child's own baseline (absolute latency is meaningless for this population). Note what is *excluded*: the child's name, age in years, diagnosis, or anything else that could bias the judgement toward low expectations. **The judge does not know the child has Down syndrome.** That is deliberate — the evidence should speak, and expectation effects are real in models as in people.

The verdict is clamped by L6 and written to `mastery_events` with the AI's reasoning attached, so a clinician can later audit why a skill was or was not promoted.

### Session summary (DP4)

Four lines of Egyptian Arabic for the caregiver, plus one concrete thing to try tonight with an object they already own. Constraints: no numbers except the count of activities, no comparison to other children, name one specific thing the child did well, and the home activity must use only items from a fixed household list.

Example output shape:

> **نور و{{CHILD}} لعبوا ٨ ألعاب النهارده.**
> عرف يوريني الأحمر لوحده تلات مرات — ده تحسّن واضح عن الأسبوع اللي فات.
> لسه بنتمرّن على "فرشة السنان" وده طبيعي، محتاج شوية تكرار كمان.
> **جرّبوا كده الليلة:** وإنت بتغسّليله سنانه، امسكي الفرشة وقولي "فرشة سنان" مرتين، وسيبيه هو يقولها.

### Offline behaviour
The client posts attempts to an IndexedDB outbox with client-generated idempotency keys and replays them on reconnect. If a session ends while offline, `judge`/`commit`/`summary` run when the outbox drains — the caregiver gets the summary as a push notification a few minutes later. Duplicate replays are absorbed by the unique index on `attempts.idempotency_key`.

### Definition of done
A simulated child (scripted response policy) can run 30 sessions end to end with the AI stubbed and produce a sane mastery curve. The random-tapper never reaches mastery. Killing the network at any point in a session loses zero attempts. Every AI node failure degrades silently.
