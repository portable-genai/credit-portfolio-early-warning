"""Managed GenerationPort: draft the review memo with the pinned Vertex model (SDK lazy).

The import lives inside :meth:`generate`, so the module is importable and constructible with no
cloud SDK present (the offline profiles bind it too). The call carries a token budget; its
temperature is the caller's, per call: the media categorisation is pinned at zero because its
answer is a classification the engine compares, and the memo draft sends none at all, because
free sampling is an ABSENT parameter (some models reject it), never a default value.

The model narrates and categorises; the caller validates its output against a schema, a
digit-token grounding check and a cited-source check, and DISCARDS it on failure. A model that
hallucinates a figure therefore changes nothing consequential.

``_MODEL`` is a module constant so ``config.generator_model`` can name it on the model pill by
reading the BINDING rather than a second settings string that could drift from it, and the same
constant is what the adapter notes (``hex_service_kit.provenance.note_model``) once it has
answered, so the pill names the model that answered. No online search tool is attached. The
agent-guardrail-gateway sits in front of this in the managed deployment; this adapter does not
re-implement guardrails.
"""

from __future__ import annotations

from hex_service_kit import provenance

from ...config import Settings
from ...domain.narration import MAX_OUTPUT_TOKENS, SYSTEM_INSTRUCTION

_MODEL = "gemini-3.5-flash"


class VertexMemoNarrator:
    """Draft watchlist review memos and categorise confirmed media items via the pinned model."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, prompt: str, *, temperature: float | None = None) -> str:
        # Lazy: the SDK import is the first thing the method does, so an offline caller gets an
        # ImportError here rather than at construction (which every profile performs).
        from google import genai
        from google.genai import types

        client = genai.Client()
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
        )
        if temperature is not None:
            # Pinned only where the caller compares the answer; otherwise it is never sent.
            config.temperature = temperature
        response = client.models.generate_content(model=_MODEL, contents=prompt, config=config)
        provenance.note_model(_MODEL)
        return str(response.text)
