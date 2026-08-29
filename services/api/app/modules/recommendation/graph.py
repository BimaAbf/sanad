"""The recommendation graph — LangGraph over the engine, the index and the judge.

    load_candidates -> retrieve -> judge -> decide

A graph rather than four awaits in a function, for one reason that matters and
one that will: every node's output is in a single state object, so the console
can show exactly what the model saw and what it did with it; and the same graph
gains a checkpointer when the session flow needs to pause and resume (docs/04b
§C04 wants `AsyncPostgresSaver` for the assessment session, and this is the
shape that takes one).

**The edges are deliberately unconditional.** There is no branch that skips the
judge when retrieval comes back empty, and no branch that skips `decide` when
the judge fails. `decide` is where the deterministic answer lives, so every path
through the graph -- including the one where the model was never called at all,
because `AI_LIVE` is off and no fixture exists -- terminates in a real
recommendation. A conditional edge here would be a second place where the
fallback lives, and the second place is the one that gets missed.

`load_candidates` runs the deterministic engine FIRST, before any retrieval or
model call. That ordering is the clinical constraint: the composition rule (at
most one new skill, none while three are practising) is applied to produce the
set, and everything downstream can only reorder what came out of it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, TypedDict

import structlog
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langgraph.graph import END, StateGraph

from app.ai.langchain import GatewayCall, GatewayInput, GatewayRunnable, frozen_system, unwrap
from app.modules.learning.domain.candidates import Candidate, candidates
from app.modules.recommendation import judge as judge_module
from app.modules.recommendation.judge import (
    NextExercisePlan,
    Recommendation,
    volatile_payload,
)
from app.modules.recommendation.retriever import as_payload, cited_ids

logger = structlog.get_logger(__name__)

# --- the frozen prompt half -------------------------------------------------
# Stable across every call, byte for byte. On Anthropic that is the cache
# prefix; on Groq there is no cache (docs/12 §1) but `fixture_key` still hashes
# what was sent, so drift here turns every replay into a miss.

RUBRIC_AR = """\
أنت بتساعد في ترتيب أنشطة قصيرة لطفل بيتعلم كلمات عربي.
مهمتك الوحيدة: ترتيب المهارات اللي اتبعتلك، من غير ما تضيف أي مهارة تانية.

قواعد ملزمة:
- استخدم بس الـ skill_id اللي في قائمة candidates. أي id تاني هيترفض بالكامل.
- متكررش نفس الـ id مرتين.
- مهارة واحدة بس نوعها "new" على الأكثر.
- ابدأ بمهارة الطفل بيعرفها كويس (kind = confidence) لو موجودة، عشان يبدأ بمكسب.
- لو في تاريخ بيقول إن الطفل بيخلط بين مهارتين، متحطهمش ورا بعض.
- لو في جلسات قفلت بسبب التعب، خلي الترتيب أقصر وأسهل في الأول.

