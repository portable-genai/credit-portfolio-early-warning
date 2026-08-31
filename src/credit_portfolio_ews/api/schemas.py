"""API request/response schemas (Pydantic) mapped to/from the pure-domain models.

The request carries no actor, no tenant and no entitlement: identity is resolved server-side and
whatever the client asserted is discarded. It carries an obligor KEY rather than a free-text
party name, because a name is not something a registry can authorise.

Every resolved value is ECHOED on the response (``as_of`` and ``test_period`` in particular), so
a stored answer is self-describing and a reader never has to guess which date or which reporting
period a proposal was tested against.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..domain.models import CovenantTest, EarlyWarningSignal, WatchlistReview


class WatchlistReviewRequest(BaseModel):
    """One obligor to review. The key, the period, the date and the retrieval window."""

    #: The key the grade registry holds, never a free-text party name. The port authorises it
    #: against the resolved principal's tenant; an obligor under another tenant answers 403 and
    #: never 404, so the two statuses cannot be used to enumerate another bank's book.
    obligor_id: str
    #: The covenant reporting period to test. Empty means the latest the covenant feed reports
    #: for this obligor, and the resolved value is echoed back.
    test_period: str = ""
    #: ISO date. Empty means the surface resolves today and echoes it, so the engine always
    #: receives an explicit date.
    as_of: str = ""
    #: The adverse-media retrieval window, clamped server-side to the policy maximum.
    news_lookback_days: int = 180


class CitationModel(BaseModel):
    source_id: str
    title: str
    snippet: str = ""


class FamilyScoreModel(BaseModel):
    family: str
    raw_weight: int
    cap: int
    capped_weight: int
    signal_count: int


class CovenantTestModel(BaseModel):
    covenant_id: str
    type: str
    status: str
    threshold: float
    operator: str
    observed_value: float | None = None
    test_period: str = ""
    observed_on: str = ""
    certificate_age_days: int | None = None
    headroom: float | None = None
    waived_until: str = ""
    family: str = ""
    severity: str = ""
    weight: int = 0
    rule_id: str = ""
    detail: str = ""
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(cls, test: CovenantTest) -> CovenantTestModel:
        return cls(
            covenant_id=test.covenant_id,
            type=test.type.value,
            status=test.status.value,
            threshold=test.threshold,
            operator=test.operator.value,
            observed_value=test.observed_value,
            test_period=test.test_period,
            observed_on=test.observed_on.isoformat() if test.observed_on else "",
            certificate_age_days=test.certificate_age_days,
            headroom=test.headroom,
            waived_until=test.waived_until.isoformat() if test.waived_until else "",
            family=test.family.value,
            severity=test.severity.value,
            weight=test.weight,
            rule_id=test.rule_id,
            detail=test.detail,
            citations=[_citation(c) for c in test.citations],
        )


class SignalModel(BaseModel):
    rule_id: str
    family: str
    severity: str
    weight: int
    metric: str = ""
    comparison: str = ""
    observed_value: float | None = None
    threshold: float | None = None
    periods_tested: int = 0
    detail: str = ""
    evidence_ref: str = ""
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(cls, signal: EarlyWarningSignal) -> SignalModel:
        return cls(
            rule_id=signal.rule_id,
            family=signal.family.value,
            severity=signal.severity.value,
            weight=signal.weight,
            metric=signal.metric,
            comparison=signal.comparison.value,
            observed_value=signal.observed_value,
            threshold=signal.threshold,
            periods_tested=signal.periods_tested,
            detail=signal.detail,
            evidence_ref=signal.evidence_ref,
            citations=[_citation(c) for c in signal.citations],
        )


class ObligorSummary(BaseModel):
    """One row of the READ-ONLY obligor listing the console's picker is populated from."""

    obligor_id: str
    name: str
    sector: str = ""
    current_grade: str = "pass"
    currency: str = ""
    clean_periods: int = 0
    last_review_on: str = ""


