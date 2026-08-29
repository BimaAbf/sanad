"""CONTROL FIXTURE — the one file allowed to construct a provider client."""

from anthropic import AsyncAnthropic


def build_client() -> AsyncAnthropic:
    return AsyncAnthropic()
