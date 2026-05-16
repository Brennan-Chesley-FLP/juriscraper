"""Oklahoma Appellate Courts Scraper.

Scrapes docket data from the Oklahoma State Courts Network (OSCN) at
www.oscn.net. The OSCN appellate database (`db=appellate`) serves the
Oklahoma Supreme Court, Court of Civil Appeals, Court of Criminal
Appeals, Court on the Judiciary, and the Judicial Ethics Advisory Panel
in a single backend; the actual court for each case is determined by
parsing the case caption heading.

Entry points:
- ``get_dockets`` / ``get_dockets_by_date``: date-range search that pulls
  every appellate case filed in the window via ``Results.aspx``.

Pipeline per case:
- ``parse_search_results`` extracts the case-detail link from each result
  row and yields a request for the appellate case page.
- ``parse_case_detail`` parses the appellate page: case heading, opinion
  citation, parties, attorneys, events, lower-court counts table, and
  every docket entry (with row colour and any attached TIFF/PDF links).
  When the appellate caption hints at a county, it yields a follow-up
  request for the trial-court page; otherwise it emits the docket
  immediately and queues archive downloads for every entry document.
- ``parse_lower_court_case`` parses the trial-court page in the same
  schema and emits the final ``OkDocket`` plus archive requests.
- ``handle_document_download`` is a no-op continuation for archived
  TIFF/PDF documents (the archive path lives with the kent driver's
  archive store).

Cloudflare note: ``curl`` succeeds today, but the user has reported the
occasional Cloudflare interstitial. Each parsing step calls
``_check_cloudflare_interstitial`` which raises ``TransientException``
when it detects the challenge body so the driver retries the request.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.exceptions import (
    ScraperAssumptionException,
    TransientException,
)
from jkent.common.page_element import PageElement
from jkent.common.param_models import DateRange
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    SkipDeduplicationCheck,
)
from pyrate_limiter import Duration, Rate

from .models import (
    COURT_IDS,
    OkAttorney,
    OkDocket,
    OkDocketEntry,
    OkEvent,
    OkLowerCourtCase,
    OkLowerCourtCount,
    OkParty,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://www.oscn.net"
SEARCH_RESULTS_URL = f"{BASE_URL}/dockets/Results.aspx"
CASE_INFO_URL = f"{BASE_URL}/dockets/GetCaseInformation.aspx"
TRACK_CASE_URL_TEMPLATE = (
    "https://app.oscn.net/cases/?act={court}&acn={case_number}"
)

# Default search window when no date range is supplied.
DEFAULT_LOOKBACK_DAYS = 7
# Each search URL hits a single date window — keep it short to stay well
# under any server-side cap.
SEARCH_CHUNK_DAYS = 7
# OSCN caps Results.aspx output at 500 rows regardless of the date
# range; when the warning appears we resume scanning from the latest
# date shown.
RESULTS_CAP = 500
RESULTS_CAP_MARKER = "limited to 500"


class SearchVolumeAssumptionError(ScraperAssumptionException):
    """Raised when an OSCN date-range search returns the 500-row cap on
    a single-day window — meaning more than 500 cases were filed on the
    same day and the date-bisection trick can't subdivide further."""


# Map heading prefix -> CourtListener court_id.
COURT_HEADING_MAP: tuple[tuple[str, str], ...] = (
    ("COURT OF CIVIL APPEALS", "oklacivapp"),
    ("COURT OF CRIMINAL APPEALS", "oklacrimapp"),
    ("COURT ON THE JUDICIARY", "oklacoj"),
    ("JUDICIAL ETHICS ADVISORY PANEL", "oklajeap"),
    ("SUPREME COURT", "okla"),
)

