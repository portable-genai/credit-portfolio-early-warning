# AGENTS.md

The working agreement for any coding agent in this repository, in the portable `AGENTS.md`
format that agent tools read. It is the only such file here, so there is no second copy to
keep in step.

## What this is

Credit Portfolio Early Warning (`credit-portfolio-early-warning`): post-origination monitoring of the lending book. Covenant
compliance is tested against the terms credit-memo-drafting (`credit-memo-drafting`) extracts at origination,
early-warning signals are fused from financial spreads, transaction patterns and adverse news by a
deterministic scoring engine, and cited watchlist-grading proposals and review memos are drafted
for the credit officer. It NEVER re-grades an obligor: the grade registry port declares read
methods only.

Rendered from `hex-service-template`, so it starts at reference parity rather than converging
toward it. Package `credit_portfolio_ews`, environment prefix
`CREDITEWS`, region `asia-southeast1`.

## Documentation authority order

On any conflict, the earlier document wins: `SPEC.md` > `ARCHITECTURE.md` > `COMPLIANCE.md` >
`README.md`. `docs/runbook.md` and `docs/onprem-migration.md` are operational and never restate
product behaviour. `docs/practices-audit.md` records the per-check verdict against the common
base practices, and it is the file to update when a gap closes.

## The hard gate

```sh
make install   # locked install from requirements-dev.lock, then the project with --no-deps
make gate      # ruff check + ruff format --check + mypy src + pytest -m 'not integration' + eval
make audit     # pip-audit over both lockfiles (needs network; CI runs the same two commands)
```

`make gate` is deliberately OFFLINE and credential-free: no cloud SDK, no project, no network. If
a change makes the gate need any of those, the change is wrong, not the gate. `make audit` is the
one step that needs a vulnerability feed, which is why it is separate locally and a hard-failing
job in CI rather than an advisory one.

After any dependency change, run `make lock` and commit both lockfiles. An uncommitted resolution
is a version set nobody reviewed.

## Architecture

Hexagonal, ports and adapters:

- `src/credit_portfolio_ews/domain/` is PURE stdlib. No web framework, no cloud SDK,
  no HTTP. `kernel.py` holds the vertical-neutral machinery and is untouched by this vertical.
  The vertical's own modules are:
  - `models.py` : the artifacts. The covenant vocabulary consumed verbatim from `credit-memo-drafting`, the
    supervisory grade ladder with its rank map, the evidence records and the result types.
  - `policy.py` : the frozen `EarlyWarningPolicy`, `SignalRule`, the shipped rule set and
    `validate_policy`, loaded from the `policy:` block of `config/settings.yaml`.
  - `early_warning.py` : the PURE engine. No clock, no I/O, no model, no settings object.
  - `watchlist_service.py` : the orchestration. It only talks to ports, and it owns the ONE
    redaction seam and the one place the exposure figure is read.
  - `narration.py` : the model boundary. `build_prompt`, `validate_memo`, the grounding oracle.
  - `errors.py` : `UngroundedSignalError`, `ObligorNotFoundError`.
  - `pii.py` : the jurisdiction pattern selection and order.

  The decision path and the drafting path are separated by the IMPORT GRAPH: `early_warning.py`
  does not import `narration.py`, and `narration.py` imports no port.
