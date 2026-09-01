# Adopting this repo as your base

This repository (Doc7, the Credit Portfolio Early Warning agent) is a **common base** that a bank
or other lender forks to build its own **post-origination monitoring engine**: a service that
tests covenant compliance against the terms extracted at origination, fuses early-warning signals
from financial spreads, servicing behaviour and adverse news through a deterministic scoring
engine, and drafts a cited watchlist-grading proposal and review memo for a credit officer. It
ships a reusable hexagonal core (a pure-stdlib domain, typed ports, three swappable adapter
profiles, a green offline gate) plus a fully worked watch-grade vertical you can keep, retune, or
replace with your own grading ladder.

**Read [`model-card.md`](model-card.md) before you read anything else here.** The scoring engine
is a model in the supervisory sense whatever it is written in, the shipped weights are reference
defaults rather than a calibrated scorecard, and this repo ships no backtest. Adoption work that
does not start with model risk starts in the wrong place.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical rebrand**
(one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md) (the port table and topology),
> [`CONTRIBUTING.md`](../CONTRIBUTING.md) (adding an adapter, adding a port), the
> [`faq/`](faq/) directory, [`model-card.md`](model-card.md) (the model boundary and what is
> unvalidated), [`practices-audit.md`](practices-audit.md) (the per-check verdict).

---

## 1. What you keep vs what you rewrite

The core is hexagonal, and the boundary between reusable machinery and the credit vertical is a
physical module split with an enforced dependency direction. `domain/kernel.py` owns the
vertical-neutral contracts and imports nothing from the vertical, so you can import it without
loading a line of credit logic; `domain/models.py` holds this service's request and result types.

| Layer | Where | For a new vertical |
|---|---|---|
| **Vertical-neutral machinery** | `domain/kernel.py` (`Citation`, `AuditEvent`, `Severity`, `Decision`, `utcnow`), `domain/errors.py`, every Protocol in `ports/`, the container wiring in `config.py` | keep untouched |
| **Policy (your numbers and sets)** | the whole of `EarlyWarningPolicy` in `domain/policy.py` (the signal rules, family caps, band floors, floor and ceiling grades, covenant and arrears weights, the past-due day counts, the materiality legs, the upgrade constraints, `min_data_completeness`, `dual_control_exposure_minor`), the jurisdiction rows in `domain/pii.py`, the metric thresholds in `eval/run_eval.py` | change deliberately (see section 4) |
| **Vertical (the artifacts themselves)** | the Doc7 models in `domain/models.py` (`WatchGrade`, `CovenantType`, `CovenantOperator`, `CovenantStatus`, `SignalFamily`, `Ifrs9Backstop`, the obligor and review types), the engines (`early_warning.py`, `policy.py`), the orchestrator (`watchlist_service.py`), the narrator (`narration.py`), the local fixture corpora under `adapters/local/` and the eval golden sets | rewrite for your book |

If your product is another *observations-in, cited-and-graded-proposal-out* monitor, most of the
hexagon, the three profiles, the deterministic-scoring pattern, the eval gate and the Hrz7 review
routing transfer directly; you replace the signal families and their sources, and retune the
policy dataclass.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly:

- **Upstream-owned** (take our changes): the vertical-neutral machinery listed above, `ports/`,
  `tests/contract/`, the eval harness mechanics (`eval/run_eval.py`), the hexagon wiring
  (`config.py` `Container`) and the deploy stack in `infra/terraform/`.
- **Adopter-owned** (yours; expect to edit): `config/settings.yaml` *values* including the whole
  `policy:` block, the local fixture corpora and the golden eval datasets, `adapters/onprem/*`,
  UI theming and branding, `infra/terraform/terraform.tfvars`, and the regulator crosswalk
  section of `COMPLIANCE.md`.

Track upstream via git tags; rebase your adopter-owned changes onto each release rather than
merging `main` continuously.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the package name (`credit_portfolio_ews`, which is also the
console script), the `CREDITEWS_` env prefix (including the bare `CREDITEWS` that
`infra/terraform/render.tf.json` carries as `render_env_prefix`, so Terraform sets the same
variable names on the Cloud Run service), the cloud resource stem (`doc7-svc`, the Terraform
`name_prefix`) and the distribution / git id in one pass. Preview first, then apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_credit_ews --env-prefix ACME \
    --resource acme-ews --dry-run

# Apply:
python scripts/rename_fork.py --package acme_credit_ews --env-prefix ACME \
    --resource acme-ews --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
