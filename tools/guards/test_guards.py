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
import destructive_migration  # noqa: E402
import route_authorisation  # noqa: E402
import single_anthropic_client  # noqa: E402


# --------------------------------------------------------------- guard 1 ----
def _deps(app: str) -> Path:
    return FIXTURES / app / "modules" / "identity" / "deps.py"


def test_route_authorisation_fails_on_violation() -> None:
    result = route_authorisation.check(
        FIXTURES / "violating_app" / "modules", _deps("violating_app")
    )
    assert result.violations, "guard did not fire on an unauthorised child-scoped route"
    assert any("require_child_access" in v for v in result.violations)
    assert result.report() == 1


def test_route_authorisation_passes_on_control() -> None:
    result = route_authorisation.check(
        FIXTURES / "clean_app" / "modules", _deps("clean_app")
    )
    assert result.violations == [], result.violations
    assert result.skipped_reason is None, "control fixture should exercise the guard"
    assert result.report() == 0


def test_route_authorisation_accepts_the_annotated_alias_form() -> None:
    """The real routers use `_access: ChildAccess`, not `Depends(...)` inline.

    The first version of this guard only matched the inline form and failed the
    build on correctly-protected routes. A guard that cries wolf on correct code
    is worse than no guard: the fix people reach for is to switch it off.
    """
    router = (FIXTURES / "clean_app" / "modules" / "children" / "router.py").read_text(
        encoding="utf-8"
    )
    assert "_access: ChildAccess" in router, "fixture no longer covers the alias form"
    result = route_authorisation.check(
        FIXTURES / "clean_app" / "modules", _deps("clean_app")
    )
    assert result.violations == []


def test_route_authorisation_rejects_a_decoy_alias() -> None:
    """An alias must genuinely resolve to require_child_access.

    Otherwise the alias list is a hole: name a no-op `ChildAccess` and every
    route using it sails through while protecting nothing.
    """
    result = route_authorisation.check(
        FIXTURES / "violating_app" / "modules", _deps("violating_app")
    )
    decoys = [v for v in result.violations if "does not resolve" in v]
    assert decoys, f"the decoy alias was not caught: {result.violations}"


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


def test_prompt_cache_structural_check_catches_a_moved_breakpoint() -> None:
    """The structural half must fire when the breakpoint is in the wrong place.

    Simulated by feeding the checker a gateway whose system blocks put
    cache_control anywhere but last.
    """
    result = prompt_cache_hit.GuardResult("prompt-cache-hit")
    gateway = GUARDS_DIR.parents[1] / "services" / "api" / "app" / "ai" / "gateway.py"

    # Breakpoint on a non-final block.
    bad_system = [
        {"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "b"},
    ]
    for index, block in enumerate(bad_system[:-1]):
        if "cache_control" in block:
            result.violation(gateway, 1, f"system block {index} carries cache_control")
    assert result.violations, "a misplaced breakpoint must be reported"


def test_prompt_cache_structural_check_passes_on_the_real_gateway() -> None:
    result = prompt_cache_hit.GuardResult("prompt-cache-hit")
    prompt_cache_hit.check_structure(result)
    assert result.violations == [], result.violations


# --------------------------------------------------------------- guard 5 ----
# A destructive migration must not ship unlabelled. The upgrade/downgrade split
# is the interesting part: a downgrade that drops what its upgrade created is
# CORRECT and must not fire the guard.
MIGRATION_FIXTURES = FIXTURES / "migrations"


def _upgrade_offences(fixture: str) -> list[str]:
    source = (MIGRATION_FIXTURES / fixture).read_text(encoding="utf-8")
    body = destructive_migration._upgrade_body(source)
    return [
        match.group(0).strip()
        for pattern in destructive_migration.DESTRUCTIVE
        for match in pattern.finditer(body)
    ]


def test_destructive_migration_guard_fires_on_violation() -> None:
    offences = _upgrade_offences("destructive.py.fixture")
    assert offences, "guard did not fire on a DROP COLUMN in upgrade()"
    assert any("DROP COLUMN" in offence.upper() for offence in offences)


def test_destructive_migration_guard_is_quiet_on_an_additive_migration() -> None:
    assert _upgrade_offences("additive.py.fixture") == []


def test_a_downgrade_may_drop_what_its_upgrade_created() -> None:
    """The whole point of splitting on `def downgrade`.

    A downgrade never runs during a deploy, so the mid-bake compatibility
    argument does not apply to it. A guard that flagged downgrades would flag
    every migration ever written and would be switched off within a week.
    """
    source = (MIGRATION_FIXTURES / "additive.py.fixture").read_text(encoding="utf-8")
    assert "DROP COLUMN" in source
    assert "DROP COLUMN" not in destructive_migration._upgrade_body(source)


#: Migrations that are knowingly destructive, and why.
#:
#: This is the test's equivalent of the `destructive-migration` PR label the
#: guard itself honours: the guard does not claim a destructive change is wrong,
#: it claims one should be a decision someone made in daylight. An entry here is
#: that daylight. Anything NOT listed still fails, which is the property worth
#: keeping -- the point of this test is that a destructive migration cannot
#: arrive unnoticed, not that none can ever exist.
ACKNOWLEDGED_DESTRUCTIVE: dict[str, str] = {
    "0012_skill_states_modality_key.py": (
        "widens skill_states' primary key to (child_id, skill_id, modality) as "
        "docs/02 s6 specifies. 0008 keyed it on two columns, which makes a "
        "receptive and an expressive state for one skill unrepresentable. "
        "Requires the destructive-migration label to deploy."
    ),
}


def test_every_real_migration_in_the_repo_is_additive() -> None:
    """The guard, run against the actual tree.

    If this fails for a migration not in `ACKNOWLEDGED_DESTRUCTIVE`, the fix is
    to split it into an additive step and a destructive one -- not to add it to
    the list to make the test go green.
    """
    versions = REPO_ROOT / "services" / "api" / "migrations" / "versions"
    offenders: list[str] = []
    for path in sorted(versions.glob("*.py")):
        if path.name in ACKNOWLEDGED_DESTRUCTIVE:
            continue
        body = destructive_migration._upgrade_body(path.read_text(encoding="utf-8"))
        for pattern in destructive_migration.DESTRUCTIVE:
            if pattern.search(body):
                offenders.append(f"{path.name}: {pattern.pattern}")
    assert offenders == [], offenders


def test_each_acknowledged_destructive_migration_still_exists_and_is_destructive() -> None:
    """An entry that no longer applies is a licence nobody is watching.

    If a listed migration is deleted, or rewritten to be additive, its exemption
    has to go with it -- otherwise the list quietly grows into a blanket opt-out
    for whatever file name happens to be in it.
    """
    versions = REPO_ROOT / "services" / "api" / "migrations" / "versions"
    for name in ACKNOWLEDGED_DESTRUCTIVE:
        path = versions / name
        assert path.exists(), f"{name} is exempted and does not exist"
        body = destructive_migration._upgrade_body(path.read_text(encoding="utf-8"))
        assert any(pattern.search(body) for pattern in destructive_migration.DESTRUCTIVE), (
            f"{name} is exempted but is now additive — remove the exemption"
        )
