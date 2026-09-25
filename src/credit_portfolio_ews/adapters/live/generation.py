"""Live GenerationPort: the laptop lane's narrator, a local open-weight model via the kit client.

The ``live`` profile keeps every other port on the SDK-free local adapters and binds THIS one to
the fleet's shared local model server (``hex_service_kit.localmodel``, configured by
``LOCAL_MODEL_URL`` / ``LOCAL_MODEL`` / ``LOCAL_MODEL_TIMEOUT``). It is asked exactly what the
managed narrator is asked: the same system instruction, the same prompt, the same token budget
and the same temperature, so the two lanes differ in the model and nothing else.

The port is one string in and one string out, and the caller expects STRICT JSON back. The
managed adapter gets that from Gemini's JSON response mode; a local server enforces nothing, so
the call goes through :meth:`LocalModelClient.complete_json` with no schema: the answer is
parsed here, a markdown fence or a sentence around the JSON is tolerated, and an answer with no
JSON in it is fed back and retried. The shape of the JSON stays the domain's to check
(``domain/narration.validate_memo`` and the categorisation parser), exactly as it is for the
managed model, so this adapter adds no second, drifting copy of it.

Failure maps to what the managed adapter does:

* a server that does not answer raises :class:`LocalModelUnavailable` unchanged, as the managed
  adapter lets its SDK error through; its message ends with the two-line start recipe;
* a model that answers with no usable JSON after every retry returns its LAST answer, as Gemini
  would return an unusable draft, so the domain's discard path reports the reason rather than
  the request failing on a drafting fault.
"""

from __future__ import annotations

import json

from hex_service_kit.localmodel import (
    LocalModelClient,
    LocalModelOutputError,
    LocalModelSettings,
    Transport,
)

from ...config import Settings
from ...domain.narration import MAX_OUTPUT_TOKENS, SYSTEM_INSTRUCTION

#: The managed narrator runs at zero, because a memo is a restatement and not a creative act.
#: The port carries no temperature of its own, so the laptop lane runs at the same value.
_TEMPERATURE = 0.0


def configured_model() -> str:
    """The model id this lane calls, as the provenance banner names it (``LOCAL_MODEL``)."""
    return LocalModelSettings.from_env().model


class LocalModelMemoNarrator:
    """Draft review memos and categorise confirmed media items with the local open-weight model."""

    def __init__(self, settings: Settings, *, transport: Transport | None = None) -> None:
        self._settings = settings
        self._client = LocalModelClient(LocalModelSettings.from_env(), transport=transport)

    def generate(self, prompt: str) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": prompt},
        ]
        try:
            completion = self._client.complete_json(
                messages, temperature=_TEMPERATURE, max_tokens=MAX_OUTPUT_TOKENS
            )
        except LocalModelOutputError as exc:
            return exc.last_text
        return json.dumps(completion.data)
