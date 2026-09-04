"""Managed CovenantTermsPort: READ credit-memo-drafting's origination extract over its API.

The S2S credential is a Google-signed OIDC ID token addressed to credit-memo-drafting's audience, so
the lazy ``google.auth`` import is the first thing the token helper does and an offline caller gets
an ImportError there rather than at construction. The HTTP itself is stdlib ``urllib``, so no extra
runtime dependency is pulled in.

An UNSET or emptied endpoint RAISES naming the variable rather than returning an empty tuple.
That distinction is load bearing for this vertical: an empty covenant set is indistinguishable
from an obligor with no covenants, and an obligor with no covenants is an obligor nobody is
monitoring. The engine would then produce a confident affirm on a borrower nobody tested.
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
from ...domain.models import (
    CovenantObservation,
    CovenantOperator,
    CovenantTerm,
    CovenantType,
)
from ...ports.tenancy import CrossTenantError

_ENDPOINT_ENV = "CREDITEWS_CREDIT_MEMO_URL"


def _as_date(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:  # pragma: no cover - a malformed upstream date is an upstream defect
        return None


class CloudCovenantTerms:
    """Read the origination covenant extract from credit-memo-drafting's authenticated read API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def terms_for(
        self, obligor_id: str, *, tenant: str, test_period: str = ""
    ) -> tuple[CovenantTerm, ...]:
        query = f"?tenant={urllib.parse.quote(tenant)}"
        if test_period:
            query += f"&test_period={urllib.parse.quote(test_period)}"
        status, body = self._get(
            f"/v1/obligors/{urllib.parse.quote(obligor_id)}/covenants{query}", obligor_id, tenant
        )
        if status == 404:
            return ()
        return tuple(_term_from_json(item, obligor_id) for item in body.get("covenants", []))

    def observations_for(
        self, obligor_id: str, *, tenant: str, test_period: str
    ) -> tuple[CovenantObservation, ...]:
        query = (
            f"?tenant={urllib.parse.quote(tenant)}&test_period={urllib.parse.quote(test_period)}"
        )
        status, body = self._get(
            f"/v1/obligors/{urllib.parse.quote(obligor_id)}/covenant-observations{query}",
            obligor_id,
            tenant,
        )
        if status == 404:
            return ()
        return tuple(
            _observation_from_json(item, obligor_id) for item in body.get("observations", [])
        )

    # ------------------------------------------------------------------ #
    def _base_url(self) -> str:
        base = self._settings.credit_memo_url.strip()
        if not base:
            raise RuntimeError(
                f"{_ENDPOINT_ENV} is not configured, so the covenant feed has no origination "
                "service to read. It refuses rather than returning an empty covenant set: an "
                "obligor with no covenants is an obligor nobody is monitoring."
            )
        return base.rstrip("/")

    def _token(self, audience: str) -> str:
        # Lazy import: the offline profiles bind this adapter too and must construct with no SDK.
        import google.auth.transport.requests
        from google.oauth2 import id_token

        request = google.auth.transport.requests.Request()
        return str(id_token.fetch_id_token(request, audience))

    def _get(self, path: str, obligor_id: str, tenant: str) -> tuple[int, Any]:
        base = self._base_url()
        request = urllib.request.Request(
            base + path, headers={"Authorization": f"Bearer {self._token(base)}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - fixed base
                return response.status, json.loads(response.read().decode("utf-8"))
        except (
            urllib.error.HTTPError
        ) as exc:  # pragma: no cover - needs a live credit-memo-drafting
            if exc.code == 403:
                raise CrossTenantError(
                    f"obligor {obligor_id!r} is not in tenant {tenant!r}"
                ) from exc
            return exc.code, {}


def _term_from_json(item: Any, obligor_id: str) -> CovenantTerm:
    facility_id = str(item.get("facility_id", ""))
    covenant_id = str(item.get("covenant_id", ""))
    return CovenantTerm(
        covenant_id=covenant_id,
        facility_id=facility_id,
        obligor_id=obligor_id,
        type=CovenantType(str(item.get("type", "other"))),
        description=str(item.get("description", "")),
        metric=str(item.get("metric", "")),
        threshold=float(item.get("threshold", 0.0)),
        operator=CovenantOperator(str(item.get("operator", "<="))),
        test_period=str(item.get("test_period", "")),
        period_end=_as_date(item.get("period_end")),
        certificate_due_on=_as_date(item.get("certificate_due_on")),
        headroom_band=(
            float(item["headroom_band"]) if item.get("headroom_band") is not None else None
        ),
        waiver_reference=str(item.get("waiver_reference", "")),
        waiver_expiry=_as_date(item.get("waiver_expiry")),
        consecutive_breaches=int(item.get("consecutive_breaches", 0)),
        citations=(
            Citation(
                source_id=f"doc2:{facility_id}:{covenant_id}",
                title="Credit agreement covenant schedule (origination extract)",
                snippet=str(item.get("clause_ref", "")),
            ),
        ),
    )


def _observation_from_json(item: Any, obligor_id: str) -> CovenantObservation:
    covenant_id = str(item.get("covenant_id", ""))
    test_period = str(item.get("test_period", ""))
    observed = item.get("observed_value")
    return CovenantObservation(
        covenant_id=covenant_id,
        obligor_id=obligor_id,
        test_period=test_period,
        observed_value=None if observed is None else float(observed),
        certificate_received_on=_as_date(item.get("certificate_received_on")),
        source=str(item.get("source", "")),
        source_ref=str(item.get("source_ref", "")),
        citations=(
            Citation(
                source_id=f"cert:{obligor_id}:{covenant_id}:{test_period}",
                title="Compliance certificate",
                snippet=str(item.get("source_ref", "")),
            ),
        ),
    )
