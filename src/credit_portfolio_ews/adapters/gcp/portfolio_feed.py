"""Managed PortfolioFeedPort: the obligor-metrics and servicing views in BigQuery.

The SDK import is lazy, inside each method, so the offline profiles bind this adapter and
construct it with no cloud SDK installed. Queries are PARAMETERISED only: an obligor id is
caller-supplied text and string interpolation into SQL is how a read port becomes a write one.

Amounts are converted to minor units AT THE BOUNDARY, so the domain never sees a currency float
and the materiality legs compare integers. Residency: the dataset must sit in the deployment
region, which is a Terraform concern recorded in ``infra/``.

An unconfigured dataset RAISES rather than returning an empty window. An empty window would
present a stressed obligor as a clean one, and a missing arrears snapshot would present an
obligor in default as current.

An obligor held for ANOTHER tenant raises ``CrossTenantError`` (403), like every other read port
here. The tenant predicate in the WHERE clause is the authorisation; on its own it answers an
empty window to "not yours" and to "not held", which is the membership oracle ``ports/tenancy.py``
exists to refuse, and it made that module's parity claim false. So an empty tenant-scoped read is
explained before it is returned.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ...config import Settings
from ...domain.kernel import Citation
from ...domain.models import ArrearsSnapshot, SignalObservation
from ...ports.tenancy import CrossTenantError

_DATASET_ENV = "CREDITEWS_METRICS_DATASET"

_OBSERVATIONS_SQL = """
SELECT metric, value, period, as_of, unit, source, source_ref
FROM `{dataset}.obligor_metrics`
WHERE obligor_id = @obligor_id AND tenant = @tenant AND as_of <= @as_of
ORDER BY as_of DESC, period DESC, source_ref DESC
LIMIT @row_limit
"""

_ARREARS_SQL = """
SELECT currency, drawn_amount, past_due_amount, days_past_due, source_ref, as_of
FROM `{dataset}.obligor_servicing`
WHERE obligor_id = @obligor_id AND tenant = @tenant AND as_of <= @as_of
ORDER BY as_of DESC
LIMIT 1
"""

#: Asked only when a tenant-scoped read came back empty, and it selects the OWNING tenant rather
#: than any obligor row, so the refusal costs one bounded lookup and returns no other tenant's
#: data. One statement per table, written out, because the table name is not a parameter.
_OBSERVATIONS_TENANCY_SQL = """
SELECT tenant
FROM `{dataset}.obligor_metrics`
WHERE obligor_id = @obligor_id AND tenant != @tenant
LIMIT 1
"""

_ARREARS_TENANCY_SQL = """
SELECT tenant
FROM `{dataset}.obligor_servicing`
WHERE obligor_id = @obligor_id AND tenant != @tenant
LIMIT 1
"""

#: Rows per period the window may carry, so ``periods`` bounds the read rather than the client.
_ROWS_PER_PERIOD = 32


def _minor(amount: Any) -> int:
    """Currency to minor units at the boundary. Money in a float is a rounding argument."""
    return int(round(float(amount or 0.0) * 100))


class CloudPortfolioFeed:
    """Query the managed obligor-metrics and servicing views under the managed profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def observations(
        self, obligor_id: str, *, tenant: str, as_of: date, periods: int = 8
    ) -> tuple[SignalObservation, ...]:
        rows = self._query(
            _OBSERVATIONS_SQL,
            obligor_id=obligor_id,
            tenant=tenant,
            as_of=as_of,
            row_limit=periods * _ROWS_PER_PERIOD,
        )
        if not rows:
            self._refuse_another_tenant(_OBSERVATIONS_TENANCY_SQL, obligor_id, tenant)
        return tuple(
            SignalObservation(
                metric=str(row["metric"]),
                value=float(row["value"]),
                period=str(row["period"]),
                as_of=row["as_of"],
                unit=str(row.get("unit") or ""),
                source=str(row.get("source") or ""),
                source_ref=str(row.get("source_ref") or ""),
                citations=(
                    Citation(
                        source_id=str(row.get("source_ref") or f"metric:{row['metric']}"),
                        title="Obligor metrics view",
                        snippet=f"{row['metric']} for {row['period']}",
                    ),
                ),
            )
            for row in rows
        )

    def arrears(self, obligor_id: str, *, tenant: str, as_of: date) -> ArrearsSnapshot | None:
        rows = self._query(_ARREARS_SQL, obligor_id=obligor_id, tenant=tenant, as_of=as_of)
        if not rows:
            self._refuse_another_tenant(_ARREARS_TENANCY_SQL, obligor_id, tenant)
            return None
        row = rows[0]
        return ArrearsSnapshot(
            obligor_id=obligor_id,
            as_of=row["as_of"],
            currency=str(row.get("currency") or ""),
            drawn_amount_minor=_minor(row.get("drawn_amount")),
            past_due_amount_minor=_minor(row.get("past_due_amount")),
            days_past_due=int(row.get("days_past_due") or 0),
            source_ref=str(row.get("source_ref") or ""),
            citations=(
                Citation(
                    source_id=str(row.get("source_ref") or f"servicing:{obligor_id}"),
                    title="Servicing arrears snapshot",
                    snippet="drawn and past-due balances from the same snapshot",
                ),
            ),
        )

    # ------------------------------------------------------------------ #
    def _refuse_another_tenant(self, sql: str, obligor_id: str, tenant: str) -> None:
        """403 for an obligor this warehouse holds under someone else, 404-shaped silence for one
        it does not hold at all. Asked only on the empty path, so an ordinary read costs nothing.
        """
        if self._query(sql, obligor_id=obligor_id, tenant=tenant):
            raise CrossTenantError(f"obligor {obligor_id!r} is not in tenant {tenant!r}")

    def _dataset(self) -> str:
        dataset = self._settings.metrics_dataset.strip()
        if not dataset:
            raise RuntimeError(
                f"{_DATASET_ENV} is not configured, so the portfolio feed has no warehouse to "
                "read. It refuses rather than returning an empty window: an empty window "
                "presents a stressed obligor as a clean one."
            )
        return dataset

    def _query(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        # The CONFIGURATION check runs before the SDK import, deliberately: an unconfigured
        # dataset is the more actionable of the two refusals, and an operator reading an
        # ImportError would go looking for a missing package rather than a missing variable.
        dataset = self._dataset()
        # Lazy import: every profile binds this adapter and must construct with no SDK present.
        from google.cloud import bigquery

        client = bigquery.Client()
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(name, _bq_type(value), value)
                for name, value in params.items()
            ]
        )
        job = client.query(sql.format(dataset=dataset), job_config=job_config)
        return [dict(row) for row in job.result()]


def _bq_type(value: Any) -> str:
    if isinstance(value, bool):  # pragma: no cover - no boolean parameters today
        return "BOOL"
    if isinstance(value, int):
        return "INT64"
    if isinstance(value, date):
        return "DATE"
    return "STRING"
