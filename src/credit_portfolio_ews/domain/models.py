"""Vertical artifact models: the post-origination monitoring types this service reasons over.

The artifacts THIS vertical produces, as opposed to the vertical-neutral machinery in
``kernel.py``. The service's own name is deliberately not substituted into this docstring: a
rendered line whose length depends on ``friendly_name`` fails the repo's own format check for
no reason but the length of its name.

Two vocabularies here are consumed VERBATIM from the origination service (catalog id
credit-memo-drafting, repository ``credit-memo-drafting``): ``CovenantType`` and
``CovenantOperator``, member for member and wire value for wire value. They are re-declared rather
than imported because the domain imports only the standard library plus the commons and
credit-memo-drafting is reached over a port, but a divergent enum is how two services silently stop
describing the same covenant, so ``tests/unit/test_covenant_vocabulary.py`` pins the member set
against what the credit-memo-drafting-shaped fixture returns.

A fork building a different vertical rewrites this module and keeps ``kernel.py`` untouched.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from hex_service_kit.enums import LenientStrEnum

from .kernel import Citation, Decision, Severity


class CovenantType(LenientStrEnum):
    """The financial-covenant kinds credit-memo-drafting extracts at origination.

    Lenient so a type credit-memo-drafting adds later degrades to a readable unknown rather than
    crashing a
    portfolio sweep partway through.
    """

    LEVERAGE = "leverage"
    DSCR = "dscr"
    INTEREST_COVER = "interest_cover"
    CURRENT_RATIO = "current_ratio"
    MIN_EBITDA = "min_ebitda"
    MAX_CAPEX = "max_capex"
    TANGIBLE_NET_WORTH = "tangible_net_worth"
    OTHER = "other"


class CovenantOperator(LenientStrEnum):
    """How an observed value is compared against a covenant threshold. Verbatim from
    credit-memo-drafting.
    """

    LE = "<="
    LT = "<"
    GE = ">="
    GT = ">"
    EQ = "=="


class CovenantStatus(LenientStrEnum):
    """credit-memo-drafting's three statuses plus the four that only exist AFTER origination.

    credit-memo-drafting has no need for the last four because at origination every term is freshly
    evidenced.
    This repo lives entirely in the world where they happen. ``NOT_DUE`` and ``NOT_EVIDENCED``
    are deliberately different states: a covenant whose period is still open must not read as
    one nobody evidenced, and a covenant nobody tested must never read as one that passed.
    """

    COMPLIANT = "compliant"
    AT_RISK = "at_risk"
    BREACH = "breach"
    WAIVED = "waived"
    STALE = "stale"
    NOT_EVIDENCED = "not_evidenced"
    NOT_DUE = "not_due"


class WatchGrade(LenientStrEnum):
    """The supervisory classification ladder, declared worst last.

    MAS Notice 612 in this deployment's jurisdiction, the same rungs as the US interagency
    scale. No internal watch rung is invented: mixing an internal tier into a supervisory
    vocabulary is the first thing a Head of Credit Review would query.
    """

    PASS = "pass"
    SPECIAL_MENTION = "special_mention"
    SUBSTANDARD = "substandard"
    DOUBTFUL = "doubtful"
    LOSS = "loss"


#: Rank map owned by this module, so every comparison in the engine is an INTEGER comparison and
#: never a string one. ``LOSS`` is present because the REGISTRY holds it and a current grade of
#: loss must be readable; the engine's ceiling is what makes it unproposable.
GRADE_RANK: Mapping[WatchGrade, int] = {
    WatchGrade.PASS: 0,
    WatchGrade.SPECIAL_MENTION: 1,
    WatchGrade.SUBSTANDARD: 2,
    WatchGrade.DOUBTFUL: 3,
    WatchGrade.LOSS: 4,
}

#: The grades a supervisor reads as non-performing. Dual control keys off this set, never off a
#: severity band: moving an exposure out of performing (or back into it) is a two-signature act.
NON_PERFORMING: frozenset[WatchGrade] = frozenset(
    {WatchGrade.SUBSTANDARD, WatchGrade.DOUBTFUL, WatchGrade.LOSS}
)


class Movement(LenientStrEnum):
    """What the proposal asks the credit officer to do relative to the grade of record.

    Never what the service DID: this service applies nothing. ``UPGRADE`` exists because a
    watchlist with no exit is a ratchet, and because the same human approval that legitimises a
    downgrade proposal legitimises an upgrade one. The engine's asymmetry, not the type system,
    is what makes an upgrade hard to earn.
    """

    AFFIRM = "affirm"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"


class SignalFamily(LenientStrEnum):
    """The three evidence families the catalog names, plus PROCESS for findings about OUR file.

    A data gap, a stale certificate, a thin coverage ratio, an overdue or absent annual review
    and an immaterial arrear are facts about the bank's own file rather than about the obligor's
    credit. The split is load bearing twice: it stops a data gap diluting a covenant breach
    under the financial cap, and it stops a thin file classifying an obligor.
    """

    FINANCIAL = "financial"
    BEHAVIOURAL = "behavioural"
    EXTERNAL = "external"
    PROCESS = "process"


class NewsRelevance(LenientStrEnum):
    """Is this item about THIS obligor? Asserted by the FEED, never inferred in this repo.

    Entity resolution on a common company name is the classic adverse-media false positive, so
    it is not a job for a narration model. The default is the inert value, so a feed that omits
    the field cannot accidentally arm a rule.
    """

    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    DISMISSED = "dismissed"


class NewsCategory(LenientStrEnum):
    """What KIND of item this is. May be assigned by the model, from this closed set.

    The category selects which capped external rule may fire. ``UNCLEAR`` is the default and
    fires nothing, so a model that cannot decide changes no outcome.
    """

    INSOLVENCY = "insolvency"
    LITIGATION = "litigation"
    RATING_DOWNGRADE = "rating_downgrade"
    REGULATORY_ACTION = "regulatory_action"
    SUPPLIER_DISTRESS = "supplier_distress"
    MANAGEMENT_EXIT = "management_exit"
    UNCLEAR = "unclear"


class Comparison(LenientStrEnum):
    """How one signal rule tests its metric."""

    MAX = "max"
    MIN = "min"
    DELTA_MAX = "delta_max"
    DELTA_MIN = "delta_min"
    PRESENT = "present"


class Ifrs9Backstop(LenientStrEnum):
    """Which IFRS 9 backstop this review TRIPPED, and nothing more.

    The engine deliberately does NOT propose an impairment stage: the standard's primary test is
    a relative increase in lifetime probability of default since initial recognition, which needs
    a PD model this repo does not have and must not pretend to have. Flagging the thirty-day and
    ninety-day presumptions is defensible; proposing a stage from days past due alone is not.
    """

    NONE = "none"
    SICR_PRESUMPTION = "sicr_presumption"
    DEFAULT_PRESUMPTION = "default_presumption"


@dataclass(frozen=True, slots=True)
class ObligorRecord:
    """The grade of record and the obligor facts, READ from the grade registry.

    One record from one system of record, rather than an obligor and a grade read separately.
    Money is an int in the currency's minor units, never a float: money in a float is a rounding
    argument nobody wins. ``clean_periods`` is maintained UPSTREAM by the registry (named in the
    risk list). ``last_review_on`` is optional because a missing review date is exactly the
    finding the review-clock rule exists to raise, and ``exposure_amount_minor`` is present but
    never read by the engine module.
    """

    obligor_id: str
    name: str
    sector: str = ""
    jurisdiction: str = ""
    current_grade: WatchGrade = WatchGrade.PASS
    exposure_amount_minor: int = 0
    currency: str = ""
    clean_periods: int = 0
    watchlist_since: date | None = None
    last_review_on: date | None = None
    source: str = ""
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class ArrearsSnapshot:
    """The servicing facts the materiality gate and the past-due rules run on, as ONE record.

    Kept together rather than split across a metric stream because the materiality test compares
    figures that must come from the same snapshot at the same date; a fresh arrears amount tested
    against a stale exposure would make the gate silently mean nothing. ``None`` is a meaningful
    answer and never a zero: no snapshot means the past-due rules have nothing to test.
    """

    obligor_id: str
    as_of: date
    currency: str
    drawn_amount_minor: int
    past_due_amount_minor: int
    days_past_due: int
    source_ref: str = ""
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class CovenantTerm:
    """One covenant as credit-memo-drafting extracted it, plus the post-origination fields.

    credit-memo-drafting owns the type, description, metric, threshold and operator. The period end
    and the
    certificate due date (which separate ``not_due`` from ``not_evidenced``), the waiver
    reference and expiry, the running consecutive-breach count and the per-term headroom
    override do not exist at origination and are held here. ``citations`` carry the
    credit-memo-drafting
    provenance, so a reviewer traces the threshold back to the credit-agreement clause it was
    extracted from, in the other service. The engine never INFERS a waiver: it reads one over
    the port or there is none.
    """

    covenant_id: str
    facility_id: str
    obligor_id: str
    type: CovenantType
    description: str
    metric: str
    threshold: float
    operator: CovenantOperator
    test_period: str = ""
    period_end: date | None = None
    certificate_due_on: date | None = None
    headroom_band: float | None = None
    waiver_reference: str = ""
    waiver_expiry: date | None = None
    consecutive_breaches: int = 0
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class CovenantObservation:
    """The tested value for one term in one reporting period, plus the certificate date.

    Matched to its term by ``covenant_id`` and ``test_period``, which makes covenant selection
    total with no tie-break at all. ``observed_value`` is optional because a missing figure is a
    finding, not a zero, and the certificate date is what the staleness and overdue rules read.
    """

    covenant_id: str
    obligor_id: str
    test_period: str
    observed_value: float | None = None
    certificate_received_on: date | None = None
    source: str = ""
    source_ref: str = ""
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class SignalObservation:
    """One normalised figure from the spreading system or the transaction warehouse.

    Both feeds land in ONE record shape so the engine reasons over one thing whatever produced
    it. ``citations`` are carried so a fired signal grounds on BOTH the policy row it derives
    from and the source locator of the figure it fired on: grounding a claim about an observed
    value on the policy row alone is not a locator a reviewer can follow.
    """

    metric: str
    value: float
    period: str
    as_of: date
    unit: str = ""
    source: str = ""
    source_ref: str = ""
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class AdverseNewsItem:
    """One retrieved external item.

    ``citation`` is a REQUIRED field with no default, so an item that cannot be cited cannot be
    constructed; the engine's grounding check then makes the invariant hold twice.
    ``classified_by`` names the model or the feed that assigned the category, so a supervisor
    can tell a model category from a feed one.
    """

    item_id: str
    obligor_id: str
    headline: str
    published_on: date
    citation: Citation
    relevance: NewsRelevance = NewsRelevance.UNCONFIRMED
    category: NewsCategory = NewsCategory.UNCLEAR
    classified_by: str = ""
    snippet: str = ""
    source_ref: str = ""


@dataclass(frozen=True, slots=True)
class CovenantTest:
    """The deterministic verdict on one covenant, explaining itself without a re-run.

    ``rule_id`` records WHICH rule produced the status rather than only the label, ``headroom``
    is the figure that decided ``at_risk`` and ``certificate_age_days`` is the figure that
    decided ``not_evidenced``.
    """

    covenant_id: str
    type: CovenantType
    status: CovenantStatus
    threshold: float
    operator: CovenantOperator
    observed_value: float | None
    test_period: str
    observed_on: date | None
    certificate_age_days: int | None
    headroom: float | None
    waived_until: date | None
    family: SignalFamily
    severity: Severity
    weight: int
    rule_id: str
    detail: str
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class EarlyWarningSignal:
    """One fired rule.

    ``weight`` is an int deliberately: the composite is integer arithmetic end to end, so no
    band edge is decided by float drift and a replay on another machine cannot land one point
    away in a different grade. Zero-weight signals are FIRST CLASS: they are the record that a
    rule was considered and did not fire, which is the first thing a second-line reviewer opens
    and the thing a silent pass destroys.
    """

    rule_id: str
    family: SignalFamily
    severity: Severity
    weight: int
    metric: str
    comparison: Comparison
    observed_value: float | None
    threshold: float | None
    periods_tested: int
    detail: str
    evidence_ref: str
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class FamilyScore:
    """Per-family arithmetic made visible: raw weight NEXT TO capped weight.

    A reviewer sees that correlated leverage and coverage rules summed to one number and
    contributed another, which is the difference between a score and a black box. Capping is
    recorded here rather than as a per-signal flag, because when a cap binds across several
    signals there is no non-arbitrary way to say which one was reduced.
    """

    family: SignalFamily
    raw_weight: int
    cap: int
    capped_weight: int
    signal_count: int


@dataclass(frozen=True, slots=True)
class GradeProposal:
    """The proposal, with ``band_grade`` kept ALONGSIDE ``proposed_grade``.

    The console and the demo can then show that the score alone said one thing and a named floor
    rule said another. A proposal that hid which of the two decided it is the black box a Chief
    Credit Officer refuses to sign. EVERY floor that applied is listed, not only the winner,
    because a retune that silently changes which rule is deciding is exactly what the eval's
    ``floor_precision`` metric has to catch.
    """

    current_grade: WatchGrade
    band_grade: WatchGrade
    proposed_grade: WatchGrade
    movement: Movement
    notches: int
    applied_floors: tuple[str, ...] = ()
    applied_ceiling: str = ""
    withheld_reason: str = ""


@dataclass(frozen=True, slots=True)
class EarlyWarningAssessment:
    """Everything one review produced, and the payload every port is handed after redaction.

    ``review_reasons`` carries the rule ids that made ``requires_human_review`` true, so a
    reviewer opens the item already knowing why it reached them. ``presumption_rebuttable``
    marks that the IFRS 9 presumptions ARE rebuttable and that only a human may rebut one: the
    engine sets the flag, never the rebuttal.

    There is deliberately no ``approved_by``, no ``effective_from``, no ``required_approvals``
    and no writeback reference on this type: approving is the review console's act, applying is
    the registry's, and the approval path depends on exposure, which the engine may not read.
    """

    obligor_id: str
    obligor_name: str
    as_of: date
    test_period: str
    composite_score: int
    family_scores: tuple[FamilyScore, ...]
    covenant_tests: tuple[CovenantTest, ...]
    signals: tuple[EarlyWarningSignal, ...]
    proposal: GradeProposal
    effective_days_past_due: int
    arrears_material: bool
    staging_backstop: Ifrs9Backstop
    unlikely_to_pay: bool
    presumption_rebuttable: bool
    data_completeness: float
    confirmation_requested: tuple[str, ...]
    severity: Severity
    decision: Decision
    requires_human_review: bool
    review_reasons: tuple[str, ...]
    summary: str
    evidence_counts: tuple[tuple[str, int], ...] = ()
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class WatchlistReview:
    """What the service returns: the engine's assessment plus what the service did around it.

    ``required_approvals`` lives here and not on the assessment, because it is the only place
    exposure size is read, which is how the design keeps materiality on the approval PATH and
    out of the classification. ``memo_discarded_reason`` is populated rather than swallowed, so
    a validation failure is visible on the surface instead of looking like a model that had
    nothing to say.
    """

    assessment: EarlyWarningAssessment
    review_ref: str = ""
    required_approvals: int = 1
    memo_headline: str = ""
    memo_body: str = ""
    memo_discarded_reason: str = ""
    #: Always False, and TYPED on the result so a console can STATE it rather than imply it: no
    #: adapter in any profile has a method that could write a grade.
    grade_applied: bool = field(default=False)
