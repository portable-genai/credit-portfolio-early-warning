"""On-prem AdverseMediaPort: fail-fast placeholder (bind the client's own screening feed)."""

from __future__ import annotations

from datetime import date

from ...config import Settings
from ...domain.models import AdverseNewsItem


class OnPremAdverseMedia:
    """Satisfies AdverseMediaPort but refuses at call time."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def items(
        self, obligor_id: str, *, tenant: str, as_of: date, lookback_days: int
    ) -> tuple[AdverseNewsItem, ...]:
        raise NotImplementedError(
            "on-prem adverse media is a portability placeholder: bind the client's own "
            "adverse-media or screening feed (see docs/onprem-migration.md). An unconfigured "
            "feed and an obligor with no coverage must not look the same."
        )
