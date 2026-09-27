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

Rule R1: the guardrail screens BOTH directions of BOTH model jobs this service makes, through
the one seam every call to :meth:`GenerationPort.generate` routes through
(:meth:`WatchlistReviewService._screened_generate`): the prompt it BUILT, as sent (the
categorisation prompt, or the memo prompt built from the redacted assessment, every
caller-reachable field inside it), is screened INPUT before the model is called, and the model's
raw answer is screened OUTPUT before anything downstream parses, validates or narrates it. Each
screen's text is used from then on exactly as given. A blocked direction, and a guardrail that
cannot decide at all, are audited ``Decision.BLOCKED`` (never carrying the refused text) and
raise :class:`~.errors.GuardrailBlockedError`. Narration is optional by design here, so each
caller falls back to FIXED text rather than failing the review: ``_categorise`` leaves the item
``NewsCategory.UNCLEAR`` (which fires nothing) and ``_draft_memo`` discards the memo with the
reason reported. Never a half-drafted memo or a fabricated category.
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
from ..ports.guardrail import GuardrailPort
from ..ports.observability import ObservabilityTracerPort
from ..ports.portfolio_feed import PortfolioFeedPort
from ..ports.review_router import ReviewRouterPort
from .early_warning import EarlyWarningEngine
from .errors import GuardrailBlockedError, ObligorNotFoundError
from .kernel import AuditEvent, Citation, Decision, Direction, GuardrailVerdict, Severity, utcnow
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

#: The one pinned sampling value. The categorisation is a classification the engine compares, so
#: it is pinned; the memo draft is drafting and sends no temperature at all.
CATEGORISE_TEMPERATURE = 0.0

#: The note a guardrail error carries when its BLOCKED record could not be written either. Such
#: an error is never turned into a fixed-text fallback: a refusal nobody recorded fails the
#: request instead (see ``WatchlistReviewService._screen``).
_UNAUDITED_REFUSAL = "the BLOCKED audit record could not be written"


