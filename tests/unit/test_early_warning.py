"""The pure engine: every rule, every clock boundary, and the ones that must NOT fire.

The engine is the vertical's whole consequential surface, so this module tests it directly
rather than through the service: no ports, no adapters, no clock. Every case builds its own
minimal evidence, so a failure names one rule instead of one obligor.

Falsification discipline (the fleet rule): the two central guards below were each shown RED
against a deliberate defect before being trusted. The mutations, and what they broke:

* delete the arrears materiality gate (read ``snapshot.days_past_due`` instead of the effective
  clock) and ``test_immaterial_arrears_never_start_the_clock`` fails with the engine proposing
  ``special_mention`` on a 640.00 arrear, because ``floor-arrears-sicr`` then applies;
* let an UNCONFIRMED media item fire (drop the relevance gate in ``_external_signals``) and
  ``test_only_a_feed_confirmed_item_can_fire_an_external_rule`` fails with a composite of 20 and
  the item missing from ``confirmation_requested``;
* raise the external family cap to 44 and
  ``test_the_external_cap_keeps_categorised_media_below_the_first_adverse_band`` fails with a
  proposed downgrade driven entirely by categorised media, and ``validate_policy`` is what
  refuses that configuration at load.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from credit_portfolio_ews.domain.early_warning import (
    EarlyWarningEngine,
    passes,
    within_headroom,
)
from credit_portfolio_ews.domain.errors import (
    UngroundedSignalError,
)
from credit_portfolio_ews.domain.kernel import (
    Citation,
    Decision,
    Severity,
)
from credit_portfolio_ews.domain.models import (
    AdverseNewsItem,
    ArrearsSnapshot,
    CovenantObservation,
    CovenantOperator,
    CovenantStatus,
    CovenantTerm,
    CovenantType,
    EarlyWarningAssessment,
    Ifrs9Backstop,
    Movement,
    NewsCategory,
    NewsRelevance,
    ObligorRecord,
    SignalFamily,
    SignalObservation,
    WatchGrade,
)
from credit_portfolio_ews.domain.policy import (
    DEFAULT_POLICY,
    EarlyWarningPolicy,
)

AS_OF = date(2026, 6, 30)
PERIOD = "FY2026H1"
DOC2 = Citation(source_id="doc2:fac-1:cov-1", title="Covenant schedule", snippet="")
REGISTRY = Citation(source_id="registry:obl-test-001", title="Grading system", snippet="")


def _obligor(**overrides: object) -> ObligorRecord:
    base: dict[str, object] = {
        "obligor_id": "obl-test-001",
        "name": "Test Trading (FICTIONAL)",
        "current_grade": WatchGrade.PASS,
        "exposure_amount_minor": 100_000_000,
        "clean_periods": 3,
        "last_review_on": date(2026, 3, 31),
        "citations": (REGISTRY,),
    }
    base.update(overrides)
    return ObligorRecord(**base)  # type: ignore[arg-type]


def _term(**overrides: object) -> CovenantTerm:
    base: dict[str, object] = {
        "covenant_id": "cov-1",
        "facility_id": "fac-1",
        "obligor_id": "obl-test-001",
        "type": CovenantType.LEVERAGE,
        "description": "Maximum net debt to EBITDA",
        "metric": "net_debt_to_ebitda",
        "threshold": 3.50,
        "operator": CovenantOperator.LE,
        "test_period": PERIOD,
        "period_end": date(2026, 6, 30),
        "certificate_due_on": date(2026, 6, 15),
        "citations": (DOC2,),
    }
    base.update(overrides)
    return CovenantTerm(**base)  # type: ignore[arg-type]


def _observed(value: float | None, **overrides: object) -> CovenantObservation:
    base: dict[str, object] = {
        "covenant_id": "cov-1",
        "obligor_id": "obl-test-001",
        "test_period": PERIOD,
        "observed_value": value,
        "certificate_received_on": date(2026, 6, 10),
        "citations": (Citation(source_id="cert:1", title="Certificate", snippet=""),),
    }
    base.update(overrides)
    return CovenantObservation(**base)  # type: ignore[arg-type]


def _arrears(days: int, past_due: int, drawn: int = 100_000_000) -> ArrearsSnapshot:
    return ArrearsSnapshot(
        obligor_id="obl-test-001",
        as_of=AS_OF,
        currency="SGD",
        drawn_amount_minor=drawn,
        past_due_amount_minor=past_due,
        days_past_due=days,
        source_ref="servicing:1",
        citations=(Citation(source_id="servicing:1", title="Servicing", snippet=""),),
    )


def _metric(
    metric: str, value: float, period: str = "2026Q2", as_of: date = AS_OF, unit: str = ""
) -> SignalObservation:
    return SignalObservation(
        metric=metric,
        value=value,
        period=period,
        as_of=as_of,
        unit=unit,
        source_ref=f"spread:{metric}:{period}",
        citations=(Citation(source_id=f"spread:{metric}:{period}", title="Spread", snippet=""),),
    )


def _news(
    relevance: NewsRelevance, category: NewsCategory = NewsCategory.INSOLVENCY
) -> AdverseNewsItem:
    return AdverseNewsItem(
        item_id="news-1",
        obligor_id="obl-test-001",
        headline="Reported filing (FICTIONAL)",
        published_on=date(2026, 5, 20),
        citation=Citation(source_id="media:news-1", title="Trade press", snippet=""),
        relevance=relevance,
        category=category,
    )


def _clean_window() -> tuple[SignalObservation, ...]:
    """Every required metric present and healthy, over two periods.

    The DEFAULT for these tests, so a case about one rule is not also a case about thin data
    coverage. A test that wants a thin file overrides it and says so.
    """
    values = {
        "net_debt_to_ebitda": (2.10, 2.20),
        "dscr": (1.92, 1.85),
        "current_ratio": (1.60, 1.55),
        "ebitda": (4.20, 4.10),
        "revolver_utilisation_pct": (42.0, 40.0),
        "collections_concentration_pct": (31.0, 33.0),
    }
    out: list[SignalObservation] = []
    for metric, (latest, prior) in values.items():
        unit = "ratio" if metric == "ebitda" else ""
        out.append(_metric(metric, latest, unit=unit))
        out.append(_metric(metric, prior, "2026Q1", date(2026, 3, 31), unit=unit))
    return tuple(out)


#: A sentinel meaning "leave this defaulted", so a test can pass ``arrears=None`` deliberately
#: and get the missing-snapshot finding rather than the quiet default.
_DEFAULT = object()


def _evaluate(
    *,
    obligor: ObligorRecord | None = None,
    terms: tuple[CovenantTerm, ...] = (),
    observations: tuple[CovenantObservation, ...] = (),
    arrears: object = _DEFAULT,
    window: object = _DEFAULT,
    news: tuple[AdverseNewsItem, ...] = (),
    policy: EarlyWarningPolicy = DEFAULT_POLICY,
    as_of: date = AS_OF,
) -> EarlyWarningAssessment:
    return EarlyWarningEngine().evaluate(
        obligor or _obligor(),
        terms,
        observations,
        _arrears(0, 0) if arrears is _DEFAULT else arrears,  # type: ignore[arg-type]
        _clean_window() if window is _DEFAULT else window,  # type: ignore[arg-type]
        news,
        policy=policy,
        as_of=as_of,
    )


def _rule_ids(assessment: EarlyWarningAssessment) -> set[str]:
    return {signal.rule_id for signal in assessment.signals}


# --------------------------------------------------------------------------------------- #
# S1: arrears materiality, and the clock it gates
# --------------------------------------------------------------------------------------- #
def test_immaterial_arrears_never_start_the_clock() -> None:
    """THE falsification case. Delete the gate and this proposes special_mention on 640.00.

    The absolute leg is cleared (64000 minor units against a 50000 limit) and the relative leg
    is not (64000 against one percent of 148000000). Both must pass, so the clock never starts.
    """
    assessment = _evaluate(arrears=_arrears(41, 64_000, drawn=148_000_000))
    assert assessment.arrears_material is False
    assert assessment.effective_days_past_due == 0
    assert assessment.proposal.applied_floors == ()
    assert assessment.proposal.proposed_grade is WatchGrade.PASS
    assert assessment.composite_score == 0
    assert assessment.requires_human_review is False


def test_the_rule_that_did_not_fire_is_recorded_at_weight_zero_with_both_limits() -> None:
    """A silent pass destroys the thing a second-line reviewer opens first."""
    assessment = _evaluate(arrears=_arrears(41, 64_000, drawn=148_000_000))
    signal = next(s for s in assessment.signals if s.rule_id == "ews-arrears-immaterial")
    assert signal.weight == 0
    assert signal.severity is Severity.LOW
    assert "50000" in signal.detail, "the absolute limit is not on the record"
    assert "1480000" in signal.detail, "the relative limit is not on the record"
    assert "64000" in signal.detail, "the observed amount is not on the record"


def test_material_arrears_start_the_clock_on_both_legs() -> None:
    assessment = _evaluate(arrears=_arrears(96, 124_000_000, drawn=3_850_000_000))
    assert assessment.arrears_material is True
    assert assessment.effective_days_past_due == 96
    assert assessment.staging_backstop is Ifrs9Backstop.DEFAULT_PRESUMPTION
    assert assessment.unlikely_to_pay is True
    assert assessment.presumption_rebuttable is True


def test_a_missing_arrears_snapshot_is_a_finding_and_never_a_zero() -> None:
    assessment = _evaluate(arrears=None)
    assert "ews-arrears-not-evidenced" in _rule_ids(assessment)
    assert "arrears-not-evidenced" in assessment.review_reasons
    assert assessment.effective_days_past_due == 0


def test_a_zero_day_snapshot_raises_nothing_at_all() -> None:
    """Nothing is past due, so the materiality question does not arise and nothing is recorded."""
    assessment = _evaluate(arrears=_arrears(0, 0))
    assert assessment.signals == ()


@pytest.mark.parametrize(
    ("days", "expected_backstop", "expected_floors"),
    [
        (29, Ifrs9Backstop.NONE, ()),
        (30, Ifrs9Backstop.SICR_PRESUMPTION, ("floor-arrears-sicr",)),
        (31, Ifrs9Backstop.SICR_PRESUMPTION, ("floor-arrears-sicr",)),
        (89, Ifrs9Backstop.SICR_PRESUMPTION, ("floor-arrears-sicr",)),
        (90, Ifrs9Backstop.DEFAULT_PRESUMPTION, ("floor-arrears-sicr", "floor-arrears-default")),
        (91, Ifrs9Backstop.DEFAULT_PRESUMPTION, ("floor-arrears-sicr", "floor-arrears-default")),
        (179, Ifrs9Backstop.DEFAULT_PRESUMPTION, ("floor-arrears-sicr", "floor-arrears-default")),
        (
            180,
            Ifrs9Backstop.DEFAULT_PRESUMPTION,
            ("floor-arrears-sicr", "floor-arrears-default", "floor-arrears-severe"),
        ),
        (
            181,
            Ifrs9Backstop.DEFAULT_PRESUMPTION,
            ("floor-arrears-sicr", "floor-arrears-default", "floor-arrears-severe"),
        ),
    ],
)
def test_the_past_due_clocks_land_exactly_on_their_boundaries(
    days: int, expected_backstop: Ifrs9Backstop, expected_floors: tuple[str, ...]
) -> None:
    """An off-by-one in a date comparison moves an obligor between grades, silently."""
    assessment = _evaluate(arrears=_arrears(days, 90_000_000, drawn=1_000_000_000))
    assert assessment.staging_backstop is expected_backstop
    assert assessment.proposal.applied_floors == expected_floors


@pytest.mark.parametrize(
    ("days", "expected_rule"),
    [
        (30, "ews-arrears-sicr"),
        (90, "ews-arrears-default"),
        (179, "ews-arrears-default"),
        (180, "ews-arrears-severe"),
    ],
)
def test_exactly_one_arrears_tier_fires_and_the_clock_picks_which(
    days: int, expected_rule: str
) -> None:
    """Three priced tiers, three rule ids, one signal.

    The severe row was priced in the settings file and read by nobody: at 180 days the signal
    was still ``ews-arrears-default``, so an operator retuning ``arrears_weights.severe`` changed
    nothing and was told nothing. The backstop deliberately does NOT move with it, because the
    severe tier is the bank's escalation and the standard has no third stage to point at.
    """
    assessment = _evaluate(arrears=_arrears(days, 90_000_000, drawn=1_000_000_000))
    tiers = {"ews-arrears-sicr", "ews-arrears-default", "ews-arrears-severe"}
    fired = _rule_ids(assessment) & tiers
    assert fired == {expected_rule}
    assert assessment.staging_backstop in (
        Ifrs9Backstop.SICR_PRESUMPTION,
        Ifrs9Backstop.DEFAULT_PRESUMPTION,
    )


# --------------------------------------------------------------------------------------- #
# S3: the covenant ladder
# --------------------------------------------------------------------------------------- #
def test_a_breach_with_no_waiver_classifies_on_the_floor_not_on_the_score() -> None:
    assessment = _evaluate(terms=(_term(),), observations=(_observed(3.62),))
    test = assessment.covenant_tests[0]
    assert test.status is CovenantStatus.BREACH
    assert test.rule_id == "covenant-breach"
    assert assessment.composite_score == 30, "below the first adverse band floor of 35"
    assert assessment.proposal.band_grade is WatchGrade.PASS
    assert assessment.proposal.proposed_grade is WatchGrade.SPECIAL_MENTION
    assert assessment.proposal.applied_floors == ("floor-covenant-breach",)


def test_a_live_waiver_removes_the_floor_and_never_the_signal() -> None:
    term = _term(waiver_reference="WVR-2026-018", waiver_expiry=date(2026, 8, 15))
    assessment = _evaluate(terms=(term,), observations=(_observed(3.70),))
    test = assessment.covenant_tests[0]
    assert test.status is CovenantStatus.WAIVED
    assert test.weight > 0, "the waiver removed the signal as well as the floor"
    assert assessment.proposal.applied_floors == ()
    assert "waiver-expiring" in assessment.review_reasons


def test_a_waiver_expiring_exactly_on_the_review_date_is_still_live() -> None:
    term = _term(waiver_reference="WVR-1", waiver_expiry=AS_OF)
    assessment = _evaluate(terms=(term,), observations=(_observed(3.70),))
    assert assessment.covenant_tests[0].status is CovenantStatus.WAIVED


def test_a_waiver_that_expired_yesterday_is_a_visibly_different_breach() -> None:
    """An expired waiver must not look like a term that never had one."""
    term = _term(waiver_reference="WVR-1", waiver_expiry=date(2026, 6, 29))
    assessment = _evaluate(terms=(term,), observations=(_observed(3.70),))
    test = assessment.covenant_tests[0]
    assert test.status is CovenantStatus.BREACH
    assert test.rule_id == "covenant-breach-waiver-expired"
    assert assessment.proposal.applied_floors == ("floor-covenant-breach",)


def test_a_covenant_nobody_evidenced_is_never_counted_compliant() -> None:
    term = _term(certificate_due_on=date(2026, 4, 20))
    assessment = _evaluate(terms=(term,))
    test = assessment.covenant_tests[0]
    assert test.status is CovenantStatus.NOT_EVIDENCED
    assert test.certificate_age_days == 71
    assert test.family.value == "process", "a data gap must not dilute a covenant breach"
    assert assessment.proposal.applied_floors == (), "not_evidenced is not a breach"


def test_a_covenant_still_inside_its_certificate_grace_is_not_due_not_missing() -> None:
    """A mid-period sweep must not read as a file nobody evidenced."""
    not_due = _evaluate(terms=(_term(certificate_due_on=date(2026, 6, 20)),))
    assert not_due.covenant_tests[0].status is CovenantStatus.NOT_DUE
    assert not_due.data_completeness == 1.0, "not_due is excluded from the denominator"

    # The control: the SAME term one day past its grace is counted, and drags coverage down.
    evidenced = _evaluate(terms=(_term(certificate_due_on=date(2026, 5, 15)),))
    assert evidenced.covenant_tests[0].status is CovenantStatus.NOT_EVIDENCED
    assert evidenced.data_completeness < 1.0


def test_the_certificate_grace_boundary_is_exact() -> None:
    on_the_day = _term(certificate_due_on=AS_OF - timedelta(days=45))
    assessment = _evaluate(terms=(on_the_day,))
    assert assessment.covenant_tests[0].status is CovenantStatus.NOT_EVIDENCED


def test_an_observation_older_than_the_reporting_lag_is_stale() -> None:
    term = _term(period_end=date(2025, 12, 31))
    observation = _observed(2.10, certificate_received_on=date(2026, 1, 5))
    assessment = _evaluate(terms=(term,), observations=(observation,))
    assert assessment.covenant_tests[0].status is CovenantStatus.STALE


def test_a_value_inside_the_headroom_band_is_at_risk() -> None:
    assessment = _evaluate(terms=(_term(),), observations=(_observed(3.42),))
    test = assessment.covenant_tests[0]
    assert test.status is CovenantStatus.AT_RISK
    assert test.headroom is not None


def test_a_per_term_headroom_override_beats_the_policy_default() -> None:
    assessment = _evaluate(terms=(_term(headroom_band=0.001),), observations=(_observed(3.42),))
    assert assessment.covenant_tests[0].status is CovenantStatus.COMPLIANT


def test_the_repeat_breach_floor_reads_the_upstream_counter() -> None:
    term = _term(consecutive_breaches=2)
    assessment = _evaluate(terms=(term,), observations=(_observed(3.62),))
    assert "floor-covenant-breach-repeat" in assessment.proposal.applied_floors
    assert assessment.proposal.proposed_grade is WatchGrade.SUBSTANDARD


def test_two_separate_breaches_also_set_the_repeat_floor() -> None:
    second = _term(covenant_id="cov-2", metric="dscr", threshold=1.25, operator=CovenantOperator.GE)
    assessment = _evaluate(
        terms=(_term(), second),
        observations=(_observed(3.62), _observed(1.10, covenant_id="cov-2")),
    )
    assert "floor-covenant-breach-repeat" in assessment.proposal.applied_floors


@pytest.mark.parametrize(
    ("observed", "threshold", "operator", "expected"),
    [
        (3.50, 3.50, CovenantOperator.LE, True),
        (3.51, 3.50, CovenantOperator.LE, False),
        (3.50, 3.50, CovenantOperator.LT, False),
        (1.25, 1.25, CovenantOperator.GE, True),
        (1.25, 1.25, CovenantOperator.GT, False),
        (1.2500000000001, 1.25, CovenantOperator.EQ, True),
        (1.26, 1.25, CovenantOperator.EQ, False),
    ],
)
def test_the_comparison_operators_are_exact_and_equality_tolerates_a_json_round_trip(
    observed: float, threshold: float, operator: CovenantOperator, expected: bool
) -> None:
    assert passes(observed, threshold, operator) is expected


def test_the_headroom_arithmetic_is_symmetric_so_a_negative_threshold_does_not_invert() -> None:
    assert within_headroom(-3.40, -3.50, 0.05) is True
    assert within_headroom(-2.00, -3.50, 0.05) is False


# --------------------------------------------------------------------------------------- #
# S5/S6: level and change rules
# --------------------------------------------------------------------------------------- #
def test_a_consecutive_period_rule_needs_every_period_to_breach() -> None:
    window = (_metric("net_debt_to_ebitda", 4.20), _metric("net_debt_to_ebitda", 3.90, "2026Q1"))
    assert "fin-leverage-trend" not in _rule_ids(_evaluate(window=window))
    both = (_metric("net_debt_to_ebitda", 4.20), _metric("net_debt_to_ebitda", 4.10, "2026Q1"))
    assert "fin-leverage-trend" in _rule_ids(_evaluate(window=both))


def test_a_short_history_does_not_fire_and_does_not_invent_a_period() -> None:
    assessment = _evaluate(window=(_metric("net_debt_to_ebitda", 4.20),))
    assert "fin-leverage-trend" not in _rule_ids(assessment)


def test_a_change_rule_treats_a_zero_prior_as_absent_rather_than_infinite() -> None:
    window = (
        _metric("ebitda", 3.30, unit="ratio"),
        _metric("ebitda", 0.0, "2026Q1", unit="ratio"),
    )
    assert "fin-ebitda-decline" not in _rule_ids(_evaluate(window=window))


def test_a_ratio_metric_is_compared_proportionally_and_others_absolutely() -> None:
    ratio = (
        _metric("ebitda", 3.30, unit="ratio"),
        _metric("ebitda", 5.00, "2026Q1", unit="ratio"),
    )
    assert "fin-ebitda-decline" in _rule_ids(_evaluate(window=ratio))
    absolute = (
        _metric("revolver_utilisation_pct", 88.0),
        _metric("revolver_utilisation_pct", 79.0, "2026Q1"),
    )
    assert "beh-utilisation-jump" not in _rule_ids(_evaluate(window=absolute))


# --------------------------------------------------------------------------------------- #
# S7: the external gate, twice
# --------------------------------------------------------------------------------------- #
def test_only_a_feed_confirmed_item_can_fire_an_external_rule() -> None:
    """The second falsification case. Drop the relevance gate and this scores 20."""
    unconfirmed = _evaluate(news=(_news(NewsRelevance.UNCONFIRMED),))
    assert "ext-insolvency" not in _rule_ids(unconfirmed)
    assert unconfirmed.composite_score == 0
    assert unconfirmed.confirmation_requested == ("news-1",)
    assert unconfirmed.requires_human_review is False

    confirmed = _evaluate(news=(_news(NewsRelevance.CONFIRMED),))
    assert "ext-insolvency" in _rule_ids(confirmed)
    assert confirmed.confirmation_requested == ()


def test_a_dismissed_item_fires_nothing_either() -> None:
    assessment = _evaluate(news=(_news(NewsRelevance.DISMISSED),))
    assert assessment.composite_score == 0


def test_an_unclear_category_fires_nothing() -> None:
    item = _news(NewsRelevance.CONFIRMED, NewsCategory.UNCLEAR)
    assert _evaluate(news=(item,)).composite_score == 0


def test_an_item_outside_the_retrieval_window_fires_nothing() -> None:
    old = replace(_news(NewsRelevance.CONFIRMED), published_on=date(2024, 1, 1))
    assert _evaluate(news=(old,)).composite_score == 0


def test_an_external_signal_carries_the_items_own_locator() -> None:
    assessment = _evaluate(news=(_news(NewsRelevance.CONFIRMED),))
    signal = next(s for s in assessment.signals if s.rule_id == "ext-insolvency")
    assert {c.source_id for c in signal.citations} >= {"media:news-1", "ews-policy:ext-insolvency"}


def test_an_item_with_no_locator_raises_rather_than_scoring_zero() -> None:
    item = replace(_news(NewsRelevance.CONFIRMED), citation=Citation(source_id="", title="x"))
    with pytest.raises(UngroundedSignalError):
        _evaluate(news=(item,))


def test_no_external_signal_ever_sets_a_floor() -> None:
    items = tuple(
        replace(_news(NewsRelevance.CONFIRMED, category), item_id=f"news-{index}")
        for index, category in enumerate(
            (NewsCategory.INSOLVENCY, NewsCategory.LITIGATION, NewsCategory.RATING_DOWNGRADE)
        )
    )
    assessment = _evaluate(news=items)
    assert assessment.proposal.applied_floors == ()
    assert assessment.proposal.proposed_grade is WatchGrade.PASS


def test_the_external_cap_keeps_categorised_media_below_the_first_adverse_band() -> None:
    """The third falsification case: raise the cap to 44 and this proposes a downgrade."""
    items = tuple(
        replace(_news(NewsRelevance.CONFIRMED, category), item_id=f"news-{index}")
        for index, category in enumerate(
            (NewsCategory.INSOLVENCY, NewsCategory.LITIGATION, NewsCategory.RATING_DOWNGRADE)
        )
    )
    assessment = _evaluate(news=items)
    external = next(s for s in assessment.family_scores if s.family.value == "external")
    assert external.raw_weight == 44
    assert external.capped_weight == 20
    assert assessment.composite_score == 20
    assert assessment.proposal.band_grade is WatchGrade.PASS

    uncapped = replace(
        DEFAULT_POLICY,
        family_caps={**DEFAULT_POLICY.family_caps, SignalFamily.EXTERNAL: 44},
    )
    lifted = _evaluate(news=items, policy=uncapped)
    assert lifted.proposal.proposed_grade is WatchGrade.SPECIAL_MENTION, (
        "with the cap lifted, categorised media alone classifies the obligor, which is the "
        "configuration validate_policy refuses at load"
    )


# --------------------------------------------------------------------------------------- #
# S9/S10: the review clock and data coverage
# --------------------------------------------------------------------------------------- #
def test_an_absent_review_is_a_worse_finding_than_a_late_one() -> None:
    absent = _evaluate(obligor=_obligor(last_review_on=None))
    overdue = _evaluate(obligor=_obligor(last_review_on=date(2025, 1, 1)))
    absent_signal = next(s for s in absent.signals if s.rule_id == "ews-review-absent")
    overdue_signal = next(s for s in overdue.signals if s.rule_id == "ews-review-overdue")
    assert absent_signal.severity is Severity.HIGH
    assert overdue_signal.severity is Severity.MEDIUM
    assert absent_signal.weight == overdue_signal.weight, "the difference is severity, not weight"


@pytest.mark.parametrize(("age_days", "fires"), [(364, False), (365, False), (366, True)])
def test_the_annual_review_clock_lands_exactly_on_its_boundary(age_days: int, fires: bool) -> None:
    obligor = _obligor(last_review_on=AS_OF - timedelta(days=age_days))
    assert ("ews-review-overdue" in _rule_ids(_evaluate(obligor=obligor))) is fires


def test_a_leap_day_does_not_move_a_clock() -> None:
    """2028 is a leap year, so a naive 365-day arithmetic would report 365 where 366 elapsed."""
    as_of = date(2029, 3, 1)
    obligor = _obligor(last_review_on=as_of - timedelta(days=366))
    assert "ews-review-overdue" in _rule_ids(_evaluate(obligor=obligor, as_of=as_of))
    assert (as_of - date(2028, 2, 29)).days == 366


def test_data_completeness_counts_closed_terms_and_required_metrics() -> None:
    assessment = _evaluate(terms=(_term(),), observations=(_observed(2.10),))
    assert assessment.data_completeness == 1.0
    assert "ews-data-coverage-insufficient" not in _rule_ids(assessment)


def test_thin_coverage_fires_and_reaches_a_human_without_classifying_the_obligor() -> None:
    term_two = _term(covenant_id="cov-2", certificate_due_on=date(2026, 4, 20))
    assessment = _evaluate(
        terms=(_term(certificate_due_on=date(2026, 4, 20)), term_two),
        window=(_metric("revolver_utilisation_pct", 55.0), _metric("dscr", 1.9)),
    )
    assert assessment.data_completeness == 0.25
    assert "ews-data-coverage-insufficient" in _rule_ids(assessment)
    assert "data-coverage-insufficient" in assessment.review_reasons
    assert assessment.proposal.applied_floors == ()
    assert assessment.proposal.movement is Movement.AFFIRM
    assert assessment.requires_human_review is True


def test_a_thin_file_can_never_classify_an_obligor_on_its_own() -> None:
    """The process family is capped below the first adverse band, by construction."""
    assessment = _evaluate(
        terms=tuple(
            _term(covenant_id=f"cov-{n}", certificate_due_on=date(2026, 4, 20)) for n in range(8)
        ),
        obligor=_obligor(last_review_on=None),
        window=(),
    )
    process = next(s for s in assessment.family_scores if s.family.value == "process")
    assert process.raw_weight > process.capped_weight
    assert assessment.composite_score < 35
    assert assessment.proposal.proposed_grade is WatchGrade.PASS


# --------------------------------------------------------------------------------------- #
# S13/S14: floors, the ceiling and movement
# --------------------------------------------------------------------------------------- #
def test_every_floor_that_applied_is_listed_not_only_the_winner() -> None:
    assessment = _evaluate(
        terms=(_term(),),
        observations=(_observed(3.62),),
        arrears=_arrears(96, 90_000_000, drawn=1_000_000_000),
    )
    assert assessment.proposal.applied_floors == (
        "floor-covenant-breach",
        "floor-arrears-sicr",
        "floor-arrears-default",
    )
    assert assessment.proposal.proposed_grade is WatchGrade.SUBSTANDARD


def test_a_downgrade_is_uncapped_and_may_jump_several_rungs() -> None:
    assessment = _evaluate(arrears=_arrears(200, 90_000_000, drawn=1_000_000_000))
    assert assessment.proposal.movement is Movement.DOWNGRADE
    assert assessment.proposal.notches == 3
    assert assessment.proposal.proposed_grade is WatchGrade.DOUBTFUL


_LOSS_FLOOR_POLICY = replace(
    DEFAULT_POLICY,
    floor_grades={**DEFAULT_POLICY.floor_grades, "floor-arrears-severe": WatchGrade.LOSS},
)


def test_loss_is_unproposable_and_the_ceiling_records_that_it_bound() -> None:
    """A write-off is an impairment-committee determination, not an early-warning output."""
    assessment = _evaluate(
        arrears=_arrears(200, 90_000_000, drawn=1_000_000_000), policy=_LOSS_FLOOR_POLICY
    )
    assert assessment.proposal.proposed_grade is WatchGrade.DOUBTFUL
    assert assessment.proposal.applied_ceiling == "ceiling-no-loss-proposal"


def test_a_current_grade_of_loss_is_readable_and_is_affirmed_rather_than_lifted() -> None:
    """The registry holds LOSS, so the engine must be able to read it without raising.

    The ceiling would otherwise turn a write-off into a proposed UPGRADE to doubtful, which the
    upgrade gate refuses on its own terms: this obligor has no clean periods.
    """
    obligor = _obligor(current_grade=WatchGrade.LOSS, clean_periods=0)
    assessment = _evaluate(
        obligor=obligor,
        arrears=_arrears(200, 90_000_000, drawn=1_000_000_000),
        policy=_LOSS_FLOOR_POLICY,
    )
    assert assessment.proposal.current_grade is WatchGrade.LOSS
    assert assessment.proposal.movement is Movement.AFFIRM
    assert assessment.proposal.applied_ceiling == "ceiling-no-loss-proposal"


def test_an_upgrade_needs_positive_evidence_and_not_merely_silence() -> None:
    """A thin file must never propose an improvement."""
    obligor = _obligor(current_grade=WatchGrade.SUBSTANDARD, clean_periods=3)
    thin = _evaluate(
        obligor=obligor,
        terms=(_term(certificate_due_on=date(2026, 4, 20)),),
        window=(_metric("dscr", 1.92),),
    )
    assert thin.proposal.movement is Movement.AFFIRM
    assert thin.proposal.withheld_reason == "upgrade-withheld-insufficient-evidence"


def test_an_upgrade_is_withheld_on_too_few_clean_periods() -> None:
    obligor = _obligor(current_grade=WatchGrade.SPECIAL_MENTION, clean_periods=1)
    assessment = _evaluate(obligor=obligor)
    assert assessment.proposal.movement is Movement.AFFIRM
    assert assessment.proposal.proposed_grade is WatchGrade.SPECIAL_MENTION
    assert assessment.proposal.withheld_reason == "upgrade-withheld-insufficient-clean-periods"
    assert "adverse-classified-periodic-review" in assessment.review_reasons


def test_an_allowed_upgrade_is_capped_at_one_notch() -> None:
    obligor = _obligor(current_grade=WatchGrade.SUBSTANDARD, clean_periods=3)
    assessment = _evaluate(obligor=obligor)
    assert assessment.proposal.movement is Movement.UPGRADE
    assert assessment.proposal.notches == 1
    assert assessment.proposal.proposed_grade is WatchGrade.SPECIAL_MENTION


def test_an_upgrade_is_withheld_while_a_high_severity_signal_is_live() -> None:
    obligor = _obligor(current_grade=WatchGrade.SUBSTANDARD, clean_periods=3)
    assessment = _evaluate(obligor=obligor, news=(_news(NewsRelevance.CONFIRMED),))
    assert assessment.proposal.withheld_reason == "upgrade-withheld-active-signal"


# --------------------------------------------------------------------------------------- #
# S15/S16: the review requirement, grounding and determinism
# --------------------------------------------------------------------------------------- #
def test_a_clean_obligor_produces_no_review_at_all() -> None:
    assessment = _evaluate()
    assert assessment.decision is Decision.ALLOWED
    assert assessment.requires_human_review is False
    assert assessment.review_reasons == ()


def test_every_review_reason_is_a_rule_id_the_reader_can_look_up() -> None:
    assessment = _evaluate(terms=(_term(),), observations=(_observed(3.62),))
    assert set(assessment.review_reasons) == {
        "regrade-proposed",
        "adverse-classified-periodic-review",
        "covenant-breach",
        "high-severity-signal",
    }


def test_an_uncited_covenant_test_raises_rather_than_being_scored() -> None:
    with pytest.raises(UngroundedSignalError):
        _evaluate(terms=(_term(citations=()),), observations=(_observed(3.62, citations=()),))


def test_the_result_citations_are_deduplicated_and_ordered_by_first_appearance() -> None:
    assessment = _evaluate(terms=(_term(),), observations=(_observed(3.62),))
    ids = [c.source_id for c in assessment.citations]
    assert ids == list(dict.fromkeys(ids))
    assert ids[0] == "doc2:fac-1:cov-1", "the origination locator comes first"


def test_the_engine_is_replayable() -> None:
    def once() -> EarlyWarningAssessment:
        return _evaluate(
            terms=(_term(),),
            observations=(_observed(3.62),),
            arrears=_arrears(96, 90_000_000, drawn=1_000_000_000),
        )

    assert once() == once()
