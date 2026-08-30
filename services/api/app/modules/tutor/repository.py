"""All SQL for the tutor runtime.

Three properties are deliberate here and each costs something.

**The answer key never leaves this file except into the evaluator.**
`SELECT_ACTIVITY` returns it; the serialiser in `schemas.py` has no field for
it. That is what makes "the frontend does not decide correctness" a fact about
the wire format rather than a convention.

**Rewards are inserted, never incremented.** `INSERT_REWARD` is
`ON CONFLICT (idempotency_key) DO NOTHING`, and the total is a `SUM` over the
table. A counter column would double on a replayed request even with the
attempt correctly deduplicated — which is exactly the bug `attempts` already
avoids the same way.

**The pending activity is a unique index, not a query.**
`tutor_activities_one_pending` means "give me the next activity" twice returns
the same activity rather than creating a second one, and it is the database
that guarantees it rather than a check-then-insert that two requests can
interleave through.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

# --- learner state ---------------------------------------------------------

SELECT_SNAPSHOTS = text("""
    SELECT s.id                        AS skill_id,
           s.code                      AS code,
           s.category::text            AS category,
           s.label_ar,
           s.label_egy,
           s.alt_text_ar,
           s.intro_order,
           s.difficulty_tier,
           s.prerequisites,
           COALESCE(st.state::text, 'not_started') AS state,
           COALESCE(st.p_known, 0.15)              AS p_known,
           st.due_at,
           st.modality::text           AS modality,
           st.total_attempts,
           st.total_correct
    FROM skills s
    LEFT JOIN skill_states st
           ON st.skill_id = s.id AND st.child_id = :child_id
    WHERE s.is_active
    ORDER BY s.intro_order
""")

SELECT_SKILLS_BY_CODE = text("""
    SELECT id, code, category::text AS category, label_ar, label_egy,
           alt_text_ar, intro_order
    FROM skills
    WHERE code IN :codes
""").bindparams(bindparam("codes", expanding=True))

SELECT_CATEGORY_POOL = text("""
    SELECT id, code, category::text AS category, label_ar, label_egy,
           alt_text_ar, intro_order
    FROM skills
    WHERE is_active AND category = CAST(:category AS skill_category) AND code <> :code
    ORDER BY abs(intro_order - :around), intro_order
    LIMIT :limit
""")

SELECT_OTHER_CATEGORY_POOL = text("""
    SELECT id, code, category::text AS category, label_ar, label_egy,
           alt_text_ar, intro_order
    FROM skills
    WHERE is_active AND category <> CAST(:category AS skill_category)
    ORDER BY intro_order
    LIMIT :limit
""")

#: The evidence bundle: this child's recent attempts on one skill, newest last.
SELECT_RECENT_ATTEMPTS = text("""
    SELECT a.result::text       AS result,
           a.prompt_level::text AS prompt_level,
           a.modality::text     AS modality,
           a.latency_ms,
           a.choice_count,
           a.client_ts,
           s.code               AS skill_code
    FROM attempts a
    JOIN skills s ON s.id = a.skill_id
    WHERE a.child_id = :child_id
    ORDER BY a.client_ts DESC, a.id DESC
    LIMIT :limit
""")

SELECT_MODALITY_ACCURACY = text("""
    SELECT a.modality::text AS modality,
           count(*)                                    AS total,
           count(*) FILTER (
               WHERE a.result IN ('correct', 'accepted_on_effort', 'caregiver_confirmed')
           )                                           AS correct
    FROM attempts a
    WHERE a.child_id = :child_id
    GROUP BY a.modality
