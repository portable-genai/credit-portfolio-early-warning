"""Domain errors this vertical raises. Pure stdlib, importable with nothing installed.

Both are deliberately hard failures rather than logged warnings. An early-warning signal with no
source behind it is a claim a reviewer cannot trace, and a watchlist proposal made of untraceable
claims is worse than no proposal at all: it looks exactly like a traceable one. An obligor the
grade registry does not hold has no grade of record, and computing a movement against an invented
one would be worse still.
"""

from __future__ import annotations


class UngroundedSignalError(RuntimeError):
    """A fired signal, or a non-compliant covenant test, carried no Citation.

    Raised by the engine rather than scored as zero. Scoring it zero would mean an uncited
    claim silently changed the composite by nothing and still appeared on the officer's screen
    beside the cited ones, which is the failure mode grounding exists to prevent.
    """


class ObligorNotFoundError(LookupError):
    """The grade registry holds no record for this obligor under this tenant.

    A 404 at the surface. Never a default pass record: an obligor the registry does not know has
    no grade of record, and a movement computed against a fabricated one would look exactly like
    a real proposal on the officer's screen.
    """

    http_status = 404
