"""Local GenerationPort: a deterministic, grounded narrator for the SDK-free profile.

No model call. It serves both model jobs the service asks for, told apart by the marker the
prompt opens with:

* CATEGORISE: match the item's own headline and snippet against the closed category vocabulary,
  in declaration order. It never asserts relevance, which is the feed's job, and it answers
  ``unclear`` when nothing matches, which fires nothing.
* DRAFT: restate the prompt's FACTS block as strict JSON, so every figure it emits is one the
  engine already produced and the groundedness check passes offline by construction.

This is not a fake that dodges the validation. It drives the real schema check, the real
digit-token grounding check, the real cited-source check and the real discard path. The
deliberately UNGROUNDED narrator below is its twin, and exists so the groundedness metric can be
shown going red rather than only ever observed green. The RECORDING narrator beside it is the
other kind of instrument: it decides nothing and only keeps what the service actually sent, so
the redact-before-the-model control can be asserted against the real call.
"""

from __future__ import annotations

import json
import re

from ...config import Settings
from ...domain.models import NewsCategory
from ...domain.narration import FACTS_MARKER
from ...domain.watchlist_service import CATEGORISE_MARKER
from ...ports.generation import GenerationPort

_ITEM_ID = re.compile(r"- item id: (.+)")
_HEADLINE = re.compile(r"- headline: (.+)")
_SNIPPET = re.compile(r"- snippet: (.+)")
_OBLIGOR = re.compile(r"- obligor: (.+)")
_MOVEMENT = re.compile(r"- movement: (.+)")
_SOURCE = re.compile(r"- source: (\S+)")

#: What the health banner reports for this binding. Deliberately not a model name: naming one
#: would claim a model this profile never calls.
OFFLINE_NARRATOR = "deterministic-offline-stub"


def _first(pattern: re.Pattern[str], prompt: str, fallback: str = "") -> str:
    match = pattern.search(prompt)
    return match.group(1).strip() if match else fallback


class LocalMemoNarrator:
    """Categorise from the item's own words and restate the engine's own facts. Grounded."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, prompt: str) -> str:
        if prompt.startswith(CATEGORISE_MARKER):
            return self._categorise(prompt)
        return self._memo(prompt)

    @staticmethod
    def _categorise(prompt: str) -> str:
        item_id = _first(_ITEM_ID, prompt)
        text = f"{_first(_HEADLINE, prompt)} {_first(_SNIPPET, prompt)}".lower()
        chosen = NewsCategory.UNCLEAR
        for category in NewsCategory:
            if category is NewsCategory.UNCLEAR:
                continue
            if category.value.replace("_", " ") in text:
                chosen = category
                break
        return json.dumps({"item_id": item_id, "category": chosen.value})

    @staticmethod
    def _memo(prompt: str) -> str:
        obligor = _first(_OBLIGOR, prompt, "the obligor")
        movement = _first(_MOVEMENT, prompt, "reviewed")
        _, _, facts = prompt.partition(FACTS_MARKER)
        body = re.sub(r"\s+", " ", facts).strip() or "See the engine result."
        sources = _SOURCE.findall(prompt)
        return json.dumps(
            {
                "headline": f"{obligor} watchlist review: {movement}",
                "body": body,
                "cited_source_ids": sources,
            }
        )


class UngroundedMemoNarrator:
    """The deliberate defect: a draft carrying a figure the engine never produced.

    Bound nowhere. It exists so ``narration_groundedness`` can be SHOWN going red, because a
    guard observed only green asserts nothing. Delete it and the metric stops meaning anything.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, prompt: str) -> str:
        if prompt.startswith(CATEGORISE_MARKER):
            return LocalMemoNarrator(self._settings).generate(prompt)
        sources = _SOURCE.findall(prompt)
        return json.dumps(
            {
                "headline": "Watchlist review",
                "body": "Composite score 4242 on a fabricated basis.",
                "cited_source_ids": sources,
            }
        )


class RecordingNarrator:
    """A spy on the model boundary: it keeps every prompt the SERVICE actually passed.

    Bound nowhere, and it decides nothing: it delegates to whichever narrator it wraps and only
    remembers what went past. It exists because "redaction precedes the model" cannot be asserted
    by rebuilding the prompt. A check that calls ``build_prompt(redacted_assessment(...))`` itself
    proves the masker works and never observes what the service handed the port, so the seam
    could be moved off the masked projection with every check still green. Wrapping the bound
    port is what makes the assertion about the real call, and it covers BOTH model jobs: the memo
    draft and the per-item categorisation, which mask through different lines of code.
    """

    def __init__(self, inner: GenerationPort) -> None:
        self._inner = inner
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._inner.generate(prompt)

    def sent(self) -> str:
        """Every prompt this port was given, joined, for one containment assertion over all."""
        return "\n".join(self.prompts)
