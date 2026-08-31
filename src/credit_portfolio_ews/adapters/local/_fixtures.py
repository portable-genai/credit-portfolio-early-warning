"""The ONE deterministic synthetic estate: obligors, covenants, spreads, arrears and media.

Every offline adapter serves this module, the demo drives it and the eval loads it, so there is
ONE synthetic estate rather than two that look alike and fail in different ways for the same
cause. Nothing here is real: every party announces itself as FICTIONAL, every address is an
``.example`` domain, and the one national id present is a synthetic checksum-valid literal whose
only job is to prove that redaction happened.

The estate is built to exercise the engine's edges rather than to look plausible: a clean
obligor, a single unwaived breach, a live waiver about to expire, an expired one, material
arrears on a spotless covenant sheet, immaterial arrears that must NOT start the clock, a file
nobody evidenced, an unconfirmed insolvency headline, three confirmed ones that must stay under
their cap, and one obligor under a DIFFERENT tenant so the cross-tenant refusal is proved offline
rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ...domain.kernel import Citation
from ...domain.models import (
    AdverseNewsItem,
    ArrearsSnapshot,
    CovenantObservation,
    CovenantOperator,
    CovenantTerm,
    CovenantType,
    NewsCategory,
    NewsRelevance,
    ObligorRecord,
    SignalObservation,
    WatchGrade,
)

#: The tenant the offline estate belongs to, and one other so the 403 path is real.
TENANT = "demo-bank"
OTHER_TENANT = "other-bank"

#: The sweep date every fixture is written against. An explicit date, never a clock.
AS_OF = date(2026, 6, 30)

#: The covenant reporting period under test, and the two metric periods the window carries.
TEST_PERIOD = "FY2026H1"
PERIOD_END = date(2026, 6, 30)
CERTIFICATE_DUE = date(2026, 6, 15)
CERTIFICATE_RECEIVED = date(2026, 6, 10)
LATEST_PERIOD = "2026Q2"
PRIOR_PERIOD = "2026Q1"
LATEST_AS_OF = date(2026, 6, 30)
PRIOR_AS_OF = date(2026, 3, 31)

CURRENCY = "SGD"

#: The declared unit that makes a change rule compare PROPORTIONALLY rather than absolutely.
RATIO = "ratio"


def _doc2_citation(facility_id: str, covenant_id: str) -> Citation:
    """The origination locator, in credit-memo-drafting's own shape.

    A reviewer follows this back to the credit-agreement clause the threshold was extracted
    from, in the OTHER service. That is the whole reason the dependency is a named port.
    """
    return Citation(
        source_id=f"doc2:{facility_id}:{covenant_id}",
        title="Credit agreement covenant schedule (origination extract)",
        snippet="threshold and operator as extracted at origination",
    )


def _term(
    obligor_id: str,
    covenant_id: str,
    kind: CovenantType,
    metric: str,
    threshold: float,
    operator: CovenantOperator,
    description: str,
    *,
    waiver_reference: str = "",
    waiver_expiry: date | None = None,
    consecutive_breaches: int = 0,
    certificate_due_on: date = CERTIFICATE_DUE,
) -> CovenantTerm:
    facility_id = f"fac-{obligor_id.split('-')[1]}-01"
    return CovenantTerm(
        covenant_id=covenant_id,
        facility_id=facility_id,
        obligor_id=obligor_id,
        type=kind,
        description=description,
        metric=metric,
        threshold=threshold,
        operator=operator,
        test_period=TEST_PERIOD,
        period_end=PERIOD_END,
        certificate_due_on=certificate_due_on,
        waiver_reference=waiver_reference,
        waiver_expiry=waiver_expiry,
        consecutive_breaches=consecutive_breaches,
        citations=(_doc2_citation(facility_id, covenant_id),),
    )


def _observed(obligor_id: str, covenant_id: str, value: float) -> CovenantObservation:
    return CovenantObservation(
        covenant_id=covenant_id,
        obligor_id=obligor_id,
        test_period=TEST_PERIOD,
        observed_value=value,
        certificate_received_on=CERTIFICATE_RECEIVED,
        source="compliance-certificate",
        source_ref=f"cert:{obligor_id}:{TEST_PERIOD}",
        citations=(
            Citation(
                source_id=f"cert:{obligor_id}:{covenant_id}:{TEST_PERIOD}",
                title="Compliance certificate",
                snippet="observed value as certified by the borrower",
            ),
        ),
    )


def _series(
    obligor_id: str, metric: str, latest: float, prior: float, unit: str = ""
) -> tuple[SignalObservation, SignalObservation]:
    def one(value: float, period: str, as_of: date) -> SignalObservation:
        return SignalObservation(
            metric=metric,
            value=value,
            period=period,
            as_of=as_of,
            unit=unit,
            source="spreading-system",
            source_ref=f"spread:{obligor_id}:{metric}:{period}",
            citations=(
                Citation(
                    source_id=f"spread:{obligor_id}:{metric}:{period}",
                    title="Financial spread",
                    snippet=f"{metric} for {period}",
                ),
            ),
        )

    return (one(latest, LATEST_PERIOD, LATEST_AS_OF), one(prior, PRIOR_PERIOD, PRIOR_AS_OF))


def _window(
    obligor_id: str,
    *,
    leverage: tuple[float, float] = (2.10, 2.20),
    dscr: tuple[float, float] = (1.92, 1.85),
    current_ratio: tuple[float, float] = (1.60, 1.55),
    ebitda: tuple[float, float] = (4.20, 4.10),
    utilisation: tuple[float, float] = (42.0, 40.0),
    collections: tuple[float, float] = (31.0, 33.0),
) -> tuple[SignalObservation, ...]:
    """The six required metrics over two periods. Defaults are a quiet, healthy obligor."""
    return (
        *_series(obligor_id, "net_debt_to_ebitda", *leverage),
        *_series(obligor_id, "dscr", *dscr),
        *_series(obligor_id, "current_ratio", *current_ratio),
        *_series(obligor_id, "ebitda", *ebitda, unit=RATIO),
        *_series(obligor_id, "revolver_utilisation_pct", *utilisation),
        *_series(obligor_id, "collections_concentration_pct", *collections),
    )


def _arrears(
    obligor_id: str, *, days: int, past_due_minor: int, drawn_minor: int
) -> ArrearsSnapshot:
    return ArrearsSnapshot(
        obligor_id=obligor_id,
        as_of=AS_OF,
        currency=CURRENCY,
        drawn_amount_minor=drawn_minor,
        past_due_amount_minor=past_due_minor,
        days_past_due=days,
        source_ref=f"servicing:{obligor_id}:{AS_OF}",
        citations=(
            Citation(
                source_id=f"servicing:{obligor_id}:{AS_OF}",
                title="Servicing arrears snapshot",
                snippet="drawn and past-due balances from the same snapshot",
            ),
        ),
    )


def _news(
    obligor_id: str,
    item_id: str,
    headline: str,
    *,
    relevance: NewsRelevance,
    category: NewsCategory = NewsCategory.UNCLEAR,
    snippet: str = "",
    classified_by: str = "",
    published_on: date = date(2026, 5, 20),
) -> AdverseNewsItem:
    return AdverseNewsItem(
        item_id=item_id,
        obligor_id=obligor_id,
        headline=headline,
        published_on=published_on,
        citation=Citation(
            source_id=f"media:{item_id}",
            title="Trade press (synthetic corpus)",
            snippet=snippet or headline,
        ),
        relevance=relevance,
        category=category,
        classified_by=classified_by,
        snippet=snippet,
        source_ref=f"media:{item_id}",
    )


def _record(
    obligor_id: str,
    name: str,
    *,
    grade: WatchGrade,
    clean_periods: int,
    exposure_minor: int,
    last_review_on: date | None,
    sector: str = "trade and logistics",
) -> ObligorRecord:
    return ObligorRecord(
        obligor_id=obligor_id,
        name=name,
        sector=sector,
        jurisdiction="SG",
        current_grade=grade,
        exposure_amount_minor=exposure_minor,
        currency=CURRENCY,
        clean_periods=clean_periods,
        last_review_on=last_review_on,
        source="grade-registry",
        citations=(
            Citation(
                source_id=f"registry:{obligor_id}",
                title="Grading system of record",
                snippet="grade of record, read only",
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class ObligorFixture:
    """One obligor's whole evidence set, in the shape the ports hand the engine."""

    record: ObligorRecord
    terms: tuple[CovenantTerm, ...]
    covenant_observations: tuple[CovenantObservation, ...]
    arrears: ArrearsSnapshot | None
    observations: tuple[SignalObservation, ...]
    news: tuple[AdverseNewsItem, ...]
    #: A raw identifier planted in this obligor's evidence, so a redaction assertion has an
    #: independent literal to look for rather than trusting the pattern pack to agree with itself.
    planted_identifier: str