make install
make gate
```

`--dist` defaults to the `--resource` value; pass it explicitly when your git id differs from
your resource stem. `--resource` is validated against the same `^[a-z][a-z0-9-]{2,18}$` regex the
Terraform `name_prefix` variable enforces, so a stem the stack would refuse fails here instead of
at plan time. `--package` must be a valid snake_case Python identifier. Add `--include-docs` to
sweep Markdown prose too; without it the script leaves `.md` files alone so a code rename stays
deterministic. The script skips itself, so the renamer is not left half-rewritten, and it renames
`src/credit_portfolio_ews/` last, after the file contents are rewritten. The catalog id `Doc7` is
left alone unless you pass `--catalog-id`, so a fork stays traceable to the entry it descends
from. The script deliberately does NOT touch the human decisions below, and in particular it does
not touch a single policy number: a fork that has run the renamer has rebranded a scorecard it
has not calibrated.

## 4. The human decisions (the script can't make these)

1. **Model risk, first and before anything else.** `domain/early_warning.py` is a MODEL under
   SR 11-7 and PRA SS1/23 whatever language it is written in. This repo ships no model card of
   your own, no conceptual-soundness write-up you have signed, no backtest of whether these
   signals actually predict deterioration in YOUR book, no outcome-monitoring plan and no
   independent validation. `composite_score` ranks attention; it does not estimate a probability
   of default and must not be read as one. Route the engine through your model-risk function
   (Rsk4, `model-risk-validation`, is the sibling that owns this) before it informs a real credit
   decision. See [`model-card.md`](model-card.md) for the full list of what is unvalidated.
2. **Region / residency.** The build defaults to `asia-southeast1` (MAS / Singapore), chosen once
   and shared: `config/settings.yaml:region`, `infra/terraform/render.tf.json:render_region` and
   the Terraform `region` / `allowed_regions` pair. Set all of them to your in-country region and
   re-run the residency tests in `infra/terraform/`, which refuse a region outside the allowlist
   at plan time. See [`runbook.md`](runbook.md).
3. **Identity / IdP.** This repo owns no login flow: the `gcp` profile verifies the IAP-injected
   assertion at the edge, `local` uses seeded dev personas, and `onprem` is a client IdP
   placeholder. Wire your issuer on the deployed service (auth is configured ON the service, not
   in this code) and set `CREDITEWS_IAP_AUDIENCE`. An unset or emptied audience refuses every
   caller rather than verifying without one.
4. **The watch-grade ladder and its floors.** `EarlyWarningPolicy.band_floors` maps a composite
   score to a `WatchGrade`, and `floor_grades` names the rules that override the band outright:
   a covenant breach, a repeat breach, the arrears clocks, and a restructuring. The shipped
   ladder follows the MAS Notice 612 grade names because the build targets Singapore; if you
   report under a different classification standard, replace the enum members AND the floors
   together, because a floor naming a grade your ladder does not have is a request-time failure
   rather than a silent mis-grade. Keep the two invariants the engine encodes: a floor rule can
   only ever move a grade in the adverse direction, and `CEILING_NO_LOSS` prevents the engine
   proposing a loss classification it has no basis to propose.
5. **The signal rules and their family caps.** `signal_rules` is the priced catalogue of what
   counts as a warning, and `family_caps` bounds how much any one family can contribute.
   `EXTERNAL` (adverse media, the family a model influences) and `PROCESS` (findings about our
   own file) are the two bounded families: neither may classify an obligor on its own. If you
   raise those caps you are removing the only bound on a feed you do not control. Note that
   `NewsRelevance` is the FEED's assertion, so a feed that marks everything confirmed leaves the
   family cap as the only defence and a name collision becomes a real signal.
6. **The covenant vocabulary is consumed, not defined here.** `CovenantType` and
   `CovenantOperator` are pinned verbatim to what `credit-memo-drafting` (Doc2) extracts at
   origination, over `CovenantTermsPort`. Doc2 extracts, this repo tests, and no arrow points the
   other way. If you fork both, change the vocabulary in Doc2 and take it here; changing it here
   alone makes origination and monitoring disagree about the same covenant.
7. **The counters this service reads and never maintains.** `clean_periods` and
   `consecutive_breaches` arrive from upstream. A registry that never increments `clean_periods`
   makes the upgrade path unreachable, and nothing in this repo can detect that. The runbook asks
   for an alert on the age of `watchlist_since` for exactly this reason; wire it.
8. **Data completeness is scored against a list you write.** `min_data_completeness` is measured
   against `required_metrics`. `validate_policy` refuses an EMPTY list, but a short non-empty one
   reports high completeness over a thin file. Make the list match what your spreading actually
   delivers.
9. **The exposure threshold that sets the approval path.** `dual_control_exposure_minor` decides
   which proposals need two approvers. It is EXPOSURE materiality and it never touches the grade;
   the separate arrears materiality legs gate the past-due clock. Set both with your credit
   policy owners, and keep them distinct.
10. **Reference data is fictional.** Every fixture (`adapters/local/_fixtures.py` and the local
    portfolio-feed, covenant-terms, adverse-media and grade-registry corpora) and the golden eval
    datasets use obviously fake obligor names and `.example` domains. Replace them with your own
    synthetic data. **Do not run against a real lending book without your own security, legal and
    model-risk sign-off.**
11. **Eval golden set.** Rebuild the golden datasets for your ladder and your policy: a fork
    inherits a green gate that measures the WRONG numbers until you do. The gate structure and
    the strict `pii_safety >= 0.99`, `floor_precision == 1.0` and `routing_accuracy == 1.0`
    metrics are generic; the golden cases are yours.
12. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root uid 10001),
    `infra/terraform/` (Org Policy, CMEK, a dry-run-first VPC-SC perimeter, the locked WORM log
    bucket) and the loopback-by-default binding before you expose anything. The WORM lock is
    irreversible: confirm `retention_days` before the first apply. This vertical's own cloud
    resources are NOT in the stack yet: the BigQuery obligor-metrics and servicing dataset and
    the adverse-media collection each need their entry in `apis.tf`, `kms.tf`, `iam.tf` and
    `vpc_sc.tf` plus their own file. That is adoption work, not a flag to flip.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable systems. Several concerns it *touches* are
owned by sibling services, and you should integrate rather than rebuild them (see
[`faq/features-faq.md`](faq/features-faq.md) for the full map). The `gcp` profile's adapters are
the seams those integrations switch into:

- **Doc2** `credit-memo-drafting`: the covenant terms extracted at origination, over
  `CovenantTermsPort`. This repo tests covenants; it never extracts them, and it never invents a
  covenant the origination record does not carry.
- **Hrz7** human-review / maker-checker console: every grading proposal is routed to it over the
  shared `review-kit` (rule R8); you wire your endpoint (`HUMAN_REVIEW_URL`), you do not
  re-implement the console. **The loop is deliberately open**: this service proposes and routes,
  and nothing here evidences that an approved re-grade reached the rating system of record.
  `GradeRegistryPort` declares read methods only, in every profile. Closing that loop is your
  integration work, and it is the one place where a fork most needs its own controls.
- **Rsk4** `model-risk-validation`: owns the challenge and validation of the scoring engine. It
  is not optional for this repo (see decision 1).
- **Hrz3** agent registry: this agent publishes its A2A card at
  `/.well-known/agent-card.json`; register it rather than inventing a discovery mechanism.
- **Hrz4** AI-quality / model-risk gate: owns promotion. `eval/run_eval.py --mode gate` is the
  client half and refuses to run off the managed profile; the offline smoke mode mirrors the
  thresholds but never promotes.
- **Hrz5** observability plus immutable WORM audit: audit events and trace spans go to it via
  `AuditSinkPort` and `ObservabilityTracerPort`.

The guardrail gateway (Hrz1) is **not** integrated today, and that matters more here than the
usual boilerplate: untrusted adverse-media text DOES reach the model on the narration path,
bounded only by a closed enum, a capped family and the no-external-floor rule. Hrz1 becomes
mandatory the moment you widen any of those three. The enterprise knowledge base (Hrz2) is not
integrated either.

## 6. Adoption checklist

- [ ] Read [`model-card.md`](model-card.md) and booked the model-risk work BEFORE anything else.
- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make gate` green.
- [ ] Set the region in all three places (settings, `render.tf.json`, tfvars) and re-ran the
      Terraform residency tests.
- [ ] Wired your IdP audience on the deployed service (this repo owns no login flow).
- [ ] Replaced the watch-grade ladder and its floors together, keeping the adverse-direction-only
      floor invariant and the no-loss ceiling.
- [ ] Repriced `signal_rules` and set `family_caps` deliberately, knowing that raising the
      EXTERNAL cap removes the only bound on a feed you do not control.
- [ ] Confirmed the covenant vocabulary still matches what your origination system extracts.
- [ ] Wired an alert on the age of `watchlist_since`, because this repo cannot detect an upstream
      that never increments `clean_periods`.
- [ ] Made `required_metrics` match what your spreading actually delivers.
- [ ] Set both materiality legs and `dual_control_exposure_minor` with your credit policy owners.
- [ ] Replaced every synthetic fixture corpus and both golden datasets.
- [ ] Rebuilt the eval golden set for your ladder and policy.
- [ ] Added this vertical's own BigQuery and adverse-media resources to `infra/terraform/`.
- [ ] Reviewed the deploy posture (Dockerfile, Terraform, `retention_days`, bind address).
- [ ] Decided how an approved re-grade reaches your rating system of record, given that this
      repo will never write one.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