""")

#: Accuracy per activity type, which is what "which modality works for this
#: child" actually means here. `attempts.modality` is the enum
#: (receptive/expressive/productive) and does NOT distinguish looking at a
#: picture from listening to a word — both are `receptive` — so grouping by it
#: cannot answer the question the brain asks. `activity_code` is
#: `<type>:<skill code>`, so the type is the part before the colon.
SELECT_TYPE_ACCURACY = text("""
    SELECT split_part(a.activity_code, ':', 1) AS activity_type,
           count(*)                                    AS total,
           count(*) FILTER (
               WHERE a.result IN ('correct', 'accepted_on_effort', 'caregiver_confirmed')
           )                                           AS correct
    FROM attempts a
    WHERE a.child_id = :child_id
    GROUP BY 1
""")

SELECT_SUPPORT_EFFECTIVENESS = text("""
    SELECT a.prompt_level::text AS prompt_level,
           count(*)                                    AS total,
           count(*) FILTER (
               WHERE a.result IN ('correct', 'accepted_on_effort', 'caregiver_confirmed')
           )                                           AS correct
    FROM attempts a
    WHERE a.child_id = :child_id
    GROUP BY a.prompt_level
""")

# --- sessions and activities ----------------------------------------------

INSERT_SESSION = text("""
    INSERT INTO play_sessions (child_id, started_by, plan, plan_source)
    VALUES (:child_id, :started_by, '[]'::jsonb, :plan_source)
    RETURNING id, child_id, started_at
""")

SELECT_SESSION = text("""
    SELECT id, child_id, started_by, started_at, ended_at, ended_reason,
           activities_done, correct_count, plan_source
    FROM play_sessions
    WHERE id = :session_id
""")

SELECT_PENDING_ACTIVITY = text("""
    SELECT id, session_id, child_id, decision_id, ordinal, activity_type,
           skill_id, skill_code, difficulty, modality::text AS modality, strategy,
           support_level, prompt_level::text AS prompt_level, choice_count,
           presentation, answer_key, state
    FROM tutor_activities
    WHERE session_id = :session_id AND state = 'pending'
""")

SELECT_ACTIVITY = text("""
    SELECT id, session_id, child_id, decision_id, ordinal, activity_type,
           skill_id, skill_code, difficulty, modality::text AS modality, strategy,
           support_level, prompt_level::text AS prompt_level, choice_count,
           presentation, answer_key, state
    FROM tutor_activities
    WHERE id = :activity_id
""")

INSERT_ACTIVITY = text("""
    INSERT INTO tutor_activities (
        session_id, child_id, decision_id, ordinal, activity_type, skill_id,
        skill_code, difficulty, modality, strategy, support_level, prompt_level,
        choice_count, presentation, answer_key
    ) VALUES (
        :session_id, :child_id, :decision_id, :ordinal, :activity_type, :skill_id,
        :skill_code, :difficulty, CAST(:modality AS modality), :strategy,
        :support_level, CAST(:prompt_level AS prompt_level), :choice_count,
        CAST(:presentation AS jsonb), CAST(:answer_key AS jsonb)
    )
    RETURNING id, ordinal
""")

MARK_ACTIVITY_ANSWERED = text("""
    UPDATE tutor_activities
    SET state = 'answered', answered_at = :now
    WHERE id = :activity_id AND state = 'pending'
    RETURNING id
""")

COUNT_ACTIVITIES = text("""
    SELECT count(*) AS n FROM tutor_activities WHERE session_id = :session_id
""")

#: The teaching strategies this child has most recently been given, across
#: sessions. The brain reads them so it can stop repeating an approach that is
#: not working, and `guard_decision` bounds the streak whatever it decides.
SELECT_RECENT_STRATEGIES = text("""
    SELECT strategy, activity_type, created_at
    FROM tutor_activities
    WHERE child_id = :child_id
    ORDER BY created_at DESC
    LIMIT :limit
""")

#: How many skills this child had already started before a moment, and how many
#: they have started since it. Used to bound how many NEW skills one session may
#: introduce: `first_seen_at` is written by the mastery fold from the first
#: attempt's timestamp, so "since the session started" is exactly "introduced in
#: this session".
COUNT_SKILLS_STARTED = text("""
    SELECT
      count(*) FILTER (WHERE first_seen_at <  :since) AS before_session,
      count(*) FILTER (WHERE first_seen_at >= :since) AS during_session
    FROM skill_states
    WHERE child_id = :child_id AND first_seen_at IS NOT NULL