def _alpha() -> ObligorFixture:
    """The baseline: a clean obligor that produces no review at all."""
    obligor_id = "obl-alpha-001"
    planted = "ops@alpha-logistics.example"
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Alpha Logistics Pte Ltd (FICTIONAL)",
            grade=WatchGrade.PASS,
            clean_periods=4,
            exposure_minor=840_000_000,
            last_review_on=date(2026, 3, 31),
        ),
        terms=(
            _term(
                obligor_id,
                "cov-alpha-lev",
                CovenantType.LEVERAGE,
                "net_debt_to_ebitda",
                3.50,
                CovenantOperator.LE,
                f"Maximum net debt to EBITDA, tested half-yearly; notices to {planted}",
            ),
            _term(
                obligor_id,
                "cov-alpha-dscr",
                CovenantType.DSCR,
                "dscr",
                1.25,
                CovenantOperator.GE,
                "Minimum debt-service coverage ratio, tested half-yearly",
            ),
        ),
        covenant_observations=(
            _observed(obligor_id, "cov-alpha-lev", 2.10),
            _observed(obligor_id, "cov-alpha-dscr", 1.92),
        ),
        arrears=_arrears(obligor_id, days=0, past_due_minor=0, drawn_minor=780_000_000),
        observations=_window(obligor_id),
        news=(),
        planted_identifier=planted,
    )


