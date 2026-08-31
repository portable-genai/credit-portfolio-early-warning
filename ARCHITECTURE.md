# ARCHITECTURE: Credit Portfolio Early Warning (Doc7)

Hexagonal ports-and-adapters. A pure-stdlib domain core speaks only to ports (`typing.Protocol`s);
adapter families implement them; one env var (`CREDITEWS_PROFILE`) swaps the
whole stack with no domain edits.

Profile selection is an exact lookup. Every declared profile has an entry for every port; when
two profiles intentionally reuse one adapter, both entries name it. A missing local or exit
binding never inherits `gcp`, so it cannot import a managed SDK or change data custody silently.

`local` runs the real API, orchestration and deterministic domain with local or synthetic edges.
It may reduce OCR/narration quality, throughput, durability, enterprise identity, managed safety
and telemetry, but it does not change figures, evidence links, escalation rules or schemas.
`make portability` executes this boundary. If a primary managed operation is ever added as a
construction-only seam, the same change must name it in `managed_readiness.py` and refuse both API
startup and Terraform serving authorization until its live integration test exists.

## Layout (`src/credit_portfolio_ews/`)
- `domain/` : pure stdlib, no cloud/framework imports.
  - `kernel.py` : vertical-neutral types and the commons `StrEnum` taxonomies. Untouched.
  - `models.py` : this vertical's artifacts. The covenant vocabulary consumed verbatim from
    credit-memo-drafting, the supervisory grade ladder with its rank map, the evidence records
    and the result types.
  - `policy.py` : the frozen `EarlyWarningPolicy`, `SignalRule`, the shipped reference rule set
    and `validate_policy`, loaded from the `policy:` block of `config/settings.yaml`.
  - `early_warning.py` : the PURE engine. No clock, no I/O, no model, no settings object. It
    imports only the standard library plus this package's kernel, models, policy and errors.
  - `watchlist_service.py` : the orchestration. It only talks to ports, and it owns the ONE
    redaction seam and the one place the exposure figure is read.
  - `narration.py` : the model boundary. `build_prompt` and `validate_memo`, plus the grounding
    oracle. Nothing consequential.
  - `errors.py` : `UngroundedSignalError` and `ObligorNotFoundError`.
  - `pii.py` : the jurisdiction pattern selection and order.

  **The decision path and the drafting path are separated by the IMPORT GRAPH, not by
  convention.** `early_warning.py` does not import `narration.py`, and `narration.py` imports no
  port at all. A model cannot reach the engine without an edit that is visible in a diff.
- `ports/` : `@runtime_checkable` Protocols, re-exported once with the `PORT_PROTOCOLS` map.
  `identity.py` adds this service's own identity vocabulary: what an adapter DECLARES about the
  end-user authentication it provides (`VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED`), which is
  what the loopback exposure guard reads, plus the refusal type that carries a status and a reason
  when no end user can be authenticated at all. `tenancy.py` holds the one cross-tenant refusal
  every read port shares: 403 for a record under another tenant, 404 only for one that exists
  nowhere.
- `adapters/{local,gcp,onprem}/` : one adapter per port per profile. GCP imports are lazy.
  `adapters/_review_payload.py` is the shared, redacted conversion to the review kit's wire shape.
- `config.py` : `Settings` + `Container` (lazy DI, dotted `module:Class` bindings loaded from
  `config/settings.yaml`).
- `api/` : FastAPI app wired with the commons identity / S2S / fail-closed helpers.
- `cli/` : a stdlib argparse CLI.
- `agent/` : the optional-but-scaffolded agent surface. `tools.py` holds plain Python callables
  that delegate to the domain services (no business logic of their own) and route escalations
  like every other surface; `agent_card.py` builds the A2A discovery card served at
  `/.well-known/agent-card.json`. Nothing here needs ADK or a cloud SDK to import or test:
  `build_function_tools()` is the single lazily-imported runtime seam.

## Surfaces outside `src/`
- `scripts/` : the demo surface. `demo.py` holds the scripted arc and drives the REAL services;
  `render_ui.py` paints its panels as dependency-free static HTML; `demo_server.py` serves the
  same panels live, one real step per click; `walkthrough.py` drives that server over loopback
  HTTP and asserts every step, which is what lets the presenter tool double as the unattended
  self-test. `portability_demo.py` and `check_docs_links.py` are standalone checks. Nothing here
  is imported by `src/`, and `.dockerignore` keeps all of it out of the serving image.
- `ui/` : the embeddable Next.js micro-frontend. Its security boundary is one policy module
  (`lib/embed-policy.mjs`) shared by the document-layer `proxy.ts` and the same-origin API route,
  plus one server-side identity module (`lib/server/identity.ts`). The browser never asserts an
  actor and never holds the service credential. Delete it with `make drop-ui` if this repo has no
  user-facing surface; the gate checks that decision for consistency in both directions.

## Test layout (`tests/`)
`unit/` (one module or service, driven by the REAL local adapters), `contract/` (the boundary
claims: conformance, the five-way port drift guard, behavioural parity), `integration/` (needs a
live service; marked so the offline gate deselects the whole directory) and `fixtures/` (shared
data only). `contract/canonical.py` holds ONE canonical request per port, so the structural and
behavioural suites cannot quietly assert different things.

## Request pipeline (`WatchlistReviewService.review`)

