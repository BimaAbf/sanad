"""T09 — privacy, consent, failover and the audio lifecycle.

Everything here is about what happens to a child's voice, so the assertions are
deliberately about *absence*: no file left on disk, no object in the bucket, no
call to the LLM gateway, no expressive activity without consent.
"""

from __future__ import annotations

import ast
import datetime as dt
import os
from pathlib import Path

import pytest
from seeds.curriculum import ACTIVITY_TEMPLATES, build_skills

from app.modules.children.domain import ConsentKey
from app.modules.learning.domain.bkt import PROMPT_DISCOUNT, BktState, PromptLevel, bkt_update
from app.modules.voice.domain.audio import (
    MAX_UPLOAD_BYTES,
    AudioRejected,
    needs_temp_file,
    sniff,
    validate_upload,
)
from app.modules.voice.domain.coverage import (
    SkillTier,
    TemplateModality,
    expressive_only_skills,
    receptive_gaps,
)
from app.modules.voice.domain.modes import (
    CAREGIVER_CONFIRMED_DISCOUNT,
    VoiceMode,
    bkt_inputs,
    resolve_capability,
)
from app.modules.voice.domain.scoring import AttemptResult, ExpectedWord, Verdict
from app.modules.voice.providers import (
    AsrChain,
    AsrUnavailable,
    HttpAsrProvider,
    NullAsr,
    NullTts,
    PreRenderedTts,
    groq_whisper_provider,
    qwen_provider,
)
from app.modules.voice.service import (
    AudioInvalid,
    AudioNotPermitted,
    InMemoryAudioSink,
    TempAudio,
    VoiceService,
    audio_key,
    phrase_hints,
)

OGG = b"OggS" + b"\x00" * 60
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 60
RED = ExpectedWord(skill_code="color_red", label_ar="أحمر", label_egy="أحمر")


class FakeConsent:
    def __init__(self, **granted: bool) -> None:
        self.granted = granted

    async def is_granted(self, child_id: str, key: ConsentKey) -> bool:
        return self.granted.get(key.value, False)


def build_service(
    *,
    consent: FakeConsent,
    hypotheses: list[str] | None = None,
    fail: bool = False,
    sink: InMemoryAudioSink | None = None,
) -> tuple[VoiceService, InMemoryAudioSink]:
    store = sink or InMemoryAudioSink()
    chain = AsrChain([NullAsr(default=hypotheses or ["أحمر"], fail=fail)])
    return VoiceService(asr=chain, consent=consent, sink=store), store


# --- audio validation ------------------------------------------------------


def test_magic_bytes_decide_the_container_not_the_extension() -> None:
    """T09 §16: a non-audio file with an audio extension is rejected."""
    disguised = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    with pytest.raises(AudioRejected) as exc:
        validate_upload(disguised)
    assert exc.value.reason == "unrecognised_audio_container"


def test_recognised_containers() -> None:
    assert sniff(OGG) is not None
    assert sniff(WEBM) is not None
    assert sniff(b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40) is not None
    assert sniff(b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 40) is not None
    # A RIFF container that is not WAVE (e.g. AVI) is not audio.
    assert sniff(b"RIFF" + b"\x00" * 4 + b"AVI " + b"\x00" * 40) is None
    assert sniff(b"not audio at all") is None


def test_upload_over_one_megabyte_is_rejected() -> None:
    """T09 §17."""
    with pytest.raises(AudioRejected) as exc:
        validate_upload(OGG + b"\x00" * MAX_UPLOAD_BYTES)
    assert exc.value.reason == "audio_too_large"


def test_empty_upload_is_rejected_distinctly() -> None:
    with pytest.raises(AudioRejected) as exc:
        validate_upload(b"")
    assert exc.value.reason == "empty_audio"


def test_small_audio_never_touches_the_disk() -> None:
    assert not needs_temp_file(OGG)
    held = TempAudio(OGG)
    assert held.path is None
    held.cleanup()  # must be safe even though nothing was written


