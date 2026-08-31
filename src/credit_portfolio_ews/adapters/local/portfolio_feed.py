"""Local PortfolioFeedPort: the offline spreading system and transaction warehouse.

Returns the fixture observation window ordered by ``(as_of, period, source_ref)`` descending, so
the engine reads the same declared total order it would read from a warehouse, plus the arrears
snapshot for the materiality cases: one that clears both legs, one that fails the relative leg on
a small amount, and one at ninety-six days. The thin-file obligor deliberately carries fewer
metrics, so the coverage rule and the short-history branch are exercised by the offline gate
rather than existing only in theory.
"""

from __future__ import annotations

from datetime import date

from ...config import Settings
from ...domain.models import ArrearsSnapshot, SignalObservation
from ...ports.tenancy import CrossTenantError
from . import _fixtures


class LocalPortfolioFeed:
    """Serve the deterministic offline metric window and arrears snapshot, tenant-scoped."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def observations(
        self, obligor_id: str, *, tenant: str, as_of: date, periods: int = 8
    ) -> tuple[SignalObservation, ...]:
        fixture = _fixture(obligor_id, tenant)
        if fixture is None:
            return ()
        ordered = sorted(
            (row for row in fixture.observations if row.as_of <= as_of),
            key=lambda row: (row.as_of, row.period, row.source_ref),
            reverse=True,
        )
        keep = sorted({row.period for row in ordered}, reverse=True)[:periods]
        return tuple(row for row in ordered if row.period in keep)

    def arrears(self, obligor_id: str, *, tenant: str, as_of: date) -> ArrearsSnapshot | None:
        fixture = _fixture(obligor_id, tenant)
        return fixture.arrears if fixture is not None else None


def _fixture(obligor_id: str, tenant: str) -> _fixtures.ObligorFixture | None:
    if _fixtures.belongs_to_another_tenant(obligor_id, tenant):
        raise CrossTenantError(f"obligor {obligor_id!r} is not in tenant {tenant!r}")
    return _fixtures.find(obligor_id, tenant)
