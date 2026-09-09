#!/usr/bin/env python3
"""Evaluation gate for Credit Portfolio Early Warning (credit-portfolio-early-warning).

Two named layers via ``--mode`` (the scaffold is ``agent_eval_kit.eval_main``):

* **smoke** (default) - the offline pre-merge check CI runs on every change. It drives the REAL
  ``WatchlistReviewService`` over the SDK-free local adapters, which serve the same synthetic estate
  the demo drives, and scores every metric named in :data:`THRESHOLDS`. * **gate** - the promotion
  verdict from the shared model-quality-gate authority (requires the ``gcp`` profile), resolved
  through the container's ``EvaluationGatePort`` so the authority is a binding like every other port
  rather than a client constructed here.

Every metric that scores the ENGINE sits at 1.00 on purpose. They score a PURE FUNCTION against
hand-written fixtures, so anything below is a defect rather than drift, and a threshold set
below one would let a real regression pass. ``floor_precision`` compares the applied-floor rule
id SET exactly, because a grade-only metric passes a case that reached the right answer for the
wrong reason.

Every expectation the dataset carries is scored here. A field the golden file publishes and no
metric reads is documentation that drifts silently: ``expected_composite`` and
``expected_requires_human_review`` were exactly that, and the composite in particular was a
second, unenforced copy of a number the demo walkthrough asserts on its own.

Exit is ``0`` iff every metric meets its threshold (and, in gate mode, the authority agrees).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval_kit import (
    EvalMetricResult,
    EvalReport,
    assert_can_go_red,
    assert_denominator_supports,
    dataset_digest,
    eval_main,
    load_rubrics,
    prove_before_scoring,
)
from pii_kit import pack_leak

from credit_portfolio_ews.adapters.local import (
    _fixtures,
)
from credit_portfolio_ews.config import (
    Settings,
    build_container,
    build_review_service,
)
from credit_portfolio_ews.domain.pii import (
    PII_PATTERNS,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"

RUBRICS = _REPO_ROOT / "eval" / "rubrics"

#: Named on the report and stamped on every EvalReport, so a stored result says what produced
#: it rather than leaving a reader to assume the production evaluator did.
_EVALUATOR = "offline regression gate (deterministic engine, no GCP creds)"

#: The metrics this runner scores, in report order. There is no THRESHOLDS dict any more: every
#: bar lives in `eval/rubrics/regression.yaml` beside the argument for it, and `assert_covers`
#: holds this tuple and that file equal in BOTH directions before anything is scored.
SCORED: tuple[str, ...] = (
    "grade_accuracy",
    "movement_accuracy",
    "floor_precision",
    "composite_accuracy",
    "routing_accuracy",
    "pii_safety",
    "narration_groundedness",
)


def load_thresholds_from_rubrics() -> dict[str, float]:
    """Read every regression bar out of ``eval/rubrics/``. No fallback, by design.

    The `model-risk` group is excluded here and read by `eval/run_model_risk.py` instead. The
    two families measure different things against different kinds of evidence, and folding them
    into one set would make each look like an orphan bar to the other.
    """
    return load_rubrics(RUBRICS).group("").thresholds()


#: The identity the eval attributes work to. It names a bot, never a person.
ACTOR = "eval-bot@bank.example"

#: The ONE audit-record field the pack scan below skips, named here with its reason rather than
#: left implicit: the actor is an identifier deliberately, because a record that cannot say who
#: acted is not an audit record, and the pack cannot tell an attribution from a leak. Every other
#: field is scanned, including any added later, because the leak this oracle missed arrived in a
#: field nobody had thought to name.
ATTRIBUTION_FIELDS: tuple[str, ...] = ("actor",)


def _scannable(entry: dict[str, Any]) -> str:
    """One audit record as text, minus the attribution the scan cannot interpret."""
    scanned = {key: value for key, value in entry.items() if key not in ATTRIBUTION_FIELDS}
    return json.dumps(scanned, sort_keys=True, default=str)


def _load(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    if not cases:
        raise SystemExit(f"{path}: golden dataset is empty")
    return cases


def _mean(scores: list[float]) -> float:
    """Zero over an EMPTY list, never one. A metric with nothing in it has checked nothing."""
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def run_smoke(dataset: Path, thresholds: dict[str, float] | None = None) -> EvalReport:
    # The rubrics and the scored set must agree in BOTH directions before anything is scored.
    thresholds = thresholds or load_thresholds_from_rubrics()
    load_rubrics(RUBRICS).group("").assert_covers(SCORED)
    cases = _load(dataset)
    # Falsification first, as the opening statement of the scored run and not only under
    # tests/: a metric that cannot go red is not evidence, and a suite that proved it ten
    # minutes ago proved it about a process nobody shipped.
    prove_before_scoring(*_red_case_proofs(cases, thresholds))
    settings = Settings(profile="local", audit_path=":memory:", tenant=_fixtures.TENANT)
    container = build_container(settings)
    service = build_review_service(container)

    grades: list[float] = []
    movements: list[float] = []
    floors: list[float] = []
    composites: list[float] = []
    routings: list[float] = []
    grounded: list[float] = []
    for case in cases:
        review = service.review(
            str(case["obligor"]),
            tenant=_fixtures.TENANT,
            actor=ACTOR,
            as_of=_fixtures.AS_OF,
        )
        proposal = review.assessment.proposal
        grades.append(1.0 if proposal.proposed_grade.value == case["expected_grade"] else 0.0)
        movements.append(1.0 if proposal.movement.value == case["expected_movement"] else 0.0)
        # An exact SET comparison: a retune that silently changed WHICH rule was deciding would
        # still reach the right grade, and a grade-only metric would call that a pass.
        floors.append(1.0 if set(proposal.applied_floors) == set(case["expected_floors"]) else 0.0)
        # The composite is the arithmetic the whole family-cap story rests on, and the routing
        # flag is rule R8's own precondition. Both are published per case, so both are scored:
        # a retune that moved a weight would otherwise leave the dataset quietly wrong.
        composites.append(
            1.0 if review.assessment.composite_score == case["expected_composite"] else 0.0
        )
        routings.append(
            1.0
            if review.assessment.requires_human_review == case["expected_requires_human_review"]
            else 0.0
        )
        if review.assessment.requires_human_review:
            # Only a routed proposal is narrated. A discarded draft scores zero and names why.
            grounded.append(1.0 if not review.memo_discarded_reason and review.memo_body else 0.0)

    # pii_safety: no raw identifier may survive into any audit record. The pack scan uses the
    # same rows the redactor masks with; the planted-literal check is an independent oracle that
    # fires even if a row is broken (the two-part scorer lesson from the C4 rollout).
    #
    # The scan reads the WHOLE record, not the summary field it used to read. A record carries
    # its citations too, those snippets are quoted upstream text, and a leak through them was
    # invisible to every oracle in this repo: an audit record is immutable, so the oracle over it
    # cannot be narrower than the record.
    records = [_scannable(entry) for entry in container.audit.log.read_all()]
    planted = [str(case["planted"]) for case in cases if case.get("planted")]
    pack_leaked = any(pack_leak(text, PII_PATTERNS) for text in records)
    literal_leaked = any(token in text for token in planted for text in records)
    pii_safety = 0.0 if (pack_leaked or literal_leaked) else 1.0

    scores = {
        "grade_accuracy": _mean(grades),
        "movement_accuracy": _mean(movements),
        "floor_precision": _mean(floors),
        "composite_accuracy": _mean(composites),
        "routing_accuracy": _mean(routings),
        "pii_safety": pii_safety,
        "narration_groundedness": _mean(grounded),
    }
    # Every bar against the denominator that actually reached it. `narration_groundedness` is
    # the one to watch: it is scored only over ROUTED proposals, so its denominator is smaller
    # than the case count and using 11 for it would certify a bar the run cannot support.
    denominators = dict.fromkeys(SCORED, len(cases))
    denominators["narration_groundedness"] = len(grounded)
    for metric in SCORED:
        assert_denominator_supports(thresholds[metric], denominators[metric], metric=metric)

    results = tuple(
        EvalMetricResult.scored(metric, scores[metric], thresholds[metric]) for metric in SCORED
    )
    return EvalReport(
        dataset=str(dataset),
        results=results,
        n_examples=len(cases),
        dataset_digest=dataset_digest(dataset),
        evaluator=_EVALUATOR,
    )


def _red_case_proofs(cases: list[dict[str, Any]], thresholds: dict[str, float]) -> tuple[Any, ...]:
    """One proof per scored metric, named after the metric, fed the scorers this run uses.

    The scoring here is inline rather than in named functions, so each proof rebuilds the one
    comparison its metric makes and shows it going red on a corrupted expectation. That is the
    same comparison the run performs three lines later, in this process, against these bars.
    """
    case = cases[0]

    def _match(expected: str, actual: str) -> float:
        return 1.0 if expected == actual else 0.0

    def grade_accuracy() -> None:
        assert_can_go_red(
            lambda expected: _match(expected, case["expected_grade"]),
            green=case["expected_grade"],
            red="doubtful" if case["expected_grade"] != "doubtful" else "pass",
            threshold=thresholds["grade_accuracy"],
            metric="grade_accuracy",
        )

    def movement_accuracy() -> None:
        assert_can_go_red(
            lambda expected: _match(expected, case["expected_movement"]),
            green=case["expected_movement"],
            red="downgrade" if case["expected_movement"] != "downgrade" else "hold",
            threshold=thresholds["movement_accuracy"],
            metric="movement_accuracy",
        )

    def floor_precision() -> None:
        # A SET comparison, and the red case is a set that reaches the same grade by a different
        # rule. That is the failure this metric exists for and the one a grade check calls a pass.
        expected = set(case["expected_floors"])
        assert_can_go_red(
            lambda applied: 1.0 if set(applied) == expected else 0.0,
            green=tuple(expected),
            red=(*expected, "floor-restructured"),
            threshold=thresholds["floor_precision"],
            metric="floor_precision",
        )

    def composite_accuracy() -> None:
        assert_can_go_red(
            lambda value: 1.0 if value == case["expected_composite"] else 0.0,
            green=case["expected_composite"],
            red=int(case["expected_composite"]) + 1,
            threshold=thresholds["composite_accuracy"],
            metric="composite_accuracy",
        )

    def routing_accuracy() -> None:
        assert_can_go_red(
            lambda flag: 1.0 if flag == case["expected_requires_human_review"] else 0.0,
            green=case["expected_requires_human_review"],
            red=not case["expected_requires_human_review"],
            threshold=thresholds["routing_accuracy"],
            metric="routing_accuracy",
        )

    def pii_safety() -> None:
        # The real pack, over a record carrying a planted identifier. Not a mock: a scan against
        # a fake pack proves the scan runs, and this metric's whole failure mode is a pack that
        # stopped matching.
        planted = next((str(c["planted"]) for c in cases if c.get("planted")), "S1234567A")
        assert_can_go_red(
            lambda text: 0.0 if pack_leak(text, PII_PATTERNS) or planted in text else 1.0,
            green="redacted summary with no identifier in it",
            red=f"redacted summary carrying {planted}",
            threshold=thresholds["pii_safety"],
            metric="pii_safety",
        )

    def narration_groundedness() -> None:
        assert_can_go_red(
            lambda memo: 1.0 if memo else 0.0,
            green="a narrated memo body",
            red="",  # the draft was discarded and the reviewer receives no explanation
            threshold=thresholds["narration_groundedness"],
            metric="narration_groundedness",
        )

    return (
        grade_accuracy,
        movement_accuracy,
        floor_precision,
        composite_accuracy,
        routing_accuracy,
        pii_safety,
        narration_groundedness,
    )


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    settings = Settings.load()
    if settings.profile != "gcp":
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            f"CREDITEWS_PROFILE=gcp (got {settings.profile!r}); "
            "run --mode smoke for the offline pre-merge check."
        )
    # Resolved through the CONTAINER, not by constructing a client here. The binding is then
    # configuration like every other port: an on-prem deployment gets an explicit refusal instead
    # of a client pointed at a service it does not run, and a repo cannot quietly grow a second,
    # differently-configured route to the same authority.
    container = build_container(settings)
    report = container.evaluation.evaluate(str(dataset))
    if not isinstance(report, EvalReport):
        raise SystemExit("EvaluationGatePort.evaluate did not return an EvalReport")
    return report, bool(container.evaluation.gate(str(dataset)))


if __name__ == "__main__":
    raise SystemExit(
        eval_main(
            smoke=run_smoke,
            gate=run_gate,
            default_dataset=DEFAULT_DATASET,
            description="Offline / model-quality-gate for credit-portfolio-early-warning.",
        )
    )
