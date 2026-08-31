"""The model boundary: draft the review memo, validate it, DISCARD it on any failure.

The model never produces a grade, a movement, a floor, a score, a weight, a threshold or a
boolean. The engine has already decided all of those. Narration turns them into the paragraph a
credit officer reads, and this module owns the three pure functions that keep it honest:

* :func:`memo_facts` extracts the labelled figures the engine produced (the grounding set);
* :func:`build_prompt` assembles the instruction and those facts in SEPARATE labelled blocks, so
  retrieved text cannot escalate the model's authority by looking like an instruction;
* :func:`validate_memo` parses the model's JSON and rejects it on any of five grounds.

The prompt is built from the REDACTED projection of the assessment and nothing else, which is
the property that matters most: what the model was allowed to see is exactly what it is allowed
to say back. Grounding is checked against the SAME projection, so masking cannot turn a faithful
restatement into an ungrounded one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .models import (
    EarlyWarningAssessment,
    WatchGrade,
)

#: A number token: integers and decimals. Every digit in the prose must resolve to one of these.
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

#: The label the FACTS block opens with. The offline narrator restates everything after it.
FACTS_MARKER = "FACTS (do not add to these):"


@dataclass(frozen=True, slots=True)
class ReviewMemo:
    """The validated memo: a headline, a grounded body, and the sources it leaned on."""

    headline: str
    body: str
    cited_source_ids: tuple[str, ...]


def memo_facts(assessment: EarlyWarningAssessment) -> tuple[tuple[str, str], ...]:
    """The labelled engine facts, in a fixed order. Labels carry no digits, deliberately.

    The grounding set is derived from these same VALUES, so a narrator that restates the block
    faithfully is grounded by construction and one that invents a figure is not.
    """
    proposal = assessment.proposal
    rows: list[tuple[str, str]] = [
        ("obligor", assessment.obligor_name),
        ("obligor reference", assessment.obligor_id),
        ("as of", str(assessment.as_of)),
        ("test period", assessment.test_period),
        ("grade of record", proposal.current_grade.value),
        ("band grade", proposal.band_grade.value),
        ("proposed grade", proposal.proposed_grade.value),
        ("movement", proposal.movement.value),
        ("notches", str(proposal.notches)),
        ("applied floors", ", ".join(proposal.applied_floors) or "none"),
        ("applied ceiling", proposal.applied_ceiling or "none"),
        ("withheld reason", proposal.withheld_reason or "none"),
        ("composite score", str(assessment.composite_score)),
        ("effective days past due", str(assessment.effective_days_past_due)),
        ("staging backstop", assessment.staging_backstop.value),
        ("data completeness", str(assessment.data_completeness)),
        ("review reasons", ", ".join(assessment.review_reasons) or "none"),
    ]
    for score in assessment.family_scores:
        rows.append(
            (
                f"family {score.family.value}",
                f"raw {score.raw_weight} capped {score.capped_weight} of {score.cap} "
                f"over {score.signal_count} signals",
            )
        )
    # EVERY covenant row, including the compliant ones. A memo that listed only the failures
    # would not tell a credit officer what was tested, and the clause text is exactly where a
    # guarantor gets named, so this is also what makes the masking of the prompt non-vacuous.
    for test in assessment.covenant_tests:
        rows.append((f"covenant {test.covenant_id}", f"{test.status.value}: {test.detail}"))
    for signal in assessment.signals:
        rows.append((f"signal {signal.rule_id}", f"weight {signal.weight}: {signal.detail}"))
    for source_id, title, snippet in (
        (c.source_id, c.title, c.snippet) for c in assessment.citations
    ):
        rows.append(("source", f"{source_id} {title} {snippet}".strip()))
    return tuple(rows)


def grounding_tokens(assessment: EarlyWarningAssessment) -> frozenset[str]:
    """Every number token the engine produced. A figure outside this set is a fabrication."""
    tokens: set[str] = set()
    for _label, value in memo_facts(assessment):
        tokens.update(_NUMBER.findall(value))
    return frozenset(tokens)


def build_prompt(assessment: EarlyWarningAssessment) -> str:
    """Instruction first, then the engine facts under a labelled block. Data is not instruction."""
    lines = [
        "You are drafting a watchlist review memo for a credit officer.",
        "Restate ONLY the facts below. Do not introduce any number, percentage, date, grade or",
        "conclusion that is not already present, and do not recommend a grade of your own.",
        'Return STRICT JSON: {"headline": str, "body": str, "cited_source_ids": [str]}.',
        "Every id in cited_source_ids must be one of the source ids listed below.",
        "",
        FACTS_MARKER,
    ]
    lines.extend(f"- {label}: {value}" for label, value in memo_facts(assessment))
    return "\n".join(lines)


def validate_memo(raw: str, assessment: EarlyWarningAssessment) -> tuple[ReviewMemo | None, str]:
    """Parse and validate the draft. Returns ``(memo, "")`` or ``(None, reason)``.

    Five ways a draft is discarded, and the reason is REPORTED rather than swallowed so a
    validation failure is visible on the surface instead of looking like a model that had
    nothing to say:

    * it is not strict JSON, or not a JSON object with string ``headline`` and ``body``;
    * it cites no source at all, which is the empty-retrieval hard error in its narration form;
    * it cites a source id the assessment does not carry;
    * it states a figure the engine did not produce;
    * it names a classification the engine did not produce.
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return (None, "the draft was not strict JSON")
    if not isinstance(parsed, dict):
        return (None, "the draft was not a JSON object")
    headline = parsed.get("headline")
    body = parsed.get("body")
    if not isinstance(headline, str) or not isinstance(body, str):
        return (None, "the draft is missing a string headline or body")
    if not headline.strip() or not body.strip():
        return (None, "the draft carried an empty headline or body")

    raw_ids = parsed.get("cited_source_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return (None, "the draft cited no source; an uncited memo is not shippable")
    cited = tuple(str(value) for value in raw_ids)
    known = {citation.source_id for citation in assessment.citations}
    unknown = [source_id for source_id in cited if source_id not in known]
    if unknown:
        return (None, f"the draft cited sources the assessment does not carry: {unknown}")

    prose = f"{headline} {body}"
    facts = grounding_tokens(assessment)
    invented = [token for token in _NUMBER.findall(prose) if token not in facts]
    if invented:
        return (None, f"the draft states figures the engine did not produce: {invented}")

    stated = _grades_named(prose)
    allowed = {
        assessment.proposal.current_grade,
        assessment.proposal.band_grade,
        assessment.proposal.proposed_grade,
    }
    invented_grades = sorted(grade.value for grade in stated - allowed)
    if invented_grades:
        return (
            None,
            f"the draft named a classification the engine did not produce: {invented_grades}",
        )

    return (ReviewMemo(headline.strip(), body.strip(), cited), "")


def _grades_named(text: str) -> set[WatchGrade]:
    """Which supervisory grade wire values appear in ``text``, on word boundaries."""
    lowered = text.lower()
    return {grade for grade in WatchGrade if re.search(rf"\b{re.escape(grade.value)}\b", lowered)}
