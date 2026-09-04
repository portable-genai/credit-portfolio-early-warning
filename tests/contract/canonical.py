"""ONE canonical request per port, shared by the structural and behavioural contract suites.

Parity means the same request through every implementation, so the request needs a single home.
Retyping it per suite is how two "parity" tests end up asserting different things.

Each :class:`PortCase` answers three questions about one port:

* ``invoke``   : what a single canonical call to this port looks like;
* ``answered`` : what it means for the OFFLINE family to have actually answered (a port that
  returns ``None`` and records nothing has not answered, it has merely not raised);
* ``managed_refusal`` : what the MANAGED family must do when called with no cloud reachable.
  Never a silent success: either it refuses because it is unconfigured, or its lazy SDK import
  fails. Both are honest; returning as if the work happened is not.

Adding a port means adding a case here. ``test_port_parity.py`` fails the build if this table
and the port map ever disagree, so the touch list in ``CONTRIBUTING.md`` is enforced rather than
merely written down.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_eval_kit import EvalReport
from hex_service_kit.identity import IdentityError, Principal, RequestContext
from hex_service_kit.observability import TokenUsage

from credit_portfolio_ews.domain.early_warning import (
    EarlyWarningEngine,
)
from credit_portfolio_ews.domain.kernel import (
    AuditEvent,
    Citation,
    Decision,
    Severity,
)
from credit_portfolio_ews.domain.models import (
    WatchlistReview,
)
from credit_portfolio_ews.domain.policy import (
    DEFAULT_POLICY,
)
from credit_portfolio_ews.domain.watchlist_service import (
    redacted_assessment,
)

from tests.fixtures import sample_cases

#: The audit record every audit-port implementation is handed. Already redacted, as the port
#: requires: a raw identifier must never reach a WORM record.
CANONICAL_EVENT = AuditEvent(
    action="watchlist_review",
    actor=sample_cases.ACTOR,
    decision=Decision.ESCALATED,
    severity=Severity.CRITICAL,
    redacted_summary="Delta Agri Trading (FICTIONAL): pass to substandard, composite 65",
    citations=(
        Citation(source_id="ews-policy", title="Early-warning policy", snippet="floor rules"),
    ),
)


def _canonical_assessment() -> Any:
    """Built by running the PURE engine over the shared estate, then redacted the way the
    service redacts it, so the payload the routers are handed is the shape they really see.
    """
    fixture = sample_cases.fixture(sample_cases.ESCALATING_OBLIGOR)
    return redacted_assessment(
        EarlyWarningEngine().evaluate(
            fixture.record,
            fixture.terms,
            fixture.covenant_observations,
            fixture.arrears,
            fixture.observations,
            fixture.news,
            policy=DEFAULT_POLICY,
            as_of=sample_cases.AS_OF,
        )
    )


#: The routed proposal every review-router implementation is handed (rule R8's payload).
CANONICAL_REVIEW = WatchlistReview(assessment=_canonical_assessment(), required_approvals=2)

#: The inbound transport context every identity implementation is handed.
CANONICAL_CONTEXT = RequestContext(headers={"x-dev-persona": "auditor"})

#: The one prompt the generation port is handed. It carries a FACTS block, because that is what
#: the offline narrator restates and what the managed one is instructed to restate.
CANONICAL_PROMPT = (
    "You are drafting a watchlist review memo for a credit officer.\n"
    "FACTS (do not add to these):\n"
    "- obligor: Delta Agri Trading (FICTIONAL)\n"
    "- movement: downgrade\n"
    "- source: ews-policy Early-warning policy row\n"
)


@dataclass(frozen=True, slots=True)
class PortCase:
    """One port's canonical call plus the two verdicts the parity suites need."""

    invoke: Callable[[Any], Any]
    answered: Callable[[Any, Any], bool]
    managed_refusal: tuple[type[BaseException], ...]
    detail: str


def _audit_invoke(adapter: Any) -> Any:
    return adapter.record(CANONICAL_EVENT)


def _audit_answered(adapter: Any, _result: Any) -> bool:
    stored = adapter.log.read_all()
    return bool(stored) and stored[-1]["actor"] == sample_cases.ACTOR and adapter.verify().ok


def _identity_invoke(adapter: Any) -> Any:
    return adapter.resolve(CANONICAL_CONTEXT)


def _identity_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, Principal) and bool(result.actor)


def _review_invoke(adapter: Any) -> Any:
    return adapter.route(CANONICAL_REVIEW, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT)


def _review_answered(adapter: Any, result: Any) -> bool:
    return bool(result) and len(adapter.outbox.pending()) == 1


def _tracer_invoke(adapter: Any) -> Any:
    with adapter.span("canonical.unit", action="canonical"):
        adapter.record_token_usage(TokenUsage(input_tokens=7, output_tokens=2), "canonical-model")
    return True


