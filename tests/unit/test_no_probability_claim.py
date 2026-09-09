"""The composite score is an ordinal triage rank, and nothing shipped may say otherwise.

`docs/model-card.md` is explicit: `composite_score` is not a probability of default, not a
rating and not an input to expected credit loss, and anyone reading it as a PD is reading it
wrong. That is not a stylistic preference. A number presented as a probability is used as one:
it gets multiplied by an exposure, it lands in an ECL calculation, and the fact that nothing
calibrated it stops being visible the moment the word appears next to it.

The risk this guards is drift, not authorship. Nobody writes "probability of default" into a
docstring on purpose. It arrives when a metric gets a friendlier name, when a comment explains
the score to a newcomer, or when a narration prompt is widened, and by then the model card and
the code disagree with nobody to notice.

The scan is over SHIPPED text: source, docs, prompts, config. It is deliberately NOT a
substring match on "probability of default": the model card, the compliance FAQ, the adopting
guide and the engine's own IFRS 9 comment all use that phrase to REFUSE the claim, and a check
that flagged them would be deleted within a week for being wrong about every hit it found.

So a match is flagged only when the sentence around it carries no refusal. That is a heuristic
and its limit is worth stating: a sentence written as "the composite score is a probability of
default, unlike a rating" would pass, because "unlike" reads as a refusal. What it does catch is
the shape drift actually takes, which is a plain declarative sentence added by someone
explaining the score to a newcomer. The two tests below hold it to both directions.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Directories whose text reaches a reader. `tests/` is out: a test that proves the engine is
#: not a PD model has to be able to say "PD".
_SCANNED = ("src", "docs", "config", "eval", "scripts")

#: The documents whose job is to REFUSE the claim, and which therefore have to make it.
_EXEMPT = {
    _REPO_ROOT / "docs" / "model-card.md",
    _REPO_ROOT / "docs" / "conceptual-soundness.md",
    _REPO_ROOT / "docs" / "override-log.md",
    _REPO_ROOT / "docs" / "evals.md",
    _REPO_ROOT / "eval" / "run_model_risk.py",
    _REPO_ROOT / "eval" / "rubrics" / "model-risk" / "discrimination.yaml",
    _REPO_ROOT / "scripts" / "render_calibration_sample.py",
    Path(__file__),
}

#: Phrases that assert the score is a probability or a rating. Written as patterns rather than
#: substrings so "probability of default" is caught however it is spaced or hyphenated, and so
#: an ordinary use of "probability" in an unrelated sentence is not.
_CLAIMS = (
    re.compile(
        r"probabilit(?:y|ies)[\s\-]*(?:\n[^\S\n]*)?of[\s\-]*(?:\n[^\S\n]*)?default",
        re.IGNORECASE,
    ),
    re.compile(r"\bPD\s+(?:estimate|score|value)\b"),
    re.compile(r"\bexpected\s+credit\s+loss\b", re.IGNORECASE),
    re.compile(r"\blifetime\s+PD\b", re.IGNORECASE),
)

#: What makes a sentence a refusal rather than a claim. Deliberately generous: a false negative
#: here costs one undetected sentence, and a false positive costs the check its credibility.
_REFUSALS = re.compile(
    r"\b(?:not|never|no|nor|rather than|instead of|unlike|without|cannot|does not|do not|"
    r"is not|are not|neither|needs a|would need|absent|refus\w*|misread\w*|wrong)\b",
    re.IGNORECASE,
)

#: How far around a match counts as "the sentence". Bounded so a refusal three paragraphs away
#: cannot launder a claim, and wide enough that a sentence wrapped across two lines is one
#: sentence, which is how every docstring in this repository is written.
_WINDOW = 400


def _sentence_around(text: str, start: int, end: int) -> str:
    """The text between the nearest sentence boundaries, clipped to a bounded window."""
    left = max(0, start - _WINDOW)
    right = min(len(text), end + _WINDOW)
    before = text[left:start]
    after = text[end:right]
    opener = max(before.rfind(". "), before.rfind(".\n"), before.rfind("\n\n"))
    breaks = (after.find(". "), after.find(".\n"), after.find("\n\n"))
    closer = min((index for index in breaks if index >= 0), default=len(after))
    return before[opener + 1 :] + text[start:end] + after[:closer]


_SUFFIXES = (".py", ".md", ".yaml", ".yml", ".json", ".txt", ".toml")


def _shipped_files() -> list[Path]:
    out: list[Path] = []
    for directory in _SCANNED:
        root = _REPO_ROOT / directory
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in _SUFFIXES or not path.is_file():
                continue
            if "__pycache__" in path.parts or path in _EXEMPT:
                continue
            out.append(path)
    return out


def test_no_shipped_text_calls_the_composite_a_probability_of_default() -> None:
    files = _shipped_files()
    assert files, "the scan found no files, which would make this test vacuous"
    hits: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in _CLAIMS:
            for match in pattern.finditer(text):
                sentence = _sentence_around(text, match.start(), match.end())
                if _REFUSALS.search(sentence):
                    continue  # the sentence refuses the claim; that is what it is for
                line = text[: match.start()].count("\n") + 1
                hits.append(
                    f"{path.relative_to(_REPO_ROOT)}:{line}: {' '.join(sentence.split())[:160]!r}"
                )
    assert not hits, (
        "shipped text presents the composite score as a probability or a rating:\n  "
        + "\n  ".join(hits)
        + "\n\nThe score is an ordinal triage rank. Nothing here is calibrated, and a number "
        "presented as a probability gets used as one. See docs/model-card.md."
    )


def test_the_scan_catches_a_claim_and_leaves_a_refusal_alone() -> None:
    """Both directions. A scan that flags everything is deleted; one that flags nothing is worse.

    The refusal below is the sentence the compliance FAQ actually ships. If this check ever
    starts flagging it, the check is wrong and the FAQ is right.
    """
    claimed = "The composite_score is a probability of default for the obligor."
    refused = (
        "Do not describe composite_score as a probability of default: it ranks attention and "
        "carries no calibration that would make that reading safe."
    )
    caught = [
        match
        for match in (pattern.search(claimed) for pattern in _CLAIMS)
        if match and not _REFUSALS.search(_sentence_around(claimed, *match.span()))
    ]
    assert caught, "the affirmative claim was not caught"
    assert all(
        not match or _REFUSALS.search(_sentence_around(refused, *match.span()))
        for match in (pattern.search(refused) for pattern in _CLAIMS)
    ), "a sentence that refuses the claim was flagged as making it"
