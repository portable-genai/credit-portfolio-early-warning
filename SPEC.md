# SPEC: Credit Portfolio Early Warning (Doc7)

Locked decisions, pinned stack, contracts. This document is the deepest authority on intent.

## Pinned stack
- Python `>=3.12`; ruff pinned exactly (`0.16.4`); mypy strict; deploy region `asia-southeast1`.
- Commons declared by tag in `pyproject.toml` (`pii-kit@v0.0.1`, `hex-service-kit@v0.0.6`, `agent-eval-kit@v0.0.1`, `review-kit@v0.0.1`) and pinned in the lockfiles to the 40-character COMMIT each tag resolved to. A tag can be moved; a commit cannot, so a lockfile that pinned the tag would let what installs change with no diff. `tests/unit/test_repo_artifacts.py` asserts the three-way agreement offline.
- The `hex-service-kit` pin is a security floor, not a preference: releases from v0.4.0 onward
  check the service-identity policy before the token, gate the zero-secret local opening on an
  exact profile match, and bind the loopback exposure guard over both HTTP and WebSocket scopes;
  v0.5.1 resolves every environment read in three states, so a variable set to empty fails closed
  instead of inheriting the unset default. Never move this pin backwards.
- Installs are LOCKED: `requirements-dev.lock` and `requirements-gcp.lock` are committed and are
  what `make install`, CI and the container image install. Nothing ships from an uncommitted
  resolve.

## Contracts

### The vertical: what this service decides, and what it refuses to decide

Locked decisions. A change to any of them is a change to what the service MEANS, not a refactor.

- **The engine is a pure function.** `EarlyWarningEngine.evaluate(obligor, terms, covenant
  observations, arrears, observations, news, policy, as_of)` has no clock, no I/O, no randomness,
  no model, no network and no settings object. Weights and caps are INTEGERS end to end, so no
  band edge is decided by float drift and a replay on another machine cannot land one point away
  in a different grade.
- **The covenant vocabulary is consumed VERBATIM from credit-memo-drafting (Doc2)**, member for
  member and wire value for wire value, and so is the headroom arithmetic (the symmetric `abs()`
  form, so a negative threshold does not invert the band). Doc2 extracts at origination; this
  repo tests afterwards and never re-extracts. `tests/unit/test_covenant_vocabulary.py` is the
  compensating control for the fact that the enum is re-declared rather than imported.
- **Arrears materiality gates the past-due clock**, and it runs FIRST. Arrears are material only
  when the past-due amount clears BOTH an absolute floor and a percentage of drawn exposure.
  Every past-due rule and every past-due floor reads `effective_days_past_due`, never the raw
  figure. A non-firing is RECORDED as a zero-weight signal naming both limits and both observed
  values, because a second-line reviewer asks what was considered.
- **A covenant with no closed-period observation is `not_evidenced` and is never counted
  compliant; a covenant whose period is still open, or whose certificate grace has not elapsed,
  is `not_due` and is never counted missing.** They are different states on purpose. A term that
  HAS a usable observation is tested on it whatever the calendar says, because an observed breach
  is a fact.
- **A live waiver removes the grade FLOOR and never the SIGNAL.** A waiver whose expiry is before
  `as_of` is not a waiver: the status stays breach and the rule id becomes
  `covenant-breach-waiver-expired`, so an expired waiver is visibly different from a term that
  never had one. The engine never infers a waiver; it reads one over the port or there is none.
- **An external signal fires only when the FEED confirms the item is about this obligor.** The
  model may assign the CATEGORY, from a closed enum, and `classified_by` records that it did.
  No external or process signal ever sets a floor, in any configuration, and `validate_policy`
  refuses at LOAD any cap that would let either family reach the first adverse band alone.
- **The grade registry declares read methods only.** That is the enforcement of "never re-grades
  an obligor autonomously": not a boolean somebody could flip, but a method that does not exist.
  Two tests hold it, both shown red against a planted `set_grade`.
- **Downgrades are immediate and uncapped; an upgrade is hard to earn.** An upgrade needs
  consecutive clean periods, no fired high-severity signal, no covenant breach, and POSITIVE
  evidence above its own higher completeness floor, and is then capped at one notch. The evidence
  gate is the sharp one: the absence of signals in a file nobody evidenced is not good news.
- **LOSS is representable and unproposable.** The registry holds it, so the engine must be able
  to read a current grade of loss; the ceiling caps every proposal at DOUBTFUL and records itself
  in `applied_ceiling`, because a write-off is an impairment-committee determination.
- **Exposure sets the approval path and never the grade.** The engine module never references the
  exposure field, and `tests/unit/test_engine_never_reads_exposure.py` greps it. Materiality
  appears twice in this design and the two are named distinctly throughout.
