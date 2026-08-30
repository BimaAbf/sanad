#!/usr/bin/env python
"""banned-terms lint — docs/06-frontend-ux.md §3, "Copy guidelines (binding)".

The list is not stylistic. Every term on it reframes a child as deficient, and
the caregiver reading it is a parent, not a clinician. "متأخر" (delayed) is the
one that matters most: it is the word the product exists to avoid.

Scope: user-facing strings only — the i18n bundles, and any Arabic string
literal in a component. Not code comments, not this file, not the design docs
(which quote the banned terms in order to ban them).

Adding a term to ALLOWED_EXCEPTIONS requires a reviewer from the clinical
partner (docs/06 §3). Do not add one to make a build pass.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The failure message is written in Arabic, and a Windows console defaults to
# cp1252. Without this the lint crashes on exactly the run where it has
# something to say.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

#: Transcribed verbatim from docs/06 §3.
BANNED_EN: tuple[str, ...] = (
    "delay",
    "deficit",
    "behind",
    "normal children",
    "problem",
    "failed",
    "score",
    "IQ",
    "should be able to",
)
BANNED_AR: tuple[str, ...] = (
    "أطفال طبيعيين",
    "متأخر",
)

#: Terms a clinical reviewer has explicitly signed off in a specific context.
#: Empty, and it should stay that way without a name attached.
ALLOWED_EXCEPTIONS: frozenset[str] = frozenset()

#: Where user-facing copy lives.
BUNDLE_GLOBS: tuple[str, ...] = ("apps/web/src/messages/*.json",)
SOURCE_GLOBS: tuple[str, ...] = ("apps/web/src/**/*.tsx",)

#: Keys inside a bundle that are metadata for developers, not copy for users.
NON_COPY_KEYS: frozenset[str] = frozenset({"_meta"})

_ARABIC_LITERAL = re.compile("\"([^\"]*[؀-ۿ][^\"]*)\"")


def _offences(text: str) -> list[str]:
    lowered = text.lower()
    hits = [term for term in BANNED_EN if term in lowered and term not in ALLOWED_EXCEPTIONS]
    hits += [term for term in BANNED_AR if term in text and term not in ALLOWED_EXCEPTIONS]
    return hits


def _walk_bundle(node: object, path: str, found: list[tuple[str, str, list[str]]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in NON_COPY_KEYS:
                continue
            _walk_bundle(value, f"{path}.{key}" if path else str(key), found)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_bundle(value, f"{path}[{index}]", found)
    elif isinstance(node, str):
        hits = _offences(node)
        if hits:
            found.append((path, node, hits))


def main() -> int:
    failures: list[str] = []

    for pattern in BUNDLE_GLOBS:
        for bundle in sorted(REPO_ROOT.glob(pattern)):
            data = json.loads(bundle.read_text(encoding="utf-8"))
            found: list[tuple[str, str, list[str]]] = []
            _walk_bundle(data, "", found)
            for key, value, hits in found:
                failures.append(
                    f"{bundle.relative_to(REPO_ROOT)}: {key} contains {hits}\n    {value!r}"
                )

    for pattern in SOURCE_GLOBS:
        for source in sorted(REPO_ROOT.glob(pattern)):
            for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
                for literal in _ARABIC_LITERAL.findall(line):
                    hits = _offences(literal)
                    if hits:
                        failures.append(
                            f"{source.relative_to(REPO_ROOT)}:{number}: contains {hits}\n"
                            f"    {literal!r}"
                        )

    if failures:
        print("BANNED-TERMS FAIL — docs/06 §3 forbids these in user-facing copy:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        print(
            "\n  Write instead: بيتعلم دلوقتي · الخطوة الجاية · نراجع مع بعض · تقدّم",
            file=sys.stderr,
        )
        return 1

    print("BANNED-TERMS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
