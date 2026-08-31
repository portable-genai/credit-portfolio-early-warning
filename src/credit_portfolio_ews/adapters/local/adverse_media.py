"""Local AdverseMediaPort: a small fixture corpus of obviously fictional trade-press items.

Filtered by obligor and by the lookback window. The corpus deliberately includes an UNCONFIRMED
insolvency headline about a similarly named entity, so the offline gate proves that an
unconfirmed item is surfaced in ``confirmation_requested`` and contributes exactly zero, and
three CONFIRMED items that arrive UNCATEGORISED, so the offline profile exercises the same
two-stage path the managed one does: the feed confirms relevance, the model assigns the category.

An obligor with no coverage returns an empty tuple, which is normal and NOT an error. No news is
a real answer, unlike an empty covenant set.
"""

from __future__ import annotations

from datetime import date

from ...config import Settings
from ...domain.models import AdverseNewsItem
from . import _fixtures


class LocalAdverseMedia:
    """Serve the deterministic offline media corpus for one obligor."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def items(
        self, obligor_id: str, *, tenant: str, as_of: date, lookback_days: int
    ) -> tuple[AdverseNewsItem, ...]:
        fixture = _fixtures.find(obligor_id, tenant)
        if fixture is None:
            return ()
        return tuple(
            item
            for item in fixture.news
            if item.published_on <= as_of and (as_of - item.published_on).days <= lookback_days
        )
