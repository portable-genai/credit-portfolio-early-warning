"""Rule R8: a watchlist proposal is ROUTED to Hrz7, not left in a per-repo boolean.

This is the standing gate for the failure the rule exists to prevent. A repo can set
``requires_human_review = True``, pass every other test, and still auto-execute in practice
because nothing ever reads the flag. So the assertions here are about the ROUTING, not the flag:
a consequential proposal produces an outbound review, a clean obligor produces none, the payload
leaves redacted, the payload says a grade was NOT applied, and the on-prem placeholder refuses
rather than swallowing the escalation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from credit_portfolio_ews.adapters.gcp.review_router import (
    CloudReviewRouter,
)
from credit_portfolio_ews.adapters.local.review_router import (
    LocalReviewRouter,
)
from credit_portfolio_ews.adapters.onprem.review_router import (
    OnPremReviewRouter,
)
from credit_portfolio_ews.api.app import (
    app,
)
from credit_portfolio_ews.config import (
    Settings,
    build_container,
    build_review_service,
)

from tests.contract.canonical import CANONICAL_REVIEW
from tests.fixtures import sample_cases

_PERSONA = {"X-Dev-Persona": "auditor"}


def _settings(profile: str = "local") -> Settings:
    return Settings(profile=profile, audit_path=":memory:", tenant=sample_cases.TENANT)


def _review(obligor_id: str) -> object:
    container = build_container(_settings())
    return build_review_service(container).review(
        obligor_id,
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
    )


def test_a_routed_proposal_produces_an_outbound_review() -> None:
    router = LocalReviewRouter(_settings())
    ref = router.route(CANONICAL_REVIEW, maker=sample_cases.ACTOR)
    assert ref, "routing must return a reference, so the caller can record where it went"
    pending = router.outbox.pending()
    assert len(pending) == 1
    review = pending[0].review
    assert review.maker == sample_cases.ACTOR
    assert review.tenant == sample_cases.TENANT
    assert review.source_key, "a durable outbox needs an idempotency key"
    assert sample_cases.ESCALATING_OBLIGOR in review.case_ref


def test_the_payload_says_a_grade_was_proposed_and_never_applied() -> None:
    router = LocalReviewRouter(_settings())
    router.route(CANONICAL_REVIEW, maker=sample_cases.ACTOR)
    summary = router.outbox.pending()[0].review.summary
    assert "grade_applied=false" in summary
    assert "substandard" in summary


def test_a_non_performing_proposal_demands_dual_control() -> None:
    router = LocalReviewRouter(_settings())
    router.route(CANONICAL_REVIEW, maker=sample_cases.ACTOR)
    assert router.outbox.pending()[0].review.required_approvals == 2


def test_the_payload_is_redacted_before_it_leaves_the_process() -> None:
    """Hrz7 is a shared sink; a raw identifier must never reach the wire."""
    router = LocalReviewRouter(_settings())
    review = _review(sample_cases.PII_OBLIGOR)
    router.route(review, maker=sample_cases.ACTOR)
    wire = repr(router.outbox.pending()[0].review.to_payload())
    assert sample_cases.PLANTED_NRIC not in wire
    assert "REDACTED" in wire


def test_the_citation_locators_survive_the_wire_even_though_the_snippets_are_masked() -> None:
    """A masked locator is a claim nobody can trace, which defeats carrying provenance at all."""
    router = LocalReviewRouter(_settings())
    router.route(CANONICAL_REVIEW, maker=sample_cases.ACTOR)
    citations = router.outbox.pending()[0].review.citations
    assert citations, "an uncited proposal is not shippable"
    assert any(c.source_id.startswith("doc2:") for c in citations)


def test_the_managed_router_refuses_when_no_console_is_configured() -> None:
    """An escalation with nowhere to go must fail loudly, not return as if it were reviewed."""
    router = CloudReviewRouter(Settings(profile="gcp", audit_path=":memory:", review_url=""))
    with pytest.raises(RuntimeError, match="R8"):
        router.route(CANONICAL_REVIEW, maker=sample_cases.ACTOR)


def test_the_onprem_placeholder_refuses_rather_than_dropping_the_escalation() -> None:
    router = OnPremReviewRouter(_settings("onprem"))
    with pytest.raises(NotImplementedError, match="R8"):
        router.route(CANONICAL_REVIEW, maker=sample_cases.ACTOR)


def test_the_api_routes_the_escalation_in_the_same_request() -> None:
    """The serving path, not just the adapter: an escalation must not depend on a later job."""
    client = TestClient(app, client=("127.0.0.1", 50000))
    escalated = client.post(
        "/v1/watchlist-review",
        json={
            "obligor_id": sample_cases.ESCALATING_OBLIGOR,
            "as_of": sample_cases.AS_OF.isoformat(),
        },
        headers=_PERSONA,
    ).json()
    assert escalated["requires_human_review"] is True
    assert escalated["review_ref"], "an escalation with no routing reference went nowhere"
    assert escalated["grade_applied"] is False

    routine = client.post(
        "/v1/watchlist-review",
        json={
            "obligor_id": sample_cases.ROUTINE_OBLIGOR,
            "as_of": sample_cases.AS_OF.isoformat(),
        },
        headers=_PERSONA,
    ).json()
    assert routine["requires_human_review"] is False
    assert routine["review_ref"] == "", "a non-escalation must not manufacture a review"
