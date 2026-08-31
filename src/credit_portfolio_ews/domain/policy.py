"""The bank-owned early-warning policy: every number a credit committee would argue about.

The engine in ``early_warning.py`` is CODE; everything it compares against is CONFIGURATION and
lives here, parsed from the ``policy:`` block of ``config/settings.yaml``. That split is the
point: a bank retunes a band edge, a family cap or a materiality leg without a code change, and
a second-line reviewer can read the numbers without reading the engine.

The shipped defaults are REFERENCE defaults and not a calibrated scorecard. A real early-warning
model is fitted on an institution's own default history and back-tested; this is a policy ladder
somebody chose. Two of the clocks are deliberately the regulatory presumptions themselves (the
thirty-day and ninety-day past-due marks), and the materiality legs mirror the
absolute-plus-relative shape supervisors expect, so a deployment that changes nothing is at
least standing on a documented starting point rather than an invented one.

:func:`validate_policy` refuses at LOAD rather than at first request. The mistake was made
seconds earlier by an operator editing a settings file, so it belongs in the deploy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .kernel import Citation, Severity
from .models import (
    GRADE_RANK,
    Comparison,
    CovenantStatus,
    NewsCategory,
    SignalFamily,
    WatchGrade,
)

#: Every rule this module ships derives from a row of the bank's own early-warning policy. The
#: citation names that row, so a signal the engine fires is grounded by construction and the
#: engine can RAISE rather than emit an uncited claim.
POLICY_CITATION = Citation(
    source_id="ews-policy",
    title="Early-warning and watchlist policy (bank-owned)",
    snippet="thresholds, caps, band floors and clocks are client configuration",
)


def _rule_citation(rule_id: str) -> Citation:
    return Citation(
        source_id=f"ews-policy:{rule_id}",
        title="Early-warning policy row (bank-owned)",
        snippet=f"threshold and weight for {rule_id}",
    )


@dataclass(frozen=True, slots=True)
class SignalRule:
    """One bank-owned early-warning rule. CONFIGURATION, which is why it is not in models.py.

    ``metric`` is a metric name for the level and change comparisons, and a
    :class:`~.models.NewsCategory` value for a ``PRESENT`` rule. ``citation`` has no default:
    a rule that cannot say which policy row it came from cannot be constructed.
    """

    rule_id: str
    family: SignalFamily
    metric: str
    comparison: Comparison
    citation: Citation
    threshold: float | None = None
    consecutive_periods: int = 1
    weight: int = 0
    severity: Severity = Severity.MEDIUM


def default_signal_rules() -> tuple[SignalRule, ...]:
    """The shipped reference rule set, mirrored verbatim in the settings file's policy block.

    ``beh-utilisation-sustained`` is a consecutive-period rule rather than a single-day trigger
    on purpose: one day at the limit is a treasury artefact, not a warning.
    """
    return (
        SignalRule(
            rule_id="fin-leverage-trend",
            family=SignalFamily.FINANCIAL,
            metric="net_debt_to_ebitda",
            comparison=Comparison.MAX,
            threshold=4.00,
            consecutive_periods=2,
            weight=20,
            severity=Severity.HIGH,
            citation=_rule_citation("fin-leverage-trend"),
        ),
        SignalRule(
            rule_id="fin-dscr-thin",
            family=SignalFamily.FINANCIAL,
            metric="dscr",
            comparison=Comparison.MIN,
            threshold=1.20,
            weight=18,
            severity=Severity.MEDIUM,
            citation=_rule_citation("fin-dscr-thin"),
        ),
        SignalRule(
            rule_id="fin-ebitda-decline",
            family=SignalFamily.FINANCIAL,
            metric="ebitda",
            comparison=Comparison.DELTA_MIN,
            threshold=-0.30,
            weight=15,
            severity=Severity.MEDIUM,
            citation=_rule_citation("fin-ebitda-decline"),
        ),
        SignalRule(
            rule_id="fin-liquidity-thin",
            family=SignalFamily.FINANCIAL,
            metric="current_ratio",
            comparison=Comparison.MIN,
            threshold=1.00,
            weight=12,
            severity=Severity.MEDIUM,
            citation=_rule_citation("fin-liquidity-thin"),
        ),
        SignalRule(
            rule_id="beh-utilisation-jump",
            family=SignalFamily.BEHAVIOURAL,
            metric="revolver_utilisation_pct",
            comparison=Comparison.DELTA_MAX,
            threshold=25.0,
            weight=15,
            severity=Severity.MEDIUM,
            citation=_rule_citation("beh-utilisation-jump"),
        ),
        SignalRule(
            rule_id="beh-utilisation-sustained",
            family=SignalFamily.BEHAVIOURAL,
            metric="revolver_utilisation_pct",
            comparison=Comparison.MAX,
            threshold=95.0,
            consecutive_periods=2,
            weight=12,
            severity=Severity.MEDIUM,
            citation=_rule_citation("beh-utilisation-sustained"),
        ),
        SignalRule(
            rule_id="beh-excess-days",
            family=SignalFamily.BEHAVIOURAL,
            metric="excess_over_limit_days",
            comparison=Comparison.MAX,
            threshold=5.0,
            weight=12,
            severity=Severity.MEDIUM,
            citation=_rule_citation("beh-excess-days"),
        ),
        SignalRule(
            rule_id="beh-returned-debits",
            family=SignalFamily.BEHAVIOURAL,
            metric="returned_debits",
            comparison=Comparison.MAX,
            threshold=2.0,
            weight=10,
            severity=Severity.MEDIUM,
            citation=_rule_citation("beh-returned-debits"),
        ),
        SignalRule(
            rule_id="beh-collections-drop",
            family=SignalFamily.BEHAVIOURAL,
            metric="collections_concentration_pct",
            comparison=Comparison.DELTA_MIN,
            threshold=-20.0,
            weight=10,
            severity=Severity.MEDIUM,
            citation=_rule_citation("beh-collections-drop"),
        ),
        SignalRule(
            rule_id="ext-insolvency",
            family=SignalFamily.EXTERNAL,
            metric=NewsCategory.INSOLVENCY.value,
            comparison=Comparison.PRESENT,
            weight=20,
            severity=Severity.HIGH,
            citation=_rule_citation("ext-insolvency"),
        ),
        SignalRule(
            rule_id="ext-litigation",
            family=SignalFamily.EXTERNAL,
            metric=NewsCategory.LITIGATION.value,
            comparison=Comparison.PRESENT,
            weight=12,
            severity=Severity.MEDIUM,
            citation=_rule_citation("ext-litigation"),
        ),
        SignalRule(
            rule_id="ext-rating-downgrade",
            family=SignalFamily.EXTERNAL,
            metric=NewsCategory.RATING_DOWNGRADE.value,
            comparison=Comparison.PRESENT,
            weight=12,
            severity=Severity.MEDIUM,
            citation=_rule_citation("ext-rating-downgrade"),
        ),
        SignalRule(
            rule_id="ext-regulatory-action",
            family=SignalFamily.EXTERNAL,
            metric=NewsCategory.REGULATORY_ACTION.value,
            comparison=Comparison.PRESENT,
            weight=12,
            severity=Severity.MEDIUM,
            citation=_rule_citation("ext-regulatory-action"),
        ),
        SignalRule(
            rule_id="ext-supplier-distress",
            family=SignalFamily.EXTERNAL,
            metric=NewsCategory.SUPPLIER_DISTRESS.value,
            comparison=Comparison.PRESENT,
            weight=8,
            severity=Severity.LOW,
            citation=_rule_citation("ext-supplier-distress"),
        ),
    )


#: The shipped reference rule set, materialised once.
DEFAULT_SIGNAL_RULES: tuple[SignalRule, ...] = default_signal_rules()

#: The rule ids the arrears clock and the review clock fire under, and the floor ids they set.
#: Named constants because the engine, the policy defaults and the tests all have to agree on
#: the exact strings, and a typo in one of three places is a rule that silently never fires.
ARREARS_SICR = "ews-arrears-sicr"
ARREARS_DEFAULT = "ews-arrears-default"
ARREARS_SEVERE = "ews-arrears-severe"
FLOOR_COVENANT_BREACH = "floor-covenant-breach"
FLOOR_COVENANT_BREACH_REPEAT = "floor-covenant-breach-repeat"
FLOOR_ARREARS_SICR = "floor-arrears-sicr"
FLOOR_ARREARS_DEFAULT = "floor-arrears-default"
FLOOR_ARREARS_SEVERE = "floor-arrears-severe"
FLOOR_RESTRUCTURED = "floor-restructured"
CEILING_NO_LOSS = "ceiling-no-loss-proposal"

#: Every floor the engine can apply, and every key it indexes a weight table by, named once here.
#: :func:`validate_policy` requires the configured mappings to cover them, because each of these
#: is an engine ``[...]`` lookup: a settings file that prices some of the rows loads cleanly and
#: then raises on the first obligor whose arrears reached the clock, which is a load-time mistake
#: discovered at request time. The engine emits from the same constants, so the two cannot drift.
FLOOR_RULE_IDS: tuple[str, ...] = (
    FLOOR_COVENANT_BREACH,
    FLOOR_COVENANT_BREACH_REPEAT,
    FLOOR_ARREARS_SICR,
    FLOOR_ARREARS_DEFAULT,
    FLOOR_ARREARS_SEVERE,
    FLOOR_RESTRUCTURED,
)

#: The past-due tiers, in clock order. One weight row each, and the engine selects exactly one.
ARREARS_TIERS: tuple[str, ...] = ("sicr", "default", "severe")

#: The two states of the periodic-review clock. An ABSENT review is not a late one.
REVIEW_CLOCK_TIERS: tuple[str, ...] = ("overdue", "absent")


def _default_family_caps() -> Mapping[SignalFamily, int]:
    return {
        SignalFamily.FINANCIAL: 40,
        SignalFamily.BEHAVIOURAL: 30,
        SignalFamily.EXTERNAL: 20,
        SignalFamily.PROCESS: 20,
    }


def _default_band_floors() -> tuple[tuple[int, WatchGrade], ...]:
    return (
        (0, WatchGrade.PASS),
        (35, WatchGrade.SPECIAL_MENTION),
        (70, WatchGrade.SUBSTANDARD),
        (90, WatchGrade.DOUBTFUL),
    )


def _default_floor_grades() -> Mapping[str, WatchGrade]:
    return {
        FLOOR_COVENANT_BREACH: WatchGrade.SPECIAL_MENTION,
        FLOOR_COVENANT_BREACH_REPEAT: WatchGrade.SUBSTANDARD,
        FLOOR_ARREARS_SICR: WatchGrade.SPECIAL_MENTION,
        FLOOR_ARREARS_DEFAULT: WatchGrade.SUBSTANDARD,
        FLOOR_ARREARS_SEVERE: WatchGrade.DOUBTFUL,
        FLOOR_RESTRUCTURED: WatchGrade.SPECIAL_MENTION,
    }


def _default_covenant_weights() -> Mapping[CovenantStatus, tuple[int, Severity, SignalFamily]]:
    """Weight, severity and FAMILY per covenant status.

    Breach, waived and at_risk land in FINANCIAL because they are facts about the obligor's
    credit; stale and not_evidenced land in PROCESS because they are facts about our own file.
    """
    return {
        CovenantStatus.BREACH: (30, Severity.HIGH, SignalFamily.FINANCIAL),
        CovenantStatus.WAIVED: (12, Severity.MEDIUM, SignalFamily.FINANCIAL),
        CovenantStatus.AT_RISK: (10, Severity.MEDIUM, SignalFamily.FINANCIAL),
        CovenantStatus.NOT_EVIDENCED: (12, Severity.MEDIUM, SignalFamily.PROCESS),
        CovenantStatus.STALE: (10, Severity.MEDIUM, SignalFamily.PROCESS),
        CovenantStatus.NOT_DUE: (0, Severity.LOW, SignalFamily.PROCESS),
        CovenantStatus.COMPLIANT: (0, Severity.LOW, SignalFamily.FINANCIAL),
    }


def _default_arrears_weights() -> Mapping[str, tuple[int, Severity]]:
    return {
        "sicr": (15, Severity.HIGH),
        "default": (25, Severity.CRITICAL),
        "severe": (25, Severity.CRITICAL),
    }


def _default_review_clock_weights() -> Mapping[str, tuple[int, Severity]]:
    """An ABSENT review is a worse finding than a late one, expressed in severity not weight."""
    return {"overdue": (12, Severity.MEDIUM), "absent": (12, Severity.HIGH)}


def _default_required_metrics() -> tuple[str, ...]:
    return (
        "net_debt_to_ebitda",
        "dscr",
        "current_ratio",
        "ebitda",
        "revolver_utilisation_pct",
        "collections_concentration_pct",
    )


@dataclass(frozen=True, slots=True)
class EarlyWarningPolicy:
    """Every bank-owned number, in one frozen object.

    The shipped values apply when the settings file carries no ``policy:`` block at all. A block
    that is PRESENT and names an empty ``signal_rules`` list is honoured as empty (the operator
    wrote it), and the engine then fires only covenant, arrears, review-clock and coverage rules.
    """

    headroom_band: float = 0.05
    max_reporting_lag_days: int = 120
    certificate_grace_days: int = 45
    waiver_expiry_notice_days: int = 90
    #: The two materiality legs. ARREARS materiality gates the past-due clock; it is a different
    #: thing from EXPOSURE materiality, which sets the approval path and never the grade.
    arrears_materiality_absolute_minor: int = 50_000
    arrears_materiality_relative_pct: float = 0.01
    sicr_days_past_due: int = 30
    default_days_past_due: int = 90
    severe_days_past_due: int = 180
    rating_review_max_age_days: int = 365
    family_caps: Mapping[SignalFamily, int] = field(default_factory=_default_family_caps)
    band_floors: tuple[tuple[int, WatchGrade], ...] = field(default_factory=_default_band_floors)
    floor_grades: Mapping[str, WatchGrade] = field(default_factory=_default_floor_grades)
    covenant_weights: Mapping[CovenantStatus, tuple[int, Severity, SignalFamily]] = field(
        default_factory=_default_covenant_weights
    )
    arrears_weights: Mapping[str, tuple[int, Severity]] = field(
        default_factory=_default_arrears_weights
    )
    review_clock_weights: Mapping[str, tuple[int, Severity]] = field(
        default_factory=_default_review_clock_weights
    )
    coverage_weight: int = 10
    min_data_completeness: float = 0.60
    upgrade_min_clean_periods: int = 2
    max_upgrade_notches: int = 1
    upgrade_min_data_completeness: float = 0.90
    required_metrics: tuple[str, ...] = field(default_factory=_default_required_metrics)
    gate_severity: Severity = Severity.HIGH
    dual_control_exposure_minor: int = 2_500_000_000
    max_news_lookback_days: int = 365
    signal_rules: tuple[SignalRule, ...] = DEFAULT_SIGNAL_RULES
    citations: tuple[Citation, ...] = (POLICY_CITATION,)


#: The shipped policy, materialised once. Loaded when no ``policy:`` block is configured.
DEFAULT_POLICY: EarlyWarningPolicy = EarlyWarningPolicy()

#: The families that may never classify an obligor on their own: the one the MODEL influences
#: (external categories) and the one that measures OUR OWN FILE (process findings).
_BOUNDED_FAMILIES: tuple[SignalFamily, ...] = (SignalFamily.EXTERNAL, SignalFamily.PROCESS)


def _missing(
    name: str, configured: Sequence[Any] | Mapping[Any, Any], expected: Sequence[Any]
) -> str:
    """One refusal line naming the rows the engine will index and the policy does not price."""
    absent = [str(getattr(key, "value", key)) for key in expected if key not in configured]
    if not absent:
        return ""
    return (
        f"{name} prices nothing for " + ", ".join(absent) + "; the engine indexes every one of "
        "them, so a partial block is a request-time failure and this is where it belongs"
    )


def _coverage_problems(policy: EarlyWarningPolicy) -> list[str]:
    """Every configured mapping must cover the keys the engine looks up in it."""
    return [
        problem
        for problem in (
            _missing("family_caps", policy.family_caps, tuple(SignalFamily)),
            _missing("floor_grades", policy.floor_grades, FLOOR_RULE_IDS),
            _missing("covenant_weights", policy.covenant_weights, tuple(CovenantStatus)),
            _missing("arrears_weights", policy.arrears_weights, ARREARS_TIERS),
            _missing("review_clock_weights", policy.review_clock_weights, REVIEW_CLOCK_TIERS),
        )
        if problem
    ]


def validate_policy(policy: EarlyWarningPolicy) -> tuple[str, ...]:
    """Return the reasons ``policy`` is not loadable (an empty tuple when it is).

    Every refusal here is a configuration that would silently change what the engine means:

    * a band ladder that is not strictly monotonic in BOTH score and grade rank, or does not
      start at ``(0, pass)``, makes the band lookup ambiguous or partial;
    * a negative family cap, or an external or process cap at or above the lowest adverse band
      floor, would let the model-influenced family or our own missing paperwork classify an
      obligor with no other evidence;
    * a SICR clock above the default clock inverts the two presumptions;
    * an upgrade notch cap below one makes the upgrade path unreachable while still reporting
      that it was entered, and an upgrade completeness floor below the general one would let a
      thinner file justify an improvement than a downgrade needs;
    * an EMPTY required-metric list reports perfect completeness having checked nothing, which
      is the shape of every falsely-green metric this organization has shipped;
    * a mapping that does not cover what the engine INDEXES. Each of these sub-blocks replaces
      the shipped mapping wholesale rather than merging into it, so an operator who edits one row
      of ``floor_grades:`` ships all the others as absent. An absent family cap is read as zero
      and silently stops the score-driven half of the engine contributing (the floors still fire,
      so it does not look broken); an absent floor, covenant status, arrears tier or review-clock
      state raises ``KeyError`` on the first obligor that reaches it. Both belong at LOAD.

    The loop over a PRESENT mapping is not the check. Iterating ``family_caps.items()`` reports
    success over an empty mapping, which is the failure this organization names by name: a check
    that reports success over zero items has not checked anything.
    """
    problems: list[str] = []
    problems.extend(_coverage_problems(policy))
    floors = policy.band_floors
    if not floors:
        problems.append("band_floors is empty")
    else:
        if floors[0][0] != 0 or floors[0][1] is not WatchGrade.PASS:
            problems.append("band_floors must start at (0, pass)")
        for earlier, later in zip(floors, floors[1:], strict=False):
            if later[0] <= earlier[0]:
                problems.append("band_floors scores must be strictly increasing")
            if GRADE_RANK[later[1]] <= GRADE_RANK[earlier[1]]:
                problems.append("band_floors grades must be strictly increasing in rank")
    lowest_adverse = min(
        (score for score, grade in floors if grade is not WatchGrade.PASS), default=0
    )
    for family, cap in policy.family_caps.items():
        if cap < 0:
            problems.append(f"family cap for {family.value} is negative")
        if family in _BOUNDED_FAMILIES and floors and cap >= lowest_adverse:
            problems.append(
                f"family cap for {family.value} ({cap}) reaches the first adverse band "
                f"({lowest_adverse}); that family must not be able to classify alone"
            )
    if policy.sicr_days_past_due > policy.default_days_past_due:
        problems.append("sicr_days_past_due must not exceed default_days_past_due")
    if policy.default_days_past_due > policy.severe_days_past_due:
        problems.append("default_days_past_due must not exceed severe_days_past_due")
    if policy.max_upgrade_notches < 1:
        problems.append("max_upgrade_notches must be at least 1")
    if policy.upgrade_min_data_completeness < policy.min_data_completeness:
        problems.append("upgrade_min_data_completeness must not be below min_data_completeness")
    if not policy.required_metrics:
        problems.append("required_metrics is empty; completeness would report success over zero")
    return tuple(problems)


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"policy.{name} must be a mapping")
    return {str(k): v for k, v in value.items()}


def _rule_from_mapping(entry: Mapping[str, Any]) -> SignalRule:
    rule_id = str(entry["rule_id"])
    threshold = entry.get("threshold")
    return SignalRule(
        rule_id=rule_id,
        family=SignalFamily(str(entry["family"])),
        metric=str(entry["metric"]),
        comparison=Comparison(str(entry["comparison"])),
        threshold=None if threshold is None else float(threshold),
        consecutive_periods=int(entry.get("consecutive_periods", 1)),
        weight=int(entry.get("weight", 0)),
        severity=Severity(str(entry.get("severity", "medium"))),
        citation=_rule_citation(rule_id),
    )


def _band_floors_from(raw: Any) -> tuple[tuple[int, WatchGrade], ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise ValueError("policy.band_floors must be a list of {min_score, grade} entries")
    out: list[tuple[int, WatchGrade]] = []
    for entry in raw:
        mapped = _as_mapping(entry, "band_floors")
        out.append((int(mapped["min_score"]), WatchGrade(str(mapped["grade"]))))
    return tuple(out)


def _covenant_weights_from(raw: Any) -> Mapping[CovenantStatus, tuple[int, Severity, SignalFamily]]:
    mapped = _as_mapping(raw, "covenant_weights")
    out: dict[CovenantStatus, tuple[int, Severity, SignalFamily]] = {}
    for key, value in mapped.items():
        row = _as_mapping(value, "covenant_weights")
        out[CovenantStatus(key)] = (
            int(row["weight"]),
            Severity(str(row["severity"])),
            SignalFamily(str(row["family"])),
        )
    return out


def _weight_severity_from(raw: Any, name: str) -> Mapping[str, tuple[int, Severity]]:
    mapped = _as_mapping(raw, name)
    out: dict[str, tuple[int, Severity]] = {}
    for key, value in mapped.items():
        row = _as_mapping(value, name)
        out[key] = (int(row["weight"]), Severity(str(row["severity"])))
    return out


def load_policy(block: Mapping[str, Any] | None) -> EarlyWarningPolicy:
    """Build the policy from the settings file's ``policy:`` block, validated before it returns.

    Follows the fleet's configuration rule exactly: a wholly ABSENT block (``None`` or empty)
    takes the shipped defaults, while a block that is PRESENT and names a key is honoured for
    that key, including an empty ``signal_rules`` list. An operator who wrote an empty list
    expressed an intent and it is not the same as writing nothing.

    Raises :class:`ValueError` naming every problem when :func:`validate_policy` refuses.
    """
    if not block:
        return DEFAULT_POLICY
    data = _as_mapping(block, "policy")
    defaults = DEFAULT_POLICY

    def number(key: str, fallback: float) -> float:
        return float(data[key]) if key in data else fallback

    def count(key: str, fallback: int) -> int:
        return int(data[key]) if key in data else fallback

    rules = defaults.signal_rules
    if "signal_rules" in data:
        raw_rules = data["signal_rules"] or []
        if not isinstance(raw_rules, Sequence) or isinstance(raw_rules, str):
            raise ValueError("policy.signal_rules must be a list of rule mappings")
        rules = tuple(_rule_from_mapping(_as_mapping(entry, "signal_rules")) for entry in raw_rules)

    caps = defaults.family_caps
    if "family_caps" in data:
        caps = {
            SignalFamily(key): int(value)
            for key, value in _as_mapping(data["family_caps"], "family_caps").items()
        }
    floor_grades = defaults.floor_grades
    if "floor_grades" in data:
        floor_grades = {
            key: WatchGrade(str(value))
            for key, value in _as_mapping(data["floor_grades"], "floor_grades").items()
        }
    policy = EarlyWarningPolicy(
        headroom_band=number("headroom_band", defaults.headroom_band),
        max_reporting_lag_days=count("max_reporting_lag_days", defaults.max_reporting_lag_days),
        certificate_grace_days=count("certificate_grace_days", defaults.certificate_grace_days),
        waiver_expiry_notice_days=count(
            "waiver_expiry_notice_days", defaults.waiver_expiry_notice_days
        ),
        arrears_materiality_absolute_minor=count(
            "arrears_materiality_absolute_minor", defaults.arrears_materiality_absolute_minor
        ),
        arrears_materiality_relative_pct=number(
            "arrears_materiality_relative_pct", defaults.arrears_materiality_relative_pct
        ),
        sicr_days_past_due=count("sicr_days_past_due", defaults.sicr_days_past_due),
        default_days_past_due=count("default_days_past_due", defaults.default_days_past_due),
        severe_days_past_due=count("severe_days_past_due", defaults.severe_days_past_due),
        rating_review_max_age_days=count(
            "rating_review_max_age_days", defaults.rating_review_max_age_days
        ),
        family_caps=caps,
        band_floors=(
            _band_floors_from(data["band_floors"])
            if "band_floors" in data
            else defaults.band_floors
        ),
        floor_grades=floor_grades,
        covenant_weights=(
            _covenant_weights_from(data["covenant_weights"])
            if "covenant_weights" in data
            else defaults.covenant_weights
        ),
        arrears_weights=(
            _weight_severity_from(data["arrears_weights"], "arrears_weights")
            if "arrears_weights" in data
            else defaults.arrears_weights
        ),
        review_clock_weights=(
            _weight_severity_from(data["review_clock_weights"], "review_clock_weights")
            if "review_clock_weights" in data
            else defaults.review_clock_weights
        ),
        coverage_weight=count("coverage_weight", defaults.coverage_weight),
        min_data_completeness=number("min_data_completeness", defaults.min_data_completeness),
        upgrade_min_clean_periods=count(
            "upgrade_min_clean_periods", defaults.upgrade_min_clean_periods
        ),
        max_upgrade_notches=count("max_upgrade_notches", defaults.max_upgrade_notches),
        upgrade_min_data_completeness=number(
            "upgrade_min_data_completeness", defaults.upgrade_min_data_completeness
        ),
        required_metrics=(
            tuple(str(m) for m in data["required_metrics"])
            if "required_metrics" in data
            else defaults.required_metrics
        ),
        gate_severity=(
            Severity(str(data["gate_severity"]))
            if "gate_severity" in data
            else defaults.gate_severity
        ),
        dual_control_exposure_minor=count(
            "dual_control_exposure_minor", defaults.dual_control_exposure_minor
        ),
        max_news_lookback_days=count("max_news_lookback_days", defaults.max_news_lookback_days),
        signal_rules=rules,
    )
    problems = validate_policy(policy)
    if problems:
        raise ValueError("policy is not loadable: " + "; ".join(problems))
    return policy