""")

SELECT_SESSION_ACTIVITIES = text("""
    SELECT ta.ordinal, ta.activity_type, ta.skill_code, ta.difficulty,
           ta.strategy, ta.support_level, ta.state,
           s.label_ar AS skill_label_ar
    FROM tutor_activities ta
    JOIN skills s ON s.id = ta.skill_id
    WHERE ta.session_id = :session_id
    ORDER BY ta.ordinal
""")

# --- attempts and outcomes -------------------------------------------------

INSERT_ATTEMPT = text("""
    INSERT INTO attempts (
        session_id, child_id, activity_code, skill_id, modality, result,
        prompt_level, latency_ms, choice_count, selected_skill_id,
        client_ts, idempotency_key
    ) VALUES (
        :session_id, :child_id, :activity_code, :skill_id,
        CAST(:modality AS modality), CAST(:result AS attempt_result),
        CAST(:prompt_level AS prompt_level), :latency_ms, :choice_count,
        :selected_skill_id, :client_ts, :idempotency_key
    )
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id
""")

INSERT_OUTCOME = text("""
    INSERT INTO activity_outcomes (
        child_id, session_id, activity_id, skill_id, difficulty, modality,
        teaching_strategy, character, expected_answer, learner_response,
        correctness, similarity, response_time_ms, prompt_level, completed,
        mastery_before, mastery_after, ai_decision_id, metrics, threshold,
        activity_row_id
    ) VALUES (
        :child_id, :session_id, :activity_code, :skill_id, :difficulty, :modality,
        :strategy, :character, :expected_answer, :learner_response,
        :correctness, :similarity, :response_time_ms,
        CAST(:prompt_level AS prompt_level), true,
        :mastery_before, :mastery_after, :decision_id,
        CAST(:metrics AS jsonb), :threshold, :activity_row_id
    )
""")

SELECT_SESSION_ATTEMPTS = text("""
    SELECT s.code            AS skill_code,
           s.label_ar        AS skill_label_ar,
           a.result::text    AS result,
           a.prompt_level::text AS prompt_level,
           a.latency_ms,
           a.client_ts,
           a.activity_code
    FROM attempts a
    JOIN skills s ON s.id = a.skill_id
    WHERE a.session_id = :session_id
    ORDER BY a.client_ts, a.id
""")

SELECT_MASTERY_CHANGES = text("""
    SELECT s.code AS skill_code, s.label_ar AS skill_label_ar,
           me.from_state::text AS from_state, me.to_state::text AS to_state
    FROM mastery_events me
    JOIN skills s ON s.id = me.skill_id
    WHERE me.session_id = :session_id
    -- `created_at, id`: several transitions can share a timestamp inside one
    -- transaction, and an unstable sort would let the caregiver report list a
    -- child's journey in an order the query planner chose. `id` is uuid v7,
    -- so it breaks the tie in the order the rows were written.
    ORDER BY me.created_at, me.id
""")

# --- rewards ---------------------------------------------------------------

INSERT_REWARD = text("""
    INSERT INTO reward_events (
        child_id, session_id, activity_id, kind, stars, reason, idempotency_key
    ) VALUES (
        :child_id, :session_id, :activity_id, :kind, :stars, :reason, :idempotency_key
    )
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id
""")

SELECT_TOTAL_STARS = text("""
    SELECT COALESCE(sum(stars), 0) AS stars FROM reward_events WHERE child_id = :child_id
""")

SELECT_SESSION_STARS = text("""
    SELECT COALESCE(sum(stars), 0) AS stars FROM reward_events WHERE session_id = :session_id
