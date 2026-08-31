"""The golden dataset and the fixture estate are ONE estate, not two that look alike.

The demo, the local adapters and the eval all read ``adapters/local/_fixtures.py``. The dataset
in ``eval/datasets/golden_cases.jsonl`` carries the EXPECTATIONS and a description of the inputs,
and this module holds the description equal to the fixtures. Without it the two drift, and the
self-test and the eval start failing in different ways for the same cause.
"""

from __future__ import annotations

import json

import pytest

from credit_portfolio_ews.adapters.local import (
    _fixtures,
)

from tests import REPO_ROOT

DATASET = REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"


def _cases() -> list[dict[str, object]]:
    rows = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert rows, "the golden dataset is empty, so every metric over it checks nothing"
    return rows


CASES = _cases()


def test_the_dataset_covers_every_obligor_in_the_estate() -> None:
    assert [str(case["obligor"]) for case in CASES] == list(_fixtures.OBLIGOR_IDS)


def test_every_case_id_is_unique() -> None:
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=[str(c["id"]) for c in CASES])
def test_the_described_inputs_match_the_fixture_estate(case: dict[str, object]) -> None:
    fixture = _fixtures.fixture_for(str(case["obligor"]))
    record = fixture.record
    assert record.name == case["name"]
    assert record.current_grade.value == case["current_grade"]
    assert record.clean_periods == case["clean_periods"]
    assert record.exposure_amount_minor == case["exposure_amount_minor"]
    assert len(fixture.terms) == case["covenants"]
    assert len(fixture.covenant_observations) == case["covenant_observations"]
    assert len(fixture.observations) == case["observations"]
    assert len(fixture.news) == case["news"]
    expected_days = case["arrears_days_past_due"]
    if expected_days is None:
        assert fixture.arrears is None
    else:
        assert fixture.arrears is not None
        assert fixture.arrears.days_past_due == expected_days


@pytest.mark.parametrize("case", CASES, ids=[str(c["id"]) for c in CASES])
def test_every_case_plants_an_identifier_the_redaction_check_can_look_for(
    case: dict[str, object],
) -> None:
    fixture = _fixtures.fixture_for(str(case["obligor"]))
    assert case["planted"] == fixture.planted_identifier
    assert fixture.planted_identifier, "a case with nothing planted proves nothing about masking"


def test_every_party_announces_itself_as_fictional() -> None:
    for case in CASES:
        assert "(FICTIONAL)" in str(case["name"])


def test_no_planted_identifier_looks_like_a_real_address() -> None:
    blob = " ".join(str(case["planted"]) for case in CASES)
    for real_looking in ("@gmail.", "@outlook.", "@yahoo.", "@hotmail."):
        assert real_looking not in blob
    assert ".example" in blob


def test_the_two_falsification_cases_are_present_and_say_what_they_pin() -> None:
    """Delete either and the metrics stop meaning anything, so their presence is a test."""
    notes = {str(case["obligor"]): str(case["note"]) for case in CASES}
    assert "MATERIALITY GATE" in notes["obl-kappa-010"]
    assert "MODEL AND FEED AUTHORITY" in notes["obl-lambda-011"]


def test_the_estate_holds_an_obligor_under_a_different_tenant() -> None:
    """So the cross-tenant refusal is a real path offline rather than a claim in a document."""
    assert _fixtures.ESTATE[_fixtures.OTHER_TENANT]
    assert _fixtures.belongs_to_another_tenant("obl-omega-999", _fixtures.TENANT) is True
    assert _fixtures.belongs_to_another_tenant("obl-alpha-001", _fixtures.TENANT) is False
