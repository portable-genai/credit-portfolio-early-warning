"""Local CovenantTermsPort: the offline copy of a read of credit-memo-drafting's extract.

Serves the shared synthetic estate in ``_fixtures.py``, the same module the eval and the demo
load. Cross-tenant reads are refused the same way the managed adapter must refuse them: an
obligor that exists under another tenant raises :class:`CrossTenantError` (403), while a wholly
unknown id returns an empty tuple, so the offline gate proves the authorisation rule rather than
assuming it.

An obligor with no facility returns an empty tuple, which is a REAL answer the engine handles
(no covenant tests, and the completeness denominator falls back to the required-metric count).
It never fabricates a term to avoid an empty result.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import CovenantObservation, CovenantTerm
from ...ports.tenancy import CrossTenantError
from . import _fixtures


class LocalCovenantTerms:
    """Read origination covenants from the deterministic offline estate, tenant-scoped."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def terms_for(
        self, obligor_id: str, *, tenant: str, test_period: str = ""
    ) -> tuple[CovenantTerm, ...]:
        fixture = _fixture(obligor_id, tenant)
        if fixture is None:
            return ()
        if not test_period:
            return fixture.terms
        return tuple(term for term in fixture.terms if term.test_period == test_period)

    def observations_for(
        self, obligor_id: str, *, tenant: str, test_period: str
    ) -> tuple[CovenantObservation, ...]:
        fixture = _fixture(obligor_id, tenant)
        if fixture is None:
            return ()
        return tuple(
            observation
            for observation in fixture.covenant_observations
            if observation.test_period == test_period
        )


def _fixture(obligor_id: str, tenant: str) -> _fixtures.ObligorFixture | None:
    if _fixtures.belongs_to_another_tenant(obligor_id, tenant):
        raise CrossTenantError(f"obligor {obligor_id!r} is not in tenant {tenant!r}")
    return _fixtures.find(obligor_id, tenant)
