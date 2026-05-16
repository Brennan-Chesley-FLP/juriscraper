"""Georgia Court of Appeals Docket Scraper.

Scrapes the public docket-search and opinion-search pages at
https://www.gaappeals.gov/. Both UIs submit GET requests to plain PHP
scripts under ``/wp-content/themes/benjamin/docket/``; everything is
server-rendered HTML with no auth, cookies, or bot protection.

Two entry families:

- ``get_opinions_by_date(date_range: DateRange)`` — date-range opinion
  search. Catches **decided** cases only and yields both a docket-detail
  fetch and an opinion-PDF download per row.
- ``fetch_<letter>_docket(case_id: YearlySpeculativeRange)`` — speculative
  per-letter probes against the case-detail page. One entry per case-type
  letter (A, D, E, I, O) since Kent's speculation system iterates a single
  ``(year, integer)`` axis per ``@entry``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urljoin, urlparse

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import DateRange, YearlySpeculativeRange
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
)
from pyrate_limiter import Duration, Rate

from .models import (
    CASE_TYPE_DESCRIPTIONS,
    GaCoaAttorney,
    GaCoaDocket,
    GaCoaDocketEntry,
    GaCoaOpinion,
    GaCoaSupremeCourtInfo,
    GaCoaTrialCourtInfo,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


SITE_BASE = "https://www.gaappeals.gov"
DOCKET_BASE = f"{SITE_BASE}/wp-content/themes/benjamin/docket"
DETAIL_URL = f"{DOCKET_BASE}/results_one_record.php"
OPINION_SEARCH_URL = f"{DOCKET_BASE}/docketdate/results_all.php"


class GeorgiaCourtOfAppealsScraper(BaseScraper[GaCoaDocket | GaCoaOpinion]):
    """Scraper for the Georgia Court of Appeals docket and opinion search.

    Speaks the site's PHP HTML endpoints directly with httpx. Emits two
    record types:

    - ``GaCoaDocket`` — one per case, with nested entries / attorneys /
      trial-court info.
    - ``GaCoaOpinion`` — one per archived opinion/order PDF (only available
      via the opinion-search path).
    """

    court_ids: ClassVar[set[str]] = {"gactapp"}
    court_url: ClassVar[str] = f"{SITE_BASE}/docket-search/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-02"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(3, Duration.SECOND)]

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(GaCoaDocket)
    def get_opinions_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """Date-range opinion search; yields decided cases in the window."""
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=OPINION_SEARCH_URL,
                params={
                    "OPstartDate": date_range.start.strftime("%m/%d/%Y"),
                    "OPendDate": date_range.end.strftime("%m/%d/%Y"),
                },
            ),
            continuation=self.parse_opinion_search,
            accumulated_data={
                "date_start": date_range.start.isoformat(),
                "date_end": date_range.end.isoformat(),
            },
        )

    @entry(GaCoaDocket)
    def fetch_direct_appeal_docket(
        self, case_id: YearlySpeculativeRange
    ) -> Request:
        """Speculative ``A{YY}A{NNNN}`` lookup (direct appeals)."""
        return self._build_speculative_request(case_id, "A")

    @entry(GaCoaDocket)
    def fetch_discretionary_application_docket(
        self, case_id: YearlySpeculativeRange
    ) -> Request:
        """Speculative ``A{YY}D{NNNN}`` lookup (discretionary applications)."""
        return self._build_speculative_request(case_id, "D")

    @entry(GaCoaDocket)
    def fetch_emergency_motion_docket(
        self, case_id: YearlySpeculativeRange
    ) -> Request:
        """Speculative ``A{YY}E{NNNN}`` lookup (emergency motions)."""
        return self._build_speculative_request(case_id, "E")

    @entry(GaCoaDocket)
    def fetch_interlocutory_application_docket(
        self, case_id: YearlySpeculativeRange
    ) -> Request:
        """Speculative ``A{YY}I{NNNN}`` lookup (interlocutory applications)."""
        return self._build_speculative_request(case_id, "I")

    @entry(GaCoaDocket)
    def fetch_original_proceeding_docket(
        self, case_id: YearlySpeculativeRange
    ) -> Request:
        """Speculative ``A{YY}O{NNNN}`` lookup (original proceedings)."""
        return self._build_speculative_request(case_id, "O")

    def _build_speculative_request(
        self,
        case_id: YearlySpeculativeRange,
        letter: str,
    ) -> Request:
        case_number = f"A{case_id.year % 100:02d}{letter}{case_id.min:04d}"
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=DETAIL_URL,
                params={"docr_case_num": case_number},
            ),
            continuation=self.parse_case_detail,
            accumulated_data={"docket_number": case_number},
            deduplication_key=f"gactapp-case-{case_number}",
        )

    # =========================================================================
    # Soft-404 detection
    # =========================================================================

    def fails_successfully(self, response: Response) -> bool:
        """Return False for the soft-404 the detail page emits.

        The PHP detail page returns HTTP 200 even for invalid case numbers;
        the only reliable marker is an empty heading
        ``<h2>Case Number: </h2>``.
        """
        if response.url and "results_one_record.php" not in response.url:
            return True
        text = response.text or ""
        return not _SOFT_404_PATTERN.search(text)

    # =========================================================================
    # Step 1: opinion-search results
    # =========================================================================

    @step()
    def parse_opinion_search(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[GaCoaDocket | GaCoaOpinion], None, None]:
        """Parse the opinion-search results table.

        For each row, yield (a) a detail fetch deduped on the case number
        and (b) an archive request for the opinion PDF. The judgment date
        and ruling from the row are forwarded into the detail step via
        ``accumulated_data``.
        """
        rows = page.query_xpath(
            "//table[contains(@class, 'search-results')]//tr[td]",
            "opinion result rows",
            min_count=0,
        )
        for row in rows:
            cells = row.query_xpath(".//td", "row cells", min_count=0)
            if len(cells) < 6:
                continue

            case_number = _clean(cells[0].text_content())
            style = _clean(cells[1].text_content())
            judgment_date = _parse_long_date(cells[2].text_content())
            judgment_ruling = _clean(cells[3].text_content())

            pdf_links = cells[5].query_xpath_strings(
                ".//a/@href", "opinion pdf href", min_count=0, max_count=1
            )
            pdf_url = pdf_links[0] if pdf_links else None

            if not case_number:
                continue

            # 1) docket detail fetch — the search page already gives us the
            # judgment metadata, so we forward it along.
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=DETAIL_URL,
                    params={"docr_case_num": case_number},
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "docket_number": case_number,
                    "preview_style": style,
                    "judgment_date": (
                        judgment_date.isoformat() if judgment_date else None
                    ),
                    "judgment_ruling": judgment_ruling,
                },
                deduplication_key=f"gactapp-case-{case_number}",
            )

            # 2) opinion PDF archive (independent record).
            if pdf_url:
                absolute_pdf_url = urljoin(response.url, pdf_url)
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=absolute_pdf_url
                    ),
                    continuation=self.handle_opinion_download,
                    expected_type="pdf",
                    accumulated_data={
                        "case_number": case_number,
                        "judgment_date": (
                            judgment_date.isoformat()
                            if judgment_date
                            else None
                        ),
                        "judgment_ruling": judgment_ruling,
                        "filing_id": _extract_filing_id(absolute_pdf_url),
                    },
                    deduplication_key=f"gactapp-opinion-{case_number}",
                )

    # =========================================================================
    # Step 2: case detail
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[GaCoaDocket], None, None]:
        """Parse the per-case detail HTML into a GaCoaDocket."""
        coa = _parse_kv_table(page, "Court of Appeals Information")
        trial = _parse_kv_table(page, "Trial Court Information")

        # The detail page lists case number at the top of the COA block.
        docket_number = (
            (
                coa.get("Case Number")
                or accumulated_data.get("docket_number")
                or ""
            )
            .strip()
            .upper()
        )
        case_name = (
            coa.get("Style")
            or accumulated_data.get("preview_style")
            or docket_number
        )

        case_type = docket_number[3:4] if len(docket_number) >= 4 else None

        docket = GaCoaDocket(
            docket_number=docket_number,
            court_id="gactapp",
            date_filed=_parse_long_date(coa.get("Docket/Notice Date")),
            case_name=case_name,
            case_type=case_type,
            case_type_description=(
                CASE_TYPE_DESCRIPTIONS.get(case_type) if case_type else None
            ),
            case_status=coa.get("Status"),
            date_remittitur=_parse_long_date(coa.get("Remittitur Date")),
            term=coa.get("Term"),
            supreme_court_transfer=_none_unless_meaningful(
                coa.get("Supreme Court Transfer")
            ),
            calendar_date=_none_unless_meaningful(coa.get("Calendar Date")),
            judgment_date=_parse_iso_date(
                accumulated_data.get("judgment_date")
            ),
            judgment_ruling=accumulated_data.get("judgment_ruling"),
            entries=_parse_entries(page),
            attorneys=_parse_attorneys(page),
            trial_court=_build_trial_court(trial),
            supreme_court=_build_supreme_court(page),
            source_url=response.url,
        )
        yield ParsedData(data=docket)

    # =========================================================================
    # Step 3: opinion download completion
    # =========================================================================

    @step()
    def handle_opinion_download(
        self,
        local_filepath: str | None,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[GaCoaOpinion], None, None]:
        """Emit a GaCoaOpinion record once an opinion PDF has been archived."""
        judgment_date = _parse_iso_date(accumulated_data.get("judgment_date"))
        yield ParsedData(
            data=GaCoaOpinion(
                case_number=accumulated_data["case_number"],
                download_url=response.url,
                filing_id=accumulated_data.get("filing_id"),
                judgment_date=judgment_date,
                judgment_ruling=accumulated_data.get("judgment_ruling"),
                local_path=local_filepath,
            )
        )


# =============================================================================
# Module-level parsing helpers
# =============================================================================

_SOFT_404_PATTERN = re.compile(r"<h2>\s*Case Number:\s*</h2>", re.IGNORECASE)
_FILING_ID_PATTERN = re.compile(r"filingId=([0-9a-fA-F-]+)")

# Values the site uses to mean "this section is empty".
_PLACEHOLDER_VALUES = {"", "none", "n/a"}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    return text or None


def _none_unless_meaningful(value: str | None) -> str | None:
    text = _clean(value)
    if text is None or text.lower() in _PLACEHOLDER_VALUES:
        return None
    return text


def _parse_long_date(value: str | None) -> date | None:
    """Parse a date in the site's display format.

    Handles ``April 15, 2026``, ``January 29,2026`` (note the missing space
    seen on the search-results page), and a couple of other variants.
    Returns None for ``None``, empty strings, or the literal ``None``.
    """
    text = _clean(value)
    if text is None or text.lower() in _PLACEHOLDER_VALUES:
        return None
    # The site sometimes omits a space after the comma ('January 29,2026').
    normalized = re.sub(r",\s*", ", ", text)
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _extract_filing_id(url: str) -> str | None:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    ids = params.get("filingId")
    return ids[0] if ids else None


def _parse_kv_table(page: PageElement, heading: str) -> dict[str, str]:
    """Extract a header→value mapping from the table that follows ``<h3>heading</h3>``.

    The detail page renders each section as an ``<h3>`` followed by a
    ``<table>`` of ``<tr><th>label</th><td>value</td></tr>`` rows. Returns
    ``{}`` if the section is absent.
    """
    rows = page.query_xpath(
        f"//h3[normalize-space()='{heading}']/following-sibling::table[1]//tr",
        f"{heading} rows",
        min_count=0,
    )
    out: dict[str, str] = {}
    for row in rows:
        ths = row.query_xpath(".//th", "row th", min_count=0, max_count=1)
        tds = row.query_xpath(".//td", "row td", min_count=0, max_count=1)
        if not ths or not tds:
            continue
        label = _clean(ths[0].text_content())
        value = _clean(tds[0].text_content())
        if label is None:
            continue
        out[label] = value or ""
    return out


def _parse_entries(page: PageElement) -> list[GaCoaDocketEntry]:
    """Parse the "Filings" and "Court Initiated Actions" tables.

    Both render as alternating ``Filing Date`` / ``Filing`` row pairs
    (header in the first ``<td>``, value in the second). The parser pairs
    them up so each entry carries one date and one description.

    Quirk: the ``<h3>`` heading for both sections lives **inside** the
    table element (invalid but accepted by browsers), so the rows are
    selected via ``ancestor::table[1]`` from the heading rather than
    ``following-sibling::table``.
    """
    entries: list[GaCoaDocketEntry] = []
    for heading, court_initiated in (
        ("Filings, Motions, and Court Actions", False),
        ("Court Initiated Actions", True),
    ):
        rows = page.query_xpath(
            f"//h3[normalize-space()='{heading}']/ancestor::table[1]//tr",
            f"{heading} rows",
            min_count=0,
        )
        pending_date: date | None = None
        for row in rows:
            cells = row.query_xpath(".//td", "row cells", min_count=0)
            if len(cells) < 2:
                continue
            label = _clean(cells[0].text_content())
            value = _clean(cells[1].text_content())
            if label is None:
                continue
            if label == "Filing Date":
                pending_date = _parse_long_date(value)
            elif label == "Filing":
                description = value
                if (
                    description
                    and description.lower() not in _PLACEHOLDER_VALUES
                ):
                    entries.append(
                        GaCoaDocketEntry(
                            date_filed=pending_date,
                            description=description,
                            court_initiated=court_initiated,
                        )
                    )
                pending_date = None
            elif label.lower() in _PLACEHOLDER_VALUES:
                # The ``None / None`` placeholder row used for empty sections.
                continue
    return entries


def _parse_attorneys(page: PageElement) -> list[GaCoaAttorney]:
    """Parse the back-to-back attorney tables under ``Attorney Information``.

    Each row carries a ``<th>`` side label (Appellant/Appellee/...) and a
    ``<td>`` name. Two tables are emitted (one per side) but we union them.
    """
    rows = page.query_xpath(
        "//h3[normalize-space()='Attorney Information']"
        "/following-sibling::table[position()<=2]//tr",
        "attorney rows",
        min_count=0,
    )
    attorneys: list[GaCoaAttorney] = []
    for row in rows:
        ths = row.query_xpath(".//th", "row th", min_count=0, max_count=1)
        tds = row.query_xpath(".//td", "row td", min_count=0, max_count=1)
        if not ths or not tds:
            continue
        side = _clean(ths[0].text_content())
        name = _clean(tds[0].text_content())
        if not name or name.lower() in _PLACEHOLDER_VALUES:
            continue
        attorneys.append(GaCoaAttorney(name=name, side=side))
    return attorneys


def _build_trial_court(
    rows: dict[str, str],
) -> GaCoaTrialCourtInfo | None:
    if not rows:
        return None
    case_number = _clean(rows.get("Case Number"))
    if case_number and case_number.lower() in _PLACEHOLDER_VALUES:
        case_number = None
    info = GaCoaTrialCourtInfo(
        case_number=case_number,
        clerk=_none_unless_meaningful(rows.get("Clerk")),
        judge=_none_unless_meaningful(rows.get("Judge")),
        county=_none_unless_meaningful(rows.get("County")),
        court=_none_unless_meaningful(rows.get("Court")),
        date_appealed_order=_parse_long_date(rows.get("Appealed Order")),
        date_notice_of_appeal=_parse_long_date(rows.get("Notice of Appeal")),
    )
    if all(
        getattr(info, f) is None
        for f in (
            "case_number",
            "clerk",
            "judge",
            "county",
            "court",
            "date_appealed_order",
            "date_notice_of_appeal",
        )
    ):
        return None
    return info


def _build_supreme_court(page: PageElement) -> GaCoaSupremeCourtInfo | None:
    """Parse the "Supreme Court Information" section if non-empty."""
    rows = page.query_xpath(
        "//h3[normalize-space()='Supreme Court Information']"
        "/following-sibling::table[1]//tr",
        "supreme court rows",
        min_count=0,
    )
    raw_rows: list[dict[str, str]] = []
    sc_case_number: str | None = None
    transfer_date: date | None = None
    for row in rows:
        cells = row.query_xpath(".//td|.//th", "row cells", min_count=0)
        if len(cells) < 2:
            continue
        label = _clean(cells[0].text_content())
        value = _clean(cells[1].text_content())
        if not label or label.lower() in _PLACEHOLDER_VALUES:
            continue
        if not value or value.lower() in _PLACEHOLDER_VALUES:
            continue
        raw_rows.append({"label": label, "value": value})
        if label.lower() in {"case number", "sc case number"}:
            sc_case_number = value
        elif "transfer" in label.lower() and "date" in label.lower():
            transfer_date = _parse_long_date(value)
    if not raw_rows:
        return None
    return GaCoaSupremeCourtInfo(
        sc_case_number=sc_case_number,
        transfer_date=transfer_date,
        rows=raw_rows,
    )
