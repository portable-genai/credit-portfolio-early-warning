"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the model adapters NOTED as
they called. Before a request is answered the pill shows ``generator_model`` from ``/healthz``,
so that value must be the model the bound adapter calls, never one a configuration flag names
while the adapter calls another.

The Gemini narrator is driven here through a FAKE ``google.genai`` module, so what is proved is
this repository's half: the model id the call notes, and the sampling each call site sends. The
media categorisation is pinned at 0.0 (a classification the engine compares); the memo draft is
drafting and sends no temperature at all. No adapter here attaches an online search tool, so
nothing in this repository notes a search; the route is still proved to carry the header the
day one does.
"""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance

from credit_portfolio_ews import config
from credit_portfolio_ews.adapters.gcp.generation import _MODEL, VertexMemoNarrator
from credit_portfolio_ews.adapters.live.generation import LocalModelMemoNarrator
from credit_portfolio_ews.adapters.local.generation import (
    OFFLINE_NARRATOR,
    LocalMemoNarrator,
    RecordingNarrator,
)
from credit_portfolio_ews.config import LIVE_PROFILE, Settings, build_container
from credit_portfolio_ews.domain.watchlist_service import (
    CATEGORISE_MARKER,
    CATEGORISE_TEMPERATURE,
    WatchlistReviewService,
)

from tests import REPO_ROOT
from tests.conftest import local_settings
from tests.fixtures import sample_cases

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"


@pytest.fixture(autouse=True)
def _local_profile(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Build under ``local`` whatever the calling shell exported, CI's unset one included."""
    monkeypatch.setenv("CREDITEWS_PROFILE", "local")
    yield


