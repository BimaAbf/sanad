"""What is present, what is missing, and what each absence costs.

Split out of `run.py` because it is the only part of the runner with any logic
worth testing: the runner itself is process plumbing, but the decision "docker
is unreachable, so start the API anyway and say exactly which routes will 500"
is a judgement that should not live inside a thread.

The rule this file exists to enforce: **never silently degrade.** A stack that
comes up missing Postgres and prints a cheerful "ready" is how an afternoon gets
spent debugging the wrong thing. Every absence is named, and every absence names
what it breaks.

Pure. No subprocess calls, no I/O — `run.py` gathers the facts and passes them in.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    OK = "ok"
    #: Runs, but a named part of the product does not.
    DEGRADED = "degraded"
    #: Nothing can start.
    FATAL = "fatal"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    severity: Severity
    detail: str
    #: What stops working. Empty for an OK check.
    breaks: tuple[str, ...] = ()
    #: The single command that would fix it, if there is one.
    remedy: str = ""

    @property
    def ok(self) -> bool:
        return self.severity is Severity.OK


@dataclass(frozen=True, slots=True)
class Preflight:
    checks: tuple[Check, ...] = field(default_factory=tuple)

    @property
    def fatal(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.severity is Severity.FATAL)

    @property
    def degraded(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.severity is Severity.DEGRADED)

    @property
    def can_start(self) -> bool:
        return not self.fatal


#: What each container is for, in the words of the thing that breaks without it.
#: Kept here rather than in a comment because `run.py` prints it verbatim.
BREAKS_WITHOUT_POSTGRES: tuple[str, ...] = (
    "every route that reads or writes — auth, children, assessment, progress",
    "/health/ready returns 503",
    "alembic migrations do not run",
)
BREAKS_WITHOUT_REDIS: tuple[str, ...] = (
    "OTP rate limiting and the session cache",
    "the ARQ job queue",
)
BREAKS_WITHOUT_MINIO: tuple[str, ...] = (
    "audio and media reads — the child app plays nothing",
    "export and erasure bundles",
)


def check_tool(name: str, *, purpose: str, fatal: bool, remedy: str) -> Check:
    """Is an executable on PATH?"""
    found = shutil.which(name)
    if found:
        return Check(name, Severity.OK, found, remedy=remedy)
    return Check(
        name,
        Severity.FATAL if fatal else Severity.DEGRADED,
        "not on PATH",
        breaks=(purpose,),
        remedy=remedy,
    )


def check_docker(reachable: bool, *, installed: bool) -> Check:
    """Docker is the one degraded-but-not-fatal case that matters here.

    The API process starts perfectly well without it — `/health` answers, the
    OpenAPI page renders, and every pure domain module is importable — so
    refusing to start would be wrong. What is wrong is starting quietly: a
    developer who does not know Postgres is absent reads the first 500 as a bug
    in their code.
    """
    if reachable:
        return Check("docker", Severity.OK, "daemon reachable")
    if not installed:
        return Check(
            "docker",
            Severity.DEGRADED,
            "not installed",
            breaks=BREAKS_WITHOUT_POSTGRES + BREAKS_WITHOUT_REDIS + BREAKS_WITHOUT_MINIO,
            remedy="install Docker Desktop: https://docs.docker.com/desktop/",
        )
    return Check(
        "docker",
        Severity.DEGRADED,
        "installed, but the daemon is not answering",
        breaks=BREAKS_WITHOUT_POSTGRES + BREAKS_WITHOUT_REDIS + BREAKS_WITHOUT_MINIO,
        remedy="start Docker Desktop and wait for the whale icon to stop animating — BLOCKED.md #1",
    )


def check_env_file(exists: bool) -> Check:
    if exists:
        return Check(".env", Severity.OK, "present")
    return Check(
        ".env",
        Severity.FATAL,
        "missing — the API refuses to start without it, by design",
        breaks=("everything: app.core.config requires the datastore URLs",),
        remedy="just bootstrap, or: uv run --no-project --python 3.12 tools/bootstrap_env.py",
    )


def check_prod_env_file(exists: bool) -> Check:
    """`--prod` needs its own file, and cannot fall back to `.env`.

    `.env` sets SANAD_ENVIRONMENT=local, which is exactly the configuration a
    deployed-shape run is trying not to use. Silently falling back would produce
    a run that looks production-shaped and is not — the failure mode this whole
    mode exists to avoid.
    """
    if exists:
        return Check(".env.production-local", Severity.OK, "present")
    return Check(
        ".env.production-local",
        Severity.FATAL,
        "missing — --prod will not fall back to .env",
        breaks=("production settings, the RS256 keypair, the non-placeholder secrets",),
        remedy="just prod-env",
    )


def check_web_build(exists: bool) -> Check:
    """`next start` serves a build; it does not make one."""
    if exists:
        return Check("apps/web/.next", Severity.OK, "built")
    return Check(
        "apps/web/.next",
        Severity.DEGRADED,
        "no production build",
        breaks=("the web app cannot start in --prod mode",),
        remedy="pnpm --filter @sanad/web build",
    )


def check_node_modules(exists: bool) -> Check:
    if exists:
        return Check("node_modules", Severity.OK, "installed")
    return Check(
        "node_modules",
        Severity.DEGRADED,
        "not installed",
        breaks=("the web app cannot start",),
        remedy="pnpm install",
    )


def check_python_env(exists: bool) -> Check:
    if exists:
        return Check("services/api/.venv", Severity.OK, "synced")
    return Check(
        "services/api/.venv",
        Severity.FATAL,
        "not synced",
        breaks=("the API cannot start",),
        remedy="uv --directory services/api sync --all-extras",
    )


#: Credentials, and the honest statement of what their absence does. This is the
#: table SETUP.md §2 promises: absence is a documented mode, never a stub.
@dataclass(frozen=True, slots=True)
class CredentialState:
    variable: str
    present: bool
    gate: str
    without_it: str


def credential_states(env: dict[str, str]) -> tuple[CredentialState, ...]:
    """Read-only view of which optional credentials are set.

    Nothing here ever prints a value, and a variable set to the empty string
    counts as absent — an empty key is a misconfiguration, not a credential.
    """

    def present(name: str) -> bool:
        return bool(env.get(name, "").strip())

    return (
        CredentialState(
            "ANTHROPIC_API_KEY",
            present("ANTHROPIC_API_KEY"),
            "Gate 4 — DP1 interpret, DP4 report",
            "the AI gateway replays recorded fixtures and makes no network call",
        ),
        CredentialState(
            "GROQ_API_KEY",
            present("GROQ_API_KEY"),
            "Gate 4 — DP0, DP2, DP3, session summaries",
            "same: fixtures, and ASR failover stops at caregiver confirmation",
        ),
        CredentialState(
            "SANAD_R2_ACCOUNT_ID",
            present("SANAD_R2_ACCOUNT_ID"),
            "Gate 5 — P09 render, P06 publish",
            "MinIO in docker-compose covers local development completely",
        ),
        CredentialState(
            "SANAD_GPU_PROVIDER_TOKEN",
            present("SANAD_GPU_PROVIDER_TOKEN"),
            "Gate 5 — the VoxCPM2 voice render",
            "no audio renders; REVIEW-QUEUE #10 is the real blocker there, not this key",
        ),
    )