def _beta() -> ObligorFixture:
    """A single unwaived breach: the FLOOR classifies, not the score."""
    obligor_id = "obl-beta-002"
    planted = "treasury@beta-cold.example"
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Beta Cold Chain Holdings (FICTIONAL)",
            grade=WatchGrade.PASS,
            clean_periods=2,
            exposure_minor=1_120_000_000,
            last_review_on=date(2026, 4, 15),
        ),
        terms=(
            _term(
                obligor_id,
                "cov-beta-lev",
                CovenantType.LEVERAGE,
                "net_debt_to_ebitda",
                3.50,
                CovenantOperator.LE,
                f"Maximum net debt to EBITDA; treasury contact {planted}",
                consecutive_breaches=1,
            ),
            _term(
                obligor_id,
                "cov-beta-dscr",
                CovenantType.DSCR,
                "dscr",
                1.25,
                CovenantOperator.GE,
                "Minimum debt-service coverage ratio",
            ),
        ),
        covenant_observations=(
            _observed(obligor_id, "cov-beta-lev", 3.62),
            _observed(obligor_id, "cov-beta-dscr", 1.48),
        ),
        arrears=_arrears(obligor_id, days=0, past_due_minor=0, drawn_minor=980_000_000),
        observations=_window(obligor_id, leverage=(3.62, 3.40), dscr=(1.48, 1.55)),
        news=(),
        planted_identifier=planted,
    )


