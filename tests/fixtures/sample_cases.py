"""Canonical synthetic obligors, shared by the unit and contract suites.

There is ONE synthetic estate in this repo and it lives in ``adapters/local/_fixtures.py``: the
local adapters serve it, the demo drives it and the eval loads it. This module names the few
members of it the contract and unit suites need by role, so a test says WHICH obligor it means
and why, rather than repeating an id nobody can interpret.

Every party is obviously fictional and every address is an ``.example`` domain.
"""

from __future__ import annotations

from credit_portfolio_ews.adapters.local import (
    _fixtures,
)

#: The verified principal the tests attribute work to (never a client-asserted actor).
ACTOR = "analyst@bank.example"

#: The tenant the offline estate belongs to, and one that holds a DIFFERENT obligor.
TENANT = _fixtures.TENANT
OTHER_TENANT = _fixtures.OTHER_TENANT

#: The sweep date every fixture is written against. An explicit date, never a clock.
AS_OF = _fixtures.AS_OF
TEST_PERIOD = _fixtures.TEST_PERIOD

#: An obligor that MUST escalate: two floors apply and a two-notch downgrade is proposed.
ESCALATING_OBLIGOR = "obl-delta-004"

#: An obligor that must NOT escalate: a router that manufactured a review here would be lying.
ROUTINE_OBLIGOR = "obl-kappa-010"

#: An obligor whose covenant clause names a guarantor, for the redact-before-anything proofs.
PII_OBLIGOR = "obl-gamma-003"

#: An obligor held under another tenant. Reading it must be 403 and never 404.
FOREIGN_OBLIGOR = "obl-omega-999"

#: An obligor the registry does not hold at all. Reading it is a 404.
UNKNOWN_OBLIGOR = "obl-nobody-000"

#: A planted identifier, so a redaction assertion has an independent literal to look for rather
#: than trusting the pattern pack to agree with itself.
PLANTED_NRIC = _fixtures.fixture_for(PII_OBLIGOR).planted_identifier


def fixture(obligor_id: str) -> _fixtures.ObligorFixture:
    """The whole evidence set for one obligor, straight from the shared estate."""
    return _fixtures.fixture_for(obligor_id)
