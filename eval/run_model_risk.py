#!/usr/bin/env python3
"""The model-risk harness: discrimination on a synthetic sample, and outcome monitoring.

`eval/run_eval.py` is a REGRESSION gate. Every engine metric there sits at 1.00 because the
engine is a pure function scored against hand-written expectations, and that is the right bar
for what it measures: the arithmetic did not move under a grade somebody already acted on. It
is not evidence of predictive validity, and under SR 11-7 and PRA SS1/23 the scoring engine in
`domain/early_warning.py` is a model that owes such evidence.

This file lands the honest half of what is owed, and refuses to overstate it.

**Discrimination is measured against an ASSUMPTION, not against the world.** The sample is
synthetic and its labels come from the generative model recorded in
`scripts/render_calibration_sample.py`, not from realised outcomes. A high AUC here means the
scorecard's weights, family caps and band edges recover a latent state through noisy
observations UNDER THAT MODEL. If the model is wrong about which signals lead deterioration,
this number is wrong in the same direction and will not say so. It is nevertheless the only
thing in this repository that goes red when a retune makes the scorecard incoherent, because
the regression metrics move with their own expectations.

**Outcome monitoring escalates on ABSENCE.** There are no realised outcomes here, and there is
no plan under which silence should read as calm. A monitoring metric with no data behind it
reports UNFIT and this harness exits non-zero, matching the drift rule in `model-quality-gate`
rather than the more comfortable alternative of reporting nothing at all. That is the whole
point of building the harness before the data exists: the day someone connects an outcomes
feed, the mechanism that reads it is already here and already failing loudly.

**Nothing here calls the composite a probability of default.** It is an ordinal triage score.
`tests/unit/test_no_probability_claim.py` holds the whole repository to that.

Three modes, because "absence escalates" and "the build fails forever" are not the same thing.
A gate that is red on every pull request from the day it is written gets bypassed, and a
bypassed control is worse than an absent one because it also produces a green tick somewhere.

    python eval/run_model_risk.py            # the full verdict. Non-zero while monitoring is
                                             # absent, which is the honest state and what a
                                             # scheduled run or a person should see.
    python eval/run_model_risk.py --gate     # what `make gate` runs. Enforces the metrics that
                                             # CAN be measured, prints the outstanding ones, and
                                             # fails if the outstanding set stops agreeing with
                                             # what docs/model-card.md records. Connect an
                                             # outcomes feed and this goes red until the model
                                             # card is updated, which is the point: the card is
                                             # how a supervisor learns the state changed.
    python eval/run_model_risk.py --report-only   # print and exit 0 (the demo act).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from agent_eval_kit import (
    assert_denominator_supports,
    dataset_digest,
    load_jsonl,
    load_rubrics,
    prove_before_scoring,
)
from agent_eval_kit.harness import NotFalselyGreenError

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from credit_portfolio_ews.domain.early_warning import EarlyWarningEngine  # noqa: E402
from credit_portfolio_ews.domain.kernel import Citation  # noqa: E402
from credit_portfolio_ews.domain.models import (  # noqa: E402
    AdverseNewsItem,
    ArrearsSnapshot,
    NewsCategory,
    NewsRelevance,
    ObligorRecord,
    SignalFamily,
    SignalObservation,
    WatchGrade,
)
from credit_portfolio_ews.domain.policy import EarlyWarningPolicy  # noqa: E402

RUBRICS = _REPO_ROOT / "eval" / "rubrics"
SAMPLE = _REPO_ROOT / "eval" / "datasets" / "synthetic_calibration.jsonl"

#: Where a realised-outcome feed WOULD land. Absent by design: see the module docstring.
OUTCOMES = _REPO_ROOT / "monitoring" / "realised_outcomes.ndjson"
OVERRIDES = _REPO_ROOT / "monitoring" / "override_log.ndjson"

#: The metrics this harness scores, in report order.
SCORED: tuple[str, ...] = (
    "rank_discrimination",
    "band_monotonicity",
    "outcome_coverage",
    "override_coverage",
)

#: The metrics that measure a control which does not exist here yet. `--gate` reports these as
#: OUTSTANDING rather than failing the build on them, and fails if one starts scoring above zero
#: while docs/model-card.md still records the control as Absent.
MONITORING: tuple[str, ...] = ("outcome_coverage", "override_coverage")

#: Where the recorded status lives, and the rows this harness holds it to.
MODEL_CARD = _REPO_ROOT / "docs" / "model-card.md"
CARD_ROWS: dict[str, str] = {
    "outcome_coverage": "Outcome monitoring",
    "override_coverage": "Override and challenge log",
}


def card_records_absent(control: str) -> bool:
    """Does the model card still record this control as Absent?

    Read from the card rather than from a constant here, because the card is the artefact a
    supervisor reads and a second copy of the status is a second thing to forget to update.
    """
    for line in MODEL_CARD.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {control} ") or line.startswith(f"| {control}|"):
            return "**Absent" in line or "**Mechanism only" in line
    raise SystemExit(
        f"{MODEL_CARD.name}: no control row named {control!r}. This harness holds the card and "
        "the measurement to each other, and it cannot do that against a row that moved."
    )


_AS_OF = date(2026, 6, 30)
_PERIODS = ("FY2025H2", "FY2026H1")
_EVALUATOR = "synthetic discrimination + absent-outcome monitoring"

#: The grade order the band-monotonicity check walks. Named here rather than derived from the
#: enum, because the enum's order is a declaration order and this is a severity claim.
_BAND_ORDER: tuple[WatchGrade, ...] = (
    WatchGrade.PASS,
    WatchGrade.SPECIAL_MENTION,
    WatchGrade.SUBSTANDARD,
    WatchGrade.DOUBTFUL,
)


def _citation(source_id: str) -> Citation:
    return Citation(
        source_id=source_id,
        title="synthetic calibration observation",
        snippet="SYNTHETIC figure from the recorded generative model; not a real observation.",
    )


def _observations(row: dict[str, Any]) -> list[SignalObservation]:
    out: list[SignalObservation] = []
    for metric, values in row["metrics"].items():
        for offset, value in enumerate(values):
            out.append(
                SignalObservation(
                    metric=metric,
                    value=float(value),
                    period=_PERIODS[offset] if offset < len(_PERIODS) else f"P{offset}",
                    as_of=_AS_OF - timedelta(days=180 * (len(values) - 1 - offset)),
                    source="synthetic-calibration",
                    source_ref=f"{row['id']}:{metric}:{offset}",
                    citations=(_citation(f"{row['id']}-{metric}-{offset}"),),
                )
            )
    return out


def _arrears(row: dict[str, Any]) -> ArrearsSnapshot | None:
    days = int(row.get("arrears_days_past_due") or 0)
    if days <= 0:
        return None
    # Past due well above any materiality floor, because this sample is about DISCRIMINATION
    # and a snapshot that failed the materiality gate would drop the clock for a reason that
    # has nothing to do with whether the obligor is deteriorating.
    return ArrearsSnapshot(
        obligor_id=row["id"],
        as_of=_AS_OF,
        currency="SGD",
        drawn_amount_minor=100_000_000,
        past_due_amount_minor=5_000_000,
        days_past_due=days,
        source_ref=f"{row['id']}:servicing",
        # The engine refuses a signal grounded on the policy row alone, so the snapshot carries
        # its own source locator. That refusal is a control worth keeping, and a sample that
        # sidestepped it would be measuring an engine nobody runs.
        citations=(_citation(f"{row['id']}-servicing"),),
    )


def _news(row: dict[str, Any]) -> list[AdverseNewsItem]:
    return [
        AdverseNewsItem(
            item_id=f"{row['id']}-news-{index}",
            obligor_id=row["id"],
            category=NewsCategory(category),
            headline="SYNTHETIC adverse coverage (fictional)",
            published_on=_AS_OF - timedelta(days=30),
            citation=_citation(f"{row['id']}-news-{index}"),
            # Confirmed on purpose: an UNCONFIRMED item may not fire an external rule, and a
            # sample whose adverse media never fires measures the EXTERNAL family not at all.
            relevance=NewsRelevance.CONFIRMED,
            classified_by="synthetic-calibration",
        )
        for index, category in enumerate(row.get("adverse_news") or ())
    ]


@dataclass(frozen=True, slots=True)
class Scored:
    """One synthetic obligor, its latent label and what the real engine made of it."""

    id: str
    stressed: bool
    composite: int
    grade: WatchGrade


def score_sample(rows: list[dict[str, Any]], policy: EarlyWarningPolicy) -> list[Scored]:
    """Run the REAL engine over every synthetic obligor. No re-implementation of the scorecard."""
    engine = EarlyWarningEngine()
    out: list[Scored] = []
    for row in rows:
        record = ObligorRecord(
            obligor_id=row["id"],
            name=f"Synthetic Obligor {row['id']} (FICTIONAL)",
            current_grade=WatchGrade.PASS,
            currency="SGD",
            exposure_amount_minor=100_000_000,
            last_review_on=_AS_OF - timedelta(days=90),
            source="synthetic-calibration",
        )
        assessment = engine.evaluate(
            record,
            terms=(),
            covenant_observations=(),
            arrears=_arrears(row),
            observations=_observations(row),
            news=_news(row),
            policy=policy,
            as_of=_AS_OF,
        )
        out.append(
            Scored(
                id=row["id"],
                stressed=row["latent_state"] == "deteriorating",
                composite=assessment.composite_score,
                grade=assessment.proposal.proposed_grade,
            )
        )
    return out


def auc(scored: list[Scored]) -> float:
    """Probability a randomly chosen deteriorating obligor outranks a stable one, ties at 0.5.

    Computed by the rank-sum identity rather than by trapezoid over a curve: with integer
    composites there are many ties, and the tie handling is the part a reader should be able
    to check. 0.5 is chance, and a scorecard at chance under its own stated assumption is not
    a scorecard.
    """
    positives = [row.composite for row in scored if row.stressed]
    negatives = [row.composite for row in scored if not row.stressed]
    if not positives or not negatives:
        # One class only. Not a hard AUC of 0.5: it is not measurable, and returning the
        # midpoint would report chance performance as though it had been observed.
        return 0.0
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positives for n in negatives)
    return round(wins / (len(positives) * len(negatives)), 4)


def band_monotonicity(scored: list[Scored]) -> tuple[float, list[tuple[str, int, float]]]:
    """Share of adjacent band pairs whose observed deterioration rate does not go DOWN.

    The band edges are the part of the scorecard a reader acts on: an obligor lands in
    SPECIAL_MENTION or it does not. A composite that ranks well can still carry band edges that
    put a lower deterioration rate in a worse band, and no AUC would show it, because AUC never
    looks at where the cuts are.

    Bands holding fewer than `_MIN_BAND` obligors are reported and NOT scored: a rate over three
    obligors is noise, and scoring it would make this metric fail on sample size rather than on
    the band edges.
    """
    buckets: dict[WatchGrade, list[Scored]] = {grade: [] for grade in _BAND_ORDER}
    for row in scored:
        buckets.setdefault(row.grade, []).append(row)
    table = [
        (
            grade.value,
            len(buckets.get(grade, [])),
            round(
                sum(1 for row in buckets.get(grade, []) if row.stressed) / len(buckets[grade]),
                4,
            )
            if buckets.get(grade)
            else 0.0,
        )
        for grade in _BAND_ORDER
    ]
    measurable = [(name, n, rate) for name, n, rate in table if n >= _MIN_BAND]
    if len(measurable) < 2:
        return 0.0, table
    pairs = list(zip(measurable, measurable[1:], strict=False))
    held = sum(1 for lower, upper in pairs if upper[2] >= lower[2] - 1e-9)
    return round(held / len(pairs), 4), table


#: Below this a band's deterioration rate is noise rather than a measurement. Stated once.
_MIN_BAND = 8


def outcome_coverage() -> tuple[float, str]:
    """Share of proposals with a realised outcome recorded against them.

    Zero, and it is meant to be. There is no outcomes feed here and no historical sample, so
    this metric reports 0.0 and the harness exits non-zero. The alternative, which is what most
    monitoring looks like before anyone connects it, is a metric that reports nothing and lets
    an unmonitored model read as a monitored one.
    """
    if not OUTCOMES.exists():
        return 0.0, f"no outcomes feed at {OUTCOMES.relative_to(_REPO_ROOT)}"
    rows = load_jsonl(OUTCOMES)
    if not rows:
        return 0.0, "the outcomes feed exists and is empty"
    with_outcome = sum(1 for row in rows if row.get("realised_outcome"))
    return round(with_outcome / len(rows), 4), f"{with_outcome} of {len(rows)} carry an outcome"


def override_coverage() -> tuple[float, str]:
    """Whether the override log is being kept at all, as a 0/1.

    The cheapest early evidence a scorecard is mis-calibrated is a credit officer disagreeing
    with it, and the cheapest way to lose that evidence is to have nowhere to put it. This
    scores the MECHANISM, not the rate: a low override rate is a finding, no log is a control
    that does not exist. See docs/override-log.md for the schema and the trigger levels.
    """
    if not OVERRIDES.exists():
        return 0.0, f"no override log at {OVERRIDES.relative_to(_REPO_ROOT)}"
    rows = load_jsonl(OVERRIDES)
    if not rows:
        return 0.0, "the override log exists and holds no entries, so nothing has been reviewed"
    return 1.0, f"{len(rows)} logged override(s) or challenges"


def _gagged(policy: EarlyWarningPolicy) -> EarlyWarningPolicy:
    """The policy with its family caps inverted: the failure the caps exist to prevent.

    EXTERNAL is adverse media and PROCESS is findings about our own file. Both are capped in
    the shipped policy precisely because neither is evidence about the obligor's credit strong
    enough to classify on its own, and this is what the scorecard looks like when that decision
    is undone.
    """
    from dataclasses import replace

    return replace(
        policy,
        family_caps={
            SignalFamily.FINANCIAL: 2,
            SignalFamily.BEHAVIOURAL: 2,
            SignalFamily.EXTERNAL: 90,
            SignalFamily.PROCESS: 90,
        },
    )


def _red_case_proofs(
    rows: list[dict[str, Any]], policy: EarlyWarningPolicy, thresholds: dict[str, float]
) -> tuple[Any, ...]:
    """The falsification proofs, run before any score below is trusted."""

    def rank_discrimination() -> None:
        # TWO red cases, because they falsify different things and one alone is not enough.
        #
        # (1) Scrambled labels. A statistic measured against labels that carry no information
        #     must land at chance. Anything else means it is reading something other than the
        #     label, and the number above it is not discrimination at all.
        scored = score_sample(rows, policy)
        real = auc(scored)
        scrambled = auc(
            [
                Scored(row.id, index % 4 == 0, row.composite, row.grade)
                for index, row in enumerate(scored)
            ]
        )
        if real < thresholds["rank_discrimination"]:
            raise NotFalselyGreenError(
                f"rank_discrimination: the harness scored {real} on the real labels, below its "
                "own bar, so nothing below this line is worth reading"
            )
        if scrambled >= thresholds["rank_discrimination"]:
            raise NotFalselyGreenError(
                f"rank_discrimination: FALSELY GREEN - scrambled labels still scored "
                f"{scrambled} >= {thresholds['rank_discrimination']}, so the statistic is not "
                "reading the label at all"
            )
        # (2) A STRUCTURALLY broken scorecard, real labels. Family caps inverted so the two
        #     model-influenced families dominate and the two evidential ones are gagged: the
        #     exact shape the caps exist to prevent. This is the proof that the metric reads
        #     the SCORECARD and not only the sample, and it is the one that would catch a
        #     retune. What it does NOT catch is recorded beside it in the rubric and in
        #     docs/conceptual-soundness.md: reversing every weight leaves this at 0.92 on this
        #     sample, so `rank_discrimination` does not validate the weights and must not be
        #     cited as though it did.
        broken = auc(score_sample(rows, _gagged(policy)))
        if broken >= thresholds["rank_discrimination"]:
            raise NotFalselyGreenError(
                "rank_discrimination: FALSELY GREEN - a scorecard whose family caps let "
                f"adverse media and process findings dominate still scored {broken} >= "
                f"{thresholds['rank_discrimination']}"
            )

    def band_monotonicity_proof() -> None:
        scored = score_sample(rows, policy)
        held, _ = band_monotonicity(scored)
        inverted = [
            Scored(
                row.id,
                not row.stressed if row.grade is WatchGrade.PASS else row.stressed,
                row.composite,
                row.grade,
            )
            for row in scored
        ]
        broken, _ = band_monotonicity(inverted)
        if held < thresholds["band_monotonicity"]:
            raise NotFalselyGreenError(
                f"band_monotonicity: scored {held} on the real sample, below its own bar"
            )
        if broken >= thresholds["band_monotonicity"]:
            raise NotFalselyGreenError(
                "band_monotonicity: FALSELY GREEN - flipping every PASS obligor's label left "
                f"the metric at {broken}, so it is not reading the band rates"
            )

    def monitoring_absence() -> None:
        # The proof that matters most here, and the one that is easiest to lose in a refactor:
        # an ABSENT measurement must score zero, not one. A monitoring harness that returns
        # 1.0 when it found nothing is worse than no harness, because it produces evidence.
        coverage, _ = outcome_coverage()
        overrides, _ = override_coverage()
        if OUTCOMES.exists() and load_jsonl(OUTCOMES):
            return  # a feed arrived; this proof no longer applies and says so by passing
        if coverage != 0.0 or (not OVERRIDES.exists() and overrides != 0.0):
            raise NotFalselyGreenError(
                "outcome_coverage: FALSELY GREEN - there is no outcomes feed and the metric "
                f"still scored {coverage}; absence must escalate, never read as calm"
            )

    band_monotonicity_proof.__name__ = "band_monotonicity"
    monitoring_absence.__name__ = "outcome_coverage"
    return (rank_discrimination, band_monotonicity_proof, monitoring_absence)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="print the table and exit 0 (the demo act).",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help=(
            "enforce the measurable metrics, report the outstanding ones, and fail if the "
            "outstanding set stops agreeing with docs/model-card.md."
        ),
    )
    args = parser.parse_args(argv)

    # `group("model-risk")` first, then assert_covers on that group alone: the regression bars
    # live in the same directory and are a different family, and holding this harness to the
    # union would make each set look like an orphan bar to the other.
    rubrics = load_rubrics(RUBRICS).group("model-risk")
    rubrics.assert_covers(SCORED)
    thresholds = rubrics.thresholds()
    rows = load_jsonl(SAMPLE, required=("id", "latent_state", "metrics"))
    policy = EarlyWarningPolicy()

    prove_before_scoring(*_red_case_proofs(rows, policy, thresholds))

    scored = score_sample(rows, policy)
    discrimination = auc(scored)
    monotonicity, table = band_monotonicity(scored)
    coverage, coverage_note = outcome_coverage()
    overrides, override_note = override_coverage()

    positives = sum(1 for row in scored if row.stressed)
    assert_denominator_supports(
        thresholds["rank_discrimination"], positives, metric="rank_discrimination"
    )

    print("\nModel-risk harness  (credit-portfolio-early-warning)")
    print(f"  evaluator : {_EVALUATOR}")
    print(f"  sample    : {SAMPLE.name}  digest {dataset_digest(SAMPLE)[:12]}")
    print(f"  obligors  : {len(scored)} synthetic, {positives} labelled deteriorating\n")
    print("  band            n   deterioration rate")
    print("  ---------------------------------------")
    for name, count, rate in table:
        print(f"  {name:15s} {count:4d}   {rate:.3f}")

    scores = {
        "rank_discrimination": (discrimination, "AUC against the synthetic latent label"),
        "band_monotonicity": (monotonicity, "band deterioration rates never go down"),
        "outcome_coverage": (coverage, coverage_note),
        "override_coverage": (overrides, override_note),
    }
    print("\n  metric                score   bar    result   note")
    print("  " + "-" * 74)
    failed: list[str] = []
    for metric in SCORED:
        score, note = scores[metric]
        bar = thresholds[metric]
        passed = score >= bar
        if not passed:
            failed.append(metric)
        print(f"  {metric:20s} {score:.3f}  {bar:.2f}   {'PASS' if passed else 'FAIL':7s} {note}")

    outstanding = [metric for metric in failed if metric in MONITORING]
    regressed = [metric for metric in failed if metric not in MONITORING]

    print()
    if outstanding:
        print(f"  OUTSTANDING (no control, not a regression): {', '.join(outstanding)}")
        print(
            "  This repository has no realised outcomes and no override entries. The harness\n"
            "  reports that as a failure rather than as silence, because a model nobody is\n"
            "  watching and a model with a silent monitor look identical from outside. Recorded\n"
            "  in docs/model-card.md and docs/conceptual-soundness.md."
        )
    if regressed:
        print(f"  MODEL-RISK HARNESS: FAIL ({', '.join(regressed)})")
    elif not outstanding:
        print("  MODEL-RISK HARNESS: PASS")

    if args.report_only:
        return 0
    if not args.gate:
        return 1 if failed else 0

    # --gate: the measurable metrics are enforced, and the outstanding ones are held against the
    # card. A control that starts producing evidence must be recorded as producing it, or the
    # card and the measurement drift apart in the direction that flatters the model.
    drifted = [
        metric
        for metric in MONITORING
        if (metric not in outstanding) is card_records_absent(CARD_ROWS[metric])
    ]
    for metric in drifted:
        print(
            f"  DRIFT: {metric} and docs/model-card.md disagree. The card records "
            f"{CARD_ROWS[metric]!r} as Absent and the harness measured otherwise, or the "
            "reverse. Update the card; that is the artefact a supervisor reads."
        )
    return 1 if (regressed or drifted) else 0


if __name__ == "__main__":
    raise SystemExit(main())
