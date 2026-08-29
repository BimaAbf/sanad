"""Operational CLI: `just seed`, `just eval`.

Both subcommands exist so the justfile contract from P00 is real rather than
aspirational, and both refuse loudly rather than pretending to succeed. Seeding
needs a schema (P02) and an item bank (P04/P06); evals need the gateway (P03).
"""

from __future__ import annotations

import argparse
import sys


def _seed(_args: argparse.Namespace) -> int:
    print(
        "seed: nothing to seed yet.\n"
        "  Consent definitions land with P02, the item bank with P04,\n"
        "  the curriculum with P06. Seeds live in services/api/seeds/.",
        file=sys.stderr,
    )
    return 1


def _eval(_args: argparse.Namespace) -> int:
    print(
        "eval: no eval suites yet.\n"
        "  The runner and the golden datasets land with P03 (gateway) and\n"
        "  docs/10. Do not stub a passing result here.",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="misk")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="load seed data").set_defaults(run=_seed)
    sub.add_parser("eval", help="run the AI eval suites").set_defaults(run=_eval)
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
