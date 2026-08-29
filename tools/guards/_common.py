"""Shared helpers for the four project-specific CI guard checks.

Each guard prevents a class of bug that ordinary testing misses (docs/08 §4).
They are deliberately cheap: a guard that takes a minute stops being run.

A guard has three possible outcomes:
  PASS  — the invariant holds
  FAIL  — the invariant is violated; exit 1 and name the offending file:line
  SKIP  — the code the guard checks does not exist yet (pre-P03, pre-P05 ...);
          exit 0, but say loudly which component will activate it.

SKIP is not a way to defer the work. Each guard's TODO names the P-prompt that
must turn it on, and tools/guards/test_guards.py asserts the guard fires on its
violation fixture even while the real tree is still empty.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

# Guard messages contain em-dashes and (in future) Arabic; a Windows console
# defaults to cp1252 and would crash the guard on exactly the run where it has
# something to report.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "services" / "api"
APP_ROOT = API_ROOT / "app"


class GuardResult:
    def __init__(self, name: str) -> None:
        self.name = name
        self.violations: list[str] = []
        self.skipped_reason: str | None = None

    def violation(self, path: Path, line: int, message: str) -> None:
        try:
            shown = path.relative_to(REPO_ROOT)
        except ValueError:
            shown = path
        self.violations.append(f"{shown}:{line}: {message}")

    def skip(self, reason: str) -> None:
        self.skipped_reason = reason

    def report(self) -> int:
        if self.violations:
            print(f"GUARD FAIL: {self.name}", file=sys.stderr)
            for violation in self.violations:
                print(f"  {violation}", file=sys.stderr)
            return 1
        if self.skipped_reason:
            print(f"GUARD SKIP: {self.name} — {self.skipped_reason}")
            return 0
        print(f"GUARD PASS: {self.name}")
        return 0


def python_files(root: Path, *, exclude: tuple[str, ...] = ()) -> Iterator[Path]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*.py")):
        parts = path.parts
        if any(marker in parts for marker in ("__pycache__", ".venv", *exclude)):
            continue
        yield path