# Oklahoma counties that OSCN exposes as `db={county}` for trial-court
# dockets. Used to detect when a heading suffix is a county hint we can
# follow rather than a COCA division label or unrelated text.
OK_COUNTIES: frozenset[str] = frozenset(
    c.lower()
    for c in (
        "Adair",
        "Alfalfa",
        "Atoka",
        "Beaver",
        "Beckham",
        "Blaine",
        "Bryan",
        "Caddo",
        "Canadian",
        "Carter",
        "Cherokee",
        "Choctaw",
        "Cimarron",
        "Cleveland",
        "Coal",
        "Comanche",
        "Cotton",
        "Craig",
        "Creek",
        "Custer",
        "Delaware",
        "Dewey",
        "Ellis",
        "Garfield",
        "Garvin",
        "Grady",
        "Grant",
        "Greer",
        "Harmon",
        "Harper",
        "Haskell",
        "Hughes",
        "Jackson",
        "Jefferson",
        "Johnston",
        "Kay",
        "Kingfisher",
        "Kiowa",
        "Latimer",
        "LeFlore",
        "Lincoln",
        "Logan",
        "Love",
        "Major",
        "Marshall",
        "Mayes",
        "McClain",
        "McCurtain",
        "McIntosh",
        "Murray",
        "Muskogee",
        "Noble",
        "Nowata",
        "Okfuskee",
        "Oklahoma",
        "Okmulgee",
        "Osage",
        "Ottawa",
        "Pawnee",
        "Payne",
        "Pittsburg",
        "Pontotoc",
        "Pottawatomie",
        "Pushmataha",
        "Roger Mills",
        "Rogers",
        "Seminole",
        "Sequoyah",
        "Stephens",
        "Texas",
        "Tillman",
        "Tulsa",
        "Wagoner",
        "Washington",
        "Washita",
        "Woods",
        "Woodward",
    )
)


