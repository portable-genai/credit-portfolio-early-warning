"""The vertical's headline control: this service has no method that could apply a grade.

The catalog line says this service never re-grades an obligor autonomously. That promise is
enforced by ABSENCE rather than by a boolean somebody could flip, and absence is exactly the kind
of claim that rots quietly, so it is checked in two independent ways:

1. the Protocol's public method set is EXACTLY the two reads. A Protocol that grew a write would
   make every adapter in the fleet grow one;
2. every BOUND adapter, in every profile, carries no public attribute matching a write verb. A
   Protocol is structural: an adapter can satisfy it and still carry extra methods, and it is the
   adapter a caller actually holds.

Both were shown RED against a planted ``set_grade`` on ``adapters/local/grade_registry.py``:
the first stays green (the Protocol is untouched, which is the point of having the second), and
the second fails with ``local/grade_registry exposes a write verb: ['set_grade']``. The
portability tour and the demo self-test fail on the same mutation, so the control is checked
three times over from three different entry points.
"""

from __future__ import annotations

import pytest

from credit_portfolio_ews.config import (
    KNOWN_PROFILES,
    build_container,
)
from credit_portfolio_ews.ports.grade_registry import (
    WRITE_VERBS,
    GradeRegistryPort,
)

from tests.conftest import local_settings

#: The complete read surface. Widening it is a decision about whether this service can change a
#: grade, so it is made here, deliberately, rather than by adding a method somewhere.
READ_METHODS = {"obligor", "list_obligors"}


def _write_verb_attributes(adapter: object) -> list[str]:
    return sorted(
        name
        for name in dir(adapter)
        if not name.startswith("_") and any(name.startswith(verb) for verb in WRITE_VERBS)
    )


def test_the_protocol_declares_exactly_the_two_reads() -> None:
    declared = {name for name in GradeRegistryPort.__protocol_attrs__ if not name.startswith("_")}
    assert declared == READ_METHODS, (
        "the grade-registry Protocol changed shape; if a write method was added, the catalog "
        "line 'never re-grades an obligor autonomously' is no longer enforced by absence"
    )


@pytest.mark.parametrize("profile", sorted(KNOWN_PROFILES))
def test_no_bound_adapter_in_any_profile_carries_a_write_verb(profile: str) -> None:
    adapter = build_container(local_settings(profile=profile)).grade_registry
    assert _write_verb_attributes(adapter) == [], (
        f"the {profile} grade-registry adapter exposes a write path; this service proposes a "
        "grade and must have no method that could apply one"
    )


def test_the_scan_can_go_red_so_the_green_above_means_something() -> None:
    """The control case: the same scan, aimed at an object that DOES carry a write verb."""

    class _PlantedWriter:
        def obligor(self) -> None: ...

        def list_obligors(self) -> None: ...

        def set_grade(self) -> None: ...

    assert _write_verb_attributes(_PlantedWriter()) == ["set_grade"]


def test_the_write_verb_list_covers_the_spellings_a_refactor_would_actually_use() -> None:
    for verb in ("set", "write", "apply", "update", "save", "upsert", "grade"):
        assert verb in WRITE_VERBS, f"a plausible write spelling is missing: {verb}"
