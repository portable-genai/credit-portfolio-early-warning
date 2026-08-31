"""PortfolioFeedPort: the spreading system and the transaction warehouse, in one record shape.

Financial spreads and transaction behaviour are two of the three evidence families the catalog
names, and they arrive from where a bank actually keeps them. One port and one normalised
observation shape, because the engine must reason over ONE evidence shape whatever produced it,
and ``periods`` bounds the window so a consecutive-period rule has a defined history to read.

:meth:`arrears` is separate and returns a WHOLE snapshot because the materiality legs compare
figures that must come from the same snapshot at the same date. Split across the metric stream, a
fresh arrears amount could be tested against a stale exposure and the gate would silently mean
nothing. ``None`` is meaningful and never a zero: the past-due rules then have nothing to test,
and the engine records that rather than reading it as zero days.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from ..domain.models import ArrearsSnapshot, SignalObservation


@runtime_checkable
class PortfolioFeedPort(Protocol):
    def observations(
        self, obligor_id: str, *, tenant: str, as_of: date, periods: int = 8
    ) -> tuple[SignalObservation, ...]:
        """The normalised metric window for this obligor, newest first.

        Raises :class:`~.tenancy.CrossTenantError` for an obligor under another tenant.
        """
        ...

    def arrears(self, obligor_id: str, *, tenant: str, as_of: date) -> ArrearsSnapshot | None:
        """The servicing snapshot the materiality gate runs on, or ``None`` when there is none."""
        ...
