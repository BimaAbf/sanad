# BLOCKED

Anything the orchestrator cannot proceed on, and what would unblock it.

_Last updated: 2026-08-29 · after P01–P08_

---

## 1. The Docker daemon stopped and did not recover

**This is the only hard blocker.**

`docker info` began hanging indefinitely partway through P01. It survived a full
Docker Desktop process kill, a `wsl --shutdown`, and a manual start of the
`docker-desktop` WSL distro (which did come back to `Running` — the daemon still
did not answer). Every subsequent `docker` command hangs until timeout.

**What it blocks:**

| Blocked | Why |
|---|---|
| Migrations `0002`–`0004` | Never executed. Only `0001` has ever run against real Postgres. |
| `repository.py` in identity and children | Pure SQL, ~35% covered, cannot be exercised. |
| `tests/integration/test_stack.py` | 5 tests, correctly marked `integration`. |
| The `ai_cannot_grant` CHECK constraint | P07 requires proving via raw SQL that an AI verdict cannot promote a child to `mastered`. The application rule is tested; **the database backstop is not.** |
| P05's LangGraph checkpointer | Needs `AsyncPostgresSaver` against a live database. |
| Export and erasure completeness | P02 requires walking every foreign key to `children`. |

**What would unblock it:** a working Docker daemon. Then:

```
just migrate && just migrate-test && just test
```

I would not trust the DDL in `0002`–`0004` until that has run. They are
transcribed from `docs/02` and reviewed, but transcription errors in DDL are
exactly what a first migration run catches.

---

## 2. Sub-session delegation is off, and it changes what P04 and P07 are worth

Not blocking — flagged because it changes how much the P04 and P07 results mean.

`ORCHESTRATOR.md` §5 makes two *independent* sessions mandatory for those two
components: one writes the engine, one writes the expectations, neither sees the
other. This session has no sub-agent capability enabled, so the same author
produced both sides.

The substitute used was to derive the expectations from the written rules and
record them **before** implementing. The engine then agreed on the first run.
That is meaningful evidence — but it is not the protocol, and it is recorded as
such in `REVIEW-QUEUE.md` #4 and in the golden-case file itself.

---

## Watch list — not blocking yet

| Item | Becomes blocking at | Tracked in |
|---|---|---|
| Named clinician (O2) | Stage 2 gate | REVIEW-QUEUE #3, #4, #5 |
| Portage licensing (O1) | PGEE go-live | REVIEW-QUEUE #2 |
| Independent red-teamer | Stage 4 gate | REVIEW-QUEUE #7 |
| Native Egyptian Arabic speaker | Stage 3 and Stage 5 | REVIEW-QUEUE #1, #6 |
| Voice talent booking | Stage 5, long lead time | SETUP §3 |
| `ANTHROPIC_API_KEY` | Gate 4, and the empirical half of the prompt-cache guard | SETUP §2 |
| A git remote | Whenever `just bootstrap` is first run from a clean clone | PROGRESS.md |
| A CI run | The workflow has still never executed on a runner | PROGRESS.md |