- **Every fired signal and every non-compliant covenant test carries BOTH the policy row it
  derives from and the source locator of the figure it fired on, or the engine raises**
  `UngroundedSignalError`. Two rules are exempt by name, because they are findings about ABSENT
  evidence and there is no source to point at.

### The route

`POST /v1/watchlist-review`. Request: `obligor_id` (required; the key the registry holds, never a
free-text party name), `test_period` (empty means the latest the covenant feed reports),
`as_of` (empty means the surface resolves today), `news_lookback_days` (clamped server-side to
the policy maximum). It carries no actor, no tenant and no entitlement.

The response echoes the RESOLVED `as_of` and `test_period`, so a stored answer is
self-describing, and carries the grade of record, the band grade the composite alone produced,
the proposed grade, the movement and notches, every applied floor rule id, any applied ceiling,
any withheld reason, the composite and per-family raw-against-capped scores, the effective
past-due clock with its materiality verdict, the IFRS 9 backstop, data completeness, the covenant
table, the signal set, the item ids awaiting confirmation, the severity and decision, the review
reasons, `review_ref`, `required_approvals`, the memo (or the reason it was discarded), the
per-feed evidence counts, the citation set, and `grade_applied`, which is always false and is
TYPED on the response so a console can state it rather than imply it.

`GET /v1/obligors` is the read-only listing the console's picker uses. There is no write route.

An obligor under another tenant answers **403, never 404**, so the two statuses cannot be used to
enumerate another bank's book. An obligor the registry does not hold answers 404 and never a
default pass record.

### The platform contracts (unchanged by the vertical)

- **Identity**: a request's actor is a server-verified `Principal`; the client-supplied actor is
  discarded. Local profile resolves a seeded dev persona from `X-Dev-Persona`.
- **Redaction before anything**: `redacted_assessment` is built ONCE, where the result leaves the
  service, and the SAME masked object is handed to the WORM audit write, the outbound review
  payload and the model prompt. Masked: the obligor name, covenant detail (which carries the
  clause text), signal detail, evidence locators, citation snippets and the summary. NOT masked:
  every figure, every grade, every rule id, every join key and every citation LOCATOR, because a
  masked figure is a changed figure and a masked locator is a claim nobody can trace. The two
  sinks that cannot be corrected afterwards mask AGAIN from their own side: the outbound payload
  in `adapters/_review_payload.py`, and both content fields of the audit record in
  `_record_audit`. Every check of this property observes the SINK: the model prompts are captured
  through a wrapped `GenerationPort` and the audit assertion reads the whole record, because a
  check that rebuilds the masked object tests the masker and sees nothing the service did.
- **Determinism**: the composite, the band, the floors and the escalation are pure stdlib and
  replayable; an LLM may narrate but never produces any of them.
- **Maker-checker (P-06) and routing (R8)**: a proposal that sets `requires_human_review` IS
  routed through `ReviewRouterPort` to the Hrz7 console in the same request. The flag alone is
  not the escalation. `required_approvals` is 2 when the proposal is into a non-performing grade,
  when the current grade is non-performing and the movement is an upgrade, or when the exposure is
  above the bank's threshold. The managed adapter refuses to run with no console configured.
- **Policy is configuration**: every number the engine compares against is parsed from the
  `policy:` block of `config/settings.yaml` into a frozen `EarlyWarningPolicy`, and
  `validate_policy` REFUSES at load rather than at first request. That includes COVERAGE: a
  mapping in the block replaces the shipped one wholesale rather than merging into it, so a
  partial `family_caps`, `floor_grades`, `covenant_weights`, `arrears_weights` or
  `review_clock_weights` is refused by name, rather than reading a missing cap as zero or raising
  on the first obligor that reaches the missing row. `tests/unit/test_policy.py` asserts the
  shipped block parses into exactly the shipped code defaults, so the file and the dataclass
  cannot drift, and every knob in the block is read by the engine: an inert row beside a live one
  is worse than an absent one, because an operator diffing what is running cannot tell which is
  which.
- **Profile**: resolved ONCE, at import, into a `ProfileChoice` and never a bare string. Three
  states of `CREDITEWS_PROFILE`: UNSET is NO CHOICE (the SDK-free adapters
  still bind, but the seeded personas are refused, no service-to-service scheme is selected, every
  relaxation sees `unconfigured` and the exposure guard refuses every route to a non-loopback
  peer); SET AND EMPTY raises, so it can never inherit the unset behaviour; SET AND UNKNOWN,
  including a mis-capitalised value, raises. Only a deliberately named profile is honoured, and
  both raises happen before the process can serve anything.
