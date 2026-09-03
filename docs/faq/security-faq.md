# Security FAQ

For AppSec and security review.

### Who is the actor on a decision, and can a caller assert it?

No. Identity is resolved server-side through `IdentityPort` and a caller-supplied identity is
never accepted. Under the `gcp` profile the IAP-injected assertion is verified at the edge against
a configured audience and IAP's own key set; `local` uses seeded dev personas; `onprem` is a
client IdP placeholder. An unset or emptied `CREDITEWS_IAP_AUDIENCE` refuses every caller rather
than verifying without one, because `verify_token` documents `audience=None` as "the audience is
not verified", which would accept any Google-signed token.

The negative matrix for that verifier lives in `tests/unit/test_iap_crypto_matrix.py`. It mints
its own key, signs its own assertions and runs the REAL verifier over them, so the arguments the
adapter passes are proved to cause rejection rather than assumed to.

### How is tenant isolation enforced?

Through `TenancyPort`, on every read. The obligor listing and the review path both scope to the
resolved tenant, and a cross-tenant obligor id is a refusal rather than an empty result, so
probing cannot distinguish "not yours" from "does not exist" by timing the difference between a
404 and an empty list.

### What happens if the profile variable goes missing in production?

It refuses to start. Configuration is three-state throughout: unset, set-and-empty, and
set-and-valid are distinct, and only the third proceeds. An unset profile is not silently treated
as `local`, and there is no fallback to a managed adapter anywhere in the container wiring.

### Can the service be reached before it is ready?

The bind address is loopback by default. Exposure posture is derived from the identity binding
and is never read from a credential or a flag: a profile whose identity adapter cannot verify an
end user does not get a public bind.

### Where does personal data go?

Redaction precedes the model and the audit stores the redacted text. Concretely: the assessment is
projected through `redacted_assessment` before it is narrated, audited or routed, the prompt is
built from that same masked object (so what the model may see is exactly what it may say back),
and `_record_audit` masks AGAIN before the immutable write. That second mask is deliberate
belt-and-braces: it is the last thing between a future caller that forgot the projection and a
record that cannot be edited.

### Can a model exfiltrate or invent anything?

The model sees only the redacted projection, and its output is validated before use:

- Categorisation must parse as JSON, echo the same `item_id`, and be a member of a closed enum.
  Anything else becomes `UNCLEAR`.
- The memo is checked against a schema, a digit-token grounding oracle built from the same masked
  assessment, and a cited-source check. It is discarded on failure rather than repaired.

So a hallucinated figure changes nothing consequential. The remaining exposure is the input side:
adverse-media headlines and snippets are written by third parties about the obligor and DO reach
the model. Three things bound that today, and all three are load-bearing: the closed output enum,
the `EXTERNAL` family cap, and the rule that an external signal can never floor a grade. The Hrz1
guardrail gateway is **not** bound, so do not widen any of the three before it is.

### How is the audit trail protected?

Audit events go to `AuditSinkPort`, backed by Hrz5's immutable WORM sink in the managed profile
and a locked WORM log bucket in the Terraform stack. The retention lock is irreversible; confirm
`retention_days` before the first apply. Each record reconstructs the decision without the source
systems: the redacted assessment, the applied rules and the citations.

### What about supply chain?

Both lockfiles are fully pinned and `pip-audit` runs over both as a hard gate in `make audit`.
The container base is digest-pinned and runs as non-root uid 10001. There are no GitHub Actions
to pin in this repository: the caller is RENDERED, never hand-written, so nothing here names an
action version. The two actions the fleet actually pins (in the reusable workflow and its
publisher) live in `.github` and are SHA-pinned there. The gate is the hosted GitHub Actions
check.

### What is deliberately out of scope?

- **Login.** This repo owns no authentication flow; auth is configured ON the deployed service.
- **Guardrail screening.** Owned by Hrz1, not bound today.
- **The grading system of record.** No write path exists here by design.
- **Network egress for research.** The adverse-media feed is a port; egress isolation belongs to
  the adapter and the perimeter, not to this domain.