def _unaudited_refusal(exc: BaseException) -> bool:
    return any(note.startswith(_UNAUDITED_REFUSAL) for note in getattr(exc, "__notes__", ()))


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
        guardrail: GuardrailPort,
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
        self._guardrail = guardrail
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
            self._media.items(obligor_id, tenant=tenant, as_of=as_of, lookback_days=lookback),
            actor=actor,
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
        headline, body, discarded = self._draft_memo(outbound, actor=actor)
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

    def _categorised(
        self, news: Sequence[AdverseNewsItem], *, actor: str
    ) -> tuple[AdverseNewsItem, ...]:
        """Let the model assign a CATEGORY, and only to items the feed already confirmed.

        The model cannot assert relevance, cannot invent an item and cannot reach a grade. The
        category merely selects which capped external rule may fire, the family cap and the
        load-time validator keep that family below the first adverse band, and no external signal
        ever sets a floor. A model that fails, is blocked by the guardrail, or answers with
        something outside the closed enum leaves the item UNCLEAR, which fires nothing.
        """
        out: list[AdverseNewsItem] = []
        for item in news:
            needs = (
                item.relevance is NewsRelevance.CONFIRMED and item.category is NewsCategory.UNCLEAR
            )
            if not needs:
                out.append(item)
                continue
            category = self._categorise(item, actor=actor)
            out.append(
                item
                if category is NewsCategory.UNCLEAR
                else replace(item, category=category, classified_by=MODEL_CLASSIFIER)
            )
        return tuple(out)

    def _categorise(self, item: AdverseNewsItem, *, actor: str) -> NewsCategory:
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
            # Pinned: the answer is a CLASSIFICATION the engine compares against a closed
            # vocabulary, so the same item must categorise the same way on a replay. Rule R1:
            # routed through `_screened_generate`, so a guardrail block (either direction) raises
            # `GuardrailBlockedError`, caught below exactly like any other model fault.
            parsed = json.loads(
                self._screened_generate(
                    prompt,
                    temperature=CATEGORISE_TEMPERATURE,
                    actor=actor,
                    action="adverse_media_categorisation",
                    # Nothing is scored yet: the category is an INPUT to the engine, so a refusal
                    # here records no band rather than one nothing produced.
                    severity=None,
                )
            )
        except GuardrailBlockedError:
            # Refused (or undecidable) and already audited: the fixed fallback, never a category.
            return NewsCategory.UNCLEAR
        except Exception as exc:  # noqa: BLE001 - a model fault must never decide an outcome
            if _unaudited_refusal(exc):
                raise
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

    def _draft_memo(
        self, assessment: EarlyWarningAssessment, *, actor: str
    ) -> tuple[str, str, str]:
        """Draft the memo from the REDACTED projection, validate it, and discard on any failure.

        Only a proposal that reaches a human is narrated: an obligor with nothing to review needs
        no write-up. What the model was allowed to SEE is exactly what it is allowed to SAY back,
        because the prompt and the grounding oracle are built from the same masked object.
        """
        if not assessment.requires_human_review:
            return ("", "", "")
        try:
            # Free: the memo is DRAFTING, so no temperature is sent. Every figure it states is
            # still checked against the engine's own by `validate_memo`, and discarded if not.
            # Rule R1: routed through `_screened_generate`, screened input-before / output-after.
            raw = self._screened_generate(
                build_prompt(assessment),
                temperature=None,
                actor=actor,
                action="watchlist_review_memo_draft",
                severity=assessment.severity,
            )
        except NotImplementedError as exc:
            if _unaudited_refusal(exc):
                raise
            # The exit profile binds no model. The memo is DRAFTING, so its absence costs a
            # paragraph and never a decision; the assessment is complete either way.
            return ("", "", f"no narration seam is bound: {exc}")
        except GuardrailBlockedError as exc:
            # Blocked, not absent: the refusal is already audited (`_screen`), and the memo is
            # DRAFTING, so this costs a paragraph and never the assessment itself. The fallback
            # is fixed text, never a partial draft.
            return ("", "", f"the draft was blocked by the guardrail: {exc}")
        memo, reason = validate_memo(raw, assessment)
        if memo is None:
            return ("", "", reason)
        return (memo.headline, memo.body, "")

    def _screened_generate(
        self,
        prompt: str,
        *,
        temperature: float | None,
        actor: str,
        action: str,
        severity: Severity | None,
    ) -> str:
        """Screen INPUT before the model is called, and OUTPUT before its answer is used.

        Rule R1: both directions of both model jobs this service makes (adverse-media
        categorisation, memo drafting) route through this one method, so there is exactly one
        place a generation call is made and exactly one place a guardrail block is decided.

        INPUT is the prompt AS SENT, every field joined: a caller-reachable value (the obligor
        key, the period, the feed's headline and snippet) reaches the model only inside this
        string, so a screen of this string is a screen of all of them together, and an
        injection split across two fields is seen whole. The model receives the text the INPUT
        screen handed back, and the caller receives the text the OUTPUT screen handed back,
        each EXACTLY as given: never a fall back to the unscreened original.

        ``severity`` is what the refusal record may state: ``None`` for a categorisation,
        which runs before anything is scored, and the scored band for a memo draft.
        """
        screened_prompt = self._screen(
            prompt, Direction.INPUT, actor=actor, action=action, severity=severity
        )
        raw = self._generation.generate(screened_prompt, temperature=temperature)
        return self._screen(raw, Direction.OUTPUT, actor=actor, action=action, severity=severity)

    def _screen(
        self,
        text: str,
        direction: Direction,
        *,
        actor: str,
        action: str,
        severity: Severity | None,
    ) -> str:
        """Screen one text in one direction; return the text to use from here on, or refuse.

        A block, and a guardrail that raised instead of deciding (its backend errored or timed
        out, or the on-prem placeholder is bound), BOTH fail closed: the refusal is audited
        ``Decision.BLOCKED`` first and then raised as :class:`GuardrailBlockedError`, which
        both callers turn into their fixed fallback (``UNCLEAR``, or a discarded memo with the
        reason reported). When the audit sink cannot take the refusal either, the guardrail's
        own error (or, for a block, the sink's error) propagates with a note instead: a refusal
        nobody recorded must not be converted into a quiet paragraph.
        """
        try:
            verdict: GuardrailVerdict = self._guardrail.screen(text, direction)
        except Exception as exc:
            reason = f"guardrail unavailable ({type(exc).__name__})"
            try:
                self._audit_guardrail_block(
                    actor=actor,
                    action=action,
                    severity=severity,
                    direction=direction,
                    reason=reason,
                )
            except Exception as audit_exc:
                exc.add_note(f"{_UNAUDITED_REFUSAL}: {audit_exc!r}")
                raise exc from audit_exc
            raise GuardrailBlockedError(reason) from exc
        if not verdict.allowed or verdict.sanitized_text is None:
            reason = verdict.reason or f"{action} {direction.value} blocked by guardrail"
            try:
                self._audit_guardrail_block(
                    actor=actor,
                    action=action,
                    severity=severity,
                    direction=direction,
                    reason=reason,
                )
            except Exception as audit_exc:
                audit_exc.add_note(f"{_UNAUDITED_REFUSAL}: the guardrail refused ({reason})")
                raise
            raise GuardrailBlockedError(reason)
        return verdict.sanitized_text

    def _audit_guardrail_block(
        self,
        *,
        actor: str,
        action: str,
        severity: Severity | None,
        direction: Direction,
        reason: str,
    ) -> None:
        """Audit a guardrail refusal BEFORE the raise reaches the caller (rule R1 / P-04).

        Never carries the refused prompt or answer: only that a refusal happened, in which
        direction, and why. A refused attempt is a security-relevant event the WORM trail must
        hold even though the model job it interrupted never produced a category or a memo.
        """
        self._audit.record(
            AuditEvent(
                action=action,
                actor=actor,
                decision=Decision.BLOCKED,
                severity=severity,
                redacted_summary=redact(f"blocked ({direction.value}): {reason}", PII_PATTERNS),
                citations=(),
                timestamp=utcnow(),
            )
        )


__all__ = [
    "CATEGORISE_MARKER",
    "CATEGORISE_TEMPERATURE",
    "MODEL_CLASSIFIER",
    "REVIEW_SPAN",
    "WatchlistReviewService",
    "redacted_assessment",
    "redacted_citations",
    "redacted_signals",
    "redacted_tests",
    "required_approvals",
]