- **Two derived postures, opposite directions**: `exposure_profile` drives every RELAXATION (CORS
  allowlist, the `X-Dev-Persona` allowed header, the HSTS baseline, the S2S scheme) and reads
  `unconfigured` when nobody chose; `bind_profile` drives the RESTRICTION (the loopback bound) and
  reads `local` when nobody chose. One string cannot do both without weakening one of them.
  Only `config.py` reads the variable.
- **End-user authentication is a property of the identity BINDING**, declared by the adapter
  (`VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED`) and read by the loopback exposure guard. The
  service-to-service secret authenticates a calling SERVICE and no end user, so it takes no part
  in that decision: setting it closes the S2S routes and relaxes nothing.
- **Audit integrity**: the trail is hash-chained AND externally anchored. `audit_anchor_path`
  points at a file on a different volume that every append writes the chain head to; without it
  a truncated tail is undetectable, because the shorter chain still verifies. Once store and
  anchor disagree the service refuses to append rather than re-anchoring, so an ordinary write
  cannot launder a divergence. Re-anchoring is a deliberate operator action.
- **Agent surface**: optional but scaffolded. The A2A card at `/.well-known/agent-card.json` is
  built from the same tool table the runtime binds, so advertised skills and implemented tools
  are the same set. Tool results are masked for personal data before they return, because a tool
  result becomes model context (P-04); an API response to the credit officer who has to act on
  the covenant text is not. A tool SIGNATURE is a request schema, because a runtime derives the
  JSON parameter schema from it, so no tool takes an actor, a tenant or an entitlement either:
  both are resolved server-side, exactly as on the route. Nothing in `agent/` needs a runtime to
  import.
- **Ports**: a port is registered in five places (`PORT_PROTOCOLS`, `DEFAULT_BINDINGS`, the
  `Container` accessor, `config/settings.yaml`, and the canonical-call table) and the contract
  suite asserts set equality across all five, in both directions.
- **Demo**: the demo is code and it is asserted. `scripts/walkthrough.py` narrates eight steps
  and, at each one, checks that the service actually reached the state the narration claimed;
  `--auto --headless` runs the same steps unattended in CI. A step exists in exactly two places
  (`demo.STEPS` and `walkthrough.CHECKS`) and the two are held equal, so a narrated claim nobody
  verifies cannot exist. The demo needs no browser engine, no network and no cloud.
- **UI identity**: the browser never asserts who it is. Every client-supplied actor, tenant,
  role, ACL and authorization header is discarded before a request is forwarded; identity is
  resolved server-side and the resolved headers are attached afterwards. The service credential
  is read from the server environment only. Framing and CORS are allowlists that refuse a
  wildcard however it is written, and an empty allowlist denies rather than opening up.
- **Eval**: `--mode smoke` is the offline pre-merge check; `--mode gate` is the Hrz4 promotion
  authority. The gate fails closed.
- **Tests**: split into `unit`, `contract` and `integration`. The offline gate runs the first
  two; every integration module is marked, and that marking is itself enforced.

## Metrics and thresholds (smoke)

- `grade_accuracy >= 1.00`
- `movement_accuracy >= 1.00`
- `floor_precision >= 1.00` (the applied-floor rule id SET, compared exactly)
- `composite_accuracy >= 1.00`
- `routing_accuracy >= 1.00` (rule R8's own precondition, per case)
- `pii_safety >= 0.99` (pack scan plus a pack-independent planted-literal check, over the WHOLE
  audit record and not one field of it)
- `narration_groundedness >= 0.98`

Every metric that scores the ENGINE sits at 1.00 deliberately. They score a PURE FUNCTION against
hand-written fixtures, so anything below one is a defect rather than drift, and a threshold set
lower would let a real regression pass. `floor_precision` compares the SET of applied floor rule
ids rather than the grade, because a grade-only metric passes a case that reached the right
answer for the wrong reason, and a retune that silently changed which rule was deciding is
exactly what has to be caught.

Every expectation the golden file carries is scored. `expected_composite` and
`expected_requires_human_review` were published per case and read by nothing, which made the
composite a second copy of a number only the demo walkthrough enforced: retune a weight and the
walkthrough went red while the dataset quietly became wrong documentation.

Near-perfect accuracy on a deterministic engine over a synthetic golden set flatters, and
`grade_accuracy` of 1.00 proves very little on its own. What makes the set worth running is the
two NEGATIVE cases in it: delete the arrears materiality gate and `obl-kappa-010` starts
proposing `special_mention` on a 640.00 arrear; raise the external family cap above the first
adverse band and `obl-lambda-011` starts proposing a downgrade driven entirely by categorised
media. Both were run and both were observed failing. If either is ever deleted or weakened to
make a build green, the metrics stop meaning anything.
