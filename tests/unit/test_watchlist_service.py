"""The orchestration layer: the ONE redaction seam, the approval path, and rule R8.

The consequential decision is tested in ``test_early_warning.py``. This module tests what the
service does AROUND it, and in particular the property the whole redaction story rests on: the
masked projection is built ONCE, where the assessment leaves the service, and the SAME object is
handed to the audit write, the outbound payload and the model prompt.

Every sink assertion here observes the SINK, never a reconstruction of what should have reached
it. That distinction is the whole finding this module was rewritten around: the prompt check used
to call ``build_prompt(redacted_assessment(review.assessment))`` itself, which proves the masker
works and observes nothing the service did, so ``self._draft_memo(outbound)`` could be changed to
``self._draft_memo(assessment)`` and the guarantor's national id reached the model with the gate,
the eval and the demo self-test all green. The audit check read one field of the record
(``redacted_summary``) and was blind to the citation snippets beside it, which travelled from the
caller's projection untouched.

What is red against what, all observed rather than asserted:

* ``_draft_memo(outbound)`` -> ``_draft_memo(assessment)``: the recorded memo prompt carries the
  planted national id, and ``test_no_prompt_the_service_actually_sent_carries_the_planted_id``
  fails. Deleting the ``redact`` on the categorisation snippet fails the same test through the
  lambda case, which is a second, independent seam the old check could not see either.
* dropping the ``redact`` inside ``_record_audit``: caught by nothing on its own, deliberately.
  The projection above it is the control; that redact and the citation masking beside it are the
  belt-and-braces the outbound payload has always had, and the record test below reads the WHOLE
  record so a leak through ANY field of it is visible rather than only through the summary.
"""

from __future__ import annotations

import json

import pytest

from credit_portfolio_ews.adapters.local.generation import (
    RecordingNarrator,
)
from credit_portfolio_ews.config import (
    Container,
    Settings,
    build_container,
    build_review_service,
)
from credit_portfolio_ews.domain.errors import (
    ObligorNotFoundError,
)
from credit_portfolio_ews.domain.models import (
    Movement,
    WatchGrade,
)
from credit_portfolio_ews.domain.watchlist_service import (
    CATEGORISE_MARKER,
    WatchlistReviewService,
    redacted_assessment,
)
from credit_portfolio_ews.ports.tenancy import (
    CrossTenantError,
)

from tests.conftest import local_settings
from tests.fixtures import sample_cases


def _service(**overrides: object) -> WatchlistReviewService:
    return build_review_service(build_container(local_settings(**overrides)))


def _spied_service(container: Container) -> tuple[WatchlistReviewService, RecordingNarrator]:
    """The REAL service with the bound narrator wrapped, so the prompts are the ones it sent."""
    spy = RecordingNarrator(container.generation)
    service = WatchlistReviewService(
        audit=container.audit,
        covenant_terms=container.covenant_terms,
        portfolio_feed=container.portfolio_feed,
        adverse_media=container.adverse_media,
        grade_registry=container.grade_registry,
        generation=spy,
        review_router=container.review_router,
        tracer=container.tracer,
    )
    return (service, spy)


def _review(obligor_id: str, service: WatchlistReviewService | None = None) -> object:
    return (service or _service()).review(
        obligor_id,
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
    )


# --------------------------------------------------------------------------------------- #
# The redaction seam
# --------------------------------------------------------------------------------------- #
def test_the_planted_identifier_is_in_the_raw_assessment_so_the_checks_below_assert_something() -> (
    None
):
    """A vacuous redaction test is worse than none: it reports a control that is not exercised."""
    review = _service().review(
        sample_cases.PII_OBLIGOR,
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
    )
    raw = " ".join(test.detail for test in review.assessment.covenant_tests)
    assert sample_cases.PLANTED_NRIC in raw, (
        "the guarantor identifier never reached the assessment, so every masking assertion "
        "below would pass for the wrong reason"
    )


def test_the_planted_identifier_never_reaches_the_immutable_record() -> None:
    """The WHOLE record, not one field of it: a record is unwritable once it is chained.

    Reading only ``redacted_summary`` was a field-shaped blind spot. The citations beside it are
    quoted upstream text, they are where an address or an identifier actually turns up, and they
    reached the sink from the caller's projection with nothing in the repo looking at them.
    """
    settings = local_settings()
    container = build_container(settings)
    build_review_service(container).review(
        sample_cases.PII_OBLIGOR,
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
    )
    record = container.audit.log.read_all()[-1]
    whole = json.dumps(record, sort_keys=True, default=str)
    assert sample_cases.PLANTED_NRIC not in whole
    assert "REDACTED" in str(record["redacted_summary"])
    assert container.audit.log.verify_chain().ok


