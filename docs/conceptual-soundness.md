# Conceptual soundness: the early-warning scoring engine

SR 11-7 asks for a written argument that a model's design, theory and logic are sound, made
before and independently of how well it happens to score. `docs/model-card.md` recorded this as
**Absent**. This is that document.

Read the next paragraph before anything else. **This is an argument, not evidence.** Every claim
below is ex ante reasoning about why a signal should lead deterioration, drawn from ordinary
credit-review practice. None of it is fitted to outcomes, because there are no outcomes here. A
conceptual-soundness write-up is a necessary control and it is the weakest of the model-risk
controls: it establishes that the design is defensible and coherent, and it cannot establish that
the design is right. The controls that could are still Absent, and the model card still says so.

## What the model is

`domain/early_warning.py` fuses covenant tests, arrears clocks, review-clock findings, coverage
findings and adverse-media items into an integer `composite_score`, and `domain/policy.py` maps
that score onto a `WatchGrade`. It is pure deterministic stdlib and it is a model: under SR 11-7
and PRA SS1/23 a quantitative method that processes inputs into estimates used in a credit
decision is a model whatever it is written in, and a hand-set scorecard is one of the oldest
kinds.

What it outputs is an ordinal triage rank. A higher score means more reasons to look. It is not
a probability of default, not a rating and not an input to expected credit loss, and nothing in
this repository may say otherwise: `tests/unit/test_no_probability_claim.py` enforces that on
the shipped text.

## The theory of the model

The scorecard rests on one claim: **credit deterioration is visible in several partially
independent places before it is visible in default, and it is visible in some of them earlier
than in others.** Everything else follows from how far each source is trusted.

Four families, in the order they are trusted:

**FINANCIAL (cap 40) is the evidential core.** Leverage, coverage, liquidity and earnings are
facts about the obligor's ability to service debt, and they are the facts a credit officer would
act on alone. `fin-leverage-trend` carries the heaviest single weight (20) and requires two
consecutive periods, because a single leverage reading moves on a working-capital swing and a
sustained one does not. `fin-dscr-thin` (18) fires below 1.20 rather than below 1.00: the point
of an early-warning system is to fire while there is still headroom, and a DSCR at 1.00 is a
problem rather than a warning. `fin-ebitda-decline` (15) is a delta rule for the same reason a
level rule would be wrong here, since a business can be small and healthy but not shrinking fast.
`fin-liquidity-thin` (12) is weighted below the other three because a current ratio is the most
easily managed of the four at a reporting date.

**BEHAVIOURAL (cap 30) leads FINANCIAL in time and trails it in reliability.** Utilisation,
excess days, returned debits and collections concentration come from the transaction warehouse
and move weekly, where statements move half-yearly. That is why the family exists and why it is
capped below FINANCIAL: a borrower can draw a revolver for an acquisition, and the signal is
noisier per observation than a covenant test. `beh-utilisation-jump` (15, a 25-point delta) is
weighted above `beh-utilisation-sustained` (12, two periods at 95%) because a jump is news and a
high level may be a business model. `beh-excess-days` (12) requires more than five days, so a
single settlement failure is not a warning. `beh-collections-drop` (10) carries the lowest weight
in the family and is the weakest claim in this document: receipts concentration falls for benign
reasons at least as often as for adverse ones.

**EXTERNAL (cap 20) may never classify an obligor on its own, and that is the most important
structural decision here.** Adverse media is the input a model touches: an item's category is
assigned by a model from a closed set, and entity resolution on a common company name is the
classic false positive. The cap is what makes a wrong category unable to move a grade by itself.
`ext-insolvency` carries 20 because a filed insolvency is close to fact rather than sentiment;
the rest carry 12 or 8. `NewsRelevance` defaults to the inert value, so a feed that omits the
field arms nothing.

