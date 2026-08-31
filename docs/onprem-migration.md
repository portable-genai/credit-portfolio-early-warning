# On-prem migration (the reversibility proof, P-12)

The `onprem` profile ships fail-fast `NotImplementedError` placeholders for every port, so the
exit path is explicit rather than implied.

The identity placeholder is the one with a serving consequence, so it refuses with a STATUS and a
REASON rather than a bare crash: `OnPremIdentityUnimplementedError` is both a
`NotImplementedError` (the exit family's uniform refusal, which the contract suite and
`scripts/portability_demo.py` assert for every port) and an `EndUserAuthUnavailableError`, so
`POST /v1/watchlist-review` answers 501 with the message below instead of a 500 with no body. Until it is
replaced, no end user can be authenticated at all, and the loopback exposure guard treats the
deployment accordingly: see the exposure section of [runbook.md](runbook.md).

## Steps
1. Set `CREDITEWS_PROFILE=onprem`. A primary path that needs an unbound port
   fails fast with a message pointing here.
2. Implement each port against the client's own stack:
   - `AuditSinkPort` -> the client's append-only WORM store (the commons hash-chained log is a
     drop-in reference; the audit trail exports as JSON Lines and reloads with the chain intact).
   - `IdentityPort` -> the client's OIDC/SAML IdP (verify the assertion server-side; keep
     discarding any client-asserted actor). Set `end_user_auth = VERIFIED` on the new class
     (`ports/identity.py`). That declaration is what tells the exposure guard the end-user routes
     are authenticated, and it is what lifts the loopback bound; an adapter that omits it is read
     as client-asserted, which is the fail-closed default and not a bug in the guard.
   - `ReviewRouterPort` -> the client's own maker-checker queue. Rule R8 does not relax on exit:
     a consequential result must still reach a human, so this placeholder RAISES rather than
     returning quietly. An adapter that dropped the escalation would leave the service
     auto-executing with the appearance of review.
   - `CovenantTermsPort` -> the client's own covenant store, or their own credit-memo-drafting
     deployment. **This is the load-bearing refusal.** An adapter that returned an empty tuple
     instead of raising would be indistinguishable from an obligor with no covenants, and an
     obligor with no covenants is an obligor nobody is monitoring: the engine would produce a
     confident AFFIRM on a borrower nobody tested.
   - `PortfolioFeedPort` -> the client's own spreading system and transaction warehouse. Return
     the arrears figures as ONE snapshot: the materiality legs compare figures that must come from
     the same snapshot at the same date, and a fresh arrears amount tested against a stale
     exposure makes the gate silently mean nothing. Convert money to MINOR UNITS at the boundary.
   - `AdverseMediaPort` -> the client's own adverse-media or screening feed. Two rules travel with
     it: `relevance` is the FEED's assertion and is never inferred in this repo, and an item with
     no resolvable locator is DROPPED rather than carried, because an item that cannot be cited
     cannot be scored.
   - `GradeRegistryPort` -> the client's grading system of record, **READ ONLY**. The seam must
     keep its shape when rebound: an on-premises adapter that gained a write method would defeat
     the control the whole vertical rests on, which is that this service proposes a grade and has
     no method that could apply one. `tests/unit/test_registry_is_read_only.py` scans every bound
     adapter in every profile, so a write verb added here fails the offline gate.
   - `GenerationPort` -> the client's own model endpoint. This is the one seam whose absence costs
     a paragraph rather than a decision: with no model bound, the assessment, the grade proposal
     and the routed escalation are all complete, and `memo_discarded_reason` names the unbound
     seam on the response.
3. Bind the new adapters under `onprem` in `config/settings.yaml` (and in
   `config.DEFAULT_BINDINGS`, which the settings test holds equal to it) and run the gate.

No domain code changes: that is the point of the hexagon.
