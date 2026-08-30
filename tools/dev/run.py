#!/usr/bin/env python
"""`just up` — the whole stack, one command, one log stream.

    just up                     everything
    just up --no-web            API only
    just up --no-docker --raw   no containers, and the API's JSON unrendered

What it does, in order:

  1. **Preflight.** Names every missing prerequisite and what that absence
     breaks, then decides whether to start. See `preflight.py` — the rule is
     that the runner never degrades quietly.
  2. **Containers.** `docker compose up -d --wait`, skipped with a loud banner
     if the daemon is not answering (BLOCKED.md #1 is exactly this case).
  3. **Migrations.** `alembic upgrade head`, only if Postgres actually answered.
  4. **Processes.** uvicorn on :8000 and Next on :3000, as children of this one.
  5. **One stream.** Every line from every child, timestamped, prefixed and
     colour-coded; the API's structlog JSON re-rendered as prose and its
     `http_request` records as request lines. See `logfmt.py`.
  6. **A file.** The same stream, uncoloured and unformatted, to
     `logs/dev-<timestamp>.log` — that file is the raw JSON, not this runner's
     rendering of it, so a bug report can carry the real record.
  7. **Ctrl-C.** Stops the child processes and prints a request summary.
     Containers are left running on purpose: `just down` stops them, and a
     restart that does not re-wait for Postgres is worth several seconds every
     time.

Standard library only, and deliberately so: this must run before `pnpm install`
and before `uv sync` have necessarily succeeded, which is precisely when a
developer needs it to tell them that.

Nothing in this file is imported by `services/api` or by CI.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dev.logfmt import RESET, banner, format_line
from dev.preflight import (
    Preflight,
    Severity,
    check_docker,
    check_env_file,
    check_node_modules,
    check_prod_env_file,
    check_python_env,
    check_tool,
    check_web_build,
    credential_states,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "services" / "api"
LOG_DIR = REPO_ROOT / "logs"
#: Written by `just prod-env`. Gitignored, and never overwritten once it exists.
PROD_ENV_FILE = REPO_ROOT / ".env.production-local"
#: The same file as uv sees it. `uv --directory services/api run --env-file` takes
#: the path RELATIVE TO --directory, and passing the absolute one mangles it when
#: the repo path contains spaces -- "E:\Summer Academy - DELL\Revamped\.env..."
#: came back as "DELLRevamped.env.production-local". The justfile's `migrate-test`
#: recipe already used the relative form for exactly this reason.
PROD_ENV_FILE_FOR_UV = "../../.env.production-local"

API_PORT = 8000
WEB_PORT = 3000
READY_URL = f"http://localhost:{API_PORT}/health/ready"

#: Next.js and docker both emit ANSI. The terminal keeps it; the log file must
#: not, or every grep needs a character class.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

URLS: tuple[tuple[str, str], ...] = (
    (f"http://localhost:{WEB_PORT}/home", "caregiver app"),
    (f"http://localhost:{WEB_PORT}/play", "child app"),
    (f"http://localhost:{WEB_PORT}/console", "clinician console"),
    (f"http://localhost:{API_PORT}/docs", "OpenAPI — try requests here"),
    (f"http://localhost:{API_PORT}/health/ready", "readiness, per dependency"),
    ("http://localhost:59001", "MinIO console (sanadminio / sanadminio-dev-secret)"),
    ("http://localhost:58025", "Mailhog"),
)


def urls_for(*, prod: bool) -> list[tuple[str, str]]:
    """`debug_docs_enabled` is False in production, so /docs 404s there.

    Printing a link that 404s is a small thing that costs someone five minutes
    of thinking they misconfigured something.
    """
    if not prod:
        return list(URLS)
    return [(url, what) for url, what in URLS if not url.endswith("/docs")] + [
        ("(/docs is disabled)", "SANAD_ENVIRONMENT=production — app.core.config")
    ]


# --------------------------------------------------------------------------- #
# terminal
# --------------------------------------------------------------------------- #


def force_utf8_stdout() -> None:
    """Windows consoles still default to cp1252 in 2026.

    Every arrow, box character and Arabic label in this runner's own output —
    and every Arabic label in a log line coming out of the API — raises
    UnicodeEncodeError without this. `errors="replace"` rather than "strict"
    because a log runner that dies on a character is worse than one that prints
    a question mark.
    """
    for handle in (sys.stdout, sys.stderr):
        reconfigure = getattr(handle, "reconfigure", None)
        if reconfigure is not None:
            # line_buffering matters as much as the encoding: Python block-buffers
            # stdout whenever it is not a tty, so `just up | tee` or a redirect
            # into a file shows nothing for the first 8 KB — which is most of a
            # short session, and exactly when someone is watching for a failure.
            reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def enable_colour() -> bool:
    """True if we should emit ANSI.

    Honours NO_COLOR (https://no-color.org) and a non-tty stdout. On Windows the
    call to `os.system("")` is the documented one-liner that flips the console
    into virtual-terminal mode; without it the escapes print literally on
    conhost.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":  # pragma: no cover - Windows console mode
        os.system("")
    return True


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #


def docker_reachable() -> bool:
    """One short probe. `docker info` can hang for minutes; `version` cannot."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def read_env_file(path: Path) -> dict[str, str]:
    """A deliberately dumb .env reader.

    It exists to answer "is GROQ_API_KEY set" without importing pydantic, and it
    never prints or returns a value to anything but `credential_states`, which
    only looks at truthiness.
    """
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.split("#", 1)[0].strip().strip("\"'")
    for key, value in os.environ.items():  # a real env var wins over the file
        values[key] = value
    return values


def run_preflight(*, want_web: bool, prod: bool = False) -> Preflight:
    checks = [
        check_prod_env_file(PROD_ENV_FILE.exists())
        if prod
        else check_env_file((REPO_ROOT / ".env").exists()),
        check_tool(
            "uv",
            purpose="the API cannot start",
            fatal=True,
            remedy="https://docs.astral.sh/uv/",
        ),
        check_python_env((API_DIR / ".venv").exists()),
        check_docker(docker_reachable(), installed=shutil.which("docker") is not None),
    ]
    if want_web:
        checks.append(
            check_tool(
                "pnpm",
                purpose="the web app cannot start",
                fatal=False,
                remedy="npm i -g pnpm",
            )
        )
        checks.append(check_node_modules((REPO_ROOT / "node_modules").exists()))
        if prod:
            checks.append(check_web_build((REPO_ROOT / "apps" / "web" / ".next").exists()))
    return Preflight(checks=tuple(checks))


def print_preflight(report: Preflight, env: dict[str, str], *, colour: bool) -> None:
    marks = {Severity.OK: "  ok", Severity.DEGRADED: "warn", Severity.FATAL: "FAIL"}
    rows = [(f"[{marks[c.severity]}] {c.name}", c.detail) for c in report.checks]
    print(banner("preflight", rows, colour=colour))

    for check in report.checks:
        if check.ok:
            continue
        print()
        print(banner(f"{check.name}: {check.detail}", [], colour=colour))
        for broken in check.breaks:
            print(f"  · {broken}")
        if check.remedy:
            print(f"  → {check.remedy}")

    print()
    credentials = credential_states(env)
    rows = [
        (
            f"[{'set ' if state.present else 'none'}] {state.variable}",
            state.gate if state.present else state.without_it,
        )
        for state in credentials
    ]
    print(
        banner(
            "credentials — absence is a documented mode, never a stub (SETUP.md §2)",
            rows,
            colour=colour,
        )
    )


# --------------------------------------------------------------------------- #
# child processes
# --------------------------------------------------------------------------- #


@dataclass
class Child:
    name: str
    command: list[str]
    cwd: Path
    process: subprocess.Popen[str] | None = None
    reader: threading.Thread | None = None


@dataclass
class RequestStats:
    """Enough to answer "what did I just exercise?" at shutdown."""

    by_status: Counter[int] = field(default_factory=Counter)
    by_path: Counter[str] = field(default_factory=Counter)
    slowest: list[tuple[float, str, str]] = field(default_factory=list)

    def record(self, record: dict[str, object]) -> None:
        status = record.get("status_code")
        path = record.get("path")
        duration = record.get("duration_ms")
        if isinstance(status, int):
            self.by_status[status] += 1
        if isinstance(path, str):
            self.by_path[path] += 1
        if isinstance(duration, (int, float)) and isinstance(path, str):
            self.slowest.append((float(duration), str(record.get("method", "?")), path))
            self.slowest.sort(reverse=True)
            del self.slowest[8:]

    @property
    def total(self) -> int:
        return sum(self.by_status.values())


def resolve(executable: str) -> str:
    """Absolute path to an executable.

    On Windows `pnpm` is `pnpm.cmd`, and `Popen` without a shell will not find
    it from the bare name. `shutil.which` does the PATHEXT lookup for us, which
    keeps `shell=True` — and its quoting hazards — out of this file entirely.
    """
    found = shutil.which(executable)
    return found or executable


def build_children(*, want_api: bool, want_web: bool, prod: bool = False) -> list[Child]:
    """The two child processes, in dev shape or deployed shape.

    `prod` runs the same code the container image runs: no reloader, two
    workers, production settings out of `.env.production-local`, and Next
    serving a real build rather than compiling on demand. It is not the image —
    building that needs a Docker daemon — but it is the same process invocation
    with the same configuration, which is what catches config-shaped bugs.
    """
    children: list[Child] = []
    if want_api:
        # uvicorn's own access log would duplicate every line the
        # RequestContextMiddleware already emits as structured JSON, and only
        # one of the two carries the request id.
        if prod:
            # `uv run --env-file` rather than exporting: the production file
            # holds a multi-line PEM, and shell export of that is where this
            # goes wrong by hand. --workers 2 matches services/api/Dockerfile.
            command = [
                resolve("uv"),
                "--directory",
                str(API_DIR),
                "run",
                "--env-file",
                PROD_ENV_FILE_FOR_UV,
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(API_PORT),
                "--workers",
                "2",
                "--no-access-log",
            ]
        else:
            command = [
                resolve("uv"),
                "--directory",
                str(API_DIR),
                "run",
                "uvicorn",
                "app.main:app",
                "--reload",
                "--port",
                str(API_PORT),
                "--no-access-log",
            ]
        children.append(Child("api", command, REPO_ROOT))
    if want_web:
        script = "start" if prod else "dev"
        children.append(Child("web", [resolve("pnpm"), "--filter", "@sanad/web", script], REPO_ROOT))
    return children


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    # Without this, Python buffers 8 KB before we see a single line and the
    # stream arrives in useless bursts.
    env["PYTHONUNBUFFERED"] = "1"
    # Windows consoles default to cp1252; every Arabic label in a log line would
    # raise UnicodeEncodeError inside the child.
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("FORCE_COLOR", "1")
    return env


def start_child(child: Child, sink: queue.Queue[tuple[str, str]]) -> None:
    creationflags = 0
    if os.name == "nt":  # pragma: no cover - Windows process groups
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    child.process = subprocess.Popen(
        child.command,
        cwd=str(child.cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=child_env(),
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )

    def pump() -> None:
        assert child.process is not None and child.process.stdout is not None
        for line in child.process.stdout:
            sink.put((child.name, line))
        sink.put((child.name, f"__exit__ {child.process.wait()}"))

    child.reader = threading.Thread(target=pump, name=f"pump-{child.name}", daemon=True)
    child.reader.start()


def stop_child(child: Child) -> None:
    """Kill the process *tree*.

    `uvicorn --reload` and `next dev` both fork a worker. Terminating only the
    parent leaves that worker holding port 8000 or 3000, and the next `just up`
    fails with an address-in-use that looks like a bug in this script.
    """
    process = child.process
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":  # pragma: no cover - Windows
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
                timeout=20,
            )
        else:  # pragma: no cover - POSIX
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:  # pragma: no cover - last resort
        process.kill()


# --------------------------------------------------------------------------- #
# containers and migrations
# --------------------------------------------------------------------------- #


def stream(
    command: list[str], *, cwd: Path, sink: queue.Queue[tuple[str, str]], source: str
) -> int:
    """Run a command to completion, forwarding its output into the stream."""
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env(),
        )
    except OSError as exc:
        sink.put((source, f"could not run {command[0]}: {exc}"))
        return 1
    assert process.stdout is not None
    for line in process.stdout:
        sink.put((source, line))
    return process.wait()


# --------------------------------------------------------------------------- #
# readiness
# --------------------------------------------------------------------------- #


#: /health has no dependencies and answers in microseconds. /health/ready opens a
#: connection to Postgres, Redis and S3 — and when Postgres is *absent* rather
#: than merely slow, that call sits on the driver's TCP timeout for 25 seconds.
#: Probing the two with the same budget is what made the first version of this
#: runner never print its URL banner on a machine with no Docker: liveness was
#: established and then thrown away because the readiness probe timed out.
LIVENESS_TIMEOUT = 2.0
READINESS_TIMEOUT = 45.0
#: Once reported, readiness is re-checked rarely. Each check can cost 25s of a
#: worker's time when a dependency is down, and it is not worth that every 2s.
READINESS_INTERVAL = 30.0


def probe_live() -> bool:
    """GET /health — is the process answering at all?"""
    try:
        with urllib.request.urlopen(
            f"http://localhost:{API_PORT}/health", timeout=LIVENESS_TIMEOUT
        ):
            return True
    except (urllib.error.URLError, OSError):
        return False


def probe_ready() -> tuple[bool, dict[str, object]]:
    """GET /health/ready. A 503 is a *successful* probe with bad news in it."""
    request = urllib.request.Request(READY_URL, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=READINESS_TIMEOUT) as response:
            return True, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return True, json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            return True, {"status": "degraded", "checks": {}}
    except (urllib.error.URLError, OSError, ValueError):
        return False, {}


def _dependency_lines(payload: dict[str, object]) -> list[str]:
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        return []
    lines = []
    for name, detail in sorted(checks.items()):
        if not isinstance(detail, dict):
            continue
        status = str(detail.get("status", "?"))
        # /health/ready reports the reason per dependency. Printing the status
        # without it produces the single least useful log line in existence.
        reason = detail.get("reason") or detail.get("error") or ""
        lines.append(f"  {name}: {status}{f' — {reason}' if reason else ''}")
    return lines


def readiness_watcher(
    sink: queue.Queue[tuple[str, str]], stop: threading.Event, *, open_browser: bool
) -> None:
    """Announce the URLs as soon as the process is *alive*, then report readiness.

    The order matters. The URL banner is gated on liveness, not readiness, so a
    developer whose Docker is down still gets the links — the API serves /docs
    and every pure route perfectly well without a database. Readiness follows
    when it arrives, with the reason attached to each dependency that is down.

    After the first report it prints transitions only. A readiness line every
    few seconds trains people to stop reading the stream, which defeats the
    entire point of having one.
    """
    while not stop.wait(1.0):
        if probe_live():
            break
    else:
        return
    if stop.is_set():
        return

    sink.put(("dev", f"api is alive on :{API_PORT}"))
    sink.put(("dev", "__urls__"))
    if open_browser:
        webbrowser.open(f"http://localhost:{WEB_PORT}/home")

    last: dict[str, str] = {}
    first = True
    while True:
        reachable, payload = probe_ready()
        if reachable:
            current = {
                name: str(detail.get("status", "?"))
                for name, detail in (payload.get("checks") or {}).items()  # type: ignore[union-attr]
                if isinstance(detail, dict)
            }
            if first:
                sink.put(("dev", f"readiness: {payload.get('status', '?')}"))
                for line in _dependency_lines(payload):
                    sink.put(("dev", line))
                first = False
            else:
                for name, status in sorted(current.items()):
                    if last.get(name) != status:
                        was = last.get(name, "?")
                        sink.put(("dev", f"readiness changed — {name}: {was} -> {status}"))
            last = current
        if stop.wait(READINESS_INTERVAL):
            return


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="just up",
        description="Start the whole Sanad stack and stream every log into one place.",
    )
    parser.add_argument("--no-docker", action="store_true", help="do not touch docker compose")
    parser.add_argument("--no-web", action="store_true", help="API only")
    parser.add_argument("--no-api", action="store_true", help="web only")
    parser.add_argument("--no-migrate", action="store_true", help="skip alembic upgrade head")
    parser.add_argument("--seed", action="store_true", help="run the curriculum seed after migrate")
    parser.add_argument("--open", action="store_true", help="open the caregiver app in a browser")
    parser.add_argument(
        "--debug", action="store_true", help="SANAD_LOG_LEVEL=DEBUG for the API process"
    )
    parser.add_argument("--raw", action="store_true", help="do not re-render the API's JSON")
    parser.add_argument(
        "--prod",
        action="store_true",
        help="deployed shape: .env.production-local, no reloader, 2 workers, a built web app",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    force_utf8_stdout()
    colour = enable_colour()
    want_api = not args.no_api
    want_web = not args.no_web
    if args.debug:
        os.environ["SANAD_LOG_LEVEL"] = "DEBUG"

    env_values = read_env_file(PROD_ENV_FILE if args.prod else REPO_ROOT / ".env")
    report = run_preflight(want_web=want_web, prod=args.prod)
    print_preflight(report, env_values, colour=colour)
    print()

    if not report.can_start:
        print("preflight failed — fix the FAIL rows above and run again.")
        return 1

    docker_ok = any(c.name == "docker" and c.ok for c in report.checks) and not args.no_docker
    web_ok = want_web and all(c.ok for c in report.checks if c.name in {"pnpm", "node_modules"})
    if want_web and not web_ok:
        print("web app will not be started — see the warn rows above.")

    LOG_DIR.mkdir(exist_ok=True)
    started = datetime.now(UTC)
    log_path = LOG_DIR / f"dev-{started.strftime('%Y%m%d-%H%M%S')}.log"
    log_file = log_path.open("w", encoding="utf-8", buffering=1)

    sink: queue.Queue[tuple[str, str]] = queue.Queue()
    stats = RequestStats()
    children: list[Child] = []
    stop = threading.Event()
    printer_done = threading.Event()

    def printer() -> None:
        while not (printer_done.is_set() and sink.empty()):
            try:
                source, raw = sink.get(timeout=0.2)
            except queue.Empty:
                continue
            if raw == "__urls__":
                print()
                print(banner("open", urls_for(prod=args.prod), colour=colour))
                print()
                continue
            if raw.startswith("__exit__ "):
                code = raw.split(" ", 1)[1]
                message = f"{source} exited with code {code}"
                print(f"{RESET if colour else ''}{message}")
                log_file.write(f"{message}\n")
                continue
            # Local wall clock on purpose: the reader is a person glancing at
            # their own clock. The UTC timestamp is in the JSON record itself.
            clock = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # noqa: DTZ005
            line = format_line(source, raw, colour=colour, clock=clock)
            # --raw prints the source line untouched, which is what you want
            # when the question is "what did the API actually emit" rather than
            # "what happened". The prefix stays so the source is still legible.
            print(f"{clock} {source:<6}│ {line.raw}" if args.raw else line.text)
            log_file.write(f"{clock} {source} {ANSI_RE.sub('', line.raw)}\n")
            if source == "api" and '"http_request"' in line.raw:
                with contextlib.suppress(ValueError):
                    stats.record(json.loads(line.raw))

    printer_thread = threading.Thread(target=printer, name="printer", daemon=True)
    printer_thread.start()

    sink.put(("dev", f"logging to {log_path.relative_to(REPO_ROOT)}"))

    try:
        if docker_ok:
            sink.put(("dev", "docker compose up -d --wait"))
            if stream(
                [resolve("docker"), "compose", "up", "-d", "--wait"],
                cwd=REPO_ROOT,
                sink=sink,
                source="docker",
            ):
                sink.put(("dev", "docker compose failed — continuing without containers"))
                docker_ok = False
        elif not args.no_docker:
            sink.put(("dev", "skipping containers: the docker daemon did not answer"))

        if docker_ok and not args.no_migrate and want_api:
            sink.put(("dev", "alembic upgrade head"))
            migrate = [resolve("uv"), "--directory", str(API_DIR), "run"]
            if args.prod:
                migrate += ["--env-file", PROD_ENV_FILE_FOR_UV]
            migrate += ["alembic", "upgrade", "head"]
            if stream(
                migrate,
                cwd=REPO_ROOT,
                sink=sink,
                source="api",
            ):
                sink.put(("dev", "migrations failed — the API will start, routes will 500"))
            elif args.seed:
                stream(
                    [
                        resolve("uv"),
                        "--directory",
                        str(API_DIR),
                        "run",
                        "python",
                        "-m",
                        "app.cli",
                        "seed",
                    ],
                    cwd=REPO_ROOT,
                    sink=sink,
                    source="api",
                )

        children = build_children(want_api=want_api, want_web=web_ok, prod=args.prod)
        if not children:
            sink.put(("dev", "nothing to start"))
            return 1
        for child in children:
            sink.put(("dev", f"starting {child.name}: {' '.join(child.command[-4:])}"))
            start_child(child, sink)

        if want_api:
            threading.Thread(
                target=readiness_watcher,
                args=(sink, stop),
                kwargs={"open_browser": args.open},
                name="readiness",
                daemon=True,
            ).start()
        else:
            sink.put(("dev", "__urls__"))

        while any(child.process is not None and child.process.poll() is None for child in children):
            time.sleep(0.4)
        sink.put(("dev", "every child process has exited"))
    except KeyboardInterrupt:
        sink.put(("dev", "shutting down"))
    finally:
        stop.set()
        for child in children:
            stop_child(child)
        # Drain before the summary, so the last few lines of a crashing process
        # are not printed underneath the report that summarises them.
        printer_done.set()
        printer_thread.join(timeout=5)
        log_file.close()
        if stats.total:
            rows = [
                (f"{count:>5}  ×  HTTP {status}", "")
                for status, count in sorted(stats.by_status.items())
            ]
            rows += [
                (f"{duration:>7.1f}ms", f"{method} {path}")
                for duration, method, path in stats.slowest[:5]
            ]
            print()
            print(banner(f"{stats.total} API requests this session", rows, colour=colour))
        print()
        print(f"full log: {log_path}")
        if docker_ok:
            print("containers are still running — `just down` stops them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
