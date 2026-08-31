"""A span carries structure, never content, and this is the test that keeps it that way.

A trace backend is not the WORM audit trail. It has no redaction stage, a wider read
audience and no retention rule written against a regulator's requirement, so anything
content-shaped that reaches a span attribute has left the boundary that redaction exists to
hold, and left it silently: nothing fails, nothing logs, and the leak is discovered by
whoever opens the trace viewer.

The pressure this resists is real and reasonable-sounding. Someone debugging a slow or wrong
review adds "just the covenant clause" to the span, because that is the one thing the trace
does not tell them. The allowlist test below is what turns that from a quiet regression into a
failed build.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from credit_portfolio_ews.config import (
    build_container,
)
from credit_portfolio_ews.domain.watchlist_service import (
    REVIEW_SPAN,
    WatchlistReviewService,
)

from tests.conftest import local_settings
from tests.fixtures import sample_cases

#: The complete set of attribute keys a review span may carry. Adding to this is a decision
#: about what leaves the trust boundary, so it is made here rather than at the call site.
_ALLOWED_ATTRIBUTES = {"action", "actor"}


class _RecordingTracer:
    """Captures span names and attributes. Satisfies ObservabilityTracerPort structurally."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        self.spans.append((name, dict(attributes)))
        yield

    def record_token_usage(self, usage: object, model: str) -> None:
        return None


def _review(obligor_id: str = sample_cases.PII_OBLIGOR) -> _RecordingTracer:
    tracer = _RecordingTracer()
    container = build_container(local_settings())
    service = WatchlistReviewService(
        audit=container.audit,
        covenant_terms=container.covenant_terms,
        portfolio_feed=container.portfolio_feed,
        adverse_media=container.adverse_media,
        grade_registry=container.grade_registry,
        generation=container.generation,
        review_router=container.review_router,
        tracer=tracer,  # type: ignore[arg-type]
    )
    service.review(
        obligor_id,
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
    )
    return tracer


def test_one_review_opens_exactly_one_span() -> None:
    tracer = _review()
    assert [name for name, _ in tracer.spans] == [REVIEW_SPAN]


def test_the_span_carries_the_structural_attributes_an_operator_needs() -> None:
    _, attributes = _review().spans[0]
    assert attributes["action"] == "watchlist_review"
    assert attributes["actor"] == sample_cases.ACTOR


def test_the_attribute_keys_are_a_fixed_allowlist() -> None:
    """Widening this set is a trust-boundary decision, so it cannot happen by accident."""
    for _, attributes in _review().spans:
        assert set(attributes) == _ALLOWED_ATTRIBUTES, (
            "a new span attribute appeared; confirm it is structural, then widen "
            "_ALLOWED_ATTRIBUTES here deliberately"
        )


def test_no_attribute_value_carries_a_covenant_clause_or_a_planted_identifier() -> None:
    emitted = " ".join(value for _, attributes in _review().spans for value in attributes.values())
    assert sample_cases.PLANTED_NRIC not in emitted
    assert "guarantor" not in emitted.lower(), "a covenant clause reached a span attribute"
    assert "obl-" not in emitted, "the obligor key is a join key, and it belongs in the audit trail"
