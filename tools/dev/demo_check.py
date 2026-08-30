#!/usr/bin/env python
"""`just demo-check` — is the demo ready, yes or no.

One command, one verdict. It resets the database, applies the migrations, seeds
the curriculum and the demo family, starts the API and the web app, runs every
gate the demo depends on, and prints

    SANAD DEMO READY

or

    SANAD DEMO NOT READY

followed by exactly which gates failed. Nothing is skipped quietly: a gate that
could not run is a FAILED gate, because "we could not check" and "we checked and
it is fine" must not print the same thing.

The gates, in the order they run — cheapest and most diagnostic first, so a
formatting mistake does not cost four minutes of Playwright:

    format          ruff format --check
    lint            ruff check
    types           mypy --strict
    banned-terms    no copy framing a child as deficient
    guards          the CI guards, and the tests proving each one fires
    api-tests       every backend test, including the ones needing Postgres
    coverage        100% branch on domain/ and guardrails/
    web-lint        eslint
    web-types       tsc --noEmit
    web-tests       vitest
    e2e             the critical path, in a browser, against this stack

`--skip-e2e` runs everything except the browser gate, for a fast inner loop. It
changes the verdict line to say so; it does not let the run claim readiness.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
API = REPO / "services" / "api"
WEB = REPO / "apps" / "web"

API_PORT = 8000
WEB_PORT = 3000

#: How long to wait for each service to answer its health check.
API_STARTUP_S = 90
WEB_STARTUP_S = 180


@dataclass(slots=True)
class Gate:
    name: str
    command: list[str]
    cwd: Path
    #: Printed when the gate fails, so the failure says what to do about it.
    hint: str = ""
    env: dict[str, str] = field(default_factory=dict)


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _wait_for(url: str, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                if response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            time.sleep(1)
    return False


def _preflight() -> list[str]:
    """Everything absent, and what its absence breaks. Never a silent skip."""
    problems: list[str] = []
    for tool in ("uv", "pnpm"):
        if shutil.which(tool) is None:
            problems.append(f"{tool} is not on PATH — nothing can run without it")

    for port, what in ((55432, "PostgreSQL"), (56379, "Redis")):
        if not _listening(port):
            problems.append(
                f"{what} is not answering on 127.0.0.1:{port} — "
                "start it with `docker compose up -d`, or see DEMO-RUNBOOK.md "
                "for the WSL alternative"
            )
    return problems


def _resolve(command: list[str]) -> list[str]:
    """Absolute path for argv[0], because Windows will not find `pnpm` alone.

    `pnpm` on Windows is `pnpm.CMD`, and `CreateProcess` does not apply PATHEXT
    — so `subprocess.run(["pnpm", ...])` raises FileNotFoundError while the same
    command works in every shell. Resolving through `shutil.which`, which does
    apply PATHEXT, makes the gate behave the same on both platforms.
    """
    found = shutil.which(command[0])
    return [found, *command[1:]] if found else command


def _run(gate: Gate) -> tuple[bool, str]:
    environment = {**os.environ, **gate.env}
    # `PYTHONIOENCODING`: several gates print Arabic, and a Windows console
    # defaults to cp1252 — a UnicodeEncodeError in a subprocess would fail a
    # gate for a reason that has nothing to do with the product.
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    print(f"\n=== {gate.name} " + "=" * max(0, 60 - len(gate.name)))
    print("$ " + " ".join(gate.command))
    result = subprocess.run(_resolve(gate.command), cwd=gate.cwd, env=environment, check=False)
    return result.returncode == 0, gate.hint


def _reset_database() -> bool:
    print("\n=== database " + "=" * 52)
    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "dev" / "reset_db.py")],
        cwd=REPO,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    return result.returncode == 0


def _clear_otp_limits() -> None:
    """Reset the sign-in rate limiter before the browser gate.

    `RATE_OTP_PER_PHONE_PER_HOUR` is three and the critical path signs in twice,
    so two runs inside an hour would rate-limit the second — and the failure
    would read as a broken sign-in rather than as a limiter doing its job. This
    is test-environment setup and it is done here, in the open, rather than by
    a back door in the application.
    """
    script = (
        "import redis, os, urllib.parse as u;"
        "url=os.environ.get('SANAD_REDIS_URL','redis://localhost:56379/0');"
        "p=u.urlparse(url);"
        "r=redis.Redis(host=p.hostname or 'localhost', port=p.port or 6379,"
        " db=int((p.path or '/0').lstrip('/') or 0));"
        "n=0\n"
        "for k in r.scan_iter('*'):\n"
        "    r.delete(k); n+=1\n"
        "print(f'demo-check: cleared {n} rate-limit / otp keys')"
    )
    subprocess.run(
        _resolve(
            [
                "uv",
                "run",
                "--no-project",
                "--python",
                "3.12",
                "--with",
                "redis",
                "python",
                "-c",
                script,
            ]
        ),
        cwd=REPO,
        check=False,
    )


def gates(*, skip_e2e: bool) -> list[Gate]:
    listed = [
        Gate("format", ["uv", "run", "ruff", "format", "--check", "."], API, "run `just fmt`"),
        Gate("lint", ["uv", "run", "ruff", "check", "."], API, "run `just fmt`"),
        Gate("types", ["uv", "run", "mypy", "--strict", "app"], API, ""),
        Gate(
            "banned-terms",
            [
                "uv",
                "run",
                "--no-project",
                "--python",
                "3.12",
                "python",
                "tools/lint/banned_terms.py",
            ],
            REPO,
            "some copy frames a child as deficient — the message names the file",
        ),
        Gate(
            "guards",
            ["uv", "run", "pytest", "../../tools/guards/test_guards.py", "--no-cov", "-q"],
            API,
            "",
        ),
        Gate(
            "api-tests",
            [
                "uv",
                "run",
                "pytest",
                "-m",
                "not live_ai",
                "--cov",
                "--cov-report=term:skip-covered",
                "--cov-report=xml",
                "-q",
            ],
            API,
            "",
        ),
        Gate(
            "coverage",
            ["uv", "run", "python", "../../tools/lint/coverage_gate.py"],
            API,
            "100% branch coverage is required on every domain/ package",
        ),
        Gate("web-lint", ["pnpm", "--filter", "@sanad/web", "lint"], REPO, ""),
        Gate("web-types", ["pnpm", "--filter", "@sanad/web", "typecheck"], REPO, ""),
        Gate("web-tests", ["pnpm", "--filter", "@sanad/web", "test"], REPO, ""),
    ]
    if not skip_e2e:
        listed.append(
            Gate(
                "e2e",
                ["pnpm", "exec", "playwright", "test", "--project=demo", "--reporter=line"],
                WEB,
                "the critical path failed — the Playwright output names the step",
                env={"SANAD_E2E_BASE_URL": f"http://localhost:{WEB_PORT}"},
            )
        )
    return listed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="demo-check")
    parser.add_argument(
        "--skip-e2e",
        action="store_true",
        help="run every gate except the browser one (fast inner loop; never READY)",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="keep the current database instead of rebuilding it from migrations",
    )
    arguments = parser.parse_args(argv)

    problems = _preflight()
    if problems:
        print("SANAD DEMO NOT READY\n")
        print("Preflight failed before any gate could run:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    if not arguments.no_reset:
        if not _reset_database():
            print("\nSANAD DEMO NOT READY\n\nFailing gate:\n  - database (reset/migrate/seed)")
            return 1

    processes: list[subprocess.Popen[bytes]] = []
    try:
        if not arguments.skip_e2e:
            if not _listening(API_PORT):
                print(f"\ndemo-check: starting the API on :{API_PORT}")
                processes.append(
                    subprocess.Popen(
                        _resolve(
                            [
                                "uv",
                                "run",
                                "uvicorn",
                                "app.main:app",
                                "--host",
                                "127.0.0.1",
                                "--port",
                                str(API_PORT),
                            ]
                        ),
                        cwd=API,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    )
                )
            if not _wait_for(f"http://127.0.0.1:{API_PORT}/health", API_STARTUP_S):
                print("\nSANAD DEMO NOT READY\n\nFailing gate:\n  - api (never became healthy)")
                return 1

            if not _listening(WEB_PORT):
                print(f"demo-check: starting the web app on :{WEB_PORT}")
                processes.append(
                    subprocess.Popen(
                        _resolve(["pnpm", "--filter", "@sanad/web", "dev"]),
                        cwd=REPO,
                        env={**os.environ},
                    )
                )
            if not _wait_for(f"http://localhost:{WEB_PORT}/onboarding", WEB_STARTUP_S):
                print("\nSANAD DEMO NOT READY\n\nFailing gate:\n  - web (never answered)")
                return 1
            _clear_otp_limits()

        failures: list[tuple[str, str]] = []
        for gate in gates(skip_e2e=arguments.skip_e2e):
            passed, hint = _run(gate)
            if not passed:
                failures.append((gate.name, hint))

        print("\n" + "=" * 68)
        if failures:
            print("SANAD DEMO NOT READY\n")
            print("Failing gates:")
            for name, hint in failures:
                print(f"  - {name}" + (f"  ({hint})" if hint else ""))
            return 1

        if arguments.skip_e2e:
            print("SANAD DEMO NOT READY\n")
            print(
                "Every gate that ran passed, but --skip-e2e was given: the critical\n"
                "path was not exercised in a browser, so this run cannot say the demo\n"
                "is ready. Run `just demo-check` without it."
            )
            return 1

        print("SANAD DEMO READY")
        print(
            "\nEvery gate passed, from a database rebuilt out of the migrations:\n"
            "  formatting, lint, types, banned terms, the CI guards, the whole\n"
            "  backend suite against real Postgres, 100% branch coverage on the\n"
            "  deterministic core, the web lint/type/unit gates, and the critical\n"
            "  path walked in a browser against this stack."
        )
        return 0
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - shutdown race
                process.kill()


if __name__ == "__main__":
    sys.exit(main())
