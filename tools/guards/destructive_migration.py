#!/usr/bin/env python
"""GUARD 5 — a destructive migration needs a labelled PR and manual approval.

docs/08 §4: "Alembic migrations as a pre-deploy one-off ECS task; forward-only
and additive; a destructive migration requires a labelled PR and manual
approval."

The word "additive" is doing real work there, and the reason is the deploy
ordering rather than caution in the abstract. Migrations run BEFORE the new
tasks start, so for a few minutes the OLD code is running against the NEW
schema. An additive migration is invisible to old code. A `DROP COLUMN` is a
500 on every request that touches the table, from a deploy that has not
technically failed yet.

So this guard fails the deploy unless the change is labelled. It is not a claim
that dropping a column is wrong — it is a claim that dropping one should be a
decision someone made on purpose, in daylight.

Runs in the deploy workflow, not in CI: a destructive migration on a branch is
fine, and it is only shipping one unannounced that is the problem.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "services" / "api" / "migrations" / "versions"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

#: The label that authorises a destructive change.
LABEL = "destructive-migration"

#: Statements that break the old code still serving traffic during the bake.
DESTRUCTIVE = (
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+CONSTRAINT\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+COLUMN\b.*\bSET\s+NOT\s+NULL\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+COLUMN\b.*\bTYPE\b", re.IGNORECASE),
    re.compile(r"\bRENAME\s+(TABLE|COLUMN|TO)\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
    re.compile(r"op\.drop_(table|column|constraint|index)\b"),
    re.compile(r"op\.alter_column\b"),
)

#: A `downgrade()` is allowed to drop what its `upgrade()` created — that is
#: what a downgrade IS, and it never runs during a deploy.
DOWNGRADE = re.compile(r"^def downgrade\(", re.MULTILINE)


def _upgrade_body(source: str) -> str:
    """Everything before `def downgrade`, which is where a deploy's risk lives."""
    match = DOWNGRADE.search(source)
    return source[: match.start()] if match else source


def _changed_migrations() -> list[Path]:
    """Migration files added or modified against the merge base."""
    base = os.environ.get("GITHUB_BASE_REF") or "main"
    try:
        diff = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "diff", "--name-only", f"origin/{base}...HEAD"],  # noqa: S607
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        names = [line.strip() for line in diff.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        names = []

    if names:
        return [
            REPO_ROOT / name
            for name in names
            if "migrations/versions/" in name and name.endswith(".py")
        ]
    # No merge base available (a tag build, a shallow clone). Check everything
    # rather than nothing: a guard that silently inspects an empty set is worse
    # than one that is occasionally noisy.
    return sorted(MIGRATIONS.glob("*.py"))


def main() -> int:
    labels = os.environ.get("PR_LABELS", "")
    authorised = LABEL in {label.strip() for label in labels.split(",")}

    offences: list[str] = []
    for path in _changed_migrations():
        if not path.exists():
            continue
        body = _upgrade_body(path.read_text(encoding="utf-8"))
        for pattern in DESTRUCTIVE:
            for match in pattern.finditer(body):
                line = body[: match.start()].count("\n") + 1
                offences.append(f"{path.relative_to(REPO_ROOT)}:{line}: {match.group(0).strip()}")

    if not offences:
        print("DESTRUCTIVE-MIGRATION PASS: every changed migration is additive.")
        return 0

    if authorised:
        print(f"DESTRUCTIVE-MIGRATION ALLOWED by the '{LABEL}' label:")
        for offence in offences:
            print(f"  {offence}")
        return 0

    print("DESTRUCTIVE-MIGRATION FAIL", file=sys.stderr)
    print(
        "\nMigrations run BEFORE the new tasks start, so for the length of the\n"
        "bake the OLD code is serving traffic against the NEW schema. Each of\n"
        "these would break it:\n",
        file=sys.stderr,
    )
    for offence in offences:
        print(f"  {offence}", file=sys.stderr)
    print(
        f"\nEither split it into an additive step now and a destructive step in a\n"
        f"later release, or add the '{LABEL}' label to the PR and get the\n"
        f"manual approval docs/08 §4 requires.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
