"""The script you hand the person who becomes Nour.

REVIEW-QUEUE #10 is the longest-lead item in the project and it has not started,
partly because `SETUP.md` §4 says "script provided by the agent" and no such
script existed. This produces it, from the repo's own curriculum rather than
from a generic phonetic wordlist, for three reasons:

* A voice clone reproduces the *register* it was trained on. Twenty minutes of
  neutral news-reading produces a Nour who reads the news. The utterances she
  will actually say — short, warm, addressed to a small child, with long pauses
  — have to be in the training audio.
* The 88 labels are the words the child hears most. They should be spoken by
  the real person, not synthesised from a distribution.
* Coverage can then be **checked** rather than assumed. `phoneme_coverage`
  reports which of the g2p inventory's phonemes never occur in the script; a
  clone trained without /ʕ/ renders /ʕ/ badly, and that is a defect discovered
  in the studio for free or in the listening test for the price of a re-book.

  ⚠️ **The Arabic in the output is placeholder Arabic.** Every label and every
  feedback line comes from `seeds/curriculum.py`, whose `REVIEWED_BY` header is
  empty. Vowelisation is mechanical. A native Egyptian speaker must pass over
  the generated script before anyone reads it into a microphone — REVIEW-QUEUE
  #1 and #6. Recording 25 minutes of subtly wrong Arabic and cloning it is the
  expensive version of that mistake.

Pure except for `render_markdown`, which returns a string. `run` in the CLI at
the bottom is the only thing that touches a file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.voice.domain.g2p import (
    CONSONANTS,
    LETTER_TO_PHONEME,
    LONG_VOWELS,
    g2p,
)

#: docs/12 §3.1 — VoxCPM2 wants 20–30 minutes. At the deliberate pace this
#: product is recorded at, budget roughly 4 seconds per short utterance
#: including the pause before and after.
SECONDS_PER_UTTERANCE = 4.0
TARGET_MINUTES_MIN = 20
TARGET_MINUTES_MAX = 30

#: Phonemes `g2p` can emit but which no Arabic grapheme maps to — they exist in
#: the inventory for loanwords and for the emphatic-pair table. Absence from the
#: script is expected and is not reported as a gap.
NOT_EXPECTED: frozenset[str] = frozenset("Rvpq")


@dataclass(frozen=True, slots=True)
class Block:
    """One numbered section of the script."""

    title: str
    purpose: str
    lines: tuple[str, ...]
    #: Read-aloud direction for this block, in English, for the engineer and
    #: the talent. Not spoken.
    direction: str = ""
    #: How many takes of each line. More than one is not redundancy: a voice
    #: clone trained on a single reading of each line reproduces that reading,
    #: and the lines a child hears most need the most variation within one
    #: consistent voice.
    takes: int = 1
    #: Warm-up audio is discarded, so it does not count toward the corpus.
    counts_toward_corpus: bool = True


@dataclass(frozen=True, slots=True)
class Coverage:
    covered: frozenset[str]
    missing: frozenset[str]

    @property
    def complete(self) -> bool:
        return not self.missing


def phoneme_coverage(lines: Sequence[str]) -> Coverage:
    """Which phonemes of the inventory the script actually exercises.

    Checked against what `g2p` can emit from Arabic text, minus `NOT_EXPECTED`.
    A missing phoneme is a real finding: the clone has never heard the talent
    produce it, so every product utterance containing it is extrapolation.
    """
    produced: set[str] = set()
    for line in lines:
        produced.update(g2p(line))
    expected = (set(LETTER_TO_PHONEME.values()) | set(LONG_VOWELS)) - NOT_EXPECTED
    expected &= set(CONSONANTS) | set(LONG_VOWELS)
    return Coverage(
        covered=frozenset(produced & expected),
        missing=frozenset(expected - produced),
    )


def recorded_utterances(blocks: Sequence[Block]) -> int:
    """Total takes that end up in the training corpus."""
    return sum(len(block.lines) * block.takes for block in blocks if block.counts_toward_corpus)


def estimated_minutes(blocks: Sequence[Block]) -> float:
    return recorded_utterances(blocks) * SECONDS_PER_UTTERANCE / 60.0


def shortfall_minutes(blocks: Sequence[Block]) -> float:
    """How far below the 20-minute floor this script leaves the session.

    Reported rather than padded. The curriculum is 88 short words and a handful
    of frames; it does not fill a cloning session on its own, and the honest
    thing to do is say so and name what the gap has to be filled with, not
    silently invent Arabic to reach a number.
    """
    return max(0.0, TARGET_MINUTES_MIN - estimated_minutes(blocks))


def build_blocks(
    *,
    labels: Sequence[str],
    instructions: Sequence[str],
    success_lines: Sequence[str],
    retry_lines: Sequence[str],
    unclear_lines: Sequence[str] = (),
) -> tuple[Block, ...]:
    """Assemble the script.

    Order is deliberate and is a recording-session decision, not a data one:
    warm-up first, then the emotionally neutral bulk while the voice is fresh,
    then the praise lines last — praise recorded in the first ten minutes of a
    session sounds like someone reading, and praise is the single utterance a
    child hears most often.
    """
    return (
        Block(
            "Warm-up — not used",
            "Levels, room tone, and getting the pace right. Discard the audio.",
            (
                "صباح الخير، أنا نور",
                "إحنا هنلعب مع بعض النهارده",
                "خد وقتك، مفيش استعجال",
            ),
            direction=(
                "Read these three at the pace you would use with a three-year-old who "
                "is still learning to speak — noticeably slower than conversation, with "
                "a clear pause at the end of each line. Record 30 seconds of silence in "
                "the room before the first line."
            ),
            counts_toward_corpus=False,
        ),
        Block(
            "The words",
            "The 88 curriculum labels. These are the words a child hears most.",
            tuple(labels),
            direction=(
                "One word per take, with a full breath between them. Say each as you "
                "would to a child pointing at the object — warm, unhurried, complete. "
                "Do not trail off at the end of the word; the final consonant matters, "
                "because the child is learning to reproduce it."
            ),
            takes=2,
        ),
        Block(
            "The instructions",
            "The sentence frames the product speaks around every label.",
            tuple(instructions),
            direction=(
                "These are requests, not commands, and never impatient. The emphasis "
                "falls on the last word — the thing being asked for. Leave a long pause "
                "after each: in the product a child is given several seconds to answer, "
                "and the clip has to end cleanly before that silence starts."
            ),
            takes=2,
        ),
        Block(
            "Praise",
            "Said after every correct answer. Recorded last, on purpose.",
            tuple(success_lines),
            direction=(
                "Genuinely pleased, not theatrical. A child hears these dozens of times "
                "in a session; anything performed becomes grating by the tenth. Give "
                "each line three takes with different warmth and let us choose."
            ),
            takes=3,
        ),
        Block(
            "Encouragement",
            "Said after a wrong or unclear answer. There is no failure state here.",
            (*retry_lines, *unclear_lines),
            direction=(
                "This is the most important direction in the session. None of these "
                "lines corrects the child, and none may sound disappointed. The product "
                "never tells a child they were wrong — it says it did not hear well. "
                "Read them as you would to a child who is trying hard."
            ),
            takes=3,
        ),
    )


def all_lines(blocks: Sequence[Block]) -> tuple[str, ...]:
    return tuple(line for block in blocks for line in block.lines)


def render_markdown(blocks: Sequence[Block], *, reviewed_by: str = "") -> str:
    """The document a studio can print."""
    lines = all_lines(blocks)
    coverage = phoneme_coverage(lines)
    minutes = estimated_minutes(blocks)
    takes = recorded_utterances(blocks)
    shortfall = shortfall_minutes(blocks)

    out: list[str] = [
        "# Nour — recording script",
        "",
    ]
    if not reviewed_by:
        out += [
            "> ⚠️ **DO NOT RECORD THIS YET.** Every Arabic string below comes from",
            "> `seeds/curriculum.py`, whose `REVIEWED_BY` header is empty: the labels are",
            "> transcribed from the architecture package but the vowelisation is",
            "> mechanical and the feedback lines are agent-written. A native Egyptian",
            "> Arabic speaker must pass over this document first — REVIEW-QUEUE #1 and #6.",
            "> Recording 25 minutes of subtly wrong Arabic and cloning it is the",
            "> expensive way to discover that.",
            "",
        ]
    else:
        out += [f"Arabic reviewed by: **{reviewed_by}**", ""]

    out += [
        f"{len(lines)} distinct lines · {takes} recorded takes · roughly "
        f"**{minutes:.0f} minutes** at {SECONDS_PER_UTTERANCE:.0f} seconds a take.",
        "",
        f"Target is {TARGET_MINUTES_MIN}–{TARGET_MINUTES_MAX} minutes (docs/12 §3.1).",
        "",
    ]
    if shortfall > 0:
        out += [
            f"> ⚠️ **This script is about {shortfall:.0f} minutes short of the "
            f"{TARGET_MINUTES_MIN}-minute floor, and the gap is not padding.**",
            ">",
            "> The curriculum is 88 isolated words and six short frames. A clone trained",
            "> only on isolated words reproduces isolated-word prosody: every sentence it",
            "> later synthesises sounds like a list. The missing minutes have to be",
            "> **connected Egyptian speech in the same register** — the talent talking to",
            "> a child for ten minutes, not reading more words.",
            ">",
            "> That passage is not generated here on purpose. It is unscripted or",
            "> lightly-scripted natural speech, it must be Egyptian colloquial as a native",
            "> speaker would actually say it, and it is exactly the content REVIEW-QUEUE #1",
            "> and #6 exist to keep an agent from inventing. Ask the native-speaker",
            "> reviewer to write or improvise it — a picture-book read aloud, or a",
            "> description of a room, works and takes them twenty minutes.",
            "",
        ]
    out += [
        "## Before the session",
        "",
        "| | |",
        "|---|---|",
        "| Format | 48 kHz, 24-bit, mono WAV. No compression, no noise reduction, no EQ. |",
        "| Room | Quiet and dry. Soft furnishings, no hard parallel walls, no HVAC. |",
        "| Mic | Large-diaphragm condenser at 20–25 cm, slightly off-axis, pop filter. |",
        "| Level | Peaks around −12 dBFS. Headroom matters more than loudness; the "
        "corpus is normalised to −16 LUFS afterwards. |",
        "| Takes | Keep every take. Do not comp in the studio — the clone is trained on "
        "consistency, and choosing takes is a judgement we make with the therapist. |",
        "| Consistency | One session, one position, one mic, one set of levels. If a "
        "second session is unavoidable, photograph the setup. |",
        "",
        "**The release comes first.** Do not record until the perpetual, transferable "
        "synthetic-reproduction licence is signed. See "
        "`docs/setup/01-nour-voice.md` §4 — this is a contract, not a formality.",
        "",
    ]

    for index, block in enumerate(blocks, start=1):
        out += [f"## {index}. {block.title}", "", f"_{block.purpose}_", ""]
        if block.direction:
            out += [f"**Direction.** {block.direction}", ""]
        out += [f"{number}. {line}" for number, line in enumerate(block.lines, start=1)]
        out += [""]

    out += ["## Phonetic coverage", ""]
    if coverage.complete:
        out += [
            "Every phoneme the product's grapheme-to-phoneme table can produce occurs "
            "somewhere in this script. ✅",
            "",
        ]
    else:
        out += [
            "**These phonemes never occur in the script above**, so the clone will never "
            "have heard the talent produce them and every product utterance containing "
            "one is extrapolation:",
            "",
            "  " + " ".join(sorted(coverage.missing)),
            "",
            "Add a word containing each before the session, or accept the gap knowingly.",
            "",
        ]
    out += [
        f"Covered: {len(coverage.covered)} of {len(coverage.covered) + len(coverage.missing)}.",
        "",
    ]
    return "\n".join(out)