def _gamma() -> ObligorFixture:
    """A live waiver removes the FLOOR and not the signal, and still reaches a human."""
    obligor_id = "obl-gamma-003"
    planted = "S1234567D"
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Gamma Marine Services Pte Ltd (FICTIONAL)",
            grade=WatchGrade.PASS,
            clean_periods=1,
            exposure_minor=690_000_000,
            last_review_on=date(2026, 2, 15),
            sector="marine services",
        ),
        terms=(
            _term(
                obligor_id,
                "cov-gamma-lev",
                CovenantType.LEVERAGE,
                "net_debt_to_ebitda",
                3.50,
                CovenantOperator.LE,
                "Maximum net debt to EBITDA",
                waiver_reference="WVR-2026-018",
                waiver_expiry=date(2026, 8, 15),
            ),
            _term(
                obligor_id,
                "cov-gamma-tnw",
                CovenantType.TANGIBLE_NET_WORTH,
                "tangible_net_worth",
                1.50,
                CovenantOperator.GE,
                f"Minimum tangible net worth; guarantor of record holds NRIC {planted}",
            ),
        ),
        covenant_observations=(
            _observed(obligor_id, "cov-gamma-lev", 3.70),
            _observed(obligor_id, "cov-gamma-tnw", 2.40),
        ),
        arrears=_arrears(obligor_id, days=0, past_due_minor=0, drawn_minor=520_000_000),
        observations=_window(obligor_id, leverage=(3.70, 3.55)),
        news=(
            _news(
                obligor_id,
                "news-gamma-01",
                "Regional bunkering supplier reports a delivery backlog",
                relevance=NewsRelevance.DISMISSED,
                category=NewsCategory.SUPPLIER_DISTRESS,
                snippet="correspondence to 12 Example Quay, care of desk@gamma-press.example",
            ),
        ),
        planted_identifier=planted,
    )


def _delta() -> ObligorFixture:
    """The consequential case: the cap binds, and the arrears floor sets the grade."""
    obligor_id = "obl-delta-004"
    planted = "counsel@delta-agri.example"
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Delta Agri Trading (FICTIONAL)",
            grade=WatchGrade.PASS,
            clean_periods=0,
            exposure_minor=4_200_000_000,
            last_review_on=date(2026, 1, 31),
            sector="agricultural commodities",
        ),
        terms=(
            _term(
                obligor_id,
                "cov-delta-dscr",
                CovenantType.DSCR,
                "dscr",
                1.25,
                CovenantOperator.GE,
                "Minimum debt-service coverage ratio, tested half-yearly",
                consecutive_breaches=1,
            ),
            _term(
                obligor_id,
                "cov-delta-lev",
                CovenantType.LEVERAGE,
                "net_debt_to_ebitda",
                3.50,
                CovenantOperator.LE,
                "Maximum net debt to EBITDA, tested half-yearly",
            ),
        ),
        covenant_observations=(
            _observed(obligor_id, "cov-delta-dscr", 1.18),
            _observed(obligor_id, "cov-delta-lev", 3.42),
        ),
        arrears=_arrears(
            obligor_id, days=96, past_due_minor=124_000_000, drawn_minor=3_850_000_000
        ),
        observations=_window(
            obligor_id,
            leverage=(3.42, 3.30),
            dscr=(1.18, 1.30),
            current_ratio=(1.22, 1.30),
            ebitda=(3.30, 5.00),
            utilisation=(88.0, 79.0),
            collections=(31.0, 33.0),
        ),
        news=(
            _news(
                obligor_id,
                "news-delta-01",
                "Commodity trader named in a contract dispute",
                relevance=NewsRelevance.UNCONFIRMED,
                category=NewsCategory.LITIGATION,
                snippet=f"filings list counsel at {planted}",
            ),
        ),
        planted_identifier=planted,
    )


def _epsilon() -> ObligorFixture:
    """Material arrears classify an exposure regardless of a spotless covenant sheet."""
    obligor_id = "obl-epsilon-005"
    planted = "rm@epsilon-ceramics.example"
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Epsilon Ceramics (FICTIONAL)",
            grade=WatchGrade.SPECIAL_MENTION,
            clean_periods=0,
            exposure_minor=330_000_000,
            last_review_on=date(2026, 3, 1),
            sector="building materials",
        ),
        terms=(
            _term(
                obligor_id,
                "cov-epsilon-lev",
                CovenantType.LEVERAGE,
                "net_debt_to_ebitda",
                3.50,
                CovenantOperator.LE,
                "Maximum net debt to EBITDA",
            ),
            _term(
                obligor_id,
                "cov-epsilon-dscr",
                CovenantType.DSCR,
                "dscr",
                1.25,
                CovenantOperator.GE,
                "Minimum debt-service coverage ratio",
            ),
        ),
        covenant_observations=(
            _observed(obligor_id, "cov-epsilon-lev", 2.05),
            _observed(obligor_id, "cov-epsilon-dscr", 1.71),
        ),
        arrears=_arrears(obligor_id, days=96, past_due_minor=9_640_000, drawn_minor=310_000_000),
        observations=_window(
            obligor_id, leverage=(2.05, 2.15), dscr=(1.71, 1.68), utilisation=(45.0, 44.0)
        ),
        news=(),
        planted_identifier=planted,
    )


