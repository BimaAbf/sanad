# ADR 017 — Infrastructure, CI and the fifth guard

- **Status:** accepted, with every deployment criterion outstanding
- **Date:** 2026-08-29
- **Component:** P15 — infrastructure, CI & observability
- **Context docs:** `docs/08` (entire) · `docs/12` §Δ3 · `docs/09` P15 · `docs/10` T15

## What was actually delivered

| Deliverable | State |
|---|---|
| Production Dockerfiles (api, web) | Written. **Never built** — no Docker daemon (BLOCKED.md #1). |
| Terraform modules and two envs | Written. **Never `validate`d, never `plan`ned, never `apply`ed.** No AWS account and no provider plugins on this machine. |
| CI: e2e, perf, security jobs | Written into `ci.yml`, replacing the P00 stubs. **CI has still never run.** |
| Deploy workflow, blue/green + bake | Written. Never run. |
| Fifth guard: destructive-migration | Written, **and tested against a violation fixture and a control** — this one really is verified. |
| Lighthouse budgets | Transcribed from docs/06 §6 as hard `error` assertions. Never executed. |
| Six runbooks | Written. **None rehearsed.** |

Stating it this way round is the point. Every acceptance criterion in docs/09
P15 is about something *happening* — an apply, a rollback, a restore drill, a
kill switch under load, a Trivy scan of a built image — and none of them has.

## Decisions

### D1 — A fifth guard: destructive-migration

Migrations run as a pre-deploy one-off task, so for the length of the bake the
**old** code serves traffic against the **new** schema. An additive migration is
invisible to old code. A `DROP COLUMN` is a 500 on every request that touches
the table, from a deploy that has not technically failed yet.

The guard fails the deploy unless the PR carries a `destructive-migration`
label. It splits each migration on `def downgrade` and only inspects the
upgrade: a downgrade that drops what its upgrade created is *correct*, and a
guard that flagged every downgrade would flag every migration ever written and
be switched off within a week.

Like the other four, it ships with a violation fixture and a control fixture,
and `test_guards.py` asserts it fires on one and stays quiet on the other.

### D2 — Two S3 buckets, not one with prefixes

Public media that a child app plays from a CDN, and private artefacts — data
exports, consented child audio — that must never be reachable by URL. One bucket
with a prefix policy is how a media URL ends up serving an export.

Exports expire after 7 days. A data export is a full copy of a child's record
sitting in a bucket; it exists to be downloaded once and then should stop
existing.

### D3 — The healthcheck hits `/health`, not `/health/ready`

Readiness reports a degraded dependency and returns 503. Killing the container
for that would turn a Redis blip into a restart loop while the API was still
serving every request that did not need Redis.

### D4 — One NAT gateway, and no default route out of the data tier

One NAT because at this scale the cross-AZ data charge is smaller than a second
gateway's hourly cost, and an AZ failure degrades outbound calls to providers
that already have deterministic fallbacks.

No default route from the data subnets at all, so an exfiltration path out of
Postgres does not exist. The database security group references the service
security group **by id**, never by CIDR — a CIDR rule grants access to whatever
lands in that subnet later.

### D5 — The GPU module provisions a precondition, not a GPU

docs/12 §3.3 is explicit that a single always-on A6000 must not be the
production ASR tier without failover, and that the *pilot* should use Groq's
free Whisper tier with no GPU at all. So `modules/gpu-asr` contains no
provider-specific compute: it holds the precondition that refuses to enable the
tier unless the Groq Whisper failover is configured, plus the idle-shutdown
policy. Turning the tier on cannot skip either.

### D6 — No committed Terraform backend

`envs/*/backend.tf` is absent by design. Pointing a fresh checkout at someone
else's state bucket by default is how two engineers destroy each other's
environment.

### D7 — Staging differs from production in exactly three ways

Single-AZ database, smaller instances, a 5-minute bake instead of 10. Nothing
structural. A staging environment shaped differently from production tests a
system nobody runs.

## Consequences, stated plainly

`terraform apply` from zero, the automatic-rollback drill, the RPO/RTO restore
drill with real timings, the kill-switch exercise under load, and the Trivy scan
of a built image are **all outstanding**. They need an account and a working
Docker daemon, and this session has neither. They are recorded in PROGRESS.md
and BLOCKED.md rather than approximated, because an infrastructure claim that
has never been executed is not a weaker version of a tested one — it is a
different kind of statement entirely.

`gitleaks` runs in CI and has never run. The repository has no remote, so
"gitleaks clean over the full history" is unverified.
