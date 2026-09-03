# Credit Portfolio Early Warning (Doc7)

Post-origination monitoring of the lending book. Covenant compliance is tested against the terms
[credit-memo-drafting](https://github.com/portable-genai/credit-memo-drafting) extracts at
origination; early-warning signals are fused from financial spreads, transaction patterns and
adverse news by a deterministic scoring engine; and cited watchlist-grading proposals and review
memos are drafted for the credit officer. It never re-grades an obligor autonomously.

The boundary against credit-memo-drafting (catalog id Doc2) is the one to state first: **Doc2
extracts covenants at origination, and this repo tests them afterwards.** The covenant vocabulary
is consumed verbatim over a port, so origination and monitoring cannot disagree about the same
covenant, and no arrow points the other way.

The honest bound, stated plainly: **this service proposes a grade and never applies one, and it
does not decide impairment or provisioning.** The grade registry port declares read methods only,
so there is no write path to the grading system of record in any profile. The engine flags the
IFRS 9 thirty-day and ninety-day presumptions as presumptions; it proposes no impairment stage and
books no allowance, because the standard's primary test needs a probability-of-default model this
repo does not have.

A hexagonal ports-and-adapters build scaffolded from the catalog commons. The consequential
decision is pure, deterministic stdlib; PII is redacted once, where a result leaves the service,
before it is audited, sent or shown to a model; every claim carries a citation; and a consequential
proposal is ROUTED to a human reviewer (rule R8) rather than auto-executed or left in a flag
nobody reads.

## Surfaces

| Route | What it does |
|---|---|
| `POST /v1/watchlist-review` | Review one obligor for one reporting period and PROPOSE a watchlist grade, with every applied floor rule named, every figure cited, and `grade_applied` typed on the response as false. |
| `GET /v1/obligors` | The READ-ONLY obligor listing the console's picker is populated from. There is no write counterpart, on this surface or on any other. |

## Commands

```bash
python3.12 -m venv .venv && source .venv/bin/activate
make install          # locked install from requirements-dev.lock, then the project --no-deps
make gate             # the full offline gate: lint + type + test + eval
make audit            # pip-audit over both lockfiles (needs network; a HARD gate in CI)
make lock             # recompile both lockfiles after a dependency change
make test-integration # tests/integration only; needs a live project (the gate deselects it)
make run-api          # uvicorn (loopback for the no-auth local profile)
credit_portfolio_ews review obl-delta-004 --as-of 2026-06-30
```

The offline gate is SDK-free and is what CI runs (via the shared reusable hard-gate workflow):

```bash
ruff check src tests && ruff format --check src tests && mypy src && \
  pytest -m 'not integration' && python eval/run_eval.py
```

The demo surface sits OUTSIDE that gate, because the gate proves the service and the demo proves
the story it is presented with. It is enforced inside the offline gate by
`tests/unit/test_demo_surface.py`, which the hosted GitHub Actions check runs, so it cannot rot
quietly:

```bash
make demo             # the presenter-paced walkthrough (see DEMO.md)
make demo-selftest    # the same walkthrough, headless and unattended, asserting every step
make demo-static      # static audit-first HTML for screenshots
make portability      # the executable portability claim, pass or fail per named check
make docs-check       # relative links resolve, fences close, no em-dash in shipped prose
make ui-install ui-check   # the micro-frontend: tsc, node tests, production build, npm audit
```

## Profiles

One env var, `CREDITEWS_PROFILE`, selects the adapter family:

- `local` (default) : SDK-free offline stack (seeded dev personas, hash-chained SQLite WORM audit
  from the commons). No cloud SDK. The default for dev/test/CI.
- `gcp` : managed cloud (Cloud Logging WORM, IAP identity). SDK imports are lazy.
- `onprem` : fail-fast `NotImplementedError` placeholders (the reversibility proof, P-12).

Unset means `local` adapters bind but nobody chose them. A value that is set but unknown, `Local`
and `GCP` included, raises at import: a typo must not silently pick a family. And because the
local profile's seeded personas authenticate nobody, the loopback exposure guard is registered on
the app object itself, so serving it off loopback returns 503 unless
`CREDITEWS_ALLOW_INSECURE_DEMO=1` says otherwise. The guard reads the identity
BINDING to decide that, never a service credential: setting
`CREDITEWS_S2S_TOKEN` closes the S2S routes and does not open anything else.
See `docs/runbook.md`.

## What comes from the commons

| Package | Used for |
|---|---|
| `hex-service-kit` | `Principal` / `IdentityPort` / seeded personas, fail-closed bind + CORS, `make_require_service_caller` / the app-object exposure guard / security headers (the end-user dependency is this repo's own, so a deployment that can authenticate nobody answers with a status and a reason rather than a blanket 401), the hash-chained WORM audit log, `StrEnum` taxonomies |
| `agent-eval-kit` | the `--mode smoke\|gate` scaffold, the Hrz4 gate client, the not-falsely-green harness |
| `pii-kit` | the jurisdiction PII pattern pack the redaction seam masks with |
| `review-kit` | the rule R8 producer path: the review payload, the submission client and the outbox |

## Surfaces

The same capability is reachable five ways, and they behave the same because they share the
domain service rather than reimplementing it: the FastAPI app (`api/`), the argparse CLI
(`cli/`), the agent tools (`agent/`, advertised on the A2A card at
`/.well-known/agent-card.json`), the embeddable micro-frontend (`ui/`) and the eval harness.
Each of them routes a consequential proposal to human review in the same call that produced it, so
rule R8 does not hold on four surfaces out of five.

## The ports, by name

`audit`, `identity`, `review_router`, `tracer` and `evaluation` come from the template and are
vertical-neutral. This vertical adds five, each naming a genuinely different system of record:

| Port | What it reads, and what it refuses |
|---|---|
| `covenant_terms` | The covenant terms credit-memo-drafting extracted at origination, and their observations for the tested period. An unconfigured managed adapter RAISES rather than returning an empty covenant set, because an obligor with no covenants is an obligor nobody is monitoring. |
| `portfolio_feed` | The normalised metric window from the spreading system, and the arrears snapshot as ONE record, because the materiality legs compare figures that must come from the same snapshot at the same date. |
| `adverse_media` | Retrieved external items that already carry their locator. Whether an item is about THIS obligor is the feed's assertion and is never inferred here. |
| `grade_registry` | The grade of record. READ ONLY: the Protocol declares two reads and no write, which is how "never re-grades an obligor autonomously" is enforced. |
| `generation` | The narration seam. It drafts the review memo and categorises a confirmed media item from a closed enum. It never produces a grade, a movement, a floor, a score or a threshold. |

`ui/` is a Next.js micro-frontend that runs standalone or embeds in a client application. Its
security value is that the browser never asserts who the user is: every client-supplied actor,
tenant, role and authorization header is discarded, identity is resolved server-side, the
service credential never leaves the server, and framing and CORS are per-tenant allowlists that
refuse a wildcard. **If this repo has no user-facing surface, run `make drop-ui`** rather than
leaving it half-wired; `tests/unit/test_ui_surface.py` holds the repo consistent in both
directions. See `ui/README.md`.

The tool results are masked for personal data before they return, which the API response is not:
a tool result becomes a model's context, and P-04 is about what reaches the model.

## Configuration

`config/settings.yaml` holds the per-port adapter map plus non-secret defaults, and it is the only
place a binding lives. `.env.example` documents every non-secret variable;
`.env.secrets.example` documents the secret NAMES with placeholder values. Every security-relevant
read resolves three states: unset, set-and-empty and set-and-valid are different, and a value an
operator deliberately emptied never inherits the more permissive unset default.
`tests/unit/test_three_state_env_reads.py` fails the build on any two-state read that ships, so
the rule is enforced rather than remembered.

**Name the profile.** `CREDITEWS_PROFILE` has no default. Leaving it unset is
its own state: the offline adapters still bind, but the seeded dev personas are refused, no
service-to-service scheme is selected, the dev CORS allowlist and the `X-Dev-Persona` header are
withdrawn, and the exposure guard refuses every route to any non-loopback peer. A deployment that
loses the variable fails visibly instead of serving a stranger.

Deepest authority on intent, in order: `SPEC.md` -> `ARCHITECTURE.md` -> `COMPLIANCE.md` -> this
file. `docs/practices-audit.md` records the per-check verdict. Region pinned to
`asia-southeast1`.

## License

Apache-2.0. Synthetic, obviously fictional data only.
