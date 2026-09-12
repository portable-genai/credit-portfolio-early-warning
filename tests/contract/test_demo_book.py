"""The demo book: one obligor warehouse, served the same way on the laptop and the deployment.

Pinned here, and each was watched failing first:

* **the two stores disagreed about units by a factor of a hundred.** The Terraform declared
  ``drawn_amount`` and ``past_due_amount`` ``INTEGER`` and called them minor units; the managed
  adapter multiplies whatever it reads by a hundred to reach minor units. Both cannot be true,
  and the difference lands on the ABSOLUTE leg of the arrears materiality gate, which is what
  decides whether the past-due clock starts at all. So the conversion is now one function used
  by both adapters, and the test below runs the same warehouse row through both;
* **the other tenant owned no rows.** ``ports/tenancy.py`` requires 403 rather than an empty
  window for an obligor held by somebody else, and the managed adapter implements that by asking
  the warehouse which tenant owns the id. The book shipped one tenant, so on a deployment that
  probe could never find a row and the refusal had nothing to be about. It was proved offline
  against a Python dictionary, on a path that no longer exists;
* the managed adapter's read set is declared and every column in it is one the Terraform
  declares, and the book ships exactly those columns, so a load cannot be short a field;
* the set held against the Terraform is ``load_order()`` -- the set the LOADER writes, which
  includes the manifest -- rather than the repository's own ``TABLES``. A sibling repository
  shipped a manifest missing from its schema and three green gates could not see it, because the
  guard iterated the wrong set.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import date

import pytest

from credit_portfolio_ews import demo_book
from credit_portfolio_ews.adapters.gcp import portfolio_feed as managed
from credit_portfolio_ews.adapters.local.portfolio_feed import LocalPortfolioFeed
from credit_portfolio_ews.config import Settings
from credit_portfolio_ews.ports.tenancy import CrossTenantError

from tests import REPO_ROOT
from tests.fixtures import sample_cases

_TF = REPO_ROOT / "infra" / "terraform" / "bigquery.tf"


def _settings() -> Settings:
    return dataclasses.replace(
        Settings.load(), profile="local", audit_path=":memory:", book_path=":memory:"
    )


@pytest.fixture
def feed() -> LocalPortfolioFeed:
    adapter = LocalPortfolioFeed(_settings())
    yield adapter
    adapter.close()


# --------------------------------------------------------------------------- #
# The shipped rows
# --------------------------------------------------------------------------- #
def test_the_shipped_book_is_internally_consistent() -> None:
    demo_book.validate()
    assert len(demo_book.BOOK.rows("obligor_metrics")) == 136
    assert len(demo_book.BOOK.rows("obligor_servicing")) == 12
    assert demo_book.BOOK.manifest()["fictional"] is True


@pytest.mark.parametrize(
    ("table", "field", "value", "message"),
    [
        ("obligor_servicing", "drawn_amount", 0.0, "drawn nothing"),
        ("obligor_servicing", "past_due_amount", -1.0, "past due a negative amount"),
        ("obligor_servicing", "past_due_amount", 10**12, "past due more than it ever drew"),
        ("obligor_servicing", "days_past_due", -1, "negative days past due"),
        ("obligor_servicing", "currency", "", "no currency"),
        ("obligor_metrics", "source_ref", "", "no source_ref"),
    ],
)
def test_the_book_refuses_a_row_the_engine_could_not_assess(
    monkeypatch: pytest.MonkeyPatch, table: str, field: str, value: object, message: str
) -> None:
    """Each is something the early-warning engine depends on and a hand edit breaks silently."""
    real = demo_book.BOOK.rows

    def broken(name: str):  # type: ignore[no-untyped-def]
        rows = real(name)
        return [dict(rows[0], **{field: value}), *rows[1:]] if name == table else rows

    monkeypatch.setattr(demo_book.BOOK, "rows", broken)
    with pytest.raises(demo_book.BookError, match=message):
        demo_book.validate()


def test_a_book_with_one_tenant_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The foreign obligor is the cross-tenant refusal's only subject on the warehouse."""
    real = demo_book.BOOK.rows

    def one_tenant(name: str):  # type: ignore[no-untyped-def]
        return [row for row in real(name) if row.get("tenant") != demo_book.OTHER_TENANT]

    monkeypatch.setattr(demo_book.BOOK, "rows", one_tenant)
    with pytest.raises(demo_book.BookError, match="the 403 path is dead"):
        demo_book.validate()


