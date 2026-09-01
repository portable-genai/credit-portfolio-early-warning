# Portability FAQ

For architecture, cloud and exit planning.

### What is the lock-in surface?

The `src/credit_portfolio_ews/adapters/gcp/` directory, and nothing else. The domain imports only
the standard library and the owned kits; every outbound dependency crosses a Protocol in `ports/`;
and one settings file maps each port to an adapter family. A purity check in the gate scans the
`domain/` and `ports/` trees and fails on any cloud import, so this is enforced rather than
described.

### What are the three profiles?

| Profile | For | Adapters |
|---|---|---|
| `local` | laptops, CI, demos | fixture portfolio feed, fixture covenant terms, fixture adverse media, deterministic narration stub, in-process audit and tracer. No SDK, no network, no credentials. |
| `gcp` | the managed deployment | BigQuery-backed feed, A2A client to Doc2 for covenant terms, managed adverse-media feed, the pinned Vertex model for narration, Hrz5 for audit and traces. |
| `onprem` | a client-hosted install | fail-fast placeholders naming the client system to bind. |

Selection is one variable, `CREDITEWS_PROFILE`, and it is three-state: unset, set-and-empty and
set-and-valid are distinct, and there is no silent fallback to a managed adapter.

### Is the portability claim tested, or just documented?

Tested. `make portability` runs named checks and exits non-zero on any failure, and the contract
tests in `tests/contract/` run the same behavioural suite against every bound adapter family, so a
profile cannot quietly answer a different shape. The purity scan is part of the offline gate.

### The managed adapters raise. Does that not break the portability claim?

It is the opposite. A managed adapter that is not finished raises `NotImplementedError` rather
than degrading to a local one, so an incomplete managed profile fails loudly at the boundary
instead of serving a laptop fixture to production and looking healthy. What is unfinished is
declared rather than discovered.

### Can it run with no model at all?

Yes, and that is the deterministic-only mode. Bind the `local` narration stub and every
consequential field is byte-identical run to run: the covenant tests, the score, the floors, the
grade proposal, the approvals and the routing are all pure stdlib. What you lose is the memo
prose and the media-category refinement, neither of which can change a grade.

That is also, today, the kill switch. It is a binding change rather than an operator action; the
model card lists making it an operator action as an open control.

### How do we actually exit?

1. Set `CREDITEWS_PROFILE=onprem` and implement the placeholder adapters against your own systems.
   The Protocols in `ports/` are the whole contract.
2. Export the data. The obligor and review records are yours; the audit stream is an append-only
   sequence of JSON records with no managed-service-specific fields.
3. Drop `adapters/gcp/` and the `infra/terraform/` stack. Nothing in `domain/` references either.

### What has to be replaced on the way out, specifically?

The ports, one by one: `PortfolioFeedPort` (obligor metrics and servicing data), `CovenantTermsPort`
(the origination covenant record, from Doc2 or your own), `AdverseMediaPort`, `GradeRegistryPort`
(read-only), `GenerationPort` (optional, see above), `IdentityPort`, `TenancyPort`,
`AuditSinkPort`, `ObservabilityTracerPort` and `ReviewRouterPort`.

### Is the data residency claim portable too?

The region is chosen once and shared across `config/settings.yaml`, `infra/terraform/render.tf.json`
and the Terraform `region` / `allowed_regions` pair, and the Terraform tests refuse a region
outside the allowlist at plan time. On the way out, residency becomes your hosting decision; the
code carries no region literal outside those three places.
