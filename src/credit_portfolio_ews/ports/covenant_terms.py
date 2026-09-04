"""CovenantTermsPort: READ the covenants credit-memo-drafting extracted at ORIGINATION.

The catalog contract is that this service tests covenant compliance against the terms
credit-memo-drafting extracted when the facility was written, and is distinct from
credit-memo-drafting precisely because it does not re-extract. That dependency has to be a NAMED
boundary, or the first pragmatic change re-implements extraction here and the two services start
disagreeing about the same covenant. The port also makes the direction visible in the import graph:
this repo reads credit-memo-drafting and credit-memo-drafting never reads this repo.

Two methods, because the term and its compliance certificate come from the same origination and
agency process but at different times, and the certificate date is what separates a covenant that
is NOT DUE from one that is NOT EVIDENCED.

An EMPTY tuple from a managed adapter is never an error answer: a covenant feed that returned
one instead of raising would hand the engine an obligor with a clean covenant sheet, and produce
a confident affirm on a borrower nobody tested.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import CovenantObservation, CovenantTerm


@runtime_checkable
class CovenantTermsPort(Protocol):
    def terms_for(
        self, obligor_id: str, *, tenant: str, test_period: str = ""
    ) -> tuple[CovenantTerm, ...]:
        """The covenant terms on this obligor's facilities, as extracted at origination.

        An obligor with no facility returns an empty tuple, which the engine handles: no covenant
        tests, and the completeness denominator falls back to the required-metric count. Raises
        :class:`~.tenancy.CrossTenantError` for an obligor under another tenant.
        """
        ...

    def observations_for(
        self, obligor_id: str, *, tenant: str, test_period: str
    ) -> tuple[CovenantObservation, ...]:
        """The tested values and certificate dates for ``test_period``.

        A term with no observation here is a finding, not a zero: the engine decides whether that
        is NOT DUE or NOT EVIDENCED from the period end and the certificate clock.
        """
        ...