الـ reason_ar: جملة واحدة قصيرة للأب أو الأم، بالعامية المصرية، من غير نسب
مئوية ومن غير أي كلام طبي أو تشخيص."""

SHAPE_AR = """\
رد بـ JSON بس، بالشكل ده:
{"ordered_skill_ids": ["..."], "reason_ar": "...", "grounded_in": ["..."]}
"""

SYSTEM_FROZEN = frozen_system(RUBRIC_AR, SHAPE_AR)

#: What the retriever is asked. Built from the candidates rather than from a
#: caregiver's question, because this graph runs unprompted -- it answers "what
#: next", and the relevant history is the history of the skills on the table.
RETRIEVAL_QUERY_PREFIX = "تاريخ الطفل مع المهارات دي:"


class RecommendationState(TypedDict, total=False):
    child_id: str
    now: dt.datetime
    snapshots: Sequence[Any]
    labels: Mapping[str, tuple[str, str]]
    candidates: list[Candidate]
    documents: list[Document]
    plan: NextExercisePlan | None
    recommendation: Recommendation | None
    #: Every node appends; nothing reads it but the console and the tests.
    trace: Annotated[list[str], lambda left, right: [*left, *right]]


def build_graph(
    *,
    retriever: BaseRetriever,
    runnable: GatewayRunnable | None,
    limit: int = 8,
) -> Any:
    """Compile the graph. `runnable=None` is the no-AI configuration.

    Passing `None` is not a test affordance -- it is the deployment where the
    feature flag is off, and it must produce the same shape of answer as the one
    where the model refused. Both land in `decide` with `plan=None`.
    """

    async def load_candidates(state: RecommendationState) -> dict[str, Any]:
        selected = candidates(
            state["snapshots"], now=state.get("now") or dt.datetime.now(dt.UTC), limit=limit
        )
        return {"candidates": selected, "trace": [f"candidates={len(selected)}"]}

    async def retrieve(state: RecommendationState) -> dict[str, Any]:
        labels = state.get("labels") or {}
        names = [labels.get(c.skill_id, ("", ""))[1] for c in state.get("candidates", [])]
        query = " ".join([RETRIEVAL_QUERY_PREFIX, *(name for name in names if name)])
        documents = await retriever.ainvoke(query)
        return {"documents": documents, "trace": [f"retrieved={len(documents)}"]}

    async def run_judge(state: RecommendationState) -> dict[str, Any]:
        selected = state.get("candidates", [])
        if runnable is None or not selected:
            return {"plan": None, "trace": ["judge=skipped"]}
        result = await runnable.ainvoke(
            GatewayInput(
                child_context=_child_context(state.get("documents", [])),
                volatile=volatile_payload(
                    selected,
                    state.get("labels") or {},
                    as_payload(state.get("documents", [])),
                ),
                child_id=state["child_id"],
            )
        )
        plan = unwrap(result, decision_point=judge_module.DECISION_POINT)
        return {"plan": plan, "trace": [f"judge={result.outcome.value}"]}

    async def decide(state: RecommendationState) -> dict[str, Any]:
        recommendation = judge_module.apply(
            state.get("plan"), state.get("candidates", []), state.get("labels") or {}
        )
        if recommendation is not None and not recommendation.grounded_in:
            # The judge is allowed to cite nothing. When it does, the audit
            # trail still records what it was shown -- otherwise a bad
            # recommendation is unreviewable after the fact.
            recommendation = _with_citations(
                recommendation, cited_ids(state.get("documents", []))
            )
        source = recommendation.source if recommendation else "none"
        logger.info(
            "recommendation_decided",
            child_id=state["child_id"],
            source=source,
            count=len(state.get("candidates", [])),
        )
        return {"recommendation": recommendation, "trace": [f"decided={source}"]}

    graph = StateGraph(RecommendationState)
    graph.add_node("load_candidates", load_candidates)
    graph.add_node("retrieve", retrieve)
    graph.add_node("judge", run_judge)
    graph.add_node("decide", decide)

    graph.set_entry_point("load_candidates")
    graph.add_edge("load_candidates", "retrieve")
    graph.add_edge("retrieve", "judge")
    graph.add_edge("judge", "decide")
    graph.add_edge("decide", END)
    return graph.compile()


def _child_context(documents: Sequence[Document]) -> dict[str, Any]:
    """The semi-stable half of the prompt.

    Only the profile document goes here. It changes when a caregiver changes a
    setting -- rarely -- while the history documents change after every session,
    and putting a volatile value above the cache line silently destroys the
    prefix (`tools/guards/prompt_cache_hit.py` exists because that failure costs
    money without failing a test).
    """
    for document in documents:
        if document.metadata.get("kind") == "profile":
            return {"settings": document.page_content}
    return {}


def _with_citations(recommendation: Recommendation, ids: Sequence[str]) -> Recommendation:
    from dataclasses import replace

    kept = tuple(identifier for identifier in ids if identifier)
    return replace(recommendation, grounded_in=kept)


def gateway_call() -> GatewayCall:
    """The judge's decision-point binding. One place, so the layers match."""
    return GatewayCall(
        decision_point=judge_module.DECISION_POINT,
        schema_model=NextExercisePlan,
        system_frozen=SYSTEM_FROZEN,
    )


__all__ = [
    "RETRIEVAL_QUERY_PREFIX",
    "RUBRIC_AR",
    "SYSTEM_FROZEN",
    "RecommendationState",
    "build_graph",
    "gateway_call",
]
