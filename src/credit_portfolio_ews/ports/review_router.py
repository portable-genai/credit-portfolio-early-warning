"""ReviewRouterPort: the boundary that routes a watchlist proposal to Hrz7 (rule R8).

Rule R8 is the reason this port exists. A producer that sets ``requires_human_review`` MUST hand
the item to the Hrz7 Human-Review and Maker-Checker Console; terminating the escalation in a
per-repo boolean is the failure this port removes, because a flag nobody reads is auto-execution
with extra steps. Setting the flag and calling :meth:`route` is one act, not two optional ones.

What travels is a :class:`~..domain.models.WatchlistReview`: the assessment, already redacted at
the service edge, plus the approval count the service computed. It is a PROPOSAL and never an
application, and ``grade_applied`` on it is always false, because no adapter in any profile has a
method that could write a grade.

The domain stays pure. This port names the hand-off; the adapters (not this module) depend on
the shared ``review-kit`` and perform the S2S submission.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import WatchlistReview


@runtime_checkable
class ReviewRouterPort(Protocol):
    def route(self, review: WatchlistReview, *, maker: str, tenant: str = "") -> str:
        """Route a proposal to Hrz7 and return the routing reference.

        ``maker`` is the VERIFIED principal that originated the underlying review, never a
        client-asserted actor; the checker is the credit officer who holds the delegated
        authority. The return value is the console's review id where the console answered, or a
        local queue reference where the submission was buffered; it is never empty, so a caller
        can record what happened to the escalation.
        """
        ...
