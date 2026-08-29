# BLOCKED

Anything the orchestrator cannot proceed on, and what would unblock it.

_Last updated: 2026-08-29_

## Nothing is blocked.

P00 is complete. P01 (identity), P06 (content) and P15 (infra) all have their
dependencies met and can start immediately — and per `ORCHESTRATOR.md` §2 they
have no shared files, so they are the parallel set.

### Watch list — not blocking yet

| Item | Becomes blocking at | Tracked in |
|---|---|---|
| Named clinician (O2) | Stage 2 gate | REVIEW-QUEUE #3 |
| Portage licensing (O1) | PGEE go-live, not the build | REVIEW-QUEUE #2 |
| Independent red-teamer | Stage 4 gate | SETUP §3 |
| Native Egyptian Arabic speaker | Stage 3 and Stage 5 | REVIEW-QUEUE #1 |
| Voice talent booking | Stage 5, but has calendar lead time | SETUP §3 |
| `ANTHROPIC_API_KEY`, `GROQ_API_KEY` | Gate 4 only | SETUP §2 |

### One question for the human that is not a gate

`ORCHESTRATOR.md` §2 instructs the orchestrator to delegate each component to a
fresh sub-session, and §5 makes two *independent* sessions mandatory for P04 and
P07 (one writes the engine, one writes the golden cases, neither sees the
other). The session-level configuration for this run says not to spawn
sub-agents unless the user asks.

P00 was mechanical and did not need delegation, so this did not bite. **It will
bite at P04.** Confirmation either way is needed before P04 starts — see the
orchestrator's report.
