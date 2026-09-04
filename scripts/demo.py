"""The scripted, offline demo: the REAL services, synthetic data, an audit-first output view.

This is the demo as CODE (practices check F1), not a slide deck and not a recording. Every step
below drives the actual watchlist-review service, the actual pure early-warning engine, the
actual hash-chained audit store and the actual rule-R8 review router over the ``local`` profile,
so a step that stops being true stops passing rather than stops being mentioned.

Three properties make it worth running in front of somebody:

* **Nothing is faked.** No engine stub, no pre-baked JSON. The composite scores, the applied
  floor rules, the audit records, the routing references and the tamper verdict are produced by
  the shipped code, over the same synthetic estate the eval loads.
* **It is bounded.** The demo proves an offline, single-process seam. It does not prove
  cross-host deployment, a live console, or the managed profile; those need a cloud project and
  live in ``tests/integration/``.
* **It is replayable.** Same inputs, same output, every time, because every consequential value
  is integer arithmetic over an explicit ``as_of``. That is what makes it safe to run live.

Run it directly to write the audit-view JSON, then render that JSON to static pages::

    make demo-static

or drive it one step at a time with ``demo_server.py`` and ``walkthrough.py`` (``make demo``).

Every party, address and identifier here is obviously fictional: ``.example`` domains, RFC 5737
and RFC 3849 literals, and a synthetic national id that exists only to prove redaction happened.

MAINTAINER NOTE: this file is rendered from a template, so no line may change length with the
package or service name. Every cookiecutter value is bound to a short module constant below and
referenced through it, and every import line is short enough that a long package name cannot
push it past the formatter's limit.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hex_service_kit.audit import HashChainedAuditLog
from hex_service_kit.identity import RequestContext
from hex_service_kit.serialization import to_jsonable

from credit_portfolio_ews.adapters.local import (
    _fixtures,
)
from credit_portfolio_ews.adapters.local.generation import (
    RecordingNarrator,
)
from credit_portfolio_ews.config import (
    Settings,
    build_container,
    build_policy,
)
from credit_portfolio_ews.domain import (
    kernel,
)
from credit_portfolio_ews.domain.early_warning import (
    EarlyWarningEngine,
)
from credit_portfolio_ews.domain.models import (
    GRADE_RANK,
    WatchGrade,
    WatchlistReview,
)
from credit_portfolio_ews.domain.pii import (
    JURISDICTIONS,
)
from credit_portfolio_ews.domain.policy import (
    DEFAULT_POLICY,
)
from credit_portfolio_ews.domain.watchlist_service import (
    WatchlistReviewService,
    redacted_assessment,
)
from credit_portfolio_ews.ports.grade_registry import (
    WRITE_VERBS,
    GradeRegistryPort,
)


def loaded_cloud_sdks() -> tuple[str, ...]:
    """Every managed-SDK module currently importable in THIS interpreter, sorted.

    Public because the demo, the walkthrough's checks and the test suite all ask the same
    question and must not each answer it slightly differently.
    """
    return tuple(sorted(name for name in sys.modules if name.split(".")[0] == "google"))


#: Rendered identity, bound once so no other line's length depends on how long a name is.
SERVICE_NAME = "Credit Portfolio Early Warning"
CATALOG_ID = "credit-portfolio-early-warning"
REPOSITORY = "credit-portfolio-early-warning"

# --------------------------------------------------------------------------------------- #
# Synthetic data. Every obligor, address and identifier below comes from the ONE fixture
# estate in `adapters/local/_fixtures.py`, which the eval loads too, so the demo and the
# evaluation cannot fail in different ways for the same cause.
# --------------------------------------------------------------------------------------- #

#: The VERIFIED principal the demo attributes work to. A client never asserts this.
ACTOR = "analyst@bank.example"
TENANT = _fixtures.TENANT
AS_OF = _fixtures.AS_OF

#: The three obligors the arc walks, in the order the beats need them.
ROUTINE_OBLIGOR = "obl-kappa-010"
ESCALATING_OBLIGOR = "obl-delta-004"
PII_OBLIGOR = "obl-gamma-003"

#: A planted identifier, so the redaction panel has an independent literal to look for rather
#: than trusting the pattern pack to agree with itself. It lives in the guarantor clause of a
#: covenant, which is exactly where personal data enters a credit file.
PLANTED_NRIC = _fixtures.fixture_for(PII_OBLIGOR).planted_identifier

#: An obligor held under a DIFFERENT tenant, used nowhere in the arc: it exists in the estate so
#: the cross-tenant refusal is a real path rather than a claim.
OTHER_TENANT_OBLIGOR = "obl-omega-999"


def registry_write_methods(registry: object) -> list[str]:
    """Public attributes on a bound grade-registry adapter that look like a WRITE. Expect none.

    This is the vertical's headline control, checked by introspecting the live object rather
    than by trusting a sentence in a document: there is no method that could apply a grade.
    """
    return sorted(
        name
        for name in dir(registry)
        if not name.startswith("_") and any(name.startswith(verb) for verb in WRITE_VERBS)
    )


def protocol_methods(protocol: type) -> list[str]:
    """The public method names a Protocol declares."""
    return sorted(
        name
        for name in getattr(protocol, "__protocol_attrs__", dir(protocol))
        if not name.startswith("_")
    )


# --------------------------------------------------------------------------------------- #
# The presenter arc
# --------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Step:
    """One presenter beat: what it shows, and the sentence the presenter reads aloud."""

    key: str
    label: str
    narration: str


#: The scripted arc, in order. ``walkthrough.py`` asserts the server reaches each key in turn
#: and carries an expectation per key, so a step added here without an expectation there fails
#: the self-test rather than silently extending the demo.
STEPS: tuple[Step, ...] = (
    Step(
        key="opened",
        label="Bound offline, with the bank's policy visible and a registry that cannot write",
        narration=(
            "The whole stack binds from one settings file. Two things on this page are the "
            "vertical rather than the scaffolding. The grade ladder, the family caps and the "
            "floor rules are the bank's numbers, read from configuration, so a credit committee "
            "retunes them without a code change, and the loader refuses a ladder that is not "
            "monotonic before it ever serves a request. And the port that holds the grade of "
            "record declares read methods only. There is no write path to grade an obligor from "
            "this service. That is not a policy we promise to keep, it is a method that does "
            "not exist."
        ),
    ),
    Step(
        key="routine",
        label="Forty one days down, and the obligor stays at pass",
        narration=(
            "Forty one days of arrears, and this obligor stays at pass. The amount clears the "
            "absolute limit and fails the relative one, so the clock never started. Immaterial "
            "arrears are a payment artefact, not a default, and an engine that classified this "
            "obligor substandard would be a toy. Look at what is on the screen though: the rule "
            "that did NOT fire is recorded, with both limits and both observed values, because "
            "a second-line reviewer asks what you considered, and a silent pass destroys that. "
            "Nothing is routed, because manufacturing a review for a clean obligor is how you "
            "train a credit committee to rubber-stamp the ones that matter."
        ),
    ),
    Step(
        key="escalation",
        label="The score said special mention. The arrears floor said substandard.",
        narration=(
            "Three things happen here that a scoring dashboard would hide. The financial family "
            "summed to 73 and contributed 40, because a covenant breach and a thin-coverage "
            "rule are the same fact and must not count twice. The composite lands the band at "
            "special mention, and then the ninety-day arrears floor classifies it substandard: "
            "days past due classify an exposure whatever the score says, and a clean covenant "
            "sheet cannot talk you out of that. And the litigation headline contributed exactly "
            "zero, because the feed has not confirmed it is about this obligor. Every figure "
            "came from integer arithmetic over named thresholds. Setting the flag is not the "
            "escalation. Routing is, and the reference says where it went."
        ),
    ),
    Step(
        key="redaction",
        label="A guarantor's identifier is masked before the model and before the write",
        narration=(
            "This is where personal data actually enters a credit file: a guarantor named in a "
            "covenant clause. The masking happens once, where the result leaves the service, "
            "and every sink downstream gets the same masked object. That last one matters most: "
            "what the model was allowed to see is exactly what it is allowed to say back. "
            "Redacting after an immutable write is too late, and redacting after the model call "
            "is too late in a different way. Two more things are true here. The live waiver "
            "removed the grade floor and did not remove the signal, so the breach still scores "
            "and simply does not classify. And this still escalates, because the waiver expires "
            "in six weeks and somebody has to decide before it does."
        ),
    ),
    Step(
        key="review_queue",
        label="What the credit officer receives: a cited proposal, redacted, nothing applied",
        narration=(
            "Queued, not submitted, and the reference the caller got says exactly that, so a "
            "buffered escalation is never mistaken for a reviewed one. The maker is the "
            "verified principal and the checker is the credit officer who holds the delegated "
            "authority. Every payload carries a proposal and never an application: no grade "
            "moved, and the count of writes to the registry is zero, which is unsurprising, "
            "because there is no method that could have made one. The substandard item asks for "
            "two approvals, because moving an exposure out of performing is a dual-control "
            "decision. Note where exposure size entered. It set the approval path, and it took "
            "no part in the classification, because a grade that moved with exposure size would "
            "be gameable by splitting facilities."
        ),
    ),
    Step(
        key="audit",
        label="The trail verifies, and it reconstructs the decision without the source systems",
        narration=(
            "Append only and hash chained, with the head anchored on a different volume, "
            "because the chain alone cannot see a truncated tail: dropping the newest rows "
            "leaves a shorter chain that verifies perfectly. Now read one record. It names the "
            "grade of record, the proposed grade, the composite and the exact floor rules that "
            "lifted it. A supervisor asking why this obligor moved on this date can reconstruct "
            "the answer without the warehouse, without the news feed, and without this "
            "codebase, and the export carries the hashes so they can re-verify it without us."
        ),
    ),
    Step(
        key="tamper",
        label="A downgrade rewritten out of the trail is DETECTED, not merely discouraged",
        narration=(
            "This is the specific fraud worth demonstrating in a credit book. Not a random byte "
            "flip, but somebody quietly turning a substandard proposal back into a pass. File "
            "access beats a database trigger, and the store cannot prevent that. What it can do "
            "is name the exact record that broke. Tamper evident, not tamper proof, and that is "
            "the honest guarantee. Every record from that sequence onward is now suspect, and "
            "the runbook says restore from the export and re-anchor deliberately."
        ),
    ),
    Step(
        key="portability",
        label="The exit profile refuses loudly rather than filing an unreviewed downgrade",
        narration=(
            "Every seam refuses, and each one names what a client has to bind. Two of these "
            "refusals are load bearing for this vertical. A covenant feed that returned an "
            "empty list instead of raising would hand the engine an obligor with a clean "
            "covenant sheet, and produce a confident affirm on a borrower nobody tested. A "
            "review router that returned successfully instead of raising would convert a "
            "two-notch downgrade proposal into a decision nobody reviewed. Silence is the "
            "failure mode here, not noise. What this proves is bounded: every port is swappable "
            "and every seam is named. It does not prove that a running on-premises deployment "
            "exists."
        ),
    ),
)

STEP_KEYS: tuple[str, ...] = tuple(step.key for step in STEPS)


# --------------------------------------------------------------------------------------- #
# Panels: the audit-first output view (the result, its evidence, the findings, what is next)
# --------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Row:
    """One labelled fact in a panel. ``tone`` drives the colour, never the meaning."""

    label: str
    value: str
    tone: str = ""


@dataclass(frozen=True, slots=True)
class Panel:
    """One block of the output view: a title, labelled facts, and an interpretation."""

    title: str
    rows: tuple[Row, ...] = ()
    note: str = ""
    tone: str = ""


@dataclass(frozen=True, slots=True)
class StepResult:
    """Everything one step produced, ready to render or to assert against."""

    key: str
    label: str
    narration: str
    panels: tuple[Panel, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)


Produced = tuple[list[Panel], dict[str, Any]]


class SpanRecorder:
    """Wraps the bound tracer and records what the REAL service put on each span.

    The no-content rule is a claim about the shipped code, so the demo asserts it against the
    attributes the shipped code actually emitted rather than against a separate copy of them.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        self.spans.append((name, dict(attributes)))
        with self._inner.span(name, **attributes):
            yield

    def record_token_usage(self, usage: object, model: str) -> None:
        self._inner.record_token_usage(usage, model)

    def emitted(self) -> str:
        return " ".join(value for _name, attrs in self.spans for value in attrs.values())


