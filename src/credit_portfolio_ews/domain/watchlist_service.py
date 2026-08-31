"""The application service: read the evidence, run the pure engine, redact once, route.

This is orchestration, not decision. The consequential decision lives in
:class:`~.early_warning.EarlyWarningEngine`, which is pure stdlib with no clock and no I/O. This
module only coordinates the ports around it, in the order the discipline requires:

1. READ the obligor and its grade of record from the grade registry (which has no write method);
2. READ the covenant terms credit-memo-drafting extracted at origination, and their observations;
3. READ the arrears snapshot and the metric window from the portfolio feed;
4. RETRIEVE adverse media, and let the model CATEGORISE only the items the feed already
   confirmed are about this obligor;
5. EVALUATE with the pure engine;
6. REDACT the assessment ONCE, at the edge of the service (:func:`redacted_assessment`);
7. write the WORM audit record, DRAFT and validate the memo, and ROUTE every consequential
   proposal to the review console, all from that one masked projection;
8. return the engine's own assessment to the authenticated caller, who has to act on it.

Nothing here applies a grade. ``grade_applied`` on the result is always false, and it is typed on
the result so the console can STATE it rather than imply it: there is no method in any bound
adapter that could have written one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from pii_kit import redact

from ..ports.adverse_media import AdverseMediaPort
from ..ports.audit import AuditSinkPort
from ..ports.covenant_terms import CovenantTermsPort
from ..ports.generation import GenerationPort
from ..ports.grade_registry import GradeRegistryPort
from ..ports.observability import ObservabilityTracerPort
from ..ports.portfolio_feed import PortfolioFeedPort
from ..ports.review_router import ReviewRouterPort
from .early_warning import EarlyWarningEngine
from .errors import ObligorNotFoundError
from .kernel import AuditEvent, Citation, utcnow
from .models import (
    NON_PERFORMING,
    AdverseNewsItem,
    CovenantTerm,
    CovenantTest,
    EarlyWarningAssessment,
    EarlyWarningSignal,
    Movement,
    NewsCategory,
    NewsRelevance,
    ObligorRecord,
    WatchlistReview,
)
from .narration import build_prompt, validate_memo
from .pii import PII_PATTERNS
from .policy import DEFAULT_POLICY, EarlyWarningPolicy

#: One span per obligor reviewed. A module constant so the traced name is greppable and stable.
REVIEW_SPAN = "watchlist.review"

#: The marker the categorisation prompt opens with, so one generation port can serve both model
#: jobs and an offline narrator can tell them apart without a second binding.
CATEGORISE_MARKER = "CATEGORISE ONE CONFIRMED ADVERSE-MEDIA ITEM"

#: What ``classified_by`` records when the model assigned the category, so a supervisor can tell
#: a model category from a feed one at a glance.
MODEL_CLASSIFIER = "generation-port"


def redacted_citations(citations: Sequence[Citation]) -> tuple[Citation, ...]:
    """Mask the SNIPPET, never the locator.

    A masked ``source_id`` or title is a claim nobody can trace, which defeats the whole point of
    carrying provenance; a snippet is quoted upstream text and is exactly where a guarantor's
    identifier or an address turns up.
    """
    return tuple(
        replace(citation, snippet=redact(citation.snippet, PII_PATTERNS)) for citation in citations
    )


def redacted_tests(tests: Sequence[CovenantTest]) -> tuple[CovenantTest, ...]:
    return tuple(
        replace(
            test,
            detail=redact(test.detail, PII_PATTERNS),
            citations=redacted_citations(test.citations),
        )
        for test in tests
    )


def redacted_signals(signals: Sequence[EarlyWarningSignal]) -> tuple[EarlyWarningSignal, ...]:
    return tuple(
        replace(
            signal,
            detail=redact(signal.detail, PII_PATTERNS),
            evidence_ref=redact(signal.evidence_ref, PII_PATTERNS),
            citations=redacted_citations(signal.citations),
        )
        for signal in signals
    )


def redacted_assessment(assessment: EarlyWarningAssessment) -> EarlyWarningAssessment:
    """The assessment with every CONTENT field masked and every FIGURE left alone.

    This is the ONE seam. An assessment reaches three sinks outside this service (the WORM audit
    write, the outbound review payload and the model prompt), and masking at each sink means
    getting it right three times, in three files, forever. So the projection is built HERE, where
    the result crosses out of the service, and every sink is handed the same masked object.

    MASKED, because it is upstream prose: the obligor name, each covenant test's detail (which
    carries the clause text, and a clause is where a guarantor gets named), each signal's detail
    and evidence locator, every citation snippet, and the summary line.

    NOT MASKED, deliberately: every figure, every grade, every rule id, every join key and every
    citation LOCATOR. A masked figure is a changed figure, a masked obligor id would detach the
    proposal from the obligor it is about, and a masked locator is a claim nobody can trace.
    """
    return replace(
        assessment,
        obligor_name=redact(assessment.obligor_name, PII_PATTERNS),
        covenant_tests=redacted_tests(assessment.covenant_tests),
        signals=redacted_signals(assessment.signals),
        summary=redact(assessment.summary, PII_PATTERNS),
        citations=redacted_citations(assessment.citations),
    )


def required_approvals(
    assessment: EarlyWarningAssessment,
    *,
    exposure_minor: int,
    policy: EarlyWarningPolicy = DEFAULT_POLICY,
) -> int:
    """Two approvals on any of three legs, one otherwise. The ONLY place exposure is read.

    Moving an exposure OUT of performing, or back INTO it, is a dual-control decision, and so is
    anything above the bank's own materiality threshold. Note where exposure entered: it sets the
    approval PATH and takes no part in the classification, because a grade that moved with
    facility size would be gameable by splitting facilities.
    """
    proposal = assessment.proposal
    into_non_performing = proposal.proposed_grade in NON_PERFORMING
    out_of_non_performing = (
        proposal.current_grade in NON_PERFORMING and proposal.movement is Movement.UPGRADE
    )
    material_exposure = exposure_minor > policy.dual_control_exposure_minor
    return 2 if (into_non_performing or out_of_non_performing or material_exposure) else 1


class WatchlistReviewService:
    """Coordinate the ports around the pure engine for one obligor's periodic review."""

    def __init__(
        self,
        *,
        audit: AuditSinkPort,
        covenant_terms: CovenantTermsPort,
        portfolio_feed: PortfolioFeedPort,
        adverse_media: AdverseMediaPort,
        grade_registry: GradeRegistryPort,
        generation: GenerationPort,
        review_router: ReviewRouterPort,
        tracer: ObservabilityTracerPort,
        policy: EarlyWarningPolicy = DEFAULT_POLICY,
    ) -> None:
        self._audit = audit
        self._covenants = covenant_terms
        self._portfolio = portfolio_feed
        self._media = adverse_media
        self._registry = grade_registry
        self._generation = generation
        self._review = review_router
        self._tracer = tracer
        self._policy = policy
        self._engine = EarlyWarningEngine()

    @property
    def policy(self) -> EarlyWarningPolicy:
        return self._policy

    def obligors(self, tenant: str) -> tuple[ObligorRecord, ...]:
        """The read-only obligor listing the console's picker is populated from."""
        return self._registry.list_obligors(tenant)

    def review(
        self,
        obligor_id: str,
        *,
        tenant: str,
        actor: str,
        as_of: date,
        test_period: str = "",
        news_lookback_days: int = 180,
    ) -> WatchlistReview:
        """Review one obligor end to end and perform every side effect the result demands.

        The whole path runs inside one span whose attributes are STRUCTURAL only, never an
        obligor name, a covenant clause, a finding or any narration text: a trace backend is not
        the WORM audit trail. It has no redaction stage, a wider read audience and no retention
        rule written against a regulator's requirement, so anything content-shaped that reaches a
        span attribute has left the boundary redaction exists to hold, and left it silently.
        """
        with self._tracer.span(REVIEW_SPAN, action="watchlist_review", actor=actor):
            return self._review_obligor(
                obligor_id,
                tenant=tenant,
                actor=actor,
                as_of=as_of,
                test_period=test_period,
                news_lookback_days=news_lookback_days,
            )

    def _review_obligor(
        self,
        obligor_id: str,
        *,
        tenant: str,
        actor: str,
        as_of: date,
        test_period: str,
        news_lookback_days: int,
    ) -> WatchlistReview:
        obligor = self._registry.obligor(obligor_id, tenant=tenant)
        if obligor is None:
            raise ObligorNotFoundError(
                f"the grade registry holds no obligor {obligor_id!r} for this tenant"
            )

        available = self._covenants.terms_for(obligor_id, tenant=tenant, test_period=test_period)
        period = test_period or self._latest_period(available)
        # One period is reviewed at a time, and the resolved period is echoed on the response, so
        # a stored answer never leaves a reader guessing which period it was tested against.
        terms = tuple(term for term in available if not period or term.test_period == period)
        observations = (
            self._covenants.observations_for(obligor_id, tenant=tenant, test_period=period)
            if period
            else ()
        )
        arrears = self._portfolio.arrears(obligor_id, tenant=tenant, as_of=as_of)
        window = self._portfolio.observations(obligor_id, tenant=tenant, as_of=as_of)
        lookback = max(1, min(news_lookback_days, self._policy.max_news_lookback_days))
        news = self._categorised(
            self._media.items(obligor_id, tenant=tenant, as_of=as_of, lookback_days=lookback)
        )

        assessment = self._engine.evaluate(
            obligor,
            terms,
            observations,
            arrears,
            window,
            news,
            policy=self._policy,
            as_of=as_of,
        )

        # One masking step, here, where the result crosses out of the service. Everything below
        # is handed the SAME object.
        outbound = redacted_assessment(assessment)
        self._record_audit(outbound, actor=actor)
        headline, body, discarded = self._draft_memo(outbound)
        approvals = required_approvals(
            assessment, exposure_minor=obligor.exposure_amount_minor, policy=self._policy
        )

        review_ref = ""
        if assessment.requires_human_review:
            # Rule R8: the proposal is ROUTED in the same call that produced it. Setting the flag
            # is not the escalation; routing is, and the reference says where it went.
            review_ref = self._review.route(
                WatchlistReview(
                    assessment=outbound,
                    required_approvals=approvals,
                    memo_headline=headline,
                    memo_body=body,
                    memo_discarded_reason=discarded,
                ),
                maker=actor,
                tenant=tenant,
            )
        return WatchlistReview(
            assessment=assessment,
            review_ref=review_ref,
            required_approvals=approvals,
            memo_headline=headline,
            memo_body=body,
            memo_discarded_reason=discarded,
        )

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _latest_period(terms: Sequence[CovenantTerm]) -> str:
        """The latest reporting period the covenant feed reports, or empty when it reports none.

        Resolved here and ECHOED on the response, so a stored answer is self-describing and a
        reader never has to guess which period a proposal was tested against.
        """
        periods = sorted({term.test_period for term in terms if term.test_period})
        return periods[-1] if periods else ""

    def _categorised(self, news: Sequence[AdverseNewsItem]) -> tuple[AdverseNewsItem, ...]:
        """Let the model assign a CATEGORY, and only to items the feed already confirmed.

        The model cannot assert relevance, cannot invent an item and cannot reach a grade. The
        category merely selects which capped external rule may fire, the family cap and the
        load-time validator keep that family below the first adverse band, and no external signal
        ever sets a floor. A model that fails or answers with something outside the closed enum
        leaves the item UNCLEAR, which fires nothing.
        """
        out: list[AdverseNewsItem] = []
        for item in news:
            needs = (
                item.relevance is NewsRelevance.CONFIRMED and item.category is NewsCategory.UNCLEAR
            )
            if not needs:
                out.append(item)
                continue
            category = self._categorise(item)
            out.append(
                item
                if category is NewsCategory.UNCLEAR
                else replace(item, category=category, classified_by=MODEL_CLASSIFIER)
            )
        return tuple(out)

    def _categorise(self, item: AdverseNewsItem) -> NewsCategory:
        allowed = ", ".join(category.value for category in NewsCategory)
        prompt = "\n".join(
            [
                CATEGORISE_MARKER,
                "The feed has already confirmed this item is about the obligor. Choose ONE",
                f"category from exactly this list: {allowed}. Choose unclear when unsure.",
                'Return STRICT JSON: {"item_id": str, "category": str}.',
                "",
                "ITEM (do not add to this):",
                f"- item id: {item.item_id}",
                f"- headline: {redact(item.headline, PII_PATTERNS)}",
                f"- snippet: {redact(item.snippet, PII_PATTERNS)}",
            ]
        )
        try:
            parsed = json.loads(self._generation.generate(prompt))
        except Exception:  # noqa: BLE001 - a model fault must never decide an outcome
            return NewsCategory.UNCLEAR
        if not isinstance(parsed, dict) or parsed.get("item_id") != item.item_id:
            return NewsCategory.UNCLEAR
        try:
            return NewsCategory(str(parsed.get("category", "")))
        except ValueError:
            return NewsCategory.UNCLEAR

    def _record_audit(self, assessment: EarlyWarningAssessment, *, actor: str) -> None:
        """Write one WORM record that reconstructs the decision without the source systems.

        ``assessment`` is already the :func:`redacted_assessment` projection. Both content fields
        that leave here are masked AGAIN anyway, the summary and the citation snippets: redaction
        is idempotent, and this method is the last thing standing between a future caller that
        forgot the projection and an IMMUTABLE record. Masking only the summary was a real defect
        rather than a hypothetical one: the citations travelled straight from the assessment, so
        the one field nobody could ever unwrite depended entirely on the caller's projection, and
        both oracles read the summary alone and could not see it. The outbound review payload
        (``adapters/_review_payload.py``) has always masked again for the same reason; the sink
        that cannot be corrected afterwards is the last place to rely on somebody else.
        """
        details = " | ".join(test.detail for test in assessment.covenant_tests) + " | ".join(
            signal.detail for signal in assessment.signals
        )
        summary = redact(
            f"{assessment.summary} :: reasons "
            f"{', '.join(assessment.review_reasons) or 'none'} :: {details}",
            PII_PATTERNS,
        )
        self._audit.record(
            AuditEvent(
                action="watchlist_review",
                actor=actor,
                decision=assessment.decision,
                severity=assessment.severity,
                redacted_summary=re.sub(r"\s+", " ", summary).strip(),
                citations=redacted_citations(assessment.citations),
                timestamp=utcnow(),
            )
        )

    def _draft_memo(self, assessment: EarlyWarningAssessment) -> tuple[str, str, str]:
        """Draft the memo from the REDACTED projection, validate it, and discard on any failure.

        Only a proposal that reaches a human is narrated: an obligor with nothing to review needs
        no write-up. What the model was allowed to SEE is exactly what it is allowed to SAY back,
        because the prompt and the grounding oracle are built from the same masked object.
        """
        if not assessment.requires_human_review:
            return ("", "", "")
        try:
            raw = self._generation.generate(build_prompt(assessment))
        except NotImplementedError as exc:
            # The exit profile binds no model. The memo is DRAFTING, so its absence costs a
            # paragraph and never a decision; the assessment is complete either way.
            return ("", "", f"no narration seam is bound: {exc}")
        memo, reason = validate_memo(raw, assessment)
        if memo is None:
            return ("", "", reason)
        return (memo.headline, memo.body, "")


__all__ = [
    "CATEGORISE_MARKER",
    "MODEL_CLASSIFIER",
    "REVIEW_SPAN",
    "WatchlistReviewService",
    "redacted_assessment",
    "redacted_citations",
    "redacted_signals",
    "redacted_tests",
    "required_approvals",
]
