"""The covenant vocabulary is consumed VERBATIM from credit-memo-drafting (credit-memo-drafting).

credit-memo-drafting extracts covenants at origination; this repo tests them afterwards. The two
services must describe the same covenant with the same words, or a threshold extracted as
``leverage`` at origination becomes an ``other`` here and quietly stops being tested by the rule
that names it.

The enum is RE-DECLARED rather than imported, because the domain imports only the standard library
plus the commons and credit-memo-drafting is reached over a port. That is the right call for the
import graph and the wrong one for drift, so this module is the compensating control: it pins the
member set and every wire value against what a credit-memo-drafting-shaped payload carries. A member
added to ``CovenantType`` here without a matching member there is drift this repo cannot see from
inside, and this is where it becomes visible.
"""

from __future__ import annotations

from credit_portfolio_ews.domain.models import (
    CovenantOperator,
    CovenantStatus,
    CovenantType,
)

#: The covenant kinds credit-memo-drafting's extraction schema enumerates, verbatim. If
#: credit-memo-drafting adds one, this list
#: is the first thing to update, and the LenientStrEnum means an unknown value degrades to a
#: readable failure rather than crashing a portfolio sweep in the meantime.
DOC2_COVENANT_TYPES: tuple[str, ...] = (
    "leverage",
    "dscr",
    "interest_cover",
    "current_ratio",
    "min_ebitda",
    "max_capex",
    "tangible_net_worth",
    "other",
)

#: The comparison operators credit-memo-drafting emits, verbatim.
DOC2_OPERATORS: tuple[str, ...] = ("<=", "<", ">=", ">", "==")

#: The three statuses credit-memo-drafting itself computes. This repo adds four that only exist
#: AFTER
#: origination, and they must be ADDITIVE: renaming one of credit-memo-drafting's three would
#: silently change
#: what a shared status string means.
DOC2_STATUSES: tuple[str, ...] = ("compliant", "at_risk", "breach")

#: The four this repo owns, because at origination every term is freshly evidenced.
POST_ORIGINATION_STATUSES: tuple[str, ...] = ("waived", "stale", "not_evidenced", "not_due")


def test_the_covenant_type_members_match_doc2_exactly() -> None:
    assert [member.value for member in CovenantType] == list(DOC2_COVENANT_TYPES)


def test_the_operator_members_match_doc2_exactly() -> None:
    assert [member.value for member in CovenantOperator] == list(DOC2_OPERATORS)


def test_the_shared_statuses_are_doc2s_and_the_rest_are_additive() -> None:
    values = [member.value for member in CovenantStatus]
    assert values[: len(DOC2_STATUSES)] == list(DOC2_STATUSES)
    assert set(values) == set(DOC2_STATUSES) | set(POST_ORIGINATION_STATUSES)


def test_not_due_and_not_evidenced_are_deliberately_different_states() -> None:
    """A covenant whose period is still open must not read as one nobody evidenced."""
    assert CovenantStatus.NOT_DUE is not CovenantStatus.NOT_EVIDENCED


def test_the_vocabulary_is_lenient_so_a_future_doc2_member_degrades_readably() -> None:
    """A sweep must not crash on a type credit-memo-drafting added last week."""
    assert CovenantType("LEVERAGE") is CovenantType.LEVERAGE
    assert CovenantOperator(">=") is CovenantOperator.GE


def test_a_doc2_shaped_payload_round_trips_through_the_vocabulary() -> None:
    """The wire values, exercised the way the managed adapter parses them."""
    payload = {"type": "tangible_net_worth", "operator": ">=", "status": "breach"}
    assert CovenantType(payload["type"]) is CovenantType.TANGIBLE_NET_WORTH
    assert CovenantOperator(payload["operator"]) is CovenantOperator.GE
    assert CovenantStatus(payload["status"]) is CovenantStatus.BREACH
