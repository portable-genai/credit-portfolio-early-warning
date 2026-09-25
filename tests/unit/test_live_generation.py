"""The ``live`` profile: the laptop stack with a local open-weight model on the model port.

Offline, like the rest of the suite: the kit client is driven through a fake TRANSPORT, so the
real request building, fence stripping, JSON parsing and retry loop all run, and only the socket
is replaced. The model server itself is exercised by hand (see the README's Profiles section),
never by the gate.
"""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Callable
from typing import Any

import pytest
from hex_service_kit.localmodel import (
    DEFAULT_LOCAL_MODEL,
    START_RECIPE,
    LocalModelUnavailable,
)

from credit_portfolio_ews.adapters.live.generation import LocalModelMemoNarrator
from credit_portfolio_ews.adapters.local.generation import LocalMemoNarrator
from credit_portfolio_ews.config import (
    LIVE_PROFILE,
    Container,
    build_container,
)
from credit_portfolio_ews.domain.narration import MAX_OUTPUT_TOKENS, SYSTEM_INSTRUCTION
from credit_portfolio_ews.domain.watchlist_service import WatchlistReviewService
from credit_portfolio_ews.ports import PORT_PROTOCOLS

from tests.conftest import local_settings
from tests.fixtures import sample_cases


def _live_container() -> Container:
    return build_container(local_settings(profile=LIVE_PROFILE))


def _chat(content: str, *, model: str = DEFAULT_LOCAL_MODEL) -> bytes:
    """A chat completion as an MLX server returns it: no usage block at all."""
    return json.dumps(
        {"model": model, "choices": [{"message": {"role": "assistant", "content": content}}]}
    ).encode("utf-8")


class _ScriptedServer:
    """A fake transport: answers each call with the next scripted reply, and keeps every body."""

    def __init__(self, *replies: Callable[[dict[str, Any]], str]) -> None:
        self._replies = list(replies)
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, url: str, body: bytes | None, timeout: float) -> bytes:
        assert body is not None, "the narrator only ever posts a chat completion"
        payload = json.loads(body)
        self.bodies.append(payload)
        return _chat(self._replies.pop(0)(payload))


def _prose(_payload: dict[str, Any]) -> str:
    return "Here is the memo you asked for, in words rather than JSON."


def _fenced_grounded(payload: dict[str, Any]) -> str:
    """What Gemma does: a correct answer inside a markdown fence.

    The JSON is the offline narrator's restatement of the prompt, so it is grounded by
    construction and the domain's validation can accept it.
    """
    prompt = next(m["content"] for m in payload["messages"] if m["role"] == "user")
    return "```json\n" + LocalMemoNarrator(local_settings()).generate(prompt) + "\n```"


# --------------------------------------------------------------------------------------- #
# The adapter against a fake transport
# --------------------------------------------------------------------------------------- #
def test_a_fenced_answer_after_an_unusable_one_is_retried_and_returned_as_strict_json() -> None:
    server = _ScriptedServer(_prose, _fenced_grounded)
    narrator = LocalModelMemoNarrator(local_settings(profile=LIVE_PROFILE), transport=server)

    raw = narrator.generate(
        "CATEGORISE ONE CONFIRMED ADVERSE-MEDIA ITEM\n- item id: n-1\n- headline: x"
    )

    assert len(server.bodies) == 2, "the unusable first answer was not fed back and retried"
    assert json.loads(raw) == {"item_id": "n-1", "category": "unclear"}
    assert not raw.startswith("```"), "the port promises strict JSON; the fence is stripped here"
    retry = server.bodies[1]["messages"]
    assert retry[-2]["role"] == "assistant" and retry[-1]["role"] == "user"


def test_the_call_carries_the_managed_narrators_instruction_budget_and_temperature() -> None:
    server = _ScriptedServer(_fenced_grounded)
    LocalModelMemoNarrator(local_settings(profile=LIVE_PROFILE), transport=server).generate(
        "- item id: n-2"
    )
    body = server.bodies[0]
    assert body["model"] == DEFAULT_LOCAL_MODEL
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == MAX_OUTPUT_TOKENS
    system, user = body["messages"]
    assert system["role"] == "system" and system["content"].startswith(SYSTEM_INSTRUCTION)
    assert user == {"role": "user", "content": "- item id: n-2"}


def test_no_usable_json_after_every_retry_returns_the_last_answer_for_the_domain_to_discard() -> (
    None
):
    """Parity with the managed model: an unusable draft reaches the discard path, not a 500."""
    server = _ScriptedServer(_prose, _prose, _prose)
    raw = LocalModelMemoNarrator(local_settings(profile=LIVE_PROFILE), transport=server).generate(
        "draft"
    )
    assert len(server.bodies) == 3
    assert raw == _prose({})


def test_a_server_that_does_not_answer_raises_with_the_start_recipe() -> None:
    def down(url: str, body: bytes | None, timeout: float) -> bytes:
        raise urllib.error.URLError("connection refused")

    narrator = LocalModelMemoNarrator(local_settings(profile=LIVE_PROFILE), transport=down)
    with pytest.raises(LocalModelUnavailable) as caught:
        narrator.generate("draft")
    assert str(caught.value).endswith(START_RECIPE)


# --------------------------------------------------------------------------------------- #
# The profile
# --------------------------------------------------------------------------------------- #
def test_the_container_builds_every_port_under_the_live_profile() -> None:
    container = _live_container()
    for port, protocol in PORT_PROTOCOLS.items():
        adapter = getattr(container, port)
        assert isinstance(adapter, protocol), f"live/{port} does not satisfy its Protocol"
    assert isinstance(container.generation, LocalModelMemoNarrator)
    personas = container.identity.personas()  # type: ignore[attr-defined]
    assert personas, "the live lane serves the same seeded personas as local"


def test_the_banner_names_the_local_model_the_live_lane_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOCAL_MODEL", raising=False)
    assert local_settings(profile=LIVE_PROFILE).generator_model == DEFAULT_LOCAL_MODEL
    monkeypatch.setenv("LOCAL_MODEL", "some-other-open-model")
    assert local_settings(profile=LIVE_PROFILE).generator_model == "some-other-open-model"
    assert local_settings().generator_model == "deterministic-offline-stub"


def test_a_live_review_drafts_a_validated_memo_through_the_kit_client() -> None:
    """End to end over the real service: fenced JSON from the model becomes a validated memo."""
    container = _live_container()
    server = _ScriptedServer(*([_fenced_grounded] * 8))
    service = WatchlistReviewService(
        audit=container.audit,
        covenant_terms=container.covenant_terms,
        portfolio_feed=container.portfolio_feed,
        adverse_media=container.adverse_media,
        grade_registry=container.grade_registry,
        generation=LocalModelMemoNarrator(container.settings, transport=server),
        review_router=container.review_router,
        tracer=container.tracer,
    )
    review = service.review(
        sample_cases.ESCALATING_OBLIGOR,
        tenant=sample_cases.TENANT,
        actor=sample_cases.ACTOR,
        as_of=sample_cases.AS_OF,
    )
    assert review.memo_discarded_reason == ""
    assert review.memo_headline and review.memo_body
    assert server.bodies, "the model port was never called"
