"""The two chat surfaces.

The assertions that matter most are the ones about what does NOT happen:
`test_red_flag_never_reaches_the_model` on both surfaces, and
`test_child_surface_can_only_say_a_reviewed_phrase`. The first is docs/04e's
requirement that red-flag input bypasses the AI entirely; the second is the
whole reason the child surface is a closed set.

The gateway used throughout is the ordinary fixture-replay one with no fixtures
present, which returns `Outcome.NO_FIXTURE`. That is not a mock -- it is the
configuration this product runs in by default, and every one of these paths has
to work in it.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.ai.gateway import LlmGateway
from app.ai.langchain import GatewayRunnable
from app.modules.chat.domain import (
    CAREGIVER_BLOCKED_AR,
    CAREGIVER_ESCALATION_AR,
    CAREGIVER_FALLBACK_AR,
    CHILD_ESCALATION_PHRASE,
    CHILD_PHRASES,
    ChatMessage,
    Role,
    TurnOutcome,
    child_phrase_ids,
    clip,
    recent,
    resolve_child_phrase,
    screen,
)
from app.modules.chat.graph import (
    CaregiverAnswer,
    ChildReply,
    build_caregiver_graph,
    build_child_graph,
    caregiver_call,
    caregiver_chain,
    child_call,
    child_chain,
)
from app.modules.chat.speech import (
    UnavailableStt,
    UnavailableTts,
    prerendered_audio_key,
)
from app.modules.recommendation.documents import SkillFact, build_corpus
from app.modules.recommendation.retriever import InMemoryChildMemoryRetriever

NOW = dt.datetime(2026, 8, 20, 9, 0, tzinfo=dt.UTC)

RED = SkillFact(
    skill_id="s-red",
    code="color_red",
    label_ar="أحمر",
    category="colors",
    state="practising",
    p_known=0.62,
    due_at=None,
    updated_at=NOW,
    total_attempts=20,
    total_correct=12,
    independent_attempts=9,
)

#: An Egyptian-Arabic distress phrase from `layers.RED_FLAG_PATTERNS`.
DISTRESS = "مش قادرة أكمل"


def _retriever() -> InMemoryChildMemoryRetriever:
    return InMemoryChildMemoryRetriever(documents=build_corpus("c1", skills=[RED]))


def _caregiver_graph(gateway: LlmGateway | None = None):
    runnable = GatewayRunnable(gateway, caregiver_call()) if gateway is not None else None
    return build_caregiver_graph(retriever=_retriever(), runnable=runnable)


def _child_graph(gateway: LlmGateway | None = None):
    runnable = GatewayRunnable(gateway, child_call()) if gateway is not None else None
    return build_child_graph(runnable=runnable)


def _state(message: str) -> dict:
    return {
        "child_id": "c1",
        "message": message,
        "history": [],
        "identifiers": [],
        "trace": [],
    }


# --- input screening --------------------------------------------------------


def test_ordinary_question_is_not_flagged() -> None:
    assert screen("إيه أخبار الألوان؟").escalate is False


def test_distress_is_flagged_for_escalation() -> None:
    result = screen(DISTRESS)
    assert result.escalate is True
    assert "distress" in result.categories


def test_clip_bounds_a_pasted_report() -> None:
    assert len(clip("ا" * 5000)) == 800


def test_recent_keeps_the_last_turns_oldest_first() -> None:
    messages = [ChatMessage(Role.USER, f"م{i}") for i in range(10)]
    kept = recent(messages, turns=3)
    assert [item["text"] for item in kept] == ["م7", "م8", "م9"]


# --- caregiver surface ------------------------------------------------------


async def test_caregiver_red_flag_never_reaches_the_model() -> None:
    """docs/04e: red-flag input bypasses the AI entirely and goes to a human.

    Asserted on the gateway's own record of what it sent, not on the answer --
    an assertion about the answer would still pass if the call had been made and
    its result discarded.
    """
    gateway = LlmGateway()
    state = await _caregiver_graph(gateway).ainvoke(_state(DISTRESS))
    assert state["outcome"] is TurnOutcome.ESCALATED
    assert state["answer_ar"] == CAREGIVER_ESCALATION_AR
    assert gateway.sent_payloads == []


async def test_caregiver_falls_back_when_no_model_answers() -> None:
    """The fallback says what happened rather than sounding like an answer."""
    state = await _caregiver_graph(LlmGateway()).ainvoke(_state("إيه أخبار الألوان؟"))
    assert state["outcome"] is TurnOutcome.FALLBACK
    assert state["answer_ar"] == CAREGIVER_FALLBACK_AR


async def test_caregiver_falls_back_with_no_model_configured() -> None:
    state = await _caregiver_graph(None).ainvoke(_state("إيه أخبار الألوان؟"))
    assert state["outcome"] is TurnOutcome.FALLBACK
    assert "answer=no_model" in state["trace"]


async def test_caregiver_retrieves_before_answering() -> None:
    state = await _caregiver_graph(LlmGateway()).ainvoke(_state("إيه أخبار الألوان؟"))
    assert state["documents"]
    assert state["grounded_in"]


def test_caregiver_chain_blocks_a_diagnosis() -> None:
    """L5. The single most important thing this surface must never produce."""
    result = caregiver_chain([]).run(
        CaregiverAnswer(answer_ar="طفلك عنده تأخر إدراكي وممكن يحتاج دوا.")
    )
    assert not result.ok
    assert result.blocked


def test_caregiver_chain_passes_ordinary_advice() -> None:
    result = caregiver_chain([]).run(CaregiverAnswer(answer_ar="جربوا الأحمر تاني النهارده."))
    assert result.ok


def test_caregiver_chain_blocks_a_leaked_identifier() -> None:
    result = caregiver_chain(["يوسف"]).run(CaregiverAnswer(answer_ar="يوسف بيتحسن في الألوان."))
    assert not result.ok


def test_blocked_message_is_not_the_fallback_message() -> None:
    """A caregiver must be able to tell a refusal from an outage."""
    assert CAREGIVER_BLOCKED_AR != CAREGIVER_FALLBACK_AR


# --- child surface ----------------------------------------------------------


async def test_child_red_flag_never_reaches_the_model() -> None:
    gateway = LlmGateway()
    state = await _child_graph(gateway).ainvoke(
        {"child_id": "c1", "message": DISTRESS, "trace": []}
    )
    assert state["outcome"] is TurnOutcome.ESCALATED
    assert state["phrase"].phrase_id == CHILD_ESCALATION_PHRASE
    assert gateway.sent_payloads == []


async def test_child_surface_always_answers_with_a_reviewed_phrase() -> None:
    state = await _child_graph(LlmGateway()).ainvoke(
        {"child_id": "c1", "message": "مش عارف", "trace": []}
    )
    assert state["phrase"].phrase_id in child_phrase_ids()


def test_child_surface_can_only_say_a_reviewed_phrase() -> None:
    """The closed set is the whole safety property of this surface.

    A model that returns an id outside `CHILD_PHRASES` is rejected by the chain
    AND resolved to the fallback -- two independent stops, because the failure
    this prevents is a child being told something nobody wrote.
    """
    rejected = child_chain().run(ChildReply(phrase_id="you_are_bad"))
    assert not rejected.ok
    assert resolve_child_phrase("you_are_bad").phrase_id == "not_understood"


def test_every_child_phrase_has_a_rendered_audio_key() -> None:
    """Nour's voice is frozen (Assumption C7). A phrase with no clip is silent."""
    for phrase in CHILD_PHRASES:
        assert prerendered_audio_key(phrase.phrase_id) == phrase.audio_key


def test_child_phrase_ids_are_unique() -> None:
    ids = child_phrase_ids()
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("phrase", CHILD_PHRASES, ids=lambda p: p.phrase_id)
def test_no_child_phrase_is_corrective(phrase) -> None:
    """docs/04e §C13: there is no failure state, so nothing Nour says is one.

    The retry pool is explicitly "gentle, never corrective" in docs/02 §5, and
    these phrases are the same contract in a different table.
    """
    for forbidden in ("غلط", "خطأ", "لأ ", "مش صح"):
        assert forbidden not in phrase.text_ar


# --- speech stubs -----------------------------------------------------------


def test_speech_ports_report_unsupported_rather_than_guessing() -> None:
    """A stub that returned empty text would hide "we did not listen"."""
    assert UnavailableTts().capability().supported is False
    assert UnavailableStt().capability().supported is False


def test_speech_capability_names_the_client_fallback() -> None:
    """The client reads this rather than hard-coding what to do instead, so
    turning on a server provider later needs no matching client release."""
    assert UnavailableTts().capability().client_fallback == "browser_speech_synthesis"
    assert UnavailableStt().capability().client_fallback == "browser_speech_recognition"
