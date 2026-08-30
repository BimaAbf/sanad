"""Load the demo family into a real database. `sanad seed-demo`.

Everything here goes through the same tables and the same domain code a real
family's data would. Specifically:

  * the starting assessment is DERIVED by `starting/domain/form.derive`, not
    hand-written, so a demo child's priors are whatever the form produces from
    the answers in `seeds/demo.py`;
  * the histories are inserted as `attempts` rows and then folded by
    `MasteryService.apply_session`, which is the same call the runtime makes —
    so `skill_states`, `p_known` and every mastery transition are computed, not
    asserted;
  * rewards go through `tutor/domain/rewards.py` and land in `reward_events`
    with the attempt's own idempotency key, so re-running the seed adds no
    stars.

Idempotent end to end. Every insert is `ON CONFLICT DO NOTHING` against a
deterministic key, so `just seed-demo` twice leaves the same database.

It refuses to run against `SANAD_ENVIRONMENT=production`. Demo children in a
production database would be indistinguishable from real ones to every query in
the product, including the ones that count how many children it has.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.learning.repository import LearningRepository
from app.modules.learning.service import MasteryService
from app.modules.starting.domain import form
from app.modules.starting.repository import StartingRepository
from app.modules.starting.service import SEED_MODALITY
from app.modules.tutor.domain import report as report_domain
from app.modules.tutor.domain import rewards as rewards_domain
from app.modules.tutor.repository import TutorRepository
from seeds.demo import (
    DEMO_CAREGIVER_ID,
    DEMO_CAREGIVER_NAME,
    DEMO_CAREGIVER_PHONE,
    DEMO_CHILDREN,
    DemoChild,
    attempt_rows,
)

UPSERT_CAREGIVER = text("""
    INSERT INTO caregivers (id, phone_e164, display_name)
    VALUES (CAST(:id AS uuid), :phone, :name)
    ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name
""")

UPSERT_CHILD = text("""
    INSERT INTO children (
        id, display_name, date_of_birth, comms_level, max_choices,
        wait_time_ms, calm_mode
    ) VALUES (
        CAST(:id AS uuid), :name, :dob, 'single_words',
        :max_choices, :wait_time_ms, :calm_mode
    )
    ON CONFLICT (id) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        max_choices  = EXCLUDED.max_choices,
        wait_time_ms = EXCLUDED.wait_time_ms,
        calm_mode    = EXCLUDED.calm_mode
""")

LINK = text("""
    INSERT INTO caregiver_child (caregiver_id, child_id, role)
    VALUES (CAST(:caregiver_id AS uuid), CAST(:child_id AS uuid), 'owner')
    ON CONFLICT DO NOTHING
""")

#: Every consent the demo needs granted, including the optional ones — a demo
#: that cannot use the microphone because nobody ticked a box is a demo of the
#: consent gate rather than of the product.
GRANT_CONSENTS = text("""
    INSERT INTO consents (child_id, caregiver_id, consent_key, version, status)
    SELECT CAST(:child_id AS uuid), CAST(:caregiver_id AS uuid), cd.key, cd.version, 'granted'
    FROM consent_definitions cd
    WHERE NOT EXISTS (
        SELECT 1 FROM consents c
        WHERE c.child_id = CAST(:child_id AS uuid) AND c.consent_key = cd.key
    )
""")

SELECT_SKILL_ID = text("SELECT id FROM skills WHERE code = :code")

INSERT_SESSION = text("""
    INSERT INTO play_sessions (
        id, child_id, started_by, plan, plan_source, started_at, ended_at,
        ended_reason, activities_done, correct_count
    ) VALUES (
        CAST(:id AS uuid), CAST(:child_id AS uuid), CAST(:started_by AS uuid),
        '[]'::jsonb, 'deterministic_fallback', :started_at, :ended_at,
        'completed', :done, :correct
    )
    ON CONFLICT (id) DO NOTHING
""")

INSERT_ATTEMPT = text("""
    INSERT INTO attempts (
        session_id, child_id, activity_code, skill_id, modality, result,
        prompt_level, latency_ms, choice_count, client_ts, idempotency_key
    ) VALUES (
        CAST(:session_id AS uuid), CAST(:child_id AS uuid), :activity_code,
        :skill_id, CAST(:modality AS modality), CAST(:result AS attempt_result),
        CAST(:prompt_level AS prompt_level), :latency_ms, :choice_count,
        :client_ts, :idempotency_key
    )
    ON CONFLICT (idempotency_key) DO NOTHING
