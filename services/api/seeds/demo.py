"""Demo seed: one caregiver, four children with genuinely different histories.

================================================================================
DEVELOPMENT AND DEMO ONLY
================================================================================
`sanad seed-demo` refuses to run when `SANAD_ENVIRONMENT` is `production`. The
children are fictional, the phone number is in the reserved test range, and the
"history" is a scripted sequence of attempts — real, in that every row goes
through the same tables a real child's would, and fictional, in that no child
did any of it.
================================================================================

**The differences between Ahmed, Laila, Omar and Sara are EVIDENCE, not labels.**
Nothing in the runtime ever reads a child's name. What differs is:

  * their starting-assessment answers, which set per-area BKT priors and a
    support profile;
  * their attempt history, which the mastery fold turns into `skill_states`;
  * which prompt level they answered at, which is what "support that works for
    this child" is computed from.

Those three inputs are what make the tutor loop produce different sessions. If
you delete the histories and keep the names, the three sessions become
identical — which is the property `tests/unit/test_personalisation.py` asserts
from the other direction, by constructing evidence with no names at all.

The histories are laid out over past days so that `distinct_days`, the
three-day delayed pass and the review schedule are all real rather than
manufactured at seed time.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

#: The caregiver every demo child belongs to. `+201000000000` is inside the
#: Egyptian mobile range and is not a routable subscriber number.
DEMO_CAREGIVER_PHONE = "+201000000000"
DEMO_CAREGIVER_NAME = "أم أحمد"

#: Fixed uuids, so the seed is idempotent and a Playwright test can address a
#: child by id without first reading it back.
DEMO_CAREGIVER_ID = "11111111-1111-4111-8111-111111111111"


@dataclass(frozen=True, slots=True)
class ScriptedRun:
    """A block of attempts on one skill: `pattern` is one character per attempt.

    ``+`` correct, ``-`` incorrect, ``.`` no response.
    """

    skill_code: str
    pattern: str
    prompt_level: str = "independent"
    choice_count: int = 2
    #: Days before "today" the block starts. Blocks step forward one day each.
    days_ago: int = 0
    modality: str = "receptive"
    activity_type: str = "select_picture"


@dataclass(frozen=True, slots=True)
class DemoChild:
    child_id: str
    display_name: str
    date_of_birth: str
    max_choices: int
    wait_time_ms: int
    calm_mode: bool
    #: Answers to the starting form, question id -> answer id.
    starting_answers: dict[str, str]
    runs: tuple[ScriptedRun, ...] = field(default_factory=tuple)


def _answers(
    *,
    colors: str,
    numbers: str,
    letters: str,
    words: str,
    speech: str,
    counting: str,
    matching: str,
    shapes: str,
    drawing: str,
    instructions: str,
    demonstration: str,
    selection: str,
    duration: str,
) -> dict[str, str]:
    return {
        "q_colors": colors,
        "q_numbers": numbers,
        "q_counting": counting,
        "q_shapes": shapes,
        "q_letters": letters,
        "q_words": words,
        "q_matching": matching,
        "q_instructions": instructions,
        "q_speech": speech,
        "q_drawing": drawing,
        "q_demonstration": demonstration,
        "q_selection": selection,
        "q_duration": duration,
    }


#: AHMED — numbers low, colours high, letters low. Demonstrations are what work
#: for him: almost every one of his successes is at a prompted level, and the
#: independent attempts he has made on numbers went badly.
AHMED = DemoChild(
    child_id="a0000000-0000-4000-8000-000000000001",
    display_name="أحمد",
    date_of_birth="2019-04-12",
    max_choices=2,
    wait_time_ms=9000,
    calm_mode=False,
    starting_answers=_answers(
        colors="usually",
        numbers="not_yet",
        letters="not_yet",
        words="sometimes",
        speech="starting",
        counting="not_yet",
        matching="sometimes",
        shapes="starting",
        drawing="starting",
        instructions="starting",
        demonstration="usually",
        selection="usually",
        duration="short",
    ),
    runs=(
        # Colours: strong, and increasingly independent.
        ScriptedRun("color_red", "++++++", days_ago=12),
        ScriptedRun("color_blue", "+++++", days_ago=10),
        ScriptedRun("color_red", "++++", days_ago=6),
        ScriptedRun("color_blue", "++++", days_ago=3),
        # Numbers: repeated failure at independent, some success when prompted.
        ScriptedRun("num_1", "--+-", days_ago=9),
        ScriptedRun("num_1", "++++", prompt_level="gestural", days_ago=7),
        ScriptedRun("num_2", "---", days_ago=4),
        ScriptedRun("num_2", "+++", prompt_level="gestural", days_ago=2),
        # Letters: barely started.
        ScriptedRun("letter_alef", "-+-", days_ago=5),
    ),
)

#: LAILA — strong nearly everywhere and mostly independent. She is the child
#: whose next session should be harder, less supported, and more varied.
LAILA = DemoChild(
    child_id="a0000000-0000-4000-8000-000000000002",
    display_name="ليلى",
    date_of_birth="2018-09-30",
    max_choices=4,
    wait_time_ms=6000,
    calm_mode=False,
    starting_answers=_answers(
        colors="usually",
        numbers="usually",
        letters="sometimes",
        words="usually",
        speech="usually",
        counting="sometimes",
        matching="usually",
        shapes="usually",
        drawing="sometimes",
        instructions="usually",
        demonstration="not_yet",
        selection="not_yet",
        duration="long",
    ),
    runs=(
        ScriptedRun("color_red", "++++++", choice_count=4, days_ago=20),
        ScriptedRun("color_blue", "++++++", choice_count=4, days_ago=17),
        ScriptedRun("color_yellow", "+++++", choice_count=4, days_ago=14),
        ScriptedRun("num_1", "++++++", choice_count=4, days_ago=12),
        ScriptedRun("num_2", "+++++", choice_count=4, days_ago=9),
        ScriptedRun("num_1", "++++", choice_count=4, days_ago=5),
        ScriptedRun("hh_cup", "+++++", choice_count=4, days_ago=4),
        ScriptedRun("letter_alef", "+++-+", choice_count=4, days_ago=2),
        # Expressive: she speaks, and it is accepted.
        ScriptedRun(
            "social_thanks",
            "++++",
            modality="expressive",
            activity_type="speak_word",
            days_ago=3,
        ),
    ),
)

#: OMAR — letters high, colours low, and a visual record that is much better
#: than his auditory one. He is the child whose modality should differ.
OMAR = DemoChild(
    child_id="a0000000-0000-4000-8000-000000000003",
    display_name="عمر",
    date_of_birth="2018-01-20",
    max_choices=3,
    wait_time_ms=8000,
    calm_mode=True,
    starting_answers=_answers(
        colors="not_yet",
        numbers="sometimes",
        letters="usually",
        words="sometimes",
        speech="not_yet",
        counting="sometimes",
        matching="usually",
        shapes="sometimes",
        drawing="usually",
        instructions="not_yet",
        demonstration="sometimes",
        selection="sometimes",
        duration="medium",
    ),
    runs=(
        ScriptedRun("letter_alef", "++++++", choice_count=3, days_ago=16),
        ScriptedRun("letter_baa", "+++++", choice_count=3, days_ago=13),
        ScriptedRun("letter_alef", "++++", choice_count=3, days_ago=8),
        ScriptedRun("letter_baa", "++++", choice_count=3, days_ago=4),
        # Colours: he is not getting them.
        ScriptedRun("color_red", "-+--", days_ago=11),
        ScriptedRun("color_blue", "---", days_ago=7),
        ScriptedRun("color_red", "-+-", days_ago=3),
        # Tracing: this is his strength, and it is productive rather than
        # receptive, so it shows up in a different modality bucket entirely.
        ScriptedRun(
            "letter_alef",
            "+++++",
            modality="productive",
            activity_type="trace_letter",
            choice_count=2,
            days_ago=6,
        ),
    ),
)

#: SARA — the child who draws. Her letters were practised months ago and are
#: long past their review date, so they lead her queue on `due_at` rather than
#: on curriculum position; her caregiver reported everything else as "not yet",
#: so the assessment opens only a handful of other skills beside them.
#:
#: SARA — the child who draws. Letters and tracing are where she is furthest
#: along and everything else is only starting, so her session leads with a
#: letter and her best-measured modality is `productive`.
#:
#: She exists because the other three do not reliably reach a tracing activity,
#: and "SANAD chose a tracing activity because this child traces well" is a
#: claim the demo makes. Her history is what makes it true: five passed tracings
#: and nothing else productive, against a thin receptive record.
SARA = DemoChild(
    child_id="a0000000-0000-4000-8000-000000000004",
    display_name="سارة",
    date_of_birth="2018-11-05",
    max_choices=2,
    wait_time_ms=8000,
    calm_mode=False,
    starting_answers=_answers(
        colors="not_yet",
        numbers="not_yet",
        letters="usually",
        words="not_yet",
        speech="not_yet",
        counting="not_yet",
        matching="starting",
        shapes="sometimes",
        drawing="usually",
        instructions="starting",
        demonstration="sometimes",
        selection="sometimes",
        duration="medium",
    ),
    runs=(
        # Letters, receptively: she knows them, and pointing at them is the
        # slower half of what she can do. The misses are the point — a child
        # whose visual record equals their productive one has no modality
        # preference to detect, and the loop would have nothing to act on.
        ScriptedRun("letter_alef", "++-+-", days_ago=150),
        ScriptedRun("letter_baa", "+-++", days_ago=140),
        ScriptedRun("letter_alef", "++-+", days_ago=120),
        ScriptedRun("letter_baa", "-+++", days_ago=100),
        # And the tracing that makes `productive` her strongest record. Two
        # letters, so the loop has somewhere to go after the first.
        ScriptedRun(
            "letter_alef",
            "+++++",
            modality="productive",
            activity_type="trace_letter",
            days_ago=130,
        ),
        ScriptedRun(
            "letter_baa",
            "++++",
            modality="productive",
            activity_type="trace_letter",
            days_ago=110,
        ),
        ScriptedRun(
            "letter_taa",
            "+++",
            modality="productive",
            activity_type="trace_letter",
            days_ago=90,
        ),
    ),
)

DEMO_CHILDREN: tuple[DemoChild, ...] = (AHMED, LAILA, OMAR, SARA)


def attempt_rows(child: DemoChild, today: dt.datetime) -> list[dict[str, object]]:
    """Expand the scripted runs into one dict per attempt, in time order.

    Each attempt inside a run is fifteen minutes after the last, which is not a
    realistic pace — it is a deliberate one. A run has to occupy a single day so
    that `distinct_days` counts sessions rather than attempts, and fifteen
    minutes keeps a six-attempt run inside one afternoon.
    """
    rows: list[dict[str, object]] = []
    for run_index, run in enumerate(child.runs):
        start = today - dt.timedelta(days=run.days_ago)
        for index, mark in enumerate(run.pattern):
            at = start + dt.timedelta(minutes=15 * index)
            result = {"+": "correct", "-": "incorrect", ".": "no_response"}[mark]
            rows.append(
                {
                    "skill_code": run.skill_code,
                    "modality": run.modality,
                    "result": result,
                    "prompt_level": run.prompt_level,
                    "choice_count": run.choice_count,
                    "activity_code": f"{run.activity_type}:{run.skill_code}",
                    "client_ts": at,
                    # Deterministic, so re-running the seed inserts nothing
                    # new — and keyed on the run's DATE as well as its position,
                    # because a run moved to a different day is a different
                    # event. Without the date, editing `days_ago` left the old
                    # attempts in place and the edit had no effect at all.
                    "idempotency_key": (
                        f"demo:{child.child_id}:{run.days_ago}:{run_index}:{index}:{run.skill_code}"
                    ),
                    "latency_ms": 2200 + 300 * (index % 4),
                }
            )
    rows.sort(key=lambda row: row["client_ts"])  # type: ignore[arg-type,return-value]
    return rows


__all__ = [
    "AHMED",
    "DEMO_CAREGIVER_ID",
    "DEMO_CAREGIVER_NAME",
    "DEMO_CAREGIVER_PHONE",
    "DEMO_CHILDREN",
    "LAILA",
    "OMAR",
    "SARA",
    "DemoChild",
    "ScriptedRun",
    "attempt_rows",
]