def _zeta() -> ObligorFixture:
    """Downgrade fast, upgrade slow: the upgrade path is entered and refused."""
    obligor_id = "obl-zeta-006"
    planted = "director@zeta-tools.example"
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Zeta Precision Tools Pte Ltd (FICTIONAL)",
            grade=WatchGrade.SPECIAL_MENTION,
            clean_periods=1,
            exposure_minor=975_000_000,
            last_review_on=date(2026, 4, 30),
            sector="precision engineering",
        ),
        terms=(
            _term(
                obligor_id,
                "cov-zeta-lev",
                CovenantType.LEVERAGE,
                "net_debt_to_ebitda",
                3.50,
                CovenantOperator.LE,
                f"Maximum net debt to EBITDA; director contact {planted}",
            ),
            _term(
                obligor_id,
                "cov-zeta-dscr",
                CovenantType.DSCR,
                "dscr",
                1.25,
                CovenantOperator.GE,
                "Minimum debt-service coverage ratio",
            ),
        ),
        covenant_observations=(
            _observed(obligor_id, "cov-zeta-lev", 2.30),
            _observed(obligor_id, "cov-zeta-dscr", 1.80),
        ),
        arrears=_arrears(obligor_id, days=0, past_due_minor=0, drawn_minor=700_000_000),
        observations=_window(obligor_id, leverage=(2.30, 2.35), dscr=(1.80, 1.78)),
        news=(),
        planted_identifier=planted,
    )


def _eta() -> ObligorFixture:
    """The one-notch cap, and dual control on the way OUT of non-performing."""
    obligor_id = "obl-eta-007"
    planted = "finance@eta-textiles.example"
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Eta Textiles (FICTIONAL)",
            grade=WatchGrade.SUBSTANDARD,
            clean_periods=3,
            exposure_minor=510_000_000,
            last_review_on=date(2026, 3, 31),
            sector="textiles",
        ),
        terms=(
            _term(
                obligor_id,
                "cov-eta-lev",
                CovenantType.LEVERAGE,
                "net_debt_to_ebitda",
                3.50,
                CovenantOperator.LE,
                f"Maximum net debt to EBITDA; finance contact {planted}",
            ),
            _term(
                obligor_id,
                "cov-eta-dscr",
                CovenantType.DSCR,
                "dscr",
                1.25,
                CovenantOperator.GE,
                "Minimum debt-service coverage ratio",
            ),
        ),
        covenant_observations=(
            _observed(obligor_id, "cov-eta-lev", 2.15),
            _observed(obligor_id, "cov-eta-dscr", 1.86),
        ),
        arrears=_arrears(obligor_id, days=0, past_due_minor=0, drawn_minor=410_000_000),
        observations=_window(obligor_id, leverage=(2.15, 2.25), dscr=(1.86, 1.80)),
        news=(),
        planted_identifier=planted,
    )


def _theta() -> ObligorFixture:
    """Absence of evidence is never read as evidence of compliance."""
    obligor_id = "obl-theta-008"
    planted = "treasury@theta-marine.example"
    overdue_certificate = date(2026, 4, 20)
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Theta Marine Foods (FICTIONAL)",
            grade=WatchGrade.PASS,
            clean_periods=2,
            exposure_minor=1_460_000_000,
            last_review_on=None,
            sector="seafood processing",
        ),
        terms=(
            _term(
                obligor_id,
                "cov-theta-lev",
                CovenantType.LEVERAGE,
                "net_debt_to_ebitda",
                3.50,
                CovenantOperator.LE,
                f"Maximum net debt to EBITDA; treasury contact {planted}",
                certificate_due_on=overdue_certificate,
            ),
            _term(
                obligor_id,
                "cov-theta-dscr",
                CovenantType.DSCR,
                "dscr",
                1.25,
                CovenantOperator.GE,
                "Minimum debt-service coverage ratio",
                certificate_due_on=overdue_certificate,
            ),
        ),
        covenant_observations=(),
        arrears=_arrears(obligor_id, days=0, past_due_minor=0, drawn_minor=1_100_000_000),
        observations=(
            *_series(obligor_id, "revolver_utilisation_pct", 55.0, 54.0),
            *_series(obligor_id, "collections_concentration_pct", 31.0, 32.0),
        ),
        news=(),
        planted_identifier=planted,
    )


