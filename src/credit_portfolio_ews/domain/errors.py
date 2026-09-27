"""Domain errors this vertical raises. Pure stdlib, importable with nothing installed.

Two are deliberately hard failures rather than logged warnings. An early-warning signal with no
source behind it is a claim a reviewer cannot trace, and a watchlist proposal made of untraceable
claims is worse than no proposal at all: it looks exactly like a traceable one. An obligor the
grade registry does not hold has no grade of record, and computing a movement against an invented
one would be worse still. ``GuardrailBlockedError`` is the odd one out: it is raised by
``domain/watchlist_service.py`` around a narration call and CAUGHT there too, exactly like the
on-prem narrator's ``NotImplementedError``, so a blocked prompt or draft costs a paragraph (a
discard reason) and never the assessment itself.
"""

from __future__ import annotations


class GuardrailBlockedError(RuntimeError):
    """The guardrail (rule R1) refused a narration call's input or output, or could not decide.

    Raised by ``domain/watchlist_service._screened_generate`` on either direction of either
    model job (adverse-media categorisation, memo drafting), after the block has already been
    audited as its own WORM record. The caller treats it exactly like a model fault: never a
    half-drafted memo, never a fabricated category, and never a raise that reaches the console
    with an unaudited block.
    """


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
