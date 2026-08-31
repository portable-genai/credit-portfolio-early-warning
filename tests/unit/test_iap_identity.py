"""The IAP verifier, branch by branch, with NO cloud SDK: the adapter's own half of the claim.

This adapter is the one that declares
``VERIFIED`` (see ``ports/identity.py``), and that declaration is the
single flag the exposure guard reads before it lets the process bind every interface. Leaving
it the one adapter with NO tests at all is how three defects sit in three lines of it while the
whole gate stays green: ``resolve`` carrying ``# pragma: no cover - needs live GCP`` and a suite
exercising only the header-absent branch prove nothing about the branch that matters.

    claims = id_token.verify_token(assertion, ga_requests.Request())

1. **no ``audience=``.** google-auth documents ``audience=None`` as "the audience is not
   verified". ANY Google-signed OIDC ID token, from any project or any application, was accepted
   and its ``email`` became the verified subject.
2. **no ``certs_url=``.** The default is the OAuth2 federated key set, not the set IAP signs
   with, so the signature check was against the wrong keys.
3. **no ``try``.** ``google.auth.exceptions.MalformedError`` is a ``ValueError``, not an
   ``IdentityError``, so it escaped ``get_principal`` and FastAPI answered a bare 500. Proved
   over the wire: ``X-Goog-IAP-JWT-Assertion: not-a-jwt`` from a LAN peer, twice, once with
   google-auth installed and once without.

Everything here runs with the google modules FAKED or BLOCKED, so it needs no cloud SDK, no
project and no network, and it runs in every rendered repo's ``make gate``. What a fake verifier
cannot prove is that the REAL verifier rejects a wrong audience, an expired token or a signature
from the wrong key; that is ``tests/unit/test_iap_crypto_matrix.py``, which mints assertions with
a locally generated key and runs google-auth over them for real.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import federation as kit_federation
from hex_service_kit.identity import IdentityError
from hex_service_kit.netdefaults import ConfiguredEmptyError

from credit_portfolio_ews.adapters.gcp.identity import (
    _AUDIENCE_ENV,
    _IAP_ASSERTION_HEADER,
    _IAP_ISSUER,
    _IAP_KEYS_URL,
    IapAudienceUnconfiguredError,
    IapIdentityAdapter,
    IapVerifierUnavailableError,
)
from credit_portfolio_ews.config import Settings
from credit_portfolio_ews.ports.identity import (
    VERIFIED,
    EndUserAuthUnavailableError,
    declared_end_user_auth,
)

from tests.conftest import is_blocked_sdk
from tests.fixtures import sample_cases

#: A configured audience: the IAP-protected resource, obviously fictional.
AUDIENCE = "/projects/000000000000/global/backendServices/1111111111111111111"

#: The claim set a real IAP assertion carries once verified.
GOOD_CLAIMS: dict[str, Any] = {
    "iss": _IAP_ISSUER,
    "sub": "accounts.google.com:100000000000000000001",
    "email": "analyst@bank.example",
    "hd": "bank.example",
}

_PROFILE_ENV = "CREDITEWS_PROFILE"
_SETTINGS_ENV = "CREDITEWS_SETTINGS"

#: The API module, named once so no line's length depends on the rendered package name.
_API_MODULE = "credit_portfolio_ews.api.app"


# --------------------------------------------------------------------------------------- #
# A fake google-auth: it records exactly what the adapter passed, and raises what we tell it.
# --------------------------------------------------------------------------------------- #
def install_fake_google(
    monkeypatch: pytest.MonkeyPatch,
    outcome: dict[str, Any] | Exception,
    captured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Put a fake ``google.oauth2.id_token`` on ``sys.modules`` and return the capture dict.

    The signature is keyword-only for ``audience`` and ``certs_url`` DELIBERATELY: the defect
    was calling ``verify_token`` without either, and a fake that accepted them positionally (or
    defaulted them) would still be satisfied by the defective call.
    """
    seen: dict[str, Any] = captured if captured is not None else {}

    def verify_token(
        assertion: str,
        request: object,
        *,
        audience: str,
        certs_url: str,
    ) -> dict[str, Any]:
        seen.update(assertion=assertion, request=request, audience=audience, certs_url=certs_url)
        if isinstance(outcome, Exception):
            raise outcome
        return dict(outcome)

    google = ModuleType("google")
    auth = ModuleType("google.auth")
    transport = ModuleType("google.auth.transport")
    oauth2 = ModuleType("google.oauth2")
    id_token = ModuleType("google.oauth2.id_token")

    class Request:
        """Stands in for ``google.auth.transport.requests.Request``; never called."""

    transport.requests = SimpleNamespace(Request=Request)  # type: ignore[attr-defined]
    id_token.verify_token = verify_token  # type: ignore[attr-defined]
    google.auth = auth  # type: ignore[attr-defined]
    google.oauth2 = oauth2  # type: ignore[attr-defined]
    auth.transport = transport  # type: ignore[attr-defined]
    oauth2.id_token = id_token  # type: ignore[attr-defined]
    for name, module in {
        "google": google,
        "google.auth": auth,
        "google.auth.transport": transport,
        "google.auth.transport.requests": transport.requests,  # type: ignore[attr-defined]
        "google.oauth2": oauth2,
        "google.oauth2.id_token": id_token,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return seen


def adapter(audience: str = AUDIENCE) -> IapIdentityAdapter:
    return IapIdentityAdapter(Settings(profile="gcp", iap_audience=audience))


def context(assertion: str | None = "signed.iap.jwt") -> Any:
    from hex_service_kit.identity import RequestContext

    return RequestContext(headers={} if assertion is None else {_IAP_ASSERTION_HEADER: assertion})


# --------------------------------------------------------------------------------------- #
# 1. The audience is verified, it is configuration, and it is three-state.
# --------------------------------------------------------------------------------------- #
def test_the_adapter_declares_that_it_verifies() -> None:
    """The claim the exposure guard cashes. Everything below is that claim being earned."""
    assert declared_end_user_auth(IapIdentityAdapter) == VERIFIED


@pytest.mark.parametrize("audience", ["", "   ", "\t\n"])
def test_an_unset_or_blank_audience_refuses_instead_of_verifying_without_one(
    audience: str,
) -> None:
    """The whole point: there is no verify-without-an-audience path to fall into.

    Set-and-blank is the state a deployment template produces when a substitution is missing.
    It is truthy, so an unstripped read would hand ``"   "`` to the verifier as the expected
    audience: configured-looking, and matching nothing.
    """
    with pytest.raises(IapAudienceUnconfiguredError) as caught:
        adapter(audience).resolve(context())
    assert _AUDIENCE_ENV in str(caught.value)
    assert caught.value.http_status == 503, "no credential would have helped, so 401 is a lie"
    assert isinstance(caught.value, EndUserAuthUnavailableError)


def test_the_unconfigured_refusal_happens_before_the_sdk_is_even_reached(
    no_cloud_sdk: None,
) -> None:
    """Proved by making ``google`` UNIMPORTABLE: nothing about this refusal can depend on it.

    The check is first for a reason. A refusal that ran after the lazy import would depend on
    the SDK being installed, and a refusal that ran after the header read would depend on what
    the caller presented; an unconfigured deployment must refuse on its own configuration alone.
    """
    assert is_blocked_sdk("google.oauth2.id_token"), "the SDK block is not in force"
    with pytest.raises(IapAudienceUnconfiguredError):
        adapter("").resolve(context())


@pytest.mark.parametrize("assertion", [None, "", "   "])
def test_a_missing_or_blank_assertion_header_is_refused_without_the_sdk(
    assertion: str | None, no_cloud_sdk: None
) -> None:
    """A request that did not pass through IAP is refused before any verifier exists."""
    with pytest.raises(IdentityError) as caught:
        adapter().resolve(context(assertion))
    assert "missing IAP assertion header" in str(caught.value)
    assert not isinstance(caught.value, EndUserAuthUnavailableError), (
        "THIS caller failed to authenticate; the deployment is fine, so this is a plain 401"
    )


# --------------------------------------------------------------------------------------- #
# 2. The call contract: the audience and IAP's own key set are both passed, every time.
# --------------------------------------------------------------------------------------- #
def test_the_verifier_is_called_with_the_audience_and_the_iap_key_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact refutation, as a contract. Both arguments were absent; both are asserted."""
    captured = install_fake_google(monkeypatch, GOOD_CLAIMS)

    principal = adapter().resolve(context())

    assert captured["audience"] == AUDIENCE, "audience=None means the audience is NOT verified"
    assert captured["certs_url"] == _IAP_KEYS_URL, "the default key set is not IAP's key set"
    assert captured["assertion"] == "signed.iap.jwt"
    assert principal.subject == "analyst@bank.example"
    assert principal.tenant == "bank.example"
    assert principal.source == "gcp-iap"
    assert principal.actor == principal.subject


def test_the_pinned_key_set_is_iaps_published_one() -> None:
    """A literal worth asserting: a typo here silently verifies against the wrong keys."""
    assert _IAP_KEYS_URL == "https://www.gstatic.com/iap/verify/public_key"
    assert _IAP_ISSUER == "https://cloud.google.com/iap"


def test_the_transport_facts_are_the_commons_values() -> None:
    """The header, the issuer and the key set are REBOUND from the kit, not re-declared.

    The test above pins the two strings to their published values, which catches a typo. It
    cannot catch the other half: a rendered repo that goes on declaring its own literals stays
    green forever, because a local literal always agrees with itself, and the fleet only learns
    the copies have drifted when two deployments disagree about which header carries identity.
    Asserting them against the kit is what makes one edit to the reviewed set reach here.
    """
    assert _IAP_ASSERTION_HEADER == kit_federation.IAP_ASSERTION_HEADER
    assert _IAP_ISSUER == kit_federation.IAP_ISSUER
    assert _IAP_KEYS_URL == kit_federation.IAP_KEYS_URL


def test_the_configured_audience_is_what_reaches_the_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configuration, not a literal: a different deployment verifies a different resource."""
    other = "/projects/999999999999/global/backendServices/2222222222222222222"
    captured = install_fake_google(monkeypatch, GOOD_CLAIMS)
    adapter(other).resolve(context())
    assert captured["audience"] == other


def test_a_surrounding_whitespace_only_audience_never_reaches_the_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = install_fake_google(monkeypatch, GOOD_CLAIMS)
    with pytest.raises(IapAudienceUnconfiguredError):
        adapter("  \t ").resolve(context())
    assert captured == {}, "the verifier was called with a blank audience"


# --------------------------------------------------------------------------------------- #
# 3. A crash is not a refusal. Every failure of the managed verifier becomes an IdentityError.
# --------------------------------------------------------------------------------------- #
class _MalformedError(ValueError):
    """Shaped like ``google.auth.exceptions.MalformedError``: a ValueError, not an IdentityError.

    The real class is ``MalformedError(GoogleAuthError, ValueError)``. What matters for the
    defect is precisely that it is NOT an ``IdentityError``, so nothing in the request path
    handled it and FastAPI answered a bare 500.
    """


@pytest.mark.parametrize(
    "raised",
    [
        _MalformedError("Can't parse segment header"),
        ValueError("Token has wrong audience x, expected y"),
        ValueError("Token expired, iat 1, exp 2, now 3"),
        ValueError("Could not verify token signature."),
        KeyError("kid"),
        RuntimeError("transport failure fetching the IAP key set"),
        OSError("offline: the key set could not be fetched"),
    ],
    ids=["malformed", "wrong-audience", "expired", "wrong-key", "keyerror", "transport", "oserror"],
)
def test_every_verifier_failure_becomes_an_identity_error_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, raised: Exception
) -> None:
    """The wrap, stated as a rule: nothing the caller can put in a header may reach the client
    as a 500. The original reason is kept on the exception (and so in the log and the chain)."""
    install_fake_google(monkeypatch, raised)
    with pytest.raises(IdentityError) as caught:
        adapter().resolve(context("not-a-jwt"))
    assert "IAP assertion verification failed" in str(caught.value)
    assert caught.value.__cause__ is raised, "the original failure must stay on the chain"
    assert not isinstance(caught.value, EndUserAuthUnavailableError), (
        "a bad assertion is THIS caller's problem; the deployment can still authenticate others"
    )