class WatchlistReviewResponse(BaseModel):
    obligor_id: str
    obligor_name: str
    #: The RESOLVED date and period, always populated, whatever the request left empty.
    as_of: str
    test_period: str
    current_grade: str
    #: What the composite alone said, kept beside the proposal so a reader can see when a named
    #: floor rule, and not the score, did the classifying.
    band_grade: str
    proposed_grade: str
    movement: str
    notches: int
    applied_floors: list[str] = []
    applied_ceiling: str = ""
    withheld_reason: str = ""
    composite_score: int = 0
    family_scores: list[FamilyScoreModel] = []
    effective_days_past_due: int = 0
    arrears_material: bool = False
    staging_backstop: str = "none"
    unlikely_to_pay: bool = False
    presumption_rebuttable: bool = False
    data_completeness: float = 0.0
    covenant_tests: list[CovenantTestModel] = []
    signals: list[SignalModel] = []
    #: News item ids the officer should confirm. These scored exactly nothing.
    confirmation_requested: list[str] = []
    severity: str = "low"
    decision: str = "allowed"
    requires_human_review: bool = False
    review_reasons: list[str] = []
    #: Where the escalation WENT (rule R8). Empty only when it did not escalate.
    review_ref: str = ""
    required_approvals: int = 1
    #: Always false, and TYPED here so a console can STATE it rather than imply it: no adapter in
    #: any profile has a method that could write a grade.
    grade_applied: bool = False
    summary: str = ""
    memo_headline: str = ""
    memo_body: str = ""
    memo_discarded_reason: str = ""
    evidence_counts: dict[str, int] = {}
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(cls, review: WatchlistReview) -> WatchlistReviewResponse:
        assessment = review.assessment
        proposal = assessment.proposal
        return cls(
            obligor_id=assessment.obligor_id,
            obligor_name=assessment.obligor_name,
            as_of=assessment.as_of.isoformat(),
            test_period=assessment.test_period,
            current_grade=proposal.current_grade.value,
            band_grade=proposal.band_grade.value,
            proposed_grade=proposal.proposed_grade.value,
            movement=proposal.movement.value,
            notches=proposal.notches,
            applied_floors=list(proposal.applied_floors),
            applied_ceiling=proposal.applied_ceiling,
            withheld_reason=proposal.withheld_reason,
            composite_score=assessment.composite_score,
            family_scores=[
                FamilyScoreModel(
                    family=score.family.value,
                    raw_weight=score.raw_weight,
                    cap=score.cap,
                    capped_weight=score.capped_weight,
                    signal_count=score.signal_count,
                )
                for score in assessment.family_scores
            ],
            effective_days_past_due=assessment.effective_days_past_due,
            arrears_material=assessment.arrears_material,
            staging_backstop=assessment.staging_backstop.value,
            unlikely_to_pay=assessment.unlikely_to_pay,
            presumption_rebuttable=assessment.presumption_rebuttable,
            data_completeness=assessment.data_completeness,
            covenant_tests=[CovenantTestModel.from_domain(t) for t in assessment.covenant_tests],
            signals=[SignalModel.from_domain(s) for s in assessment.signals],
            confirmation_requested=list(assessment.confirmation_requested),
            severity=assessment.severity.value,
            decision=assessment.decision.value,
            requires_human_review=assessment.requires_human_review,
            review_reasons=list(assessment.review_reasons),
            review_ref=review.review_ref,
            required_approvals=review.required_approvals,
            grade_applied=review.grade_applied,
            summary=assessment.summary,
            memo_headline=review.memo_headline,
            memo_body=review.memo_body,
            memo_discarded_reason=review.memo_discarded_reason,
            evidence_counts=dict(assessment.evidence_counts),
            citations=[_citation(c) for c in assessment.citations],
        )


class HealthResponse(BaseModel):
    status: str
    profile: str
    region: str
    #: Provenance the UI banner states on every page: where the runtime sits and which model
    #: answers. Derived server-side so the UI never guesses (org decision, 2026-08-30).
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "no-model"


def _citation(citation: object) -> CitationModel:
    return CitationModel(
        source_id=getattr(citation, "source_id", ""),
        title=getattr(citation, "title", ""),
        snippet=getattr(citation, "snippet", ""),
    )
