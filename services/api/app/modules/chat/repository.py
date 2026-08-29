"""SQL for the chat transcript.

Reads are ordered DESC with a LIMIT and reversed in Python rather than ordered
ASC with an OFFSET. The index is `(child_id, surface, created_at DESC)`, so the
DESC form is an index scan that stops after `limit` rows; the ASC form reads the
whole conversation to find its tail. On a transcript that grows for years that
is the difference between a constant-time read and a linear one.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.domain import ChatMessage, Role, Surface, TurnOutcome

logger = structlog.get_logger(__name__)

INSERT_MESSAGE = text("""
    INSERT INTO chat_messages (
        child_id, caregiver_id, surface, role, text_ar, grounded_in, outcome
    ) VALUES (
        CAST(:child_id AS uuid),
        CAST(NULLIF(:caregiver_id, '') AS uuid),
        :surface, :role, :text_ar, CAST(:grounded_in AS jsonb), :outcome
    )
    RETURNING id::text AS id, created_at
""")

SELECT_RECENT = text("""
    SELECT role, text_ar, created_at, grounded_in, outcome
    FROM chat_messages
    WHERE child_id = CAST(:child_id AS uuid) AND surface = :surface
    ORDER BY created_at DESC, id DESC
    LIMIT :limit
""")

PURGE = text("DELETE FROM chat_messages WHERE child_id = CAST(:child_id AS uuid)")


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        child_id: str,
        caregiver_id: str | None,
        surface: Surface,
        role: Role,
        text_ar: str,
        grounded_in: Sequence[str] = (),
        outcome: TurnOutcome = TurnOutcome.OK,
    ) -> str:
        row = (
            await self._session.execute(
                INSERT_MESSAGE,
                {
                    "child_id": child_id,
                    "caregiver_id": caregiver_id or "",
                    "surface": surface.value,
                    "role": role.value,
                    "text_ar": text_ar,
                    "grounded_in": json.dumps(list(grounded_in)),
                    "outcome": outcome.value,
                },
            )
        ).one()
        return str(row.id)

    async def recent(
        self, child_id: str, surface: Surface, *, limit: int = 20
    ) -> list[ChatMessage]:
        """Oldest first, which is the order a transcript is read in."""
        rows = list(
            await self._session.execute(
                SELECT_RECENT,
                {"child_id": child_id, "surface": surface.value, "limit": limit},
            )
        )
        return [_message(row) for row in reversed(rows)]

    async def purge(self, child_id: str) -> int:
        result = await self._session.execute(PURGE, {"child_id": child_id})
        return int(cast("CursorResult[Any]", result).rowcount or 0)


def _message(row: Any) -> ChatMessage:
    grounded = row.grounded_in if isinstance(row.grounded_in, list) else []
    return ChatMessage(
        role=Role(row.role),
        text_ar=row.text_ar,
        created_at=row.created_at,
        grounded_in=tuple(str(item) for item in grounded),
        outcome=TurnOutcome(row.outcome),
    )


__all__ = ["ChatRepository"]
