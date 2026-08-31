"""The engine may not read the exposure figure, and this is the scan that keeps it that way.

Materiality appears TWICE in this vertical and the two are different things:

* ARREARS materiality gates the past-due clock, so a trivial arrear cannot classify an obligor;
* EXPOSURE materiality sets the APPROVAL PATH, and takes no part in the classification.

Conflating them is the obvious way for an implementer to get this wrong, and the consequence is
specific: a grade that moved with facility size would be gameable by splitting facilities. So the
engine module is greppable-clean of the field name, and the one function that reads it lives in
the service beside a docstring saying why.
"""

from __future__ import annotations

import ast

from credit_portfolio_ews.domain.models import (
    WatchGrade,
)
from credit_portfolio_ews.domain.policy import (
    DEFAULT_POLICY,
)
from credit_portfolio_ews.domain.watchlist_service import (
    required_approvals,
)

from tests import REPO_ROOT
from tests.contract.canonical import CANONICAL_REVIEW

_ENGINE = REPO_ROOT / "src" / "credit_portfolio_ews" / "domain" / "early_warning.py"

#: The field the engine may not touch, spelled once so this module does not trip its own scan
#: by mentioning it in prose.
_FORBIDDEN = "exposure_amount" + "_minor"


def test_the_engine_module_never_names_the_exposure_field() -> None:
    source = _ENGINE.read_text(encoding="utf-8")
    assert _FORBIDDEN not in source, (
        "the early-warning engine references the exposure figure; exposure sets the approval "
        "path and never the grade, because a grade that moved with facility size would be "
        "gameable by splitting facilities"
    )


def test_the_engine_module_reads_no_attribute_of_that_name_under_any_alias() -> None:
    """The grep half catches the obvious edit; this catches a rename that keeps the access."""
    tree = ast.parse(_ENGINE.read_text(encoding="utf-8"))
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert _FORBIDDEN not in attributes


def test_the_approval_path_is_where_exposure_is_read_and_it_moves_no_grade() -> None:
    assessment = CANONICAL_REVIEW.assessment
    below = required_approvals(assessment, exposure_minor=1, policy=DEFAULT_POLICY)
    above = required_approvals(
        assessment,
        exposure_minor=DEFAULT_POLICY.dual_control_exposure_minor + 1,
        policy=DEFAULT_POLICY,
    )
    assert below == 2, "this proposal is into a non-performing grade on its own merits"
    assert above == 2
    # The grade is identical either way: the exposure only ever changed the approval count.
    assert assessment.proposal.proposed_grade is WatchGrade.SUBSTANDARD


def test_a_large_exposure_alone_demands_dual_control_on_an_otherwise_ordinary_proposal() -> None:
    from dataclasses import replace

    from credit_portfolio_ews.domain.models import Movement

    ordinary = replace(
        CANONICAL_REVIEW.assessment,
        proposal=replace(
            CANONICAL_REVIEW.assessment.proposal,
            proposed_grade=WatchGrade.SPECIAL_MENTION,
            current_grade=WatchGrade.PASS,
            movement=Movement.DOWNGRADE,
        ),
    )
    assert required_approvals(ordinary, exposure_minor=1) == 1
    assert (
        required_approvals(ordinary, exposure_minor=DEFAULT_POLICY.dual_control_exposure_minor + 1)
        == 2
    )
