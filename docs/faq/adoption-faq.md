# Adoption FAQ

For engineering leads forking this repo. The full walkthrough is
[`../ADOPTING.md`](../ADOPTING.md); this page answers the questions that come up first.

### How do I rebrand it for my organisation?

One script:

```bash
python scripts/rename_fork.py --package acme_credit_ews --env-prefix ACME \
    --resource acme-ews --dry-run     # preview, writes nothing
python scripts/rename_fork.py --package acme_credit_ews --env-prefix ACME \
    --resource acme-ews --yes         # apply
```

It rewrites the package name (which is also the console script), the `CREDITEWS_` env prefix
including the bare token `infra/terraform/render.tf.json` carries as `render_env_prefix` and the
backticked form the docs carry, the Terraform `name_prefix` resource stem (`doc7-svc`) and the
distribution id. Add `--include-docs` to sweep Markdown prose too. It skips itself, so the renamer
is not left half-rewritten, and it renames the package directory last. The catalog id `Doc7` is
kept unless you pass `--catalog-id`, so a fork stays traceable to what it descends from.

Then recreate the venv (the distribution name changed) and run `make gate`.

### If several institutions fork this, how does each take upstream fixes?

Track upstream by git tag and rebase your adopter-owned changes onto each release, rather than
merging `main` continuously. The split is stated in [`../ADOPTING.md`](../ADOPTING.md) section 2:
upstream owns the vertical-neutral machinery, `ports/`, the contract tests, the eval mechanics and
the deploy stack; you own the `policy:` values, the fixtures, the golden datasets, the `onprem`
adapters, branding and the regulator crosswalk.

### What do we have to supply that is not in this repo?

- **A calibrated scorecard.** The shipped `EarlyWarningPolicy` is a reference. This is the big one;
  see [`../model-card.md`](../model-card.md).
- **A portfolio feed**: obligor metrics and servicing data behind `PortfolioFeedPort`.
- **Covenant terms**: from Doc2 or your own origination record, behind `CovenantTermsPort`.
- **An adverse-media feed** behind `AdverseMediaPort`.
- **A grade registry to read** behind `GradeRegistryPort`, and separately a decision about how an
  approved change gets written, which this repo will never do.
- **Your IdP audience** on the deployed service.
- **Your own synthetic fixtures and golden datasets.**

### Can I retune the policy without touching engine code?

Yes, and that is the design. `EarlyWarningPolicy` in `domain/policy.py` holds every bank-owned
number as data: the signal rules, the family caps, the band floors, the floor and ceiling grades,
the covenant and arrears weights, the past-due day counts, both materiality legs, the upgrade
constraints, `min_data_completeness`, `required_metrics` and `dual_control_exposure_minor`. The
settings file's `policy:` block overrides them.

Two behaviours to know. A `policy:` block that is PRESENT with an empty `signal_rules` list is
honoured as empty (you wrote it), and the engine then fires only covenant, arrears, review-clock
and coverage rules. And a partial mapping is a request-time failure rather than a silent gap:
`validate_policy` refuses a `family_caps` or `covenant_weights` block that does not price every
key the engine will look up.

### Does the gate run for my fork out of the box?

The offline gate does: `make gate` needs no network, no credentials and no cloud SDK. Hosted CI is
a different question. There are no workflow files to inherit, because GitHub Actions are disabled
organization-wide and the workflows were retired; the required check is a Cloud Build trigger
defined in `org-metadata/ci/gcp/repository-policy.json`. **A repository absent from that policy
gets no trigger and no required check, and nothing reports the omission.** Register your fork, or
stand up your own CI, before you rely on a gate.

### The eval reports high scores. Should we believe it?

Believe what it measures, which is that the engine is consistent with its own golden set. It is
not evidence that the grades are right for your book: the golden cases were written against the
shipped policy, so a fork inherits a green gate measuring the wrong numbers until the datasets are
rebuilt. Rebuild them, then believe it.

### How do I add a new outbound dependency?

Add a Protocol to `ports/`, implement it in all three adapter families, bind it in the `Container`
in `config.py`, and add a contract test so every family is held to the same behaviour. Do not
import a client library in `domain/`: the purity scan in the gate will fail, which is the point.

### Will the demo rot after I diverge?

`tests/unit/test_demo_surface.py` drives the whole arc inside the offline gate and fails if a step
has no expectation, and the hosted Cloud Build check runs that gate on every pull request. So the
demo cannot rot silently while the gate is running. `make demo-selftest` runs the same arc
headless on demand.

### What is still open?

The catalog row for Doc7 carries the honest list. In short: the scoring engine is uncalibrated and
unvalidated; this vertical's cloud resources are not in Terraform; Hrz1, Hrz5 and Hrz3 are
unwired; no Docker image has been built; the demo pages have not been rehearsed; and the loop back
to the rating system of record is open by design.
