# 04d — Component: C08 Voice Gateway

> **Providers in this document are superseded by [12 — Stack Revision](12-stack-revision-groq-selfhosted-voice.md).** TTS is now VoxCPM2 with a cloned Egyptian voice, batch-rendered offline to CDN (no runtime TTS in the child's path). ASR is now self-hosted Qwen3-ASR-1.7B with Groq Whisper failover. **The scoring design — `normalize_ar`, the phoneme substitution-cost matrix, the 0.55 threshold, the three verdicts, accept-on-effort and the caregiver override — is unchanged, because none of it depended on the vendor.**


The component with the widest gap between "works in a demo" and "works for these children". Everything here is designed around one fact:

> **No commercial ASR is validated on the speech of Egyptian Arabic-speaking children with Down syndrome.** Reduced intelligibility is the norm, not the exception — hypotonia, high rates of childhood apraxia of speech, and orofacial differences all push word error rates far above the vendor's published numbers.

So the architecture treats ASR as a **sensor with known bias**, not as a judge.

---

## 1. Responsibilities

1. Synthesise Egyptian Arabic speech (TTS), cache it permanently, pre-generate the corpus.
2. Transcribe short child utterances (ASR) behind a provider interface.
3. Score a pronunciation attempt leniently and return one of three verdicts.
4. Provide the caregiver override path.
5. Build a per-child pronunciation reference over time (opt-in), so recognition improves for *that child*.
6. Never retain audio without explicit consent.

---

## 2. Text-to-speech

### Provider interface

```python
class TtsProvider(Protocol):
    async def synthesize(self, ssml: str, voice: str,
                         fmt: str = "ogg-48khz-16bit-mono-opus") -> bytes: ...

class AzureTts(TtsProvider): ...        # primary — ar-EG-SalmaNeural / ar-EG-ShakirNeural
class ElevenLabsTts(TtsProvider): ...   # alternative, multilingual, warmer character voice
class NullTts(TtsProvider): ...         # tests — returns a fixed 200 ms tone
```

### SSML template

Rate and pauses are tuned for auditory-short-term-memory limits, not for naturalness. This is worth being explicit about: the voice is deliberately slower than a demo would want.

```xml
<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="ar-EG">
  <voice name="ar-EG-SalmaNeural">
    <prosody rate="-15%" pitch="+4%">
      <break time="300ms"/>
      وَرِّيني <emphasis level="moderate">الأَحْمَر</emphasis>
      <break time="600ms"/>
    </prosody>
  </voice>
</speak>
```

- `rate="-15%"` (from `children.audio_rate_pct`, default 85, adjustable 60–110 per child).
- A **600 ms trailing pause** before the wait timer starts — the child needs the utterance to have clearly *ended* before they begin processing.
- Text is drawn from the **vowelised** column (`label_vowelised`). Unvowelised Arabic sent to a TTS engine mispronounces reliably; this is the single most common Arabic TTS bug.
- `<emphasis>` on the target word only.
- Loudness normalised to −16 LUFS across the whole corpus so no clip is startling.

### Caching

```python
cache_key = sha256(f"{voice}|{rate}|{pitch}|{ssml_text}".encode()).hexdigest()
```

Lookup order: `tts_cache` row → S3 → synthesise → store → return. Cache entries are **never evicted**; the whole corpus is ~35 MB. `hit_count` and `last_hit_at` are updated asynchronously so the read path stays single-query.

### Pre-generation

An ARQ job enumerates every utterance the product can say from a fixed inventory (§10.4 of [02](02-data-model.md)) — ~850 files. Runs on content publish, is idempotent, and reports missing assets as a **publish blocker**. Steady-state cache hit rate should exceed 92%; below that, an alert fires because it means dynamic text has crept into a hot path.

### Dynamic synthesis
Only two things are synthesised live: the child's name inserted into greetings, and the praise pool. Both are cached by hash on first use, so each is generated at most once per child, ever.

### Fallback ladder
Azure fails → ElevenLabs → cached generic variant of the same utterance → on-screen Arabic text with a "اقرأ لطفلك" (read to your child) badge. The session never stops for a TTS failure.

---

## 3. Automatic speech recognition

### Client-side capture

```
getUserMedia({ audio: { channelCount: 1, sampleRate: 16000,
                        echoCancellation: true, noiseSuppression: true,
                        autoGainControl: true } })
  → AudioWorklet
  → Silero VAD (WASM, @ricky0123/vad-web) for endpointing
  → MediaRecorder → audio/webm;codecs=opus @ 24 kbps
  → POST /voice/attempt (multipart, ~8–20 KB per utterance)
```

VAD parameters are retuned for this population:

| Parameter | Web default | Ours | Why |
|---|---|---|---|
| positive speech threshold | 0.50 | **0.35** | Quieter, breathier phonation is common |
| min speech frames | 3 | **2** | Utterances may be a single syllable |
| pre-speech pad | 200 ms | **500 ms** | Onsets are often soft and get clipped |
| redemption frames (silence to end) | 8 (~250 ms) | **24 (~750 ms)** | Longer internal pauses are normal; cutting at 250 ms truncates real attempts |
| hard max duration | — | **6 s** | Bounds cost and stops open-mic situations |

Getting the redemption window wrong is the most common way this feature fails: at the default, the recogniser cuts the child off mid-word and the platform tells them they were wrong.

### Provider interface

```python
class AsrProvider(Protocol):
    async def transcribe(self, audio: bytes, *, language: str = "ar-EG",
                         phrase_hints: list[str] | None = None,
                         n_best: int = 5) -> AsrResult: ...
```

- **Primary: Azure Speech `ar-EG`** with a **phrase list** containing the expected word plus its known child-speech variants. Phrase hints are worth more than any other single lever here — biasing the recogniser toward a 3-word hypothesis space transforms accuracy on short utterances.
- **Fallback / second opinion: OpenAI `gpt-4o-transcribe`** with an Arabic prompt hint. Used when Azure returns low confidence or empty.
- **Null provider** for tests, returning scripted transcripts.

### Scoring — lenient by construction

```python
def score_attempt(expected: Skill, asr: AsrResult) -> Verdict:
    best = 0.0
    for hyp in asr.n_best:                       # any hypothesis may match
        norm = normalize_ar(hyp.text)            # strip tashkeel, unify أإآا, ة→ه, ى→ي
        if norm == normalize_ar(expected.label_ar) or \
           norm == normalize_ar(expected.label_egy):
            return Verdict("accept", 1.0, hyp.text)
        best = max(best, phoneme_similarity(g2p(norm), expected.phonemes))

    if best >= 0.55:  return Verdict("accept",  best)
    if best >= 0.30:  return Verdict("retry",   best)
    return Verdict("unclear", best)
```

**`phoneme_similarity`** is a normalised weighted Levenshtein over an Arabic phoneme inventory, with a substitution-cost matrix that makes the *expected* error patterns cheap:

| Substitution class | Cost | Rationale |
|---|---|---|
| Emphatic ↔ plain (ص/س, ط/ت, ض/د, ظ/ذ, ق/ك) | 0.2 | Universally late-acquired in Arabic; not a comprehension failure |
| Fricative → stop (س→ت, ش→ت, ث→ت) | 0.3 | Stopping is the most common phonological process in this population |
| Cluster reduction (deleting one of CC) | 0.3 | Extremely common; the word is still targeted |
| Final consonant deletion | 0.3 | Common; word identity is usually preserved |
| Vowel length error (a/aː) | 0.15 | Almost never meaningful. **Reached as a deletion, not a substitution** — unvowelised Arabic writes no short vowels, so a shortened vowel arrives as an absent mater lectionis. `deletion_cost` prices a long vowel deleted between two consonants (CVC → CC) at this rate; an *inserted* long vowel stays at 0.8, because a cheap vowel insertion lets the aligner slide unrelated words together. Unreviewed addition — REVIEW-QUEUE #8 |
| Any other substitution | 1.0 | |
| Insertion / deletion elsewhere | 0.8 | |

Threshold **0.55** was chosen to sit deliberately on the permissive side. The cost of a false accept is that a child is praised for an approximation — which is exactly what a speech therapist would do. The cost of a false reject is that a child who tried is told they were wrong. These costs are not symmetric, and the threshold reflects that.

### The three verdicts

| Verdict | Nour says | Recorded as |
|---|---|---|
| `accept` | *"برافو! كده بالظبط"* | `correct` |
| `retry` (attempt 1 only) | *"قريب أوي! جرّب تاني معايا: الأَحْمَر"* + model audio | (no attempt row yet) |
| `unclear` (attempt 1 only) | *"مش سامعة كويس، قولها تاني"* — never "wrong" | (no attempt row yet) |
| **any verdict, attempt ≥ 2** | *"شاطر! سمعتك"* | `accepted_on_effort` |

**After two attempts the answer is always accepted.** The BKT weight of `accepted_on_effort` is low (it behaves like `prompt_level='partial_verbal'`), so measurement stays honest while the child's experience stays positive. This is the same honest-measurement / kind-presentation split as the prompt ladder in [04c](04c-components-learning.md).

### Caregiver override

A persistent, large button beside every expressive activity: **"قالها صح ✅"**. Tapping it records `caregiver_confirmed`, which BKT weights at 0.5 of an independent correct. This single control is what makes the feature usable for a child whose speech no machine can transcribe — and it is why assumption A3 (caregiver present) is structural.

Overrides are also the training signal: a `(audio, expected_word, caregiver_confirmed)` triple is exactly what a per-child reference model needs.

### Per-child adaptation (opt-in, `voice_retention`)

With consent, up to 20 caregiver-confirmed utterances per skill are retained for 30 days and embedded (`speechbrain/spkrec-ecapa` or an equivalent utterance encoder) into pgvector. On later attempts, cosine similarity against that child's own accepted references runs **in parallel with ASR**, and `max(asr_similarity, reference_similarity)` is used. For a child whose speech ASR cannot handle, this becomes the primary path within about two weeks of use.

Without consent, none of this runs and the caregiver override carries the feature. Both paths work.

---

## 4. Interfaces

| Method | Path | Notes |
|---|---|---|
| `POST` | `/voice/tts` | `{text, voice, rate}` → `{url, cached}`. Admin/preview only; runtime uses manifest URLs |
| `POST` | `/voice/attempt` | multipart `{audio, activity_id, attempt_no}` → `{verdict, similarity, heard, feedback_audio_url}` |
| `POST` | `/voice/override` | `{activity_id}` → records `caregiver_confirmed` |
| `POST` | `/voice/pregenerate` | admin, enqueues the batch job |
| `GET` | `/voice/health` | provider reachability + cache hit rate |

---

## 5. Privacy

| Step | Behaviour |
|---|---|
| Upload | TLS 1.3; audio held in memory, written to a temp file only if larger than 256 KB |
| Transcribe | Azure configured with **logging disabled** (must be set explicitly — it is not the default) |
| Retention | Deleted immediately after scoring **unless** `voice_retention` consent is granted |
| With consent | S3 `audio/{child_id}/{skill}/{uuid}.opus`, SSE-KMS, 30-day lifecycle rule |
| Transcript | `attempts.asr_heard` stores only the recognised word — never a full free-form transcript |
| Withdrawal | Withdrawing `voice_retention` purges the child's S3 prefix and pgvector rows within 5 minutes |
| Never | No audio, no transcript, and no embedding is ever sent to the LLM |

---

## 6. Latency budget

| Stage | Budget | Note |
|---|---|---|
| VAD endpoint detection | 750 ms | Deliberately long — see the table above |
| Upload (20 KB on 4G) | 300 ms | |
| ASR (Azure short-form) | 900 ms | |
| Scoring | 20 ms | Pure CPU |
| Feedback audio start | 200 ms | Pre-cached per verdict, so no synthesis on the hot path |
| **Total speech-end → feedback** | **≈ 2,200 ms** | Budget 2,500 ms |

If the total exceeds 3,000 ms, the client plays a pre-cached *"ثانية واحدة…"* filler so the child is never left in silence wondering whether anything is happening.

---

## 7. Failure modes

| Failure | Behaviour |
|---|---|
| Mic permission denied | Expressive activities are swapped for receptive equivalents for the whole session; a one-line caregiver explainer appears |
| No speech detected (6 s) | Counts as `no_response`, advances the prompt ladder — never a failure |
| ASR provider down | Immediate fallback to caregiver-confirmation mode; a small badge tells the caregiver why |
| Both providers down | Expressive tasks become "say it together" — model audio plays, caregiver confirms |
| Very noisy environment (SNR < 5 dB, measured client-side) | Suggest a quieter spot once, then switch to caregiver-confirmation for the session |
| Consent `voice_asr` absent | Expressive tasks never appear; the curriculum runs receptive-only and is complete on its own |

---

## 8. Definition of done

- 100% of the pre-generation corpus exists and plays; loudness within ±1 LUFS across the corpus.
- A native Egyptian Arabic speaker reviews all 88 skill labels and every instruction for pronunciation, and signs off. **This is a mandatory gate, not a nice-to-have** — TTS mispronunciation of a taught word teaches the wrong word.
- Scoring unit tests cover 60 hand-built (expected, heard) pairs including every substitution class, with expected verdicts agreed by a speech-language therapist.
- A 30-sample recorded set from real children (with consent, via the pilot centre) is used to calibrate the 0.55 threshold before launch, and the chosen value is recorded in an ADR.
- Every expressive activity has a verified tap-based equivalent.