def _review(api_client: TestClient) -> dict[str, str]:
    response = api_client.post(
        "/v1/watchlist-review",
        json={
            "obligor_id": sample_cases.ESCALATING_OBLIGOR,
            "as_of": sample_cases.AS_OF.isoformat(),
        },
        headers={"X-Dev-Persona": "auditor"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["memo_body"], "no memo was drafted, so no model answered"
    return dict(response.headers)


def test_the_local_narrator_answers_as_the_stub_the_pill_first_names(
    api_client: TestClient,
) -> None:
    """Under ``local`` the pill before and after the answer name the same stub."""
    headers = _review(api_client)
    assert headers[ANSWERED_BY] == OFFLINE_NARRATOR
    assert local_settings().generator_model == OFFLINE_NARRATOR
    assert SEARCH_USED not in headers


def test_a_call_that_searched_says_so_and_the_next_request_starts_fresh(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = LocalMemoNarrator.generate

    def searching(self: LocalMemoNarrator, prompt: str, *, temperature: float | None = None) -> str:
        provenance.note_model("fake-searching-model")
        provenance.note_search()
        return original(self, prompt, temperature=temperature)

    monkeypatch.setattr(LocalMemoNarrator, "generate", searching)
    headers = _review(api_client)
    assert headers[ANSWERED_BY] == f"fake-searching-model, {OFFLINE_NARRATOR}"
    assert headers[SEARCH_USED] == "true"
    monkeypatch.setattr(LocalMemoNarrator, "generate", original)
    headers = _review(api_client)
    assert headers[ANSWERED_BY] == OFFLINE_NARRATOR
    assert SEARCH_USED not in headers


# --------------------------------------------------------------------------------------- #
# The call sites: what the SERVICE sent, read off the port it was handed.
# --------------------------------------------------------------------------------------- #
def _spied_review(obligor_id: str) -> RecordingNarrator:
    container = build_container(local_settings())
    spy = RecordingNarrator(container.generation)
    WatchlistReviewService(
        audit=container.audit,
        covenant_terms=container.covenant_terms,
        portfolio_feed=container.portfolio_feed,
        adverse_media=container.adverse_media,
        grade_registry=container.grade_registry,
        generation=spy,
        review_router=container.review_router,
        tracer=container.tracer,
    ).review(
        obligor_id,
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
    )
    return spy


def test_the_memo_draft_is_free_and_the_categorisation_is_pinned() -> None:
    sent: list[tuple[str, float | None]] = []
    for obligor_id in (sample_cases.PII_OBLIGOR, "obl-lambda-011"):
        spy = _spied_review(obligor_id)
        sent.extend(zip(spy.prompts, spy.temperatures, strict=True))
    drafts = [t for prompt, t in sent if not prompt.startswith(CATEGORISE_MARKER)]
    categorisations = [t for prompt, t in sent if prompt.startswith(CATEGORISE_MARKER)]
    assert drafts and categorisations, "one of the two call sites was never reached"
    assert set(drafts) == {None}, "the memo is drafting: it must send no temperature"
    assert CATEGORISE_TEMPERATURE == 0.0
    assert set(categorisations) == {0.0}, "the categorisation is compared, so it is pinned"


# --------------------------------------------------------------------------------------- #
# The Gemini narrator, through a fake SDK.
# --------------------------------------------------------------------------------------- #
class _FakeModels:
    def __init__(self, text: str) -> None:
        self.calls: list[dict[str, Any]] = []
        self._text = text

    def generate_content(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(text=self._text)


def _fake_genai(monkeypatch: pytest.MonkeyPatch, text: str) -> _FakeModels:
    models = _FakeModels(text)
    genai = types.ModuleType("google.genai")
    genai_types = types.ModuleType("google.genai.types")
    genai_types.GenerateContentConfig = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    genai.types = genai_types  # type: ignore[attr-defined]
    genai.Client = lambda **_: SimpleNamespace(models=models)  # type: ignore[attr-defined]
    google = sys.modules.get("google") or types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setattr(google, "genai", genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", genai_types)
    return models


def test_the_gemini_narrator_notes_its_model_and_drafts_with_no_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = _fake_genai(monkeypatch, '{"headline": "h"}')
    with provenance.scope() as record:
        VertexMemoNarrator(Settings(profile="gcp")).generate("draft")
    assert record.models == [_MODEL]
    assert record.search_used is False
    (call,) = models.calls
    assert call["model"] == _MODEL
    sent = vars(call["config"])
    assert "temperature" not in sent, "drafting is free: no temperature, never a default"
    assert "tools" not in sent, "no online search tool is attached, so none may be claimed"


def test_a_pinned_call_reaches_the_gemini_config(monkeypatch: pytest.MonkeyPatch) -> None:
    models = _fake_genai(monkeypatch, "{}")
    VertexMemoNarrator(Settings(profile="gcp")).generate("categorise", temperature=0.0)
    assert models.calls[0]["config"].temperature == 0.0


def test_the_live_narrator_sends_no_temperature_and_the_kit_notes_the_model() -> None:
    bodies: list[dict[str, Any]] = []

    def transport(url: str, body: bytes | None, timeout: float) -> bytes:
        assert body is not None
        bodies.append(json.loads(body))
        return json.dumps(
            {"model": "a-local-model", "choices": [{"message": {"content": "{}"}}], "usage": {}}
        ).encode()

    narrator = LocalModelMemoNarrator(local_settings(profile=LIVE_PROFILE), transport=transport)
    with provenance.scope() as record:
        narrator.generate("draft")
    assert "temperature" not in bodies[0]
    assert record.models == ["a-local-model"]


# --------------------------------------------------------------------------------------- #
# generator_model is the model the adapter calls.
# --------------------------------------------------------------------------------------- #
def test_generator_model_is_the_model_the_gemini_narrator_calls() -> None:
    assert Settings(profile="gcp").generator_model == _MODEL


def test_no_flag_swaps_in_a_model_the_adapter_never_calls() -> None:
    """The latent false banner: a flag that moved the pill but not the model that answered."""
    models = SimpleNamespace(
        reasoning="the-model-the-adapter-calls",
        hard_reasoning="a-model-nobody-calls",
        use_hard_reasoning=True,
    )
    named = config._model_from_settings(SimpleNamespace(models=models), "models.reasoning")
    assert named == "the-model-the-adapter-calls"


def test_the_hard_reasoning_flag_does_not_exist() -> None:
    settings_file = (REPO_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert "use_hard_reasoning" not in settings_file
    for source in sorted((REPO_ROOT / "src").rglob("*.py")):
        assert "use_hard_reasoning" not in source.read_text(encoding="utf-8"), source
