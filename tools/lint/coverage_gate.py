#!/usr/bin/env python
"""Branch-coverage gate: 100% on the deterministic core.

docs/08 §4 sets 85% overall, and 100% BRANCH coverage on
``app/modules/*/domain*`` and ``app/guardrails``. Those two are not arbitrary:

* domain/ computes every number a caregiver ever sees — developmental age,
  developmental quotient, mastery. An untaken branch there is a wrong number in
  a child's record that nothing else will catch.
* guardrails/ is what makes "the AI may be more conservative, never less" true
  rather than aspirational. An untaken branch is a guardrail that has never run.

Reads coverage.xml (produced by `pytest --cov --cov-report=xml`).
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2] / "services" / "api"
COVERAGE_XML = API_ROOT / "coverage.xml"

#: Path fragments (posix form) whose branch coverage must be exactly 100%.
CRITICAL_FRAGMENTS: tuple[str, ...] = (
    "app/modules/",  # narrowed to domain files below
    "app/guardrails/",
)


def _is_critical(filename: str) -> bool:
    """Does this file fall under the 100%-branch rule?

    Two shapes count, and the second one was originally missed:

        app/modules/children/domain.py        a single-module domain
        app/modules/learning/domain/bkt.py    a domain PACKAGE

    docs/08 §4 writes the rule as the glob ``app/modules/*/domain*``, which
    matches both. The first version of this function tested
    ``Path(name).startswith("domain")`` — true for `domain.py`, false for
    `bkt.py` — so every package-style domain silently fell outside the gate.
    That is most of them: the assessment engine, BKT, mastery, the manifest and
    the voice scorer were all unchecked while the gate reported PASS.
    """
    posix = filename.replace("\\", "/")
    # coverage.xml records paths RELATIVE TO <source>, which is `services/api/app`
    # — so a filename reads `modules/learning/domain/bkt.py`, with no `app/`
    # prefix. Matching on "app/modules/" therefore matched nothing at all and the
    # gate reported SKIP on every run, including the ones that recorded 100%
    # branch coverage in PROGRESS.md. The prefix is stripped rather than
    # required, so the check works against either form.
    posix = posix.removeprefix("app/")
    if posix.startswith("guardrails/"):
        return True
    if not posix.startswith("modules/"):
        return False
    return "/domain/" in posix or Path(posix).name.startswith("domain")


def main() -> int:
    if not COVERAGE_XML.exists():
        print(
            f"coverage.xml not found at {COVERAGE_XML}. Run:\n"
            f"  uv run pytest --cov --cov-report=xml",
            file=sys.stderr,
        )
        return 1

    root = ET.parse(COVERAGE_XML).getroot()
    failures: list[str] = []
    checked = 0

    for class_element in root.iter("class"):
        filename = class_element.get("filename", "")
        if not _is_critical(filename):
            continue
        checked += 1
        total = covered = 0
        for line in class_element.iter("line"):
            if line.get("branch") != "true":
                continue
            condition = line.get("condition-coverage", "")
            # format: "50% (1/2)"
            if "(" not in condition:
                continue
            taken, _, out_of = condition.split("(")[1].rstrip(")").partition("/")
            covered += int(taken)
            total += int(out_of)
            if int(taken) < int(out_of):
                failures.append(
                    f"{filename}:{line.get('number')}: branch {condition} — "
                    f"the deterministic core requires 100%"
                )
        if total:
            print(f"  {filename}: {covered}/{total} branches")

    if checked == 0:
        print(
            "COVERAGE GATE SKIP: no app/modules/*/domain*.py or app/guardrails/ files yet.\n"
            "  Activates with P02 (first domain module) and P03 (guardrails)."
        )
        return 0

    if failures:
        print("COVERAGE GATE FAIL: branch coverage below 100% on the core", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print(f"COVERAGE GATE PASS: {checked} critical file(s) at 100% branch coverage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