def test_an_uninstalled_verifier_refuses_with_a_reason_rather_than_a_bare_500(
    no_cloud_sdk: None,
) -> None:
    """The second half of the wire proof: the bare 500 also happened with google-auth ABSENT.

    The lazy import is inside the ``try`` for exactly this. A deployment missing the managed
    extra can authenticate nobody, so it says so with a status and a message naming the fix,
    instead of raising ``ModuleNotFoundError`` per request out of a route.
    """
    with pytest.raises(IapVerifierUnavailableError) as caught:
        adapter().resolve(context("not-a-jwt"))
    assert caught.value.http_status == 503
    assert "requirements-gcp.lock" in str(caught.value)
    assert isinstance(caught.value, EndUserAuthUnavailableError)


# --------------------------------------------------------------------------------------- #
# 4. The claims are checked after the signature, not trusted because it passed.
# --------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({**GOOD_CLAIMS, "iss": "https://accounts.google.com"}, "issuer"),
        ({**GOOD_CLAIMS, "iss": ""}, "issuer"),
        ({k: v for k, v in GOOD_CLAIMS.items() if k != "iss"}, "issuer"),
        ({**GOOD_CLAIMS, "sub": ""}, "sub and email"),
        ({**GOOD_CLAIMS, "email": ""}, "sub and email"),
        ({k: v for k, v in GOOD_CLAIMS.items() if k != "email"}, "sub and email"),
    ],
    ids=["wrong-issuer", "blank-issuer", "no-issuer", "no-sub", "no-email", "email-absent"],
)
def test_a_verified_signature_does_not_excuse_the_claims(
    monkeypatch: pytest.MonkeyPatch, claims: dict[str, Any], reason: str
) -> None:
    """``verify_token`` checks signature, audience and expiry. It does NOT check the issuer."""
    install_fake_google(monkeypatch, claims)
    with pytest.raises(IdentityError, match=reason):
        adapter().resolve(context())