**PROCESS (cap 20) is findings about our own file, not about the obligor.** A missing covenant
certificate, a stale one, an overdue or absent review. These belong in the score because a file
nobody can evidence is a risk, and they are capped low and separated from FINANCIAL because
punishing an obligor for our own administration would be a category error. An ABSENT review is
weighted the same as an overdue one (12) and given a higher severity, because the difference is
about escalation, not about score.

## The band edges

`(0, PASS), (35, SPECIAL_MENTION), (70, SUBSTANDARD), (90, DOUBTFUL)`.

35 is deliberately below the heaviest single financial signal plus the next: one serious finding
alone should not put an obligor on the watchlist, and two should raise a question. 70 is above
the FINANCIAL cap, so no accumulation of financial signals alone reaches SUBSTANDARD without
something from a second family, which is the same independence claim the whole scorecard rests
on. 90 is above FINANCIAL plus BEHAVIOURAL, so the most adverse proposal available needs a
covenant breach or an arrears clock behind it, and those set floors rather than scores.

## The floors, and why they only move one way

A covenant breach, a repeat breach, the arrears clocks and a restructuring set a grade FLOOR: the
proposal may be worse than the floor and never better. These are events, not evidence, and the
argument for treating them differently from signals is that a breach has already happened while
a signal is a prediction. `CEILING_NO_LOSS` caps the engine below a loss classification in the
other direction, because a loss classification is a judgement about recovery that no amount of
early-warning evidence supports.

## What would falsify this argument

Named so a validator has something to test rather than something to agree with.

1. **If BEHAVIOURAL signals do not lead FINANCIAL ones in time**, the cap ordering is wrong and
   the family should be weighted up or the two merged. Testable on any historical sample by
   measuring the lag between the first behavioural firing and the first financial one.
2. **If EXTERNAL items are as reliable as covenant tests**, the cap is costing real early
   warning. Testable by measuring precision of the category assignment against confirmed events.
3. **If the deterioration rate is not monotone across the four bands**, the edges are wrong
   wherever it inverts. This one is measured now, on synthetic data, by `band_monotonicity` in
   `eval/run_model_risk.py`, and it holds under the stated generative model.
4. **If `collections_concentration_pct` carries no signal**, the weakest claim above is wrong and
   the rule should be removed rather than left carrying 10 points.
5. **If the composite ranks no better than its strongest single component**, the fusion is
   adding nothing and the scorecard should be replaced by that component.

Only the third is measured at all today, and only against an assumption.

## What is measured now, and what it is worth

`eval/run_model_risk.py` scores the scorecard against a synthetic sample whose labels come from
the generative model in `scripts/render_calibration_sample.py`. That model is a written claim
about which observables separate deteriorating obligors from stable ones, and it is a claim a
validator can disagree with in a way they cannot disagree with a weight in `policy.py`.

The measured results, and the limit they carry:

- **AUC 0.975** on the shipped sample, against a floor of 0.80.
- **Inverting the family caps** so EXTERNAL and PROCESS dominate drops it to **0.743** and fails.
  That is the red case the harness runs before it scores anything.
- **Flattening every rule weight to 1** scores **0.951**. **Reversing the weight order** scores
  **0.923**. Both pass.

The last line is the finding. On this sample the ranking is driven by WHICH signals fire, not by
how heavily they are weighted, so this measurement validates the family structure and the caps
and says nothing about the weights. The weights remain reference defaults chosen to be legible,
exactly as the model card says, and only a historical sample can move that.

## What is still Absent

Unchanged from the model card and repeated here so this document cannot be read as closing more
than it closes: development evidence, a backtest, discriminatory power on real outcomes,
independent validation. Outcome monitoring and the override log now have a MECHANISM and no
data, which `eval/run_model_risk.py` reports as a failure rather than as silence.

## Related

- `docs/model-card.md` for the control inventory and the boundary.
- `docs/override-log.md` for the challenge log's schema and trigger levels.
- `docs/evals.md` for what the regression gate measures, which is a different thing entirely.