def _tracer_answered(adapter: Any, result: Any) -> bool:
    return bool(result)


def _evaluation_invoke(adapter: Any) -> Any:
    return adapter.evaluate("eval/datasets/canonical.jsonl")


def _evaluation_answered(adapter: Any, result: Any) -> bool:
    return isinstance(result, EvalReport) and result.dataset.endswith("canonical.jsonl")


def _covenant_invoke(adapter: Any) -> Any:
    return adapter.terms_for(sample_cases.ESCALATING_OBLIGOR, tenant=sample_cases.TENANT)


def _covenant_answered(_adapter: Any, result: Any) -> bool:
    # An EMPTY tuple is not an answer here. A covenant feed that returned one would hand the
    # engine a clean covenant sheet for a borrower nobody tested.
    return bool(result) and all(term.threshold for term in result)


def _portfolio_invoke(adapter: Any) -> Any:
    return adapter.arrears(
        sample_cases.ESCALATING_OBLIGOR, tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF
    )


def _portfolio_answered(_adapter: Any, result: Any) -> bool:
    return result is not None and result.days_past_due > 0


def _media_invoke(adapter: Any) -> Any:
    return adapter.items(
        sample_cases.ESCALATING_OBLIGOR,
        tenant=sample_cases.TENANT,
        as_of=sample_cases.AS_OF,
        lookback_days=180,
    )


def _media_answered(_adapter: Any, result: Any) -> bool:
    # Every retrieved item must already carry its own locator: an item that cannot be cited
    # cannot be scored, and the engine raises rather than scoring it zero.
    return bool(result) and all(item.citation.source_id for item in result)


def _registry_invoke(adapter: Any) -> Any:
    return adapter.obligor(sample_cases.ESCALATING_OBLIGOR, tenant=sample_cases.TENANT)


def _registry_answered(_adapter: Any, result: Any) -> bool:
    return result is not None and bool(result.current_grade)


def _generation_invoke(adapter: Any) -> Any:
    return adapter.generate(CANONICAL_PROMPT)


def _generation_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, str) and result.strip().startswith("{")


CANONICAL_CALLS: dict[str, PortCase] = {
    "audit": PortCase(
        invoke=_audit_invoke,
        answered=_audit_answered,
        # The lazy `google.cloud` import is the first thing the managed sink does.
        managed_refusal=(ImportError,),
        detail="write one already-redacted WORM record",
    ),
    "identity": PortCase(
        invoke=_identity_invoke,
        answered=_identity_answered,
        # No IAP assertion header offline, so the managed adapter refuses before importing.
        managed_refusal=(IdentityError,),
        detail="resolve a verified principal from transport context",
    ),
    "review_router": PortCase(
        invoke=_review_invoke,
        answered=_review_answered,
        # Rule R8: with no console configured the managed router must refuse, not swallow.
        managed_refusal=(RuntimeError,),
        detail="route one watchlist proposal to human review",
    ),
    "tracer": PortCase(
        invoke=_tracer_invoke,
        answered=_tracer_answered,
        # NOTHING. Tracing is not essential to correctness, so the managed adapter must not
        # refuse offline either: with no SDK installed it degrades to a no-op and the traced
        # body still runs. An adapter that raised here would take a request down over a
        # diagnostic, which is the opposite of what every other port on this table wants.
        managed_refusal=(),
        detail="open one span and report the cost of a model call",
    ),
    "evaluation": PortCase(
        invoke=_evaluation_invoke,
        answered=_evaluation_answered,
        # The managed gate reaches model-quality-gate over HTTP, which is unreachable offline.
        managed_refusal=(Exception,),
        detail="score one golden dataset through the promotion authority",
    ),
    "covenant_terms": PortCase(
        invoke=_covenant_invoke,
        answered=_covenant_answered,
        # Unconfigured endpoint: it RAISES rather than returning an empty covenant set.
        managed_refusal=(RuntimeError,),
        detail="read the origination covenant terms for one obligor",
    ),
    "portfolio_feed": PortCase(
        invoke=_portfolio_invoke,
        answered=_portfolio_answered,
        managed_refusal=(RuntimeError,),
        detail="read one arrears snapshot as a single consistent record",
    ),
    "adverse_media": PortCase(
        invoke=_media_invoke,
        answered=_media_answered,
        managed_refusal=(RuntimeError,),
        detail="retrieve adverse media items that already carry their locator",
    ),
    "grade_registry": PortCase(
        invoke=_registry_invoke,
        answered=_registry_answered,
        managed_refusal=(RuntimeError,),
        detail="read the grade of record, and nothing else",
    ),
    "generation": PortCase(
        invoke=_generation_invoke,
        answered=_generation_answered,
        # The lazy `google.genai` import is the first thing the managed narrator does.
        managed_refusal=(ImportError,),
        detail="return a raw draft the caller then validates or discards",
    ),
}
