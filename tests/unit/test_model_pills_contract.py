"""The half of the model-pill contract that lives in the BROWSER.

Every served console shows two pills at the top right of every page: the model that answered,
and ``Search`` when it searched (owner decision, 2026-09-23; they replaced the full-width
provenance banner of 2026-08-30). Until the first answer arrives the model pill shows
``generator_model`` from ``/healthz``, with WHERE it runs in its title. The SERVICE half of that
contract -- the profile implies a runtime, the schema carries both fields, the endpoint answers
from the binding the container builds rather than from a literal -- is pinned in
``tests/unit/test_api.py``, and what ANSWERED in ``tests/unit/test_answer_provenance.py``.

This file pins the other half, and the other half is the one that broke under the banner. On
2026-09-04 eight consoles were found to have been rendering NOTHING on every page load: the
component named ``/api/agent``, the same-origin route handler the service template ships, in
trees that ship no such handler. The health call reached a path nothing serves, took the failure
branch, and the failure branch renders nothing -- deliberately, because a pill that guessed would
assert provenance it does not have. A check that cannot fail loudly fails as an ABSENCE, and an
absent pill is exactly what no reviewer notices.

Every service-side assertion was true and green throughout. That is why these live in their own
file: a green service half says nothing about whether a reader ever sees the pill.
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path("ui")

#: The words the model pill puts in its title under ``gcp``, spelled once in the component
#: that owns it. Locating that component by what it SAYS rather than by where it sits is the
#: point: this fleet has kept the same fact in three different places, and a path-keyed check
#: once reported working consoles as having nothing at all.
_WORDING = "running on GCP"

#: Build output and vendored packages are not this console's source.
_NOT_SOURCE = frozenset({"node_modules", ".next", "dist", "out", "coverage"})


def _console_sources() -> list[Path]:
    """Every ``.tsx`` this console actually ships, build output and vendored trees pruned."""
    found: list[Path] = []
    pending = [UI]
    while pending:
        for child in pending.pop().iterdir():
            if child.is_dir():
                if child.name not in _NOT_SOURCE:
                    pending.append(child)
            elif child.suffix == ".tsx":
                found.append(child)
    return sorted(found)


def _pills_source() -> Path:
    """The component that renders the pills, wherever this console keeps it."""
    hits = [p for p in _console_sources() if _WORDING in p.read_text()]
    assert hits, (
        "no component under ui/ renders the provenance wording, so this console states neither "
        "its runtime nor its model at the top of any page"
    )
    assert len(hits) == 1, (
        f"more than one component renders the pills ({[str(p) for p in hits]}), so two pages can "
        "phrase the same fact differently and only one of them can be the one a screenshot "
        "came from"
    )
    return hits[0]


def test_the_pills_are_mounted_in_the_layout_rather_than_in_a_page() -> None:
    """Being at the top of EVERY page is a property of the console, not of any page.

    Mounted per page, the pills are present on the pages somebody remembered and absent on the
    one a screenshot came from -- and the absence is invisible, because they render nothing
    until the service answers anyway. The layout is the only mount that cannot be
    forgotten by adding a route.
    """
    layout = Path("ui/app/layout.tsx")
    assert layout.is_file(), "this console has no root layout, so nothing can be mounted for it"
    owner = _pills_source().stem
    assert owner in layout.read_text(), (
        f"{owner} renders the model pills but the root layout does not reference it, so "
        "the pills reach only the pages that remember to mount them"
    )


def test_the_pills_call_a_base_this_console_actually_serves() -> None:
    """The defect that shipped, stated as an assertion.

    Both architectures are legitimate, so this pins AGREEMENT rather than a literal. A tree with
    ``ui/app/api/agent`` proxies through its own origin and the pills should name that path; a
    tree without one must reach its backend the way the rest of the console does, through the
    ``NEXT_PUBLIC_*`` base resolved once in ``ui/lib/api``. The combination that shipped --
    naming the proxy while having none -- is the only one that is never right.

    Sharing the base is what makes the health call REACHABLE rather than merely tidy: the
    ``connect-src`` the console ships is built from that same value, and a cross-origin
    standalone run is on the service's CORS allowlist because every other call already needs to
    be. A health check on a base of its own would have to earn both of those separately, and
    would be silently refused until it did.
    """
    source = _pills_source()
    pills = source.read_text()
    proxies_through_own_origin = Path("ui/app/api/agent").is_dir()

    assert ('"/api/agent"' in pills) == proxies_through_own_origin, (
        f"{source} names /api/agent but this console has no route handler at ui/app/api/agent, "
        "so the health call reaches nothing and the pills render nothing"
        if not proxies_through_own_origin
        else f"this console ships a /api/agent route handler but {source} does not use it"
    )

    if not proxies_through_own_origin:
        # Either spelling of the same fact: the component may import the resolved base itself,
        # or call the client function that already closes over it. What it must not do is spell
        # a base of its own -- a second, independently resolved origin is how the two drift
        # apart again, and the drift is invisible until a deployment serves through a proxy.
        reaches_the_shared_client = "API_BASE" in pills or re.search(
            r'from\s+"(?:\.\./)+lib/api(?:\.mjs)?"', pills
        )
        assert reaches_the_shared_client, (
            f"{source} must reach its backend through the base the rest of this console reads "
            "(ui/lib/api, which resolves NEXT_PUBLIC_*) rather than spelling one of its own"
        )


def _rule(css: str, selector: str) -> str | None:
    """The body of one CSS rule, or ``None`` when this stylesheet does not carry it."""
    opening = f"{selector} {{"
    if opening not in css:
        return None
    start = css.index(opening)
    return css[start : css.index("}", start)]


def _px(block: str, property_name: str) -> int | None:
    """A single-value px property of ``block``, or ``None`` when the rule does not set it."""
    match = re.search(rf"^\s*{property_name}:\s*(-?\d+)(?:px)?;", block, re.MULTILINE)
    return None if match is None else int(match.group(1))


def test_the_pills_sit_at_the_top_right_inside_the_viewport() -> None:
    """A pill that renders off-screen has satisfied every other assertion in this file.

    The banner this replaced was full-bleed, pulled up by negative margins to cancel ``body``'s
    padding, and in eight trees that arithmetic hoisted it ABOVE the viewport: rendered, right,
    in the DOM on every page load, and visible on none. The pills are fixed to the viewport
    instead, so what is held here is that they are pinned to its top-right corner by a
    non-negative offset, and small enough to sit inside ``body``'s top padding rather than over
    the page's own heading and controls.
    """
    css_path = Path("ui/app/globals.css")
    assert css_path.is_file(), "this console has no root stylesheet"
    css = css_path.read_text()
    assert ".provenance-banner" not in css, "the full-width banner's rule is back"
    rule = _rule(css, ".model-pills")
    assert rule is not None, "the pills carry no rule, so nothing places them at the top right"
    assert re.search(r"^\s*position:\s*fixed;", rule, re.MULTILINE), (
        "the pills are not fixed, so they scroll away or push the page's own chrome down"
    )
    top, right = _px(rule, "top"), _px(rule, "right")
    assert top is not None and right is not None, "the pills are not pinned to the top right"
    assert top >= 0 and right >= 0, (
        f"the pills are offset top={top}px right={right}px, which renders them outside the "
        "viewport where no reader sees the provenance they exist to state"
    )
    body_padding = re.search(r"^\s*padding:\s*(\d+)px", _rule(css, "body") or "", re.MULTILINE)
    assert body_padding is not None, "body carries no top padding for the pills to sit in"
    assert top < int(body_padding.group(1)), (
        "the pills start below body's top padding, so they cover the page's own heading"
    )
