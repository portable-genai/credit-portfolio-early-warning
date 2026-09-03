"""Managed GenerationPort: draft the review memo with the pinned Vertex model (SDK lazy).

The import lives inside :meth:`generate`, so the module is importable and constructible with no
cloud SDK present (the offline profiles bind it too). Temperature is zero and the call carries a
token budget, because a memo is a restatement and not a creative act.

The model narrates and categorises; the caller validates its output against a schema, a
digit-token grounding check and a cited-source check, and DISCARDS it on failure. A model that
hallucinates a figure therefore changes nothing consequential.

``_MODEL`` is a module constant so ``config.generator_model`` can name it on the provenance
banner by reading the BINDING rather than a second settings string that could drift from it. The
Hrz1 guardrail gateway sits in front of this in the managed deployment; this adapter does not
re-implement guardrails.
"""

from __future__ import annotations

from ...config import Settings

_MODEL = "gemini-3.5-flash"
_SYSTEM = (
    "You restate credit early-warning facts as JSON. You never introduce a figure, a date or a "
    "grade that was not given to you, and you never recommend a classification of your own."
)
#: A memo is a paragraph. The budget is a cost control and a bound on what a runaway draft costs.
_MAX_OUTPUT_TOKENS = 768


class VertexMemoNarrator:
    """Draft watchlist review memos and categorise confirmed media items via the pinned model."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, prompt: str) -> str:
        # Lazy: the SDK import is the first thing the method does, so an offline caller gets an
        # ImportError here rather than at construction (which every profile performs).
        from google import genai
        from google.genai import types

        client = genai.Client()
        response = client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                temperature=0.0,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
                response_mime_type="application/json",
            ),
        )
        return str(response.text)
