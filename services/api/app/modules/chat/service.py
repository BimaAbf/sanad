"""The chat service — consent, retrieval, the graph, and the transcript.

Ordering in `ask` is the design, and it is the same shape as `voice/service.py`:

    clip -> require consent -> run the graph -> persist both turns

Consent (`ai_processing`) is **required**, not degraded past. That differs from
the recommendation service, and the difference is deliberate: a recommendation
has a complete deterministic answer with no model involved, so a caregiver who
declined AI still gets a working product. A chat turn has no deterministic
answer -- there is no engine that answers "how is he doing with colours" -- so
the honest response to a missing consent is a 403 that says which consent is
missing, not a canned sentence that looks like an answer.

Both turns are persisted even when the outcome is an escalation, a block or a
fallback. A transcript that only records the successful turns is a transcript
that cannot answer "what did the caregiver ask just before it refused", which is
the only question anyone reviewing an escalation will have.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from app.ai.langchain import GatewayRunnable
from app.modules.chat.domain import (
    CAREGIVER_HISTORY_TURNS,
    ChatMessage,
    ChildPhrase,
    Role,
    Surface,
    TurnOutcome,
    clip,
    recent,
)
from app.modules.chat.graph import (
    build_caregiver_graph,
    build_child_graph,
    caregiver_call,
    child_call,
)
from app.modules.chat.repository import ChatRepository
from app.modules.chat.speech import SttPort, TtsPort, UnavailableStt, UnavailableTts
from app.modules.children.consent_gate import ConsentGate
from app.modules.children.domain import ConsentKey
from app.modules.recommendation.service import RecommendationService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChatTurn:
    """One exchange, as the router renders it."""

    text_ar: str
    outcome: TurnOutcome
    grounded_in: tuple[str, ...] = ()
    #: Child surface only: the reviewed phrase that was selected, so the client
    #: can play its pre-rendered clip instead of synthesising anything.
    phrase_id: str | None = None
    audio_key: str | None = None


class ChatService:
    def __init__(
        self,
        *,
        repository: ChatRepository,
        recommendations: RecommendationService,
        consent: ConsentGate,
        gateway: Any | None = None,
        tts: TtsPort | None = None,
        stt: SttPort | None = None,
    ) -> None:
        self._repository = repository
        self._recommendations = recommendations
        self._consent = consent
        self._gateway = gateway
        self.tts = tts or UnavailableTts()
        self.stt = stt or UnavailableStt()

    # --- transcript ---------------------------------------------------------

    async def history(
        self, child_id: str, surface: Surface, *, limit: int = 20
    ) -> list[ChatMessage]:
        return await self._repository.recent(child_id, surface, limit=limit)

    async def purge(self, child_id: str) -> int:
        return await self._repository.purge(child_id)

    # --- the turn -----------------------------------------------------------

    def _runnable(self, which: str) -> GatewayRunnable | None:
        if self._gateway is None:
            return None
        call = caregiver_call() if which == "caregiver" else child_call()
        return GatewayRunnable(self._gateway, call)

    async def ask_caregiver(self, *, child_id: str, caregiver_id: str, message: str) -> ChatTurn:
        text = clip(message)
        await self._consent.require(child_id, ConsentKey.AI_PROCESSING)

        prior = await self._repository.recent(
            child_id, Surface.CAREGIVER, limit=CAREGIVER_HISTORY_TURNS
        )
        graph = build_caregiver_graph(
            retriever=self._recommendations.retriever(child_id),
            runnable=self._runnable("caregiver"),
        )
        state = await graph.ainvoke(
            {
                "child_id": child_id,
                "message": text,
                "history": recent(prior),
                # The PII layer needs something to check the answer against.
                # The child's display name is deliberately NOT loaded here --
                # `documents.py` never indexes it, the gateway pseudonymises
                # anything that slips through, and loading it to check for it
                # would be the only place in this path that reads it.
                "identifiers": [],
                "trace": [],
            }
        )
        turn = ChatTurn(
            text_ar=state.get("answer_ar", ""),
            outcome=state.get("outcome", TurnOutcome.FALLBACK),
            grounded_in=tuple(state.get("grounded_in", [])),
        )
        await self._persist(
            child_id=child_id,
            caregiver_id=caregiver_id,
            surface=Surface.CAREGIVER,
            question=text,
            turn=turn,
        )
        logger.info(
            "chat_turn",
            child_id=child_id,
            surface="caregiver",
            outcome=turn.outcome.value,
            count=len(turn.grounded_in),
        )
        return turn

    async def ask_child(self, *, child_id: str, caregiver_id: str | None, heard: str) -> ChatTurn:
        """The child surface. Selects a reviewed phrase; generates nothing.

        No retrieval. Nour does not reason about a child's history mid-session
        -- she reacts to the utterance in front of her, and the seven phrases
        she can say do not depend on anything a retriever could find.
        """
        text = clip(heard)
        await self._consent.require(child_id, ConsentKey.AI_PROCESSING)

        graph = build_child_graph(runnable=self._runnable("child"))
        state = await graph.ainvoke({"child_id": child_id, "message": text, "trace": []})
        phrase: ChildPhrase | None = state.get("phrase")
        turn = ChatTurn(
            text_ar=phrase.text_ar if phrase else "",
            outcome=state.get("outcome", TurnOutcome.FALLBACK),
            phrase_id=phrase.phrase_id if phrase else None,
            audio_key=phrase.audio_key if phrase else None,
        )
        await self._persist(
            child_id=child_id,
            caregiver_id=caregiver_id,
            surface=Surface.CHILD,
            question=text,
            turn=turn,
        )
        logger.info(
            "chat_turn",
            child_id=child_id,
            surface="child",
            outcome=turn.outcome.value,
            phrase_id=turn.phrase_id,
        )
        return turn

    async def _persist(
        self,
        *,
        child_id: str,
        caregiver_id: str | None,
        surface: Surface,
        question: str,
        turn: ChatTurn,
    ) -> None:
        await self._repository.append(
            child_id=child_id,
            caregiver_id=caregiver_id,
            surface=surface,
            role=Role.USER,
            text_ar=question,
        )
        await self._repository.append(
            child_id=child_id,
            caregiver_id=caregiver_id,
            surface=surface,
            role=Role.ASSISTANT,
            text_ar=turn.text_ar,
            grounded_in=turn.grounded_in,
            outcome=turn.outcome,
        )


__all__ = ["ChatService", "ChatTurn"]
