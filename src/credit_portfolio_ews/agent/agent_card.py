"""The A2A discovery card: what this agent can be asked to do, in one machine-readable place.

Served at ``/.well-known/agent-card.json`` and registrable with agent-registry (rule R4). The card
is built from the SAME tool table the runtime binds, so an agent cannot advertise a skill it does
not implement or implement one it never advertises; ``tests/unit/test_agent_surface.py`` fails the
build when the two disagree.

Pure: domain types and stdlib only, no ADK and no cloud SDK, so the card can be generated and
inspected offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hex_service_kit.serialization import to_jsonable

from ..config import Settings

_CARD_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class AgentSkill:
    """One advertised capability. ``id`` is the tool function's name, never a prose label."""

    id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class AgentCard:
    """The minimal A2A discovery document a peer agent or the registry reads."""

    name: str
    description: str
    url: str
    version: str = _CARD_VERSION
    provider: str = "credit-portfolio-early-warning"
    skills: tuple[AgentSkill, ...] = field(default_factory=tuple)


SKILLS: tuple[AgentSkill, ...] = (
    AgentSkill(
        id="review_obligor",
        name="Watchlist review and grade proposal",
        description=(
            "Test one obligor's origination covenants against the reported period, fuse "
            "financial, behavioural, external and process early-warning signals through a "
            "deterministic scoring engine, and PROPOSE a watchlist grade with every applied "
            "floor named and every claim cited. Records an already-redacted audit event and "
            "routes a consequential proposal to human review (rule R8). It never applies a "
            "grade: there is no write path to the grading system of record."
        ),
    ),
    AgentSkill(
        id="verify_audit_trail",
        name="Audit-trail verification",
        description=(
            "Re-derive the hash chain over the stored audit trail and cross-check the external "
            "head anchor, returning an honest verdict: intact, or the first record that broke "
            "the chain, or the anchor disagreement that exposes a truncated tail."
        ),
    ),
)

#: Joined from short pieces, each carrying at most one template variable, so a longer
#: ``friendly_name`` cannot push a line past the formatter's limit in the rendered repo while
#: the template itself still looks fine. The vertical's own prose belongs in ``README.md``;
#: the card says what the agent IS and what it guarantees.
_DESCRIPTION = " ".join(
    (
        "Credit Portfolio Early Warning",
        "(credit-portfolio-early-warning).",
        "Deterministic scoring, cited output, redact-before-audit, a proposal that is",
        "never applied, and every consequential result routed to a human reviewer.",
    )
)


def build_agent_card(settings: Settings | None = None) -> AgentCard:
    """Construct the A2A card for this agent in the configured deployment."""
    resolved = settings or Settings.load()
    return AgentCard(
        name="credit-portfolio-early-warning",
        description=_DESCRIPTION,
        url=_resolve_url(resolved),
        skills=SKILLS,
    )


def agent_card_document(settings: Settings | None = None) -> dict[str, Any]:
    """The JSON-safe body served at ``/.well-known/agent-card.json``."""
    document = to_jsonable(build_agent_card(settings))
    if not isinstance(document, dict):  # pragma: no cover - dataclasses serialise to objects
        raise TypeError("an agent card must serialise to a JSON object")
    return document


def _resolve_url(settings: Settings) -> str:
    """Best-effort public URL for the card, region-qualified so residency is visible on it."""
    return f"https://credit-portfolio-early-warning.{settings.region}.internal.example/a2a"
