"""The hexagon's boundaries, re-exported once so there is a single import site.

Every port is a ``@runtime_checkable`` Protocol and every port has a binding in every profile
(``config.DEFAULT_BINDINGS``); ``tests/contract/test_port_parity.py`` asserts both, plus set
equality in the reverse direction so a port added here without a binding fails the build.

``IdentityPort``, ``ObservabilityTracerPort`` and ``EvaluationGatePort`` are not redeclared:
they come from the shared commons packages and are re-exported here so consumers still have
one import site for the boundary set. Copies of these had already drifted apart across the
fleet before they were shared, which is the whole reason they are imported rather than typed
out. See :mod:`.observability`. What an identity
adapter DECLARES about the authentication it provides is this service's own vocabulary, not the
commons', and lives in :mod:`.identity` next to the re-export.

The five vertical ports below name five genuinely different systems of record: the origination
service that extracted the covenants, the spreading system and transaction warehouse, the
adverse-media feed, the grading system of record, and the model seam. Folding any two together
would either hide the grounding requirement or give the registry feed a write path by accident.
"""

from __future__ import annotations

from hex_service_kit.identity import IdentityPort

from .adverse_media import AdverseMediaPort
from .audit import AuditSinkPort
from .covenant_terms import CovenantTermsPort
from .generation import GenerationPort
from .grade_registry import WRITE_VERBS, GradeRegistryPort
from .identity import (
    CLIENT_ASSERTED,
    END_USER_AUTH_ATTR,
    END_USER_AUTH_KINDS,
    UNIMPLEMENTED,
    VERIFIED,
    EndUserAuthUnavailableError,
    declared_end_user_auth,
)
from .observability import (
    EvaluationGatePort,
    ObservabilityTracerPort,
    TokenUsage,
)
from .portfolio_feed import PortfolioFeedPort
from .review_router import ReviewRouterPort
from .tenancy import CrossTenantError

#: port name (the key in the settings ``adapters:`` block) -> the Protocol it must satisfy.
PORT_PROTOCOLS: dict[str, type] = {
    "audit": AuditSinkPort,
    "identity": IdentityPort,
    "review_router": ReviewRouterPort,
    "tracer": ObservabilityTracerPort,
    "evaluation": EvaluationGatePort,
    "covenant_terms": CovenantTermsPort,
    "portfolio_feed": PortfolioFeedPort,
    "adverse_media": AdverseMediaPort,
    "grade_registry": GradeRegistryPort,
    "generation": GenerationPort,
}

__all__ = [
    "WRITE_VERBS",
    "TokenUsage",
    "ObservabilityTracerPort",
    "EvaluationGatePort",
    "CLIENT_ASSERTED",
    "END_USER_AUTH_ATTR",
    "END_USER_AUTH_KINDS",
    "PORT_PROTOCOLS",
    "UNIMPLEMENTED",
    "VERIFIED",
    "AdverseMediaPort",
    "AuditSinkPort",
    "CovenantTermsPort",
    "CrossTenantError",
    "EndUserAuthUnavailableError",
    "GenerationPort",
    "GradeRegistryPort",
    "IdentityPort",
    "PortfolioFeedPort",
    "ReviewRouterPort",
    "declared_end_user_auth",
]
