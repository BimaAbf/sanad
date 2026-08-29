"""The chat graphs — one per surface, because they are not the same product.

    caregiver:  screen -> retrieve -> answer -> guard
    child:      screen -> classify -> resolve

The caregiver graph retrieves and generates. The child graph retrieves nothing
and generates nothing: it classifies an utterance into one of seven reviewed
phrases (`domain.CHILD_PHRASES`) and resolves the id. `domain.py` sets out why
at length; the short version is that the child app runs offline from a
pre-rendered audio corpus and nothing unreviewed should be spoken to a child
learning these exact words.

Both graphs enter at `screen`, and on both, a red-flag finding **terminates the
graph before any model call**. That is the one conditional edge in either graph,
and it is conditional precisely because the requirement is that the model is not
reached at all -- not that its answer is discarded afterwards.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

import structlog
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from app.ai.langchain import GatewayCall, GatewayInput, GatewayRunnable, frozen_system, unwrap
from app.guardrails.chain import GuardrailChain
from app.guardrails.layers import (
    enforce_clinical_safety,
    enforce_enum,
    enforce_no_pii,
    enforce_reading_level,
)
from app.modules.chat.domain import (
    CAREGIVER_BLOCKED_AR,
    CAREGIVER_ESCALATION_AR,
    CAREGIVER_FALLBACK_AR,
    CHILD_ESCALATION_PHRASE,
    CHILD_PHRASES,
    ChildPhrase,
    TurnOutcome,
    child_phrase_ids,
    resolve_child_phrase,
    screen,
)
from app.modules.recommendation.retriever import as_payload, cited_ids

logger = structlog.get_logger(__name__)

CAREGIVER_DECISION_POINT = "caregiver_chat"
CHILD_DECISION_POINT = "child_chat"


# --- output contracts -------------------------------------------------------


class CaregiverAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_ar: str = Field(min_length=1, max_length=700)
    #: Which retrieved documents the answer actually used. Self-reported and
    #: therefore not trusted as a citation -- it is compared against what was
    #: retrieved so the console can show a model claiming evidence it was never
    #: shown.
    used_document_ids: list[str] = Field(default_factory=list, max_length=8)


class ChildReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phrase_id: str = Field(min_length=1, max_length=40)


# --- frozen prompt halves ---------------------------------------------------

CAREGIVER_RUBRIC_AR = """\
انت مساعد لأب أو أم عندهم طفل بيستخدم تطبيق سند لتعلّم كلمات عربي.
بتجاوب بالعامية المصرية، بجملتين أو تلاتة على الأكثر.

اللي تعمله:
- جاوب من واقع «history» اللي اتبعتلك بس. دي بيانات الطفل الحقيقية.
- لو المعلومة مش في الـ history، قول إنك مش عارف. متخمّنش.
- اقترح خطوة عملية واحدة صغيرة يقدروا يعملوها النهارده.

اللي متعملهوش أبداً:
- متشخّصش، ومتتكلمش عن دوا ولا علاج ولا تطور طبي.
- متقولش نسب مئوية ولا مقارنة بأطفال تانيين ولا أعمار «طبيعية».
- متوعدش بنتايج، ومتقولش إن الطفل «متأخر» أو «ضعيف».
- متذكرش اسم الطفل. اتكلم عنه بصيغة «طفلك»."""

CAREGIVER_SHAPE_AR = """\
رد بـ JSON بس: {"answer_ar": "...", "used_document_ids": ["..."]}
"""

CAREGIVER_SYSTEM = frozen_system(CAREGIVER_RUBRIC_AR, CAREGIVER_SHAPE_AR)


def _child_menu_ar() -> str:
    lines = [f"- {phrase.phrase_id}: {phrase.when_ar}" for phrase in CHILD_PHRASES]
    return "\n".join(lines)


CHILD_RUBRIC_AR = f"""\
انت بتساعد شخصية اسمها «نور» بتتكلم مع طفل صغير بيتعلم كلمات.
نور بتقول جمل جاهزة بس. انت شغلتك تختار جملة واحدة من القايمة دي:

{_child_menu_ar()}

