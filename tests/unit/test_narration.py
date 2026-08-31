"""The model boundary: five ways a draft is discarded, and the reason is always reported.

The model never produces a grade, a movement, a floor, a score, a weight, a threshold or a
boolean. What it produces is prose, and prose is checked: strict JSON, a non-empty citation list,
only sources the assessment carries, only figures the engine produced, and only the
classifications the engine itself named.

``memo_discarded_reason`` is populated rather than swallowed, so a validation failure is visible
on the surface instead of looking like a model that had nothing to say.
"""

from __future__ import annotations

import json

import pytest

from credit_portfolio_ews.domain.narration import (
    FACTS_MARKER,
    build_prompt,
    grounding_tokens,
    memo_facts,
    validate_memo,
)

from tests.contract.canonical import CANONICAL_REVIEW

ASSESSMENT = CANONICAL_REVIEW.assessment
SOURCE_ID = ASSESSMENT.citations[0].source_id


def _draft(**overrides: object) -> str:
    body = {
        "headline": "Watchlist review",
        "body": f"Composite {ASSESSMENT.composite_score} on obligor {ASSESSMENT.obligor_id}.",
        "cited_source_ids": [SOURCE_ID],
    }
    body.update(overrides)
    return json.dumps(body)


def test_the_prompt_keeps_the_instruction_and_the_data_in_separate_labelled_blocks() -> None:
    """Retrieved text must not be able to escalate the model's authority by looking like one."""
    prompt = build_prompt(ASSESSMENT)
    instruction, marker, facts = prompt.partition(FACTS_MARKER)
    assert marker == FACTS_MARKER
    assert "Restate ONLY the facts below" in instruction
    assert "do not recommend a grade of your own" in instruction
    assert facts.strip().startswith("- obligor:")


def test_the_prompt_carries_every_covenant_row_not_only_the_failures() -> None:
    labels = {label for label, _value in memo_facts(ASSESSMENT)}
    for test in ASSESSMENT.covenant_tests:
        assert f"covenant {test.covenant_id}" in labels


def test_the_grounding_set_is_derived_from_the_same_values_the_prompt_shows() -> None:
    tokens = grounding_tokens(ASSESSMENT)
    assert str(ASSESSMENT.composite_score) in tokens
    assert str(ASSESSMENT.effective_days_past_due) in tokens


def test_a_faithful_restatement_validates() -> None:
    memo, reason = validate_memo(_draft(), ASSESSMENT)
    assert memo is not None
    assert reason == ""
    assert memo.cited_source_ids == (SOURCE_ID,)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("not json at all", "not strict JSON"),
        ("[1, 2, 3]", "not a JSON object"),
    ],
)
def test_a_malformed_draft_is_discarded_with_a_reason(raw: str, expected: str) -> None:
    memo, reason = validate_memo(raw, ASSESSMENT)
    assert memo is None
    assert expected in reason


def test_a_draft_missing_a_headline_or_a_body_is_discarded() -> None:
    assert validate_memo(_draft(headline=42), ASSESSMENT)[0] is None
    assert validate_memo(_draft(body="   "), ASSESSMENT)[0] is None


def test_a_draft_citing_nothing_is_the_empty_retrieval_error_in_its_narration_form() -> None:
    memo, reason = validate_memo(_draft(cited_source_ids=[]), ASSESSMENT)
    assert memo is None
    assert "cited no source" in reason


def test_a_draft_citing_a_source_the_assessment_does_not_carry_is_discarded() -> None:
    memo, reason = validate_memo(_draft(cited_source_ids=["invented:1"]), ASSESSMENT)
    assert memo is None
    assert "invented:1" in reason


def test_a_fabricated_figure_is_discarded_and_named() -> None:
    """The load-bearing check: a figure the engine did not compute is a fabrication."""
    memo, reason = validate_memo(
        _draft(body="The composite score was 4242 on the reported basis."), ASSESSMENT
    )
    assert memo is None
    assert "4242" in reason


def test_a_classification_the_engine_did_not_produce_is_discarded() -> None:
    """The model may restate a grade; it may not reach one."""
    memo, reason = validate_memo(_draft(body="This obligor should be graded doubtful."), ASSESSMENT)
    assert memo is None
    assert "doubtful" in reason


def test_the_grades_the_engine_itself_produced_are_restatable() -> None:
    proposal = ASSESSMENT.proposal
    memo, reason = validate_memo(
        _draft(
            body=(
                f"The grade of record is {proposal.current_grade.value}; the band alone said "
                f"{proposal.band_grade.value} and the proposal is "
                f"{proposal.proposed_grade.value}."
            )
        ),
        ASSESSMENT,
    )
    assert memo is not None, reason


def test_the_offline_narrator_drives_the_real_validation_rather_than_dodging_it() -> None:
    from credit_portfolio_ews.adapters.local.generation import LocalMemoNarrator
    from credit_portfolio_ews.config import Settings

    raw = LocalMemoNarrator(Settings(profile="local")).generate(build_prompt(ASSESSMENT))
    memo, reason = validate_memo(raw, ASSESSMENT)
    assert memo is not None, reason
    assert memo.cited_source_ids, "the offline narrator must cite the assessment's own sources"


def test_the_ungrounded_narrator_exists_so_the_metric_can_be_shown_going_red() -> None:
    from credit_portfolio_ews.adapters.local.generation import UngroundedMemoNarrator
    from credit_portfolio_ews.config import Settings

    raw = UngroundedMemoNarrator(Settings(profile="local")).generate(build_prompt(ASSESSMENT))
    memo, reason = validate_memo(raw, ASSESSMENT)
    assert memo is None
    assert "4242" in reason
