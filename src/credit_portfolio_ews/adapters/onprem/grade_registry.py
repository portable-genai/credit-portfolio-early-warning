"""On-prem GradeRegistryPort: fail-fast placeholder, and it must STAY read-only when rebound.

A client binds their own grading system of record here. The seam must keep its read-only shape:
an on-premises adapter that gained a write method would defeat the control the whole vertical
rests on, which is that this service proposes a grade and has no method that could apply one.

Returning a default record would be the worst possible placeholder: every obligor would appear
unchanged, nothing would ever be proposed, and the service would look like it was working.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ObligorRecord

_REFUSAL = (
    "on-prem grade registry is a portability placeholder: bind the client's own grading system "
    "of record, READ ONLY (see docs/onprem-migration.md). It refuses rather than defaulting a "
    "grade, because a default grade of record makes every obligor look unchanged."
)


class OnPremGradeRegistry:
    """Satisfies GradeRegistryPort but refuses at call time. No write method, on purpose."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def obligor(self, obligor_id: str, *, tenant: str) -> ObligorRecord | None:
        raise NotImplementedError(_REFUSAL)

    def list_obligors(self, tenant: str) -> tuple[ObligorRecord, ...]:
        raise NotImplementedError(_REFUSAL)
