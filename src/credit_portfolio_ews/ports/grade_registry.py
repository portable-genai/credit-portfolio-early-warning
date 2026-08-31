"""GradeRegistryPort: the grade of record, READ ONLY. This is the vertical's headline control.

The service needs the grade of record to compute a movement, and the catalog line says this
service never re-grades an obligor autonomously. That promise is enforced by ABSENCE: the
Protocol below declares read methods and nothing else. There is no ``set_grade``, no
``apply_proposal`` and no write of any kind, so no future refactor can reach one by accident and
the claim is checkable by anyone who opens this file rather than resting on a boolean somebody
could flip.

The approved grade is applied by the registry's own maker-checker after the review console
approves it, outside this service. Two tests hold the control, and both were shown red against a
planted ``set_grade``: one asserts this Protocol's public method set is exactly these two, and
one scans every bound adapter in every profile for a public attribute matching a write verb.

``None`` from :meth:`obligor` is a real answer the service turns into a 404, never a default
pass record: inventing a grade of record for an obligor the registry does not know would let the
engine compute a movement against a fiction.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import ObligorRecord

#: Verb stems a public adapter attribute may not start with. The read-only claim is enforced on
#: the Protocol AND on every bound adapter, because a Protocol is structural: an adapter may
#: satisfy it and still carry extra methods.
WRITE_VERBS: tuple[str, ...] = (
    "set",
    "write",
    "apply",
    "update",
    "put",
    "post",
    "save",
    "upsert",
    "patch",
    "delete",
    "create",
    "grade",
    "downgrade",
    "upgrade",
    "assign",
)


@runtime_checkable
class GradeRegistryPort(Protocol):
    def obligor(self, obligor_id: str, *, tenant: str) -> ObligorRecord | None:
        """The obligor's record, including the grade of record, or ``None`` if unknown.

        Raises :class:`~.tenancy.CrossTenantError` for an obligor under another tenant.
        """
        ...

    def list_obligors(self, tenant: str) -> tuple[ObligorRecord, ...]:
        """Every obligor in this tenant's book, for the console's obligor picker."""
        ...
