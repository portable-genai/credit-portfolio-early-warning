"""On-prem GenerationPort: fail-fast placeholder (bind the client's own model endpoint).

The memo is DRAFTING, so this refusal costs a paragraph and never a decision. That is precisely
why the decision does not live here: an on-premises deployment with no model still gets a
complete assessment, a complete grade proposal and a complete routed escalation, with
``memo_discarded_reason`` naming the unbound seam.
"""

from __future__ import annotations

from ...config import Settings


class OnPremMemoNarrator:
    """Satisfies GenerationPort but refuses at call time: wire the client's model gateway."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, prompt: str) -> str:
        raise NotImplementedError(
            "on-prem narration model is a portability placeholder: bind the client's own model "
            "endpoint (see docs/onprem-migration.md). The assessment is complete without it; "
            "only the drafted memo is missing."
        )
