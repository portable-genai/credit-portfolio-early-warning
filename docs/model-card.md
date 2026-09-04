# Model card: Credit Portfolio Early Warning (`credit-portfolio-early-warning`)

This is a STARTER model card. It records the model boundary as built and the controls that must
be completed before this service informs a real credit decision.

**This repo contains two things a supervisor would call a model, and only one of them is an
LLM.** Most model cards in this catalog describe a generative seam and stop there. That would be
misleading here, so this card has two halves: the **scoring engine**, which is the consequential
one, and the **narration model**, which is bounded and cannot change an outcome.

---

## Part 1: the scoring engine is a model, and it is not validated

`domain/early_warning.py` fuses covenant tests, arrears clocks, review-clock findings, coverage
findings and adverse-media signals into a `composite_score`, and `domain/policy.py` maps that
score onto a `WatchGrade`. It is pure, deterministic stdlib. **That does not make it not a
model.** Under SR 11-7 and PRA SS1/23 a quantitative method that processes inputs into estimates
used in a credit decision is a model whatever it is written in, and a hand-set scorecard is one
of the oldest kinds.

What is missing, stated plainly so nobody has to discover it:

| Control | Status |
|---|---|
| Conceptual soundness write-up | **Absent.** No document argues why these signals, these weights and these band edges should predict deterioration. |
| Development evidence | **Absent.** The weights, family caps and band edges in `EarlyWarningPolicy` are REFERENCE defaults chosen to be legible in a demo. They were not fitted, tuned or selected against outcomes. |
| Backtest | **Absent.** Nothing in this repo measures whether a flagged obligor subsequently deteriorated, or whether an unflagged one did not. There is no historical sample here to measure against. |
| Discriminatory power | **Unmeasured.** No AUC, no Gini, no rank-order statistic. `composite_score` has never been shown to separate deteriorating obligors from stable ones. |
| Outcome monitoring | **Absent.** No plan and no mechanism for tracking realised outcomes against proposals. |
| Independent validation | **Absent.** Not reviewed by a validation function. `model-risk-validation` (the data-residency validator) is the sibling that owns this and has not seen it. |
| Override and challenge log | **Absent.** Nothing records where a credit officer disagreed with a proposal, which is the cheapest early evidence a scorecard is mis-calibrated. |

### What `composite_score` is, and is not

It **ranks attention**. It is an ordinal triage aid whose only defensible claim is that a higher
score means more reasons to look. It is **not** a probability of default, not a rating, and not
an input to expected credit loss. Anyone reading it as a PD is reading it wrong, and the number
carries no calibration that would make that reading safe.

The IFRS 9 treatment is deliberately narrow for the same reason. `Ifrs9Backstop` flags the
thirty-day and ninety-day past-due presumptions AS presumptions. The engine proposes no
impairment stage and books no allowance, because the standard's primary significant-increase
test needs a lifetime PD model this repo does not have and does not pretend to have.

### The structural controls that ARE present

These are real and worth keeping through any recalibration:

- **Nothing is applied.** The service proposes a grade; `grade_applied` is typed `False` on every
  response. `GradeRegistryPort` declares read methods only, in all three profiles, so there is no
  write path to the grading system of record anywhere in the build.
- **Floors move one way.** A floor rule (covenant breach, repeat breach, the arrears clocks, a
  restructuring) can only ever make a grade more adverse. `CEILING_NO_LOSS` stops the engine
  proposing a loss classification it has no basis for.
- **Two families are bounded.** `EXTERNAL` (adverse media) and `PROCESS` (findings about our own
  file) are capped and may never classify an obligor on their own. This is the only reason a
  model-influenced input cannot drive a grade.
- **Every figure is cited.** A signal without a citation does not enter the assessment.
- **A proposal is routed to a human** in the same call that produced it (rule R8), and exposure
  above `dual_control_exposure_minor` requires two approvers.

### Before this informs a real credit decision

1. Write the conceptual-soundness argument: why each signal family is a leading indicator in
   YOUR book, and why the weights rank them the way they do.
