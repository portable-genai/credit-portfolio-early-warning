"""Local PortfolioFeedPort: the shipped obligor book, in DuckDB, over the warehouse's schema.

This used to serve an in-process dictionary, and that is the shape of blindness the sibling
repositories kept finding: a local profile that runs no SQL cannot disagree with the warehouse
about anything, so a schema the managed adapter could not query, a unit conversion applied twice,
or a tenancy probe with nothing to find all passed a green offline gate. The store here holds the
SAME tables in the SAME column order as ``infra/terraform/bigquery.tf`` and answers the SAME
statements ``adapters/gcp/portfolio_feed.py`` sends, so the two can be held against each other
rather than merely both working.

The cross-tenant refusal is the part that matters most. It is not a dictionary lookup any more:
an empty tenant-scoped read asks the store which tenant owns the id, exactly as the managed
adapter asks the warehouse, and the book ships a foreign obligor so that question has an answer.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from hex_service_kit.demobook import DuckDbStore

from ... import demo_book
from ...config import Settings
from ...domain.models import ArrearsSnapshot, SignalObservation
from ...ports.tenancy import CrossTenantError

#: The statements, in the managed adapter's own shape. Kept side by side with it on purpose:
#: two stores over one book and one column order can be compared, and a divergence in either
#: is a test failure rather than a surprise on a deployment.
_OBSERVATIONS_SQL = """
SELECT metric, value, period, as_of, unit, source, source_ref
FROM obligor_metrics
WHERE obligor_id = ? AND tenant = ? AND as_of <= ?
ORDER BY as_of DESC, period DESC, source_ref DESC
LIMIT ?
"""

_ARREARS_SQL = """
SELECT currency, drawn_amount, past_due_amount, days_past_due, source_ref, as_of
FROM obligor_servicing
WHERE obligor_id = ? AND tenant = ? AND as_of <= ?
ORDER BY as_of DESC
LIMIT 1
"""

_OBSERVATIONS_TENANCY_SQL = """
SELECT tenant FROM obligor_metrics WHERE obligor_id = ? AND tenant != ? LIMIT 1
"""

_ARREARS_TENANCY_SQL = """
SELECT tenant FROM obligor_servicing WHERE obligor_id = ? AND tenant != ? LIMIT 1
"""

#: The columns each SELECT above returns, in order, so a row tuple becomes a mapping the
#: shared row-to-domain functions read. Named here rather than derived from the SQL text: the
#: contract test holds these against the managed adapter's declared read set, and a mismatch
#: is two stores answering different shapes from one book.
_OBSERVATION_COLUMNS = ("metric", "value", "period", "as_of", "unit", "source", "source_ref")
_ARREARS_COLUMNS = (
    "currency",
    "drawn_amount",
    "past_due_amount",
    "days_past_due",
    "source_ref",
    "as_of",
)

#: Rows per period the window may carry, matching the managed adapter, so ``periods`` bounds
#: the read on both sides identically.
_ROWS_PER_PERIOD = 32


class LocalPortfolioFeed:
    """Serve the shipped obligor book from DuckDB, tenant-scoped, refusing across tenants."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._store = DuckDbStore(demo_book.BOOK, settings.book_path)

    def observations(
        self, obligor_id: str, *, tenant: str, as_of: date, periods: int = 8
    ) -> tuple[SignalObservation, ...]:
        rows = self._select(
            _OBSERVATIONS_SQL,
            _OBSERVATION_COLUMNS,
            [obligor_id, tenant, as_of, periods * _ROWS_PER_PERIOD],
        )
        if not rows:
            self._refuse_another_tenant(_OBSERVATIONS_TENANCY_SQL, obligor_id, tenant)
        return tuple(demo_book.to_observation(row) for row in rows)

    def arrears(self, obligor_id: str, *, tenant: str, as_of: date) -> ArrearsSnapshot | None:
        rows = self._select(
            _ARREARS_SQL,
            _ARREARS_COLUMNS,
            [obligor_id, tenant, as_of],
        )
        if not rows:
            self._refuse_another_tenant(_ARREARS_TENANCY_SQL, obligor_id, tenant)
            return None
        return demo_book.to_arrears(rows[0], obligor_id)

    def close(self) -> None:
        self._store.close()

    # ------------------------------------------------------------------ #
    def _refuse_another_tenant(self, sql: str, obligor_id: str, tenant: str) -> None:
        """403 for an obligor the book holds under someone else, silence for one it never held.

        The same decision the managed adapter makes, asked of the same book. Offline this used
        to be a dictionary membership test, which proved the rule about a Python object rather
        than about the store the rule exists to police.
        """
        if self._store.connection.execute(sql, [obligor_id, tenant]).fetchall():
            raise CrossTenantError(f"obligor {obligor_id!r} is not in tenant {tenant!r}")

    def _select(
        self, sql: str, columns: tuple[str, ...], params: list[Any]
    ) -> list[dict[str, Any]]:
        rows = self._store.connection.execute(sql, params).fetchall()
        return [dict(zip(columns, row, strict=True)) for row in rows]
