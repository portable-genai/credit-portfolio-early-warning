"""Tool functions an agent runtime calls: thin, side-effect-honest wrappers on the services.

Design rules, in the order they matter:

* **No business logic here.** The domain service decides HOW; the model only decides WHICH tool
  to call. A rule that lives in a tool wrapper is a rule the CLI and the API do not have.
* **Rule R8 applies on this path too.** An escalated result is ROUTED from inside the tool, in
  the same call that produced it. An agent surface that only returned the flag would be a third
  place an escalation can quietly stop, after the API and the CLI.
* **Import-safe without a runtime.** ``google.adk`` is imported lazily inside
  :func:`build_function_tools`, so these callables are importable, testable and runnable with
  no ADK and no cloud SDK installed.
* **Typed and documented.** A runtime derives each tool's name, description and JSON parameter
  schema from the signature and the docstring, so both are part of the contract.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from hex_service_kit.serialization import to_jsonable
from pii_kit import redact

from ..config import Container, Settings, build_container, build_review_service
from ..domain.pii import PII_PATTERNS

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool

#: The identity every tool call on this surface is attributed to. It names the SERVICE, not a
#: person, so an agent-initiated action is never mistaken for a human's.
#:
#: It is a CONSTANT rather than a parameter, and that is the invariant rather than a convenience:
#: identity is resolved and never accepted. A runtime derives each tool's JSON parameter schema
#: from the signature below, so an ``actor`` argument would let a model choose the string that
#: becomes the WORM audit actor and the Hrz7 maker, and a ``tenant`` argument would let it choose
#: whose book to read. The HTTP surface has never carried either (``WatchlistReviewRequest``
#: names only the obligor and the period), and this one now matches it. When a runtime can
#: propagate a verified end user, it arrives through the same server-side resolution the API
#: uses, never through an argument the model filled in.
DEFAULT_ACTOR = "credit-portfolio-early-warning-agent"


def _container(settings: Settings | None) -> Container:
    return build_container(settings)


def _redacted(node: Any) -> Any:
    """Mask personal data in every string of a tool result, however deeply it is nested.

    A tool result is not an API response. The API returns to the authenticated caller the text
    that caller just submitted; a TOOL result goes into a model's context, and P-04 says
    minimise the data that reaches a model. The evidence snippet a caller may legitimately read
    back is therefore masked here, on the way to the agent, using the same pattern pack the
    audit write masks with. Walking the whole structure rather than three named fields means a
    future field cannot arrive unredacted just because nobody remembered to add it.
    """
    if isinstance(node, str):
        return redact(node, PII_PATTERNS)
    if isinstance(node, dict):
        return {key: _redacted(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_redacted(value) for value in node]
    return node


def review_obligor(
    obligor_id: str,
    test_period: str = "",
    as_of: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Review one obligor's covenants and early-warning signals and PROPOSE a watchlist grade.

    Tests the covenants credit-memo-drafting extracted at origination against the reported
    period, fuses financial, behavioural, external and process signals through a deterministic
    scoring engine, writes an already-redacted audit record, and, when the proposal is
    consequential, routes it to the human-review console (rule R8). It never applies a grade:
    there is no write path to the grading system of record in any profile.

    The identity and the tenant are RESOLVED here and are not arguments: see
    :data:`DEFAULT_ACTOR`. A caller cannot attribute this call to somebody else or point it at
    another tenant's book, because there is nothing on the signature to attribute it with.

    Args:
      obligor_id: The key the grade registry holds, never a free-text party name.
      test_period: The covenant reporting period. Empty means the latest reported.
      as_of: ISO date for the review. Empty means today.

    Returns:
      A JSON-safe result dict with every string masked for personal data (P-04: a tool result
      goes into a model's context), plus ``review_ref``: where the escalation WENT. It is empty
      only when the proposal did not escalate, so a caller can tell a routed escalation from a
      flag nobody read.
    """
    container = _container(settings)
    service = build_review_service(container)
    review = service.review(
        obligor_id,
        tenant=container.settings.tenant,
        actor=DEFAULT_ACTOR,
        as_of=date.fromisoformat(as_of) if as_of else date.today(),
        test_period=test_period,
    )
    payload = _redacted(to_jsonable(review))
    if not isinstance(payload, dict):  # pragma: no cover - dataclasses serialise to objects
        raise TypeError("a watchlist review must serialise to a JSON object")
    # Attached after the redaction pass: it is a routing reference, not narrative text, and
    # masking an identifier would break the caller's ability to look the review up.
    payload["review_ref"] = review.review_ref
    payload["requires_human_review"] = review.assessment.requires_human_review
    payload["grade_applied"] = review.grade_applied
    return payload


def verify_audit_trail(settings: Settings | None = None) -> dict[str, Any]:
    """Verify the audit trail's hash chain and its external head anchor.

    Returns:
      A dict with ``ok``, the record counts and a ``detail`` string. ``ok`` is false for an
      edited, deleted or reordered record, and, when an external anchor is configured, for a
      truncated tail as well. Without an anchor a truncation cannot be detected, and the detail
      says so rather than implying a stronger guarantee than the store provides.
    """
    resolved = settings or Settings.load()
    audit = _container(resolved).audit
    verify = getattr(audit, "verify", None)
    if verify is None:
        raise NotImplementedError(
            f"the {resolved.profile} audit adapter does not expose chain verification; a "
            "managed WORM sink is verified by its own retention policy, not from here"
        )
    report = verify()
    return {
        "ok": report.ok,
        "entries": report.entries,
        "chained": report.chained,
        "legacy": report.legacy,
        "first_bad_seq": report.first_bad_seq,
        "detail": report.detail,
        "anchored": bool(resolved.audit_anchor_path),
    }


#: The tool table. The agent card advertises exactly these, by function name.
TOOL_FUNCTIONS = (review_obligor, verify_audit_trail)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each callable as a runtime FunctionTool (the only ADK-dependent code path).

    The import is deliberately here rather than at module scope: without it this module, the
    card and every tool would need an agent runtime installed to be imported at all, and the
    offline gate installs none.
    """
    # No ignore comment: the missing-import error for this module is already reported (and
    # ignored) at the TYPE_CHECKING import above, and a second one would be flagged as unused.
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=function) for function in TOOL_FUNCTIONS]