def test_no_citation_snippet_on_the_record_carries_an_address_the_evidence_did() -> None:
    """The second sink field, over the obligor whose EVIDENCE plants the address."""
    container = build_container(local_settings())
    build_review_service(container).review(
        "obl-lambda-011",
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
    )
    planted = sample_cases.fixture("obl-lambda-011").planted_identifier
    assert any(planted in item.snippet for item in sample_cases.fixture("obl-lambda-011").news), (
        "the address is not in the evidence, so the assertion below would pass for no reason"
    )
    record = container.audit.log.read_all()[-1]
    snippets = [str(citation["snippet"]) for citation in record["citations"]]
    assert snippets, "a record with no citations proves nothing about masking them"
    assert not any(planted in snippet for snippet in snippets)
    assert any("REDACTED" in snippet for snippet in snippets)


def test_the_audit_record_reconstructs_the_decision_without_the_source_systems() -> None:
    settings = local_settings()
    container = build_container(settings)
    review = build_review_service(container).review(
        sample_cases.ESCALATING_OBLIGOR,
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
    )
    record = container.audit.log.read_all()[-1]
    summary = str(record["redacted_summary"])
    assert review.assessment.proposal.proposed_grade.value in summary
    assert review.assessment.proposal.current_grade.value in summary
    assert str(review.assessment.composite_score) in summary
    for floor in review.assessment.proposal.applied_floors:
        assert floor in summary
    for reason in review.assessment.review_reasons:
        assert reason in summary
    assert record["actor"] == sample_cases.ACTOR


def test_no_prompt_the_service_actually_sent_carries_the_planted_id() -> None:
    """What the model was allowed to SEE is exactly what it is allowed to SAY back.

    The port is WRAPPED and the assertion is over what came past it. Rebuilding the prompt here,
    which is what this check used to do, tests ``build_prompt`` and ``redacted_assessment`` and
    is blind to which object the service handed the port.
    """
    container = build_container(local_settings())
    service, spy = _spied_service(container)
    review = service.review(
        sample_cases.PII_OBLIGOR,
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
    )
    assert review.memo_body, "no memo was drafted, so no prompt was sent and this asserts nothing"
    assert spy.prompts, "the model boundary was never crossed"
    assert sample_cases.PLANTED_NRIC not in spy.sent()
    memo_prompts = [p for p in spy.prompts if not p.startswith(CATEGORISE_MARKER)]
    assert len(memo_prompts) == 1, "the memo is drafted once per routed proposal"
    assert "REDACTED" in memo_prompts[0], (
        "the clause text never reached the prompt at all, so the masking assertion above would "
        "pass for the wrong reason"
    )


def test_no_categorisation_prompt_carries_the_address_the_snippet_plants() -> None:
    """The other model job, masked by a different line, and no other check watches it.

    The categorisation prompt quotes an adverse-media snippet, which is untrusted upstream text
    and exactly where a contact address arrives. It is masked in ``_categorise`` rather than by
    the projection, so a memo-only prompt check leaves it unguarded.
    """
    container = build_container(local_settings())
    service, spy = _spied_service(container)
    service.review(
        "obl-lambda-011",
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
    )
    fixture = sample_cases.fixture("obl-lambda-011")
    planted = fixture.planted_identifier
    assert any(planted in item.snippet for item in fixture.news), (
        "the address is not in the evidence the model is shown, so this proves nothing"
    )
    categorisations = [p for p in spy.prompts if p.startswith(CATEGORISE_MARKER)]
    assert len(categorisations) == len(fixture.news), "every confirmed item is categorised"
    assert planted not in spy.sent()
    assert any("REDACTED" in prompt for prompt in categorisations), (
        "the snippet never reached a prompt, so the masking assertion above is vacuous"
    )


def test_the_locator_survives_masking_even_though_the_snippet_does_not() -> None:
    """Mask the snippet, never the locator: a masked locator is a claim nobody can trace."""
    review = _review(sample_cases.PII_OBLIGOR)
    masked = redacted_assessment(review.assessment)
    assert {c.source_id for c in masked.citations} == {
        c.source_id for c in review.assessment.citations
    }
    assert any(c.source_id.startswith("doc2:") for c in masked.citations)


def test_masking_changes_no_figure_no_grade_and_no_join_key() -> None:
    review = _review(sample_cases.ESCALATING_OBLIGOR)
    raw, masked = review.assessment, redacted_assessment(review.assessment)
    assert masked.composite_score == raw.composite_score
    assert masked.proposal == raw.proposal
    assert masked.obligor_id == raw.obligor_id
    assert masked.data_completeness == raw.data_completeness
    assert [t.covenant_id for t in masked.covenant_tests] == [
        t.covenant_id for t in raw.covenant_tests
    ]


# --------------------------------------------------------------------------------------- #
# Rule R8 and the approval path
# --------------------------------------------------------------------------------------- #
def test_a_consequential_proposal_is_routed_inside_the_same_call() -> None:
    review = _review(sample_cases.ESCALATING_OBLIGOR)
    assert review.assessment.requires_human_review is True
    assert review.review_ref, "setting the flag is not the escalation; routing is"
    assert review.grade_applied is False


def test_a_clean_obligor_produces_no_review_and_no_routing() -> None:
    review = _review(sample_cases.ROUTINE_OBLIGOR)
    assert review.assessment.requires_human_review is False
    assert review.review_ref == "", "a manufactured review trains a committee to rubber-stamp"