read the obligor and its grade of record from the registry (which has no write method) -> read
the covenant terms Doc2 extracted at origination and their observations for the resolved period
-> read the arrears snapshot and the metric window -> retrieve adverse media and let the model
CATEGORISE only the items the feed already confirmed -> **evaluate with the pure engine** ->
build the redacted projection ONCE at the service edge -> write the already-redacted WORM audit
record -> draft and validate the memo from that same masked object, discarding it on any failure
-> compute `required_approvals` (the only place exposure is read) -> **route every consequential
proposal to Hrz7 (R8)** -> return the engine's own assessment to the authenticated credit officer,
who has to act on the covenant text.

The audit actor and the review maker are both the verified `Principal`, never the request body.
Routing happens in the same call that produced the result, on every surface, so an escalation
never depends on a later job that may not exist. Nothing in this pipeline applies a grade.

## The dependency direction

```
credit-memo-drafting (Doc2)  --covenant terms-->  credit-portfolio-early-warning (Doc7)
                                                          |
                                                          +--proposal--> Hrz7 review console
                                                          |
grade registry (system of record)  --read only-->  (no arrow back)
```

This repo READS credit-memo-drafting over a port; credit-memo-drafting never reads this repo. No
arrow points from here into the rating system: the approved grade is applied by the registry's own
maker-checker after the console approves it, outside this service. That gap is an integration a
client owns, and it is stated as such rather than closed by adding a writeback method, because
adding one would remove the property the catalog line rests on.

## The redaction seam

`redacted_assessment` is built ONCE, in `watchlist_service.py`, where the result crosses out of
the service, and the SAME masked object is handed to three sinks: the WORM audit write, the
outbound review payload and the model prompt. Masking at each sink means getting it right three
times, in three files, forever.

| Masked, because it is upstream prose | NOT masked, deliberately |
|---|---|
| the obligor name | every figure (a masked figure is a changed figure) |
| each covenant test's detail, which carries the clause text, and a clause is where a guarantor gets named | every grade and every movement |
| each signal's detail and its evidence locator | every rule id, floor id and review reason |
| every citation SNIPPET | every join key: obligor id, covenant id, period |
| the summary line | every citation LOCATOR (a masked locator is a claim nobody can trace) |

The rule to remember is the pair: **mask the snippet, never the locator**, and a masked payload
must still resolve to its source. `tests/unit/test_watchlist_service.py` asserts both halves, and
asserts first that the planted identifier IS present in the raw assessment, because a vacuous
redaction test is worse than none.

## The port table
| Port | local | gcp | onprem | why the managed family refuses rather than returning empty |
|---|---|---|---|---|
| `AuditSinkPort` | hash-chained SQLite WORM (commons) | Cloud Logging WORM (lazy) | placeholder | an unwritten audit record is an unrecorded decision |
| `IdentityPort` | seeded personas (commons) | IAP assertion (lazy) | placeholder | it decides whether the exposure guard may stand down |
| `ReviewRouterPort` | review-kit outbox (offline, inspectable) | Hrz7 service intake over S2S | placeholder | a router that returned would convert a downgrade proposal into a decision nobody reviewed |
| `ObservabilityTracerPort` | no-op | Cloud Trace or OTLP (lazy) | ABSENT by design | a diagnostic must never be fatal |
| `EvaluationGatePort` | offline scorer, refuses to promote | Hrz4 authority | placeholder | a promotion certified by a laptop is certified by nothing |
| `CovenantTermsPort` | the shared fixture estate, tenant-scoped | Doc2's authenticated read API (lazy OIDC) | placeholder | an empty covenant set is indistinguishable from an obligor with no covenants, and an obligor with no covenants is an obligor nobody is monitoring |
| `PortfolioFeedPort` | the fixture window and arrears snapshots | BigQuery metrics and servicing views (lazy, parameterised) | placeholder | an empty window presents a stressed obligor as a clean one, and a missing snapshot presents an obligor in default as current |
| `AdverseMediaPort` | a small fixture corpus with one UNCONFIRMED item | the Hrz3 knowledge base (lazy) | placeholder | an unconfigured feed and an obligor with no coverage must not look the same. An EMPTY result from a configured feed is a real answer |
| `GradeRegistryPort` | the fixture estate, read only | the managed grade store, read only, viewer role only | placeholder, and it must STAY read-only when rebound | a defaulted grade of record makes every obligor look unchanged and nothing is ever proposed |
| `GenerationPort` | a deterministic offline narrator that drives the REAL validation | the pinned Vertex model at temperature zero (lazy) | placeholder | the memo is drafting, so this refusal costs a paragraph and never a decision |

The on-prem placeholders RAISE. Two of them are load bearing for this vertical: a covenant feed
that returned an empty list would produce a confident affirm on a borrower nobody tested, and a
review router that returned successfully would convert a two-notch downgrade proposal into a
decision nobody reviewed. Silence is the failure mode here, not noise.

A port is registered in FIVE places: `ports/__init__.py` (`PORT_PROTOCOLS`), `config.py`
(`DEFAULT_BINDINGS` and a `Container` accessor), `config/settings.yaml` and
`tests/contract/canonical.py`. `tests/contract/test_port_parity.py` asserts set equality across
all five, so a port that is bound but unregistered (or registered but unbound) fails the build
instead of running with no enforcement. The full touch list is in `CONTRIBUTING.md`.

## Audit integrity
The local WORM log is hash-chained AND anchored: `audit_anchor_path` points at an external file,
on a different volume, that every append writes the chain head to. The chain alone catches an
edit, a deletion or a reorder; only the anchor catches a truncated tail, because a truncated
chain still verifies. `tests/unit/test_audit_anchor.py` proves both halves, including the
control case where the same truncation goes undetected without an anchor.