- `ports/` holds `@runtime_checkable` Protocols, re-exported once from `ports/__init__.py` with
  the `PORT_PROTOCOLS` map. By name: `audit`, `identity`, `review_router`, `tracer`, `evaluation`
  (vertical-neutral, from the template) and `covenant_terms`, `portfolio_feed`, `adverse_media`,
  `grade_registry`, `generation` (this vertical's, each naming a different system of record).
  `ports/identity.py` carries what an identity adapter declares about the end-user authentication
  it provides, and the refusal type that carries a status and a reason; `ports/tenancy.py` carries
  the one cross-tenant refusal every read port shares.
- `adapters/{local,gcp,onprem}/` are the three families. `local` is SDK-free and actually works;
  `gcp` imports its SDK LAZILY inside the method, so the other two profiles import it with no
  cloud SDK installed; `onprem` is a placeholder that RAISES rather than pretending.
- `config.py` resolves the profile and binds every port. `config/settings.yaml` carries the
  binding table, so switching a port is configuration, not a code edit.
- `agent/` is the optional-but-scaffolded agent surface: plain tool callables plus the A2A card.
  It imports with no ADK and no cloud SDK; `build_function_tools()` is the only runtime seam.
- `tests/` splits into `unit/`, `contract/`, `integration/` and `fixtures/`. Integration modules
  are marked so `pytest -m 'not integration'` deselects them, and a test dropped into `tests/`
  root fails `tests/unit/test_test_layout.py`.
- `scripts/` is the demo surface (see `scripts/README.md`): the scripted arc, a static renderer,
  a live click-through server, the presenter walkthrough that doubles as the self-test, the
  executable portability claim and the offline documentation checker. It is importable from the
  suite (`pythonpath = ["scripts"]`) and excluded from the serving image.
- `ui/` is the embeddable micro-frontend. One policy module and one server-side identity module
  are its whole security boundary. Run `make drop-ui` if this repo has no user-facing surface.
- `infra/terraform/` is the vertical-neutral deploy posture, not a skeleton: residency validated
  at plan time, Org Policy guardrails, a regional CMEK key ring, a least-privilege serving
  identity, a locked WORM log bucket and sink, the five security metrics and alerts, a
  dry-run-first VPC-SC perimeter, and the opt-in Cloud Run serving edge behind IAP and Cloud
  Armor. `render.tf.json` is the ONE file cookiecutter rendered; every `.tf` and `.tftest.hcl`
  beside it was copied verbatim, because Terraform interpolation and Jinja fight over braces.
  The render-time constants therefore arrive as JSON locals (`render_region`,
  `render_package_name`, `render_env_prefix`, `render_catalog_id`) and `naming.tf` derives
  everything else from them. `make tf-check` runs the whole offline check; the vertical's own
  resources (a store, a warehouse, a bucket) are yours to add, in four places at once.

## Invariants (a change that breaks one of these is a defect, not a trade-off)

- **Born fail-closed.** `add_loopback_exposure_guard` is bound at MODULE scope in `api/app.py`,
  because the Dockerfile `CMD` and `make run-api` serve the app OBJECT: a bound that lives only
  in `main()` never runs in a shipped process. `tests/unit/test_serving_path_exposure.py` is the
  standing gate.
- **The exposure guard is derived from the IDENTITY BINDING, and from nothing else.** An end-user
  route is authenticated when the bound identity adapter can produce a verified principal without
  trusting a header the client wrote, and the adapter DECLARES that (`ports/identity.py`:
  `VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED`, defaulting to client-asserted when silent).
  `CREDITEWS_S2S_TOKEN` may never enter that decision: it authenticates a
  calling SERVICE and no end user, and while it did, SETTING it switched the guard off for the
  end-user routes it was protecting and a LAN peer with no credential got the seeded approver
  persona and a real grade proposal. `tests/unit/test_end_user_auth_posture.py` walks the
  guard's argument through the constants it names and fails the build if a credential reappears
  at any depth; `scripts/prove-exposure-matrix.sh` in the template drives the whole matrix over a
  real socket.
- **The one adapter that declares `VERIFIED` must EARN it, and it is the one adapter that may not
  go untested.** `adapters/gcp/identity.py` calls `id_token.verify_token` with `audience=` (the
  configured `CREDITEWS_IAP_AUDIENCE`, three-state: unset or emptied REFUSES,
  because `audience=None` means the audience is NOT verified and accepts any Google-signed token
  from any project) and `certs_url=` (IAP's own key set, not google-auth's OAuth2 default), checks
  the issuer itself (`verify_token` does not), and WRAPS both the verifier call and the lazy
  import so no caller-supplied header can become a 500. `MalformedError` is a `ValueError`, not an
  `IdentityError`. Caller faults are 401 with the reason kept in the log; deployment faults (no
  audience, no verifier installed) are 503 naming the fix. `tests/unit/test_iap_identity.py` runs
  in every `make gate`; `tests/unit/test_iap_crypto_matrix.py` runs the REAL verifier over
  locally minted assertions and is required by the `iap-verifier` CI job and by the template's
  render gate, which fail if it skips. There is no `# pragma: no cover` on this adapter.
- **Interactive docs are a relaxation, not a constant.** `/docs`, `/redoc` and `/openapi.json` are
  registered only when `exposure_profile` is the deliberate `local`. Under `gcp` the loopback
  guard has stood down and the process binds every interface, so an uncredentialed peer was
  receiving the whole route inventory and every schema; the routes are ABSENT there rather than
  guarded, because a guard the profile has switched off is no guard.
- **One profile read, three states, refused at import.** `config.PROFILE_CHOICE` resolves once at
  import into a `ProfileChoice`. UNSET is NO CHOICE, not a silent `local`; SET-AND-EMPTY raises so
  it cannot inherit the unset behaviour; SET-AND-UNKNOWN raises. Both raises kill the process
  before it can serve a request. Only `config.py` may read
  `CREDITEWS_PROFILE` (mentioning it in a refusal message is wanted, reading
  it is the defect); `tests/unit/test_profile_single_source.py` fails the build if any other
  module re-derives it, because a permissive default gets reintroduced one module at a time.
- **Two derived postures, never one string.** Relaxations (CORS, the `X-Dev-Persona` allowed
  header, HSTS, the S2S scheme) key off `ProfileChoice.exposure_profile`, which is `unconfigured`
  when nobody chose. The loopback bound keys off `ProfileChoice.bind_profile`, which is `local`
  when nobody chose. They fail closed in OPPOSITE directions, so a single effective-profile
  string would harden one and weaken the other. The seeded-persona adapter refuses to construct
  unless `local` was chosen deliberately.
- **The audit trail is anchored, not just chained.** `audit_anchor_path` writes the chain head to
  a file on another volume. The chain catches an edit, a deletion or a reorder; only the anchor
  catches a truncated tail. `tests/unit/test_audit_anchor.py` proves both, including the control
  case that fails without it.
- **Three-state environment reads, everywhere, enforced, in BOTH languages.** UNSET,
  SET-AND-EMPTY and SET-AND-VALID are three states, not two. A variable an operator deliberately
  emptied must never inherit the unset default. In Python use
  `hex_service_kit.netdefaults.read_env_setting`; `tests/unit/test_three_state_env_reads.py`
  walks the AST of `src/`, `scripts/` and `eval/` and fails the build on any two-state
  `os.environ.get` / `os.getenv` read that is neither an exact-match comparison against a literal
  nor listed with a written reason. In `ui/` use `readEnvSetting` from `ui/lib/env-setting.mjs`;
  `ui/tests/three-state-env-reads.test.mjs` scans every shipped `.mjs` / `.ts` / `.tsx` with the
  same rule and the same two escapes. Both halves are needed: a guard that only watched the
  PROFILE variable is how a two-state read of a different one stayed invisible, and a guard that
  only parsed Python is how `env.UI_TENANT_ORIGINS || "*"` survived the entire gate.
- **Every unit of work opens a span, and no span carries content.** `WatchlistReviewService.review`
  wraps its work in `self._tracer.span(...)` with STRUCTURAL attributes only: the action and the
  actor, never an obligor name or a covenant clause. A span is not a redacted sink. Tracing is the one seam that is
  ABSENT rather than fatal on-prem, and the one managed adapter that must not refuse offline:
  it is a diagnostic, not a control, and an exporter fault must never become a request fault.
  `demo.EXIT_ABSENT` records that exemption and the portability tour asserts it in both
  directions, so a tracer that starts raising fails the tour. The no-content half is a TEST, not
  a convention: `tests/unit/test_span_content.py` holds the attribute keys to a fixed allowlist
  and asserts the planted identifier never appears in a value. Widening that set is a decision
  about what leaves the trust boundary, and it is made in that file rather than at a call site,
  because the pressure to add "just the case text" comes from someone debugging a real incident
  and sounds entirely reasonable at the time.
- **Logs are diagnosis; the audit trail is evidence. Do not confuse them.** `configure_logging`
  is called at MODULE scope in `api/app.py` (the Dockerfile CMD serves the app object) and at the
  top of the CLI. A deployed profile emits JSON with Cloud Logging's own field names and the
  active trace id; `local` and `onprem` stay plain text. The formatter emits an ALLOWLIST and
  never the record's `__dict__`: logs are not WORM and nothing redacts them downstream, so
  `logger.info("...", extra={"prompt": prompt})` must not be able to put a model prompt in a log
  sink. Add a key to the allowlist deliberately, in the commons, with a reviewer.
- **The core's purity is a test, not a convention, and it is proved twice.**
  `tests/unit/test_core_purity.py` walks the AST of `domain/` and `ports/` and fails the build on
  any import outside the standard library, this package and the workspace kits. It is an
  ALLOWLIST rather than a list of banned SDK names, because a blocklist rots the day a vendor
  renames a distribution. The dynamic half is
  `tests/contract/test_port_parity.py::test_every_profile_constructs_with_no_cloud_sdk_importable`,
  which constructs every profile in a fresh interpreter where the managed SDKs cannot be
  imported. Both are needed: the probe cannot see a lazy import inside a function body on a call
  path that construction never reaches, and the static scan cannot see an adapter that fails to
  build. An import that must stay gets a NAMED row in `EXEMPT_IMPORTS` with a written reason, so
  it is debt somebody owns rather than a silently widened rule, and a stale row fails rather than
  quietly covering the next violation.
- **Redact before anything leaves.** PII is masked before the audit write, before any outbound
  payload and before the model prompt. The raw identifier never reaches a WORM record, the review
  console or a prompt. Two rules make that a control rather than an intention:
  - **Assert against the SINK, never against a rebuild of what should have reached it.** A check
    that calls `build_prompt(redacted_assessment(...))` itself tests the masker and observes
    nothing the service did, which is how a one-token change to `_draft_memo` sent a guarantor's
    national id to the model with the gate, the eval, the demo self-test and the portability tour
    all green. Capture the prompt through a wrapped `GenerationPort`
    (`adapters/local/generation.RecordingNarrator`, which the unit suite and the demo both bind),
    and read the WHOLE audit record rather than one field of it, because the leak that hid there
    was in `citations[].snippet` and every oracle was pointed at `redacted_summary`.
  - **A sink that cannot be corrected afterwards masks again from its own side.** The outbound
    payload does it in `adapters/_review_payload.py` and the WORM write does it in
    `_record_audit`, for both content fields. The projection at the service edge is still the
    control; this is the belt and braces that makes a single mistake survivable, and it is why a
    mutation of the seam ALONE is expected to stay green there.
- **The VERTICAL invariants. Break one of these and the catalog line stops being true.**
  - **The grade registry declares NO write method, in any profile.** That is the enforcement of
    "never re-grades an obligor autonomously": a method that does not exist, not a boolean
    somebody could flip. `tests/unit/test_registry_is_read_only.py` checks the Protocol's method
    set AND scans every bound adapter for a write verb; `make portability` and
    `make demo-selftest` fail on the same mutation from two other entry points. An on-premises
    adapter that gained a write method would defeat the control the whole vertical rests on.
  - **The arrears materiality gate runs FIRST**, before every past-due rule and every past-due
    floor, and every one of them reads `effective_days_past_due` and never the raw figure. Delete
    the gate and the engine classifies an obligor substandard on a 640.00 arrear;
    `obl-kappa-010` in the golden set exists to make that failure loud.
  - **Every row of the `policy:` block is READ by something, and an incomplete block is refused
    at LOAD.** An inert knob beside a live one is worse than an absent one: it reads as a control
    in an audit, and retuning it changes nothing and warns nobody. `confirmable_categories` and
    the unread `arrears_weights.severe` row were both that, one deleted and one wired to the
    third past-due tier it was always priced for. A mapping named in the block REPLACES the
    shipped one rather than merging, so `validate_policy` requires it to price every row the
    engine indexes: an unpriced family cap reads as zero and silently stops the score-driven half
    of the engine, and an unpriced floor, status or tier raises at first request.
  - **A covenant with no closed-period observation is `not_evidenced` and is never counted
    compliant.** `not_due` is a DIFFERENT state: a mid-period sweep must not read as a file nobody
    evidenced, and a file nobody evidenced must not read as one that passed.
  - **A waiver suppresses the FLOOR and never the SIGNAL**, and a waiver expired at `as_of` is not
    a waiver: the status stays breach and the rule id says why.
  - **Only a FEED-confirmed news item can fire an external rule**, and no external or process
    signal ever sets a floor, in any configuration. `validate_policy` refuses at LOAD any cap that
    would let either family reach the first adverse band alone; `obl-lambda-011` exists to make
    that failure loud.
  - **The engine module never reads the exposure figure.** Exposure sets the approval path and
    nothing else, because a grade that moved with facility size would be gameable by splitting
    facilities. `tests/unit/test_engine_never_reads_exposure.py` greps the module.
  - **LOSS is readable and unproposable.** The registry holds it; the ceiling caps every proposal
    at DOUBTFUL and records itself.
  - **An upgrade needs POSITIVE evidence, not the absence of signals.** A thin file must never be
    able to propose an improvement.
  - **Policy numbers are configuration.** Every number the engine compares against is in the
    `policy:` block, and `tests/unit/test_policy.py` holds the shipped block equal to the shipped
    code defaults. A number that appears only in `early_warning.py` is a defect.
- **Rule R8: escalations are ROUTED, never merely flagged.** Setting `requires_human_review` and
  calling `ReviewRouterPort.route` is one act. `api/app.py`, `cli/main.py` and `agent/tools.py`
  all route in the same call that produced the result. `tests/unit/test_review_routing.py` is the
  standing gate; a local router that silently did nothing would let a producer ship R8 unwired
  and green.
- **The consequential decision is deterministic.** The composite, the band, every floor and the
  escalation come from pure stdlib integer arithmetic over an explicit `as_of`, and are
  replayable. An LLM may narrate the result and categorise one already-confirmed media item; it
  may never produce a grade, a movement, a floor, a score, a weight, a threshold or a boolean.
- **Every result carries a citation.** A claim with no provenance is not shippable.
- **The demo is code, and every narrated claim is checked.** A step lives in `demo.STEPS` and in
  `walkthrough.CHECKS`, and `tests/unit/test_demo_surface.py` holds the two equal, so a claim the
  demo makes but nobody verifies cannot exist. `make demo-selftest` runs the whole arc headless
  in CI. Do NOT move the demo into `make gate`: the gate proves the service and must stay fast
  and offline, and the demo has its own required check.
- **The browser never asserts who it is.** In `ui/`, every client-supplied actor, tenant, role,
  ACL and authorization header is discarded before forwarding, identity is resolved server-side,
  and the service credential stays on the server. Framing and CORS are allowlists that refuse a
  wildcard, and every variable behind them is read in three states: unset takes the documented
  restrictive default, EMPTIED refuses. `UI_PROFILE` refuses rather than seeding a dev persona
  when nobody chose; `UI_FRAME_ANCESTORS` and `UI_TENANT_ORIGINS` refuse from `next.config.mjs`,
  so the refusal is a build/boot refusal rather than a surprise on a later request. The one
  deliberate exception is the OUTBOUND `AGENT_S2S_TOKEN`, exempted with a written reason because
  the receiver decides whether an uncredentialed call is acceptable.
- **The console must actually HYDRATE, and only one check can tell you.** The document CSP is
  nonce-based (`script-src 'self' 'nonce-<n>' 'strict-dynamic'`), `proxy.ts` puts that policy
  on the REQUEST `Content-Security-Policy` header because that is the only name Next reads a
  nonce from, and `app/layout.tsx` sets `force-dynamic` because Next can only stamp a nonce
  onto a dynamically rendered route. All three are required: a bare `script-src 'self'` blocks
  Next's inline hydration bootstrap so React never attaches, and a nonce on a prerendered
  route is worse still, since `'strict-dynamic'` then also blocks the chunk scripts. Correct
  headers, a clean `tsc`, green policy tests, a successful build and a good screenshot are all
  consistent with a page that never hydrates, so the gate is `npm run assert-hydratable`,
  which serves the built app and asserts every script tag carries the served nonce.
  `assertHydratableCsp` refuses the half-configured build outright.
- **`ui/`, its dependabot ecosystem and its CI job agree, in both directions.** Present together
  or absent together. `make drop-ui` is the one step that keeps them consistent, and
  `tests/unit/test_ui_surface.py` fails the gate until they do.
- **The deploy posture is CHECKED offline, and the refusals live in the tests, not in the
  comments.** `make tf-check` and the `terraform` CI job run `init -backend=false`, `validate`,
  `fmt -check -recursive` and `test`, with no backend, no project and no credentials;
  `infra/terraform/production_edge.tftest.hcl` uses `mock_provider` and plan-only runs. Fourteen
  runs carry the claims: residency defaults in country, the perimeter starting in dry run, the
  edge absent by default, the served edge's contract, and nine refusals (an out-of-allowlist
  region, retention below the six-month floor, a reduced locked retention, a perimeter with no
  access policy, a mutable image tag, an edge with no review console, an edge with no alert
  channel, an audience with no IAP, and a reserved or moving secret). A residency claim that
  lives only in a comment is a claim nobody checks.
