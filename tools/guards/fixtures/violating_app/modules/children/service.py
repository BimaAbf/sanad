"""VIOLATION FIXTURE — single-anthropic-client guard must FAIL on this file."""

from anthropic import Anthropic


def summarise(text: str) -> str:
    # Bypasses app/ai/gateway.py, and with it redaction, guardrails and budget.
    client = Anthropic()
    return str(client)