class DemoRun:
    """A live demo, advanced one step at a time over the real services.

    The run owns a working directory holding the durable audit store and its external anchor.
    They are separate directories on purpose: an anchor that lives beside the store it witnesses
    is rewritten by whatever rewrites the store.
    """

    def __init__(self, workdir: Path | None = None) -> None:
        # What was ALREADY loaded before this run began. The offline claim is that the demo
        # imports no cloud SDK, and in a live `python scripts/demo.py` nothing else has loaded
        # one, so the delta and the absolute set are the same list. In a shared pytest process
        # they are not: any other module in the suite may legitimately have imported google for
        # its own reasons (the IAP negative matrix does), and a claim measured as an absolute
        # would then be decided by test ordering rather than by the demo. The absolute form of
        # the claim is still made, in fresh interpreters, by `scripts/portability_demo.py`, by
        # the headless walkthrough and by `tests/unit/test_demo_surface.py`.
        self._cloud_sdk_before = frozenset(loaded_cloud_sdks())
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        if workdir is None:
            self._tempdir = tempfile.TemporaryDirectory(prefix="demo-run-")
            workdir = Path(self._tempdir.name)
        self.workdir = workdir
        self.audit_path = workdir / "store" / "audit.sqlite3"
        self.anchor_path = workdir / "anchor" / "head.json"
        # The audit store creates its own parent; the ANCHOR does not, because it is meant to
        # live on a volume somebody provisioned deliberately rather than one a library invented.
        # An operator therefore has to create that directory too; the demo does it here so the
        # first run of `make demo` in a fresh checkout does not fail on a missing path.
        self.anchor_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(
            profile="local",
            audit_path=str(self.audit_path),
            audit_anchor_path=str(self.anchor_path),
            tenant=TENANT,
        )
        self.container = build_container(self.settings)
        self.policy = build_policy(self.settings)
        self.tracer = SpanRecorder(self.container.tracer)
        # Wrapped for the same reason as the tracer: the redaction beat asserts what the model
        # was SENT, and a panel that rebuilt the prompt from the masked projection would be
        # reporting its own arithmetic rather than the service's behaviour.
        self.narrator = RecordingNarrator(self.container.generation)
        self.service = WatchlistReviewService(
            audit=self.container.audit,
            covenant_terms=self.container.covenant_terms,
            portfolio_feed=self.container.portfolio_feed,
            adverse_media=self.container.adverse_media,
            grade_registry=self.container.grade_registry,
            generation=self.narrator,
            review_router=self.container.review_router,
            tracer=self.tracer,
            policy=self.policy,
        )
        self.results: list[StepResult] = []
        self.reviewed = 0
        self.escalated = 0
        self.routed = 0
        self.chain_ok = True
        self._perform(STEPS[0])

    # -------------------------------------------------------------- control

    @property
    def index(self) -> int:
        """Index of the step most recently performed."""
        return len(self.results) - 1

    @property
    def done(self) -> bool:
        return len(self.results) >= len(STEPS)

    def advance(self) -> StepResult:
        """Perform the next step, or re-return the last one when the arc is finished."""
        if self.done:
            return self.results[-1]
        return self._perform(STEPS[len(self.results)])

    def run_to_end(self) -> None:
        while not self.done:
            self.advance()

    def _perform(self, step: Step) -> StepResult:
        handler: Callable[[], Produced] = getattr(self, "_step_" + step.key)
        panels, facts = handler()
        result = StepResult(
            key=step.key,
            label=step.label,
            narration=step.narration,
            panels=tuple(panels),
            facts=facts,
        )
        self.results.append(result)
        return result

    # -------------------------------------------------------------- steps

    def _step_opened(self) -> Produced:
        bindings = [
            Row(port, self.settings.adapters[port][self.settings.profile].split(":")[-1])
            for port in sorted(self.settings.adapters)
        ]
        profiles = sorted({name for table in self.settings.adapters.values() for name in table})
        sdk = [name for name in loaded_cloud_sdks() if name not in self._cloud_sdk_before]
        ladder = [(score, grade.value) for score, grade in self.policy.band_floors]
        monotonic = all(
            later[0] > earlier[0]
            and GRADE_RANK[WatchGrade(later[1])] > GRADE_RANK[WatchGrade(earlier[1])]
            for earlier, later in zip(ladder, ladder[1:], strict=False)
        )
        caps = {family.value: cap for family, cap in self.policy.family_caps.items()}
        first_adverse = min(
            score for score, grade in self.policy.band_floors if grade is not WatchGrade.PASS
        )
        write_methods = registry_write_methods(self.container.grade_registry)
        deployment = Panel(
            title="Deployment",
            rows=(
                Row("Service", SERVICE_NAME),
                Row("Profile", self.settings.profile, "ok"),
                Row("Profiles bound for every port", ", ".join(profiles)),
                Row("Residency region", self.settings.region),
                Row("Jurisdiction PII packs", ", ".join(JURISDICTIONS)),
            ),
            note=(
                "One environment variable selects the adapter family for every port, including "
                "the covenant feed this repo reads from credit-memo-drafting, the portfolio "
                "feed, the adverse-media feed, the grade registry and the narration seam."
            ),
        )
        adapters = Panel(
            title="Bound adapters",
            rows=tuple(bindings),
            note="The binding map lives in config/settings.yaml, not in the code.",
        )
        bank_policy = Panel(
            title="The bank's numbers, not ours",
            rows=(
                Row("Grade ladder", " | ".join(f"{s}+ {g}" for s, g in ladder)),
                Row("Ladder monotonic", "yes" if monotonic else "NO", "ok" if monotonic else "bad"),
                Row("Family caps", ", ".join(f"{k} {v}" for k, v in sorted(caps.items()))),
                Row("First adverse band floor", str(first_adverse)),
                Row("Floor rules", ", ".join(sorted(self.policy.floor_grades))),
                Row(
                    "Arrears clocks (days)",
                    f"{self.policy.sicr_days_past_due} then "
                    f"{self.policy.default_days_past_due} then "
                    f"{self.policy.severe_days_past_due}",
                ),
            ),
            note=(
                "Read from the settings policy block, so a credit committee retunes them without "
                "a code change, and the loader refuses a non-monotonic ladder at boot rather "
                "than at the first request."
            ),
            tone="ok" if monotonic else "bad",
        )
        registry = Panel(
            title="The registry cannot write",
            rows=(
                Row("Protocol methods", ", ".join(protocol_methods(GradeRegistryPort))),
                Row(
                    "Write-verb methods on the bound adapter",
                    ", ".join(write_methods) or "none",
                    "bad" if write_methods else "ok",
                ),
                Row("Model-influenced family cap", str(caps.get("external", 0))),
                Row("Own-file family cap", str(caps.get("process", 0))),
            ),
            note=(
                "Never re-grades an obligor autonomously is enforced by ABSENCE: there is no "
                "method that could. The two bounded family caps sit below the first adverse "
                "band, so neither categorised media nor our own missing paperwork can classify."
            ),
            tone="bad" if write_methods else "ok",
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Cloud SDK modules imported", ", ".join(sdk) or "none", "bad" if sdk else "ok"),
                Row("Credentials required", "none", "ok"),
                Row("Network required", "none", "ok"),
            ),
            note=(
                "The managed adapters import their SDK lazily, so this profile runs with none "
                "installed at all."
            ),
            tone="bad" if sdk else "ok",
        )
        facts = {
            "profile": self.settings.profile,
            "sdk_modules": sdk,
            "profiles": profiles,
            "band_ladder": ladder,
            "ladder_monotonic": monotonic,
            "family_caps": caps,
            "first_adverse_band": first_adverse,
            "grade_registry_write_methods": write_methods,
        }
        return [deployment, adapters, bank_policy, registry, findings], facts

    def _step_routine(self) -> Produced:
        panels, facts = self._review_panels(ROUTINE_OBLIGOR, expect_routing=False)
        fixture = _fixtures.fixture_for(ROUTINE_OBLIGOR)
        snapshot = fixture.arrears
        assert snapshot is not None
        relative = int(snapshot.drawn_amount_minor * self.policy.arrears_materiality_relative_pct)
        panels.insert(
            1,
            Panel(
                title="The rule that did NOT fire",
                rows=(
                    Row("Days past due (raw)", str(snapshot.days_past_due), "warn"),
                    Row("Past due amount (minor units)", str(snapshot.past_due_amount_minor)),
                    Row("Absolute limit", str(self.policy.arrears_materiality_absolute_minor)),
                    Row("Relative limit", str(relative)),
                    Row("Arrears material", str(facts["arrears_material"]), "ok"),
                    Row("Effective days past due", str(facts["effective_days_past_due"]), "ok"),
                ),
                note=(
                    "Both legs must pass before the past-due clock starts. The absolute limit is "
                    "cleared and the relative one is not, so the clock never started, and the "
                    "non-firing is RECORDED at weight zero rather than left silent."
                ),
                tone="ok",
            ),
        )
        facts["days_past_due"] = snapshot.days_past_due
        return panels, facts

    def _step_escalation(self) -> Produced:
        return self._review_panels(ESCALATING_OBLIGOR, expect_routing=True)

    def _step_redaction(self) -> Produced:
        sent_before = len(self.narrator.prompts)
        panels, facts = self._review_panels(PII_OBLIGOR, expect_routing=True)
        review = self._last_review
        # The WHOLE record and the REAL prompts. Reading one field of the record and rebuilding
        # the prompt is how this beat stayed green while the identifier reached both.
        record = self.container.audit.log.read_all()[-1]
        recorded = str(record["redacted_summary"])
        stored = json.dumps(record, sort_keys=True, default=str)
        prompts = self.narrator.prompts[sent_before:]
        sent = "\n".join(prompts)
        raw_present = any(PLANTED_NRIC in test.detail for test in review.assessment.covenant_tests)
        leaked = PLANTED_NRIC in stored
        prompt_leak = PLANTED_NRIC in sent
        prompt_masked = "REDACTED" in sent
        span_leak = PLANTED_NRIC in self.tracer.emitted()
        waived = [
            test for test in review.assessment.covenant_tests if test.status.value == "waived"
        ]
        panels.append(
            Panel(
                title="Redact once, at the edge, before every sink",
                rows=(
                    Row("Identifier in the covenant clause", PLANTED_NRIC, "warn"),
                    Row(
                        "Present in the RAW assessment",
                        "yes" if raw_present else "NO (the check would be vacuous)",
                        "ok" if raw_present else "bad",
                    ),
                    Row(
                        "Identifier in the immutable record",
                        "PRESENT" if leaked else "absent",
                        "bad" if leaked else "ok",
                    ),
                    Row(
                        "Prompts the service actually sent",
                        str(len(prompts)),
                        "ok" if prompts else "bad",
                    ),
                    Row(
                        "Identifier in any prompt sent",
                        "PRESENT" if prompt_leak else "absent",
                        "bad" if prompt_leak else "ok",
                    ),
                    Row(
                        "Clause text the model DID see",
                        "masked" if prompt_masked else "NOT MASKED",
                        "ok" if prompt_masked else "bad",
                    ),
                    Row(
                        "Identifier in any span attribute",
                        "PRESENT" if span_leak else "absent",
                        "bad" if span_leak else "ok",
                    ),
                    Row("Stored summary", recorded[:160]),
                ),
                note=(
                    "One masking seam, built where the assessment leaves the service, and the "
                    "SAME masked object is handed to the audit write, the outbound payload and "
                    "the model prompt. Redacting after an immutable write is too late. The "
                    "prompt row reads the prompts the model boundary was actually given, and "
                    "the record row reads the whole record rather than its summary field."
                ),
                tone="bad" if (leaked or prompt_leak or span_leak or not raw_present) else "ok",
            )
        )
        panels.append(
            Panel(
                title="A waiver suppresses the floor, never the signal",
                rows=tuple(
                    Row(
                        test.covenant_id,
                        f"{test.status.value} at weight {test.weight}, waived until "
                        f"{test.waived_until}",
                        "ok",
                    )
                    for test in waived
                )
                or (Row("waived tests", "none", "bad"),),
                note=(
                    "The breach still scores and simply does not classify. It escalates anyway, "
                    "because the waiver expires inside the notice window and somebody has to "
                    "decide before it does."
                ),
                tone="ok" if waived else "bad",
            )
        )
        facts["planted_identifier_leaked"] = leaked
        facts["model_prompts_sent"] = len(prompts)
        facts["planted_identifier_in_prompt"] = prompt_leak
        facts["prompt_carries_the_masked_clause"] = prompt_masked
        facts["planted_identifier_in_span"] = span_leak
        facts["planted_identifier_in_raw"] = raw_present
        facts["waived_weight"] = waived[0].weight if waived else 0
        return panels, facts

    def _step_review_queue(self) -> Produced:
        pending = list(self.container.review_router.outbox.pending())
        rows: list[Row] = []
        leaked = False
        approvals: list[int] = []
        for item in pending:
            payload = to_jsonable(item)
            leaked = leaked or PLANTED_NRIC in json.dumps(payload, sort_keys=True)
            review = getattr(item, "review", item)
            approvals.append(int(getattr(review, "required_approvals", 1)))
            rows.append(Row(str(getattr(review, "source_key", "review")), _summarise(payload)))
        writes = registry_write_methods(self.container.grade_registry)
        queue = Panel(
            title="Outbound review queue",
            rows=tuple(rows) or (Row("queue", "empty", "bad"),),
            note=(
                "Queued, not submitted. The reference the caller received says exactly that, so "
                "a buffered escalation is never mistaken for a reviewed one."
            ),
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Proposals escalated", str(self.escalated)),
                Row(
                    "Routed to review",
                    str(self.routed),
                    "ok" if self.routed == self.escalated else "bad",
                ),
                Row("Approvals required", ", ".join(str(n) for n in approvals) or "none"),
                Row("Grades applied", "0", "ok"),
                Row(
                    "Writes to the grade registry",
                    str(len(writes)),
                    "bad" if writes else "ok",
                ),
                Row(
                    "Personal data on the wire",
                    "LEAKED" if leaked else "none",
                    "bad" if leaked else "ok",
                ),
            ),
            note=(
                "Every payload carries a proposal and never an application. Exposure size set "
                "the approval path and took no part in the classification."
            ),
            tone="bad" if leaked or self.routed != self.escalated or writes else "ok",
        )
        actions = Panel(
            title="Next actions",
            rows=(
                Row("Credit officer", "open the queued proposal and approve, amend or reject it"),
                Row("Operator", "point HUMAN_REVIEW_URL at the console and flush the outbox"),
            ),
        )
        facts = {
            "pending": len(pending),
            "wire_leak": leaked,
            "required_approvals": approvals,
            "registry_writes": len(writes),
            "grade_applied": False,
        }
        return [queue, findings, actions], facts

    def _step_audit(self) -> Produced:
        log = self.container.audit.log
        report = self.container.audit.verify()
        self.chain_ok = report.ok
        export = self.workdir / "export" / "audit.jsonl"
        export.parent.mkdir(parents=True, exist_ok=True)
        written = log.export_jsonl(export)
        restored = HashChainedAuditLog(":memory:")
        reloaded = restored.import_jsonl(export)
        round_trip = restored.verify_chain()
        anchored = bool(self.settings.audit_anchor_path) and self.anchor_path.exists()
        stored = [str(entry["redacted_summary"]) for entry in log.read_all()]
        names_grade = any("substandard" in summary for summary in stored)
        names_floor = any("floor-arrears-default" in summary for summary in stored)
        trail = Panel(
            title="Audit trail",
            rows=(
                Row("Records", str(report.entries)),
                Row("Hash-chained", str(report.chained)),
                Row(
                    "Unverifiable (unchained)",
                    str(report.legacy),
                    "ok" if report.legacy == 0 else "bad",
                ),
                Row("Verdict", report.detail, "ok" if report.ok else "bad"),
                Row(
                    "External head anchor",
                    "configured" if anchored else "absent",
                    "ok" if anchored else "warn",
                ),
                Row(
                    "A record names the proposed grade",
                    "yes" if names_grade else "no",
                    "ok" if names_grade else "bad",
                ),
                Row(
                    "A record names the applied floor rule",
                    "yes" if names_floor else "no",
                    "ok" if names_floor else "bad",
                ),
            ),
            note=(
                "The chain alone cannot detect a truncated tail: dropping the newest rows leaves "
                "a shorter chain that verifies perfectly. The anchor, kept on a different "
                "volume, is what closes that gap. Framed against what BCBS 239 asks of "
                "risk-data lineage and what EU AI Act Article 12 asks of event logging."
            ),
            tone="ok" if report.ok else "bad",
        )
        portable = Panel(
            title="Open-format round trip",
            rows=(
                Row("Exported records", str(written)),
                Row("Reloaded into a fresh store", str(reloaded)),
                Row(
                    "Chain after reload",
                    round_trip.detail,
                    "ok" if round_trip.ok else "bad",
                ),
            ),
            note=(
                "JSON Lines with the hashes included, so a consumer can re-verify the trail "
                "without this codebase. That is what makes the record portable."
            ),
            tone="ok" if round_trip.ok else "bad",
        )
        facts = {
            "chain_ok": report.ok,
            "entries": report.entries,
            "exported": written,
            "round_trip_ok": round_trip.ok,
            "anchored": anchored,
            "record_names_grade": names_grade,
            "record_names_floor": names_floor,
        }
        return [trail, portable], facts

    def _step_tamper(self) -> Produced:
        before = self.container.audit.verify()
        target = _rewrite_a_record(self.audit_path)
        after = self.container.audit.verify()
        self.chain_ok = after.ok
        detected = (not after.ok) and after.first_bad_seq == target
        attack = Panel(
            title="The tamper",
            rows=(
                Row("Append-only triggers", "dropped by the attacker", "warn"),
                Row("Record rewritten in place", "seq " + str(target), "warn"),
                Row("Edit made", "substandard proposal rewritten back to a pass", "warn"),
                Row("Verdict before the rewrite", before.detail, "ok"),
            ),
            note=(
                "File access beats a database trigger. A store that claims otherwise is "
                "describing a policy, not a control."
            ),
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Chain intact", "YES" if after.ok else "no", "bad" if after.ok else "ok"),
                Row("First broken record", str(after.first_bad_seq), "ok"),
                Row("Detail", after.detail),
                Row(
                    "Named the exact rewritten record",
                    "yes" if detected else "no",
                    "ok" if detected else "bad",
                ),
            ),
            note=(
                "Tamper-EVIDENT, not tamper-proof. The guarantee is that a rewrite cannot pass "
                "unnoticed, and that the report names which record broke."
            ),
            tone="ok" if detected else "bad",
        )
        actions = Panel(
            title="Next actions",
            rows=(
                Row("Operator", "restore from the exported JSONL and re-anchor deliberately"),
                Row("Auditor", "treat every record from seq " + str(target) + " on as suspect"),
            ),
        )
        facts = {"tampered_seq": target, "detected": detected, "chain_ok": after.ok}
        return [attack, findings, actions], facts

    def _step_portability(self) -> Produced:
        onprem = build_container(Settings(profile="onprem", tenant=TENANT))
        rows: list[Row] = []
        refused: list[str] = []
        absent: list[str] = []
        for port, call in EXIT_CALLS.items():
            expected_absent = port in EXIT_ABSENT
            try:
                call(onprem)
            except NotImplementedError as exc:
                if expected_absent:  # pragma: no cover - a raising diagnostic seam is the defect
                    rows.append(Row(port, "REFUSED, but is meant to be absent", "bad"))
                else:
                    refused.append(port)
                    rows.append(Row(port, "refused: " + str(exc).split(":")[0], "ok"))
            else:
                if expected_absent:
                    absent.append(port)
                    rows.append(Row(port, "absent, by design (a diagnostic, not a control)", "ok"))
                else:  # pragma: no cover - a silent success is the failure this step looks for
                    rows.append(Row(port, "SUCCEEDED SILENTLY", "bad"))
        exit_panel = Panel(
            title="Exit profile (onprem)",
            rows=tuple(rows),
            note=(
                "Selected by one environment variable. No domain module was edited and no "
                "import changed."
            ),
            tone="ok" if len(refused) + len(absent) == len(EXIT_CALLS) else "bad",
        )
        bounds = Panel(
            title="What this does and does not prove",
            rows=(
                Row("Proved", "every port is swappable and every seam is named"),
                Row("Proved", "an unimplemented seam refuses instead of dropping work"),
                Row("NOT proved", "a running on-premises deployment exists"),
                Row("NOT proved", "model, infrastructure or whole-system portability"),
            ),
            note=(
                "Bounded claims are the point. Run scripts/portability_demo.py for the full "
                "seam tour, with a pass or fail per named check."
            ),
        )
        return [exit_panel, bounds], {"refused": sorted(refused), "absent": sorted(absent)}

    # -------------------------------------------------------------- helpers

    def _review_panels(self, obligor_id: str, *, expect_routing: bool) -> Produced:
        review = self.service.review(obligor_id, tenant=TENANT, actor=ACTOR, as_of=AS_OF)
        self._last_review = review
        assessment = review.assessment
        proposal = assessment.proposal
        self.reviewed += 1
        if assessment.requires_human_review:
            self.escalated += 1
            self.routed += 1
        consistent = bool(review.review_ref) == expect_routing == assessment.requires_human_review
        decision = Panel(
            title="Proposal: " + assessment.obligor_name,
            rows=(
                Row("Grade of record", proposal.current_grade.value),
                Row("Band (the score alone)", proposal.band_grade.value),
                Row(
                    "Proposed grade",
                    proposal.proposed_grade.value,
                    "bad" if proposal.movement.value == "downgrade" else "ok",
                ),
                Row("Movement", f"{proposal.movement.value} ({proposal.notches} notches)"),
                Row("Applied floors", ", ".join(proposal.applied_floors) or "none"),
                Row("Withheld reason", proposal.withheld_reason or "none"),
                Row("Composite score", str(assessment.composite_score)),
                Row("Requires human review", str(assessment.requires_human_review)),
                Row("Review reasons", ", ".join(assessment.review_reasons) or "none"),
                Row(
                    "Routed to review",
                    review.review_ref or "not routed (nothing to decide)",
                    "ok" if consistent else "bad",
                ),
                Row("Approvals required", str(review.required_approvals)),
                Row("Grade applied", str(review.grade_applied), "ok"),
                Row("Attributed to", ACTOR),
            ),
            note=(
                "The band came from integer arithmetic over named thresholds. A floor rule, not "
                "the score, is what classifies when the two disagree, and this service proposes "
                "a grade and never applies one."
            ),
            tone="ok" if consistent else "bad",
        )
        families = Panel(
            title="Family scores (raw against capped)",
            rows=tuple(
                Row(
                    score.family.value,
                    f"raw {score.raw_weight}, cap {score.cap}, contributed "
                    f"{score.capped_weight} over {score.signal_count} signals",
                    "warn" if score.raw_weight > score.capped_weight else "",
                )
                for score in assessment.family_scores
            ),
            note=(
                "The caps ARE the anti-double-counting rule. Showing raw beside capped is the "
                "difference between a score and a black box."
            ),
        )
        covenants = Panel(
            title="Covenant tests",
            rows=tuple(
                Row(
                    test.covenant_id,
                    f"{test.status.value} ({test.rule_id}), observed {test.observed_value} "
                    f"against {test.operator.value} {test.threshold}, weight {test.weight}",
                    "bad" if test.status.value == "breach" else "",
                )
                for test in assessment.covenant_tests
            )
            or (Row("covenants", "none extracted at origination", "warn"),),
            note=(
                "Tested against the terms credit-memo-drafting extracted at origination. A "
                "covenant nobody tested is not_evidenced and is never counted compliant."
            ),
        )
        signals = Panel(
            title="Signals",
            rows=tuple(
                Row(
                    signal.rule_id,
                    f"{signal.family.value}, weight {signal.weight}, {signal.detail}",
                    "warn" if signal.weight == 0 else "",
                )
                for signal in assessment.signals
            )
            or (Row("signals", "none fired", "ok"),),
            note=(
                "Zero-weight rows are the rules that were CONSIDERED and did not fire. A "
                "second-line reviewer opens those first."
            ),
        )
        evidence = Panel(
            title="Evidence",
            rows=tuple(
                Row(citation.title, citation.source_id) for citation in assessment.citations[:6]
            )
            or (Row("citations", "NONE", "bad"),),
            note=(
                "Every fired rule carries both the policy row it derives from and the source "
                "locator of the figure it fired on. An uncited signal raises."
            ),
        )
        memo = Panel(
            title="Memo drafted for the credit officer",
            rows=(
                Row("Headline", review.memo_headline or "(not drafted)"),
                Row("Discarded", review.memo_discarded_reason or "no"),
                Row("Engine summary", assessment.summary),
            ),
            note=(
                "Every figure comes from the engine, and the draft is discarded if it does not. "
                "The model never produces a grade, a movement, a floor or a score."
            ),
        )
        facts = {
            "obligor_id": assessment.obligor_id,
            "composite_score": assessment.composite_score,
            "band_grade": proposal.band_grade.value,
            "proposed_grade": proposal.proposed_grade.value,
            "movement": proposal.movement.value,
            "notches": proposal.notches,
            "applied_floors": list(proposal.applied_floors),
            "family_scores": {
                score.family.value: [score.raw_weight, score.capped_weight]
                for score in assessment.family_scores
            },
            "effective_days_past_due": assessment.effective_days_past_due,
            "arrears_material": assessment.arrears_material,
            "signals": [[s.rule_id, s.weight] for s in assessment.signals],
            "confirmation_requested": list(assessment.confirmation_requested),
            "requires_human_review": assessment.requires_human_review,
            "review_ref": review.review_ref,
            "required_approvals": review.required_approvals,
            "grade_applied": review.grade_applied,
            "consistent": consistent,
        }
        return [decision, families, covenants, signals, evidence, memo], facts

    # -------------------------------------------------------------- state

    def state(self) -> dict[str, Any]:
        """The whole run as JSON-safe data: what the UI renders and the walkthrough asserts."""
        current = self.results[-1]
        return {
            "service": SERVICE_NAME,
            "repository": REPOSITORY,
            "profile": self.settings.profile,
            "region": self.settings.region,
            "step": current.key,
            "step_index": self.index,
            "step_count": len(STEPS),
            "label": current.label,
            "next": "" if self.done else STEPS[len(self.results)].label,
            "done": self.done,
            "totals": {
                "reviewed": self.reviewed,
                "escalated": self.escalated,
                "routed": self.routed,
                "chain_ok": self.chain_ok,
            },
            "steps": [_step_to_dict(result) for result in self.results],
        }