def test_a_missing_hosted_domain_is_an_empty_tenant_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``hd`` is absent for consumer accounts; the tenant partition is empty, not invented."""
    install_fake_google(monkeypatch, {k: v for k, v in GOOD_CLAIMS.items() if k != "hd"})
    assert adapter().resolve(context()).tenant == ""


# --------------------------------------------------------------------------------------- #
# 5. On the wire: the API answers 401, never 500, for an assertion a caller wrote.
# --------------------------------------------------------------------------------------- #
#: A LAN peer. RFC 5737 documentation address: no real host, and obviously fictional.
LAN_PEER = "192.0.2.50"

#: The managed profile with its DATA ports rebound to the SDK-free adapters, so these tests
#: exercise the real gcp IDENTITY binding without needing Cloud Logging or a live console. This
#: is the documented rebinding path (``adapters:`` in the settings file), not a test-only hook.
_PKG = "credit_portfolio_ews"
_REBOUND_SETTINGS = "\n".join(
    [
        'audit_path: ":memory:"',
        "iap_audience: " + "${" + _AUDIENCE_ENV + ":-}",
        "adapters:",
        "  audit:",
        *[f"    {p}: {_PKG}.adapters.local.audit:LocalAuditAdapter" for p in ("local", "gcp")],
        f"    onprem: {_PKG}.adapters.onprem.audit:OnPremAuditAdapter",
        "  identity:",
        f"    local: {_PKG}.adapters.local.identity:LocalIdentityAdapter",
        f"    gcp: {_PKG}.adapters.gcp.identity:IapIdentityAdapter",
        f"    onprem: {_PKG}.adapters.onprem.identity:OnPremIdentityAdapter",
        "  review_router:",
        *[
            f"    {p}: {_PKG}.adapters.local.review_router:LocalReviewRouter"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.review_router:OnPremReviewRouter",
        # Every port must bind every profile or `_bindings_from` refuses the whole file, so
        # this fixture lists the observability ports too. They take no part in the identity
        # posture under test; the offline adapters keep the rebuilt module SDK-free.
        "  tracer:",
        *[
            f"    {p}: {_PKG}.adapters.local.tracer:LocalNoopTracerAdapter"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.tracer:OnPremTracerAdapter",
        "  evaluation:",
        *[
            f"    {p}: {_PKG}.adapters.local.evaluation:LocalOfflineEvalAdapter"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.evaluation:OnPremEvalAdapter",
        # The five vertical ports, rebound to the offline adapters for the same reason: this
        # suite is about the IDENTITY binding, and it must not need a covenant feed, a
        # warehouse, a media index, a grade store or a model to exercise one.
        "  covenant_terms:",
        *[
            f"    {p}: {_PKG}.adapters.local.covenant_terms:LocalCovenantTerms"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.covenant_terms:OnPremCovenantTerms",
        "  portfolio_feed:",
        *[
            f"    {p}: {_PKG}.adapters.local.portfolio_feed:LocalPortfolioFeed"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.portfolio_feed:OnPremPortfolioFeed",
        "  adverse_media:",
        *[
            f"    {p}: {_PKG}.adapters.local.adverse_media:LocalAdverseMedia"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.adverse_media:OnPremAdverseMedia",
        "  grade_registry:",
        *[
            f"    {p}: {_PKG}.adapters.local.grade_registry:LocalGradeRegistry"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.grade_registry:OnPremGradeRegistry",
        "  generation:",
        *[f"    {p}: {_PKG}.adapters.local.generation:LocalMemoNarrator" for p in ("local", "gcp")],
        f"    onprem: {_PKG}.adapters.onprem.generation:OnPremMemoNarrator",
    ]
)

#: The one claim set whose hosted domain IS the offline estate's tenant partition. The federation
#: policy maps ``hd`` straight to the tenant id (see ``adapters/gcp/identity.py``), so a served
#: request only reaches a real obligor when the two agree, and the positive control below has to
#: reach one to prove that the escalation was ROUTED.
_SERVED_CLAIMS: dict[str, Any] = {**GOOD_CLAIMS, "hd": sample_cases.TENANT}


def _managed_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, audience: str | None) -> Any:
    """Re-import the API module under the managed profile with the given audience.

    The postures are decided at import, so the module is rebuilt rather than patched, and the
    audience arrives through the settings file's ``${VAR:-}`` expansion exactly as a deployment
    supplies it. ``None`` leaves the variable UNSET, which is how a deployment that configured
    no audience looks; the expansion then yields the empty string and the adapter refuses every
    caller. Setting the variable to an EMPTY value is a different state and the loader refuses it
    (see the emptied-audience test below), so it is never spelled here as ``""``.
    """
    from tests.conftest import reimport

    path = tmp_path / "settings.yaml"
    path.write_text(_REBOUND_SETTINGS + "\n", encoding="utf-8")
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(_SETTINGS_ENV, str(path))
    if audience is None:
        monkeypatch.delenv(_AUDIENCE_ENV, raising=False)
    else:
        monkeypatch.setenv(_AUDIENCE_ENV, audience)
    return reimport(_API_MODULE)


def test_a_malformed_assertion_from_a_lan_peer_answers_401_and_never_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The refutation over the request path: the exact request that produced a bare 500.

    ``gcp`` is the one profile whose exposure guard stands down and whose process really does
    bind every interface, so this is a stranger reaching a real deployment.
    """
    install_fake_google(monkeypatch, _MalformedError("Can't parse segment header"))
    module = _managed_app(monkeypatch, tmp_path, AUDIENCE)
    with TestClient(module.app, client=(LAN_PEER, 50000)) as client:
        resp = client.post(
            "/v1/watchlist-review",
            json={"obligor_id": sample_cases.ESCALATING_OBLIGOR},
            headers={_IAP_ASSERTION_HEADER: "not-a-jwt"},
        )
    assert resp.status_code == 401, "a header a caller wrote may not become a 500"
    detail = resp.json()["detail"]
    assert detail == "authentication required"
    assert "audience" not in detail and "signature" not in detail, (
        "the specific reason belongs in the log and the exception chain, not in the answer to "
        "an unauthenticated caller who would be learning what to forge next"
    )


