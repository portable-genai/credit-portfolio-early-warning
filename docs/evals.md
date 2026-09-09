# Evals

How this repository knows when it is wrong, in two parts that measure different things and must
not be read as one.

The scoring engine in `domain/early_warning.py` is a model under SR 11-7 and PRA SS1/23: a
quantitative method that processes inputs into estimates used in a credit decision is a model
whatever it is written in, and a hand-set scorecard is one of the oldest kinds. A regression gate
is not the evidence a model owes. So there are two harnesses, and the first thing this page does
is keep them apart.

| | `eval/run_eval.py` | `eval/run_model_risk.py` |
|---|---|---|
| Scores | a pure function against hand-written expectations | the scorecard's structure against a stated assumption, and whether the monitoring controls exist |
| Corpus | 11 golden cases over one synthetic estate | 240 synthetic obligors, plus two absent feeds |
| Bars | all 1.00 | a discrimination floor, a coherence bar, and two that fail on purpose |
| Answers | "did the arithmetic move?" | "is the scorecard coherent, and is anyone watching?" |
| Does not answer | anything about predictive validity | anything about the world |

Neither is a backtest. There is no historical outcome sample in this repository and none is
claimed. `docs/model-card.md` is the control inventory and it is still the honest one.

## What the regression gate measures

`eval/run_eval.py`. Every bar is 1.00 and every bar lives in
`eval/rubrics/regression.yaml` beside the argument for it. There is no threshold dict
in the runner: a metric scored with no reviewed bar fails the build, and so does a bar
that names no scored metric, which is the direction that rots quietly because it rots
toward looking well governed.

These metrics score a PURE FUNCTION against hand-written expectations. They prove the
arithmetic did not move under a grade somebody already acted on. They prove nothing
about whether the scorecard predicts anything, and no number in this table may be
cited as though they did.

| Metric | Bar | What it measures |
|---|---|---|
| `composite_accuracy` | 1 | Share of cases where the integer composite matches. This is the arithmetic the whole family-cap story rests on, so it is scored rather than left as a field the dataset publishes and nothing reads. |
| `floor_precision` | 1 | Share of cases where the applied-floor rule id SET matches exactly. A set comparison, not a count: a retune that silently changed WHICH rule was deciding still reaches the right grade, and a grade-only metric calls that a pass. |
| `grade_accuracy` | 1 | Share of golden cases where the proposed WatchGrade matches the expected one. Binary per case; 11 cases. |
| `movement_accuracy` | 1 | Share of cases where the proposed movement (upgrade, downgrade, hold) matches. Scored separately from the grade because a grade can be right while the movement against the grade of record is not. |
| `narration_groundedness` | 1 | Share of routed proposals that produced a memo rather than a discarded draft. Raised from 0.98 for the same arithmetic reason as pii_safety, and because a routed proposal whose narration was discarded is a proposal a reviewer receives with no explanation. |
| `pii_safety` | 1 | No raw identifier survives into any audit record, scored two independent ways: the shared pii-kit pack scan over the WHOLE record, and a planted-literal oracle that still fires if a pack row is broken. Raised from 0.99, which over 11 binary cases was already the same bar: 10/11 is 0.909. |
| `routing_accuracy` | 1 | Share of cases where requires_human_review matches, which is rule R8's own precondition. Nothing here is applied, and the routing flag is what makes that true in the response rather than only in the docstring. |

Scored over 11 golden cases, dataset digest
`791c9798b736`, by `offline regression gate (deterministic engine, no GCP creds)`. At 11 cases
scored 0/1, the loosest bar that would tolerate a single failure is
0.91, so every bar here that used to read
0.98 or 0.99 was already all-or-nothing and now says so.

## What the model-risk harness measures

`eval/run_model_risk.py`. A different kind of bar, and the distinction is load-bearing:
under SR 11-7 and PRA SS1/23 the scoring engine is a model, and a regression gate is
not the evidence a model owes.

The first two metrics are measured against a SYNTHETIC sample whose labels come from
the generative model recorded in `scripts/render_calibration_sample.py`, not from
realised outcomes. They say whether the scorecard's structure is coherent under a
written assumption a validator can read and disagree with. They are not a backtest.
The last two measure whether the controls that would produce real evidence exist at
all, and both score zero.

| Metric | Score | Bar | What it measures |
|---|---|---|---|
| `band_monotonicity` | 1.000 | 1 | Share of adjacent watch-grade bands whose observed deterioration rate does not fall as the grade worsens. Bands holding fewer than 8 obligors are reported and not scored. |
| `outcome_coverage` | 0.000 | 0.7 | Share of recorded proposals carrying a realised outcome. Currently 0.000: there is no outcomes feed in this repository and no historical sample. (outstanding: no control) |
| `override_coverage` | 0.000 | 1 | Whether the override and challenge log exists and holds entries, as a 0/1. Currently 0.000: the log exists as a schema and a document, and no proposal has been reviewed. (outstanding: no control) |
| `rank_discrimination` | 0.975 | 0.8 | AUC of the composite score against the synthetic latent deterioration label, ties counted at 0.5. Measured over 240 synthetic obligors, 60 of them labelled deteriorating. |

Band table from the same run:

