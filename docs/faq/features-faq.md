# Features FAQ

For product, credit and delivery. What the engine does, what is deterministic, and where this
repo stops.

### What does it actually do?

It reviews one obligor for one reporting period and proposes a watchlist grade, with reasons.

1. **Tests covenants** against the terms `credit-memo-drafting` extracted at origination,
   read over `CovenantTermsPort`. Each test produces a `CovenantStatus`: compliant, in a headroom
   band, breached, waived, or untestable because the reporting is stale.
2. **Runs the arrears clocks.** Days past due are measured against the material-arrears legs, and
   the thirty-, ninety- and one-hundred-eighty-day thresholds are applied.
3. **Fuses early-warning signals** from financial spreads, servicing behaviour and adverse media
   into a `composite_score`, with each signal family capped.
4. **Applies the ladder.** The score maps to a `WatchGrade` through `band_floors`, and floor rules
   (a breach, a repeat breach, an arrears clock, a restructuring) override the band adversely.
5. **Drafts a cited review memo** and routes the whole proposal to a human reviewer (`human-review-console`).

Every figure it states carries a citation. A signal with no citation does not enter the
assessment.

### What is deterministic, and what does the model write?

The consequential path is pure stdlib and replayable: the covenant tests, the arrears clocks, the
composite score, the floors, the ceiling, the grade proposal, the approval count and the routing
decision are all computed by `domain/`, which imports nothing but the standard library.

A model does exactly two bounded things, and neither can change a grade:

- **Categorises an already-confirmed media item** into a closed enum. Any malformed reply, wrong
  item id, unknown category or exception yields `UNCLEAR`. The result enters the capped `EXTERNAL`
  family, which may never classify an obligor on its own.
- **Drafts the memo prose**, only for a proposal that already requires human review, and only from
  the redacted projection. It is validated against a schema, a digit-token grounding oracle and a
  cited-source check, and DISCARDED on any failure. A discarded memo costs a paragraph.

See [`../model-card.md`](../model-card.md) for the pinned model, the call parameters and the
controls that are still open.

### What will it refuse to do?

- **Apply a grade.** `grade_applied` is typed `False` on every response, and `GradeRegistryPort`
  declares read methods only in every profile. There is no write path to the grading system of
  record anywhere in this build, on any surface.
- **Propose an impairment stage or book an allowance.** `Ifrs9Backstop` flags the thirty- and
  ninety-day past-due presumptions AS presumptions. The standard's primary test needs a lifetime
  PD model this repo does not have.
- **Let an external signal floor a grade.** Adverse media is capped and cannot classify alone.
- **Upgrade freely.** An upgrade needs `upgrade_min_clean_periods` clean periods, is limited to
  `max_upgrade_notches`, and requires `upgrade_min_data_completeness`.
- **Score a thin file as if it were complete.** Below `min_data_completeness` the assessment
  reports the gap rather than a confident grade.
- **Invent a covenant.** It tests what origination extracted, and nothing else.

### Which surfaces expose it?

| Route | What it drives |
|---|---|
| `POST /v1/watchlist-review` | The whole review for one obligor and one period: the proposal, every applied floor rule named, every figure cited, `grade_applied` false. |
| `GET /v1/obligors` | The read-only listing the console's picker uses. There is no write counterpart on this or any surface. |

### What does this repo own, and what does it integrate?

**Owns:** the covenant test engine, the arrears clocks, the signal catalogue and its caps, the
watch-grade ladder and its floors, the composite score, the review memo, the approval-count rule,
and the audit projection.

**Integrates, and must not rebuild:**

| Sibling | Boundary |
|---|---|
| `credit-memo-drafting` | Extracts covenants at origination. This repo tests them afterwards. The vocabulary is consumed verbatim over `CovenantTermsPort` so the two cannot disagree, and no arrow points the other way. |
| **the data-residency validator** `model-risk-validation` | Owns challenge and validation of the scoring engine. Not optional here. |
| `human-review-console` | Owns the maker-checker workflow. This repo routes to it (rule R8); it does not re-implement a console. |
| `agent-registry` | Discovery. The A2A card is published at `/.well-known/agent-card.json`. |
| `model-quality-gate` eval / quality gate | Owns promotion verdicts. |
| `agent-observability` and WORM audit | Owns the immutable audit sink and traces. |
| `agent-guardrail-gateway` | **Not bound.** See the security FAQ; it matters here because adverse-media text reaches the model. |
| `enterprise-knowledge-base` | Not integrated. |

### Can I demo it without a cloud project?

Yes. `make demo` runs the whole arc on loopback with the `local` profile: fixture portfolio feed,
fixture covenant terms, fixture adverse media, deterministic narration stub. No credentials, no
network, no SDK. `make demo-selftest` runs the same arc headless and exits non-zero when a step
stops being true.

### What is not built yet?

The honest list lives in the catalog row and in [`../../COMPLIANCE.md`](../../COMPLIANCE.md). The
headline items: the scoring engine is uncalibrated and unvalidated (see the model card); this
vertical's own BigQuery and adverse-media resources are not in `infra/terraform/`; `agent-guardrail-gateway`, `agent-observability` and
the `agent-registry` registration are unwired; and the loop back from an approved re-grade to the rating
system of record is deliberately open, because this repo will never write one.
