"""Managed GradeRegistryPort: READ the obligor row from the managed grade store.

Read only by construction of the Protocol, and read only again in the deployment: the serving
identity's least-privilege role in ``infra/terraform/iam.tf`` grants viewer on that collection
only, so the claim is enforced at two layers rather than one. This class deliberately carries no
public method beyond the two the Protocol declares; the read-only scan in the offline gate walks
every bound adapter in every profile looking for a write verb.

The SDK import is lazy, inside each method, so the offline profiles bind this adapter and
construct it with no cloud SDK installed. An unconfigured endpoint RAISES; returning a default
record would be the worst possible placeholder, because every obligor would appear unchanged and
nothing would ever be proposed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

from ...config import Settings
from ...domain.kernel import Citation
from ...domain.models import ObligorRecord, WatchGrade
from ...ports.tenancy import CrossTenantError

_ENDPOINT_ENV = "CREDITEWS_GRADE_REGISTRY_URL"


class CloudGradeRegistry:
    """Read the grade of record from the managed grading system, tenant-partitioned."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def obligor(self, obligor_id: str, *, tenant: str) -> ObligorRecord | None:
        status, body = self._get(
            f"/v1/obligors/{urllib.parse.quote(obligor_id)}?tenant={urllib.parse.quote(tenant)}",
            obligor_id,
            tenant,
        )
        if status == 404:
            return None
        return _record_from_json(body)

    def list_obligors(self, tenant: str) -> tuple[ObligorRecord, ...]:
        _status, body = self._get(f"/v1/obligors?tenant={urllib.parse.quote(tenant)}", "", tenant)
        return tuple(_record_from_json(item) for item in body.get("obligors", []))

    # ------------------------------------------------------------------ #
    def _base_url(self) -> str:
        base = self._settings.grade_registry_url.strip()
        if not base:
            raise RuntimeError(
                f"{_ENDPOINT_ENV} is not configured, so the grade of record cannot be read. It "
                "refuses rather than defaulting a grade: a movement computed against an invented "
                "grade of record looks exactly like a real proposal."
            )
        return base.rstrip("/")

    def _get(self, path: str, obligor_id: str, tenant: str) -> tuple[int, Any]:
        base = self._base_url()
        # Lazy import: every profile binds this adapter and must construct with no SDK present.
        import google.auth.transport.requests
        from google.oauth2 import id_token

        request = google.auth.transport.requests.Request()
        token = str(id_token.fetch_id_token(request, base))
        req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310 - fixed base
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - needs a live registry
            if exc.code == 403:
                raise CrossTenantError(
                    f"obligor {obligor_id!r} is not in tenant {tenant!r}"
                ) from exc
            return exc.code, {}


def _as_date(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:  # pragma: no cover - a malformed upstream date is an upstream defect
        return None


def _record_from_json(item: Any) -> ObligorRecord:
    obligor_id = str(item.get("obligor_id", ""))
    return ObligorRecord(
        obligor_id=obligor_id,
        name=str(item.get("name", "")),
        sector=str(item.get("sector", "")),
        jurisdiction=str(item.get("jurisdiction", "")),
        current_grade=WatchGrade(str(item.get("current_grade", "pass"))),
        exposure_amount_minor=int(item.get("exposure_amount_minor", 0)),
        currency=str(item.get("currency", "")),
        clean_periods=int(item.get("clean_periods", 0)),
        watchlist_since=_as_date(item.get("watchlist_since")),
        last_review_on=_as_date(item.get("last_review_on")),
        source="grade-registry",
        citations=(
            Citation(
                source_id=f"registry:{obligor_id}",
                title="Grading system of record",
                snippet="grade of record, read only",
            ),
        ),
    )
