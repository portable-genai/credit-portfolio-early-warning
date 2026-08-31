"""AdverseMediaPort: the external, unstructured feed, kept deliberately separate.

Adverse media is a genuinely different boundary from the two structured feeds: it is external
and unstructured, its items need a published date and a source locator to be citable at all, and
whether an item is about THIS obligor is an assertion somebody makes rather than a figure
somebody measured. Keeping it on its own port is what makes the relevance gate legible: only a
FEED-confirmed item can fire a rule, and that fact lives in one place instead of being buried in
a mixed feed.

An empty result is a REAL answer here, unlike an empty covenant set: no news is normal, and a
service that treated it as an error would refuse to review the quiet obligors. What is not
allowed is an item with no resolvable locator, which the adapters DROP rather than carry,
because an item that cannot be cited cannot be scored.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from ..domain.models import AdverseNewsItem


@runtime_checkable
class AdverseMediaPort(Protocol):
    def items(
        self, obligor_id: str, *, tenant: str, as_of: date, lookback_days: int
    ) -> tuple[AdverseNewsItem, ...]:
        """Retrieved items for this obligor inside the lookback window, each already cited.

        ``relevance`` is read from the feed's own field and is never inferred in this repo.
        """
        ...
