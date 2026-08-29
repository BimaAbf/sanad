"""Each guard must fire on its violation fixture and stay quiet on its control.

This is the test that makes the guards trustworthy. Without it a guard that
silently matches nothing looks identical, in CI, to a guard that passes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

GUARDS_DIR = Path(__file__).resolve().parent
FIXTURES = GUARDS_DIR / "fixtures"
REPO_ROOT = GUARDS_DIR.parents[1]

sys.path.insert(0, str(GUARDS_DIR))

import prompt_cache_hit  # noqa: E402
import required_guardrail_layer  # noqa: E402
import route_authorisation  # noqa: E402
import single_anthropic_client  # noqa: E402


# --------------------------------------------------------------- guard 1 ----
def test_route_authorisation_fails_on_violation() -> None:
    result = route_authorisation.check(FIXTURES / "violating_app" / "modules")
    assert result.violations, "guard did not fire on an unauthorised child-scoped route"
    assert "require_child_access" in result.violations[0]
    assert result.report() == 1


def test_route_authorisation_passes_on_control() -> None:
    result = route_authorisation.check(FIXTURES / "clean_app" / "modules")
    assert result.violations == []
    assert result.skipped_reason is None, "control fixture should exercise the guard"
    assert result.report() == 0


# --------------------------------------------------------------- guard 2 ----
def test_single_anthropic_client_fails_on_violation() -> None:
    app = FIXTURES / "violating_app"
    result = single_anthropic_client.check(app, app / "ai" / "gateway.py")
    assert result.violations, "guard did not fire on a client built outside the gateway"
    assert "Anthropic()" in result.violations[0]
    assert result.report() == 1


def test_single_anthropic_client_passes_on_control() -> None:
    app = FIXTURES / "clean_app"
    result = single_anthropic_client.check(app, app / "ai" / "gateway.py")
    assert result.violations == []
    assert result.report() == 0


# --------------------------------------------------------------- guard 3 ----
def test_prompt_cache_hit_fails_on_a_recorded_miss() -> None:
    result = prompt_cache_hit.check(FIXTURES / "cache_fixtures" / "miss.json")
    assert result.violations, "guard did not fire on cache_read_input_tokens == 0"
    assert "cache_read_input_tokens" in result.violations[0]
    assert result.report() == 1


def test_prompt_cache_hit_passes_on_a_recorded_hit() -> None:
    result = prompt_cache_hit.check(FIXTURES / "cache_fixtures" / "hit.json")
    assert result.violations == []
    assert result.skipped_reason is None
    assert result.report() == 0


# --------------------------------------------------------------- guard 4 ----
def test_required_guardrail_layer_fails_on_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        required_guardrail_layer, "GUARDRAILS_ROOT", FIXTURES / "violating_app" / "guardrails"
    )
    result = required_guardrail_layer.check()
    assert result.violations, "guard did not fire on pgee_report missing a layer"
    assert "NumericEqualityLayer" in result.violations[0]
    assert result.report() == 1


def test_required_guardrail_layer_passes_on_control(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        required_guardrail_layer, "GUARDRAILS_ROOT", FIXTURES / "clean_app" / "guardrails"
    )
    result = required_guardrail_layer.check()
    assert result.violations == []
    assert result.skipped_reason is None
    assert result.report() == 0


# ------------------------------------------------------------- stylelint ----
def test_stylelint_bans_physical_properties() -> None:
    """The stylelint rule must fail on `margin-left: 4px` (P00 acceptance)."""
    common = [
        "--config",
        str(REPO_ROOT / ".stylelintrc.mjs"),
        "--custom-syntax=postcss",
    ]
    violating = subprocess.run(  # noqa: S603
        ["pnpm", "exec", "stylelint", *common, str(FIXTURES / "physical-properties.css.fixture")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        shell=sys.platform == "win32",
        check=False,
    )
    assert violating.returncode != 0, "stylelint accepted a physical property"
    # stylelint reports findings on stderr.
    assert "margin-left" in violating.stdout + violating.stderr
    assert "margin-inline-start" in violating.stdout + violating.stderr

    compliant = subprocess.run(  # noqa: S603
        ["pnpm", "exec", "stylelint", *common, str(FIXTURES / "logical-properties.css.fixture")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        shell=sys.platform == "win32",
        check=False,
    )
    assert compliant.returncode == 0, compliant.stdout + compliant.stderr


# --------------------------------------------------- the real tree, today ----
def test_every_guard_runs_against_the_real_tree() -> None:
    """No guard may crash on the actual repository, in whatever state it is."""
    for module in (
        route_authorisation,
        single_anthropic_client,
        prompt_cache_hit,
        required_guardrail_layer,
    ):
        result = module.check()
        assert result.report() == 0, f"{result.name} is failing on the real tree"