class OklahomaScraper(BaseScraper[OkDocket]):
    """Scraper for Oklahoma appellate court dockets via oscn.net.

    Usage:
        # Default: dockets filed in the last 7 days
        scraper = OklahomaScraper()

        # Explicit date range
        params = OklahomaScraper.params()
        params.OkDocket.date_filed.gte = date(2026, 4, 1)
        params.OkDocket.date_filed.lte = date(2026, 4, 30)
        scraper = OklahomaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = "https://www.oscn.net/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-04-30"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Transient / Cloudflare detection
    # =========================================================================

    @staticmethod
    def _check_cloudflare_interstitial(
        response: Response,
        text: str | None = None,
    ) -> None:
        """Raise ``TransientException`` if the response looks like a
        Cloudflare challenge page.

        The OSCN site is normally directly reachable, but the user has
        reported intermittent Cloudflare interstitials. We detect them
        from a combination of:

        * Status 403/503 + ``cf-ray`` response header
        * Body containing ``cdn-cgi/challenge-platform`` / ``cf-error``
        * Title text matching ``Just a moment``, ``Attention Required``,
          or ``Sorry, you have been blocked``

        On a hit we raise ``TransientException`` so the kent driver
        retries the request rather than treating the page as a real
        case-not-found.
        """
        headers = {k.lower(): v for k, v in (response.headers or {}).items()}
        status = response.status_code

        if status in (403, 503) and "cf-ray" in headers:
            raise TransientException(
                f"Cloudflare challenge: HTTP {status} with cf-ray header"
            )

        body = text if text is not None else (response.text or "")
        # Cheap substring checks first — keep parsing avoidable.
        markers = (
            "cdn-cgi/challenge-platform",
            "cf-error-details",
            'id="cf-wrapper"',
            "Just a moment...",
            "Attention Required! | Cloudflare",
            "Sorry, you have been blocked",
        )
        for marker in markers:
            if marker in body:
                raise TransientException(
                    f"Cloudflare interstitial detected (marker: {marker!r})"
                )

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _parse_date(text: str | None) -> date | None:
        """Parse OSCN date strings (``MM/DD/YYYY`` or ``MM-DD-YYYY``)."""
        if not text:
            return None
        text = text.strip()
        if not text or text == "-":
            return None
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _normalize_ws(text: str | None) -> str:
        """Collapse runs of whitespace and trim."""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _court_id_from_heading(cls, heading: str) -> str:
        """Map a case caption heading like ``IN THE SUPREME COURT OF THE
        STATE OF OKLAHOMA`` to a CourtListener court id."""
        upper = heading.upper()
        for prefix, court_id in COURT_HEADING_MAP:
            if prefix in upper:
                return court_id
        # Fall back to Supreme Court — the most common case when the
        # heading is unusual.
        return "okla"

    @staticmethod
    def _county_hint_from_heading(heading: str) -> str | None:
        """Return a likely county name (lowercased) appended to the
        heading, or ``None`` if the trailing token isn't a known county.

        The COCA case caption appends the originating-county / division
        token after ``OKLAHOMA``, e.g. ``... OF THE STATE OF OKLAHOMA
        Tulsa``. We use that as the ``db=`` parameter for trial-court
        lookups when it matches a known Oklahoma county."""
        m = re.search(r"OF\s+OKLAHOMA\s+(.+?)\s*$", heading, re.IGNORECASE)
        if not m:
            return None
        suffix = m.group(1).strip()
        if not suffix:
            return None
        # Try the full suffix and the last whitespace-separated token,
        # since OSCN counties are mostly single words but include
        # "Roger Mills" / "LeFlore" etc.
        candidates = [suffix, suffix.rsplit(None, 1)[-1]]
        for candidate in candidates:
            if candidate.lower() in OK_COUNTIES:
                return candidate.lower()
        return None

    @staticmethod
    def _extract_json_style(text: str) -> dict:
        """Extract the embedded ``<script id="json_style">`` block.

        Returns an empty dict if the block is missing or unparseable.
        The block exposes the canonical case number (which can differ
        from the URL ``number=`` parameter for prefixed case types) and
        the ``court`` token used to build the Track-Case URL.
        """
        m = re.search(
            r'<script[^>]*id="json_style"[^>]*>(.*?)</script>',
            text,
            re.DOTALL,
        )
        if not m:
            return {}
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _row_color(row_html: str) -> str | None:
        """Return the dominant ``<font color="...">`` value in a docket row.

        OSCN repeats the colour across every cell in a row, so the first
        match is typically representative. Returns the hex string without
        the leading ``#``."""
        m = re.search(r'<font[^>]*color="([0-9A-Fa-f]{6})"', row_html)
        return m.group(1).upper() if m else None

    # =========================================================================
    # Search-parameter helpers
    # =========================================================================

    def _get_param_date_range(self) -> tuple[date, date]:
        """Resolve a ``(date_gte, date_lte)`` pair from scraper params."""
        date_gte: date | None = None
        date_lte: date | None = None
        if self._params is not None:
            try:
                proxy = self._params.OkDocket  # type: ignore[attr-defined]
            except AttributeError:
                proxy = None
            if proxy is not None:
                searchable = proxy.get_searchable_fields()
                date_field = searchable.get("date_filed")
                if date_field and date_field.is_set():
                    date_gte = date_field.gte
                    date_lte = date_field.lte
        if date_lte is None:
            date_lte = date.today()
        if date_gte is None:
            date_gte = date_lte - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        return date_gte, date_lte

    def _yield_search_chunks(
        self,
        date_gte: date,
        date_lte: date,
    ) -> Generator[Request, None, None]:
        """Split the date range into ``SEARCH_CHUNK_DAYS`` windows and
        yield one search request per chunk."""
        cur = date_gte
        while cur <= date_lte:
            chunk_end = min(
                cur + timedelta(days=SEARCH_CHUNK_DAYS - 1), date_lte
            )
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=SEARCH_RESULTS_URL,
                    params={
                        "db": "appellate",
                        "FiledDateL": cur.strftime("%m/%d/%Y"),
                        "FiledDateH": chunk_end.strftime("%m/%d/%Y"),
                    },
                ),
                continuation=self.parse_search_results,
                accumulated_data={
                    "search_start": cur.isoformat(),
                    "search_end": chunk_end.isoformat(),
                },
                deduplication_key=SkipDeduplicationCheck(),
            )
            cur = chunk_end + timedelta(days=1)

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(OkDocket)
    def get_dockets(self) -> Generator[Request, None, None]:
        """Date-range scan based on scraper params (defaults to the last
        ``DEFAULT_LOOKBACK_DAYS`` days)."""
        date_gte, date_lte = self._get_param_date_range()
        yield from self._yield_search_chunks(date_gte, date_lte)

    @entry(OkDocket)
    def get_dockets_by_date(
        self,
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Date-range scan with explicit start/end dates."""
        yield from self._yield_search_chunks(date_range.start, date_range.end)

    # =========================================================================
    # Step: parse search results
    # =========================================================================

    @step()
    def parse_search_results(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OkDocket], None, None]:
        """Parse a ``Results.aspx`` table.

        NOTE on Cloudflare: this site is normally directly reachable,
        but the user has reported intermittent Cloudflare interstitials.
        We call ``_check_cloudflare_interstitial`` first so the driver
        retries via ``TransientException`` rather than treating the
        challenge body as a legitimate empty result page.

        NOTE on the 500-row cap: ``Results.aspx`` caps every response at
        500 rows regardless of the requested date range and prints a
        ``limited to 500`` warning when that cap was hit. We always emit
        case-detail Requests for every row on the page; if the warning
        is present we additionally yield a follow-up search Request
        whose start date is the latest date observed on the current
        page (the original end date is preserved). Per-case Requests
        deduplicate on case_number so the boundary day's overlapping
        results are filtered automatically.

        If the cap is hit on a single-day window — i.e. every row on
        the page shares the same filed-date — date bisection has
        nothing to subdivide and we raise
        ``SearchVolumeAssumptionError``.
        """
        self._check_cloudflare_interstitial(response, response.text)

        # Find the date filed per row up front so we can both yield
        # detail requests (using the result_casenumber link) and detect
        # the cap-resume boundary in one pass.
        result_rows = page.query_xpath(
            "//tr[contains(@class, 'resultTableRow')]",
            "search result rows",
            min_count=0,
        )

        case_requests: list[Request] = []
        row_dates: list[date] = []
        seen: set[str] = set()
        for row in result_rows:
            link_nodes = row.query_xpath(
                ".//td[contains(@class, 'result_casenumber')]/a",
                "case-number anchor",
                min_count=0,
                max_count=1,
            )
            date_nodes = row.query_xpath(
                ".//td[contains(@class, 'result_datefiled')]",
                "date filed cell",
                min_count=0,
                max_count=1,
            )
            if not link_nodes:
                continue
            href = link_nodes[0].get_attribute("href")
            if not href:
                continue
            absolute = urljoin(response.url, href)
            if absolute in seen:
                continue
            seen.add(absolute)

            case_number = self._normalize_ws(link_nodes[0].text_content())
            row_date = (
                self._parse_date(date_nodes[0].text_content())
                if date_nodes
                else None
            )
            if row_date is not None:
                row_dates.append(row_date)
            case_requests.append(
                Request(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=absolute,
                    ),
                    continuation=self.parse_case_detail,
                    accumulated_data={"appellate_case_number": case_number},
                    deduplication_key=case_number or absolute,
                )
            )

        yield from case_requests

        # === 500-row cap handling ===
        cap_hit = RESULTS_CAP_MARKER in (response.text or "")
        if not cap_hit:
            return

        if not row_dates:
            # Cap message is present but we couldn't read any dates —
            # treat as a structural surprise rather than silently
            # skipping the rest of the range.
            raise SearchVolumeAssumptionError(
                "Results page reports the 500-row cap but no result "
                "dates were parseable; cannot resume the search.",
                response.url,
            )

        oldest = min(row_dates)
        newest = max(row_dates)
        if oldest == newest:
            # Date bisection can't help — more than 500 cases share a
            # single filed-date.
            raise SearchVolumeAssumptionError(
                f"OSCN returned the 500-row cap on a single-day window "
                f"({oldest.isoformat()}); date bisection cannot "
                f"subdivide further.",
                response.url,
            )

        original_end = date.fromisoformat(accumulated_data["search_end"])
        # Resume from the latest date shown — the user's spec keeps the
        # boundary day inclusive so any cases on that date that didn't
        # fit in the first 500 are picked up. Per-case dedup filters
        # the duplicates from the overlap.
        resume_start = newest
        if resume_start >= original_end:
            # Nothing left to scan; the cap was on the final boundary day.
            return

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=SEARCH_RESULTS_URL,
                params={
                    "db": "appellate",
                    "FiledDateL": resume_start.strftime("%m/%d/%Y"),
                    "FiledDateH": original_end.strftime("%m/%d/%Y"),
                },
            ),
            continuation=self.parse_search_results,
            accumulated_data={
                "search_start": resume_start.isoformat(),
                "search_end": original_end.isoformat(),
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =========================================================================
    # Step: parse appellate case page
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        text: str,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OkDocket], None, None]:
        """Parse a ``GetCaseInformation.aspx`` appellate page.

        NOTE on Cloudflare: the OSCN site has been reported to surface
        Cloudflare interstitials occasionally. ``_check_cloudflare_interstitial``
        runs before any parsing so a challenge body raises
        ``TransientException`` and the driver retries.
        """
        self._check_cloudflare_interstitial(response, text)

        json_style = self._extract_json_style(text)
        case_number = (
            json_style.get("casenumber")
            or accumulated_data.get("appellate_case_number")
            or ""
        )
        cmid = json_style.get("cmid") or None
        court_token = (json_style.get("court") or "APPELLATE").upper()

        # === Heading + court detection ===
        heading_nodes = page.query_xpath(
            "//h2[contains(translate(., 'abcdefghijklmnopqrstuvwxyz',"
            " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'STATE OF OKLAHOMA')]",
            "court heading",
            min_count=0,
            max_count=1,
        )
        heading = (
            self._normalize_ws(heading_nodes[0].text_content())
            if heading_nodes
            else ""
        )
        court_id = self._court_id_from_heading(heading)
        county_hint = self._county_hint_from_heading(heading)

        # === Case caption + classification + filed date + opinion ===
        caption_cells = page.query_xpath(
            "(//h2[contains(., 'OKLAHOMA')]/following-sibling::table[1])"
            "//tr[1]/td",
            "case caption row cells",
            min_count=0,
            max_count=2,
        )
        case_name = ""
        case_classification = None
        date_filed: date | None = None
        opinion_url = None
        opinion_citation = None
        if caption_cells:
            case_name = self._normalize_ws(caption_cells[0].text_content())
        if len(caption_cells) >= 2:
            right_cell = caption_cells[1]
            right_text = right_cell.text_content()
            # Classification is in parens after the case number.
            cls_match = re.search(r"\(([^)]+)\)", right_text)
            if cls_match:
                case_classification = cls_match.group(1).strip()
            filed_match = re.search(
                r"Filed:\s*(\d{1,2}/\d{1,2}/\d{4})", right_text
            )
            if filed_match:
                date_filed = self._parse_date(filed_match.group(1))
            # Opinion link / citation
            opinion_anchors = right_cell.query_xpath(
                ".//a[contains(@href, 'deliverdocument')]",
                "opinion link in caption",
                min_count=0,
                max_count=1,
            )
            if opinion_anchors:
                opinion_url = opinion_anchors[0].get_attribute("href")
                opinion_citation = self._normalize_ws(
                    opinion_anchors[0].text_content()
                )

        # === Track Case URL (built ourselves from json_style) ===
        track_case_url = None
        if case_number:
            track_case_url = TRACK_CASE_URL_TEMPLATE.format(
                court=court_token,
                case_number=case_number,
            )

        # === Parties ===
        parties = self._parse_parties(page)

        # === Attorneys ===
        attorneys = self._parse_attorneys(page)

        # === Events ===
        events = self._parse_events(page)

        # === Lower court counts ===
        lower_court_counts = self._parse_lower_court_counts(page)

        # === Docket entries ===
        entries = self._parse_docket_entries(page, response.url, text)

        docket = OkDocket(
            case_number=case_number,
            court_id=court_id,
            date_filed=date_filed,
            case_name=case_name or case_number,
            case_classification=case_classification,
            cmid=cmid,
            court_name=heading or None,
            parties=parties,
            attorneys=attorneys,
            entries=entries,
            events=events,
            lower_court_counts=lower_court_counts,
            lower_court_case=None,
            opinion_url=opinion_url,
            opinion_citation=opinion_citation,
            track_case_url=track_case_url,
            source_url=response.url,
        )

        # === Decide whether to fetch a lower-court case ===
        lower_case_number: str | None = None
        for lc in lower_court_counts:
            if lc.case_number and lc.case_number != "-":
                lower_case_number = lc.case_number
                break

        if county_hint and lower_case_number:
            lookup_url = (
                f"{CASE_INFO_URL}?db={county_hint}&number={lower_case_number}"
            )
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=lookup_url,
                ),
                continuation=self.parse_lower_court_case,
                accumulated_data={
                    "docket": docket.model_dump(mode="json"),
                    "county": county_hint,
                    "lower_case_number": lower_case_number,
                },
                deduplication_key=f"lc:{county_hint}:{lower_case_number}",
            )
        else:
            # No lower-court fetch — emit the docket and archive requests.
            yield ParsedData(data=docket)
            yield from self._yield_archive_requests(docket)

    # =========================================================================
    # Step: parse trial-court page
    # =========================================================================

    @step()
    def parse_lower_court_case(
        self,
        page: PageElement,
        response: Response,
        text: str,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OkDocket], None, None]:
        """Parse a trial-court ``GetCaseInformation.aspx`` page and
        attach it to the parent appellate docket before yielding.

        NOTE on Cloudflare: same interstitial detection as the appellate
        step — we raise ``TransientException`` on a challenge body so
        the driver retries.
        """
        self._check_cloudflare_interstitial(response, text)

        docket = OkDocket.model_validate(accumulated_data["docket"])
        county = accumulated_data["county"]
        lower_case_number = accumulated_data["lower_case_number"]

        # The presence of a populated ``json_style`` block is the most
        # reliable signal that this is a real OSCN case page (rather
        # than a soft-404 / error stub). Trial-court pages don't repeat
        # the ``IN THE ... COURT OF OKLAHOMA`` heading the appellate
        # pages use.
        lc_json = self._extract_json_style(text)
        if lc_json.get("casenumber"):
            # Caption table sits after the case-tracker script block;
            # reach for the first ``Parties`` heading and back up to the
            # immediately preceding table.
            caption_cells = page.query_xpath(
                "(//h2[normalize-space()='Parties']/preceding::table)[last()]"
                "//tr[1]/td",
                "trial caption row cells",
                min_count=0,
                max_count=2,
            )
            case_name = (
                self._normalize_ws(caption_cells[0].text_content())
                if caption_cells
                else lc_json.get("style")
            )
            date_filed: date | None = None
            if len(caption_cells) >= 2:
                filed_match = re.search(
                    r"Filed:\s*(\d{1,2}/\d{1,2}/\d{4})",
                    caption_cells[1].text_content(),
                )
                if filed_match:
                    date_filed = self._parse_date(filed_match.group(1))

            docket.lower_court_case = OkLowerCourtCase(
                court_db=county,
                case_number=lc_json.get("casenumber") or lower_case_number,
                case_name=case_name,
                date_filed=date_filed,
                parties=self._parse_parties(page),
                attorneys=self._parse_attorneys(page),
                entries=self._parse_docket_entries(page, response.url, text),
                source_url=response.url,
            )

        yield ParsedData(data=docket)
        yield from self._yield_archive_requests(docket)

    # =========================================================================
    # Step: handle archived document downloads
    # =========================================================================

    @step()
    def handle_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OkDocket], None, None]:
        """No-op continuation for archived TIFF/PDF downloads.

        kent's archive store records the file location keyed by the
        ``deduplication_key`` we supply; we don't need to mutate the
        already-emitted ``OkDocket`` here.
        """
        # Empty generator — no further yields required.
        if False:
            yield  # pragma: no cover

    # =========================================================================
    # Section parsers
    # =========================================================================

    def _parse_parties(self, page: PageElement) -> list[OkParty]:
        spans = page.query_xpath(
            "//h2[normalize-space()='Parties']/following-sibling::p[1]"
            "/span[contains(@class, 'parties_party')]",
            "party spans",
            min_count=0,
        )
        parties: list[OkParty] = []
        for span in spans:
            name_nodes = span.query_xpath(
                ".//span[contains(@class, 'parties_partyname')]",
                "party name span",
                min_count=0,
                max_count=1,
            )
            type_nodes = span.query_xpath(
                ".//span[contains(@class, 'parties_type')]",
                "party type span",
                min_count=0,
                max_count=1,
            )
            name = (
                self._normalize_ws(name_nodes[0].text_content())
                if name_nodes
                else self._normalize_ws(span.text_content())
            )
            role = (
                self._normalize_ws(type_nodes[0].text_content())
                if type_nodes
                else None
            )
            if name:
                parties.append(OkParty(name=name, role=role))
        return parties

    @staticmethod
    def _cell_lines(cell: PageElement) -> list[str]:
        """Return the cell's text broken on ``<br>`` boundaries.

        OSCN cells separate attorney address segments with ``<br>`` tags,
        which collapse to nothing inside ``text_content()``. We assemble
        the cell's leading text plus its serialised inner HTML, split on
        ``<br>``, strip remaining markup, and unescape ``&nbsp;``.
        """
        inner = cell.inner_html() or ""
        # ``inner_html`` only iterates over child elements; the cell's
        # leading text node (everything before the first child) lives on
        # the underlying lxml element's ``.text`` attribute.
        leading = ""
        try:
            elem = cell._element._element  # type: ignore[attr-defined]
            leading = elem.text or ""
        except AttributeError:
            leading = ""
        full = leading + inner
        if not full:
            return []
        chunks = re.split(r"(?i)<br\s*/?>", full)
        out: list[str] = []
        for chunk in chunks:
            stripped = re.sub(r"<[^>]+>", "", chunk)
            stripped = stripped.replace("\xa0", " ").replace("&nbsp;", " ")
            stripped = re.sub(r"\s+", " ", stripped).strip()
            if stripped:
                out.append(stripped)
        return out

    def _parse_attorneys(self, page: PageElement) -> list[OkAttorney]:
        rows = page.query_xpath(
            "//h2[normalize-space()='Attorneys']"
            "/following-sibling::table[1]//tbody/tr",
            "attorney rows",
            min_count=0,
        )
        attorneys: list[OkAttorney] = []
        for row in rows:
            cells = row.query_xpath("./td", "attorney row cells", min_count=0)
            if len(cells) < 2:
                continue
            attorney_lines = self._cell_lines(cells[0])
            represented_lines = self._cell_lines(cells[1])
            represented_list = [
                p
                for line in represented_lines
                for p in re.split(r",\s*", line)
                if p
            ]
            if not attorney_lines:
                continue
            name_line = attorney_lines[0]
            bar_match = re.search(r"\(Bar\s*#\s*(\d+)\)", name_line)
            bar_number = bar_match.group(1) if bar_match else None
            name = re.sub(r"\(Bar\s*#\s*\d+\)", "", name_line).strip()
            address = (
                "\n".join(attorney_lines[1:])
                if len(attorney_lines) > 1
                else None
            )
            attorneys.append(
                OkAttorney(
                    name=name,
                    bar_number=bar_number,
                    address=address,
                    represented_parties=represented_list,
                )
            )
        return attorneys

    def _parse_events(self, page: PageElement) -> list[OkEvent]:
        section_text_nodes = page.query_xpath(
            "//h2[contains(translate(., 'abcdefghijklmnopqrstuvwxyz',"
            " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'EVENTS')]"
            "/following-sibling::*[1]",
            "events section",
            min_count=0,
            max_count=1,
        )
        if not section_text_nodes:
            return []
        section = section_text_nodes[0]
        text = self._normalize_ws(section.text_content())
        if not text or text.lower() == "none":
            return []
        # Best-effort: extract any rows from a table, otherwise capture
        # the section as a single descriptive event.
        rows = section.query_xpath(".//tr", "event rows", min_count=0)
        events: list[OkEvent] = []
        for row in rows:
            cells = row.query_xpath("./td", "event cells", min_count=0)
            if not cells:
                continue
            cell_texts = [self._normalize_ws(c.text_content()) for c in cells]
            event_date = next(
                (
                    self._parse_date(t)
                    for t in cell_texts
                    if self._parse_date(t)
                ),
                None,
            )
            description = " | ".join(t for t in cell_texts if t)
            if description:
                events.append(
                    OkEvent(event_date=event_date, description=description)
                )
        if not events and text:
            events.append(OkEvent(event_date=None, description=text))
        return events

    def _parse_lower_court_counts(
        self, page: PageElement
    ) -> list[OkLowerCourtCount]:
        rows = page.query_xpath(
            "//h2[contains(., 'Lower Court')]"
            "/following-sibling::table[1]//tbody/tr",
            "lower court rows",
            min_count=0,
        )
        results: list[OkLowerCourtCount] = []
        for row in rows:
            cells = row.query_xpath(
                "./td", "lower court row cells", min_count=0
            )
            if not cells:
                continue
            values = [self._normalize_ws(c.text_content()) for c in cells]
            # Pad to the expected column count.
            while len(values) < 7:
                values.append("")

            def or_none(v: str) -> str | None:
                return v if v and v != "-" else None

            results.append(
                OkLowerCourtCount(
                    count=or_none(values[0]),
                    case_number=or_none(values[1]),
                    statute=or_none(values[2]),
                    crime=or_none(values[3]),
                    sentence=or_none(values[4]),
                    judge=or_none(values[5]),
                    reporter=or_none(values[6]),
                )
            )
        return results

    def _parse_docket_entries(
        self,
        page: PageElement,
        base_url: str,
        page_text: str,
    ) -> list[OkDocketEntry]:
        rows = page.query_xpath(
            "//tr[contains(@class, 'docketRow')]",
            "docket rows",
            min_count=0,
        )
        # Find each row's HTML in the response text once so we can read
        # the inline ``<font color>`` attribute. Using the page-level
        # body lets us avoid re-serialising the lxml subtree.
        entries: list[OkDocketEntry] = []
        for row in rows:
            cells = row.query_xpath("./td", "docket row cells", min_count=0)
            if len(cells) < 3:
                continue
            date_text = self._normalize_ws(cells[0].text_content())
            code_text = self._normalize_ws(cells[1].text_content())
            description_text = self._normalize_ws(cells[2].text_content())
            count_text = (
                self._normalize_ws(cells[3].text_content())
                if len(cells) > 3
                else ""
            )
            party_text = (
                self._normalize_ws(cells[4].text_content())
                if len(cells) > 4
                else ""
            )
            amount_text = (
                self._normalize_ws(cells[5].text_content())
                if len(cells) > 5
                else ""
            )

            # Strip [BRACKETS] from code if present — keep the inner token.
            code_match = re.match(r"^\[(.+)\]$", code_text)
            code = code_match.group(1) if code_match else code_text or None

            # Document attachments + ID
            doc_id = None
            tiff_url = None
            pdf_url = None
            doc_match = re.search(
                r"Document Available\s*\(#?(\d+)\)", description_text
            )
            if doc_match:
                doc_id = doc_match.group(1)
                description_text = description_text[
                    : doc_match.start()
                ].rstrip()
            anchors = cells[2].query_xpath(".//a", "doc anchors", min_count=0)
            for a in anchors:
                href = a.get_attribute("href")
                if not href:
                    continue
                absolute = urljoin(base_url, href)
                label = (a.text_content() or "").strip().lower()
                if "fmt=tif" in href.lower() or label == "tiff":
                    tiff_url = absolute
                elif "fmt=pdf" in href.lower() or label == "pdf":
                    pdf_url = absolute

            # Row colour — read the row's inner HTML and find the first
            # <font color="..."> token.
            color = None
            try:
                color = self._row_color(row.inner_html() or "")
            except Exception:
                color = None

            entries.append(
                OkDocketEntry(
                    date_filed=self._parse_date(date_text),
                    code=code,
                    description=description_text or None,
                    color=color,
                    count=count_text or None,
                    party=party_text or None,
                    amount=amount_text or None,
                    document_id=doc_id,
                    tiff_url=tiff_url,
                    pdf_url=pdf_url,
                )
            )
        return entries

    # =========================================================================
    # Archive request helpers
    # =========================================================================

    def _yield_archive_requests(
        self, docket: OkDocket
    ) -> Generator[Request, None, None]:
        """Yield archive Requests for every TIFF/PDF discovered on the
        docket (appellate + lower court). Each download dedups on the
        docket case number + document id + format so re-runs reuse the
        archive store."""
        archive_targets: list[tuple[str, str, str]] = []
        for docket_entry in docket.entries:
            if docket_entry.document_id and docket_entry.tiff_url:
                archive_targets.append(
                    (docket_entry.document_id, docket_entry.tiff_url, "tif")
                )
            if docket_entry.document_id and docket_entry.pdf_url:
                archive_targets.append(
                    (docket_entry.document_id, docket_entry.pdf_url, "pdf")
                )
        if docket.lower_court_case is not None:
            for docket_entry in docket.lower_court_case.entries:
                if docket_entry.document_id and docket_entry.tiff_url:
                    archive_targets.append(
                        (
                            docket_entry.document_id,
                            docket_entry.tiff_url,
                            "tif",
                        )
                    )
                if docket_entry.document_id and docket_entry.pdf_url:
                    archive_targets.append(
                        (docket_entry.document_id, docket_entry.pdf_url, "pdf")
                    )

        for doc_id, url, fmt in archive_targets:
            expected_type = "pdf" if fmt == "pdf" else "image"
            yield Request(
                archive=True,
                request=HTTPRequestParams(method=HttpMethod.GET, url=url),
                continuation=self.handle_document_download,
                expected_type=expected_type,
                accumulated_data={
                    "case_number": docket.case_number,
                    "document_id": doc_id,
                    "format": fmt,
                },
                deduplication_key=f"doc:{docket.case_number}:{doc_id}:{fmt}",
            )