def test_moving_into_a_non_performing_grade_demands_dual_control() -> None:
    review = _review(sample_cases.ESCALATING_OBLIGOR)
    assert review.assessment.proposal.proposed_grade is WatchGrade.SUBSTANDARD
    assert review.required_approvals == 2


def test_moving_out_of_a_non_performing_grade_demands_dual_control_too() -> None:
    review = _review("obl-eta-007")
    assert review.assessment.proposal.movement is Movement.UPGRADE
    assert review.required_approvals == 2


def test_an_ordinary_proposal_needs_one_approval() -> None:
    review = _review("obl-beta-002")
    assert review.assessment.proposal.proposed_grade is WatchGrade.SPECIAL_MENTION
    assert review.required_approvals == 1


# --------------------------------------------------------------------------------------- #
# The memo, and what happens when it cannot be drafted
# --------------------------------------------------------------------------------------- #
def test_a_routed_proposal_carries_a_validated_memo() -> None:
    review = _review(sample_cases.ESCALATING_OBLIGOR)
    assert review.memo_headline and review.memo_body
    assert review.memo_discarded_reason == ""


def test_a_clean_obligor_is_not_narrated_at_all() -> None:
    review = _review(sample_cases.ROUTINE_OBLIGOR)
    assert (review.memo_headline, review.memo_body, review.memo_discarded_reason) == ("", "", "")


def test_an_ungrounded_draft_is_discarded_and_the_reason_is_reported() -> None:
    """A validation failure must be visible, not look like a model with nothing to say."""
    from credit_portfolio_ews.adapters.local.generation import UngroundedMemoNarrator

    container = build_container(local_settings())
    service = WatchlistReviewService(
        audit=container.audit,
        covenant_terms=container.covenant_terms,
        portfolio_feed=container.portfolio_feed,
        adverse_media=container.adverse_media,
        grade_registry=container.grade_registry,
        generation=UngroundedMemoNarrator(container.settings),
        review_router=container.review_router,
        tracer=container.tracer,
    )
    review = _review(sample_cases.ESCALATING_OBLIGOR, service)
    assert review.memo_body == ""
    assert "figures the engine did not produce" in review.memo_discarded_reason
    assert review.assessment.requires_human_review is True, "the assessment is complete anyway"


def test_an_unbound_narration_seam_costs_a_paragraph_and_never_a_decision() -> None:
    """The on-premises model placeholder refuses, and the assessment is still complete."""
    container = build_container(local_settings())
    onprem = build_container(Settings(profile="onprem", tenant=sample_cases.TENANT))
    service = WatchlistReviewService(
        audit=container.audit,
        covenant_terms=container.covenant_terms,
        portfolio_feed=container.portfolio_feed,
        adverse_media=container.adverse_media,
        grade_registry=container.grade_registry,
        generation=onprem.generation,
        review_router=container.review_router,
        tracer=container.tracer,
    )
    review = _review(sample_cases.ESCALATING_OBLIGOR, service)
    assert "no narration seam is bound" in review.memo_discarded_reason
    assert review.assessment.proposal.proposed_grade is WatchGrade.SUBSTANDARD
    assert review.review_ref


# --------------------------------------------------------------------------------------- #
# Reads are tenant-scoped, and the two statuses cannot be used to enumerate a book
# --------------------------------------------------------------------------------------- #
def test_an_obligor_under_another_tenant_is_403_and_never_404() -> None:
    with pytest.raises(CrossTenantError):
        _review(sample_cases.FOREIGN_OBLIGOR)


def test_an_obligor_the_registry_does_not_hold_is_404_and_never_a_default_record() -> None:
    with pytest.raises(ObligorNotFoundError):
        _review(sample_cases.UNKNOWN_OBLIGOR)


def test_the_resolved_period_and_date_are_echoed_so_a_stored_answer_is_self_describing() -> None:
    review = _review(sample_cases.ESCALATING_OBLIGOR)
    assert review.assessment.test_period == sample_cases.TEST_PERIOD
    assert review.assessment.as_of == sample_cases.AS_OF


def test_the_news_lookback_is_clamped_to_the_policy_maximum() -> None:
    service = _service()
    wide = service.review(
        "obl-lambda-011",
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
        news_lookback_days=10_000,
    )
    assert wide.assessment.composite_score == 20, "a caller cannot widen the retrieval window"


def test_the_model_categorises_only_what_the_feed_already_confirmed() -> None:
    """The feed owns entity resolution; the model owns the category, from a closed enum."""
    confirmed = _review("obl-lambda-011")
    fired = {signal.rule_id for signal in confirmed.assessment.signals}
    assert {"ext-insolvency", "ext-litigation", "ext-rating-downgrade"} <= fired

    unconfirmed = _review("obl-iota-009")
    assert unconfirmed.assessment.signals == ()
    assert unconfirmed.assessment.confirmation_requested == ("news-iota-01",)