""")

INSERT_ACHIEVEMENT = text("""
    INSERT INTO achievements (child_id, code, session_id)
    VALUES (:child_id, :code, :session_id)
    ON CONFLICT (child_id, code) DO NOTHING
    RETURNING id
""")

SELECT_ACHIEVEMENTS = text("""
    SELECT code, awarded_at FROM achievements
    WHERE child_id = :child_id ORDER BY awarded_at
""")

SELECT_ACHIEVEMENT_CONTEXT = text("""
    SELECT
      (SELECT count(*) FROM play_sessions
        WHERE child_id = :child_id AND ended_at IS NOT NULL)          AS completed_sessions,
      (SELECT count(DISTINCT date_trunc('day', started_at)) FROM play_sessions
        WHERE child_id = :child_id AND ended_at IS NOT NULL)          AS distinct_days,
      (SELECT count(*) FROM activity_outcomes ao
        JOIN tutor_activities ta ON ta.id = ao.activity_row_id
        WHERE ao.child_id = :child_id AND ta.activity_type = 'speak_word'
          AND ao.correctness)                                          AS accepted_speech,
      (SELECT count(*) FROM activity_outcomes ao
        JOIN tutor_activities ta ON ta.id = ao.activity_row_id
        WHERE ao.child_id = :child_id AND ta.activity_type = 'trace_letter'
          AND ao.correctness)                                          AS passed_tracings,
      (SELECT count(*) FROM skill_states
        WHERE child_id = :child_id AND state IN ('mastered', 'retained')) AS skills_mastered
""")

# --- summaries and inspector ----------------------------------------------

UPSERT_SUMMARY = text("""
    INSERT INTO session_summaries (session_id, child_id, facts, narrative_ar, narrative_source)
    VALUES (:session_id, :child_id, CAST(:facts AS jsonb), :narrative_ar, :narrative_source)
    ON CONFLICT (session_id) DO UPDATE SET
        facts            = EXCLUDED.facts,
        narrative_ar     = EXCLUDED.narrative_ar,
        narrative_source = EXCLUDED.narrative_source
""")

SELECT_SUMMARY = text("""
    SELECT session_id, child_id, facts, narrative_ar, narrative_source, created_at
    FROM session_summaries WHERE session_id = :session_id
""")

#: A child's finished sessions, newest first, with the facts each produced.
#: LEFT JOIN rather than INNER: a session that ended before the summary was
#: written still happened, and hiding it would make a caregiver's history
#: quietly shorter than their child's.
SELECT_CHILD_SESSIONS = text("""
    SELECT ps.id, ps.started_at, ps.ended_at, ps.activities_done, ps.correct_count,
           ss.facts, ss.narrative_ar, ss.narrative_source,
           COALESCE(
               (SELECT sum(stars) FROM reward_events re WHERE re.session_id = ps.id), 0
           ) AS stars
    FROM play_sessions ps
    LEFT JOIN session_summaries ss ON ss.session_id = ps.id
    WHERE ps.child_id = :child_id
    ORDER BY ps.started_at DESC
    LIMIT :limit
""")

SELECT_DECISIONS = text("""
    SELECT id, session_id, state_snapshot, proposed_decision, final_decision,
           reason_codes, guardrail_actions, model_name, resulting_activity_id,
           created_at
    FROM ai_decisions
    WHERE session_id = :session_id
    ORDER BY created_at
""")

SELECT_LATEST_DECISION = text("""
    SELECT id, session_id, state_snapshot, proposed_decision, final_decision,
           reason_codes, guardrail_actions, model_name, resulting_activity_id,
           created_at
    FROM ai_decisions
    WHERE child_id = :child_id
    ORDER BY created_at DESC
    LIMIT 1
""")

SELECT_SKILL_STATE = text("""
    SELECT state::text AS state, p_known, total_attempts, total_correct
    FROM skill_states
    WHERE child_id = :child_id AND skill_id = :skill_id
      AND modality = CAST(:modality AS modality)
