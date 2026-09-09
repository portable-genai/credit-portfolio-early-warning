# Monitoring inputs

Two files this repository READS and never writes, both currently absent, both measured as absent
by `eval/run_model_risk.py`:

- `realised_outcomes.ndjson` scores `outcome_coverage`. One line per proposal that has since had
  an observable outcome, carrying at least `obligor_ref`, `as_of`, `proposed_grade` and
  `realised_outcome`. There is no such feed here and no historical sample.
- `override_log.ndjson` scores `override_coverage`. Schema and trigger levels in
  `docs/override-log.md`.

Absent is the honest state and the harness reports it as a FAILURE rather than as silence,
because a model nobody is watching and a model with a silent monitor look identical from
outside. The mechanism exists before the data so that the day a feed is connected, the thing
that reads it is already here and already failing loudly.

Nothing in this directory contains real data. `obligor_ref` is a pseudonym in both files, never
an obligor id or a name: see `docs/override-log.md`.