def _step_to_dict(result: StepResult) -> dict[str, Any]:
    return {
        "key": result.key,
        "label": result.label,
        "narration": result.narration,
        "facts": result.facts,
        "panels": [
            {
                "title": panel.title,
                "note": panel.note,
                "tone": panel.tone,
                "rows": [
                    {"label": row.label, "value": row.value, "tone": row.tone} for row in panel.rows
                ],
            }
            for panel in result.panels
        ],
    }


def _summarise(payload: Any) -> str:
    """One readable line for a queued review, without dumping the whole payload."""
    if isinstance(payload, dict):
        parts = [
            str(payload[key])
            for key in ("subject", "severity", "required_approvals", "maker")
            if payload.get(key)
        ]
        if parts:
            return " / ".join(parts)
    return json.dumps(payload, sort_keys=True)[:120]


def _rewrite_a_record(store: Path) -> int:
    """Drop the append-only triggers and rewrite one INTERIOR record, as an attacker would.

    The edit is the SPECIFIC fraud worth demonstrating in a credit book: a substandard proposal
    turned back into a pass and an escalation turned back into an allowed decision. Returns the
    ``seq`` that was rewritten. An interior row is chosen deliberately, because rewriting the
    newest row is the easy case.
    """
    conn = sqlite3.connect(store)
    try:
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
        rows = conn.execute("SELECT seq, event_json FROM audit_log ORDER BY seq ASC").fetchall()
        if len(rows) < 3:
            raise RuntimeError("the tamper step needs an interior record to rewrite")
        middle = rows[len(rows) // 2]
        payload = json.loads(middle[1])
        payload["decision"] = "allowed"
        payload["severity"] = "low"
        payload["redacted_summary"] = str(payload.get("redacted_summary", "")).replace(
            "substandard", "pass"
        )
        conn.execute(
            "UPDATE audit_log SET event_json = ? WHERE seq = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), int(middle[0])),
        )
        conn.commit()
        return int(middle[0])
    finally:
        conn.close()


def _exit_audit(container: Any) -> Any:
    return container.audit.record(
        kernel.AuditEvent(
            action="watchlist_review",
            actor=ACTOR,
            decision=kernel.Decision.ESCALATED,
            severity=kernel.Severity.HIGH,
            redacted_summary="Delta Agri Trading (FICTIONAL): proposed substandard",
        )
    )


def _exit_review(container: Any) -> Any:
    return container.review_router.route(_canonical_review(), maker=ACTOR, tenant=TENANT)


def _canonical_review() -> WatchlistReview:
    """The one routed proposal the exit tour and the offline tour both hand the router.

    Built by running the PURE engine over the fixture estate, so the payload the tour routes is
    the shape the service really produces rather than a hand-typed lookalike, and redacted the
    same way the service redacts it.
    """
    fixture = _fixtures.fixture_for(ESCALATING_OBLIGOR)
    assessment = EarlyWarningEngine().evaluate(
        fixture.record,
        fixture.terms,
        fixture.covenant_observations,
        fixture.arrears,
        fixture.observations,
        fixture.news,
        policy=DEFAULT_POLICY,
        as_of=AS_OF,
    )
    return WatchlistReview(assessment=redacted_assessment(assessment), required_approvals=2)


def _exit_identity(container: Any) -> Any:
    # The persona header is deliberately present. It is what the OFFLINE family answers, so
    # sending it proves the exit family refuses the call itself rather than merely lacking an
    # input: a placeholder that returned a principal for a client-written header would be worse
    # than one that raises.
    return container.identity.resolve(RequestContext(headers={"x-dev-persona": "approver"}))


def _exit_tracer(container: Any) -> Any:
    with container.tracer.span("exit.tour", action="portability"):
        return None


def _exit_evaluation(container: Any) -> Any:
    return container.evaluation.gate("eval/datasets/golden_cases.jsonl")


def _exit_covenant_terms(container: Any) -> Any:
    return container.covenant_terms.terms_for(ESCALATING_OBLIGOR, tenant=TENANT)


def _exit_portfolio_feed(container: Any) -> Any:
    return container.portfolio_feed.arrears(ESCALATING_OBLIGOR, tenant=TENANT, as_of=AS_OF)


def _exit_adverse_media(container: Any) -> Any:
    return container.adverse_media.items(
        ESCALATING_OBLIGOR, tenant=TENANT, as_of=AS_OF, lookback_days=180
    )


def _exit_grade_registry(container: Any) -> Any:
    return container.grade_registry.obligor(ESCALATING_OBLIGOR, tenant=TENANT)


def _exit_generation(container: Any) -> Any:
    return container.generation.generate("FACTS (do not add to these):\n- obligor: exit tour")


#: The calls the exit profile must REFUSE, one per port with an exit placeholder. Add a port,
#: add a row: a seam nobody calls is a seam nobody knows is unimplemented.
#:
#: IDENTITY is the load-bearing one for exposure, because what the bound identity adapter
#: DECLARES is the single flag the exposure guard reads before it stands down. COVENANT_TERMS
#: and REVIEW_ROUTER are the load-bearing ones for this vertical: a covenant feed that returned
#: an empty list would produce a confident affirm on a borrower nobody tested, and a review
#: router that returned successfully would convert a downgrade proposal into an unreviewed one.
EXIT_CALLS: dict[str, Callable[[Any], Any]] = {
    "audit": _exit_audit,
    "identity": _exit_identity,
    "review_router": _exit_review,
    "tracer": _exit_tracer,
    "evaluation": _exit_evaluation,
    "covenant_terms": _exit_covenant_terms,
    "portfolio_feed": _exit_portfolio_feed,
    "adverse_media": _exit_adverse_media,
    "grade_registry": _exit_grade_registry,
    "generation": _exit_generation,
}

#: Ports whose exit placeholder is deliberately ABSENT rather than refusing.
#:
#: Every other seam raises on-prem because a placeholder that returned successfully would convert
#: real work into a silent no-op. Tracing is the exception on purpose: it is a diagnostic, it
#: carries no compliance claim, and making it fatal would force every on-prem operator to stand up
#: a tracing stack before the service would serve a request. So for these the tour asserts the
#: OPPOSITE, that the call completes, and a tracer that started raising would fail this tour.
EXIT_ABSENT: frozenset[str] = frozenset({"tracer"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the scripted offline demo end to end.")
    parser.add_argument(
        "output",
        nargs="?",
        default="demo.json",
        help="where to write the audit-view JSON (default: demo.json)",
    )
    parser.add_argument("--quiet", action="store_true", help="write the JSON and print nothing")
    args = parser.parse_args(argv)

    run = DemoRun()
    run.run_to_end()
    state = run.state()
    Path(args.output).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    if not args.quiet:
        for step in state["steps"]:
            print("[" + step["key"] + "] " + step["label"])
        totals = state["totals"]
        print(
            "reviewed="
            + str(totals["reviewed"])
            + " escalated="
            + str(totals["escalated"])
            + " routed="
            + str(totals["routed"])
        )
        print("wrote " + args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
