"""403 and never 404, in the OFFLINE family and in the MANAGED one, for the same three cases.

``ports/tenancy.py`` says the offline adapters obey the same rule as the managed ones, "so the
offline gate proves the authorisation rather than assuming it". For the portfolio feed that was
an assumption: the offline adapter raised ``CrossTenantError`` and the managed one filtered by
tenant in the WHERE clause and answered an EMPTY window, which is exactly the membership oracle
the rule exists to refuse. Nothing was leaking on the served path, because
``WatchlistReviewService`` reads the grade registry first and that adapter does refuse, but an
ordering is not a control: reorder those two reads and the refusal disappears with no test red.

The behavioural-parity suite makes ONE canonical call per port, which is the right shape for
"does this family answer at all" and cannot see this. So the refusal gets its own module, and it
covers three cases that must stay distinguishable: held for you, held for somebody else, held
nowhere.

The managed adapter is driven over a stubbed warehouse. BigQuery, the SQL dialect and the client
are not what is under test; what the adapter DECIDES when a tenant-scoped read comes back empty
is, and that decision runs with no cloud SDK installed.
"""

from __future__ import annotations

from typing import Any

import pytest

from credit_portfolio_ews.adapters.gcp.portfolio_feed import (
    CloudPortfolioFeed,
)
from credit_portfolio_ews.adapters.local import (
    _fixtures,
)
from credit_portfolio_ews.adapters.local.portfolio_feed import (
    LocalPortfolioFeed,
)
from credit_portfolio_ews.config import (
    Settings,
)
from credit_portfolio_ews.ports.tenancy import (
    CrossTenantError,
)

from tests.conftest import local_settings
from tests.fixtures import sample_cases

#: Who the stub warehouse holds each obligor for. The third id is held by nobody.
_OWNERS = {"obl-ours-001": sample_cases.TENANT, "obl-theirs-002": sample_cases.OTHER_TENANT}
_HELD_NOWHERE = "obl-nobody-000"

_METRIC_ROW = {
    "metric": "dscr",
    "value": 1.4,
    "period": "FY2026H1",
    "as_of": sample_cases.AS_OF,
    "unit": "ratio",
    "source": "spreading",
    "source_ref": "metric:1",
}

_SERVICING_ROW = {
    "currency": "SGD",
    "drawn_amount": 1000.0,
    "past_due_amount": 0.0,
    "days_past_due": 0,
    "source_ref": "servicing:1",
    "as_of": sample_cases.AS_OF,
}


class _StubWarehouse(CloudPortfolioFeed):
    """The managed adapter's own logic, answering its own SQL from a dict."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.statements: list[str] = []

    def _query(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        self.statements.append(sql)
        obligor, tenant = str(params["obligor_id"]), str(params["tenant"])
        owner = _OWNERS.get(obligor)
        if "tenant != @tenant" in sql:
            return [{"tenant": owner}] if owner is not None and owner != tenant else []
        if owner != tenant:
            return []
        return [dict(_METRIC_ROW) if "obligor_metrics" in sql else dict(_SERVICING_ROW)]


def _managed() -> _StubWarehouse:
    return _StubWarehouse(local_settings(profile="gcp"))


def _read(feed: Any, obligor_id: str) -> tuple[Any, Any]:
    return (
        feed.observations(obligor_id, tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF),
        feed.arrears(obligor_id, tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF),
    )


# --------------------------------------------------------------------------------------- #
# The managed family
# --------------------------------------------------------------------------------------- #
def test_the_managed_feed_answers_for_an_obligor_the_tenant_owns() -> None:
    """The green half, so the refusals below are not simply an adapter that raises at anything."""
    observations, arrears = _read(_managed(), "obl-ours-001")
    assert [row.metric for row in observations] == ["dscr"]
    assert arrears is not None
    assert arrears.days_past_due == 0


def test_the_managed_feed_asks_nothing_extra_on_the_ordinary_path() -> None:
    """The tenancy probe is on the EMPTY path only, so a served read still costs one statement."""
    feed = _managed()
    feed.observations("obl-ours-001", tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF)
    assert len(feed.statements) == 1


@pytest.mark.parametrize("method", ["observations", "arrears"])
def test_the_managed_feed_refuses_another_tenants_obligor_rather_than_answering_empty(
    method: str,
) -> None:
    feed = _managed()
    with pytest.raises(CrossTenantError):
        getattr(feed, method)(
            "obl-theirs-002", tenant=sample_cases.TENANT, as_of=sample_cases.AS_OF
        )


def test_the_managed_feed_stays_silent_for_an_obligor_held_nowhere() -> None:
    """404-shaped, and it must NOT become a 403: the two statuses carry different information."""
    observations, arrears = _read(_managed(), _HELD_NOWHERE)
    assert observations == ()
    assert arrears is None


# --------------------------------------------------------------------------------------- #
# The offline family, over the shared estate, on the same three cases
# --------------------------------------------------------------------------------------- #
def test_the_offline_feed_makes_the_same_three_distinctions() -> None:
    feed = LocalPortfolioFeed(local_settings())
    owned, arrears = _read(feed, sample_cases.ESCALATING_OBLIGOR)
    assert owned and arrears is not None

    assert _fixtures.belongs_to_another_tenant(sample_cases.FOREIGN_OBLIGOR, sample_cases.TENANT)
    with pytest.raises(CrossTenantError):
        _read(feed, sample_cases.FOREIGN_OBLIGOR)

    assert _read(feed, _HELD_NOWHERE) == ((), None)
