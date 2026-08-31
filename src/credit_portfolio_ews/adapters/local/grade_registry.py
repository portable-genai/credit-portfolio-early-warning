"""Local GradeRegistryPort: the offline grading system of record, READ ONLY.

Read only by construction of the Protocol, and this class deliberately carries no other public
method: ``tests/unit/test_registry_is_read_only.py`` scans every bound adapter in every profile
for a public attribute matching a write verb, and it was shown red against a planted
``set_grade``.

``None`` for an unknown obligor is a real answer the service turns into a 404, never a default
pass record: inventing a grade of record would let the engine compute a movement against a
fiction. The estate includes one obligor with no completed review, so the review-clock absence
branch is exercised offline.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ObligorRecord
from ...ports.tenancy import CrossTenantError
from . import _fixtures


class LocalGradeRegistry:
    """Read obligor records from the deterministic offline estate, tenant-scoped."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def obligor(self, obligor_id: str, *, tenant: str) -> ObligorRecord | None:
        if _fixtures.belongs_to_another_tenant(obligor_id, tenant):
            raise CrossTenantError(f"obligor {obligor_id!r} is not in tenant {tenant!r}")
        fixture = _fixtures.find(obligor_id, tenant)
        return fixture.record if fixture is not None else None

    def list_obligors(self, tenant: str) -> tuple[ObligorRecord, ...]:
        return tuple(fixture.record for fixture in _fixtures.ESTATE.get(tenant, {}).values())