def _iota() -> ObligorFixture:
    """An unconfirmed item is surfaced to a human and can never move a grade."""
    obligor_id = "obl-iota-009"
    planted = "editor@iota-news.example"
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Iota Freight Forwarding (FICTIONAL)",
            grade=WatchGrade.PASS,
            clean_periods=3,
            exposure_minor=280_000_000,
            last_review_on=date(2026, 2, 28),
            sector="freight forwarding",
        ),
        terms=(
            _term(
                obligor_id,
                "cov-iota-lev",
                CovenantType.LEVERAGE,
                "net_debt_to_ebitda",
                3.50,
                CovenantOperator.LE,
                "Maximum net debt to EBITDA",
            ),
            _term(
                obligor_id,
                "cov-iota-dscr",
                CovenantType.DSCR,
                "dscr",
                1.25,
                CovenantOperator.GE,
                "Minimum debt-service coverage ratio",
            ),
        ),
        covenant_observations=(
            _observed(obligor_id, "cov-iota-lev", 1.95),
            _observed(obligor_id, "cov-iota-dscr", 2.05),
        ),
        arrears=_arrears(obligor_id, days=0, past_due_minor=0, drawn_minor=190_000_000),
        observations=_window(obligor_id, leverage=(1.95, 2.00), dscr=(2.05, 2.02)),
        news=(
            _news(
                obligor_id,
                "news-iota-01",
                "Similarly named forwarding agent enters administration",
                relevance=NewsRelevance.UNCONFIRMED,
                category=NewsCategory.INSOLVENCY,
                snippet=f"newsroom contact {planted}",
            ),
        ),
        planted_identifier=planted,
    )


def _kappa() -> ObligorFixture:
    """The falsification case for the materiality gate: 41 days, and the clock never starts."""
    obligor_id = "obl-kappa-010"
    planted = "ar@kappa-bunkering.example"
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Kappa Bunkering Services (FICTIONAL)",
            grade=WatchGrade.PASS,
            clean_periods=3,
            exposure_minor=148_000_000,
            last_review_on=date(2026, 3, 31),
            sector="marine fuels",
        ),
        terms=(
            _term(
                obligor_id,
                "cov-kappa-lev",
                CovenantType.LEVERAGE,
                "net_debt_to_ebitda",
                3.50,
                CovenantOperator.LE,
                f"Maximum net debt to EBITDA; receivables desk {planted}",
            ),
            _term(
                obligor_id,
                "cov-kappa-dscr",
                CovenantType.DSCR,
                "dscr",
                1.25,
                CovenantOperator.GE,
                "Minimum debt-service coverage ratio",
            ),
        ),
        covenant_observations=(
            _observed(obligor_id, "cov-kappa-lev", 2.40),
            _observed(obligor_id, "cov-kappa-dscr", 1.70),
        ),
        arrears=_arrears(obligor_id, days=41, past_due_minor=64_000, drawn_minor=148_000_000),
        observations=_window(obligor_id, leverage=(2.40, 2.45), dscr=(1.70, 1.72)),
        news=(),
        planted_identifier=planted,
    )


