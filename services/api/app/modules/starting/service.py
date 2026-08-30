"""Starting-assessment business rules: ask, record, derive, seed.

    Create Child -> Caregiver Assessment -> Persist -> Derive
                 -> Initial Learner State (skill_states with priors)
                 -> Learner Profile (support, modality, duration)
                 -> the tutor loop's first decision reads both

The one rule worth stating plainly: **finalising is idempotent and
non-destructive.** The skill-state seed is `ON CONFLICT DO NOTHING`, so a
caregiver who fills the form in a second time, or a retried request, cannot
overwrite a state built from what the child actually did. The learner PROFILE
does upsert, because support preferences are the caregiver's to restate.

Authorisation follows the same pattern as `assessment/service.py`: the route
path carries `{assessment_id}` rather than `{child_id}`, so
`tools/guards/route_authorisation.py` cannot see it and every method resolves
the assessment to its child and calls `assert_child_access` explicitly.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, NotFound
from app.modules.children.repository import ChildrenRepository
from app.modules.identity.domain import Role
from app.modules.identity.service import IdentityService
from app.modules.starting.domain import form
from app.modules.starting.repository import StartingRepository
from app.modules.tutor.repository import TutorRepository

logger = structlog.get_logger(__name__)

#: The modality a seeded skill state is created in. Receptive: every skill in
#: the catalogue is reachable receptively, and it is the only modality a
#: caregiver's answers say anything about.
SEED_MODALITY = "receptive"


class StartingService:
    def __init__(
        self,
        *,
        repo: StartingRepository,
        children: ChildrenRepository,
        identity: IdentityService,
        profiles: TutorRepository,
    ) -> None:
        self._repo = repo
        self._children = children
        self._identity = identity
        # `learner_profiles` belongs to the tutor -- it is the only reader --
        # so the write goes through its repository rather than a second set of
        # SQL for the same table in this module.
        self._profiles = profiles

    async def start(self, *, child_id: UUID, caregiver_id: UUID) -> dict[str, Any]:
        await self._identity.assert_child_access(
            caregiver_id=caregiver_id, child_id=child_id, min_role=Role.CO_CAREGIVER
        )
        if await self._children.get_child(child_id) is None:
            raise NotFound(detail="Child not found.")

        existing = await self._repo.open_for_child(child_id)
        if existing is not None:
            # A second open assessment is almost always a closed tab. Resuming
            # is the answer a caregiver wants and the one that does not fork
            # the answer log.
            return await self.state(assessment_id=existing, caregiver_id=caregiver_id)

        try:
            row = await self._repo.create(
                child_id=child_id, started_by=caregiver_id, form_version=form.FORM_VERSION
            )
        except IntegrityError:
            # The check above and this INSERT are two statements, and two
            # requests can interleave between them. React's development strict
            # mode does exactly that — it runs the mount effect twice — and both
            # requests found no open assessment and both tried to create one.
            #
            # `starting_assessments_one_open` is what makes that safe, and this
            # is what makes it invisible: the loser of the race resumes the
            # assessment the winner created, which is the same answer it would
            # have got half a millisecond earlier. Without it a caregiver opening
            # the form saw a 500 roughly half the time.
            await self._repo.rollback_to_savepoint()
            resumed = await self._repo.open_for_child(child_id)
            if resumed is None:
                raise
            return await self.state(assessment_id=resumed, caregiver_id=caregiver_id)

        logger.info("starting_assessment_started", child_id=str(child_id))
        return self._state_of(row, answers={})

    async def state(self, *, assessment_id: UUID, caregiver_id: UUID) -> dict[str, Any]:
        row = await self._require(assessment_id, caregiver_id)
        return self._state_of(row, answers=dict(row.answers or {}))

    async def answer(
        self,
        *,
        assessment_id: UUID,
        caregiver_id: UUID,
        question_id: str,
        answer_id: str,
    ) -> dict[str, Any]:
        row = await self._require(assessment_id, caregiver_id)
        if str(row.status) == "completed":
            raise Conflict(detail="This assessment is already finished.")

        question = form.QUESTION_BY_ID.get(question_id)
        if question is None:
            raise NotFound(detail="No such question in this form.")
        allowed = (
            {str(band) for band in form.BAND_ORDER}
            if question.uses_bands
            else set(question.options)
        )
        if answer_id not in allowed:
            raise Conflict(detail="That answer is not one of this question's options.")

        answers = await self._repo.record_answer(
            assessment_id=assessment_id, question_id=question_id, answer_id=answer_id
        )
        if answers is None:
            raise Conflict(detail="This assessment is already finished.")
        return self._state_of(row, answers=answers)

    async def finalise(self, *, assessment_id: UUID, caregiver_id: UUID) -> dict[str, Any]:
        """Derive the profile, create the learner state, close the assessment."""
        row = await self._require(assessment_id, caregiver_id)
        answers = {str(k): str(v) for k, v in dict(row.answers or {}).items()}
        profile = form.derive(answers)
        now = _now()

        written = await self._repo.finalise(
            assessment_id=assessment_id,
            area_levels=profile.area_bands,
            supports=profile.as_json(),
            now=now,
        )
        if not written:
            # Already completed. Return what is on file rather than re-deriving:
            # a completed assessment is a fixed historical fact.
            fresh = await self._repo.get(assessment_id)
            if fresh is not None and fresh.completed_at is not None:
                return {
                    "assessment_id": assessment_id,
                    "child_id": fresh.child_id,
                    "status": "completed",
                    "completed_at": fresh.completed_at,
                    "area_levels": dict(fresh.area_levels or {}),
                    "supports": dict(fresh.supports or {}),
                    "skills_seeded": 0,
                    "unmapped_areas": list(dict(fresh.supports or {}).get("unmapped_areas", [])),
                }

        seeded = await self._seed_learner_state(child_id=row.child_id, profile=profile, now=now)
        await self._write_profile(
            child_id=row.child_id, assessment_id=assessment_id, profile=profile
        )
        logger.info(
            "starting_assessment_completed",
            child_id=str(row.child_id),
            seeded=seeded,
            support=profile.effective_support,
        )
        return {
            "assessment_id": assessment_id,
            "child_id": row.child_id,
            "status": "completed",
            "completed_at": now,
            "area_levels": profile.area_bands,
            "supports": profile.as_json(),
            "skills_seeded": seeded,
            "unmapped_areas": list(profile.unmapped_areas),
        }

    async def latest(self, *, child_id: UUID, caregiver_id: UUID) -> dict[str, Any] | None:
        await self._identity.assert_child_access(
            caregiver_id=caregiver_id, child_id=child_id, min_role=Role.CO_CAREGIVER
        )
        row = await self._repo.latest_for_child(child_id)
        if row is None:
            return None
        return {
            "assessment_id": row.id,
            "child_id": row.child_id,
            "status": str(row.status),
            "completed_at": row.completed_at,
            "area_levels": dict(row.area_levels or {}),
            "supports": dict(row.supports or {}),
        }

    # --- internals ---------------------------------------------------------

    async def _seed_learner_state(
        self, *, child_id: UUID, profile: form.StartingProfile, now: dt.datetime
    ) -> int:
        """Create the skill states the tutor loop will start from.

        `due_at = now`, so every seeded skill is immediately a review candidate.
        Without it the candidate generator would see a set of `practising`
        skills with no review date and offer none of them, and the assessment
        would have changed nothing the child experiences.
        """
        wanted: dict[str, tuple[int, float, str]] = {}
        for seed in profile.seeds:
            # The strongest claim for a category wins its head: two areas can
            # map to one category (`simple_words` covers household AND body
            # parts) and taking the max means a caregiver's better answer is not
            # thrown away by their worse one.
            current = wanted.get(seed.category)
            if current is None or seed.rank + 1 > current[0]:
                wanted[seed.category] = (seed.rank + 1, seed.prior, seed.state)
            elif seed.prior > current[1]:
                wanted[seed.category] = (current[0], seed.prior, seed.state)

        seeded = 0
        for category, (count, prior, state) in sorted(wanted.items()):
            for row in await self._repo.category_head(category=category, limit=count):
                await self._repo.seed_state(
                    {
                        "child_id": child_id,
                        "skill_id": row.id,
                        "modality": SEED_MODALITY,
                        "state": state,
                        "p_known": prior,
                        "p_prior": prior,
                        "due_at": now,
                        "now": now,
                    }
                )
                seeded += 1
        return seeded

    async def _write_profile(
        self, *, child_id: UUID, assessment_id: UUID, profile: form.StartingProfile
    ) -> None:
        await self._profiles.upsert_profile(
            {
                "child_id": child_id,
                "source": "starting_assessment",
                "starting_assessment_id": assessment_id,
                "effective_support": profile.effective_support,
                "effective_modality": profile.effective_modality,
                "demonstration_helps": profile.demonstration_helps,
                "follows_spoken": profile.follows_spoken,
                "comfortable_speaking": profile.comfortable_speaking,
                "comfortable_minutes": profile.comfortable_minutes,
                "area_levels": profile.area_bands,
            }
        )

    async def _require(self, assessment_id: UUID, caregiver_id: UUID) -> Any:
        row = await self._repo.get(assessment_id)
        if row is None:
            raise NotFound(detail="Assessment not found.")
        # The check the route path cannot express. Same failure semantics as
        # require_child_access: no distinction between "not yours" and "does not
        # exist", so ids cannot be enumerated.
        await self._identity.assert_child_access(
            caregiver_id=caregiver_id, child_id=row.child_id, min_role=Role.CO_CAREGIVER
        )
        return row

    def _state_of(self, row: Any, *, answers: dict[str, str]) -> dict[str, Any]:
        pending = form.remaining(answers)
        return {
            "assessment_id": row.id,
            "child_id": row.child_id,
            "status": str(row.status),
            "form_version": str(row.form_version),
            "answered": len(answers),
            "total": len(form.QUESTIONS),
            "complete": form.is_complete(answers),
            "answers": answers,
            "next_questions": [
                item
                for item in form.question_payload()
                if item["id"] in {question.id for question in pending}
            ],
            "watermark": form.WATERMARK,
        }


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


__all__ = ["SEED_MODALITY", "StartingService"]