""")

# --- learner profile -------------------------------------------------------

SELECT_PROFILE = text("""
    SELECT child_id, source, effective_support, effective_modality,
           demonstration_helps, follows_spoken, comfortable_speaking,
           comfortable_minutes, area_levels
    FROM learner_profiles WHERE child_id = :child_id
""")

UPSERT_PROFILE = text("""
    INSERT INTO learner_profiles (
        child_id, source, starting_assessment_id, effective_support,
        effective_modality, demonstration_helps, follows_spoken,
        comfortable_speaking, comfortable_minutes, area_levels, updated_at
    ) VALUES (
        :child_id, :source, :starting_assessment_id, :effective_support,
        :effective_modality, :demonstration_helps, :follows_spoken,
        :comfortable_speaking, :comfortable_minutes, CAST(:area_levels AS jsonb), now()
    )
    ON CONFLICT (child_id) DO UPDATE SET
        source                 = EXCLUDED.source,
        starting_assessment_id = COALESCE(EXCLUDED.starting_assessment_id,
                                          learner_profiles.starting_assessment_id),
        effective_support      = EXCLUDED.effective_support,
        effective_modality     = EXCLUDED.effective_modality,
        demonstration_helps    = EXCLUDED.demonstration_helps,
        follows_spoken         = EXCLUDED.follows_spoken,
        comfortable_speaking   = EXCLUDED.comfortable_speaking,
        comfortable_minutes    = EXCLUDED.comfortable_minutes,
        area_levels            = EXCLUDED.area_levels,
        updated_at             = now()
""")

#: The latest decision per consent key. `DISTINCT ON` rather than a MAX
#: subquery, and ordered the same way `children/consent_gate.py` orders it, so
#: the tutor's view of a family's consents cannot differ from the gate's.
SELECT_CONSENT = text("""
    SELECT DISTINCT ON (consent_key) consent_key, status::text AS status
    FROM consents
    WHERE child_id = :child_id
    ORDER BY consent_key, granted_at DESC, id DESC