2. Assemble a historical sample and backtest. Report rank-order performance and calibration of
   the band edges, not just accuracy against your own labels.
3. Recalibrate `EarlyWarningPolicy` against that sample, and record the fitted values and the
   date. Delete the reference defaults rather than leaving them as a fallback.
4. Define outcome monitoring and the trigger levels at which the scorecard is re-fitted.
5. Submit to independent validation (the data-residency validator) and record the finding here.
6. Log officer overrides from day one, including during pilot.

Until steps 1 to 5 are complete, this engine is a demonstrator. It is safe to run offline against
synthetic data and it is not cleared to inform a lending decision.

---

## Part 2: the narration model, which is bounded

Unlike most repos in this catalog, the managed generation adapter here **is wired and does call a
model**.

- **Model**: `gemini-3.5-flash`, pinned as a module constant in
  `adapters/gcp/generation.py` so `config.generator_model` names it by reading the BINDING rather
  than a second settings string that could drift.
- **Call shape**: `temperature=0.0`, `max_output_tokens=768`, `response_mime_type="application/json"`.
- **System instruction**: restate facts as JSON, never introduce a figure, date or grade that was
  not supplied, never recommend a classification.

It has exactly two jobs, both behind the single `GenerationPort.generate` seam:

| Job | Where | What bounds it |
|---|---|---|
| Categorise one **already-confirmed** media item | `watchlist_service.py` | Output must parse as JSON, echo the same `item_id`, and be a member of the closed `NewsCategory` enum. Any failure, including any exception, returns `NewsCategory.UNCLEAR`. The result then enters the capped `EXTERNAL` family, which cannot classify an obligor alone. |
| Draft the review memo | `watchlist_service.py`, `narration.py` | Only produced when the assessment already requires human review. `validate_memo` checks it against a schema, a digit-token grounding oracle and a cited-source check, and DISCARDS it on any failure. A discarded memo costs a paragraph, never a decision. |

The prompt is built from the **redacted** projection, so what the model may see is exactly what
it may say back, and the grounding oracle is built from the same masked object. Redaction
precedes the model, and the audit stores the redacted text.

| Profile | Generation adapter | Behaviour |
|---|---|---|
| `local` | `adapters/local/generation.py` | Deterministic stub. SDK-free, no model, no network. |
| `gcp` | `adapters/gcp/generation.py` | **Wired.** Calls the pinned Vertex model with the lazy SDK import. |
| `onprem` | `adapters/onprem/generation.py` | Fail-fast placeholder naming the client-hosted gateway to bind. |

### Remaining controls on the narration path (TODO, repo owner)

- **Prompt-injection screening** (rule R1). The `agent-guardrail-gateway` is **not** bound today, and
  untrusted third-party text DOES reach the model: an adverse-media headline and snippet are
  written by someone outside the bank about the obligor. The three things standing in the way of
  that mattering are the closed output enum, the `EXTERNAL` family cap and the rule that an
  external signal can never floor a grade. Bind `agent-guardrail-gateway` before widening any of those three, and fail
  closed to deterministic-only when the screen is unavailable.
- **Per-tenant token budget and rate limit** (P-10). `max_output_tokens` bounds one reply; nothing
  bounds a caller's aggregate spend.
- **A documented kill switch** (P-11). Rebinding the profile to `local` is deterministic-only
  operation today, but that is a deployment change rather than an operator action. Make it one,
  and document it in the runbook.
- **Reasoning trace** (P-07). The audit record carries the redacted assessment and its citations,
  not a prompt and reply pair.
- **Managed-profile evaluation** (P-08, rule R5). `eval/run_eval.py` scores the deterministic
  pipeline with the local stub bound. Add a managed-profile run registered with the `model-quality-gate` that
  scores memo groundedness and categorisation agreement with a real model bound.
- **Model version drift.** `gemini-3.5-flash` is pinned in code, but nothing fails the build when
  the served model behind that alias changes. Record the exact served version at each promotion.

---

## Reference data

Every fixture and both golden datasets use fictional obligors and `.example` domains. There is no
real lending data in this repository, and none of the numbers here were derived from any.