def test_large_audio_uses_a_temp_file_and_removes_it() -> None:
    big = OGG + b"\x00" * (300 * 1024)
    held = TempAudio(big)
    assert held.path is not None
    path = held.path
    assert os.path.exists(path)
    held.cleanup()
    assert not os.path.exists(path)
    held.cleanup()  # idempotent


# --- consent ---------------------------------------------------------------


async def test_without_voice_asr_consent_nothing_is_transcribed() -> None:
    service, _ = build_service(consent=FakeConsent())
    with pytest.raises(AudioNotPermitted):
        await service.score_attempt(
            child_id="c1", expected=RED, audio=OGG, attempt_no=1, attempt_id="a1"
        )


async def test_consent_is_checked_before_the_provider_is_called() -> None:
    """Ordering matters: a healthy provider must not make consent irrelevant."""
    provider = NullAsr(default=["أحمر"])
    service = VoiceService(
        asr=AsrChain([provider]), consent=FakeConsent(), sink=InMemoryAudioSink()
    )
    with pytest.raises(AudioNotPermitted):
        await service.score_attempt(
            child_id="c1", expected=RED, audio=OGG, attempt_no=1, attempt_id="a1"
        )
    assert provider.calls == 0


async def test_audio_is_deleted_after_scoring_without_retention_consent() -> None:
    """T09 §9 — check the temp directory AND the bucket."""
    service, sink = build_service(consent=FakeConsent(voice_asr=True))
    before = set(Path(os.environ.get("TEMP", "/tmp")).glob("sanad-voice-*"))

    outcome = await service.score_attempt(
        child_id="c1",
        expected=RED,
        audio=OGG + b"\x00" * (300 * 1024),
        attempt_no=1,
        attempt_id="a1",
    )

    assert outcome.score.verdict is Verdict.ACCEPT
    assert outcome.stored_audio_key is None
    assert sink.objects == {}
    after = set(Path(os.environ.get("TEMP", "/tmp")).glob("sanad-voice-*"))
    assert after == before


async def test_with_retention_consent_audio_lands_in_the_bucket() -> None:
    """T09 §10."""
    service, sink = build_service(consent=FakeConsent(voice_asr=True, voice_retention=True))
    outcome = await service.score_attempt(
        child_id="c1", expected=RED, audio=OGG, attempt_no=1, attempt_id="a1"
    )
    assert outcome.stored_audio_key == audio_key("c1", "color_red", "a1")
    assert await sink.list_prefix("audio/c1/") == [outcome.stored_audio_key]


async def test_retention_stores_nothing_for_a_retry_that_was_not_recorded() -> None:
    """A retry writes no attempt row, so there is nothing for the audio to belong to."""
    service, sink = build_service(
        consent=FakeConsent(voice_asr=True, voice_retention=True), hypotheses=["أزرق"]
    )
    outcome = await service.score_attempt(
        child_id="c1", expected=RED, audio=OGG, attempt_no=1, attempt_id="a1"
    )
    assert outcome.score.verdict is Verdict.RETRY
    assert sink.objects == {}


async def test_withdrawing_retention_purges_the_prefix() -> None:
    """T09 §11 — the object-store half; the pgvector half is the caller's."""
    service, sink = build_service(consent=FakeConsent(voice_asr=True, voice_retention=True))
    for index in range(3):
        await service.score_attempt(
            child_id="c1", expected=RED, audio=OGG, attempt_no=1, attempt_id=f"a{index}"
        )
    await sink.put("audio/c2/color_red/other.opus", OGG, content_type="audio/ogg")

    removed = await service.purge_child_audio("c1")
    assert removed == 3
    assert await sink.list_prefix("audio/c1/") == []
    # Another child's audio is untouched.
    assert await sink.list_prefix("audio/c2/") == ["audio/c2/color_red/other.opus"]


