#!/usr/bin/env python3
"""Generate the SYNTHETIC calibration sample the discrimination harness scores.

Read the limits before the numbers.

This sample contains no real obligors and no realised outcomes. It is drawn from a stated
generative model: a latent deterioration state, and observable figures emitted from that state
with enough overlap that the problem is not trivial. Scoring the scorecard against it measures
whether the scorecard's STRUCTURE, its weights, its family caps and its band edges, recovers a
latent state through noisy observations, UNDER THAT MODEL. It does not measure whether the
scorecard predicts real deterioration, and no number this produces may be reported as if it
did. If the generative model below is wrong about the world, every statistic downstream of it
is wrong in the same direction and will not say so.

What it is nevertheless good for, and why it is worth having under SR 11-7 while a historical
sample does not exist:

* it is the only thing in this repository that can go red when a weight, a cap or a band edge
  is retuned into incoherence. The regression metrics in `eval/run_eval.py` pin the arithmetic
  to hand-written expectations, so a retune that moves both the code and the expectations is
  invisible to every one of them, and the eleven golden cases were written from the same
  intuition the weights were;
* it makes the assumption ARGUABLE. The distributions here are a written claim about which
  signals lead deterioration and by how much, and a validator can disagree with a number in
  this file in a way they cannot disagree with a weight in `policy.py`.

Usage::

    python scripts/render_calibration_sample.py            # rewrite the sample
    python scripts/render_calibration_sample.py --check    # non-zero when the file is stale

Deterministic: one fixed seed, one recorded model version, so the committed file is a function
of this script alone and `--check` in the gate fails an edit that was never re-rendered.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

OUTPUT = _REPO_ROOT / "eval" / "datasets" / "synthetic_calibration.jsonl"

#: Stamped on every row. A change to the generative model below is a change to this string, or
#: the rows claim to come from an assumption that is no longer the one written down.
MODEL_VERSION = "synthetic-deterioration-v1"

#: The one seed. Named rather than inlined because reproducibility is the property that makes
#: `--check` mean anything.
SEED = 20260910

#: How many obligors, and how many of them are deteriorating. 240 and 0.25 are chosen for the
#: denominator rather than for realism: AUC over a small sample is a wide interval, and a
#: prevalence far below this leaves too few positives to say anything. A real portfolio's
#: watchlist prevalence is lower, and that is one of the several ways this sample is not a
#: portfolio.
N_OBLIGORS = 240
PREVALENCE = 0.25

#: The generative claim, one row per observable, as (stable_mean, stable_sd, stressed_mean,
#: stressed_sd). The gap between the two means, measured in standard deviations, IS the claim
#: that this signal leads deterioration, and its size is the claim about how strongly. Every
#: one of these is a judgement a validator should push back on; none is fitted to anything.
#:
#: The overlaps are deliberate and are the point. A stressed obligor whose leverage happens to
#: read 3.6 exists here, because one exists in a portfolio, and a sample without them would
#: measure a discrimination no scorecard could achieve on real data.
DISTRIBUTIONS: dict[str, tuple[float, float, float, float]] = {
    # Leverage rises first and is the single most-cited leading indicator in credit review.
    "net_debt_to_ebitda": (2.60, 0.70, 4.60, 1.10),
    # Debt service coverage falls as earnings thin; the rule fires below 1.20.
    "dscr": (1.75, 0.35, 1.15, 0.30),
    # Liquidity is noisier than leverage and moves later, so a smaller separation.
    "current_ratio": (1.45, 0.30, 1.05, 0.28),
    # Revolver utilisation is behavioural and moves EARLY, often before a statement lands.
    "revolver_utilisation_pct": (58.0, 16.0, 88.0, 12.0),
    # Collections concentration drifts, and drifts for benign reasons too: the weakest claim
    # in this table, and it carries the smallest weight in the scorecard as well.
    "collections_concentration_pct": (62.0, 12.0, 52.0, 14.0),
}

#: EBITDA is emitted as a level and a prior-period level, because the rule that reads it is a
#: DELTA rule. A generative model that emitted only a level would leave `fin-ebitda-decline`
#: unable to fire at all, and a signal that cannot fire in the sample is a signal the harness
#: silently does not measure.
EBITDA_BASE = 40_000_000.0
EBITDA_DECLINE = (-0.05, 0.12, -0.34, 0.18)

#: Arrears are conditional on the state rather than drawn from it: most obligors are current,
#: and a stressed obligor is much more likely to have run past due. The days are the clocks the
#: engine's own tiers read.
ARREARS_PROBABILITY = (0.04, 0.38)
ARREARS_DAYS = (0, 15, 35, 95)
ARREARS_DAY_WEIGHTS = ((0.70, 0.20, 0.08, 0.02), (0.10, 0.28, 0.37, 0.25))

#: Adverse media, same shape. The EXTERNAL family is capped in the scorecard precisely because
#: this input is the least reliable, and the sample reflects that: a stable obligor picks up
#: litigation coverage often enough to matter.
NEWS_CATEGORIES = ("litigation", "rating_downgrade", "supplier_distress", "regulatory_action")
NEWS_PROBABILITY = (0.10, 0.45)


def _clamped(rng: random.Random, mean: float, sd: float, low: float, high: float) -> float:
    return round(min(max(rng.gauss(mean, sd), low), high), 4)


def _row(rng: random.Random, index: int, stressed: bool) -> dict[str, Any]:
    leg = 2 if stressed else 0
    metrics: dict[str, list[float]] = {}
    for metric, params in DISTRIBUTIONS.items():
        mean, sd = params[leg], params[leg + 1]
        low, high = (0.0, 1_000.0) if metric.endswith("_pct") else (0.0, 40.0)
        # Two consecutive periods, because the leverage and utilisation rules only fire on a
        # SUSTAINED reading. One period would leave both of them dead in this sample.
        metrics[metric] = [
            _clamped(rng, mean, sd, low, high),
            _clamped(rng, mean, sd, low, high),
        ]
    decline_mean, decline_sd = EBITDA_DECLINE[leg], EBITDA_DECLINE[leg + 1]
    decline = round(min(max(rng.gauss(decline_mean, decline_sd), -0.90), 0.90), 4)
    metrics["ebitda"] = [
        round(EBITDA_BASE, 2),
        round(EBITDA_BASE * (1.0 + decline), 2),
    ]

    arrears_days = 0
    if rng.random() < ARREARS_PROBABILITY[1 if stressed else 0]:
        arrears_days = rng.choices(
            ARREARS_DAYS, weights=ARREARS_DAY_WEIGHTS[1 if stressed else 0], k=1
        )[0]
    news = []
    if rng.random() < NEWS_PROBABILITY[1 if stressed else 0]:
        news = [rng.choice(NEWS_CATEGORIES)]
    return {
        "id": f"syn-{index:04d}",
        "latent_state": "deteriorating" if stressed else "stable",
        "metrics": metrics,
        "arrears_days_past_due": arrears_days,
        "adverse_news": news,
        "model_version": MODEL_VERSION,
        "fictional": True,
    }


def render() -> str:
    rng = random.Random(SEED)
    stressed_count = round(N_OBLIGORS * PREVALENCE)
    states = [True] * stressed_count + [False] * (N_OBLIGORS - stressed_count)
    rng.shuffle(states)
    header = [
        "# SYNTHETIC calibration sample. No real obligors, no realised outcomes, no historical",
        "# data of any kind. Generated by scripts/render_calibration_sample.py from the stated",
        "# generative model recorded there; `latent_state` is that model's own label and is NOT",
        "# an observed outcome. Scoring against it measures the scorecard's structure under that",
        "# assumption and says nothing about predictive validity. See docs/model-card.md.",
    ]
    rows = [json.dumps(_row(rng, i, stressed)) for i, stressed in enumerate(states, start=1)]
    return "\n".join(header + rows) + "\n"


if __name__ == "__main__":
    from agent_eval_kit import render_main

    raise SystemExit(
        render_main(
            output=OUTPUT,
            render=render,
            description="Regenerate the synthetic calibration sample from its recorded model.",
            argv=sys.argv[1:],
        )
    )