```
  band            n   deterioration rate
  ---------------------------------------
  pass             178   0.045
  special_mention   54   0.833
  substandard        8   0.875
  doubtful           0   0.000
```

## What is exercised

- **11 golden cases** in `eval/datasets/golden_cases.jsonl`, over ONE
  synthetic estate whose inputs live in `adapters/local/_fixtures.py` and are read by
  the local adapters, the demo and this dataset alike. Hand-written expectations, held
  equal to those fixtures by `tests/unit/test_golden_dataset.py`.
- **240 synthetic obligors** in `eval/datasets/synthetic_calibration.jsonl`,
  60 of them labelled deteriorating by the generative model that produced
  them. No real obligors, no realised outcomes, no historical data of any kind. The
  file is rendered from one seed and `--check` fails the gate when it is stale.
- **Zero realised outcomes and zero logged overrides.** Both are measured rather than
  assumed: `monitoring/` holds neither file and the harness reports that as a failing
  metric. See `monitoring/README.md`.
- **The falsification proofs run first in both harnesses.** `prove_before_scoring` is
  the opening statement of each scored run, so every metric is shown going red on its
  own planted defect in the same process, against the same bars, before any score is
  trusted. `tests/unit/test_not_falsely_green.py` adds what a proof cannot say about
  itself: that there is one for every metric scored, in both families.

## Why the monitoring metrics fail, and why that is the design

`outcome_coverage` and `override_coverage` score 0.000 and will keep scoring 0.000 until someone
connects a feed. That is not a defect in the harness; it is the harness working.

A model with no monitoring and a model with a silent monitor look identical from outside. Both
produce no alerts. The difference only becomes visible when something goes wrong, which is the
moment at which the distinction stops being useful. So the mechanism is built before the data
exists, and it reports absence as a failure rather than as nothing at all.

The build does not stay red forever, because a gate that is red on every pull request from the
day it is written gets bypassed, and a bypassed control is worse than an absent one: it also
produces a green tick somewhere. `make gate` runs the harness in `--gate` mode, which enforces
the two metrics that CAN be measured, prints the outstanding ones under an OUTSTANDING banner,
and fails if the outstanding set stops agreeing with `docs/model-card.md`. Connect an outcomes
feed and the gate goes red until the card is updated, which is the point: the card is the
artefact a supervisor reads, and a control that quietly starts working is a control whose status
is quietly wrong.

`make model-risk-full` gives the unvarnished verdict, non-zero, for a person or a scheduled run.

## What the synthetic sample is worth, and what it is not

`eval/datasets/synthetic_calibration.jsonl` holds 240 fictional obligors whose observable figures
are drawn from a generative model recorded in `scripts/render_calibration_sample.py`: a latent
deterioration state, and observables emitted from it with enough overlap that the problem is not
trivial. `latent_state` is that model's own label. It is not an observed outcome and nothing
derived from it may be reported as one.

What the measurement is worth:

- It is the only thing in this repository that goes red when a retune makes the scorecard
  **incoherent**. Inverting the family caps so adverse media and process findings dominate, the
  exact failure the caps exist to prevent, drops AUC from 0.975 to 0.743 and fails the bar. That
  red case runs before any score is trusted.
- It makes the assumption **arguable**. The distributions in the generator are a written claim
  about which signals lead deterioration and by how much, and a validator can disagree with a
  number in that file in a way they cannot disagree with a weight in `policy.py`.

What it is not worth, stated because the number is high enough to be misread:

- **It does not validate the weights.** Flattening every rule weight to 1 scores 0.951;
  reversing the weight order scores 0.923. Both pass. On this sample the ranking is driven by
  which signals fire, not by how heavily they are weighted.
- **It does not measure the top band.** No obligor in the sample reaches a composite of 90, so
  DOUBTFUL is empty and `band_monotonicity` says nothing about that edge. An unexercised edge in
  a monotonicity check reads exactly like a sound one.
- **It cannot be wrong in a way it would notice.** If the generative model is wrong about which
  signals lead deterioration, every statistic downstream of it is wrong in the same direction
  and silent about it.

## What nothing here measures

- **Predictive validity.** No historical sample, no backtest, no rank-order statistic on real
  outcomes. `docs/model-card.md` records this as Absent and it stays Absent.
- **Development evidence.** The weights, family caps and band edges are reference defaults
  chosen to be legible. They were not fitted, tuned or selected against outcomes.
- **Independent validation.** Not reviewed by a validation function.
- **The narration model's quality beyond grounding.** A routed proposal either produced a memo
  or discarded the draft; nothing scores whether the memo is any good.

## Running it

```
make eval             # render-check the sample, the regression gate, the doc check
make model-risk       # the gate-mode model-risk harness
make model-risk-full  # the full verdict, non-zero while monitoring has no data
make gate             # everything above plus lint, tests and the plugin render
make evals-doc        # regenerate the derived sections of this page
```

## Related

- `docs/model-card.md` for the control inventory and the model boundary.
- `docs/conceptual-soundness.md` for why these signals, weights and band edges at all.
- `docs/override-log.md` for the challenge log's schema and trigger levels.
- `monitoring/README.md` for the two feeds that do not exist.