- **The audit log name agrees BY CONSTRUCTION, and a test holds the derivation.**
  `adapters/gcp/audit.py` writes to the logger `credit_portfolio_ews-audit` and
  `naming.tf` derives `local.audit_log_name` from `local.render_package_name`, which is the same
  cookiecutter variable. A WORM sink filter naming a log nobody writes routes an EMPTY stream and
  looks exactly like a working sink, so the tftest asserts both the derivation and that the
  sink's filter contains it. Do not re-pin either half by hand.
- **The region is injected once, and only once.** `render.tf.json` carries it; `variables.tf`
  keeps `region` and `allowed_regions` nullable and `naming.tf` makes them effective, so an
  operator overrides in `terraform.tfvars` and the single cross-variable validation holds the
  pair consistent. That validation lives on `var.region` alone and reads
  `coalesce(var.region, local.render_region)` rather than `local.region`: two validations that
  read each other's variable is a dependency cycle Terraform refuses to build, and
  `terraform validate` then fails before it checks anything at all.
- **VPC-SC starts in DRY RUN.** `use_explicit_dry_run_spec = !var.vpc_sc_enforce`, so the first
  apply audits rather than enforces. Watch the `vpc_sc_denials` alert for a full business cycle,
  add the operator identities, and only then enforce. Never enforce blind on a path nobody has
  watched.

