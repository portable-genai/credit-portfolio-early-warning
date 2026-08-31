"""GenerationPort: the model boundary. One string in, one string out, deliberately.

The catalog says this service drafts cited watchlist-grading proposals and review memos for the
credit officer, so there is a real drafting job and it needs a named boundary: the model is a
binding like every other port rather than a client constructed inside the domain.

The surface is thin on purpose. The port cannot be handed a result object and can never grow the
ability to return one, so the consequential decision cannot leak into an adapter. Both model jobs
go through this one method, so there is exactly one place where a model answers and exactly one
place (``domain/narration.py``) where its answer is checked.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class GenerationPort(Protocol):
    def generate(self, prompt: str) -> str:
        """Return the model's raw response to ``prompt`` (expected to be strict JSON).

        The caller validates it and may DISCARD it; the port makes no promise the output is
        well formed, only that it is what the model returned.
        """
        ...