""")


class TutorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- learner state -----------------------------------------------------

    async def snapshots(self, child_id: UUID) -> list[Any]:
        return list(await self._session.execute(SELECT_SNAPSHOTS, {"child_id": child_id}))

    async def skills_by_code(self, codes: list[str]) -> list[Any]:
        if not codes:
            return []
        return list(await self._session.execute(SELECT_SKILLS_BY_CODE, {"codes": codes}))

    async def category_pool(self, *, category: str, code: str, around: int, limit: int):  # type: ignore[no-untyped-def]
        return list(
            await self._session.execute(
                SELECT_CATEGORY_POOL,
                {"category": category, "code": code, "around": around, "limit": limit},
            )
        )

    async def other_category_pool(self, *, category: str, limit: int) -> list[Any]:
        return list(
            await self._session.execute(
                SELECT_OTHER_CATEGORY_POOL, {"category": category, "limit": limit}
            )
        )

    async def recent_attempts(self, *, child_id: UUID, limit: int = 40) -> list[Any]:
        return list(
            await self._session.execute(
                SELECT_RECENT_ATTEMPTS, {"child_id": child_id, "limit": limit}
            )
        )

    async def modality_accuracy(self, child_id: UUID) -> dict[str, float]:
        rows = await self._session.execute(SELECT_MODALITY_ACCURACY, {"child_id": child_id})
        return {str(row.modality): (row.correct / row.total) for row in rows if row.total}

    async def type_accuracy(self, child_id: UUID) -> dict[str, float]:
        rows = await self._session.execute(SELECT_TYPE_ACCURACY, {"child_id": child_id})
        return {str(row.activity_type): (row.correct / row.total) for row in rows if row.total}

    async def support_effectiveness(self, child_id: UUID) -> dict[str, float]:
        rows = await self._session.execute(SELECT_SUPPORT_EFFECTIVENESS, {"child_id": child_id})
        return {str(row.prompt_level): (row.correct / row.total) for row in rows if row.total}

    async def skill_state(self, *, child_id: UUID, skill_id: UUID, modality: str) -> Any | None:
        return (
            await self._session.execute(
                SELECT_SKILL_STATE,
                {"child_id": child_id, "skill_id": skill_id, "modality": modality},
            )
        ).one_or_none()

    async def consents(self, child_id: UUID) -> dict[str, str]:
        rows = await self._session.execute(SELECT_CONSENT, {"child_id": child_id})
        return {str(row.consent_key): str(row.status) for row in rows}

    # --- sessions ----------------------------------------------------------

    async def create_session(self, *, child_id: UUID, started_by: UUID, plan_source: str) -> Any:
        return (
            await self._session.execute(
                INSERT_SESSION,
                {"child_id": child_id, "started_by": started_by, "plan_source": plan_source},
            )
        ).one()

    async def get_session(self, session_id: UUID) -> Any | None:
        return (
            await self._session.execute(SELECT_SESSION, {"session_id": session_id})
        ).one_or_none()

    async def end_session(self, *, session_id: UUID, reason: str, now: dt.datetime) -> Any | None:
        from app.modules.play.repository import END_SESSION

        return (
            await self._session.execute(
                END_SESSION, {"session_id": session_id, "reason": reason, "now": now}
            )
        ).one_or_none()

    async def record_session_end_event(self, values: dict[str, Any]) -> None:
        from app.modules.play.repository import INSERT_SESSION_END_EVENT

        payload = dict(values)
        payload["props"] = json.dumps(payload["props"], ensure_ascii=False)
        await self._session.execute(INSERT_SESSION_END_EVENT, payload)

    # --- activities --------------------------------------------------------

    async def pending_activity(self, session_id: UUID) -> Any | None:
        return (
            await self._session.execute(SELECT_PENDING_ACTIVITY, {"session_id": session_id})
        ).one_or_none()

    async def activity(self, activity_id: UUID) -> Any | None:
        return (
            await self._session.execute(SELECT_ACTIVITY, {"activity_id": activity_id})
        ).one_or_none()

    async def insert_activity(self, values: dict[str, Any]) -> Any:
        payload = dict(values)
        payload["presentation"] = json.dumps(payload["presentation"], ensure_ascii=False)
        payload["answer_key"] = json.dumps(payload["answer_key"], ensure_ascii=False)
        return (await self._session.execute(INSERT_ACTIVITY, payload)).one()

    async def mark_answered(self, *, activity_id: UUID, now: dt.datetime) -> bool:
        row = (
            await self._session.execute(
                MARK_ACTIVITY_ANSWERED, {"activity_id": activity_id, "now": now}
            )
        ).one_or_none()
        return row is not None

    async def activity_count(self, session_id: UUID) -> int:
        row = (await self._session.execute(COUNT_ACTIVITIES, {"session_id": session_id})).one()
        return int(row.n)

    async def skills_started(self, *, child_id: UUID, since: dt.datetime) -> tuple[int, int]:
        row = (
            await self._session.execute(
                COUNT_SKILLS_STARTED, {"child_id": child_id, "since": since}
            )
        ).one()
        return int(row.before_session), int(row.during_session)

    async def recent_strategies(self, child_id: UUID, limit: int = 6) -> list[Any]:
        rows = list(
            await self._session.execute(
                SELECT_RECENT_STRATEGIES, {"child_id": child_id, "limit": limit}
            )
        )
        # Oldest first: `recent_strategies[-3:]` in the brain means "the last
        # three", and a newest-first list would make it mean the opposite.
        return list(reversed(rows))

    async def session_activities(self, session_id: UUID) -> list[Any]:
        return list(
            await self._session.execute(SELECT_SESSION_ACTIVITIES, {"session_id": session_id})
        )

    # --- attempts ----------------------------------------------------------

    async def record_attempt(self, values: dict[str, Any]) -> bool:
        row = (await self._session.execute(INSERT_ATTEMPT, values)).one_or_none()
        return row is not None

    async def record_outcome(self, values: dict[str, Any]) -> None:
        payload = dict(values)
        payload["metrics"] = json.dumps(payload.get("metrics") or {}, ensure_ascii=False)
        await self._session.execute(INSERT_OUTCOME, payload)

    async def session_attempts(self, session_id: UUID) -> list[Any]:
        return list(
            await self._session.execute(SELECT_SESSION_ATTEMPTS, {"session_id": session_id})
        )

    async def mastery_changes(self, session_id: UUID) -> list[Any]:
        return list(await self._session.execute(SELECT_MASTERY_CHANGES, {"session_id": session_id}))

    # --- rewards -----------------------------------------------------------

    async def grant_reward(self, values: dict[str, Any]) -> bool:
        """True when this call is the one that wrote the row.

        False means the key was already there — a retry, a double tap, or an
        outbox draining twice. The caller reports the same totals either way;
        what it must not do is report a second award.
        """
        row = (await self._session.execute(INSERT_REWARD, values)).one_or_none()
        return row is not None

    async def total_stars(self, child_id: UUID) -> int:
        row = (await self._session.execute(SELECT_TOTAL_STARS, {"child_id": child_id})).one()
        return int(row.stars)

    async def session_stars(self, session_id: UUID) -> int:
        row = (await self._session.execute(SELECT_SESSION_STARS, {"session_id": session_id})).one()
        return int(row.stars)

    async def grant_achievement(
        self, *, child_id: UUID, code: str, session_id: UUID | None
    ) -> bool:
        row = (
            await self._session.execute(
                INSERT_ACHIEVEMENT,
                {"child_id": child_id, "code": code, "session_id": session_id},
            )
        ).one_or_none()
        return row is not None

    async def achievements(self, child_id: UUID) -> list[Any]:
        return list(await self._session.execute(SELECT_ACHIEVEMENTS, {"child_id": child_id}))

    async def achievement_context(self, child_id: UUID) -> Any:
        return (
            await self._session.execute(SELECT_ACHIEVEMENT_CONTEXT, {"child_id": child_id})
        ).one()

    # --- summaries and decisions -------------------------------------------

    async def save_summary(self, values: dict[str, Any]) -> None:
        payload = dict(values)
        payload["facts"] = json.dumps(payload["facts"], ensure_ascii=False)
        await self._session.execute(UPSERT_SUMMARY, payload)

    async def summary(self, session_id: UUID) -> Any | None:
        return (
            await self._session.execute(SELECT_SUMMARY, {"session_id": session_id})
        ).one_or_none()

    async def child_sessions(self, *, child_id: UUID, limit: int = 20) -> list[Any]:
        return list(
            await self._session.execute(
                SELECT_CHILD_SESSIONS, {"child_id": child_id, "limit": limit}
            )
        )

    async def decisions(self, session_id: UUID) -> list[Any]:
        return list(await self._session.execute(SELECT_DECISIONS, {"session_id": session_id}))

    async def latest_decision(self, child_id: UUID) -> Any | None:
        return (
            await self._session.execute(SELECT_LATEST_DECISION, {"child_id": child_id})
        ).one_or_none()

    # --- learner profile ---------------------------------------------------

    async def profile(self, child_id: UUID) -> Any | None:
        return (await self._session.execute(SELECT_PROFILE, {"child_id": child_id})).one_or_none()

    async def upsert_profile(self, values: dict[str, Any]) -> None:
        payload = dict(values)
        payload["area_levels"] = json.dumps(payload.get("area_levels") or {}, ensure_ascii=False)
        await self._session.execute(UPSERT_PROFILE, payload)


__all__ = ["TutorRepository"]