def _lambda() -> ObligorFixture:
    """The falsification case for model and feed authority: three confirmed items, capped."""
    obligor_id = "obl-lambda-011"
    planted = "desk@lambda-chem.example"
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Lambda Speciality Chemicals Pte Ltd (FICTIONAL)",
            grade=WatchGrade.PASS,
            clean_periods=2,
            exposure_minor=730_000_000,
            last_review_on=date(2026, 1, 30),
            sector="speciality chemicals",
        ),
        terms=(
            _term(
                obligor_id,
                "cov-lambda-lev",
                CovenantType.LEVERAGE,
                "net_debt_to_ebitda",
                3.50,
                CovenantOperator.LE,
                "Maximum net debt to EBITDA",
            ),
            _term(
                obligor_id,
                "cov-lambda-dscr",
                CovenantType.DSCR,
                "dscr",
                1.25,
                CovenantOperator.GE,
                "Minimum debt-service coverage ratio",
            ),
        ),
        covenant_observations=(
            _observed(obligor_id, "cov-lambda-lev", 2.25),
            _observed(obligor_id, "cov-lambda-dscr", 1.66),
        ),
        arrears=_arrears(obligor_id, days=0, past_due_minor=0, drawn_minor=600_000_000),
        observations=_window(obligor_id, leverage=(2.25, 2.30), dscr=(1.66, 1.64)),
        news=(
            # Uncategorised on arrival, exactly as a live feed delivers them, so the offline
            # profile exercises the same two-stage path (feed confirms, model categorises) the
            # managed one does.
            _news(
                obligor_id,
                "news-lambda-01",
                "Insolvency proceedings opened against a group affiliate",
                relevance=NewsRelevance.CONFIRMED,
                snippet="affiliate filing reported by the trade press",
            ),
            _news(
                obligor_id,
                "news-lambda-02",
                "Litigation filed over a disputed supply contract",
                relevance=NewsRelevance.CONFIRMED,
                snippet=f"press desk {planted}",
            ),
            _news(
                obligor_id,
                "news-lambda-03",
                "Rating downgrade published by a regional agency",
                relevance=NewsRelevance.CONFIRMED,
                snippet="one notch, outlook negative",
            ),
        ),
        planted_identifier=planted,
    )


def _omega() -> ObligorFixture:
    """Another tenant's obligor. Never served to this tenant; the port answers 403, not 404."""
    obligor_id = "obl-omega-999"
    return ObligorFixture(
        record=_record(
            obligor_id,
            "Omega Shipping (FICTIONAL, another tenant)",
            grade=WatchGrade.PASS,
            clean_periods=5,
            exposure_minor=100_000_000,
            last_review_on=date(2026, 5, 1),
        ),
        terms=(),
        covenant_observations=(),
        arrears=None,
        observations=(),
        news=(),
        planted_identifier="",
    )


def _estate() -> dict[str, dict[str, ObligorFixture]]:
    own = (
        _alpha(),
        _beta(),
        _gamma(),
        _delta(),
        _epsilon(),
        _zeta(),
        _eta(),
        _theta(),
        _iota(),
        _kappa(),
        _lambda(),
    )
    return {
        TENANT: {fixture.record.obligor_id: fixture for fixture in own},
        OTHER_TENANT: {_omega().record.obligor_id: _omega()},
    }


#: tenant -> obligor id -> the whole evidence set. Built once; the adapters only read it.
ESTATE: dict[str, dict[str, ObligorFixture]] = _estate()

#: The obligor ids of this tenant's book, in a stable order, for the demo and the eval.
OBLIGOR_IDS: tuple[str, ...] = tuple(ESTATE[TENANT])


def fixture_for(obligor_id: str, tenant: str = TENANT) -> ObligorFixture:
    """The fixture for one obligor, for the demo and the eval. Raises for an unknown id."""
    return ESTATE[tenant][obligor_id]


def find(obligor_id: str, tenant: str) -> ObligorFixture | None:
    """The fixture within ``tenant``, or ``None``. Cross-tenant refusal is the ADAPTER's job."""
    return ESTATE.get(tenant, {}).get(obligor_id)


def belongs_to_another_tenant(obligor_id: str, tenant: str) -> bool:
    """True when the obligor exists, but under a different tenant. The 403 case, never a 404."""
    return any(
        obligor_id in book for other, book in ESTATE.items() if other != tenant
    ) and obligor_id not in ESTATE.get(tenant, {})
