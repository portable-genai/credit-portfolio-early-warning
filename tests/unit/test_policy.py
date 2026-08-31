"""The bank-owned policy: the shipped block IS the shipped defaults, and the validator refuses.

Two failures this module exists to prevent:

1. the settings file and the dataclass drift, so an operator reads one set of numbers and the
   engine runs another. The equality test below is the standing gate;
2. a configuration that would silently change what the engine MEANS is accepted at load and only
   discovered when a proposal looks odd. ``validate_policy`` refuses each of those at LOAD, and
   every refusal here is written as a mutation of the shipped policy, so the check is shown going
   red against the exact edit somebody would make.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
import yaml

from credit_portfolio_ews.domain.models import (
    SignalFamily,
    WatchGrade,
)
from credit_portfolio_ews.domain.policy import (
    DEFAULT_POLICY,
    DEFAULT_SIGNAL_RULES,
    FLOOR_RULE_IDS,
    load_policy,
    validate_policy,
)

from tests import REPO_ROOT

_SETTINGS = REPO_ROOT / "config" / "settings.yaml"


def _shipped_block() -> dict[str, object]:
    loaded = yaml.safe_load(_SETTINGS.read_text(encoding="utf-8"))
    block = loaded.get("policy")
    assert isinstance(block, dict), "the settings file ships no policy block to read"
    return block


def test_the_shipped_block_parses_into_exactly_the_shipped_code_defaults() -> None:
    """One set of numbers, two homes, and they must agree or one of them is decoration."""
    assert load_policy(_shipped_block()) == DEFAULT_POLICY


def test_the_shipped_block_mirrors_every_default_rule_verbatim() -> None:
    parsed = load_policy(_shipped_block())
    assert parsed.signal_rules == DEFAULT_SIGNAL_RULES
    assert len(parsed.signal_rules) == len({rule.rule_id for rule in parsed.signal_rules})


def test_an_absent_block_takes_the_shipped_defaults() -> None:
    assert load_policy(None) is DEFAULT_POLICY
    assert load_policy({}) is DEFAULT_POLICY


def test_a_present_block_naming_an_empty_rule_list_is_honoured_as_empty() -> None:
    """The operator wrote it. Absence and emptiness are different states everywhere else too."""
    policy = load_policy({"signal_rules": []})
    assert policy.signal_rules == ()
    assert policy.family_caps == DEFAULT_POLICY.family_caps, "unnamed keys keep their defaults"


def test_the_shipped_policy_is_valid() -> None:
    assert validate_policy(DEFAULT_POLICY) == ()


def test_a_non_monotonic_band_ladder_is_refused_at_load() -> None:
    broken = replace(
        DEFAULT_POLICY,
        band_floors=(
            (0, WatchGrade.PASS),
            (70, WatchGrade.SUBSTANDARD),
            (35, WatchGrade.SPECIAL_MENTION),
        ),
    )
    assert any("strictly increasing" in reason for reason in validate_policy(broken))


def test_a_ladder_that_does_not_start_at_pass_is_refused() -> None:
    broken = replace(DEFAULT_POLICY, band_floors=((10, WatchGrade.SPECIAL_MENTION),))
    assert any("must start at (0, pass)" in reason for reason in validate_policy(broken))


@pytest.mark.parametrize("family", [SignalFamily.EXTERNAL, SignalFamily.PROCESS])
def test_a_bounded_family_may_not_reach_the_first_adverse_band_alone(
    family: SignalFamily,
) -> None:
    """The falsification case for model and feed authority, expressed as configuration.

    Raise the external cap to 44 and the three-confirmed-item obligor starts proposing a
    downgrade driven entirely by categorised media. This is the load-time refusal that stops it.
    """
    lifted = replace(DEFAULT_POLICY, family_caps={**DEFAULT_POLICY.family_caps, family: 44})
    reasons = validate_policy(lifted)
    assert any("must not be able to classify alone" in reason for reason in reasons)
    with pytest.raises(ValueError, match="not loadable"):
        load_policy({"family_caps": {family.value: 44}})


def test_the_financial_and_behavioural_caps_are_deliberately_not_bounded_that_way() -> None:
    """They measure the OBLIGOR'S credit, so they are allowed to classify. Only the model-
    influenced family and the family measuring our own file are held below the band."""
    lifted = replace(
        DEFAULT_POLICY,
        family_caps={**DEFAULT_POLICY.family_caps, SignalFamily.FINANCIAL: 80},
    )
    assert validate_policy(lifted) == ()


def test_an_inverted_arrears_clock_is_refused() -> None:
    broken = replace(DEFAULT_POLICY, sicr_days_past_due=120)
    assert any("sicr_days_past_due" in reason for reason in validate_policy(broken))


def test_an_upgrade_notch_cap_below_one_is_refused() -> None:
    broken = replace(DEFAULT_POLICY, max_upgrade_notches=0)
    assert any("max_upgrade_notches" in reason for reason in validate_policy(broken))


def test_an_upgrade_evidence_floor_below_the_general_one_is_refused() -> None:
    """A thinner file must never justify an improvement than a downgrade needs."""
    broken = replace(DEFAULT_POLICY, upgrade_min_data_completeness=0.10)
    assert any("upgrade_min_data_completeness" in reason for reason in validate_policy(broken))


def test_an_empty_required_metric_list_is_refused() -> None:
    """A completeness metric measured over zero required items reports success over nothing."""
    broken = replace(DEFAULT_POLICY, required_metrics=())
    assert any("required_metrics" in reason for reason in validate_policy(broken))
    with pytest.raises(ValueError, match="required_metrics"):
        load_policy({"required_metrics": []})


# --------------------------------------------------------------------------------------- #
# Coverage: a mapping the engine INDEXES must be complete, and the refusal belongs at load
# --------------------------------------------------------------------------------------- #
_PARTIAL_BLOCKS: list[tuple[str, dict[str, object]]] = [
    ("family_caps", {"family_caps": {}}),
    ("family_caps", {"family_caps": {"external": 20}}),
    ("floor_grades", {"floor_grades": {"floor-covenant-breach": "special_mention"}}),
    (
        "covenant_weights",
        {"covenant_weights": {"breach": {"weight": 30, "severity": "high", "family": "financial"}}},
    ),
    ("arrears_weights", {"arrears_weights": {"sicr": {"weight": 15, "severity": "high"}}}),
    (
        "review_clock_weights",
        {"review_clock_weights": {"overdue": {"weight": 12, "severity": "medium"}}},
    ),
]


_PARTIAL_IDS = [f"{name}-{index}" for index, (name, _) in enumerate(_PARTIAL_BLOCKS)]


@pytest.mark.parametrize(("named", "block"), _PARTIAL_BLOCKS, ids=_PARTIAL_IDS)
def test_a_partial_mapping_is_refused_at_load_rather_than_at_the_first_request(
    named: str, block: dict[str, object]
) -> None:
    """Each of these is one row of a settings file, edited the way an operator edits one.

    A present sub-block REPLACES the shipped mapping rather than merging into it, so naming one
    row ships every other row as absent. Each of these loaded cleanly before the coverage check
    existed, and then: an empty ``family_caps`` took obl-delta-004's composite from 65 to 0 and
    its band from special mention to pass with no error anywhere, because a missing cap reads as
    zero; the other four raised ``KeyError`` inside the engine on the first obligor that reached
    the missing row. SPEC.md says this validator refuses at LOAD, and now it does.
    """
    with pytest.raises(ValueError, match=named):
        load_policy(block)


def test_a_complete_mapping_is_honoured_so_the_refusal_is_about_coverage_not_presence() -> None:
    """A retune of every row must still load, or the check is refusing configuration itself."""
    lowered = {
        key: "special_mention" for key in ("floor-covenant-breach", "floor-arrears-sicr")
    } | {
        key: "substandard"
        for key in ("floor-covenant-breach-repeat", "floor-arrears-default", "floor-restructured")
    }
    policy = load_policy({"floor_grades": {**lowered, "floor-arrears-severe": "doubtful"}})
    assert policy.floor_grades["floor-restructured"] is WatchGrade.SUBSTANDARD
    assert policy.family_caps == DEFAULT_POLICY.family_caps, "unnamed blocks keep their defaults"


def test_every_floor_the_engine_can_apply_is_priced_by_the_shipped_policy() -> None:
    """The floor id list and the floor-grade table have one home each and must agree."""
    assert set(FLOOR_RULE_IDS) == set(DEFAULT_POLICY.floor_grades)


def test_every_default_rule_carries_the_policy_row_it_derives_from() -> None:
    for rule in DEFAULT_SIGNAL_RULES:
        assert rule.citation.source_id == f"ews-policy:{rule.rule_id}"
