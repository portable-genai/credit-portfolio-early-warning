"""On-prem PortfolioFeedPort: fail-fast placeholder (bind the client's own systems).

Returning an empty tuple would present a stressed obligor as a clean one, and returning no
arrears snapshot silently would present an obligor in default as current. Both are worse than a
refusal, because both look exactly like a working service.
"""

from __future__ import annotations

from datetime import date

from ...config import Settings
from ...domain.models import ArrearsSnapshot, SignalObservation

_REFUSAL = (
    "on-prem portfolio feed is a portability placeholder: bind the client's own spreading system "
    "and transaction warehouse (see docs/onprem-migration.md). It refuses rather than returning "
    "an empty window, because silence here presents a stressed obligor as a clean one."
)


class OnPremPortfolioFeed:
    """Satisfies PortfolioFeedPort but refuses at call time."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def observations(
        self, obligor_id: str, *, tenant: str, as_of: date, periods: int = 8
    ) -> tuple[SignalObservation, ...]:
        raise NotImplementedError(_REFUSAL)

    def arrears(self, obligor_id: str, *, tenant: str, as_of: date) -> ArrearsSnapshot | None:
        raise NotImplementedError(_REFUSAL)
