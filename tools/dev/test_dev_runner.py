"""The two pure halves of `just up`.

`run.py` itself is process plumbing and is exercised by running it. These two
modules are not: `preflight.py` decides whether to start and what to warn about,
and `logfmt.py` decides what a developer actually reads. Both are worth a test,
and both were split out of the runner so they could have one.

Run with the rest of the suite: `just test`, or directly

    uv --directory services/api run pytest ../../tools/dev/test_dev_runner.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dev.logfmt import banner, format_json_record, format_line, is_problem_level
from dev.preflight import (
    Preflight,
    Severity,
    check_docker,
    check_env_file,
    check_node_modules,
    check_prod_env_file,
    check_python_env,
    check_web_build,
    credential_states,
)

# --- preflight -------------------------------------------------------------


def test_a_missing_env_file_is_fatal_and_names_its_remedy() -> None:
    """The API refuses to start without .env by design, so the runner must too."""
    check = check_env_file(exists=False)
    assert check.severity is Severity.FATAL
    assert "bootstrap_env" in check.remedy


def test_docker_absence_is_degraded_and_never_silent() -> None:
    """The property this runner exists for.

    A stack that comes up without Postgres and prints "ready" is how an
    afternoon gets spent debugging the wrong thing. Absent docker must be
    non-fatal — the API serves /docs and every pure route fine — and must name
    what it breaks.
    """
    check = check_docker(reachable=False, installed=True)
    assert check.severity is Severity.DEGRADED
    assert check.breaks, "an absence with no stated consequence is a silent degradation"
    assert any("auth" in item for item in check.breaks)
    assert "BLOCKED.md" in check.remedy


def test_docker_not_installed_reads_differently_from_docker_not_answering() -> None:
    """Two different problems, two different remedies."""
    absent = check_docker(reachable=False, installed=False)
    dead = check_docker(reachable=False, installed=True)
    assert absent.remedy != dead.remedy
    assert absent.breaks == dead.breaks


def test_a_reachable_docker_reports_nothing_to_fix() -> None:
    check = check_docker(reachable=True, installed=True)
    assert check.ok
    assert check.breaks == ()


def test_can_start_is_false_only_for_fatal_checks() -> None:
    degraded = Preflight(checks=(check_docker(reachable=False, installed=True),))
    assert degraded.can_start
    assert degraded.degraded

    fatal = Preflight(checks=(check_python_env(exists=False),))
    assert not fatal.can_start


def test_node_modules_missing_stops_the_web_app_and_nothing_else() -> None:
    check = check_node_modules(exists=False)
    assert check.severity is Severity.DEGRADED
    assert check.remedy == "pnpm install"


def test_prod_mode_will_not_fall_back_to_the_dev_env_file() -> None:
    """`.env` sets SANAD_ENVIRONMENT=local.

    Falling back to it would produce a run that looks production-shaped and is
    not — which is the one thing --prod exists to rule out. So a missing
    `.env.production-local` is fatal, not degraded.
    """
    check = check_prod_env_file(exists=False)
    assert check.severity is Severity.FATAL
    assert check.remedy == "just prod-env"


def test_a_missing_web_build_stops_only_the_web_app() -> None:
    """`next start` serves a build; it does not make one."""
    check = check_web_build(exists=False)
    assert check.severity is Severity.DEGRADED
    assert "build" in check.remedy


def test_credentials_report_absence_as_a_mode_never_as_a_failure() -> None:
    """SETUP.md §2: absence is documented, never stubbed.

    Nothing in `credential_states` may return a value — only whether one is set.
    """
    states = credential_states({"GROQ_API_KEY": "sk-live-should-never-be-echoed"})
    groq = next(state for state in states if state.variable == "GROQ_API_KEY")
    assert groq.present
    assert "sk-live" not in groq.gate + groq.without_it

    anthropic = next(state for state in states if state.variable == "ANTHROPIC_API_KEY")
    assert not anthropic.present
    assert "fixture" in anthropic.without_it


def test_an_empty_string_is_not_a_credential() -> None:
    """`GROQ_API_KEY=` in .env is a misconfiguration, not a key."""
    states = credential_states({"GROQ_API_KEY": "   "})
    groq = next(state for state in states if state.variable == "GROQ_API_KEY")
    assert not groq.present


# --- log formatting --------------------------------------------------------

HTTP_RECORD = {
    "method": "GET",
    "path": "/voice/health",
    "status_code": 503,
    "duration_ms": 32.8,
    "event": "http_request",
    "level": "info",
    "logger": "app.core.middleware",
    "timestamp": "2026-08-29T09:06:38.264Z",
    "request_id": "0d20cb28-ffeb-4f91-95bb-2d03de41de12",
    "service": "sanad-api",
}


def test_an_http_record_renders_as_a_request_line() -> None:
    rendered = format_json_record(HTTP_RECORD, colour=False)
    assert rendered == "503 GET    /voice/health 32.8ms req=0d20cb28"


def test_the_request_id_is_shortened_but_still_correlates() -> None:
    """Two records from the same request must carry the same visible id.

    That is the whole point: /voice/health emits a `problem_detail` and an
    `http_request` line, and reading them as one event depends on the id
    matching by eye.
    """
    problem = dict(HTTP_RECORD, event="problem_detail", code="service_unavailable")
    del problem["status_code"]
    first = format_json_record(HTTP_RECORD, colour=False)
    second = format_json_record(problem, colour=False)
    assert "req=0d20cb28" in first
    assert "req=0d20cb28" in second


def test_the_formatter_never_adds_a_field_the_record_did_not_carry() -> None:
    """`app.core.logging` already dropped everything not on its allow-list.

    A formatter that helpfully re-derived, say, a child's name from an id would
    reintroduce exactly what that allow-list exists to remove.
    """
    record = {"event": "startup", "level": "info", "environment": "local"}
    rendered = format_json_record(record, colour=False)
    assert rendered == "startup environment=local"


def test_prose_passes_through_untouched() -> None:
    """uvicorn, Next and docker all emit prose. Rewriting it hides messages."""
    line = format_line("web", "  ▲ Next.js 15.1.3\n", colour=False, clock="12:00:00.000")
    assert line.text.endswith("  ▲ Next.js 15.1.3")
    assert line.raw == "  ▲ Next.js 15.1.3"


def test_a_line_that_looks_like_json_but_is_not_is_left_alone() -> None:
    line = format_line("api", "{not json at all}", colour=False, clock="12:00:00.000")
    assert line.text.endswith("{not json at all}")


def test_the_raw_field_is_the_source_line_so_the_log_file_keeps_the_json() -> None:
    """The file on disk must be the record, not this module's opinion of it."""
    raw = json.dumps(HTTP_RECORD)
    line = format_line("api", raw + "\n", colour=False, clock="12:00:00.000")
    assert line.raw == raw
    assert json.loads(line.raw)["request_id"] == HTTP_RECORD["request_id"]


def test_problems_are_flagged_for_the_runner_without_a_second_parse() -> None:
    assert is_problem_level({"level": "error"})
    assert is_problem_level({"level": "WARNING"})
    assert not is_problem_level({"level": "info"})
    assert not is_problem_level({})


def test_colour_is_absent_when_it_is_not_asked_for() -> None:
    """NO_COLOR and a redirected stdout both land here."""
    rendered = format_line("api", json.dumps(HTTP_RECORD), colour=False, clock="12:00:00.000")
    assert "\x1b[" not in rendered.text


def test_banner_aligns_its_second_column() -> None:
    text = banner("open", [("a", "one"), ("bbbb", "two")], colour=False)
    lines = text.splitlines()
    assert lines[0] == "open"
    assert lines[1] == "  a     one"
    assert lines[2] == "  bbbb  two"


def test_banner_with_no_rows_is_just_a_title() -> None:
    assert banner("nothing", [], colour=False) == "nothing"
