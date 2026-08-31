"""Prove the pii_safety metric THE GATE ACTUALLY RUNS is not falsely green (the C4 lesson).

Pointed at the shipped oracle, deliberately. The previous version of this module defined its own
one-line ``_pii_safety`` over a hand-written string and proved that ``pii_kit.redact`` and
``pii_kit.pack_leak`` disagree about it, which is a property of the commons and not of this
repo's pipeline. The metric that gates promotion is the one in ``eval/run_eval.py``, which reads
REAL audit records written by the real service, and that one had two blind spots this harness
could not have seen: it read a single field of a record, and nothing anywhere observed the string
the service handed the model.

So the harness drives ``run_eval.run_smoke`` over the whole estate twice, and the only difference
between the runs is the pattern pack the SERVICE masks with. Emptying that pack is the one-place
expression of "redaction off": the projection at the service edge, the second masking inside the
audit write and the categorisation snippet all read it. The oracle under test keeps the real
pack, because an oracle that degraded with its subject would report clean either way, which is
the exact failure this file exists to rule out.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import run_eval
from agent_eval_kit import assert_can_go_red
from pii_kit import Pattern

from credit_portfolio_ews.domain import (
    watchlist_service,
)
from credit_portfolio_ews.domain.pii import (
    PII_PATTERNS,
)


@contextmanager
def _masking_with(pack: tuple[Pattern, ...]) -> Iterator[None]:
    """Rebind the pack the service masks with, and put the shipped one back afterwards."""
    original = watchlist_service.PII_PATTERNS
    watchlist_service.PII_PATTERNS = pack
    try:
        yield
    finally:
        watchlist_service.PII_PATTERNS = original


def _pii_safety(pack: tuple[Pattern, ...]) -> float:
    """The SHIPPED metric, over the SHIPPED pipeline, with ``pack`` doing the masking."""
    with _masking_with(pack):
        report = run_eval.run_smoke(run_eval.DEFAULT_DATASET)
    return next(result.score for result in report.results if result.metric == "pii_safety")


def test_the_shipped_pii_safety_oracle_can_go_red_over_real_audit_records() -> None:
    assert_can_go_red(
        _pii_safety,
        green=PII_PATTERNS,  # redaction on: every planted identifier is masked
        red=(),  # redaction off (the mutant): the raw identifiers survive
        threshold=run_eval.THRESHOLDS["pii_safety"],
        metric="pii_safety",
    )


def test_the_oracle_reads_more_of_the_record_than_the_field_it_used_to_read() -> None:
    """A record is immutable, so the scan over it cannot be narrower than the record.

    The leak that went undetected sat in ``citations[].snippet``. This pins the shape of the fix
    rather than the wording: everything on the record is scanned except the attribution the pack
    cannot tell from a leak, and that exemption is named in one place.
    """
    entry = {
        "actor": "analyst@bank.example",
        "redacted_summary": "clean",
        "citations": [{"snippet": "press desk desk@lambda-chem.example"}],
    }
    scanned = run_eval._scannable(entry)
    assert "desk@lambda-chem.example" in scanned, "a citation snippet is not being scanned"
    assert "analyst@bank.example" not in scanned
    assert run_eval.ATTRIBUTION_FIELDS == ("actor",)