async def test_invalid_audio_raises_a_problem_detail_with_arabic() -> None:
    service, _ = build_service(consent=FakeConsent(voice_asr=True))
    with pytest.raises(AudioInvalid) as exc:
        await service.score_attempt(
            child_id="c1", expected=RED, audio=b"junk", attempt_no=1, attempt_id="a1"
        )
    assert exc.value.message_ar
    assert exc.value.status == 400


# --- failover --------------------------------------------------------------


async def test_first_provider_wins() -> None:
    first = NullAsr(default=["أحمر"])
    second = NullAsr(default=["أزرق"])
    chain = AsrChain([first, second])
    result = await chain.transcribe(OGG)
    assert result.provider == "null"
    assert second.calls == 0


async def test_a_dead_provider_falls_through_to_the_next() -> None:
    """T09 §6 — Qwen down, Groq Whisper answers, the session continues."""
    dead = NullAsr(fail=True)
    alive = NullAsr(default=["أحمر"])
    alive.name = "groq_whisper"
    result = await AsrChain([dead, alive]).transcribe(OGG)
    assert result.provider == "groq_whisper"
    assert not result.unavailable


async def test_an_empty_answer_asks_the_next_provider() -> None:
    empty = NullAsr(default=[])
    alive = NullAsr(default=["أحمر"])
    result = await AsrChain([empty, alive]).transcribe(OGG)
    assert result.n_best


async def test_both_providers_down_is_unavailable_not_an_exception() -> None:
    """T09 §7 — "say it together" mode is reachable, not a crash."""
    result = await AsrChain([NullAsr(fail=True), NullAsr(fail=True)]).transcribe(OGG)
    assert result.unavailable
    assert result.provider == "none"


async def test_asr_unavailable_degrades_the_session_not_the_child() -> None:
    service, _ = build_service(consent=FakeConsent(voice_asr=True), fail=True)
    outcome = await service.score_attempt(
        child_id="c1", expected=RED, audio=OGG, attempt_no=1, attempt_id="a1"
    )
    assert outcome.degraded_to is VoiceMode.CAREGIVER_CONFIRM
    assert outcome.score.reason == "asr_unavailable"
    # Nothing is recorded against the child.
    assert outcome.bkt is None


def test_capability_ladder() -> None:
    assert (
        resolve_capability(voice_asr_consent=False, mic_permission=True, asr_providers_up=2).mode
        is VoiceMode.RECEPTIVE_ONLY
    )
    assert (
        resolve_capability(voice_asr_consent=True, mic_permission=False, asr_providers_up=2).mode
        is VoiceMode.RECEPTIVE_ONLY
    )
    assert (
        resolve_capability(voice_asr_consent=True, mic_permission=True, asr_providers_up=2).mode
        is VoiceMode.ASR
    )
    assert (
        resolve_capability(voice_asr_consent=True, mic_permission=True, asr_providers_up=0).mode
        is VoiceMode.CAREGIVER_CONFIRM
    )
    assert (
        resolve_capability(
            voice_asr_consent=True,
            mic_permission=True,
            asr_providers_up=0,
            caregiver_present=False,
        ).mode
        is VoiceMode.SAY_TOGETHER
    )
    assert (
        resolve_capability(
            voice_asr_consent=True,
            mic_permission=True,
            asr_providers_up=2,
            noisy_environment=True,
        ).mode
        is VoiceMode.CAREGIVER_CONFIRM
    )


def test_capability_flags() -> None:
    receptive = resolve_capability(voice_asr_consent=False, mic_permission=True, asr_providers_up=1)
    assert not receptive.expressive_allowed
    assert not receptive.records_audio
    asr = resolve_capability(voice_asr_consent=True, mic_permission=True, asr_providers_up=1)
    assert asr.expressive_allowed
    assert asr.records_audio


