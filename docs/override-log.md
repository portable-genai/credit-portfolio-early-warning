# Override and challenge log

`docs/model-card.md` records this control as **Absent**, with the reason: nothing records where
a credit officer disagreed with a proposal, and officer disagreement is the cheapest early
evidence that a scorecard is mis-calibrated. This document defines the log. The log itself is
`monitoring/override_log.ndjson` and it holds no entries, because no proposal from this service
has been reviewed by anyone.

That empty state is measured rather than assumed. `eval/run_model_risk.py` scores
`override_coverage` as 0.000 against a bar of 1.0 and the harness exits non-zero. A control that
exists as a document and produces no evidence is not a control, and the difference between "we
have a log" and "the log has entries" is the whole of it.

## What goes in it

One line per interaction where a human's decision differed from the proposal, or where the
proposal was challenged and upheld. Both directions matter: an upheld challenge is evidence the
scorecard was right in a case where a person expected otherwise, and a log that records only
disagreements over-samples the failures.

```json
{
  "logged_at": "2026-07-14T09:22:00Z",
  "obligor_ref": "obl#3f2a1c9d4e77",
  "as_of": "2026-06-30",
  "proposed_grade": "special_mention",
  "decided_grade": "pass",
  "direction": "downgrade_rejected",
  "reason_code": "signal_stale",
  "reason": "Utilisation jump was a bridge draw for a completed acquisition, evidenced in the file.",
  "decided_by_role": "credit_officer",
  "model_version": "ews-policy-2026-06",
  "composite_score": 42,
  "applied_floors": [],
  "signals_disputed": ["beh-utilisation-jump"]
}
```

Every field is required except `signals_disputed`. Three of them carry decisions rather than
data:

- **`obligor_ref` is a pseudonym, never an obligor id or a name.** The same SHA-256 form the
  audit records use. This file is a monitoring artefact that will be read by people outside the
  credit team, and an override log is exactly the shape of file that leaks a portfolio.
- **`decided_by_role`, not `decided_by`.** The finding is that a role disagreed, and at the
  volumes an override log reaches, a named individual is identifiable from a handful of entries.
  Attribution belongs in the WORM audit trail, which is access-controlled; this file is not.
- **`reason_code` from a closed set**, so the log can be counted, with `reason` as free text so
  it can be read. A log with only free text is a log nobody analyses. The set:
  `signal_stale`, `signal_wrong`, `evidence_outside_model`, `weight_disputed`,
  `band_edge_disputed`, `floor_disputed`, `data_quality`, `upheld`.

## Trigger levels

These govern a human escalation, not a build, which is why they are here and deliberately not
thresholds in `eval/rubrics/`. A build that failed on an override rate would teach people not to
log overrides.

| Observation | What it means | Action |
|---|---|---|
| Override rate above 30% over a quarter | The scorecard and the officers disagree more often than they agree about anything | Re-fit is on the table; validation function is informed |
| Override rate above 15% | Ordinary disagreement, but enough to look at | Review the reason-code distribution at the next model committee |
| One `reason_code` above 40% of overrides | A specific rule or edge is wrong, not the scorecard | Fix that rule; record the change in `docs/conceptual-soundness.md` |
| `band_edge_disputed` clustered at one edge | The edge is in the wrong place | Move the edge and re-run the calibration harness |
| Fewer than 20 entries in a quarter with the service in use | The log is not being kept | Escalate the process, not the model |
| Zero entries, service not in use | The current state | No action; `override_coverage` reports it |

The last row is where this repository is.

## Why a downgrade that is rejected is the most valuable entry

An officer who rejects a proposed downgrade is asserting that the model saw something that is
not there. Aggregated over a quarter with a reason-code distribution, that is a fault report on
specific rules, and it arrives long before any realised outcome does. It is the only feedback
channel that works on a book with no defaults in it yet, which describes every early-warning
system in its first two years.

An accepted downgrade is not logged, because it is not evidence: an officer accepting a proposal
may agree with the reasoning or may be deferring to it, and the log cannot tell those apart. That
is a known blind spot of this control and not a defect in the schema.

## How it will be written

Not from this service. `GradeRegistryPort` declares read methods only in every profile and
there is no write path to the grading system of record anywhere in this build, which is a
control worth keeping. The log is written by whatever system records the credit decision, and
this repository reads it. The harness therefore treats an absent file as an absent control and
never as a quiet one.

## Related

- `docs/model-card.md` for the control inventory.
- `docs/conceptual-soundness.md` for what an override would falsify.
- `eval/run_model_risk.py` for the measurement.