""")

INSERT_SESSION_END_EVENT = text("""
    INSERT INTO events (child_id, caregiver_id, name, props, client_ts, idempotency_key)
    SELECT CAST(:child_id AS uuid), CAST(:caregiver_id AS uuid), 'session_end',
           CAST(:props AS jsonb), :client_ts, :idempotency_key
    WHERE NOT EXISTS (SELECT 1 FROM events WHERE idempotency_key = :idempotency_key)
""")

DELETE_STARTING = text("""
    DELETE FROM starting_assessments WHERE child_id = CAST(:child_id AS uuid)
""")


#: Namespace for the demo's derived ids. A fixed uuid, so `seed-demo` produces
#: the same session ids on every machine and in every run.
DEMO_NAMESPACE = uuid5(NAMESPACE_URL, "https://sanad.app/seeds/demo")


def _session_uuid(child_id: str, day: dt.date) -> str:
    """A deterministic session id per child per day.

    uuid5 rather than a hand-assembled string: the first version of this built
    the last group from `%Y%m%d`, which is ten hex digits where a uuid needs
    twelve, and asyncpg rejected every row. Deriving it removes the arithmetic.

    Per-day, so `distinct_days` and the streak counter see a history of separate
    sittings rather than one very long session.
    """
    return str(uuid5(DEMO_NAMESPACE, f"{child_id}:{day.isoformat()}"))


async def _skill_ids(session: AsyncSession, codes: set[str]) -> dict[str, UUID]:
    found: dict[str, UUID] = {}
    for code in sorted(codes):
        row = (await session.execute(SELECT_SKILL_ID, {"code": code})).one_or_none()
        if row is not None:
            found[code] = row.id
    return found


async def _skill_labels(session: AsyncSession, codes: list[str]) -> dict[str, str]:
    """code -> Arabic label, for the report's caregiver-facing lists."""
    found: dict[str, str] = {}
    for code in codes:
        row = (
            await session.execute(
                text("SELECT label_ar FROM skills WHERE code = :code"), {"code": code}
            )
        ).one_or_none()
        if row is not None:
            found[code] = str(row.label_ar)
    return found


async def _seed_starting_assessment(
    session: AsyncSession, child: DemoChild, caregiver_id: str
) -> int:
    """Run the real form derivation and write the real learner state."""
    repo = StartingRepository(session)
    # A demo re-run re-derives from scratch: the answers in `seeds/demo.py` are
    # the source of truth for a demo child, and an assessment left over from a
    # previous version of them would be a second, stale answer log.
    await session.execute(DELETE_STARTING, {"child_id": child.child_id})
    row = await repo.create(
        child_id=UUID(child.child_id),
        started_by=UUID(caregiver_id),
        form_version=form.FORM_VERSION,
    )
    for question_id, answer_id in child.starting_answers.items():
        await repo.record_answer(
            assessment_id=UUID(str(row.id)), question_id=question_id, answer_id=answer_id
        )

    profile = form.derive(child.starting_answers)
    now = dt.datetime.now(dt.UTC)
    await repo.finalise(
        assessment_id=UUID(str(row.id)),
        area_levels=profile.area_bands,
        supports=profile.as_json(),
        now=now,
    )

    seeded = 0
    wanted: dict[str, tuple[int, float, str]] = {}
    for seed in profile.seeds:
        current = wanted.get(seed.category)
        if current is None or seed.rank + 1 > current[0]:
            wanted[seed.category] = (seed.rank + 1, seed.prior, seed.state)
    for category, (count, prior, state) in sorted(wanted.items()):
        for skill in await repo.category_head(category=category, limit=count):
            await repo.seed_state(
                {
                    "child_id": UUID(child.child_id),
                    "skill_id": skill.id,
                    "modality": SEED_MODALITY,
                    "state": state,
                    "p_known": prior,
                    "p_prior": prior,
                    "due_at": now,
                    "now": now,
                }
            )
            seeded += 1

    await TutorRepository(session).upsert_profile(
        {
            "child_id": UUID(child.child_id),
            "source": "starting_assessment",
            "starting_assessment_id": UUID(str(row.id)),
            "effective_support": profile.effective_support,
            "effective_modality": profile.effective_modality,
            "demonstration_helps": profile.demonstration_helps,
            "follows_spoken": profile.follows_spoken,
            "comfortable_speaking": profile.comfortable_speaking,
            "comfortable_minutes": profile.comfortable_minutes,
            "area_levels": profile.area_bands,
        }
    )
    return seeded