async def test_service_capability_reads_consent() -> None:
    service, _ = build_service(consent=FakeConsent(voice_asr=True))
    assert (await service.capability("c1")).mode is VoiceMode.ASR
    service2, _ = build_service(consent=FakeConsent())
    assert (await service2.capability("c1")).mode is VoiceMode.RECEPTIVE_ONLY


# --- the caregiver override ------------------------------------------------


async def test_override_records_caregiver_confirmed_at_half_weight() -> None:
    """T09 §5 — the control that makes this feature work at all."""
    service, sink = build_service(consent=FakeConsent())
    outcome = await service.override(child_id="c1", expected=RED)

    assert outcome.score.result is AttemptResult.CAREGIVER_CONFIRMED
    assert outcome.bkt == (True, PromptLevel.INDEPENDENT, CAREGIVER_CONFIRMED_DISCOUNT)
    # No consent needed and no audio involved: this is the path that always works.
    assert sink.objects == {}


def test_caregiver_confirmed_moves_bkt_less_than_an_independent_correct() -> None:
    state = BktState()
    independent = bkt_update(
        state, correct=True, choice_count=2, prompt_level=PromptLevel.INDEPENDENT
    )
    confirmed = bkt_update(
        state,
        correct=True,
        choice_count=2,
        prompt_level=PromptLevel.INDEPENDENT,
        discount_override=CAREGIVER_CONFIRMED_DISCOUNT,
    )
    assert confirmed.p_known < independent.p_known


def test_accepted_on_effort_is_weighted_like_a_partial_verbal_prompt() -> None:
    """docs/04d §3 states this explicitly, and it is what keeps measurement honest."""
    correct, level, override = bkt_inputs(AttemptResult.ACCEPTED_ON_EFFORT)
    assert correct
    assert level is PromptLevel.PARTIAL_VERBAL
    assert override is None
    assert PROMPT_DISCOUNT[level] < PROMPT_DISCOUNT[PromptLevel.INDEPENDENT]


def test_no_response_is_not_correct() -> None:
    correct, _, _ = bkt_inputs(AttemptResult.NO_RESPONSE)
    assert not correct


# --- the curriculum is completable without speaking ------------------------


def test_every_one_of_the_88_skills_has_a_receptive_route() -> None:
    """T09 §8 — walk the full curriculum, not a sample.

    A family that declines microphone consent must get the whole product. If
    this ever fails, the consent toggle has become a paywall on learning.
    """
    skills = [SkillTier(s.code, s.difficulty_tier) for s in build_skills()]
    templates = [TemplateModality(t.code, t.modality, t.min_tier) for t in ACTIVITY_TEMPLATES]
    assert len(skills) == 88
    assert receptive_gaps(skills, templates) == []
    assert expressive_only_skills(skills, templates) == []


# --- nothing reaches the LLM ----------------------------------------------

VOICE_ROOT = Path(__file__).resolve().parents[2] / "app" / "modules" / "voice"


def test_the_voice_module_cannot_reach_the_llm_gateway() -> None:
    """T09 §12, enforced structurally rather than by observation.

    A spy on gateway calls proves nothing about the code paths the test did not
    walk. Proving the import does not exist proves it about all of them: audio,
    transcripts and embeddings cannot cross a boundary the module cannot name.
    """
    offenders: list[str] = []
    for path in VOICE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.startswith("app.ai") or name == "anthropic":
                    offenders.append(f"{path.name}:{node.lineno} imports {name}")
    assert offenders == []


async def test_a_full_voice_attempt_makes_zero_gateway_calls() -> None:
    """The behavioural half of the same claim, for the actual request path."""
    import app.ai.gateway as gateway

    calls: list[object] = []
    original = getattr(gateway, "call_structured", None)
    if original is not None:
        gateway.call_structured = lambda *a, **k: calls.append((a, k))  # type: ignore[assignment]
    try:
        service, _ = build_service(consent=FakeConsent(voice_asr=True, voice_retention=True))
        await service.score_attempt(
            child_id="c1", expected=RED, audio=OGG, attempt_no=1, attempt_id="a1"
        )
        await service.override(child_id="c1", expected=RED)
    finally:
        if original is not None:
            gateway.call_structured = original  # type: ignore[assignment]
    assert calls == []


