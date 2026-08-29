"""Operational CLI: `just seed`, `just eval`.

Both subcommands refuse loudly rather than pretending to succeed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

UPSERT_SKILL = """
    INSERT INTO skills (
        code, category, label_ar, label_vowelised, label_egy, transliteration,
        phonemes, difficulty_tier, intro_order, alt_text_ar, colour,
        distractor_pool, prerequisites
    ) VALUES (
        :code, CAST(:category AS skill_category), :label_ar, :label_vowelised,
        :label_egy, :transliteration, :phonemes, :difficulty_tier, :intro_order,
        :alt_text_ar, CAST(:colour AS jsonb), CAST(:distractor_pool AS jsonb),
        CAST(:prerequisites AS jsonb)
    )
    ON CONFLICT (code) DO UPDATE SET
        category        = EXCLUDED.category,
        label_ar        = EXCLUDED.label_ar,
        label_vowelised = EXCLUDED.label_vowelised,
        label_egy       = EXCLUDED.label_egy,
        transliteration = EXCLUDED.transliteration,
        phonemes        = EXCLUDED.phonemes,
        difficulty_tier = EXCLUDED.difficulty_tier,
        intro_order     = EXCLUDED.intro_order,
        alt_text_ar     = EXCLUDED.alt_text_ar,
        colour          = EXCLUDED.colour,
        distractor_pool = EXCLUDED.distractor_pool,
        prerequisites   = EXCLUDED.prerequisites,
        updated_at      = now()
"""


async def _seed_curriculum() -> int:
    """Load `seeds/curriculum.py` into `skills`.

    An upsert on `code`, so running it twice is a no-op and a curriculum edit is
    picked up without a truncate. It never touches `skill_states`: those belong
    to a child, and a reseed must not reset a child's progress.
    """
    from sqlalchemy import text

    from app.core.config import get_settings
    from app.core.db import init_engine

    try:
        from seeds.curriculum import REVIEWED_BY, build_skills
    except ModuleNotFoundError:
        print(
            "seed: cannot import seeds.curriculum.\n"
            "  Run it from services/api (`just seed` does).",
            file=sys.stderr,
        )
        return 1

    skills = build_skills()
    engine = init_engine(get_settings())
    async with engine.begin() as conn:
        for skill in skills:
            await conn.execute(
                text(UPSERT_SKILL),
                {
                    "code": skill.code,
                    "category": skill.category,
                    "label_ar": skill.label_ar,
                    "label_vowelised": skill.label_vowelised,
                    "label_egy": skill.label_egy,
                    "transliteration": skill.transliteration,
                    "phonemes": skill.phonemes,
                    "difficulty_tier": skill.difficulty_tier,
                    "intro_order": skill.intro_order,
                    "alt_text_ar": skill.alt_text_ar,
                    "colour": json.dumps(skill.colour) if skill.colour else None,
                    "distractor_pool": json.dumps(list(skill.distractor_pool)),
                    "prerequisites": json.dumps(list(skill.prerequisites)),
                },
            )
    await engine.dispose()

    print(f"seed: {len(skills)} skills upserted into `skills`.")
    if not REVIEWED_BY:
        # Loud, and not fatal: local development needs the rows. What must not
        # happen is a family seeing these labels, and that is gated elsewhere.
        print(
            "seed: WARNING — seeds/curriculum.py REVIEWED_BY is empty.\n"
            "  Every vowelisation, phoneme string and distractor pool just\n"
            "  loaded is a mechanically generated PLACEHOLDER. Not for any\n"
            "  child. See REVIEW-QUEUE.md #6.",
            file=sys.stderr,
        )
    return 0


def _seed(_args: argparse.Namespace) -> int:
    return asyncio.run(_seed_curriculum())


def _eval(_args: argparse.Namespace) -> int:
    print(
        "eval: no eval suites yet.\n"
        "  The runner and the golden datasets land with P03 (gateway) and\n"
        "  docs/10. Do not stub a passing result here.",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sanad")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="load seed data").set_defaults(run=_seed)
    sub.add_parser("eval", help="run the AI eval suites").set_defaults(run=_eval)
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
