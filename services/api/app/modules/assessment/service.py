"""Assessment business rules: the thin layer between the router and the engine.

The engine is pure and stays pure. Everything here is load, replay, persist.

**Replay on every write, not incremental state.** The service never stores an
`AssessmentState`; it rebuilds one from the answer log each time. That is what
`engine.replay()` exists for, it is well under 5 ms for a 600-item bank, and it
removes the entire class of bug where a cached basal and the answer log disagree
after a correction.

Authorisation: every method that takes an `assessment_id` resolves it to a
`child_id` and asserts access on that. The route path has no `{child_id}` in it
(docs/05 §4 puts assessments at the top level), so `require_child_access` cannot
be declared on the route and the check has to be explicit here. GUARD 1 does not
catch this one -- which is exactly why it is written out rather than assumed.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import structlog

from app.core.errors import Conflict, NotFound
from app.modules.assessment.bank_source import get_bank, item_text, watermark
from app.modules.assessment.domain import engine
from app.modules.assessment.domain.state import Answer, ItemRef, Verdict
from app.modules.assessment.repository import AssessmentRepository
from app.modules.assessment.schemas import AssessmentScored, AssessmentState, ItemOut
from app.modules.children import domain as child_domain
from app.modules.children.repository import ChildrenRepository
from app.modules.identity.domain import Role
from app.modules.identity.service import IdentityService

logger = structlog.get_logger(__name__)

#: How many items to hand the client at once. Enough that a caregiver never
#: waits on a round trip between two questions, few enough that a correction
#: does not invalidate a long queue.
CANDIDATE_BATCH = 5

#: Written on every answer the engine inferred rather than observed. The enum
#: value exists in 0001 for precisely this.
PROPAGATED_SOURCE = "evidence_propagated"


class AssessmentService:
    def __init__(
        self,
        *,
        repo: AssessmentRepository,
        children: ChildrenRepository,
        identity: IdentityService,
    ) -> None:
        self._repo = repo
        self._children = children
        self._identity = identity

    # --- lifecycle ---------------------------------------------------------

    async def start(self, *, child_id: UUID, caregiver_id: UUID) -> AssessmentState:
        await self._identity.assert_child_access(
            caregiver_id=caregiver_id, child_id=child_id, min_role=Role.CO_CAREGIVER
        )
        child = await self._children.get_child(child_id)
        if child is None:
            raise NotFound(detail="Child not found.")

        # A second open assessment is almost always a closed tab, not a second
        # administration. Resuming is the answer a caregiver wants and it is
        # also the one that does not fork the answer log.
        existing = await self._repo.open_for_child(child_id)
        if existing is not None:
            return await self.state(assessment_id=existing, caregiver_id=caregiver_id)

        age = child_domain.age_months(
            child.date_of_birth, child_domain.today(), child.gestational_weeks
        )
        bank = get_bank()
        row = await self._repo.create(
            child_id=child_id,
            started_by=caregiver_id,
            bank_version=bank.version,
            # Corrected, not chronological (docs/04a §C02). The entry bands are
            # computed from this value, and it is stored so that a replay years
            # later uses the age the assessment was actually administered at.
            child_months=round(age.corrected_months, 2),
        )
        logger.info("assessment_started", assessment_id=str(row.id), child_id=str(child_id))
        return self._state_of(row, answers=[])

    async def state(self, *, assessment_id: UUID, caregiver_id: UUID) -> AssessmentState:
        row = await self._require(assessment_id, caregiver_id)
        return self._state_of(row, answers=await self._repo.answers(assessment_id))

    async def answer(
        self,
        *,
        assessment_id: UUID,
        caregiver_id: UUID,
        item_id: str,
        verdict: str,
        source: str,
        idempotency_key: str | None,
    ) -> AssessmentState:
        row = await self._require(assessment_id, caregiver_id)
        if str(row.status) == "completed":
            raise Conflict(detail="This assessment is already finished.")

        bank = get_bank(str(row.bank_version))
        if not bank.has(item_id):
            raise NotFound(detail="No such item in this assessment's bank.")

        # The idempotency check comes FIRST, before anything is superseded.
        # Ordered the other way it is destructive: a retry after a timeout looks
        # like a second answer for an already-answered item, so the original row
        # is superseded, and then the INSERT is skipped as a duplicate key --
        # leaving the item with no live answer at all. The retry would silently
        # erase the answer it was retrying.
        if idempotency_key and await self._repo.has_key(
            assessment_id=assessment_id, idempotency_key=idempotency_key
        ):
            return self._state_of(row, answers=await self._repo.answers(assessment_id))

        answers = await self._repo.answers(assessment_id)
        state = engine.replay(
            bank=bank,
            child_months=float(row.child_months),
            answers=[_answer(a) for a in answers],
        )

        # A second answer for an item already answered is a CORRECTION, not a
        # duplicate: the old row is superseded and the whole assessment replays
        # from the surviving sequence. That is the only way basal and ceiling
        # stay consistent with the answers actually on file.
        if any(a.item_id == item_id for a in answers):
            await self._repo.supersede(assessment_id=assessment_id, item_id=item_id, now=_now())

        parsed = Verdict(verdict)
        _, implied = engine.apply_answer(state, bank.ref(item_id), parsed, bank)

        written = await self._repo.record_answer(
            assessment_id=assessment_id,
            item_id=item_id,
            verdict=parsed.value,
            source=source,
            propagated=False,
            idempotency_key=idempotency_key,
        )
        if written:
            for ref, implied_verdict in implied:
                await self._repo.record_answer(
                    assessment_id=assessment_id,
                    item_id=ref.id,
                    verdict=implied_verdict.value,
                    source=PROPAGATED_SOURCE,
                    propagated=True,
                    # No client key: the server derived this row, and pairing it
                    # with the observed answer's key would collide on the
                    # partial unique index.
                    idempotency_key=None,
                )

        return self._state_of(row, answers=await self._repo.answers(assessment_id))

    async def finalise(self, *, assessment_id: UUID, caregiver_id: UUID) -> AssessmentScored:
        """Score and close. Idempotent: finalising twice returns the same row."""
        row = await self._require(assessment_id, caregiver_id)
        bank = get_bank(str(row.bank_version))
        answers = await self._repo.answers(assessment_id)
        state = engine.replay(
            bank=bank,
            child_months=float(row.child_months),
            answers=[_answer(a) for a in answers],
        )
        scores = engine.score(engine.mark_complete(state), bank)
        # Developmental age per domain. Never a quotient here: DQ exists on
        # DomainScore, it belongs in the report behind the opt-in norm panel,
        # and this value feeds the journey chart, which is a dashboard.
        domain_da = {
            code: round(score.developmental_age_months, 2) for code, score in scores.items()
        }
        mastered = await self._repo.count_mastered(row.child_id)
        now = _now()
        if not await self._repo.finalise(
            assessment_id=assessment_id,
            domain_da=domain_da,
            skills_mastered=mastered,
            now=now,
        ):
            # Already completed. Return what is on file rather than the numbers
            # just recomputed: a completed assessment is a fixed historical
            # fact, and a second finalise must not quietly restate it.
            fresh = await self._repo.get(assessment_id)
            if fresh is not None and fresh.completed_at is not None:
                return AssessmentScored(
                    assessment_id=assessment_id,
                    status=str(fresh.status),
                    completed_at=fresh.completed_at,
                    domain_da={k: float(v) for k, v in dict(fresh.domain_da or {}).items()},
                    skills_mastered=int(fresh.skills_mastered),
                )
        logger.info("assessment_completed", assessment_id=str(assessment_id))
        return AssessmentScored(
            assessment_id=assessment_id,
            status="completed",
            completed_at=now,
            domain_da=domain_da,
            skills_mastered=mastered,
        )

    # --- internals ---------------------------------------------------------

    async def _require(self, assessment_id: UUID, caregiver_id: UUID) -> Any:
        row = await self._repo.get(assessment_id)
        if row is None:
            raise NotFound(detail="Assessment not found.")
        # The authorisation check the route path cannot express. Same failure
        # semantics as require_child_access: no distinction between "not yours"
        # and "does not exist", so ids cannot be enumerated.
        await self._identity.assert_child_access(
            caregiver_id=caregiver_id, child_id=row.child_id, min_role=Role.CO_CAREGIVER
        )
        return row

    def _state_of(self, row: Any, *, answers: list[Any]) -> AssessmentState:
        bank = get_bank(str(row.bank_version))
        state = engine.replay(
            bank=bank,
            child_months=float(row.child_months),
            answers=[_answer(a) for a in answers],
        )
        items = engine.candidates(state, bank, limit=CANDIDATE_BATCH)
        complete = all(d.complete for d in state.domains.values())
        return AssessmentState(
            assessment_id=row.id,
            status=str(row.status),
            bank_version=str(row.bank_version),
            child_months=float(row.child_months),
            # Observed answers only. Counting propagated evidence would tell a
            # caregiver they answered questions they never saw.
            answered=sum(1 for a in answers if not a.propagated),
            remaining_estimate=engine.remaining_estimate(state, bank),
            complete=complete or not items,
            next_items=[_item_out(ref) for ref in items],
            bank_watermark=watermark(),
        )


def _answer(row: Any) -> Answer:
    return Answer(
        item_id=str(row.item_id),
        verdict=Verdict(str(row.verdict)),
        propagated=bool(row.propagated),
    )


def _item_out(ref: ItemRef) -> ItemOut:
    text = item_text(ref.id)
    return ItemOut(
        item_id=ref.id,
        domain=ref.domain,
        band=ref.band,
        ordinal=ref.ordinal,
        prompt_ar=text.prompt_ar if text else "",
        prompt_ar_msa=text.prompt_ar_msa if text else "",
        example_ar=text.example_ar if text else "",
    )


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


__all__ = ["CANDIDATE_BATCH", "AssessmentService"]