# --- providers -------------------------------------------------------------


class FakeTransport:
    def __init__(self, payload: dict[str, object] | None = None, raises: bool = False) -> None:
        self.payload = payload or {"text": "أحمر", "confidence": 0.8}
        self.raises = raises
        self.seen: dict[str, object] = {}

    async def post_audio(self, **kwargs: object) -> dict[str, object]:
        self.seen = kwargs
        if self.raises:
            raise TimeoutError("provider timeout")
        return self.payload


async def test_http_provider_sends_phrase_hints() -> None:
    """docs/04d §3: the single biggest accuracy lever on short utterances."""
    transport = FakeTransport()
    provider = qwen_provider(transport)
    await provider.transcribe(OGG, phrase_hints=["أحمر", "احمر"])
    assert transport.seen["prompt"] == "أحمر احمر"
    assert transport.seen["model"] == "Qwen/Qwen3-ASR-1.7B"


async def test_http_provider_reads_n_best_segments() -> None:
    transport = FakeTransport({"segments": ["أحمر", "أحم", "احم"], "confidence": 0.5})
    result = await groq_whisper_provider(transport).transcribe(OGG, n_best=2)
    assert [h.text for h in result.n_best] == ["أحمر", "أحم"]
    assert result.provider == "groq_whisper"


async def test_http_provider_failure_becomes_asr_unavailable() -> None:
    provider = HttpAsrProvider(name="qwen", model="m", transport=FakeTransport(raises=True))
    with pytest.raises(AsrUnavailable):
        await provider.transcribe(OGG)


async def test_http_provider_with_no_text_returns_no_hypotheses() -> None:
    result = await qwen_provider(FakeTransport({"confidence": 0.0})).transcribe(OGG)
    assert result.n_best == ()


def test_phrase_hints_are_deduplicated_and_stable() -> None:
    word = ExpectedWord(skill_code="c", label_ar="أحمر", label_egy="احمر")
    assert phrase_hints(word) == ["احمر"]
    assert phrase_hints(word, ["أحم", ""]) == ["احمر", "احم"]


def test_chain_reports_its_providers() -> None:
    chain = AsrChain([NullAsr(), NullAsr()])
    assert chain.provider_names == ["null", "null"]


# --- TTS providers ---------------------------------------------------------


async def test_null_tts_returns_a_sniffable_tone() -> None:
    tts = NullTts()
    data = await tts.synthesize("<speak/>", "nour")
    assert sniff(data) is not None
    assert tts.calls == 1


async def test_prerendered_tts_serves_only_what_was_rendered() -> None:
    """docs/12 §Δ2: a miss is a publish-gate failure, never a live synthesis."""
    tts = PreRenderedTts({"<speak>hello</speak>": OGG})
    assert await tts.synthesize("<speak>hello</speak>", "nour") == OGG
    with pytest.raises(LookupError):
        await tts.synthesize("<speak>missing</speak>", "nour")


def test_service_health_reports_configuration_not_a_probe() -> None:
    service, _ = build_service(consent=FakeConsent())
    assert service.provider_status() == {"null": "configured"}
    assert service.cache_hit_rate() == 1.0
    assert service.missing_asset_count() == 0


def test_audio_key_shape_matches_the_privacy_doc() -> None:
    assert audio_key("c1", "hh_shoes", "u1") == "audio/c1/hh_shoes/u1.opus"


def test_retention_window_is_thirty_days() -> None:
    from app.modules.voice.service import MAX_REFERENCES_PER_SKILL, RETENTION_DAYS

    assert RETENTION_DAYS == 30
    assert MAX_REFERENCES_PER_SKILL == 20
    assert dt.timedelta(days=RETENTION_DAYS).days == 30
