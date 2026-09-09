#!/usr/bin/env python3
"""Regenerate the derived sections of ``docs/evals.md`` from the rubrics and two real runs.

Two harnesses, two families of bar, and the difference between them is the thing a reader must
not lose. The regression gate scores a pure function at 1.00 and says nothing about predictive
validity; the model-risk harness scores structure against a stated assumption and says nothing
about the world. A page that listed both by hand would state that difference once and then go
stale the first time a bar moved.

    make evals-doc          # rewrite the generated sections
    make eval               # includes --check; non-zero when the page and the artifacts differ

Only the sections named in :data:`BLOCKS` are generated. Everything else is hand-written prose
addressed to a reviewer, and this script does not touch it.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

from agent_eval_kit import load_jsonl, load_rubrics, render_main

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "eval"))
sys.path.insert(0, str(_REPO_ROOT / "src"))

DOC = _REPO_ROOT / "docs" / "evals.md"
RUBRICS = _REPO_ROOT / "eval" / "rubrics"

BLOCKS = (
    "## What the regression gate measures",
    "## What the model-risk harness measures",
    "## What is exercised",
)


def _regression_block() -> list[str]:
    import run_eval

    report = run_eval.run_smoke(run_eval.DEFAULT_DATASET)
    rubrics = load_rubrics(RUBRICS).group("")
    lines = [
        BLOCKS[0],
        "",
        "`eval/run_eval.py`. Every bar is 1.00 and every bar lives in",
        "`eval/rubrics/regression.yaml` beside the argument for it. There is no threshold dict",
        "in the runner: a metric scored with no reviewed bar fails the build, and so does a bar",
        "that names no scored metric, which is the direction that rots quietly because it rots",
        "toward looking well governed.",
        "",
        "These metrics score a PURE FUNCTION against hand-written expectations. They prove the",
        "arithmetic did not move under a grade somebody already acted on. They prove nothing",
        "about whether the scorecard predicts anything, and no number in this table may be",
        "cited as though they did.",
        "",
        "| Metric | Bar | What it measures |",
        "|---|---|---|",
    ]
    for rubric in rubrics:
        lines.append(
            f"| `{rubric.metric}` | {rubric.threshold:g} | {' '.join(rubric.description.split())} |"
        )
    lines += [
        "",
        f"Scored over {report.n_examples} golden cases, dataset digest",
        f"`{report.dataset_digest[:12]}`, by `{report.evaluator}`. At {report.n_examples} cases",
        "scored 0/1, the loosest bar that would tolerate a single failure is",
        f"{(report.n_examples - 1) / report.n_examples:.2f}, so every bar here that used to read",
        "0.98 or 0.99 was already all-or-nothing and now says so.",
        "",
    ]
    return lines


def _model_risk_block() -> list[str]:
    import run_model_risk

    rubrics = load_rubrics(RUBRICS).group("model-risk")
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        run_model_risk.main(["--report-only"])
    printed = buffer.getvalue()
    scores = {
        line.split()[0]: line.split()[1]
        for line in printed.splitlines()
        if line.startswith("  ")
        and len(line.split()) > 3
        and line.split()[0] in run_model_risk.SCORED
    }
    lines = [
        BLOCKS[1],
        "",
        "`eval/run_model_risk.py`. A different kind of bar, and the distinction is load-bearing:",
        "under SR 11-7 and PRA SS1/23 the scoring engine is a model, and a regression gate is",
        "not the evidence a model owes.",
        "",
        "The first two metrics are measured against a SYNTHETIC sample whose labels come from",
        "the generative model recorded in `scripts/render_calibration_sample.py`, not from",
        "realised outcomes. They say whether the scorecard's structure is coherent under a",
        "written assumption a validator can read and disagree with. They are not a backtest.",
        "The last two measure whether the controls that would produce real evidence exist at",
        "all, and both score zero.",
        "",
        "| Metric | Score | Bar | What it measures |",
        "|---|---|---|---|",
    ]
    for rubric in rubrics:
        outstanding = (
            " (outstanding: no control)" if rubric.metric in run_model_risk.MONITORING else ""
        )
        lines.append(
            f"| `{rubric.metric}` | {scores.get(rubric.metric, 'n/a')} | {rubric.threshold:g} | "
            f"{' '.join(rubric.description.split())}{outstanding} |"
        )
    # The band table verbatim, taken from the header line to the first blank after it rather
    # than by pattern: a filter that matched on content picked up the metric rows too, and a
    # table that quietly gains a row from another section is worse than no table.
    printed_lines = printed.splitlines()
    start = next(i for i, line in enumerate(printed_lines) if line.strip().startswith("band "))
    end = next(
        (i for i in range(start, len(printed_lines)) if not printed_lines[i].strip()),
        len(printed_lines),
    )
    lines += ["", "Band table from the same run:", "", "```"]
    lines += [line.rstrip() for line in printed_lines[start:end]]
    lines += ["```", ""]
    return lines


def _exercised_block() -> list[str]:
    import run_eval
    import run_model_risk

    golden = load_jsonl(run_eval.DEFAULT_DATASET)
    sample = load_jsonl(run_model_risk.SAMPLE)
    positives = sum(1 for row in sample if row["latent_state"] == "deteriorating")
    return [
        BLOCKS[2],
        "",
        f"- **{len(golden)} golden cases** in `eval/datasets/golden_cases.jsonl`, over ONE",
        "  synthetic estate whose inputs live in `adapters/local/_fixtures.py` and are read by",
        "  the local adapters, the demo and this dataset alike. Hand-written expectations, held",
        "  equal to those fixtures by `tests/unit/test_golden_dataset.py`.",
        f"- **{len(sample)} synthetic obligors** in `eval/datasets/synthetic_calibration.jsonl`,",
        f"  {positives} of them labelled deteriorating by the generative model that produced",
        "  them. No real obligors, no realised outcomes, no historical data of any kind. The",
        "  file is rendered from one seed and `--check` fails the gate when it is stale.",
        "- **Zero realised outcomes and zero logged overrides.** Both are measured rather than",
        "  assumed: `monitoring/` holds neither file and the harness reports that as a failing",
        "  metric. See `monitoring/README.md`.",
        "- **The falsification proofs run first in both harnesses.** `prove_before_scoring` is",
        "  the opening statement of each scored run, so every metric is shown going red on its",
        "  own planted defect in the same process, against the same bars, before any score is",
        "  trusted. `tests/unit/test_not_falsely_green.py` adds what a proof cannot say about",
        "  itself: that there is one for every metric scored, in both families.",
        "",
    ]


def render() -> str:
    text = DOC.read_text(encoding="utf-8")
    missing = [heading for heading in BLOCKS if heading not in text]
    if missing:
        raise SystemExit(
            f"{DOC}: missing generated section(s) {missing}. This script replaces named "
            "headings; it does not invent them, because a page it could create from nothing "
            "would silently replace one a person wrote."
        )
    generated = {
        BLOCKS[0]: _regression_block(),
        BLOCKS[1]: _model_risk_block(),
        BLOCKS[2]: _exercised_block(),
    }
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line in generated:
            out.extend(generated[line])
            skipping = True
            continue
        if skipping:
            if line.startswith("## "):
                skipping = False
            else:
                continue
        out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


if __name__ == "__main__":
    raise SystemExit(
        render_main(
            output=DOC,
            render=render,
            description="Regenerate docs/evals.md from the rubrics and two real runs.",
            argv=sys.argv[1:],
        )
    )
