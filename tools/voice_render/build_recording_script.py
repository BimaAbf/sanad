#!/usr/bin/env python
"""`just voice-script` — write the Nour recording script from the curriculum.

    uv --directory services/api run python ../../tools/voice_render/build_recording_script.py

Reads `seeds/curriculum.py` and writes `dist/nour-recording-script.md`. Both the
assembly and the phonetic-coverage check live in `recording_script.py`, which is
pure and tested; this file only fetches the seed data and writes the file.
"""

from __future__ import annotations

import sys
from pathlib import Path

from seeds.curriculum import ACTIVITY_TEMPLATES, RETRY_POOL, REVIEWED_BY, SUCCESS_POOL, build_skills

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_render.recording_script import build_blocks, render_markdown

OUTPUT = Path(__file__).resolve().parents[2] / "dist" / "nour-recording-script.md"

#: One representative label per instruction frame. The talent records the frame
#: with a real word in it, not with a "{label}" placeholder she would have to
#: read aloud — and one word per frame is enough, because the render substitutes
#: the other 87 by concatenating the frame's prosody with a separately recorded
#: label clip.
FRAME_EXAMPLE = "الكورة"

#: docs/04d §3. Said when the recogniser could not make out the attempt. Never
#: in `curriculum.py` because it is voice-gateway copy, not curriculum content.
UNCLEAR_LINES: tuple[str, ...] = (
    "مش سامعة كويس، قولها تاني",
    "قريب أوي! جرّب تاني معايا",
    "شاطر! سمعتك",
)


def main() -> int:
    skills = build_skills()
    labels = [skill.label_egy or skill.label_ar for skill in skills]
    instructions = sorted(
        {
            template.instruction_ar.replace("{label}", FRAME_EXAMPLE)
            for template in ACTIVITY_TEMPLATES
        }
    )
    blocks = build_blocks(
        labels=labels,
        instructions=instructions,
        success_lines=SUCCESS_POOL,
        retry_lines=RETRY_POOL,
        unclear_lines=UNCLEAR_LINES,
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_markdown(blocks, reviewed_by=REVIEWED_BY), encoding="utf-8")
    print(f"wrote {OUTPUT}")
    if not REVIEWED_BY:
        print(
            "  seeds/curriculum.py REVIEWED_BY is empty — the script carries a "
            "DO NOT RECORD banner until a native speaker signs off (REVIEW-QUEUE #6)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
