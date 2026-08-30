"""Offline TTS render pipeline. NOT part of the API service.

docs/12 §Δ2. After the stack revision there is no runtime TTS anywhere in the
child's path: the whole audio surface of the product is a batch render that runs
on a rented GPU for about two hours and is then shut down.

    VoxCPM2 + the Nour LoRA adapter
        → render the ~850-item inventory at 48 kHz
        → loudness-normalise to -16 LUFS
        → encode to 48 kbps Opus
        → upload to Cloudflare R2, write tts_cache rows
        → shut the GPU down. Runtime cost from then on: $0.

This package holds the parts of that pipeline that are pure and testable — the
plan, the idempotency rule, the loudness gate and the publish report. The model
call itself is behind `Renderer`, which the API never imports and CI never runs.
"""
