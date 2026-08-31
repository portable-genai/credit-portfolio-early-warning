"""On-prem CovenantTermsPort: fail-fast placeholder. This is the load-bearing refusal.

A covenant feed that returned an empty tuple would be indistinguishable from an obligor with no
covenants, and an obligor with no covenants is an obligor nobody is monitoring: the engine would
produce a confident affirm on a borrower nobody tested. So it raises, and names what a client
must bind.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import CovenantObservation, CovenantTerm

_REFUSAL = (
    "on-prem covenant terms are a portability placeholder: bind the client's own covenant store, "
    "or their own credit-memo-drafting deployment (see docs/onprem-migration.md). It refuses "
    "rather than returning an empty covenant set, because an obligor with no covenants is an "
    "obligor nobody is monitoring."
)


class OnPremCovenantTerms:
    """Satisfies CovenantTermsPort but refuses at call time."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def terms_for(
        self, obligor_id: str, *, tenant: str, test_period: str = ""
    ) -> tuple[CovenantTerm, ...]:
        raise NotImplementedError(_REFUSAL)

    def observations_for(
        self, obligor_id: str, *, tenant: str, test_period: str
    ) -> tuple[CovenantObservation, ...]:
        raise NotImplementedError(_REFUSAL)