async def _seed_history(
    session: AsyncSession, child: DemoChild, caregiver_id: str, today: dt.datetime
) -> tuple[int, int]:
    """Insert the scripted attempts and fold them into real learner state."""
    rows = attempt_rows(child, today)
    ids = await _skill_ids(session, {str(row["skill_code"]) for row in rows})
    labels = await _skill_labels(session, sorted(ids))

    by_day: dict[dt.date, list[dict[str, Any]]] = {}
    for row in rows:
        moment: dt.datetime = row["client_ts"]  # type: ignore[assignment]
        by_day.setdefault(moment.date(), []).append(row)

    tutor = TutorRepository(session)
    mastery = MasteryService(repo=LearningRepository(session))
    attempts = 0
    stars = 0

    for day in sorted(by_day):
        day_rows = by_day[day]
        session_id = _session_uuid(child.child_id, day)
        started = day_rows[0]["client_ts"]
        ended = day_rows[-1]["client_ts"]
        correct = sum(
            1 for row in day_rows if str(row["result"]) in rewards_domain.REWARDED_RESULTS
        )
        await session.execute(
            INSERT_SESSION,
            {
                "id": session_id,
                "child_id": child.child_id,
                "started_by": caregiver_id,
                "started_at": started,
                "ended_at": ended,
                "done": len(day_rows),
                "correct": correct,
            },
        )
        for row in day_rows:
            skill_id = ids.get(str(row["skill_code"]))
            if skill_id is None:
                # A code this deployment's catalogue does not have. Skipping it
                # loses one demo attempt; failing would make `seed-demo`
                # unusable against a partially seeded curriculum.
                continue
            attempts += 1
            await session.execute(
                INSERT_ATTEMPT,
                {
                    "session_id": session_id,
                    "child_id": child.child_id,
                    "activity_code": row["activity_code"],
                    "skill_id": skill_id,
                    "modality": row["modality"],
                    "result": row["result"],
                    "prompt_level": row["prompt_level"],
                    "latency_ms": row["latency_ms"],
                    "choice_count": row["choice_count"],
                    "client_ts": row["client_ts"],
                    "idempotency_key": row["idempotency_key"],
                },
            )
            grant = rewards_domain.attempt_reward(
                result=str(row["result"]),
                prompt_level=str(row["prompt_level"]),
                attempt_key=str(row["idempotency_key"]),
            )
            if grant is not None and await tutor.grant_reward(
                {
                    "child_id": UUID(child.child_id),
                    "session_id": UUID(session_id),
                    "activity_id": None,
                    "kind": grant.kind,
                    "stars": grant.stars,
                    "reason": grant.reason,
                    "idempotency_key": grant.idempotency_key,
                }
            ):
                stars += grant.stars

        bonus = rewards_domain.session_reward(session_id=session_id, activities_done=len(day_rows))
        if bonus is not None and await tutor.grant_reward(
            {
                "child_id": UUID(child.child_id),
                "session_id": UUID(session_id),
                "activity_id": None,
                "kind": bonus.kind,
                "stars": bonus.stars,
                "reason": bonus.reason,
                "idempotency_key": bonus.idempotency_key,
            }
        ):
            stars += bonus.stars

        # The session summary, computed by the same code the runtime uses.
        # A seeded session with no summary is a session the caregiver report
        # cannot open — and the demo's report screen reads the newest FINISHED
        # session, which is a seeded one until the caregiver plays a full one.
        facts = report_domain.compute(
            [
                report_domain.AttemptFact(
                    skill_code=str(row["skill_code"]),
                    skill_label_ar=labels.get(str(row["skill_code"]), str(row["skill_code"])),
                    activity_type=str(row["activity_code"]).split(":")[0],
                    result=str(row["result"]),
                    prompt_level=str(row["prompt_level"]),
                    latency_ms=int(row["latency_ms"]),  # type: ignore[arg-type]
                    at=row["client_ts"],  # type: ignore[arg-type]
                )
                for row in day_rows
                if str(row["skill_code"]) in ids
            ],
            stars_earned=await tutor.session_stars(UUID(session_id)),
            duration_minutes=max(1, len(day_rows) * 2),
        )
        narrative, source, _rejected = report_domain.resolve_narrative(
            ai_narrative=None, facts=facts
        )
        await tutor.save_summary(
            {
                "session_id": UUID(session_id),
                "child_id": UUID(child.child_id),
                "facts": facts.as_json(),
                "narrative_ar": narrative,
                "narrative_source": source,
            }
        )

        await session.execute(
            INSERT_SESSION_END_EVENT,
            {
                "child_id": child.child_id,
                "caregiver_id": caregiver_id,
                "props": json.dumps(
                    {
                        "session_id": session_id,
                        "minutes": max(1, len(day_rows) * 2),
                        "attempts": len(day_rows),
                        "correct": correct,
                        "by_category": {},
                    }
                ),
                "client_ts": ended,
                "idempotency_key": f"session_end:{session_id}",
            },
        )

        # The real fold, per skill this day touched, at the time it happened —
        # so `due_at`, `distinct_days` and the delayed pass all land where a
        # real history would have put them.
        targets = await LearningRepository(session).session_targets(UUID(session_id))
        for skill_id, modality in targets:
            await mastery.apply_session(
                child_id=UUID(child.child_id),
                session_id=UUID(session_id),
                wait_time_ms=child.wait_time_ms,
                now=ended,
                only=(skill_id, modality),
            )

    return attempts, stars


