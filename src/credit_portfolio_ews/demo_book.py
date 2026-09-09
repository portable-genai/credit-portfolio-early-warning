"""The shipped demo book: a fictional obligor warehouse, served the same way on both sides.

The rows live as newline-delimited JSON under ``credit_portfolio_ews/data/demo_book/``, one
file per BigQuery table and in that table's column order, so one set of files feeds the DuckDB
store the offline profiles read, the loader that fills the managed dataset, the fixture estate
the demo and the eval read, and the tests. The reading, the overwrite guard and the tenant rule
come from :mod:`hex_service_kit.demobook`; what is here is about THIS system.

Two things this repository was hiding, neither visible to a green offline gate, are pinned by
``tests/contract/test_demo_book.py``:

**The two stores disagreed about units by a factor of a hundred.** ``infra/terraform`` declared
``drawn_amount`` and ``past_due_amount`` as ``INTEGER`` and its comment called them minor units,
while the managed adapter multiplies whatever it reads by a hundred to reach minor units
(``adapters/gcp/portfolio_feed.py``). Both cannot be true. The adapter is what runs, and its own
test double has always answered ``drawn_amount: 1000.0`` -- a decimal major amount -- so the
schema was the half that was wrong: a warehouse column holding a currency amount is ``NUMERIC``,
and an ``INTEGER`` there cannot hold cents at all. Left alone, the absolute leg of the arrears
materiality gate would have run against figures a hundred times too large on the deployment and
classified obligors the laptop calls immaterial. The book is MAJOR units, the conversion stays at
the boundary in both adapters, and a test now holds the two conversions equal.

**The other tenant owned no rows.** ``ports/tenancy.py`` requires 403 rather than an empty
window for an obligor held under another tenant, and the managed adapter implements it by asking
which tenant owns the id. The book shipped no row for anyone but ``demo-bank``, so on a
deployment that probe could never find one and the refusal had nothing to be about: the control
was proved offline against a Python dictionary and would have been dead in the warehouse it
exists to police. ``obl-omega-999`` now carries a window and a snapshot of its own, and
:data:`CROSS_TENANT` keeps the loader from folding it into the deployment's tenant.

Everything is fictional. See ``data/demo_book/README.md``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from hex_service_kit.demobook import BookError, NdjsonBook, Table, as_date

from .domain.kernel import Citation
from .domain.models import ArrearsSnapshot, SignalObservation

#: The tenant the shipped rows belong to, and the one other tenant the 403 path needs.
SHIPPED_TENANT = "demo-bank"
OTHER_TENANT = "other-bank"

#: Rows whose tenant the loader must NOT fold into the deployment's own. Stamping the foreign
#: obligor with the hosted domain would delete the only evidence the cross-tenant refusal has
#: anything to refuse, on the one surface where it has never been exercised.
CROSS_TENANT: dict[str, str] = {"obl-omega-999": "-other"}

#: The metrics the signal rules read. A window short of one of these is a file the coverage
#: rule must report on rather than a file that scores well.
REQUIRED_METRICS = (
    "net_debt_to_ebitda",
    "dscr",
    "current_ratio",
    "ebitda",
    "revolver_utilisation_pct",
    "collections_concentration_pct",
)

OBLIGOR_METRICS = Table(
    name="obligor_metrics",
    columns=(
        "obligor_id",
        "tenant",
        "metric",
        "value",
        "period",
        "as_of",
        "unit",
        "source",
        "source_ref",
    ),
    types={
        "obligor_id": "TEXT NOT NULL",
        "tenant": "TEXT NOT NULL",
        "metric": "TEXT NOT NULL",
        "value": "DOUBLE NOT NULL",
        "period": "TEXT NOT NULL",
        "as_of": "DATE NOT NULL",
        "unit": "TEXT",
        "source": "TEXT NOT NULL",
        "source_ref": "TEXT NOT NULL",
    },
    primary_key=("obligor_id", "tenant", "metric", "period"),
    date_columns=frozenset({"as_of"}),
)

OBLIGOR_SERVICING = Table(
    name="obligor_servicing",
    columns=(
        "obligor_id",
        "tenant",
        "currency",
        # MAJOR units, decimal. The adapters convert to minor at the boundary, on both sides,
        # so the domain never sees a currency float. See the module docstring.
        "drawn_amount",
        "past_due_amount",
        "days_past_due",
        "as_of",
        "source_ref",
    ),
    types={
        "obligor_id": "TEXT NOT NULL",
        "tenant": "TEXT NOT NULL",
        "currency": "TEXT NOT NULL",
        "drawn_amount": "DOUBLE NOT NULL",
        "past_due_amount": "DOUBLE NOT NULL",
        "days_past_due": "BIGINT NOT NULL",
        "as_of": "DATE NOT NULL",
        "source_ref": "TEXT NOT NULL",
    },
    primary_key=("obligor_id", "tenant", "as_of"),
    date_columns=frozenset({"as_of"}),
)

TABLES = (OBLIGOR_METRICS, OBLIGOR_SERVICING)

BOOK = NdjsonBook("credit_portfolio_ews.data.demo_book", TABLES)


def minor(amount: Any) -> int:
    """A major-unit warehouse amount to minor units. THE conversion, used by both adapters.

    Written once and imported by both the managed adapter and the local store, because a
    conversion implemented twice is a conversion that eventually differs, and the difference
    here is a factor of a hundred on the leg that decides whether arrears are material at all.
    """
    return int(round(float(amount or 0.0) * 100))


def validate() -> None:
    """The book's own invariants, on top of the shape the kit checks.

    Every rule here is something the early-warning engine depends on and a hand edit can break
    without any other test going red: a metric window that cannot support a change rule, an
    obligor past due more than it ever drew, or a foreign obligor with no rows, which is the
    cross-tenant refusal quietly losing its subject.
    """
    BOOK.validate()
    metrics = BOOK.rows("obligor_metrics")
    servicing = BOOK.rows("obligor_servicing")
    if not metrics or not servicing:
        raise BookError("the book ships no metrics or no servicing rows")

    seen: set[tuple[str, str, str]] = set()
    for row in metrics:
        where = f"{row['obligor_id']}/{row['metric']}/{row['period']}"
        key = (str(row["obligor_id"]), str(row["metric"]), str(row["period"]))
        if key in seen:
            raise BookError(f"{where} is spread twice; the window would read a duplicate period")
        seen.add(key)
        if not str(row["source_ref"]).strip():
            raise BookError(f"{where} has no source_ref, so no figure it feeds could be cited")
        if as_date(row["as_of"]) is None:
            raise BookError(f"{where} has no as_of, so the window cannot be ordered")

    for row in servicing:
        where = str(row["obligor_id"])
        drawn, past_due = float(row["drawn_amount"]), float(row["past_due_amount"])
        if drawn <= 0:
            raise BookError(f"{where} has drawn nothing, so no arrears against it can be material")
        if past_due < 0:
            raise BookError(f"{where} is past due a negative amount")
        if past_due > drawn:
            raise BookError(f"{where} is past due more than it ever drew")
        if int(row["days_past_due"]) < 0:
            raise BookError(f"{where} has negative days past due")
        if not str(row["currency"]).strip():
            raise BookError(f"{where} has no currency, so its amounts mean nothing")

    tenants = {str(row["tenant"]) for row in metrics} | {str(row["tenant"]) for row in servicing}
    if OTHER_TENANT not in tenants:
        raise BookError(
            f"no rows belong to {OTHER_TENANT!r}. The cross-tenant refusal asks the warehouse "
            "which tenant owns an id; with one tenant in the book that probe can never find "
            "one and the 403 path is dead on the deployment."
        )

    windows: dict[str, set[str]] = {}
    for row in metrics:
        if str(row["tenant"]) == SHIPPED_TENANT:
            windows.setdefault(str(row["obligor_id"]), set()).add(str(row["metric"]))
    thin = {obligor for obligor, found in windows.items() if not found}
    if thin:
        raise BookError(f"obligors with no metric at all: {sorted(thin)}")
    if not any(set(REQUIRED_METRICS) <= found for found in windows.values()):
        raise BookError(
            "no obligor carries the full required metric set, so the coverage rule has no "
            "complete file to contrast a thin one against"
        )


# --------------------------------------------------------------------------- #
# Row to domain
# --------------------------------------------------------------------------- #
def to_observation(row: dict[str, Any]) -> SignalObservation:
    """One warehouse row as the engine's normalised observation, citation and all."""
    source_ref = str(row.get("source_ref") or f"metric:{row['metric']}")
    return SignalObservation(
        metric=str(row["metric"]),
        value=float(row["value"]),
        period=str(row["period"]),
        as_of=as_date(row["as_of"]) or date.min,
        unit=str(row.get("unit") or ""),
        source=str(row.get("source") or ""),
        source_ref=source_ref,
        citations=(
            Citation(
                source_id=source_ref,
                title="Obligor metrics view",
                snippet=f"{row['metric']} for {row['period']}",
            ),
        ),
    )


def to_arrears(row: dict[str, Any], obligor_id: str) -> ArrearsSnapshot:
    """One servicing row as the snapshot the materiality gate runs on, in MINOR units."""
    source_ref = str(row.get("source_ref") or f"servicing:{obligor_id}")
    return ArrearsSnapshot(
        obligor_id=obligor_id,
        as_of=as_date(row["as_of"]) or date.min,
        currency=str(row.get("currency") or ""),
        drawn_amount_minor=minor(row.get("drawn_amount")),
        past_due_amount_minor=minor(row.get("past_due_amount")),
        days_past_due=int(row.get("days_past_due") or 0),
        source_ref=source_ref,
        citations=(
            Citation(
                source_id=source_ref,
                title="Servicing arrears snapshot",
                snippet="drawn and past-due balances from the same snapshot",
            ),
        ),
    )
