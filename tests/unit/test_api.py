"""API surface: verified-principal identity, fail-closed S2S, security headers, the route.

The client comes from the shared ``api_client`` fixture, which pins a loopback peer: the
app-object exposure guard refuses the unauthenticated local posture to any other peer, and
TestClient's default peer is the literal host "testclient".
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.fixtures import sample_cases

_TOKEN_ENV = "CREDITEWS_S2S_TOKEN"
_PERSONA = {"X-Dev-Persona": "auditor"}


def _body(obligor_id: str = sample_cases.ESCALATING_OBLIGOR, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "obligor_id": obligor_id,
        "as_of": sample_cases.AS_OF.isoformat(),
    }
    payload.update(extra)
    return payload


def _review(client: TestClient, **kwargs: object) -> dict[str, object]:
    resp = client.post("/v1/watchlist-review", json=_body(**kwargs), headers=_PERSONA)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


def test_the_review_uses_the_verified_principal_and_routes_the_escalation(
    api_client: TestClient,
) -> None:
    body = _review(api_client)
    assert body["proposed_grade"] == "substandard"
    assert body["band_grade"] == "special_mention", "the floor classified, not the score"
    assert body["requires_human_review"] is True
    # Rule R8: the proposal was routed, not merely flagged (see test_review_routing.py).
    assert body["review_ref"]
    assert body["required_approvals"] == 2


def test_the_response_states_that_no_grade_was_applied_rather_than_implying_it(
    api_client: TestClient,
) -> None:
    body = _review(api_client)
    assert body["grade_applied"] is False


def test_the_response_echoes_the_resolved_period_and_date(api_client: TestClient) -> None:
    """A stored answer must be self-describing: a reader never guesses which period was tested."""
    body = _review(api_client)
    assert body["as_of"] == sample_cases.AS_OF.isoformat()
    assert body["test_period"] == sample_cases.TEST_PERIOD


def test_an_empty_as_of_is_resolved_server_side_and_echoed(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/watchlist-review",
        json={"obligor_id": sample_cases.ESCALATING_OBLIGOR},
        headers=_PERSONA,
    )
    assert resp.status_code == 200
    assert resp.json()["as_of"], "the engine must always receive an explicit date"


def test_a_malformed_as_of_is_a_422_and_never_a_500(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/watchlist-review",
        json={"obligor_id": sample_cases.ESCALATING_OBLIGOR, "as_of": "last Tuesday"},
        headers=_PERSONA,
    )
    assert resp.status_code == 422


def test_a_clean_obligor_is_not_routed(api_client: TestClient) -> None:
    body = _review(api_client, obligor_id=sample_cases.ROUTINE_OBLIGOR)
    assert body["requires_human_review"] is False
    assert body["review_ref"] == ""
    assert body["effective_days_past_due"] == 0, "the materiality gate stopped the clock"


def test_an_obligor_under_another_tenant_is_403_and_never_404(api_client: TestClient) -> None:
    """The two statuses must not be usable to enumerate another bank's book."""
    resp = api_client.post(
        "/v1/watchlist-review", json=_body(sample_cases.FOREIGN_OBLIGOR), headers=_PERSONA
    )
    assert resp.status_code == 403


def test_an_unknown_obligor_is_404_and_never_a_default_pass_record(
    api_client: TestClient,
) -> None:
    resp = api_client.post(
        "/v1/watchlist-review", json=_body(sample_cases.UNKNOWN_OBLIGOR), headers=_PERSONA
    )
    assert resp.status_code == 404


def test_the_obligor_listing_is_read_only_and_tenant_scoped(api_client: TestClient) -> None:
    resp = api_client.get("/v1/obligors", headers=_PERSONA)
    assert resp.status_code == 200
    ids = [row["obligor_id"] for row in resp.json()]
    assert sample_cases.ESCALATING_OBLIGOR in ids
    assert sample_cases.FOREIGN_OBLIGOR not in ids, "another tenant's book leaked into the picker"


def test_the_request_schema_carries_no_actor_tenant_or_entitlement() -> None:
    """Identity is resolved, never accepted. A schema that carried an actor invites the bug."""
    from credit_portfolio_ews.api.schemas import WatchlistReviewRequest

    fields = set(WatchlistReviewRequest.model_fields)
    assert fields == {"obligor_id", "test_period", "as_of", "news_lookback_days"}


def test_unknown_persona_is_401(api_client: TestClient) -> None:
    resp = api_client.post("/v1/watchlist-review", json=_body(), headers={"X-Dev-Persona": "ghost"})
    assert resp.status_code == 401


def test_healthz_reports_profile_and_region(api_client: TestClient) -> None:
    body = api_client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["profile"] == "local"
    assert body["region"] == "asia-southeast1"


def test_healthz_states_the_provenance_the_ui_banner_renders(api_client: TestClient) -> None:
    """The service half of the banner contract (org decision, 2026-08-30).

    The UI must never infer either value. A console that read its runtime from
    ``window.location`` would be right until the deployment served through a proxy and
    wrong silently after that, so the service is asked and the service answers.
    """
    body = api_client.get("/healthz").json()
    assert body["runtime"] == "local"
    # This repo BINDS a generative port (memo drafting and media categorisation), so the banner
    # names what is bound rather than `no-model`: offline that is a deterministic stub, and a
    # reviewer approving a proposal is entitled to know which of the two they are reading.
    assert body["generator_model"] == "deterministic-offline-stub"


@pytest.mark.parametrize(
    ("profile", "expected"), [("local", "local"), ("gcp", "gcp"), ("onprem", "local")]
)
def test_the_runtime_follows_the_profile_and_onprem_is_not_gcp(profile: str, expected: str) -> None:
    """``onprem`` reads local, and that is the whole point of the profile.

    It runs on the adopter's own iron. Treating any non-local profile as "on GCP" would put
    the wrong sentence at the top of every page of the one deployment whose selling point is
    that it is not on GCP.
    """
    from credit_portfolio_ews.config import Settings

    assert Settings(profile=profile).runtime == expected


def test_the_managed_banner_names_the_pinned_model_off_the_binding() -> None:
    """Read off the BINDING, never a second settings string that could drift from it."""
    from credit_portfolio_ews.adapters.gcp.generation import _MODEL
    from credit_portfolio_ews.config import Settings

    assert Settings(profile="gcp").generator_model == _MODEL


def test_the_onprem_banner_says_the_seam_is_unbound_rather_than_naming_a_model() -> None:
    from credit_portfolio_ews.config import Settings

    assert Settings(profile="onprem").generator_model == "onprem-not-implemented"


def test_security_headers_present(api_client: TestClient) -> None:
    headers = api_client.get("/healthz").headers
    assert headers["Content-Security-Policy"] == "frame-ancestors 'self'"
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.fixture()
def token_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv(_TOKEN_ENV, "s3cret-service-token")
    yield "s3cret-service-token"


def test_s2s_endpoint_open_when_secret_unset(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_TOKEN_ENV, raising=False)
    assert api_client.post("/v1/audit/ping").status_code == 200


def test_s2s_endpoint_rejects_missing_token_when_enforced(
    api_client: TestClient, token_env: str
) -> None:
    assert api_client.post("/v1/audit/ping").status_code == 401


def test_s2s_endpoint_accepts_correct_token(api_client: TestClient, token_env: str) -> None:
    resp = api_client.post("/v1/audit/ping", headers={"Authorization": f"Bearer {token_env}"})
    assert resp.status_code == 200