def test_an_unconfigured_audience_answers_503_with_the_variable_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The operator-facing half: this deployment can authenticate nobody, and says which knob."""
    module = _managed_app(monkeypatch, tmp_path, None)
    with TestClient(module.app, client=(LAN_PEER, 50000)) as client:
        resp = client.post(
            "/v1/watchlist-review",
            json={"obligor_id": sample_cases.ESCALATING_OBLIGOR},
            headers={_IAP_ASSERTION_HEADER: "signed.iap.jwt"},
        )
    assert resp.status_code == 503
    assert _AUDIENCE_ENV in resp.json()["detail"]


def test_an_emptied_audience_is_refused_by_the_loader_and_never_serves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """An operator who EMPTIED the audience named nothing, and the loader refuses it.

    ``iap_audience: ${...:-}`` goes through the settings loader, which delegates to
    ``envread.setting_or_default``. UNSET still yields the empty string, which the adapter turns
    into a 503 naming the variable (the test above). SET-AND-EMPTY is a third state and the
    loader refuses it outright, so the mistake surfaces in the deploy that made it seconds
    earlier rather than as a value nobody reviewed.

    The API module still IMPORTS, because ``end_user_auth_kind`` swallows any lookup failure and
    resolves to ``CLIENT_ASSERTED`` on purpose: a guard that switched off because a lookup raised
    would fail OPEN. So the second half of this test is the fail-closed consequence: the LAN peer
    is refused rather than served by a process whose audience nobody chose.
    """
    module = _managed_app(monkeypatch, tmp_path, "")
    with pytest.raises(ConfiguredEmptyError, match=_AUDIENCE_ENV):
        Settings.load()
    with TestClient(module.app, client=(LAN_PEER, 50000)) as client:
        resp = client.post(
            "/v1/watchlist-review",
            json={"obligor_id": sample_cases.ESCALATING_OBLIGOR},
            headers={_IAP_ASSERTION_HEADER: "signed.iap.jwt"},
        )
    assert resp.status_code == 503


def test_a_verified_assertion_is_served_so_the_refusals_above_mean_something(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The positive control. Without it, every assertion above is satisfied by a broken adapter.

    The escalation is ROUTED in the same request (rule R8) and the audit actor is the VERIFIED
    subject from the assertion, never anything in the body.
    """
    install_fake_google(monkeypatch, _SERVED_CLAIMS)
    module = _managed_app(monkeypatch, tmp_path, AUDIENCE)
    with TestClient(module.app, client=(LAN_PEER, 50000)) as client:
        resp = client.post(
            "/v1/watchlist-review",
            json={
                "obligor_id": sample_cases.ESCALATING_OBLIGOR,
                "as_of": sample_cases.AS_OF.isoformat(),
            },
            headers={_IAP_ASSERTION_HEADER: "signed.iap.jwt"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_human_review"] is True
    assert body["review_ref"], "an escalated proposal must be routed, not merely flagged"
    assert body["grade_applied"] is False, "nothing applies a grade, on any profile"