def test_a_metric_spread_twice_for_one_period_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicated period makes a consecutive-period rule read the same quarter twice."""
    real = demo_book.BOOK.rows

    def duplicated(name: str):  # type: ignore[no-untyped-def]
        rows = real(name)
        return [rows[0], *rows] if name == "obligor_metrics" else rows

    monkeypatch.setattr(demo_book.BOOK, "rows", duplicated)
    with pytest.raises(demo_book.BookError, match="spread twice"):
        demo_book.validate()


# --------------------------------------------------------------------------- #
# The managed schema
# --------------------------------------------------------------------------- #
def _terraform_tables() -> dict[str, set[str]]:
    assert _TF.exists(), "infra/terraform/bigquery.tf is missing; nothing creates the dataset"
    text = _TF.read_text(encoding="utf-8")
    blocks = re.findall(
        r'resource\s+"google_bigquery_table"\s+"\w+"\s*\{(.*?)\n\}', text, flags=re.DOTALL
    )
    assert blocks, "no google_bigquery_table blocks found; the regex or the file moved"
    out: dict[str, set[str]] = {}
    for block in blocks:
        table_id = re.search(r'table_id\s*=\s*"(\w+)"', block)
        assert table_id is not None
        out[table_id.group(1)] = set(re.findall(r'name\s*=\s*"(\w+)"', block))
    return out


def _terraform_types() -> dict[tuple[str, str], str]:
    text = _TF.read_text(encoding="utf-8")
    blocks = re.findall(
        r'resource\s+"google_bigquery_table"\s+"\w+"\s*\{(.*?)\n\}', text, flags=re.DOTALL
    )
    out: dict[tuple[str, str], str] = {}
    for block in blocks:
        table_id = re.search(r'table_id\s*=\s*"(\w+)"', block)
        assert table_id is not None
        for name, kind in re.findall(r'name\s*=\s*"(\w+)",\s*type\s*=\s*"(\w+)"', block):
            out[(table_id.group(1), name)] = kind
    return out


def test_the_managed_adapter_reads_only_columns_the_terraform_declares() -> None:
    declared = _terraform_tables()
    for table, columns in managed.SELECTED_COLUMNS.items():
        assert table in declared, f"{table!r} is not a Terraform table"
        undeclared = sorted(set(columns) - declared[table])
        assert not undeclared, f"{table} reads columns Terraform never declares: {undeclared}"


def test_the_book_and_the_terraform_declare_the_same_columns() -> None:
    """``load_order()``, so the manifest the loader writes is held too.

    ``TABLES`` is this repository's own tables and the loader writes one more: the manifest,
    stamped last because it records the load that wrote the others. The loader creates nothing,
    so a manifest missing from the Terraform is a load that exits before its first row.
    """
    declared = _terraform_tables()
    for table in demo_book.BOOK.load_order():
        assert table.name in declared, f"the book ships {table.name} and Terraform does not"
        book_columns, tf_columns = sorted(table.columns), sorted(declared[table.name])
        assert book_columns == tf_columns, (
            f"{table.name}: book {book_columns} vs terraform {tf_columns}"
        )


def test_the_currency_columns_are_exact_decimals_rather_than_integers() -> None:
    """An INTEGER money column cannot hold cents, and said the opposite of what the adapter does.

    The adapter multiplies what it reads by a hundred to reach minor units, so the warehouse
    holds MAJOR units. Declared INTEGER, the column could neither hold a cent nor agree with
    the comment that described it as minor units, and the absolute materiality leg would have
    run a hundred times out on the deployment.
    """
    types = _terraform_types()
    for column in ("drawn_amount", "past_due_amount"):
        assert types[("obligor_servicing", column)] == "NUMERIC", (
            f"obligor_servicing.{column} must be NUMERIC: it holds a major-unit currency amount"
        )


# --------------------------------------------------------------------------- #
# The two stores, over one book
# --------------------------------------------------------------------------- #
def test_both_adapters_convert_a_warehouse_amount_to_the_same_minor_figure() -> None:
    """The conversion is ONE function, and this is the row that proves the two agree.

    Watched failing against the old ``_minor`` defined separately in the managed adapter and a
    local adapter that did no conversion at all, which is how a hundredfold difference survived
    a green gate: the offline store never converted anything because it never held a warehouse
    row.
    """
    row = {
        "currency": "SGD",
        "drawn_amount": 7_800_000.0,
        "past_due_amount": 96_400.5,
        "days_past_due": 41,
        "as_of": "2026-06-30",
        "source_ref": "servicing:test",
    }
    snapshot = demo_book.to_arrears(row, "obl-test-000")
    assert snapshot.drawn_amount_minor == 780_000_000
    assert snapshot.past_due_amount_minor == 9_640_050
    assert managed._minor(row["past_due_amount"]) == snapshot.past_due_amount_minor


def test_the_store_serves_the_shipped_window_newest_first(feed: LocalPortfolioFeed) -> None:
    observations = feed.observations(
        sample_cases.ESCALATING_OBLIGOR, tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF
    )
    assert observations, "the escalating obligor has no metric window to escalate on"
    ordered = [(row.as_of, row.period, row.source_ref) for row in observations]
    assert ordered == sorted(ordered, reverse=True)
    assert all(row.citations for row in observations), "a figure must cite the row it came from"


def test_the_store_answers_the_arrears_snapshot_in_minor_units(
    feed: LocalPortfolioFeed,
) -> None:
    snapshot = feed.arrears(
        sample_cases.ESCALATING_OBLIGOR, tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF
    )
    assert snapshot is not None
    assert snapshot.past_due_amount_minor > 0
    assert snapshot.drawn_amount_minor >= snapshot.past_due_amount_minor
    assert snapshot.currency == "SGD"


def test_the_store_refuses_another_tenants_obligor_from_the_warehouse_itself(
    feed: LocalPortfolioFeed,
) -> None:
    """403 and never 404, decided by asking the store who owns the id -- not a dict lookup."""
    with pytest.raises(CrossTenantError):
        feed.observations(
            sample_cases.FOREIGN_OBLIGOR, tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF
        )
    with pytest.raises(CrossTenantError):
        feed.arrears(
            sample_cases.FOREIGN_OBLIGOR, tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF
        )


def test_an_obligor_held_nowhere_is_silence_rather_than_a_refusal(
    feed: LocalPortfolioFeed,
) -> None:
    """The two statuses carry different information and must stay distinguishable."""
    assert (
        feed.observations(
            sample_cases.UNKNOWN_OBLIGOR, tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF
        )
        == ()
    )
    assert (
        feed.arrears(
            sample_cases.UNKNOWN_OBLIGOR, tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF
        )
        is None
    )


def test_the_window_stops_at_the_as_of_date_rather_than_reading_the_future(
    feed: LocalPortfolioFeed,
) -> None:
    """A demo pinned to a clock empties as it ages; this one is measured from its own date."""
    early = feed.observations(
        sample_cases.ESCALATING_OBLIGOR, tenant=sample_cases.TENANT, as_of=date(2026, 3, 31)
    )
    full = feed.observations(
        sample_cases.ESCALATING_OBLIGOR, tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF
    )
    assert 0 < len(early) < len(full)
    assert all(row.as_of <= date(2026, 3, 31) for row in early)


# --------------------------------------------------------------------------- #
# The key the dataset stamps onto every table it creates
# --------------------------------------------------------------------------- #
# Watched failing first, on a copy of bigquery.tf with one table's block deleted: the per-table
# assertion names the table, and the count assertion catches a table added later with no block
# at all.
_TABLE_BLOCK = re.compile(r'resource\s+"google_bigquery_table"\s+"(\w+)"\s*\{(.*?)\n\}', re.DOTALL)
_TABLE_KEY = re.compile(r"\n\s*encryption_configuration\s*\{[^}]*?kms_key_name\s*=\s*([^\s#]+)")
_ANY_TABLE_BLOCK = re.compile(r"\n\s*encryption_configuration\s*\{")


def _dataset_default_key() -> str:
    """The key the dataset's ``default_encryption_configuration`` names."""
    block = re.search(
        r"default_encryption_configuration\s*\{(.*?)\n  \}",
        _TF.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    assert block is not None, "the dataset declares no default_encryption_configuration"
    key = re.search(r"kms_key_name\s*=\s*([^\s#]+)", block.group(1))
    assert key is not None, "the dataset's default_encryption_configuration names no key"
    return key.group(1)


def test_every_table_declares_the_key_the_dataset_would_stamp_on_it() -> None:
    """An inherited CMEK key is a REPLACEMENT waiting to happen, and a replaced table is empty.

    The dataset's ``default_encryption_configuration`` makes BigQuery stamp that key onto every
    table it creates in the dataset, so the live table carries an ``encryption_configuration``
    whether or not the Terraform declares one. Terraform then reads the undeclared block as a
    REMOVAL, and removing an encryption configuration FORCES REPLACEMENT: the table is destroyed
    and recreated, and a recreated table holds no rows. Proved by execution against a sibling
    deployment on 2026-09-12, where every loaded table planned as ``must be replaced`` with
    ``encryption_configuration { # forces replacement }`` as the cause.

    CMEK cascades in BigQuery's model and not in Terraform's, which is why the key is named
    twice, and why nothing but a check like this notices when it is named once.
    """
    text = _TF.read_text(encoding="utf-8")
    expected = _dataset_default_key()
    blocks = _TABLE_BLOCK.findall(text)
    assert blocks, "no google_bigquery_table blocks found; the regex or the file moved"

    for name, block in blocks:
        declared = _TABLE_KEY.search(block)
        assert declared is not None, (
            f"google_bigquery_table.{name} declares no encryption_configuration. The dataset "
            "stamps its key onto the table anyway, so the next plan reads the server-set block "
            "as a removal and REPLACES the table, which destroys every row it holds."
        )
        assert declared.group(1) == expected, (
            f"google_bigquery_table.{name} names {declared.group(1)} where the dataset stamps "
            f"{expected}. A table keyed differently from the dataset default is still a "
            "replacement at the next plan."
        )

    # The count is the half that catches a table added LATER with no block at all: iterating the
    # tables found cannot fail over a table nobody declared a key for if nobody looks at how many
    # keys were declared.
    assert len(_ANY_TABLE_BLOCK.findall(text)) == len(blocks), (
        f"{len(blocks)} google_bigquery_table resources and "
        f"{len(_ANY_TABLE_BLOCK.findall(text))} table-level encryption_configuration blocks; "
        "every table needs exactly one, naming the dataset's key."
    )
