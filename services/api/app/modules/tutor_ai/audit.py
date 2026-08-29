"""Persistence boundary for tutor audit records.

The repository stores structured decisions and short reason codes only. Callers
must not pass chain-of-thought or raw child identity into these methods.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


INSERT_AI_DECISION = text("""
    INSERT INTO ai_decisions (
        child_id, session_id, state_snapshot, proposed_decision, final_decision,
        reason_codes, guardrail_actions, model_name, outcome_summary,
        resulting_activity_id
    ) VALUES (
        :child_id, :session_id, CAST(:state_snapshot AS jsonb),
        CAST(:proposed_decision AS jsonb), CAST(:final_decision AS jsonb),
        CAST(:reason_codes AS jsonb), CAST(:guardrail_actions AS jsonb),
        :model_name, :outcome_summary, :resulting_activity_id
    ) RETURNING id
""")


class TutorAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_decision(
        self,
        *,
        child_id: UUID,
        session_id: UUID | None,
        state_snapshot: dict[str, Any],
        proposed_decision: dict[str, Any],
        final_decision: dict[str, Any],
        reason_codes: list[str],
        guardrail_actions: list[str],
        model_name: str,
        outcome_summary: str | None = None,
        resulting_activity_id: str | None = None,
    ) -> UUID:
        row = (
            await self._session.execute(
                INSERT_AI_DECISION,
                {
                    "child_id": child_id,
                    "session_id": session_id,
                    "state_snapshot": json.dumps(state_snapshot, ensure_ascii=False),
                    "proposed_decision": json.dumps(proposed_decision, ensure_ascii=False),
                    "final_decision": json.dumps(final_decision, ensure_ascii=False),
                    "reason_codes": json.dumps(reason_codes, ensure_ascii=False),
                    "guardrail_actions": json.dumps(guardrail_actions, ensure_ascii=False),
                    "model_name": model_name,
                    "outcome_summary": outcome_summary,
                    "resulting_activity_id": resulting_activity_id,
                },
            )
        ).one()
        return row.id


__all__ = ["TutorAuditRepository"]