async def _grant_achievements(session: AsyncSession, child: DemoChild) -> list[str]:
    """Whatever the histories have actually earned. The same rule the loop uses.

    Computed rather than listed: a demo child with an achievement the rule would
    not have given them is a demo of the seed file, not of the product.
    """
    tutor = TutorRepository(session)
    facts = await tutor.achievement_context(UUID(child.child_id))
    context = rewards_domain.AchievementContext(
        completed_sessions=int(facts.completed_sessions),
        distinct_session_days=int(facts.distinct_days),
        # The best streak inside any ONE session, which is what the achievement
        # is about. Computed from the scripted runs rather than re-queried: a
        # run is one skill on one day, and the pattern IS the sequence.
        best_streak_this_session=max((_longest_run(run.pattern) for run in child.runs), default=0),
        accepted_speech_attempts=int(facts.accepted_speech),
        passed_tracings=int(facts.passed_tracings),
        skills_mastered=int(facts.skills_mastered),
    )
    granted: list[str] = []
    for achievement in rewards_domain.achievements_earned(context):
        if await tutor.grant_achievement(
            child_id=UUID(child.child_id), code=str(achievement), session_id=None
        ):
            granted.append(str(achievement))
    return granted


def _longest_run(pattern: str) -> int:
    best = running = 0
    for mark in pattern:
        running = running + 1 if mark == "+" else 0
        best = max(best, running)
    return best


async def load(session: AsyncSession, *, today: dt.datetime | None = None) -> dict[str, Any]:
    """Load the whole demo family. Returns a summary for the CLI to print."""
    moment = today or dt.datetime.now(dt.UTC)
    await session.execute(
        UPSERT_CAREGIVER,
        {
            "id": DEMO_CAREGIVER_ID,
            "phone": DEMO_CAREGIVER_PHONE,
            "name": DEMO_CAREGIVER_NAME,
        },
    )

    summary: dict[str, Any] = {"caregiver": DEMO_CAREGIVER_PHONE, "children": []}
    for child in DEMO_CHILDREN:
        await session.execute(
            UPSERT_CHILD,
            {
                "id": child.child_id,
                "name": child.display_name,
                # A real `date`, not the ISO string: asyncpg binds a DATE
                # parameter by calling `toordinal()` on it and does not parse
                # strings, so `CAST(:dob AS date)` never gets the chance to run.
                "dob": dt.date.fromisoformat(child.date_of_birth),
                "max_choices": child.max_choices,
                "wait_time_ms": child.wait_time_ms,
                "calm_mode": child.calm_mode,
            },
        )
        await session.execute(LINK, {"caregiver_id": DEMO_CAREGIVER_ID, "child_id": child.child_id})
        await session.execute(
            GRANT_CONSENTS,
            {"child_id": child.child_id, "caregiver_id": DEMO_CAREGIVER_ID},
        )
        seeded = await _seed_starting_assessment(session, child, DEMO_CAREGIVER_ID)
        attempts, stars = await _seed_history(session, child, DEMO_CAREGIVER_ID, moment)
        achievements = await _grant_achievements(session, child)
        summary["children"].append(
            {
                "id": child.child_id,
                "name": child.display_name,
                "skills_seeded": seeded,
                "attempts": attempts,
                "stars": stars,
                "achievements": achievements,
            }
        )
    return summary


__all__ = ["load"]
