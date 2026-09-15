"""Delaware CourtConnect scraper (courtconnect.courts.delaware.gov).

CourtConnect is Delaware's public Avenu/Neumo "Contexte" portal. It serves
plain, server-rendered HTML with no bot protection, no session state and no
cookies, so it runs under the HTTP driver.

Scope is **appellate**: the Court of Chancery in full, Superior Court sitting
as Delaware's intermediate appellate court, and Common Pleas hearing appeals up
from the Justice of the Peace courts. Delaware's Supreme Court is not on this
portal at all.

Addressing: **speculative case-number enumeration**, and nothing else. The
portal offers three searches -- party name, judgments-against, and the docket
report -- and the first two do not reach the Court of Chancery at all: a party
search restricted to Chancery's ``2A`` case type returns "No records found" for
any name, and the same filter returns nothing for every appellate type tried.
There is no date search, no result list, and no bulk feed. The docket report
takes a bare ``case_id`` and returns the whole case on one page, which makes
walking the number spaces the only route in.

There are **six** such spaces, because Delaware renumbered two of these courts
and because a court's docket can be split by county, month and unit. They share
one entry, ``dockets_by_number``, whose ``DeCaseRange`` param names the space
and the partition and knows how to render ``min`` as that space's case id:

===========================  ==================================  ===========
Space                        Format                              Era
===========================  ==================================  ===========
``chancery``                 ``{YYYY}-{NNNN}``                   2017 ->
``chancery_legacy``          flat integer, max 13013             -> 2016
``superior_appeal``          ``{County}{YY}A-{MM}-{NNN}``        2009 ->
``superior_appeal_archival`` ``S{County}{YY}A-{MM}-{NNN}``       1991-2008
``common_pleas``             ``CPU{unit}-{YY}-{NNNNNN}``         2009 ->
``common_pleas_legacy``      ``U{unit}{YY}-{MM}-{NNN}``          1993-2008
===========================  ==================================  ===========

Two of them mix in cases that are out of scope -- Chancery's legacy integers
share their low end with a few Justice of the Peace cases, and Common Pleas
interleaves JP appeals with ordinary civil claims under one sequence -- so the
step filters on the case-type code the page prints (``_in_scope``). Superior's
``A`` dockets need no filter: that space is appellate by construction.

Flow, all from one request::

    dockets_by_number / docket_by_number
      -> parse_docket_report (priority 2)
           CaseDescriptionParser  -> case metadata
           PartiesParser          -> parties (litigants, judges, attorneys)
           DocketEntriesParser    -> docket entries
           CaseEventsParser       -> scheduled events, as docket entries
           RelatedCasesParser     -> related cases
         -> ParsedData(DeCourtConnectDocket)

There are no documents to download: Chancery's own docket text says the
pleadings are available only through File & ServeXpress (paid) or a courthouse
terminal, and no sampled page linked a file of any kind.

Page extraction lives in the ``parsers`` package; this module keeps the request
building, the soft-404 rule, the truncated-response guard and the court
derivation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.exceptions import TransientException
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
)
from pydantic import model_validator
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import CourtRange

from .models import (
    APPEAL_CASE_TYPES,
    BASE_URL,
    CASE_TYPE_COURTS,
    CHANCERY_SPACES,
    COMMON_PLEAS_UNITS,
    COUNTY_CODES,
    COURT_IDS,
    DOCKET_REPORT_URL,
    LEGACY_CP_SEQUENCE_WIDTH,
    SOFT_404_PHRASE,
    WHOLLY_APPELLATE_SPACES,
    DeCourtConnectDocket,
    DeNumberSpace,
)
from .parsers import (
    CaseDescriptionParser,
    CaseEventsParser,
    DocketEntriesParser,
    PartiesParser,
    RelatedCasesParser,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield

_Yield = DeCourtConnectDocket

#: Default court id to seed each space with. This is the court the space is
#: *expected* to hold; the court actually recorded on a docket is always
#: re-derived from the case-type code the page prints (``_court_for``), which
#: is what keeps the mixed spaces honest.
SPACE_COURTS: dict[DeNumberSpace, str] = {
    DeNumberSpace.CHANCERY: "delch",
    DeNumberSpace.CHANCERY_LEGACY: "delch",
    DeNumberSpace.SUPERIOR_APPEAL: "delsuperct",
    DeNumberSpace.SUPERIOR_APPEAL_ARCHIVAL: "delsuperct",
    DeNumberSpace.COMMON_PLEAS: "delctcompl",
    DeNumberSpace.COMMON_PLEAS_LEGACY: "delctcompl",
}

#: Inclusive year bounds each space was observed to cover (2026-09-14). The
#: upper bound of an open space is the year of last verification, not a limit.
SPACE_YEARS: dict[DeNumberSpace, tuple[int, int]] = {
    DeNumberSpace.CHANCERY: (2017, 2026),
    DeNumberSpace.CHANCERY_LEGACY: (2007, 2016),
    DeNumberSpace.SUPERIOR_APPEAL: (2009, 2026),
    DeNumberSpace.SUPERIOR_APPEAL_ARCHIVAL: (1991, 2008),
    DeNumberSpace.COMMON_PLEAS: (2009, 2026),
    DeNumberSpace.COMMON_PLEAS_LEGACY: (1993, 2008),
}

#: Highest Chancery ``{YYYY}-{NNNN}`` number seen per year as of 2026-09-14.
#: Useful as the ``soft_max`` when seeding a backfill year, and as ``min`` for
#: the current one. Volumes grow steadily: ~1,000/year in 2019 to ~1,500 in
#: 2025.
SEED_HINTS: dict[int, int] = {
    2019: 1000,
    2020: 1100,
    2021: 1100,
    2022: 1200,
    2023: 1300,
    2024: 1300,
    2025: 1507,
    2026: 1100,
}

#: Last number in the pre-2017 Chancery run — case 13013, filed 2016-12-30.
#: ``2017-0001`` is the next Chancery case, so the two spaces abut exactly.
CHANCERY_LEGACY_MAX = 13013

#: Per-space ``gap`` defaults: how many consecutive misses end a probe.
#:
#: Chancery's spaces are near-contiguous (one hole in a 60-wide scan), so the
#: generous value is headroom for a year's sparse tail. Superior's appellate
#: months hold only a handful of cases each and never skipped a number, so a
#: small gap is enough and a large one would waste most of the probe budget on
#: a space that is mostly empty. Common Pleas' six-digit sequences are long and
#: the observed holes larger.
SPACE_GAPS: dict[DeNumberSpace, int] = {
    DeNumberSpace.CHANCERY: 25,
    DeNumberSpace.CHANCERY_LEGACY: 40,
    DeNumberSpace.SUPERIOR_APPEAL: 5,
    DeNumberSpace.SUPERIOR_APPEAL_ARCHIVAL: 5,
    DeNumberSpace.COMMON_PLEAS: 50,
    DeNumberSpace.COMMON_PLEAS_LEGACY: 50,
}

#: The last markup on a complete docket report. The portal occasionally closes
#: a connection mid-body -- one probe out of ~250 came back as a 122-byte
#: fragment of the ``<head>`` with HTTP 200 -- and a truncated page is
#: indistinguishable from a miss by content alone. Checking for the footer
#: turns that into a retry instead of a phantom gap in the number space.
_PAGE_FOOTER_MARKER = 'id="docket-nav"'


class DeCaseRange(CourtRange):
    """One speculative template: a number space, a partition of it, and a run.

    CourtConnect's spaces are partitioned differently from one another — by
    year, by year *and* month *and* county, by unit — so a template names the
    partition it walks and ``min``/``soft_max`` walk the sequence *inside* that
    partition. Seed one per partition; ``from_int`` copies via ``model_copy``,
    so the partition survives the driver's advancement.

    ``court_id`` (from ``CourtRange``) is the court the space is expected to
    hold. It is a seeding label only: the court recorded on each docket comes
    from the case-type code the page prints.
    """

    space: DeNumberSpace
    """Which number space this template walks."""

    year: int | None = None
    """Four-digit filing year. Required by every space except the flat
    Chancery legacy run, which has no year component at all."""

    month: int | None = None
    """Filing month, 1-12. Required by the spaces whose sequence restarts
    monthly (Superior's appellate dockets, legacy Common Pleas)."""

    county: str | None = None
    """Superior Court county letter — ``N``, ``K`` or ``S``."""

    unit: int | None = None
    """Common Pleas unit number — 4, 5 or 6."""

    suffix: str = ""
    """Trailing letters appended to the sequence, used by the legacy Common
    Pleas space.

    There, one monthly sequence is shared between suffixed and unsuffixed ids,
    and the suffix encodes the case type: ``U598-01-0094AP`` is a JP appeal
    (``4M``) while the same number without the suffix does not exist at all,
    and ``U501-05-0047NC`` is a change-of-name petition. Probing for appeals in
    that space therefore means probing the ``AP`` form specifically — see the
    caveat in CC_NOTES.md, this is the least-established of the six spaces."""

    @model_validator(mode="after")
    def _partition_matches_space(self) -> DeCaseRange:
        """Reject a template missing a component its space addresses by.

        Without this a missing ``month`` formats as ``None`` straight into the
        URL and every probe in the seed misses — which the driver reads as a
        legitimately empty partition, so the mistake looks like an answer.
        """
        required: dict[str, object | None] = {}
        if self.space is not DeNumberSpace.CHANCERY_LEGACY:
            required["year"] = self.year
        if self.space in _MONTH_PARTITIONED:
            required["month"] = self.month
        if self.space in _COUNTY_PARTITIONED:
            required["county"] = self.county
        if self.space in _UNIT_PARTITIONED:
            required["unit"] = self.unit

        if missing := sorted(k for k, v in required.items() if v is None):
            raise ValueError(
                f"space {self.space.value!r} is addressed by "
                f"{', '.join(sorted(required))}; missing {', '.join(missing)}"
            )
        if self.month is not None and not 1 <= self.month <= 12:
            raise ValueError(f"month ({self.month}) must be 1-12")
        if self.county is not None and self.county not in COUNTY_CODES:
            raise ValueError(
                f"county ({self.county!r}) must be one of "
                f"{sorted(COUNTY_CODES)}"
            )
        if self.unit is not None and self.unit not in COMMON_PLEAS_UNITS:
            raise ValueError(
                f"unit ({self.unit}) must be one of "
                f"{sorted(COMMON_PLEAS_UNITS)}"
            )
        return self

    def case_id(self) -> str:
        """Render the current ``min`` as the site's ``case_id``."""
        sequence = self.min
        if self.space is DeNumberSpace.CHANCERY:
            return f"{self.year}-{sequence:04d}"
        if self.space is DeNumberSpace.CHANCERY_LEGACY:
            # A flat integer, printed with no padding at all: the site serves
            # "5195" and "13013", never "05195".
            return str(sequence)
        if self.space in _SUPERIOR_APPEAL_SPACES:
            prefix = (
                "S"
                if self.space is DeNumberSpace.SUPERIOR_APPEAL_ARCHIVAL
                else ""
            )
            return (
                f"{prefix}{self.county}{self.year % 100:02d}A"
                f"-{self.month:02d}-{sequence:03d}"
            )
        if self.space is DeNumberSpace.COMMON_PLEAS:
            return f"CPU{self.unit}-{self.year % 100:02d}-{sequence:06d}"
        width = LEGACY_CP_SEQUENCE_WIDTH[self.unit]
        return (
            f"U{self.unit}{self.year % 100:02d}"
            f"-{self.month:02d}-{sequence:0{width}d}{self.suffix}"
        )


#: Spaces whose sequence restarts every month.
_MONTH_PARTITIONED = frozenset(
    {
        DeNumberSpace.SUPERIOR_APPEAL,
        DeNumberSpace.SUPERIOR_APPEAL_ARCHIVAL,
        DeNumberSpace.COMMON_PLEAS_LEGACY,
    }
)

#: Spaces addressed by a Superior Court county letter.
_COUNTY_PARTITIONED = frozenset(
    {
        DeNumberSpace.SUPERIOR_APPEAL,
        DeNumberSpace.SUPERIOR_APPEAL_ARCHIVAL,
    }
)

#: Spaces addressed by a Common Pleas unit number.
_UNIT_PARTITIONED = frozenset(
    {
        DeNumberSpace.COMMON_PLEAS,
        DeNumberSpace.COMMON_PLEAS_LEGACY,
    }
)

#: The two forms of Superior Court's appellate docket.
_SUPERIOR_APPEAL_SPACES = frozenset(
    {
        DeNumberSpace.SUPERIOR_APPEAL,
        DeNumberSpace.SUPERIOR_APPEAL_ARCHIVAL,
    }
)


def seed_templates(
    space: DeNumberSpace,
    years: Iterable[int] | None = None,
    *,
    soft_max: int | None = None,
    gap: int | None = None,
    should_advance: bool = True,
) -> list[dict]:
    """Build the ``dockets_by_number`` seed list for one number space.

    A space partitioned by county *and* month needs 36 templates per year, so
    writing them by hand is impractical — this expands the partition grid
    instead. Returns plain dicts ready to drop into a run's ``seed_params``::

        seed_params = [
            {"dockets_by_number": {"docket_number": t}}
            for t in seed_templates(DeNumberSpace.SUPERIOR_APPEAL)
        ]

    ``years`` defaults to the observed span of the space (``SPACE_YEARS``).
    ``soft_max`` defaults per space to something a little past the largest run
    seen, so the initial seed covers a typical partition and speculation only
    has to extend an unusually busy one.
    """
    first, last = SPACE_YEARS[space]
    years = list(years) if years is not None else list(range(first, last + 1))
    gap = SPACE_GAPS[space] if gap is None else gap
    ceiling = _DEFAULT_SOFT_MAX[space] if soft_max is None else soft_max
    base = {
        "space": space.value,
        "court_id": SPACE_COURTS[space],
        "min": 1,
        "soft_max": ceiling,
        "gap": gap,
        "should_advance": should_advance,
    }

    if space is DeNumberSpace.CHANCERY_LEGACY:
        # One flat run, no partitions -- the whole space is a single template.
        return [{**base, "soft_max": CHANCERY_LEGACY_MAX + 1}]
    if space is DeNumberSpace.CHANCERY:
        return [
            {**base, "year": year, "soft_max": SEED_HINTS.get(year, ceiling)}
            for year in years
        ]
    if space in _SUPERIOR_APPEAL_SPACES:
        return [
            {**base, "year": year, "month": month, "county": county}
            for year in years
            for county in COUNTY_CODES
            for month in range(1, 13)
        ]
    if space is DeNumberSpace.COMMON_PLEAS:
        return [
            {**base, "year": year, "unit": unit}
            for year in years
            for unit in COMMON_PLEAS_UNITS
        ]
    # Legacy Common Pleas. Seeded with the ``AP`` suffix, because that is how
    # an appeal is addressed there: the unsuffixed form of the same number does
    # not exist. Most probes in a month will miss -- appeals are a minority of
    # a shared sequence -- so this space is a sweep with ``should_advance``
    # off, not a walk that can detect its own end.
    return [
        {**base, "year": year, "unit": unit, "month": month, "suffix": "AP"}
        for year in years
        for unit in COMMON_PLEAS_UNITS
        for month in range(1, 13)
    ]


#: Initial seed ceiling per space, a little above the largest run observed:
#: ~1,500 Chancery cases in a year, ~10 Superior appeals in a county-month,
#: ~8,000 Common Pleas cases in a unit-year.
_DEFAULT_SOFT_MAX: dict[DeNumberSpace, int] = {
    DeNumberSpace.CHANCERY: 1600,
    DeNumberSpace.CHANCERY_LEGACY: CHANCERY_LEGACY_MAX + 1,
    DeNumberSpace.SUPERIOR_APPEAL: 15,
    DeNumberSpace.SUPERIOR_APPEAL_ARCHIVAL: 15,
    DeNumberSpace.COMMON_PLEAS: 8000,
    DeNumberSpace.COMMON_PLEAS_LEGACY: 2000,
}


class DeCourtConnectScraper(BaseScraper[_Yield]):
    """Scraper for Delaware CourtConnect (Court of Chancery dockets)."""

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS)
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-09-14"
    last_verified: ClassVar[str] = "2026-09-14"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Entry points (§4)
    # =========================================================================

    @entry(DeCourtConnectDocket)
    def dockets_by_number(self, docket_number: DeCaseRange) -> Request:
        """Speculatively fetch one docket from any of the portal's spaces.

        One entry covers all six number spaces (SCRAPER_STANDARDS §4 prefers a
        single canonical entry with the court carried in the speculative
        param). It has to be one entry rather than six: a speculative entry is
        dispatched with **only** its speculative param, so the space cannot be
        a separate argument — it rides in ``DeCaseRange.space``, which also
        decides how ``min`` is formatted into a case id.

        Seed with :func:`seed_templates`, which expands each space's partition
        grid — 36 templates per year for the county-and-month-partitioned
        Superior appellate dockets::

            seed_params = [
                {"dockets_by_number": {"docket_number": template}}
                for space in (DeNumberSpace.CHANCERY,
                              DeNumberSpace.SUPERIOR_APPEAL)
                for template in seed_templates(space)
            ]

        A **closed** partition is a finite set, so backfills are best seeded
        ``should_advance: False`` — otherwise each one spends a ``gap``-length
        tail proving what the calendar already settled.
        """
        return self._docket_report_request(
            docket_number.case_id(),
            court=docket_number.court_id,
            entry_point="dockets_by_number",
            space=docket_number.space,
        )

    @entry(DeCourtConnectDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Fetch one already-known case by its site case id.

        Accepts any id the portal serves, not just Chancery's: ``court_id``
        supplies the court, so a Superior Court (``N22C-09-501``) or Justice of
        the Peace (``JP17-20-002897``) id works too. Only the record's
        ``court`` differs -- the page shape is identical across courts.

        A generator, unlike the speculative entry above: the driver seeds a
        plain entry with ``yield from``, so returning a bare ``Request`` fails
        with "'Request' object is not iterable".
        """
        yield self._docket_report_request(
            docket_number,
            court=court_id,
            entry_point="docket_by_number",
            space=None,
        )

    def _docket_report_request(
        self,
        docket_number: str,
        *,
        court: str,
        entry_point: str,
        space: DeNumberSpace | None,
    ) -> Request:
        """Build the one request a case needs.

        ``begin_date``/``end_date`` bound the docket-entry window and are sent
        empty. They are sent at all because the site's own form always sends
        them; passing a populated window made no difference to the entries
        returned in testing, so they are not used to page or filter.
        """
        params = {
            "backto": "D",
            "case_id": docket_number,
            "begin_date": "",
            "end_date": "",
        }
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET, url=DOCKET_REPORT_URL, params=params
            ),
            continuation=self.parse_docket_report,
            reseedable=True,
            accumulated_data={
                "docket_number": docket_number,
                "court": court,
                "entry_point": entry_point,
                "space": space.value if space is not None else None,
            },
            deduplication_key=f"docket_report:{docket_number}",
        )

    # =========================================================================
    # Step: the docket report (the whole case, one page)
    # =========================================================================

    @step(priority=2)
    def parse_docket_report(
        self, page: PageElement, response: Response, accumulated_data: dict
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse all four sections of the report and emit one docket."""
        body = response.text or ""
        if _PAGE_FOOTER_MARKER not in body:
            raise TransientException(
                "docket report body ended before the page footer "
                f"({_PAGE_FOOTER_MARKER!r} absent) for case "
                f"{accumulated_data['docket_number']}"
            )
        if SOFT_404_PHRASE in body.lower():
            # ``actually_successful`` already told the speculation tracker this
            # probe missed, but the driver runs the continuation either way --
            # so the miss has to be recognised here too, or every probe past
            # the end of a year raises on the absent Case Description table.
            return

        docket_data = CaseDescriptionParser()(page)[0].raw_data
        parties = [party.raw_data for party in PartiesParser()(page)]
        entries = [row.raw_data for row in DocketEntriesParser()(page)]
        entries += [row.raw_data for row in CaseEventsParser()(page)]
        related = [row.raw_data for row in RelatedCasesParser()(page)]

        # The page prints the case id twice -- once in the Report Selection
        # Criteria block (echoing the request) and once in the Case
        # Description block. The parser reads the second; falling back to the
        # requested id keeps the record addressable if the court ever stops
        # printing it.
        requested_number = accumulated_data["docket_number"]
        if not docket_data.get("docket_number"):
            docket_data["docket_number"] = requested_number
            docket_data["docket_number_raw"] = requested_number

        filing_dates = [
            row["date_filed"]
            for row in entries
            if row.get("date_filed") is not None
        ]

        case_type_code = docket_data.get("case_type_code")
        court = self._court_for(case_type_code, accumulated_data["court"])
        if not self._in_scope(
            accumulated_data.get("space"), court, case_type_code
        ):
            # A hit, but not a case we collect -- a JP case sharing Chancery's
            # legacy integers, or a first-instance Common Pleas claim sitting
            # in the same sequence as the JP appeals. Emitting nothing here
            # still lets speculation count the probe as a success and keep
            # walking, which is what we want: the partition is not exhausted,
            # this case just is not ours.
            return

        docket_data.update(
            court=court,
            assigned_to_str=self._assigned_judge(parties),
            date_last_filing=max(filing_dates, default=None),
            parties=parties,
            docket_entries=entries,
            related_cases=related,
            source_url=response.url,
            source_entry_point=accumulated_data["entry_point"],
        )
        yield ParsedData(DeCourtConnectDocket.raw(**docket_data))

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _in_scope(
        space: str | None, court: str, case_type_code: str | None
    ) -> bool:
        """Decide whether a fetched case is one this scraper collects.

        Scope is **appellate**: Chancery in full, Superior Court sitting as
        Delaware's intermediate appellate court, and Common Pleas hearing
        appeals up from the Justice of the Peace courts. How that is tested
        depends on how cleanly the space separates:

        * Superior's ``A`` dockets are appellate by construction -- the whole
          space qualifies, no test needed.
        * Chancery's two spaces are wanted in full as a *court*. The test only
          drops the unrelated Justice of the Peace cases that share the low end
          of the pre-2017 integers.
        * Common Pleas interleaves JP appeals with ordinary civil claims under
          one indistinguishable sequence, so only the appellate case types are
          kept.

        ``docket_by_number`` passes no space (the caller asked for one specific
        case by id, so it is collected whatever it turns out to be).
        """
        if space is None:
            return True
        number_space = DeNumberSpace(space)
        if number_space in WHOLLY_APPELLATE_SPACES:
            return True
        if number_space in CHANCERY_SPACES:
            return court == "delch"
        return (case_type_code or "") in APPEAL_CASE_TYPES

    @staticmethod
    def _court_for(case_type_code: str | None, fallback: str) -> str:
        """Resolve the CourtListener court id for a case.

        The page never names its court; the case-type code's leading character
        is the only signal it carries ("2A" -> Chancery). Where that character
        is one this scraper has verified, it wins -- it is read off the page
        itself, so it stays right even if a number space turns out not to
        belong entirely to the court that seeded it. Otherwise the caller's
        court id stands.
        """
        if case_type_code:
            return CASE_TYPE_COURTS.get(case_type_code[0], fallback)
        return fallback

    @staticmethod
    def _assigned_judge(parties: list[dict]) -> str | None:
        """Read the assigned judge out of the party rows.

        CourtConnect has no judge field: the judge is a party row typed
        ``JUDGE``. Every case sampled had exactly one; if a case ever lists
        several, they are joined so none is silently dropped.
        """
        names = [
            name
            for party in parties
            if (party.get("party_type") or "").upper() == "JUDGE"
            and (name := party.get("name"))
        ]
        return "; ".join(names) or None

    # =========================================================================
    # HTTP status handling (§10)
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Treat the "No case was found." page as the 404 it is.

        An unused case id returns HTTP 200 with the Report Selection Criteria
        block and that one sentence in place of the case, so speculation would
        otherwise never see a miss and never stop advancing.
        """
        return SOFT_404_PHRASE not in (response.text or "").lower()
