"""The deterministic early-warning engine: a pure function of its inputs and the policy.

One public method, :meth:`EarlyWarningEngine.evaluate`. It has no clock, no I/O, no randomness,
no model, no network and no settings object: an explicit ``as_of`` comes in with the data, and
the same inputs produce the same grade proposal, the same integer composite, the same floor rule
ids and the same review reasons on any machine, a year later.

That is not a stylistic preference. A supervisor or a second-line credit reviewer asking why an
obligor moved to substandard on a particular date must get an answer that does not depend on
which model version answered that day. Three choices protect it: weights and caps are INTEGERS,
so no band edge is decided by float drift; covenant observations are matched by id and period
and metric observations by a declared total order, so equal-dated inputs cannot reorder between
runs; and every threshold is bank-owned configuration in ``policy.py``.

The rule ids below are the vocabulary the whole repo shares. Reading order matters:

* **S1** arrears materiality runs FIRST and gates every past-due rule and every past-due floor;
* **S2/S3/S4** the covenant ladder, one status per term, first match wins;
* **S5/S6/S7** the level, change and external signal rules;
* **S8/S9/S10** the past-due clock, the review clock and data coverage;
* **S11/S12/S13** family fusion with caps, the band lookup, then the floors and the ceiling;
* **S14/S15/S16** movement, the review requirement, severity and the grounding check.

What this module may NOT read is the obligor's exposure figure. Exposure sets the approval path
in the service and nothing else, because a grade that moved with facility size would be gameable
by splitting facilities. ``tests/unit/test_engine_never_reads_exposure.py`` greps this file.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from .errors import UngroundedSignalError
from .kernel import Citation, Decision, Severity
from .models import (
    GRADE_RANK,
    AdverseNewsItem,
    ArrearsSnapshot,
    Comparison,
    CovenantObservation,
    CovenantOperator,
    CovenantStatus,
    CovenantTerm,
    CovenantTest,
    EarlyWarningAssessment,
    EarlyWarningSignal,
    FamilyScore,
    GradeProposal,
    Ifrs9Backstop,
    Movement,
    NewsRelevance,
    ObligorRecord,
    SignalFamily,
    SignalObservation,
    WatchGrade,
)
from .policy import (
    ARREARS_DEFAULT,
    ARREARS_SEVERE,
    ARREARS_SICR,
    CEILING_NO_LOSS,
    FLOOR_ARREARS_DEFAULT,
    FLOOR_ARREARS_SEVERE,
    FLOOR_ARREARS_SICR,
    FLOOR_COVENANT_BREACH,
    FLOOR_COVENANT_BREACH_REPEAT,
    FLOOR_RESTRUCTURED,
    EarlyWarningPolicy,
    SignalRule,
)

#: The engine's own severity ordering. Declared here rather than inferred from the enum's
#: declaration order, so a reordering of the taxonomy cannot silently change which severity wins.
SEVERITY_RANK: Mapping[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}

#: The grade each rung reports as its own severity, before the worst fired signal is considered.
GRADE_SEVERITY: Mapping[WatchGrade, Severity] = {
    WatchGrade.PASS: Severity.LOW,
    WatchGrade.SPECIAL_MENTION: Severity.MEDIUM,
    WatchGrade.SUBSTANDARD: Severity.HIGH,
    WatchGrade.DOUBTFUL: Severity.CRITICAL,
    WatchGrade.LOSS: Severity.CRITICAL,
}

#: Relative tolerance for the ``==`` covenant operator, so a float that round-tripped through
#: JSON is never reported as a breach of an equality covenant.
EQ_TOLERANCE = 1e-9

#: The metric a restructuring is published on. A value at or below the window sets the
#: restructured floor.
RESTRUCTURED_METRIC = "restructured_within_days"
RESTRUCTURED_WINDOW_DAYS = 365

#: A metric whose declared unit is this one is compared PROPORTIONALLY by the change rules: the
#: spreading system publishes it on a basis where a period-over-period ratio is the meaningful
#: comparison. Any other unit is compared by absolute difference.
RATIO_UNIT = "ratio"

# Rule ids that are not floors and not policy rows: the covenant ladder, the clocks and the
# coverage rule. Constants because the engine, the tests and the demo all name them.
COVENANT_NOT_DUE = "covenant-not-due"
COVENANT_NOT_EVIDENCED = "covenant-not-evidenced"
COVENANT_STALE = "covenant-stale"
COVENANT_BREACH = "covenant-breach"
COVENANT_BREACH_WAIVER_EXPIRED = "covenant-breach-waiver-expired"
COVENANT_WAIVED = "covenant-breach-waived"
COVENANT_AT_RISK = "covenant-at-risk"
COVENANT_COMPLIANT = "covenant-compliant"
ARREARS_IMMATERIAL = "ews-arrears-immaterial"
ARREARS_NOT_EVIDENCED = "ews-arrears-not-evidenced"
REVIEW_OVERDUE = "ews-review-overdue"
REVIEW_ABSENT = "ews-review-absent"
COVERAGE_INSUFFICIENT = "ews-data-coverage-insufficient"

# Review reason ids (S15). They are what reaches the officer as "why this is in front of me".
REASON_REGRADE = "regrade-proposed"
REASON_ADVERSE_PERIODIC = "adverse-classified-periodic-review"
REASON_COVENANT_BREACH = "covenant-breach"
REASON_WAIVER_EXPIRING = "waiver-expiring"
REASON_COVERAGE = "data-coverage-insufficient"
REASON_ARREARS_UNEVIDENCED = "arrears-not-evidenced"
REASON_HIGH_SEVERITY = "high-severity-signal"

# Withheld-upgrade reasons (S14).
WITHHELD_CLEAN_PERIODS = "upgrade-withheld-insufficient-clean-periods"
WITHHELD_ACTIVE_SIGNAL = "upgrade-withheld-active-signal"
WITHHELD_COVENANT_BREACH = "upgrade-withheld-covenant-breach"
WITHHELD_EVIDENCE = "upgrade-withheld-insufficient-evidence"

#: How many citations the result carries. Enough to trace the decision without copying the whole
#: evidence set onto every downstream payload.
MAX_RESULT_CITATIONS = 12

#: Citations whose source id starts with this are the POLICY ROW a rule derives from. They are
#: half of the grounding requirement; the other half is a locator for the figure the rule fired
#: on, because a claim about an observed value grounded on the policy row alone is not something
#: a reviewer can follow.
POLICY_SOURCE_PREFIX = "ews-policy"

#: The two rules that are findings about ABSENT evidence, and therefore cannot carry a source
#: locator: the whole finding is that there is no source to point at. Named here so the exemption
#: is a decision somebody made and can be argued with, rather than a hole in the check.
GROUNDING_EXEMPT: frozenset[str] = frozenset({COVERAGE_INSUFFICIENT, ARREARS_NOT_EVIDENCED})


def passes(observed: float, threshold: float, operator: CovenantOperator) -> bool:
    """Compare an observed covenant value against its threshold. The only place this is decided.

    ``==`` compares with a relative tolerance, because a float that has been through JSON is not
    bit-identical to the one that was extracted and reporting that as a breach would be a defect
    dressed as a finding.
    """
    if operator is CovenantOperator.LE:
        return observed <= threshold
    if operator is CovenantOperator.LT:
        return observed < threshold
    if operator is CovenantOperator.GE:
        return observed >= threshold
    if operator is CovenantOperator.GT:
        return observed > threshold
    return abs(observed - threshold) <= abs(threshold) * EQ_TOLERANCE


def within_headroom(observed: float, threshold: float, band: float) -> bool:
    """Credit-memo-drafting's own headroom arithmetic, member for member.

    Symmetric ``abs()`` form rather than a per-operator one, so origination and monitoring cannot
    disagree about the same covenant and a negative threshold does not invert the band.
    """
    return abs(observed - threshold) <= abs(threshold) * band


def _worst(severities: Sequence[Severity], floor: Severity = Severity.LOW) -> Severity:
    worst = floor
    for severity in severities:
        if SEVERITY_RANK[severity] > SEVERITY_RANK[worst]:
            worst = severity
    return worst


def _days(later: date, earlier: date) -> int:
    return (later - earlier).days


def _has_locator(citations: Sequence[Citation]) -> bool:
    """True when at least one citation points at a SOURCE rather than at the policy row."""
    return any(
        citation.source_id and not citation.source_id.startswith(POLICY_SOURCE_PREFIX)
        for citation in citations
    )


class EarlyWarningEngine:
    """Turn one obligor's evidence into a cited, grounded watchlist grade PROPOSAL.

    Nothing here applies a grade, and nothing here decides an impairment stage or an allowance.
    The engine flags the IFRS 9 presumptions and leaves the rebuttal, the classification and the
    provisioning to the people whose job they are.
    """

    def evaluate(
        self,
        obligor: ObligorRecord,
        terms: Sequence[CovenantTerm],
        covenant_observations: Sequence[CovenantObservation],
        arrears: ArrearsSnapshot | None,
        observations: Sequence[SignalObservation],
        news: Sequence[AdverseNewsItem],
        *,
        policy: EarlyWarningPolicy,
        as_of: date,
    ) -> EarlyWarningAssessment:
        signals: list[EarlyWarningSignal] = []
        review_reasons: list[str] = []

        # S1: arrears materiality first, so every past-due rule and floor below reads the
        # EFFECTIVE clock and never the raw figure.
        effective_days, material, arrears_signal = self._arrears_gate(arrears, policy)
        if arrears_signal is not None:
            signals.append(arrears_signal)
            if arrears_signal.rule_id == ARREARS_NOT_EVIDENCED:
                review_reasons.append(REASON_ARREARS_UNEVIDENCED)

        # S2/S3/S4: the covenant ladder, then one signal per non-compliant, non-not_due test.
        tests = self._covenant_tests(terms, covenant_observations, policy=policy, as_of=as_of)
        signals.extend(self._covenant_signals(tests))

        # S5/S6/S7: the configured rule set over the observation window and the retrieved media.
        signals.extend(self._rule_signals(observations, news, policy=policy, as_of=as_of))

        # S8: the past-due rules, mutually exclusive, on the effective clock only.
        backstop, arrears_rule = self._arrears_rules(effective_days, arrears, policy)
        if arrears_rule is not None:
            signals.append(arrears_rule)

        # S9: the review clock.
        clock = self._review_clock(obligor, policy=policy, as_of=as_of)
        if clock is not None:
            signals.append(clock)

        # S10: data completeness over the closed covenant terms and the required metrics.
        completeness = self._completeness(tests, observations, policy=policy, as_of=as_of)
        if completeness < policy.min_data_completeness:
            signals.append(self._coverage_signal(completeness, policy))
            review_reasons.append(REASON_COVERAGE)

        # S16 (first half): grounding is checked BEFORE anything is scored, so an uncited claim
        # cannot reach a composite at all.
        self._require_grounding(tests, signals)

        # S11/S12/S13/S14: fusion, band, floors and ceiling, then movement.
        family_scores, composite = self._fuse(signals, policy)
        band = self._band(composite, policy)
        floors = self._floors(terms, tests, effective_days, observations, policy)
        proposal = self._proposal(
            obligor,
            band=band,
            floors=floors,
            signals=signals,
            tests=tests,
            completeness=completeness,
            policy=policy,
        )

        # S15: the review requirement, and the rule ids that produced it.
        review_reasons.extend(
            self._review_reasons(proposal, tests, signals, policy=policy, as_of=as_of)
        )
        ordered_reasons = tuple(dict.fromkeys(review_reasons))
        requires_review = bool(ordered_reasons)

        severity = _worst(
            [signal.severity for signal in signals],
            floor=GRADE_SEVERITY[proposal.proposed_grade],
        )
        test_period = self._test_period(terms, covenant_observations)
        confirmation = tuple(
            item.item_id for item in news if item.relevance is not NewsRelevance.CONFIRMED
        )
        return EarlyWarningAssessment(
            obligor_id=obligor.obligor_id,
            obligor_name=obligor.name,
            as_of=as_of,
            test_period=test_period,
            composite_score=composite,
            family_scores=family_scores,
            covenant_tests=tests,
            signals=tuple(signals),
            proposal=proposal,
            effective_days_past_due=effective_days,
            arrears_material=material,
            staging_backstop=backstop,
            unlikely_to_pay=backstop is Ifrs9Backstop.DEFAULT_PRESUMPTION,
            presumption_rebuttable=backstop is not Ifrs9Backstop.NONE,
            data_completeness=completeness,
            confirmation_requested=confirmation,
            severity=severity,
            decision=Decision.ESCALATED if requires_review else Decision.ALLOWED,
            requires_human_review=requires_review,
            review_reasons=ordered_reasons,
            summary=self._summary(obligor, proposal, composite, test_period),
            evidence_counts=(
                ("covenant_terms", len(terms)),
                ("covenant_observations", len(covenant_observations)),
                ("signal_observations", len(observations)),
                ("news_items", len(news)),
            ),
            citations=self._result_citations(tests, signals),
        )

    # ------------------------------------------------------------------ S1
    def _arrears_gate(
        self, arrears: ArrearsSnapshot | None, policy: EarlyWarningPolicy
    ) -> tuple[int, bool, EarlyWarningSignal | None]:
        """The effective past-due clock, and the record of what was considered.

        A snapshot that is absent is a FINDING, not a zero. A snapshot showing arrears that clear
        neither materiality leg stops the clock, and the non-firing is recorded as a zero-weight
        signal naming both limits and both observed values: a second-line reviewer asks what you
        considered, and a silent pass destroys that.
        """
        if arrears is None:
            return (
                0,
                False,
                EarlyWarningSignal(
                    rule_id=ARREARS_NOT_EVIDENCED,
                    family=SignalFamily.PROCESS,
                    severity=Severity.MEDIUM,
                    weight=0,
                    metric="days_past_due",
                    comparison=Comparison.PRESENT,
                    observed_value=None,
                    threshold=None,
                    periods_tested=0,
                    detail=(
                        "no arrears snapshot was returned for this obligor, so the past-due "
                        "rules had nothing to test"
                    ),
                    evidence_ref="",
                    citations=(policy.citations[0],),
                ),
            )
        if arrears.days_past_due <= 0 and arrears.past_due_amount_minor <= 0:
            return (0, False, None)
        relative_limit = int(arrears.drawn_amount_minor * policy.arrears_materiality_relative_pct)
        absolute_ok = arrears.past_due_amount_minor >= policy.arrears_materiality_absolute_minor
        relative_ok = arrears.past_due_amount_minor >= relative_limit
        if absolute_ok and relative_ok:
            return (arrears.days_past_due, True, None)
        return (
            0,
            False,
            EarlyWarningSignal(
                rule_id=ARREARS_IMMATERIAL,
                family=SignalFamily.PROCESS,
                severity=Severity.LOW,
                weight=0,
                metric="past_due_amount_minor",
                comparison=Comparison.MIN,
                observed_value=float(arrears.past_due_amount_minor),
                threshold=float(max(policy.arrears_materiality_absolute_minor, relative_limit)),
                periods_tested=1,
                detail=(
                    f"past due {arrears.past_due_amount_minor} minor units at "
                    f"{arrears.days_past_due} days, against an absolute limit of "
                    f"{policy.arrears_materiality_absolute_minor} and a relative limit of "
                    f"{relative_limit}; the clock did not start"
                ),
                evidence_ref=arrears.source_ref,
                citations=(policy.citations[0], *arrears.citations),
            ),
        )

    # ------------------------------------------------------------------ S2/S3
    def _covenant_tests(
        self,
        terms: Sequence[CovenantTerm],
        observations: Sequence[CovenantObservation],
        *,
        policy: EarlyWarningPolicy,
        as_of: date,
    ) -> tuple[CovenantTest, ...]:
        """One status per term, first match wins, total with no tie-break.

        Selection is by ``covenant_id`` plus ``test_period``, so two equally dated observations
        can never reorder between runs. The ladder resolves the UNEVIDENCED states first: a term
        with no usable observation is either NOT DUE (its period is still open, or its
        certificate grace has not elapsed) or NOT EVIDENCED. A term that HAS a usable observation
        is tested on it, whatever the calendar says, because an observed breach is a fact.
        """
        index: dict[tuple[str, str], CovenantObservation] = {}
        for observation in observations:
            index[(observation.covenant_id, observation.test_period)] = observation
        return tuple(
            self._one_covenant_test(
                term,
                index.get((term.covenant_id, term.test_period)),
                policy=policy,
                as_of=as_of,
            )
            for term in terms
        )

    def _one_covenant_test(
        self,
        term: CovenantTerm,
        observation: CovenantObservation | None,
        *,
        policy: EarlyWarningPolicy,
        as_of: date,
    ) -> CovenantTest:
        band = term.headroom_band if term.headroom_band is not None else policy.headroom_band
        value = observation.observed_value if observation else None
        received = observation.certificate_received_on if observation else None
        certificate_age = (
            _days(as_of, term.certificate_due_on) if term.certificate_due_on is not None else None
        )

        if value is None:
            # COV-1 / COV-2: nothing usable was received, so the only question is whether it was
            # DUE yet. A mid-period sweep must not read as a file nobody evidenced.
            open_period = term.period_end is not None and term.period_end > as_of
            in_grace = (
                term.certificate_due_on is not None
                and _days(as_of, term.certificate_due_on) < policy.certificate_grace_days
            )
            not_due = open_period or in_grace
            status = CovenantStatus.NOT_DUE if not_due else CovenantStatus.NOT_EVIDENCED
            rule_id = COVENANT_NOT_DUE if not_due else COVENANT_NOT_EVIDENCED
            detail = (
                f"{term.metric} for {term.test_period} is not yet due"
                if status is CovenantStatus.NOT_DUE
                else (
                    f"{term.metric} for {term.test_period} has no compliance certificate; "
                    f"the certificate is {certificate_age} days past its due date"
                )
            )
            return self._covenant_test(
                term, status, rule_id, detail, policy, value, received, certificate_age, None, band
            )

        # COV-3: an observation exists, but it is too old to describe the obligor today.
        lag_from = received or term.period_end
        if lag_from is not None and _days(as_of, lag_from) > policy.max_reporting_lag_days:
            detail = (
                f"{term.metric} was last evidenced {_days(as_of, lag_from)} days ago, beyond the "
                f"{policy.max_reporting_lag_days} day reporting-lag limit"
            )
            return self._covenant_test(
                term,
                CovenantStatus.STALE,
                COVENANT_STALE,
                detail,
                policy,
                value,
                received,
                certificate_age,
                None,
                band,
            )

        headroom = value - term.threshold
        if not passes(value, term.threshold, term.operator):
            waiver_live = (
                bool(term.waiver_reference)
                and term.waiver_expiry is not None
                and term.waiver_expiry >= as_of
            )
            if waiver_live:
                detail = (
                    f"{term.metric} observed {value} against {term.operator.value} "
                    f"{term.threshold}, waived under {term.waiver_reference} until "
                    f"{term.waiver_expiry}"
                )
                return self._covenant_test(
                    term,
                    CovenantStatus.WAIVED,
                    COVENANT_WAIVED,
                    detail,
                    policy,
                    value,
                    received,
                    certificate_age,
                    headroom,
                    band,
                    evidence_ref=term.waiver_reference,
                )
            # An EXPIRED waiver is not a waiver, and it is visibly different from a term that
            # never had one: the status stays breach and the rule id says why.
            expired = bool(term.waiver_reference) and term.waiver_expiry is not None
            rule_id = COVENANT_BREACH_WAIVER_EXPIRED if expired else COVENANT_BREACH
            expiry_note = (
                f", waiver {term.waiver_reference} expired {term.waiver_expiry}" if expired else ""
            )
            detail = (
                f"{term.metric} observed {value} against {term.operator.value} "
                f"{term.threshold}{expiry_note}"
            )
            return self._covenant_test(
                term,
                CovenantStatus.BREACH,
                rule_id,
                detail,
                policy,
                value,
                received,
                certificate_age,
                headroom,
                band,
            )

        if within_headroom(value, term.threshold, band):
            detail = (
                f"{term.metric} observed {value} against {term.operator.value} {term.threshold}, "
                f"inside the headroom band"
            )
            return self._covenant_test(
                term,
                CovenantStatus.AT_RISK,
                COVENANT_AT_RISK,
                detail,
                policy,
                value,
                received,
                certificate_age,
                headroom,
                band,
            )

        detail = (
            f"{term.metric} observed {value} against {term.operator.value} {term.threshold}, "
            f"outside the headroom band"
        )
        return self._covenant_test(
            term,
            CovenantStatus.COMPLIANT,
            COVENANT_COMPLIANT,
            detail,
            policy,
            value,
            received,
            certificate_age,
            headroom,
            band,
        )

    def _covenant_test(
        self,
        term: CovenantTerm,
        status: CovenantStatus,
        rule_id: str,
        detail: str,
        policy: EarlyWarningPolicy,
        value: float | None,
        received: date | None,
        certificate_age: int | None,
        headroom: float | None,
        band: float,
        *,
        evidence_ref: str = "",
    ) -> CovenantTest:
        weight, severity, family = policy.covenant_weights[status]
        citations = (*term.citations, policy.citations[0])
        # The clause TEXT travels on the detail, not only the metric name, because that is what a
        # credit officer reads and because a clause naming a guarantor is exactly where personal
        # data enters a credit file. The redaction seam at the service edge is what masks it.
        described = f"{term.description}: {detail}" if term.description else detail
        return CovenantTest(
            covenant_id=term.covenant_id,
            type=term.type,
            status=status,
            threshold=term.threshold,
            operator=term.operator,
            observed_value=value,
            test_period=term.test_period,
            observed_on=received,
            certificate_age_days=certificate_age,
            headroom=headroom,
            waived_until=term.waiver_expiry if status is CovenantStatus.WAIVED else None,
            family=family,
            severity=severity,
            weight=weight,
            rule_id=rule_id,
            detail=described + (f" [{evidence_ref}]" if evidence_ref else ""),
            citations=citations,
        )

    # ------------------------------------------------------------------ S4
    def _covenant_signals(self, tests: Sequence[CovenantTest]) -> list[EarlyWarningSignal]:
        out: list[EarlyWarningSignal] = []
        for test in tests:
            if test.status in (CovenantStatus.COMPLIANT, CovenantStatus.NOT_DUE):
                continue
            out.append(
                EarlyWarningSignal(
                    rule_id=test.rule_id,
                    family=test.family,
                    severity=test.severity,
                    weight=test.weight,
                    metric=test.covenant_id,
                    comparison=Comparison.PRESENT,
                    observed_value=test.observed_value,
                    threshold=test.threshold,
                    periods_tested=1,
                    detail=test.detail,
                    evidence_ref=test.covenant_id,
                    citations=test.citations,
                )
            )
        return out

    # ------------------------------------------------------------------ S5/S6/S7
    def _rule_signals(
        self,
        observations: Sequence[SignalObservation],
        news: Sequence[AdverseNewsItem],
        *,
        policy: EarlyWarningPolicy,
        as_of: date,
    ) -> list[EarlyWarningSignal]:
        by_metric = self._ordered_by_metric(observations)
        out: list[EarlyWarningSignal] = []
        for rule in policy.signal_rules:
            if rule.comparison is Comparison.PRESENT:
                out.extend(self._external_signals(rule, news, policy=policy, as_of=as_of))
                continue
            series = by_metric.get(rule.metric, ())
            signal = (
                self._level_signal(rule, series)
                if rule.comparison in (Comparison.MAX, Comparison.MIN)
                else self._change_signal(rule, series)
            )
            if signal is not None:
                out.append(signal)
        return out

    @staticmethod
    def _ordered_by_metric(
        observations: Sequence[SignalObservation],
    ) -> dict[str, tuple[SignalObservation, ...]]:
        """Newest first, by a DECLARED total order, so equal-dated inputs cannot reorder."""
        grouped: dict[str, list[SignalObservation]] = {}
        for observation in observations:
            grouped.setdefault(observation.metric, []).append(observation)
        return {
            metric: tuple(
                sorted(rows, key=lambda o: (o.as_of, o.period, o.source_ref), reverse=True)
            )
            for metric, rows in grouped.items()
        }

    def _level_signal(
        self, rule: SignalRule, series: Sequence[SignalObservation]
    ) -> EarlyWarningSignal | None:
        """S5: fire only when EVERY one of the most recent N periods breaches.

        Fewer observations than the rule asks for does NOT fire and does not invent a period.
        A short history reading as a pass is what the coverage rule exists to catch instead.
        """
        if rule.threshold is None or len(series) < rule.consecutive_periods:
            return None
        window = series[: rule.consecutive_periods]
        breached = all(
            (row.value > rule.threshold)
            if rule.comparison is Comparison.MAX
            else (row.value < rule.threshold)
            for row in window
        )
        if not breached:
            return None
        latest = window[0]
        return self._rule_signal(
            rule,
            observed=latest.value,
            periods=len(window),
            detail=(
                f"{rule.metric} {latest.value} against {rule.comparison.value} "
                f"{rule.threshold} over {len(window)} consecutive periods"
            ),
            evidence_ref=latest.source_ref,
            extra=latest.citations,
        )

    def _change_signal(
        self, rule: SignalRule, series: Sequence[SignalObservation]
    ) -> EarlyWarningSignal | None:
        """S6: period-over-period change. A zero or absent prior is ABSENT, never infinite."""
        if rule.threshold is None or len(series) < 2:
            return None
        latest, prior = series[0], series[1]
        if latest.unit == RATIO_UNIT:
            if prior.value == 0:
                return None
            delta = (latest.value - prior.value) / abs(prior.value)
        else:
            delta = latest.value - prior.value
        fired = (
            delta > rule.threshold
            if rule.comparison is Comparison.DELTA_MAX
            else delta < rule.threshold
        )
        if not fired:
            return None
        return self._rule_signal(
            rule,
            observed=round(delta, 4),
            periods=2,
            detail=(
                f"{rule.metric} moved {round(delta, 4)} against {rule.comparison.value} "
                f"{rule.threshold} between {prior.period} and {latest.period}"
            ),
            evidence_ref=latest.source_ref,
            extra=(*latest.citations, *prior.citations),
        )

    def _external_signals(
        self,
        rule: SignalRule,
        news: Sequence[AdverseNewsItem],
        *,
        policy: EarlyWarningPolicy,
        as_of: date,
    ) -> list[EarlyWarningSignal]:
        """S7: gated TWICE. The FEED asserts relevance; the model may only assign the category.

        An unconfirmed or dismissed item can never fire a rule, whatever its category, because
        entity resolution on a common company name is the classic adverse-media false positive.
        An item that fires carries its own locator as a Citation, and one that cannot is a hard
        error rather than a silent zero.
        """
        out: list[EarlyWarningSignal] = []
        for item in news:
            if item.relevance is not NewsRelevance.CONFIRMED:
                continue
            if item.category.value != rule.metric:
                continue
            if _days(as_of, item.published_on) > policy.max_news_lookback_days:
                continue
            if not item.citation.source_id:
                raise UngroundedSignalError(
                    f"{rule.rule_id}: adverse-media item {item.item_id!r} carries no locator"
                )
            out.append(
                self._rule_signal(
                    rule,
                    observed=None,
                    periods=1,
                    detail=(
                        f"{item.category.value} item {item.item_id} confirmed by the feed, "
                        f"published {item.published_on}: {item.headline}"
                    ),
                    evidence_ref=item.item_id,
                    extra=(item.citation,),
                )
            )
        return out

    @staticmethod
    def _rule_signal(
        rule: SignalRule,
        *,
        observed: float | None,
        periods: int,
        detail: str,
        evidence_ref: str,
        extra: Sequence[Citation],
    ) -> EarlyWarningSignal:
        return EarlyWarningSignal(
            rule_id=rule.rule_id,
            family=rule.family,
            severity=rule.severity,
            weight=rule.weight,
            metric=rule.metric,
            comparison=rule.comparison,
            observed_value=observed,
            threshold=rule.threshold,
            periods_tested=periods,
            detail=detail,
            evidence_ref=evidence_ref,
            citations=(rule.citation, *extra),
        )

    # ------------------------------------------------------------------ S8
    def _arrears_rules(
        self,
        effective_days: int,
        arrears: ArrearsSnapshot | None,
        policy: EarlyWarningPolicy,
    ) -> tuple[Ifrs9Backstop, EarlyWarningSignal | None]:
        """The IFRS 9 backstops AS PRESUMPTIONS. The engine raises the flag; a human rebuts it.

        No impairment stage is proposed and no allowance is booked: the standard's primary test
        is a relative increase in lifetime probability of default, which needs a PD model this
        repo does not have.

        Three tiers, one selected. The SEVERE tier is the bank's own escalation above the
        ninety-day presumption and not a third stage of the standard, so it changes the weight,
        the severity and the rule id and leaves the BACKSTOP at the default presumption: a
        settings row does not get to restate what the standard presumes. Its floor
        (``floor-arrears-severe``) has always been live, and shipping the weight row beside it
        unread meant an operator retuning that row changed nothing and was told nothing.
        """
        if effective_days >= policy.severe_days_past_due:
            key, rule_id = "severe", ARREARS_SEVERE
            backstop = Ifrs9Backstop.DEFAULT_PRESUMPTION
            threshold = policy.severe_days_past_due
        elif effective_days >= policy.default_days_past_due:
            key, rule_id = "default", ARREARS_DEFAULT
            backstop = Ifrs9Backstop.DEFAULT_PRESUMPTION
            threshold = policy.default_days_past_due
        elif effective_days >= policy.sicr_days_past_due:
            key, rule_id = "sicr", ARREARS_SICR
            backstop = Ifrs9Backstop.SICR_PRESUMPTION
            threshold = policy.sicr_days_past_due
        else:
            return (Ifrs9Backstop.NONE, None)
        weight, severity = policy.arrears_weights[key]
        return (
            backstop,
            EarlyWarningSignal(
                rule_id=rule_id,
                family=SignalFamily.BEHAVIOURAL,
                severity=severity,
                weight=weight,
                metric="effective_days_past_due",
                comparison=Comparison.MAX,
                observed_value=float(effective_days),
                threshold=float(threshold),
                periods_tested=1,
                detail=(
                    f"{effective_days} effective days past due against the {threshold} day "
                    f"presumption; rebuttable by a credit officer, never by this engine"
                ),
                evidence_ref=arrears.source_ref if arrears else "",
                citations=(policy.citations[0], *(arrears.citations if arrears else ())),
            ),
        )

    # ------------------------------------------------------------------ S9
    def _review_clock(
        self, obligor: ObligorRecord, *, policy: EarlyWarningPolicy, as_of: date
    ) -> EarlyWarningSignal | None:
        if obligor.last_review_on is None:
            weight, severity = policy.review_clock_weights["absent"]
            detail = "no completed obligor review is recorded in the rating file"
            observed = None
            rule_id = REVIEW_ABSENT
        else:
            age = _days(as_of, obligor.last_review_on)
            if age <= policy.rating_review_max_age_days:
                return None
            weight, severity = policy.review_clock_weights["overdue"]
            detail = (
                f"the last completed obligor review was {age} days ago, beyond the "
                f"{policy.rating_review_max_age_days} day review clock"
            )
            observed = float(age)
            rule_id = REVIEW_OVERDUE
        return EarlyWarningSignal(
            rule_id=rule_id,
            family=SignalFamily.PROCESS,
            severity=severity,
            weight=weight,
            metric="last_review_on",
            comparison=Comparison.MAX,
            observed_value=observed,
            threshold=float(policy.rating_review_max_age_days),
            periods_tested=1,
            detail=detail,
            evidence_ref=obligor.source,
            citations=(policy.citations[0], *obligor.citations),
        )

    # ------------------------------------------------------------------ S10
    def _completeness(
        self,
        tests: Sequence[CovenantTest],
        observations: Sequence[SignalObservation],
        *,
        policy: EarlyWarningPolicy,
        as_of: date,
    ) -> float:
        closed = [test for test in tests if test.status is not CovenantStatus.NOT_DUE]
        evidenced = [
            test
            for test in closed
            if test.status not in (CovenantStatus.NOT_EVIDENCED, CovenantStatus.STALE)
        ]
        fresh_metrics = {
            observation.metric
            for observation in observations
            if observation.as_of <= as_of
            and _days(as_of, observation.as_of) <= policy.max_reporting_lag_days
        }
        covered = [metric for metric in policy.required_metrics if metric in fresh_metrics]
        denominator = len(closed) + len(policy.required_metrics)
        if denominator == 0:
            return 0.0
        return round((len(evidenced) + len(covered)) / denominator, 4)

    def _coverage_signal(
        self, completeness: float, policy: EarlyWarningPolicy
    ) -> EarlyWarningSignal:
        return EarlyWarningSignal(
            rule_id=COVERAGE_INSUFFICIENT,
            family=SignalFamily.PROCESS,
            severity=Severity.MEDIUM,
            weight=policy.coverage_weight,
            metric="data_completeness",
            comparison=Comparison.MIN,
            observed_value=completeness,
            threshold=policy.min_data_completeness,
            periods_tested=1,
            detail=(
                f"evidence covers {completeness} of the required covenant tests and metrics, "
                f"below the {policy.min_data_completeness} floor"
            ),
            evidence_ref="",
            citations=(policy.citations[0],),
        )

    # ------------------------------------------------------------------ S11/S12
    def _fuse(
        self, signals: Sequence[EarlyWarningSignal], policy: EarlyWarningPolicy
    ) -> tuple[tuple[FamilyScore, ...], int]:
        """Per-family raw and capped weight, and the integer composite.

        The CAPS are the anti-double-counting rule: a covenant breach and a thin-coverage rule
        describing the same fact cannot contribute twice, and neither the model-influenced family
        nor the family that measures our own file can classify an obligor alone.
        """
        scores: list[FamilyScore] = []
        composite = 0
        for family in SignalFamily:
            members = [signal for signal in signals if signal.family is family]
            raw = sum(signal.weight for signal in members)
            cap = policy.family_caps.get(family, 0)
            capped = min(raw, cap)
            composite += capped
            scores.append(
                FamilyScore(
                    family=family,
                    raw_weight=raw,
                    cap=cap,
                    capped_weight=capped,
                    signal_count=len(members),
                )
            )
        return (tuple(scores), min(100, composite))

    @staticmethod
    def _band(composite: int, policy: EarlyWarningPolicy) -> WatchGrade:
        grade = policy.band_floors[0][1]
        for min_score, banded in policy.band_floors:
            if composite >= min_score:
                grade = banded
        return grade

    # ------------------------------------------------------------------ S13
    def _floors(
        self,
        terms: Sequence[CovenantTerm],
        tests: Sequence[CovenantTest],
        effective_days: int,
        observations: Sequence[SignalObservation],
        policy: EarlyWarningPolicy,
    ) -> tuple[str, ...]:
        """EVERY floor that applied, by rule id, not only the one that won.

        A retune that silently changes which rule is deciding is exactly what the eval's
        floor_precision metric has to catch, and it cannot catch it from the grade alone.
        """
        applied: list[str] = []
        breached_ids = {test.covenant_id for test in tests if test.status is CovenantStatus.BREACH}
        if breached_ids:
            applied.append(FLOOR_COVENANT_BREACH)
        # The repeat leg reads the UPSTREAM counter as well as today's sheet: a covenant breached
        # for a second consecutive period is a different finding from two covenants breached once.
        repeat = len(breached_ids) >= 2 or any(
            term.covenant_id in breached_ids and term.consecutive_breaches >= 2 for term in terms
        )
        if breached_ids and repeat:
            applied.append(FLOOR_COVENANT_BREACH_REPEAT)
        if effective_days >= policy.sicr_days_past_due:
            applied.append(FLOOR_ARREARS_SICR)
        if effective_days >= policy.default_days_past_due:
            applied.append(FLOOR_ARREARS_DEFAULT)
        if effective_days >= policy.severe_days_past_due:
            applied.append(FLOOR_ARREARS_SEVERE)
        if any(
            observation.metric == RESTRUCTURED_METRIC
            and observation.value <= RESTRUCTURED_WINDOW_DAYS
            for observation in observations
        ):
            applied.append(FLOOR_RESTRUCTURED)
        return tuple(applied)

    # ------------------------------------------------------------------ S14
    def _proposal(
        self,
        obligor: ObligorRecord,
        *,
        band: WatchGrade,
        floors: Sequence[str],
        signals: Sequence[EarlyWarningSignal],
        tests: Sequence[CovenantTest],
        completeness: float,
        policy: EarlyWarningPolicy,
    ) -> GradeProposal:
        current_rank = GRADE_RANK[obligor.current_grade]
        proposed_rank = GRADE_RANK[band]
        for rule_id in floors:
            proposed_rank = max(proposed_rank, GRADE_RANK[policy.floor_grades[rule_id]])

        ceiling = ""
        if proposed_rank >= GRADE_RANK[WatchGrade.LOSS]:
            # LOSS is READABLE because the registry holds it, and UNPROPOSABLE because a
            # write-off is an impairment-committee determination and not an early-warning output.
            proposed_rank = GRADE_RANK[WatchGrade.DOUBTFUL]
            ceiling = CEILING_NO_LOSS

        withheld = ""
        if proposed_rank < current_rank:
            withheld = self._upgrade_withheld(
                obligor, signals=signals, tests=tests, completeness=completeness, policy=policy
            )
            if withheld:
                proposed_rank = current_rank
            else:
                proposed_rank = max(proposed_rank, current_rank - policy.max_upgrade_notches)

        proposed = self._grade_at(proposed_rank)
        if proposed_rank > current_rank:
            movement, notches = Movement.DOWNGRADE, proposed_rank - current_rank
        elif proposed_rank < current_rank:
            movement, notches = Movement.UPGRADE, current_rank - proposed_rank
        else:
            movement, notches = Movement.AFFIRM, 0
        return GradeProposal(
            current_grade=obligor.current_grade,
            band_grade=band,
            proposed_grade=proposed,
            movement=movement,
            notches=notches,
            applied_floors=tuple(floors),
            applied_ceiling=ceiling,
            withheld_reason=withheld,
        )

    def _upgrade_withheld(
        self,
        obligor: ObligorRecord,
        *,
        signals: Sequence[EarlyWarningSignal],
        tests: Sequence[CovenantTest],
        completeness: float,
        policy: EarlyWarningPolicy,
    ) -> str:
        """Downgrade fast, upgrade slow, and an upgrade rests on POSITIVE evidence.

        The evidence gate is the sharp one: a thin file must never be able to propose an
        improvement, because the absence of signals in a file nobody evidenced is not good news.
        """
        if obligor.clean_periods < policy.upgrade_min_clean_periods:
            return WITHHELD_CLEAN_PERIODS
        if any(
            SEVERITY_RANK[signal.severity] >= SEVERITY_RANK[Severity.HIGH]
            for signal in signals
            if signal.weight > 0
        ):
            return WITHHELD_ACTIVE_SIGNAL
        if any(test.status is CovenantStatus.BREACH for test in tests):
            return WITHHELD_COVENANT_BREACH
        if completeness < policy.upgrade_min_data_completeness:
            return WITHHELD_EVIDENCE
        return ""

    @staticmethod
    def _grade_at(rank: int) -> WatchGrade:
        for grade, value in GRADE_RANK.items():
            if value == rank:
                return grade
        raise ValueError(f"no grade at rank {rank}")  # pragma: no cover - rank is clamped above

    # ------------------------------------------------------------------ S15
    def _review_reasons(
        self,
        proposal: GradeProposal,
        tests: Sequence[CovenantTest],
        signals: Sequence[EarlyWarningSignal],
        *,
        policy: EarlyWarningPolicy,
        as_of: date,
    ) -> list[str]:
        reasons: list[str] = []
        if proposal.movement is not Movement.AFFIRM:
            reasons.append(REASON_REGRADE)
        if GRADE_RANK[proposal.proposed_grade] >= GRADE_RANK[WatchGrade.SPECIAL_MENTION]:
            reasons.append(REASON_ADVERSE_PERIODIC)
        if any(test.status is CovenantStatus.BREACH for test in tests):
            reasons.append(REASON_COVENANT_BREACH)
        if any(
            test.status is CovenantStatus.WAIVED
            and test.waived_until is not None
            and _days(test.waived_until, as_of) <= policy.waiver_expiry_notice_days
            for test in tests
        ):
            reasons.append(REASON_WAIVER_EXPIRING)
        if any(
            SEVERITY_RANK[signal.severity] >= SEVERITY_RANK[policy.gate_severity]
            and signal.weight > 0
            for signal in signals
        ):
            reasons.append(REASON_HIGH_SEVERITY)
        return reasons

    # ------------------------------------------------------------------ S16
    @staticmethod
    def _require_grounding(
        tests: Sequence[CovenantTest], signals: Sequence[EarlyWarningSignal]
    ) -> None:
        """Every fired rule carries BOTH the policy row and a source locator, or the engine raises.

        Scoring an uncited claim zero would put it on the officer's screen beside the traceable
        ones and change the composite by nothing, which is the failure grounding exists to stop.
        The policy row alone is not enough: it says where the THRESHOLD came from and nothing
        about where the FIGURE came from, and a reviewer has to be able to trace both.

        The two rules in :data:`GROUNDING_EXEMPT` are findings about ABSENT evidence, so they
        carry the policy row alone by construction.
        """
        for test in tests:
            if test.status in (CovenantStatus.COMPLIANT, CovenantStatus.NOT_DUE):
                continue
            if not _has_locator(test.citations):
                raise UngroundedSignalError(
                    f"covenant test {test.covenant_id!r} ({test.status.value}) carries no source "
                    "locator, only the policy row it was tested against"
                )
        for signal in signals:
            if not signal.citations:
                raise UngroundedSignalError(f"signal {signal.rule_id!r} carries no citation")
            if signal.rule_id in GROUNDING_EXEMPT:
                continue
            if not _has_locator(signal.citations):
                raise UngroundedSignalError(
                    f"signal {signal.rule_id!r} carries no source locator, only the policy row"
                )

    @staticmethod
    def _result_citations(
        tests: Sequence[CovenantTest], signals: Sequence[EarlyWarningSignal]
    ) -> tuple[Citation, ...]:
        """De-duplicated by source_id, ordered by FIRST APPEARANCE, capped. Deterministic."""
        seen: set[str] = set()
        out: list[Citation] = []
        for citation in [c for test in tests for c in test.citations] + [
            c for signal in signals for c in signal.citations
        ]:
            if citation.source_id in seen:
                continue
            seen.add(citation.source_id)
            out.append(citation)
            if len(out) >= MAX_RESULT_CITATIONS:
                break
        return tuple(out)

    @staticmethod
    def _test_period(
        terms: Sequence[CovenantTerm], observations: Sequence[CovenantObservation]
    ) -> str:
        for term in terms:
            if term.test_period:
                return term.test_period
        for observation in observations:
            if observation.test_period:
                return observation.test_period
        return ""

    @staticmethod
    def _summary(
        obligor: ObligorRecord, proposal: GradeProposal, composite: int, test_period: str
    ) -> str:
        floors = ", ".join(proposal.applied_floors) or "none"
        return (
            f"{obligor.name} ({obligor.obligor_id}) {test_period}: "
            f"{proposal.movement.value} {proposal.current_grade.value} to "
            f"{proposal.proposed_grade.value}, composite {composite}, band "
            f"{proposal.band_grade.value}, floors {floors}"
        )