## Extending

`CONTRIBUTING.md` carries the file-by-file touch list for both walkthroughs, with the test that
enforces each row. The short version:

- **A new adapter:** the class under `adapters/<family>/` (one constructor shape,
  `Adapter(settings)`, cloud imports inside the method), the same `module:Class` target in
  `config.DEFAULT_BINDINGS` AND `config/settings.yaml` (`tests/unit/test_settings_file.py` fails
  if the two disagree), plus any new variable in `.env.example`.
- **A new port:** it must be registered in FIVE places, or it runs with no enforcement at all:
  `ports/__init__.py` (`PORT_PROTOCOLS`), `config.DEFAULT_BINDINGS`, a `Container` accessor,
  `config/settings.yaml`, and a `PortCase` in `tests/contract/canonical.py`. Then bind it in all
  three families. `tests/contract/test_port_parity.py` asserts set equality across the five.
- **A new surface:** whatever it is, it routes escalations (R8), it minimises what it hands a
  model, and it ACCEPTS no identity: no actor, no tenant, no entitlement on a request schema, and
  none on a tool signature either, because a runtime derives the tool's JSON parameter schema
  from the signature. `tests/unit/test_api.py` pins the field set for the route and
  `tests/unit/test_agent_surface.py` pins the parameter set for every tool. An agent tool also
  needs its skill in `agent/agent_card.py`; the card and the tool table are compared for set
  equality.
- **A new demo step:** the `Step` and its `_step_<key>` method in `scripts/demo.py`, plus the
  matching entry in `walkthrough.CHECKS`. Put the numbers the check reads in the step's `facts`
  dict, never only in the rendered rows: a check that parses prose breaks on a wording change.
- **Synthetic data only.** Fixtures, demos and docs use obviously fictional parties and
  `.example` domains. No real customer, counterparty or identifier, ever.
