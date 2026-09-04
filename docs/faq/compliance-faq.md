# Compliance FAQ

For compliance, model risk and the second line.

### Is the watchlist grade defensible in front of a regulator?

The **mechanism** is: every proposal names each floor rule it applied, cites every figure it used,
and is reproducible from the audit record without the source systems. The grade is computed by
pure deterministic code, so the same inputs give the same output, and a reviewer can replay it.

The **calibration** is not. The weights, family caps and band edges are reference defaults chosen
to be legible, not fitted to any book. There is no backtest, no discriminatory-power statistic and
no independent validation. Read [`../model-card.md`](../model-card.md) before you take this to a
supervisor, and do not describe `composite_score` as a probability of default: it ranks attention
and nothing more.

### Who signs off a grade change?

A human, always. The service proposes and never applies: `grade_applied` is typed `False` on every
response and `GradeRegistryPort` declares read methods only in every profile, so no write path to
the grading system of record exists in this build. Every proposal is routed to the `human-review-console`
maker-checker console in the same call that produced it (rule R8). Exposure above
`dual_control_exposure_minor` requires two approvers rather than one.

Note the loop is deliberately open at the far end: nothing here evidences that an approved
re-grade reached your rating system. Closing that is adoption work, and it is where a fork most
needs its own controls.

### Where does the data live, and is residency enforced or just documented?

Enforced. The region is set once and shared across the settings file, `render.tf.json` and the
Terraform `region` / `allowed_regions` pair, and the Terraform tests refuse a region outside the
allowlist at plan time rather than at apply time. The stack also carries Org Policy resource-location
constraints, a regional CMEK ring with per-service-agent bindings, and a dry-run-first VPC-SC
perimeter.

### What about key management and least privilege?

A regional CMEK key ring with per-service-agent bindings, one least-privilege serving identity,
and no service-account keys (the Org Policy constraint forbids them). This vertical's own data
resources are **not** in the stack yet: the BigQuery obligor-metrics and servicing dataset and the
adverse-media collection each still need their entry in `apis.tf`, `kms.tf`, `iam.tf` and
`vpc_sc.tf`. A service enabled with no CMEK binding encrypts under Google-managed keys and looks
identical in the console, so treat that as open work rather than a detail.

### How long is the audit trail kept, and can it be edited?

It is written to a locked WORM bucket with a retention lock, so it cannot be edited or deleted
before the retention period expires. **The lock is irreversible**: confirm `retention_days` with
your records function before the first apply. Each record carries the redacted assessment, the
rules applied and the citations, which is enough to reconstruct the decision without the source
systems.

### What personal data does this system process?

Obligor and guarantor identifiers, contact details appearing in servicing records, and names
appearing in adverse-media text. All of it is masked by `domain/pii.py` before the model, before
the audit write and before a review payload leaves the process. Redaction precedes the model and
the audit stores the redacted text; the audit path masks a second time as a defence against a
future caller that forgets the projection.

The jurisdiction rows and their ORDER in `domain/pii.py` are policy you own; the shipped set is a
reference.

### What model-risk evidence exists?

Today: the deterministic engine's own test suite, an offline eval gate with `floor_precision`,
`routing_accuracy`, `grade_accuracy`, `movement_accuracy`, `composite_accuracy`,
`pii_safety >= 0.99` and `narration_groundedness >= 0.98`, and the structural controls (no write
path, adverse-direction-only floors, capped external family, mandatory human review).

Not present, and this is the material point: no conceptual-soundness write-up, no development
evidence, no backtest, no discriminatory-power measure, no outcome monitoring, no override log and
no independent validation. The eval scores the engine against ITS OWN golden set, which proves
internal consistency and not predictive validity. `model-risk-validation` (the data-residency validator) is the sibling
that owns the challenge, and it has not seen this.

### Which regulations does this claim to satisfy?

None, by itself. The crosswalk in [`../../COMPLIANCE.md`](../../COMPLIANCE.md) maps the build's
controls to principles and to the MAS Notice 612 grade vocabulary the shipped ladder follows,
because the build targets Singapore. That crosswalk is **adopter-owned**: your jurisdiction, your
classification standard and your supervisor's expectations are yours to state, and the shipped
ladder is a starting point rather than a compliance claim.

### What is still open at go-live?

Model risk first, in the order given in the model card. Then: this vertical's cloud resources in
Terraform, the `agent-guardrail-gateway` binding before any widening of the adverse-media path, `agent-observability` and `agent-registry`
wiring, the alert on the age of `watchlist_since` (because this repo cannot detect an upstream
that never increments `clean_periods`), and the decision about how an approved re-grade reaches
your rating system.