اختار الـ id اللي مناسب لكلام الطفل. متكتبش أي جملة من عندك.
لو مش متأكد، اختار not_understood."""

CHILD_SHAPE_AR = """\
رد بـ JSON بس: {"phrase_id": "..."}
"""

CHILD_SYSTEM = frozen_system(CHILD_RUBRIC_AR, CHILD_SHAPE_AR)


# --- state ------------------------------------------------------------------


class ChatState(TypedDict, total=False):
    child_id: str
    message: str
    history: list[dict[str, str]]
    #: Identifiers the PII layer checks the answer against. Never sent.
    identifiers: list[str]
    documents: list[Document]
    answer_ar: str
    phrase: ChildPhrase | None
    grounded_in: list[str]
    outcome: TurnOutcome
    trace: Annotated[list[str], lambda left, right: [*left, *right]]


# --- caregiver graph --------------------------------------------------------


def caregiver_chain(identifiers: list[str]) -> GuardrailChain:
    """L5 safety, reading level and the PII leak check, cheapest last.

    Safety runs first deliberately. A blocked answer is never rendered, so
    spending the reading-level regex on text that is about to be thrown away is
    work for nothing -- and more importantly, a block and a rejection are
    different outcomes and the caregiver sees a different message for each.
    """

    def safety(answer: CaregiverAnswer) -> None:
        enforce_clinical_safety(answer.answer_ar)

    def reading_level(answer: CaregiverAnswer) -> None:
        enforce_reading_level(answer.answer_ar)

    def no_pii(answer: CaregiverAnswer) -> None:
        enforce_no_pii(answer.answer_ar, identifiers)

    return GuardrailChain(
        CAREGIVER_DECISION_POINT,
        [("clinical_safety", safety), ("reading_level", reading_level), ("pii_leak", no_pii)],
    )


def build_caregiver_graph(
    *, retriever: BaseRetriever, runnable: GatewayRunnable | None
) -> Any:
    async def screen_input(state: ChatState) -> dict[str, Any]:
        result = screen(state["message"])
        if result.escalate:
            logger.info(
                "chat_escalated",
                child_id=state["child_id"],
                surface="caregiver",
                categories=list(result.categories),
            )
            return {
                "answer_ar": CAREGIVER_ESCALATION_AR,
                "outcome": TurnOutcome.ESCALATED,
                "trace": [f"screen=escalate:{','.join(result.categories)}"],
            }
        return {"trace": ["screen=clear"]}

    async def retrieve(state: ChatState) -> dict[str, Any]:
        documents = await retriever.ainvoke(state["message"])
        return {"documents": documents, "trace": [f"retrieved={len(documents)}"]}

    async def answer(state: ChatState) -> dict[str, Any]:
        documents = state.get("documents", [])
        if runnable is None:
            return {
                "answer_ar": CAREGIVER_FALLBACK_AR,
                "outcome": TurnOutcome.FALLBACK,
                "trace": ["answer=no_model"],
            }
        result = await runnable.ainvoke(
            GatewayInput(
                child_context={"history": as_payload(documents)},
                volatile={
                    "question": state["message"],
                    "recent_turns": state.get("history", []),
                },
                child_id=state["child_id"],
            )
        )
        value = unwrap(result, decision_point=CAREGIVER_DECISION_POINT)
        if value is None:
            return {
                "answer_ar": CAREGIVER_FALLBACK_AR,
                "outcome": TurnOutcome.FALLBACK,
                "grounded_in": cited_ids(documents),
                "trace": [f"answer={result.outcome.value}"],
            }

        chain = caregiver_chain(state.get("identifiers", []))
        checked = chain.run(value)
        if not checked.ok:
            logger.info(
                "chat_answer_blocked",
                child_id=state["child_id"],
                guardrail_layer=checked.events[-1].layer if checked.events else "unknown",
            )
            return {
                "answer_ar": CAREGIVER_BLOCKED_AR,
                "outcome": TurnOutcome.BLOCKED,
                "grounded_in": cited_ids(documents),
                "trace": ["answer=blocked"],
            }
        return {
            "answer_ar": value.answer_ar,
            "outcome": TurnOutcome.OK,
            # What was RETRIEVED, not what the model said it used. The model's
            # own list is unverified; the retrieval log is a fact.
            "grounded_in": cited_ids(documents),
            "trace": ["answer=ok"],
        }

    def after_screen(state: ChatState) -> str:
        return END if state.get("outcome") is TurnOutcome.ESCALATED else "retrieve"

    graph = StateGraph(ChatState)
    graph.add_node("screen", screen_input)
    graph.add_node("retrieve", retrieve)
    graph.add_node("answer", answer)
    graph.set_entry_point("screen")
    graph.add_conditional_edges("screen", after_screen, {END: END, "retrieve": "retrieve"})
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


# --- child graph ------------------------------------------------------------


def child_chain() -> GuardrailChain:
    """One check, and it is the whole safety property of this surface."""

    def closed_set(reply: ChildReply) -> None:
        enforce_enum(reply.phrase_id, child_phrase_ids(), layer="child_phrase_allowlist")

    return GuardrailChain(CHILD_DECISION_POINT, [("child_phrase_allowlist", closed_set)])


def build_child_graph(*, runnable: GatewayRunnable | None) -> Any:
    async def screen_input(state: ChatState) -> dict[str, Any]:
        result = screen(state["message"])
        if result.escalate:
            logger.info(
                "chat_escalated",
                child_id=state["child_id"],
                surface="child",
                categories=list(result.categories),
            )
            return {
                "phrase": resolve_child_phrase(CHILD_ESCALATION_PHRASE),
                "outcome": TurnOutcome.ESCALATED,
                "trace": ["screen=escalate"],
            }
        return {"trace": ["screen=clear"]}

    async def classify(state: ChatState) -> dict[str, Any]:
        if runnable is None:
            return {
                "phrase": resolve_child_phrase(None),
                "outcome": TurnOutcome.FALLBACK,
                "trace": ["classify=no_model"],
            }
        result = await runnable.ainvoke(
            GatewayInput(
                volatile={"heard": state["message"]},
                child_id=state["child_id"],
            )
        )
        value = unwrap(result, decision_point=CHILD_DECISION_POINT)
        if value is None:
            return {
                "phrase": resolve_child_phrase(None),
                "outcome": TurnOutcome.FALLBACK,
                "trace": [f"classify={result.outcome.value}"],
            }
        checked = child_chain().run(value)
        if not checked.ok:
            # An invented phrase id. `resolve_child_phrase` would have caught it
            # anyway -- the chain runs so the rejection is *recorded* rather than
            # silently absorbed, which is what makes "the model tried to say
            # something new" visible in the console.
            return {
                "phrase": resolve_child_phrase(None),
                "outcome": TurnOutcome.BLOCKED,
                "trace": ["classify=off_allowlist"],
            }
        return {
            "phrase": resolve_child_phrase(value.phrase_id),
            "outcome": TurnOutcome.OK,
            "trace": ["classify=ok"],
        }

    def after_screen(state: ChatState) -> str:
        return END if state.get("outcome") is TurnOutcome.ESCALATED else "classify"

    graph = StateGraph(ChatState)
    graph.add_node("screen", screen_input)
    graph.add_node("classify", classify)
    graph.set_entry_point("screen")
    graph.add_conditional_edges("screen", after_screen, {END: END, "classify": "classify"})
    graph.add_edge("classify", END)
    return graph.compile()


# --- decision-point bindings ------------------------------------------------


def caregiver_call() -> GatewayCall:
    return GatewayCall(
        decision_point=CAREGIVER_DECISION_POINT,
        schema_model=CaregiverAnswer,
        system_frozen=CAREGIVER_SYSTEM,
    )


def child_call() -> GatewayCall:
    return GatewayCall(
        decision_point=CHILD_DECISION_POINT,
        schema_model=ChildReply,
        system_frozen=CHILD_SYSTEM,
    )


__all__ = [
    "CAREGIVER_DECISION_POINT",
    "CAREGIVER_SYSTEM",
    "CHILD_DECISION_POINT",
    "CHILD_SYSTEM",
    "CaregiverAnswer",
    "ChatState",
    "ChildReply",
    "build_caregiver_graph",
    "build_child_graph",
    "caregiver_call",
    "caregiver_chain",
    "child_call",
    "child_chain",
]
