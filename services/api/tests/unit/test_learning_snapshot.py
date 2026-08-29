"""The `skill_states` counters.

`snapshot.py` is under `domain/`, so `tools/lint/coverage_gate.py` requires 100%
branch coverage on it. That is not bureaucracy here: these six numbers are what
a clinician console shows about how a child is doing, they have exactly one
right answer given the attempts, and a wrong one is indistinguishable from a
right one at a glance.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.modules.learning.domain.snapshot import (
    AttemptFact,
    is_correct,
    mean_latency,
    summarise,
    trailing_correct,
)

DAY = dt.datetime(2026, 3, 1, 9, 0, tzinfo=dt.UTC)


def fact(*, correct: bool, latency: int | None = 1000, offset_days: int = 0) -> AttemptFact:
    return AttemptFact(correct=correct, latency_ms=latency, at=DAY + dt.timedelta(days=offset_days))


class TestTrailingCorrect:
    def test_an_empty_history_has_no_streak(self) -> None:
        assert trailing_correct([]) == 0

    def test_every_attempt_correct_is_the_whole_length(self) -> None:
        assert trailing_correct([fact(correct=True)] * 4) == 4

    def test_it_stops_at_the_most_recent_miss(self) -> None:
        """The streak is the TRAILING run, not the longest one.

        Five correct, then a miss, then two correct is a streak of two. Reading
        it as five would tell a caregiver their child is on a run they are not
        on, and step the difficulty up underneath them.
        """
        history = [fact(correct=True)] * 5 + [fact(correct=False)] + [fact(correct=True)] * 2
        assert trailing_correct(history) == 2

    def test_a_miss_at_the_end_ends_the_streak(self) -> None:
        assert trailing_correct([fact(correct=True), fact(correct=False)]) == 0


class TestMeanLatency:
    def test_no_attempts_is_none(self) -> None:
        assert mean_latency([]) is None

    def test_a_client_that_never_reported_one_is_none_not_zero(self) -> None:
        """None and 0 must not collapse into each other.

        Zero would read as a child answering instantly, which is the opposite of
        "we do not know how long they took".
        """
        assert mean_latency([fact(correct=True, latency=None)] * 3) is None

    def test_it_averages_only_the_reported_ones(self) -> None:
        history = [
            fact(correct=True, latency=1000),
            fact(correct=True, latency=None),
            fact(correct=True, latency=2000),
        ]
        assert mean_latency(history) == 1500

    def test_it_rounds(self) -> None:
        history = [fact(correct=True, latency=1000), fact(correct=True, latency=1001)]
        assert mean_latency(history) == 1000  # 1000.5 -> banker's rounding


class TestSummarise:
    def test_an_empty_history_is_all_zeros_and_no_dates(self) -> None:
        snapshot = summarise([])
        assert snapshot.total_attempts == 0
        assert snapshot.total_correct == 0
        assert snapshot.consecutive_correct == 0
        assert snapshot.avg_latency_ms is None
        assert snapshot.first_seen_at is None
        assert snapshot.distinct_days == 0

    def test_it_counts_attempts_correct_and_the_streak(self) -> None:
        history = [
            fact(correct=True, offset_days=0),
            fact(correct=False, offset_days=0),
            fact(correct=True, offset_days=1),
            fact(correct=True, offset_days=1),
        ]
        snapshot = summarise(history)
        assert snapshot.total_attempts == 4
        assert snapshot.total_correct == 3
        assert snapshot.consecutive_correct == 2

    def test_first_seen_at_is_the_head_of_the_history(self) -> None:
        history = [fact(correct=True, offset_days=0), fact(correct=True, offset_days=5)]
        assert summarise(history).first_seen_at == DAY

    def test_distinct_days_counts_days_not_attempts(self) -> None:
        """Four attempts across two days is two days.

        `mastery_rule` requires two distinct days, so counting attempts here
        would let a single sitting satisfy a condition that exists precisely to
        rule a single sitting out.
        """
        history = [
            fact(correct=True, offset_days=0),
            fact(correct=True, offset_days=0),
            fact(correct=True, offset_days=3),
            fact(correct=True, offset_days=3),
        ]
        assert summarise(history).distinct_days == 2


class TestIsCorrect:
    @pytest.mark.parametrize("result", ["correct", "accepted_on_effort", "caregiver_confirmed"])
    def test_the_three_successes(self, result: str) -> None:
        """`accepted_on_effort` and `caregiver_confirmed` are successes.

        docs/04d: the first is the voice tier accepting a real attempt at a hard
        phoneme, the second is a caregiver overruling the recogniser. Scoring
        either as a failure would punish a child for the microphone.
        """
        assert is_correct(result) is True

    @pytest.mark.parametrize("result", ["incorrect", "no_response", "skipped"])
    def test_everything_else_is_not(self, result: str) -> None:
        assert is_correct(result) is False
