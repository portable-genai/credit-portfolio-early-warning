"""Shared conversion from a watchlist proposal to a ``review-kit`` Review payload.

Lives in the adapter layer, not the pure domain, because it depends on the kit. What arrives is
already the redacted projection the service built once at its edge; this module redacts AGAIN,
against EVERY jurisdiction's rows rather than only this deployment's, because Hrz7 is a SHARED
sink: a proposal filed in one market may still quote another market's national id. Redaction is
idempotent, so the second pass costs nothing and covers a future caller that forgot the first.

``maker`` and ``tenant`` are asserted here and trusted by Hrz7 because the caller is an
authenticated S2S service; per-hop on-behalf-of token exchange is the deferred next layer.

DUAL CONTROL is three-legged now, not severity-based: two approvals when the proposal is INTO a
non-performing grade, when the current grade is non-performing and the movement is an UPGRADE, or
when the exposure is above the bank's threshold. The rule itself lives in
``domain/watchlist_service.required_approvals`` and the count travels on the review, because that
function is the ONLY place the exposure figure is read and duplicating the rule here would put a
second, drifting copy of it in the adapter layer.
"""

from __future__ import annotations

import re

from pii_kit import NATIONAL_ID_PATTERNS, UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit import redact as pii_redact
from review_kit import Citation as KitCitation
from review_kit import Review

from ..domain.models import WatchlistReview

#: Cap the citations carried on the wire: enough for a reviewer to trace the decision without
#: copying the whole evidence set into the console.
_MAX_CITATIONS = 8

#: The console is a SHARED sink, so the payload is scrubbed against every jurisdiction's rows
#: plus the universal email/phone rows, whatever this deployment's own selection is.
_ALL_PATTERNS = (
    *national_patterns_for(tuple(NATIONAL_ID_PATTERNS.keys())),
    *UNIVERSAL_PATTERNS,
)


def _redact(text: str) -> str:
    """Mask every jurisdiction's identifiers plus email/phone, and normalise whitespace."""
    return re.sub(r"\s+", " ", pii_redact(text, _ALL_PATTERNS)).strip()


def _kit_citations(review: WatchlistReview) -> tuple[KitCitation, ...]:
    """Mask the SNIPPET, keep the LOCATOR: a masked locator is a claim nobody can trace."""
    seen: set[str] = set()
    out: list[KitCitation] = []
    for citation in review.assessment.citations:
        if citation.source_id in seen:
            continue
        seen.add(citation.source_id)
        out.append(
            KitCitation(
                source_id=citation.source_id,
                title=citation.title,
                snippet=_redact(citation.snippet),
            )
        )
        if len(out) >= _MAX_CITATIONS:
            break
    return tuple(out)


def review_to_payload(review: WatchlistReview, *, maker: str, tenant: str = "") -> Review:
    """Build the review a producer submits to Hrz7 when a proposal must reach a human.

    The summary states the proposal, the floors that produced it and the reasons it routed, and
    it states that NOTHING was applied: ``grade_applied`` is false on every payload, because no
    adapter in any profile has a method that could have written a grade.
    """
    assessment = review.assessment
    proposal = assessment.proposal
    # The covenant TABLE travels with the proposal, not only the headline: a credit officer
    # approving a downgrade needs to see which covenant was tested against what, and each row
    # keeps its credit-memo-drafting locator through the citation set below.
    covenants = " | ".join(
        f"{test.covenant_id} {test.status.value} ({test.rule_id}): {test.detail}"
        for test in assessment.covenant_tests
    )
    summary = _redact(
        f"{assessment.summary} :: reasons "
        f"{', '.join(assessment.review_reasons) or 'none'} :: covenants {covenants or 'none'} "
        f":: proposal only, grade_applied={str(review.grade_applied).lower()}"
    )
    return Review(
        action="credit_portfolio_ews:watchlist_review",
        subject=_redact(f"{assessment.obligor_name} ({assessment.obligor_id})"),
        maker=maker,
        tenant=tenant,
        summary=summary,
        severity=assessment.severity.value,
        required_approvals=review.required_approvals,
        sod_group="credit_portfolio_ews-maker-checker",
        case_ref=assessment.obligor_id,
        # Producer-owned, tenant-scoped key so a retried delivery is idempotent at the console.
        source_key=(
            f"Doc7:{assessment.obligor_id}:{assessment.as_of.isoformat()}:"
            f"{proposal.proposed_grade.value}"
        ),
        citations=_kit_citations(review),
    )
