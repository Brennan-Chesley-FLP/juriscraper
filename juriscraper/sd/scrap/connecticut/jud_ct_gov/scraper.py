"""Connecticut Appellate Courts Scraper.

This module contains a unified scraper for opinions, oral arguments, and dockets from
the CT Judicial Branch website for both the Supreme Court and Appellate Court.

Entry points::

    - @entry(ConnOpinionCluster) get_opinions
    - @entry(ConnOralArgument) get_oral_arguments
    - @entry(ConnDocket) fetch_docket (speculative via SpeculativeRange param)

Opinions Flow::

    1. get_opinions -> archive index pages for selected courts
    2. parse_archive_index -> yields requests for each year page
    3. parse_year_page -> parses opinions, yields archive requests for PDFs
    4. handle_opinion_download -> stores local paths, yields final clusters

Oral Arguments Flow::

    1. get_oral_arguments -> oral arguments index page for selected courts
    2. parse_oral_arguments_index -> yields requests for each court year
    3. parse_court_year_page -> parses cases, yields requests to audio player pages
    4. parse_audio_player_page -> extracts MP3 URL, yields archive request
    5. handle_audio_download -> yields final ConnOralArgument

Dockets Flow::

    1. fetch_docket -> generates speculative requests for CRN IDs
    2. parse_docket_page -> parses case detail, yields ConnDocket
"""

from __future__ import annotations

import re
import ssl
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin

from jkent.common.decorators import entry, step
from jkent.common.exceptions import (
    HTMLStructuralAssumptionException,
)
from jkent.common.page_element import PageElement
from jkent.common.param_models import SpeculativeRange
from jkent.data_types import (
    ArchiveResponse,
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    XPath,
)
from pyrate_limiter import Duration, Rate

from .models import (
    DOCKET_PREFIX_TO_COURT,
    ConnDocket,
    ConnDocketEntry,
    ConnDocketUnavailable,
    ConnOpinion,
    ConnOpinionCluster,
    ConnOralArgument,
    ConnPreliminaryPaper,
    ConnTranscriptInfo,
    ConnTrialCaseUnavailable,
    ConnTrialCourtDocket,
    ConnTrialCourtDocketEntry,
    ConnTrialCourtParty,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


# Court configuration for opinions
OPINIONS_CONFIG = {
    "conn": {
        "name": "Connecticut Supreme Court",
        "archive_url": "https://www.jud.ct.gov/external/supapp/archiveAROsup.htm",
        "year_url_pattern": "archiveAROsup{yy}.htm",
        "docket_prefix": "SC",
    },
    "connappct": {
        "name": "Connecticut Appellate Court",
        "archive_url": "https://www.jud.ct.gov/external/supapp/archiveAROap.htm",
        "year_url_pattern": "archiveAROap{yy}.htm",
        "docket_prefix": "AC",
    },
}

# Court configuration for oral arguments
ORAL_ARGS_CONFIG = {
    "conn": {
        "name": "Connecticut Supreme Court",
        "audio_url": "https://jud.ct.gov/supremecourt/Audio/OralArgumentsAudio.aspx",
        "docket_prefix": "SC",
    },
    "connappct": {
        "name": "Connecticut Appellate Court",
        "audio_url": "https://jud.ct.gov/appellatecourt/Audio/OralArgumentsAudio.aspx",
        "docket_prefix": "AC",
    },
}

# Docket configuration
DOCKET_CONFIG = {
    "base_url": "https://appellateinquiry.jud.ct.gov",
    "case_detail_url": "https://appellateinquiry.jud.ct.gov/CaseDetail.aspx",
    "error_url": "https://appellateinquiry.jud.ct.gov/ErrorPage.aspx",
}

# Trial court configuration
TRIAL_COURT_CONFIG = {
    "base_url": "https://civilinquiry.jud.ct.gov",
    "case_detail_url": "https://civilinquiry.jud.ct.gov/CaseDetail/PublicCaseDetail.aspx",
    "document_inquiry_url": "https://civilinquiry.jud.ct.gov/DocumentInquiry/DocumentInquiry.aspx",
}


class ConnScraper(
    BaseScraper[
        ConnOpinionCluster
        | ConnOralArgument
        | ConnDocket
        | ConnDocketUnavailable
        | ConnTrialCaseUnavailable
        | ConnTrialCourtDocket
        | ConnTrialCourtDocketEntry
    ]
):
    """Unified scraper for Connecticut appellate court opinions, oral arguments, and dockets.

    Scrapes opinions, oral argument audio, and docket information from the CT Judicial Branch.
    Supports both Supreme Court (conn) and Appellate Court (connappct).

    Usage:
        # Scrape everything (all data types, both courts)
        scraper = ConnScraper()

        # Scrape only opinions (disable other data types)
        params = ConnScraper.params()
        params.ConnOralArgument = None
        params.ConnDocket = None
        scraper = ConnScraper(params=params)

        # Scrape only oral arguments (disable other data types)
        params = ConnScraper.params()
        params.ConnOpinionCluster = None
        params.ConnDocket = None
        scraper = ConnScraper(params=params)

        # Scrape only dockets starting from CRN 90000
        params = ConnScraper.params()
        params.ConnOpinionCluster = None
        params.ConnOralArgument = None
        params.ConnDocket.crn.gt = 90000
        scraper = ConnScraper(params=params)

        # Scrape a specific docket by CRN
        params = ConnScraper.params()
        params.ConnOpinionCluster = None
        params.ConnOralArgument = None
        params.ConnDocket.crn.eq = 92788
        scraper = ConnScraper(params=params)

        # Scrape only Supreme Court
        params = ConnScraper.params()
        params.ConnOpinionCluster.court_id.values = {"conn"}
        params.ConnOralArgument.court_id.values = {"conn"}
        params.ConnDocket.court_id.values = {"conn"}
        scraper = ConnScraper(params=params)

        # Filter opinions by date range
        params = ConnScraper.params()
        params.ConnOpinionCluster.date_filed.gte = date(2025, 12, 1)
        params.ConnOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = ConnScraper(params=params)

        # Filter oral arguments by date range
        params = ConnScraper.params()
        params.ConnOralArgument.date_argued.gte = date(2025, 9, 1)
        params.ConnOralArgument.date_argued.lte = date(2025, 9, 30)
        scraper = ConnScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"conn", "connappct", "connsuperct"}
    court_url: ClassVar[str] = "https://www.jud.ct.gov/"
    data_types: ClassVar[set[str]] = {"opinions", "oral_arguments", "dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2025-02-21"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(4, Duration.SECOND)]

    # === Opinions XPath definitions ===
    XPATH_YEAR_LINKS = XPath("//ul//li/a[strong] | //td//ul//li/a[strong])")
    # Note: Header format varies by year - different HTML elements used:
    # - Older pages (2003): Bold text, not in heading tags
    # - Mid-range pages: <h3> tags
    # - Recent pages (2025): <h2> tags
    # Examples: "Published in Connecticut Law Journal - 12/30/03:"
    #           "Published in the Law Journal of December 30, 2025:"
    # Use contains(., 'Published in') to check all descendant text, not just direct children
    # This handles nested tags like <strong><font>Published in...</font></strong>
    # Different years use different elements:
    # - 2020: <font> tags directly
    # - 2006: <strong><font>...</font></strong>
    # - Mid-range: <h3>
    # - Recent (2025): <h2>
    XPATH_PUBLICATION_HEADERS = (
        "//h2[contains(., 'Published in')] | "
        "//h3[contains(., 'Published in')] | "
        "//b[contains(., 'Published in')] | "
        "//strong[contains(., 'Published in')] | "
        "//font[contains(., 'Published in')]"
    )

    # === Opinions Regex patterns ===
    # Publication header format varies significantly by year:
    # - 2003: "Published in Connecticut Law Journal - 12/30/03:"
    # - 2014: "Published in Connecticut Law Journal of 12/30/14:"
    # - 2023: "Published in the Connecticut Law Journal of 12/19/2023:"
    # - 2025: "Published in the Law Journal of December 30, 2025:"
    # This pattern captures:
    #   Group 1: publication name (e.g., "the Connecticut Law Journal")
    #   Group 2: date in MM/DD/YY or MM/DD/YYYY format, OR
    #   Group 3: month name, Group 4: day, Group 5: year (for "Month D, YYYY" format)
    PUBLICATION_HEADER_PATTERN = re.compile(
        r"Published in\s+"
        r"(.+?)"  # Group 1: publication name (non-greedy)
        r"\s*[-–of]+\s*"  # separator: dash, en-dash, or "of"
        r"(?:"
        r"(\d{1,2}/\d{1,2}/\d{2,4})"  # Group 2: MM/DD/YY or MM/DD/YYYY
        r"|"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"  # Group 3: month name
        r"\s+(\d{1,2}),?\s*(\d{4})"  # Group 4: day, Group 5: year
        r")"
        r"\s*:",
        re.IGNORECASE,
    )
    # Legacy pattern for backwards compatibility (not used in new code)
    DATE_PATTERN = PUBLICATION_HEADER_PATTERN
    DOCKET_PATTERN = re.compile(r"^((SC|AC)\d+(?:,\s*(SC|AC)\d+)*)")
    OPINION_TYPE_PATTERN = re.compile(
        r"(Dissent|Concurrence|Concurrence & Dissent|Appendix|Order on Motion|"
        r"First Dissent|Second Dissent|Third Dissent|Second Concurrence|Third Concurrence)"
    )

    # === Oral Arguments Regex patterns ===
    DATE_ARGUED_PATTERN = re.compile(r"Date Argued:\s*(\d{1,2}/\d{1,2}/\d{4})")
    ORAL_ARGS_DOCKET_PATTERN = re.compile(r"^(SC|AC)\s*(\d+)$")
    AUDIO_ID_PATTERN = re.compile(r"ID=(\d+)")
    COURT_YEAR_PATTERN = re.compile(r"(\d{4})-(\d{4})")

    # === Docket Regex patterns ===
    # Docket number: "AC 48343" or "SC 21125"
    DOCKET_NUMBER_PATTERN = re.compile(r"^(SC|AC)\s*(\d+)$")
    # Date pattern for docket pages: "01/02/2025"
    DOCKET_DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")

    @classmethod
    def get_ssl_context(cls) -> ssl.SSLContext:
        """Return SSL context for CT Judicial Branch server.

        The CT Judicial Branch server requires specific cipher configuration.
        """
        ctx = ssl.create_default_context()
        ctx.set_ciphers("AES256-SHA256")
        return ctx

    @staticmethod
    def _extract_aspnet_viewstate(
        page: PageElement,
    ) -> dict[str, str]:
        """Extract ASP.NET ViewState fields required for postbacks.

        ASP.NET web forms require these hidden fields to be included in
        POST requests for server-side postbacks to work correctly.

        Args:
            page: The parsed HTML tree.

        Returns:
            Dict with __VIEWSTATE, __VIEWSTATEGENERATOR, and __EVENTVALIDATION
            if found.
        """
        viewstate_fields: dict[str, str] = {}
        field_names = [
            "__VIEWSTATE",
            "__VIEWSTATEGENERATOR",
            "__EVENTVALIDATION",
        ]

        for field_name in field_names:
            inputs = page.query_strings(
                XPath(f"//input[@name='{field_name}']/@value"),
                f"ASP.NET {field_name} field",
                min_count=0,
            )
            if inputs:
                viewstate_fields[field_name] = inputs[0]

        return viewstate_fields

    # =========================================================================
    # Parameter extraction (for both opinions and oral arguments)
    # =========================================================================

    def _get_opinions_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters for opinions from ScraperParams."""
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.ConnOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        docket_number = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        docket_field = searchable.get("docket_id")
        if docket_field and docket_field.is_set():
            docket_number = docket_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, docket_number, court_ids

    def _get_oral_args_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters for oral arguments from ScraperParams."""
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.ConnOralArgument
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        docket_number = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_argued")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        docket_field = searchable.get("docket_id")
        if docket_field and docket_field.is_set():
            docket_number = docket_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, docket_number, court_ids

    def _get_docket_search_params(
        self,
    ) -> tuple[int | None, int | None, set[str] | None]:
        """Extract search parameters for dockets from ScraperParams.

        Returns:
            Tuple of (crn_gt, crn_eq, court_ids)
            - crn_gt: Start scraping after this CRN (exclusive)
            - crn_eq: Scrape exactly this CRN
            - court_ids: Filter to specific courts (applied after fetching)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.ConnDocket
        except AttributeError:
            return None, None, None

        crn_gt = None
        crn_eq = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        crn_field = searchable.get("crn")
        if crn_field and crn_field.is_set():
            crn_gt = crn_field.gt
            crn_eq = crn_field.eq

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return crn_gt, crn_eq, court_ids

    def _get_opinions_target_courts(self) -> set[str]:
        """Get the set of court IDs to scrape for opinions."""
        _, _, _, court_ids = self._get_opinions_search_params()
        if court_ids:
            valid_courts = court_ids & set(OPINIONS_CONFIG.keys())
            if valid_courts:
                return valid_courts
        return set(OPINIONS_CONFIG.keys())

    def _get_oral_args_target_courts(self) -> set[str]:
        """Get the set of court IDs to scrape for oral arguments."""
        _, _, _, court_ids = self._get_oral_args_search_params()
        if court_ids:
            valid_courts = court_ids & set(ORAL_ARGS_CONFIG.keys())
            if valid_courts:
                return valid_courts
        return set(ORAL_ARGS_CONFIG.keys())

    def _get_opinions_year_range(self) -> tuple[int, int]:
        """Determine year range to scrape for opinions based on params."""
        date_gte, date_lte, _, _ = self._get_opinions_search_params()
        current_year = datetime.now().year

        if date_gte:
            start_year = date_gte.year
        else:
            start_year = 2000  # Archive starts at 2000

        if date_lte:
            end_year = date_lte.year
        else:
            end_year = current_year

        return start_year, end_year

    def _get_oral_args_court_year_range(self) -> tuple[int, int]:
        """Determine court year range for oral arguments based on date params.

        Court years run from fall to summer (e.g., 2025-2026 starts Sept 2025).
        """
        date_gte, date_lte, _, _ = self._get_oral_args_search_params()
        current_year = datetime.now().year

        if date_gte:
            if date_gte.month < 9:
                start_year = date_gte.year - 1
            else:
                start_year = date_gte.year
        else:
            start_year = (
                2018  # Audio archive appears to start around 2018-2019
            )

        if date_lte:
            if date_lte.month < 9:
                end_year = date_lte.year - 1
            else:
                end_year = date_lte.year
        else:
            end_year = current_year

        return start_year, end_year

    # =========================================================================
    # Entry Points
    # =========================================================================

    @entry(ConnOpinionCluster)
    def get_opinions(self) -> Generator[Request, None, None]:
        """Yield initial request for opinions scraping."""
        target_courts = self._get_opinions_target_courts()
        first_court = sorted(target_courts)[0]
        config = OPINIONS_CONFIG[first_court]

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=config["archive_url"],
            ),
            continuation=self.parse_archive_index,
            accumulated_data={
                "court_id": first_court,
                "remaining_courts": sorted(target_courts - {first_court}),
            },
        )

    @entry(ConnOralArgument)
    def get_oral_arguments(self) -> Generator[Request, None, None]:
        """Yield initial request for oral arguments scraping."""
        target_courts = self._get_oral_args_target_courts()
        first_court = sorted(target_courts)[0]
        config = ORAL_ARGS_CONFIG[first_court]

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=config["audio_url"],
            ),
            continuation=self.parse_oral_arguments_index,
            accumulated_data={
                "court_id": first_court,
                "remaining_courts": sorted(target_courts - {first_court}),
            },
        )

    # =========================================================================
    # Opinions Scraping Steps
    # =========================================================================

    @step()
    def parse_archive_index(
        self,
        page: PageElement,
        # response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[ConnOpinionCluster | ConnOralArgument], None, None
    ]:
        """Parse the archive index and yield requests for year pages."""
        court_id = accumulated_data.get("court_id")
        remaining_courts = accumulated_data.get("remaining_courts", [])
        start_year, end_year = self._get_opinions_year_range()

        # Find all year links (find_links resolves URLs automatically)
        year_links = page.find_links(
            self.XPATH_YEAR_LINKS,
            "year links",
            min_count=1,
        )

        for link in year_links:
            try:
                year = int(link.text)
            except ValueError:
                continue

            if year < start_year or year > end_year:
                continue

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=link.url,
                ),
                continuation=self.parse_year_page,
                accumulated_data={
                    "year": year,
                    "court_id": court_id,
                },
            )

        # After processing all years for this court, move to next court
        if remaining_courts:
            next_court = remaining_courts[0]
            config = OPINIONS_CONFIG[next_court]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=config["archive_url"],
                ),
                continuation=self.parse_archive_index,
                accumulated_data={
                    "court_id": next_court,
                    "remaining_courts": remaining_courts[1:],
                },
            )

    @step()
    def parse_year_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[ConnOpinionCluster | ConnOralArgument], None, None
    ]:
        """Parse a year's archive page and yield opinion clusters."""
        year = accumulated_data.get("year")
        court_id: str = accumulated_data.get("court_id", "")
        date_gte, date_lte, target_docket, _ = (
            self._get_opinions_search_params()
        )

        expected_prefix = OPINIONS_CONFIG[court_id]["docket_prefix"]

        headers = page.query(
            XPath(self.XPATH_PUBLICATION_HEADERS),
            "publication date headers",
            min_count=1,
        )

        for header in headers:
            # Normalize whitespace: text_content() may include newlines/tabs
            # from nested elements (e.g., <font> tags in 2020 pages)
            header_text = " ".join(header.text_content().split())
            header_match = self.PUBLICATION_HEADER_PATTERN.search(header_text)
            if not header_match:
                continue

            # Extract publication name (group 1)
            publication_name = header_match.group(1).strip()

            # Extract date - either MM/DD/YY format (group 2) or Month D, YYYY (groups 3-5)
            date_str: str
            if header_match.group(2):
                # Format: MM/DD/YY or MM/DD/YYYY
                date_str = header_match.group(2)
                try:
                    if len(date_str.split("/")[-1]) == 4:
                        pub_date = datetime.strptime(
                            date_str, "%m/%d/%Y"
                        ).date()
                    else:
                        pub_date = datetime.strptime(
                            date_str, "%m/%d/%y"
                        ).date()
                except ValueError:
                    continue
            else:
                # Format: Month D, YYYY
                month_name = header_match.group(3)
                day = header_match.group(4)
                year_str = header_match.group(5)
                date_str = f"{month_name} {day}, {year_str}"
                try:
                    pub_date = datetime.strptime(
                        f"{month_name} {day} {year_str}", "%B %d %Y"
                    ).date()
                except ValueError:
                    continue

            if date_gte and pub_date < date_gte:
                continue
            if date_lte and pub_date > date_lte:
                continue

            opinion_items = header.query(
                XPath(
                    "following-sibling::*[self::p or self::ul][position() <= 2]"
                    "/self::ul/li | following-sibling::ul[1]/li"
                ),
                "opinion list items",
                min_count=0,
            )

            case_opinions: dict[str, list[tuple[str, str, str]]] = {}

            for item in opinion_items:
                links = item.find_links(
                    XPath(".//a"), "opinion links", min_count=0
                )
                if not links:
                    continue

                first_link = links[0]
                docket_text = first_link.text

                docket_match = self.DOCKET_PATTERN.match(docket_text)
                if not docket_match:
                    continue

                docket_number = docket_match.group(1)

                if not docket_number.startswith(expected_prefix):
                    continue

                pdf_url = first_link.url

                opinion_type = "majority"
                type_match = self.OPINION_TYPE_PATTERN.search(docket_text)
                if type_match:
                    raw_type = type_match.group(1).lower()
                    if "dissent" in raw_type and "concurrence" in raw_type:
                        opinion_type = "concurrence_dissent"
                    elif "dissent" in raw_type:
                        opinion_type = "dissent"
                    elif "concurrence" in raw_type:
                        opinion_type = "concurrence"
                    elif "appendix" in raw_type:
                        opinion_type = "appendix"
                    elif "order" in raw_type:
                        opinion_type = "order"

                full_text = item.text_content()
                case_name = re.sub(
                    r"^(SC|AC)[\d,\s]+(SC|AC)?[\d,\s]*(?:\s+\w+)*\s*[-–]\s*",
                    "",
                    full_text,
                ).strip()

                primary_docket = docket_number.split(",")[0].strip()

                if primary_docket not in case_opinions:
                    case_opinions[primary_docket] = []

                case_opinions[primary_docket].append(
                    (pdf_url, opinion_type, case_name)
                )

            for docket_id, opinions_data in case_opinions.items():
                if target_docket and docket_id != target_docket:
                    continue

                case_name = opinions_data[0][2] if opinions_data else "Unknown"

                cluster_data: dict[str, Any] = {
                    "docket_id": docket_id,
                    "court_id": court_id,
                    "date_filed": pub_date.isoformat(),
                    "case_name": case_name,
                    "source_url": response.url,
                    "publication_year": year,
                    "law_journal_date": date_str,
                    "publication_name": publication_name,
                    "opinions_data": [
                        {"download_url": url, "type": op_type}
                        for url, op_type, _ in opinions_data
                    ],
                    "pending_downloads": len(opinions_data),
                    "completed_downloads": 0,
                    "downloaded_paths": {},
                }

                first_url, _, _ = opinions_data[0]
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=first_url,
                    ),
                    continuation=self.handle_opinion_download,
                    expected_type="pdf",
                    accumulated_data={
                        **cluster_data,
                        "current_download_index": 0,
                    },
                )

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[ConnOpinionCluster | ConnOralArgument], None, None
    ]:
        """Handle a downloaded opinion PDF."""
        current_index = accumulated_data["current_download_index"]

        accumulated_data["downloaded_paths"][current_index] = response.file_url
        accumulated_data["completed_downloads"] += 1

        if (
            accumulated_data["completed_downloads"]
            >= accumulated_data["pending_downloads"]
        ):
            yield from self._yield_final_cluster(accumulated_data)
        else:
            next_index = current_index + 1
            opinions_data = accumulated_data["opinions_data"]
            next_opinion = opinions_data[next_index]

            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_opinion["download_url"],
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data={
                    **accumulated_data,
                    "current_download_index": next_index,
                },
            )

    def _yield_final_cluster(
        self, accumulated_data: dict
    ) -> Generator[
        ScraperYield[ConnOpinionCluster | ConnOralArgument], None, None
    ]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                ConnOpinion(
                    download_url=op_data["download_url"],
                    type=op_data["type"],
                    local_path=local_path,
                )
            )

        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        cluster = ConnOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=opinions,
            source_url=accumulated_data["source_url"],
            publication_year=accumulated_data["publication_year"],
            law_journal_date=accumulated_data["law_journal_date"],
            publication_name=accumulated_data.get("publication_name"),
            precedential_status="Published",
        )

        yield ParsedData(cluster)

    # =========================================================================
    # Oral Arguments Scraping Steps
    # =========================================================================

    @step()
    def parse_oral_arguments_index(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[ConnOpinionCluster | ConnOralArgument], None, None
    ]:
        """Parse the oral arguments index page and yield requests for court years."""
        court_id = accumulated_data.get("court_id")
        remaining_courts = accumulated_data.get("remaining_courts", [])
        start_year, end_year = self._get_oral_args_court_year_range()

        # Extract ASP.NET ViewState fields for postback requests
        viewstate = self._extract_aspnet_viewstate(page)

        year_links = page.query(
            XPath(
                "//a[contains(@href, 'doPostBack') and contains(text(), '-')]"
            ),
            "court year links",
            min_count=0,
        )

        processed_years = set()

        for link in year_links:
            link_text = link.text_content().strip()
            year_match = self.COURT_YEAR_PATTERN.match(link_text)
            if not year_match:
                continue

            court_year_start = int(year_match.group(1))

            if court_year_start < start_year or court_year_start > end_year:
                continue

            if link_text in processed_years:
                continue
            processed_years.add(link_text)

            href = link.get_attribute("href") or ""
            event_target_match = re.search(r"__doPostBack\('([^']+)'", href)
            if not event_target_match:
                continue

            event_target = event_target_match.group(1)

            # Build POST data with ASP.NET ViewState fields
            post_data = {
                "__EVENTTARGET": event_target,
                "__EVENTARGUMENT": "",
                **viewstate,  # Include __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION
            }

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=response.url,
                    data=post_data,
                ),
                continuation=self.parse_court_year_page,
                accumulated_data={
                    "court_id": court_id,
                    "court_year": link_text,
                    "remaining_courts": remaining_courts,
                },
            )

        # Also process the current page (shows current court year by default)
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=response.url,
            ),
            continuation=self.parse_court_year_page,
            accumulated_data={
                "court_id": court_id,
                "court_year": None,
                "remaining_courts": remaining_courts,
                "is_initial_page": True,
            },
        )

    def _process_oral_args_entries(
        self,
        page: PageElement,
        response: Response,
        court_id: str,
        court_year: str | None,
        expected_prefix: str,
        date_gte: date | None,
        date_lte: date | None,
        target_docket: str | None,
    ) -> Generator[
        ScraperYield[ConnOpinionCluster | ConnOralArgument], None, None
    ]:
        """Process oral argument entries from either old or new page format.

        Old format: Term buttons followed by article sections
        New format: article.ResponseCaseList with section.fullWidth entries
        """
        # Try old format first: term buttons followed by article sections
        term_buttons = page.query(
            XPath("//button[contains(text(), 'Term:')]"),
            "oral args term buttons",
            min_count=0,
        )

        if term_buttons:
            # Old format with term buttons
            # Structure:
            #   <article class="collapsable">
            #     <button>First Term:</button>
            #     <div class="collapsable_cont">
            #       <article class="ResponseCaseList">
            #         <section class="fullWidth">...
            for button in term_buttons:
                term_text = button.text_content().strip()
                term_match = re.match(
                    r"(First|Second|Third|Fourth)\s+Term", term_text
                )
                term = term_match.group(0) if term_match else "Unknown Term"

                # The article.ResponseCaseList is inside a sibling div, not
                # a direct sibling article
                content_sections = button.query(
                    XPath(
                        "following-sibling::div[1]//article[@class='ResponseCaseList']"
                        "//section[@class='fullWidth']"
                        " | following-sibling::article[1]//section[@class='fullWidth']"
                    ),
                    "oral args content sections",
                    min_count=0,
                )

                for section in content_sections:
                    yield from self._parse_oral_arg_section(
                        section=section,
                        response=response,
                        court_id=court_id,
                        court_year=court_year,
                        expected_prefix=expected_prefix,
                        date_gte=date_gte,
                        date_lte=date_lte,
                        target_docket=target_docket,
                        term=term,
                    )
        else:
            # New format: article.ResponseCaseList with section.fullWidth
            # entries The sections directly contain header.HeaderText with
            # Date Argued
            sections = page.query(
                XPath(
                    "//article[@class='ResponseCaseList']//section[@class='fullWidth']"
                    " | //section[header[contains(@class, 'HeaderText')]]"
                ),
                "oral args case sections",
                min_count=0,
            )

            for section in sections:
                yield from self._parse_oral_arg_section(
                    section=section,
                    response=response,
                    court_id=court_id,
                    court_year=court_year,
                    expected_prefix=expected_prefix,
                    date_gte=date_gte,
                    date_lte=date_lte,
                    target_docket=target_docket,
                    term=None,  # New format doesn't have term info
                )

    def _parse_oral_arg_section(
        self,
        section: PageElement,
        response: Response,
        court_id: str,
        court_year: str | None,
        expected_prefix: str,
        date_gte: date | None,
        date_lte: date | None,
        target_docket: str | None,
        term: str | None,
    ) -> Generator[
        ScraperYield[ConnOpinionCluster | ConnOralArgument], None, None
    ]:
        """Parse a single oral argument section element.

        Works with both old format (div-based) and new format (header-based).
        """
        # Find date - try both old format (div) and new format (header)
        date_elements = section.query(
            XPath(
                ".//header[contains(@class, 'HeaderText') and "
                "contains(text(), 'Date Argued:')]"
                " | .//div[contains(text(), 'Date Argued:')]"
            ),
            "date argued element",
            min_count=0,
        )

        if not date_elements:
            # The section itself might have the date text directly
            section_text = section.text_content()
            if "Date Argued:" not in section_text:
                return

        # Extract date from section text or date element
        if date_elements:
            date_text = date_elements[0].text_content().strip()
        else:
            date_text = section.text_content().strip()

        date_match = self.DATE_ARGUED_PATTERN.search(date_text)
        if not date_match:
            return

        try:
            argued_date = datetime.strptime(
                date_match.group(1), "%m/%d/%Y"
            ).date()
        except ValueError:
            return

        if date_gte and argued_date < date_gte:
            return
        if date_lte and argued_date > date_lte:
            return

        # Find docket link - works for both formats
        docket_links = section.find_links(
            XPath(
                ".//a[contains(@href, 'appellateinquiry') or "
                "contains(@href, 'CaseDetail')]"
            ),
            "docket link",
            min_count=0,
        )
        if not docket_links:
            return

        docket_link = docket_links[0]
        docket_text = docket_link.text
        case_detail_url = docket_link.url

        # Parse docket number
        docket_match = self.ORAL_ARGS_DOCKET_PATTERN.match(docket_text)
        if not docket_match:
            docket_match = re.match(
                r"^(SC|AC)\s*(\d+)$", docket_text.replace(" ", "")
            )
            if not docket_match:
                return

        prefix = docket_match.group(1)
        docket_num = docket_match.group(2)
        docket_id = f"{prefix}{docket_num}"

        if prefix != expected_prefix:
            return

        if target_docket and docket_id != target_docket:
            return

        # Find case name - try both formats
        case_name_elements = section.query(
            XPath(
                ".//div[@class='CaseName']"
                " | .//div[contains(@class, 'Col_7of10')]"
                " | .//div[a[contains(@href, 'appellateinquiry')]]"
                "/following-sibling::div[1]"
            ),
            "case name element",
            min_count=0,
        )
        case_name = "Unknown"
        if case_name_elements:
            raw_name = case_name_elements[0].text_content().strip()
            # Clean up the case name - remove docket prefix if present
            case_name = re.sub(r"^(SC|AC)\s*\d+\s*", "", raw_name).strip()
            # Normalize whitespace and line breaks
            case_name = re.sub(r"\s+", " ", case_name).strip()
            if not case_name:
                case_name = raw_name

        # Find audio link - works for both formats
        audio_links = section.find_links(
            XPath(".//a[contains(@href, 'PlayAudio')]"),
            "audio link",
            min_count=0,
        )
        if not audio_links:
            return

        audio_link = audio_links[0]
        audio_url = audio_link.url

        audio_id_match = self.AUDIO_ID_PATTERN.search(audio_url)
        audio_id = int(audio_id_match.group(1)) if audio_id_match else None

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=audio_url,
            ),
            continuation=self.parse_audio_player_page,
            accumulated_data={
                "docket_id": docket_id,
                "court_id": court_id,
                "date_argued": argued_date.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "court_year": court_year,
                "term": term,
                "case_detail_url": case_detail_url,
                "audio_id": audio_id,
            },
        )

    @step()
    def parse_court_year_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[ConnOpinionCluster | ConnOralArgument], None, None
    ]:
        """Parse a court year's oral arguments page."""
        court_id: str = accumulated_data.get("court_id", "")
        court_year = accumulated_data.get("court_year")
        remaining_courts = accumulated_data.get("remaining_courts", [])
        is_initial = accumulated_data.get("is_initial_page", False)
        date_gte, date_lte, target_docket, _ = (
            self._get_oral_args_search_params()
        )

        expected_prefix = ORAL_ARGS_CONFIG[court_id]["docket_prefix"]

        if not court_year:
            selected_tab = page.query(
                XPath(
                    "//a[contains(@class, 'ui-tabs-anchor') and ancestor::li[contains(@class, 'ui-tabs-active')]]"
                ),
                "selected court year tab",
                min_count=0,
            )
            if selected_tab:
                tab_text = selected_tab[0].text_content().strip()
                if ":" in tab_text:
                    court_year = tab_text.split(":")[-1].strip()

        # Process oral argument entries from the page
        # Support both old format (with term buttons) and new format (direct sections)
        yield from self._process_oral_args_entries(
            page=page,
            response=response,
            court_id=court_id,
            court_year=court_year,
            expected_prefix=expected_prefix,
            date_gte=date_gte,
            date_lte=date_lte,
            target_docket=target_docket,
        )

        # After processing, move to next court
        if is_initial and remaining_courts:
            next_court = remaining_courts[0]
            config = ORAL_ARGS_CONFIG[next_court]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=config["audio_url"],
                ),
                continuation=self.parse_oral_arguments_index,
                accumulated_data={
                    "court_id": next_court,
                    "remaining_courts": remaining_courts[1:],
                },
            )

    @step()
    def parse_audio_player_page(
        self,
        page: PageElement,
        # response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[ConnOpinionCluster | ConnOralArgument], None, None
    ]:
        """Parse the audio player page to extract the actual MP3 URL."""
        audio_sources = page.query(
            XPath("//audio/source[@src]"),
            "audio source element",
            min_count=0,
        )
        if not audio_sources:
            audio_sources = page.query(
                XPath("//source[@type='audio/mpeg']"),
                "mpeg audio source",
                min_count=0,
            )

        if not audio_sources:
            return

        mp3_url = audio_sources[0].get_attribute("src") or ""
        if not mp3_url:
            return

        yield Request(
            archive=True,
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=mp3_url,
            ),
            continuation=self.handle_audio_download,
            expected_type="audio",
            accumulated_data=accumulated_data,
        )

    @step
    def handle_audio_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[ConnOpinionCluster | ConnOralArgument], None, None
    ]:
        """Handle a downloaded oral argument audio file."""
        argued_date = datetime.fromisoformat(
            accumulated_data["date_argued"]
        ).date()

        oral_arg = ConnOralArgument(
            docket_number=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_argued=argued_date,
            case_name=accumulated_data["case_name"],
            download_url=response.request.request.url,
            local_path=response.file_url,
            source_url=accumulated_data.get("source_url"),
            court_year=accumulated_data.get("court_year"),
            term=accumulated_data.get("term"),
            case_detail_url=accumulated_data.get("case_detail_url"),
            audio_id=accumulated_data.get("audio_id"),
        )

        yield ParsedData(oral_arg)

    # =========================================================================
    # Dockets Scraping Steps
    # =========================================================================

    @entry(ConnDocket)
    def fetch_docket(self, rid: SpeculativeRange) -> Request:
        """Create a speculative request for a docket by CRN.

        CRNs are monotonically increasing internal IDs used by the CT
        courts. Templates are supplied via ``seed_params`` at run time,
        e.g.::

            [{"fetch_docket": {"rid": {"min": 105336, "gap": 20}}}]

        The request is processed by parse_docket_page.
        """
        crn = rid.min

        # Get court_ids filter from params (if set)
        _, _, court_ids = self._get_docket_search_params()

        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{DOCKET_CONFIG['case_detail_url']}?CRN={crn}",
            ),
            continuation=self.parse_docket_page,
            accumulated_data={
                "crn": crn,
                "court_ids": list(court_ids) if court_ids else None,
            },
        )

    # XPath patterns for docket page elements
    # Note: The appellate case number (SC/AC format) is in lblAppealNo,
    # NOT in lblDocketNum (which contains trial court docket numbers)
    XPATH_DOCKET_NUMBER = "//span[@id='lblAppealNo']"
    XPATH_CASE_NAME = "//span[@id='lblCaseName']"
    XPATH_STATUS = "//span[@id='lblCaseStatus']"
    # Some cases display "This case is not available at this time" on a
    # NotAvailable.aspx page (but URL doesn't change). Detect via this span.
    XPATH_NOT_AVAILABLE = "//span[@id='lblNotAvailable']"

    @step()
    def parse_docket_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            ConnOpinionCluster
            | ConnOralArgument
            | ConnDocket
            | ConnDocketUnavailable
        ],
        bool | None,
        None,
    ]:
        """Parse a docket page and yield ConnDocket.

        Extracts:
        - Case information (docket number, case name, status)
        - Appeal case information (dates, disposition, panel)
        - Trial court information
        - Parties and attorneys
        - Case activity (docket entries)

        For unavailable cases (unpublished), yields a minimal ConnDocket
        with unavailable=True.
        """
        crn = accumulated_data.get("crn")
        court_ids_filter = accumulated_data.get("court_ids")

        # Missing CRNs return a 302 redirecting to ErrorPage.aspx?errmsg=Case Not Found.
        # The unencoded space in the Location header prevents httpx from following the
        # redirect, so the 302 status is what we see here (response.url stays on
        # CaseDetail.aspx). This is expected for speculative scraping.
        if response.status_code != 200:
            return
        if DOCKET_CONFIG["error_url"] in response.url:
            return

        # Check if case is marked as "not available at this time"
        # These are unpublished cases that show a message like:
        # "SC 140295 - This case is not available at this time."
        not_available_elems = page.query(
            XPath(self.XPATH_NOT_AVAILABLE),
            "not available message",
            min_count=0,
        )
        if not_available_elems:
            # Extract docket number from the message (e.g., "SC 140295 - ...")
            not_available_text = not_available_elems[0].text_content().strip()
            docket_match = self.DOCKET_NUMBER_PATTERN.match(
                not_available_text.replace(" ", "")
            )
            if not docket_match:
                # Try with spaces
                docket_match = re.match(
                    r"^(SC|AC)\s*(\d+)", not_available_text
                )

            if docket_match:
                prefix = docket_match.group(1)
                docket_num = docket_match.group(2)
                docket_id = f"{prefix} {docket_num}"
                court_id = DOCKET_PREFIX_TO_COURT.get(prefix)

                # Filter by court_id if specified
                if court_ids_filter and court_id not in court_ids_filter:
                    return

                # Yield a ConnDocketUnavailable for unavailable cases
                yield ParsedData(
                    ConnDocketUnavailable(
                        crn=crn,
                        docket_id=docket_id,
                        court_id=court_id,
                        source_url=response.url,
                        message=not_available_text,
                    )
                )
            return

        # Extract docket number from page - this is required
        docket_elems = page.query(
            XPath(self.XPATH_DOCKET_NUMBER),
            "docket number",
            min_count=1,
            max_count=1,
        )
        docket_text = docket_elems[0].text_content().strip()

        # Parse the docket number format (SC or AC prefix + number)
        docket_match = self.DOCKET_NUMBER_PATTERN.match(
            docket_text.replace(" ", "")
        )
        if not docket_match:
            # Try with spaces
            docket_match = re.match(r"^(SC|AC)\s*(\d+)$", docket_text)
            if not docket_match:
                raise HTMLStructuralAssumptionException(
                    selector=self.XPATH_DOCKET_NUMBER,
                    selector_type="xpath",
                    description="docket number with valid SC/AC format",
                    expected_min=1,
                    expected_max=1,
                    actual_count=1,  # Found element but invalid format
                    request_url=response.url,
                )

        prefix = docket_match.group(1)
        docket_num = docket_match.group(2)
        docket_id = f"{prefix} {docket_num}"
        court_id = DOCKET_PREFIX_TO_COURT.get(prefix)

        # Filter by court_id if specified
        if court_ids_filter and court_id not in court_ids_filter:
            return  # Skip this docket - not in requested courts

        # Extract case name - required
        case_name_elems = page.query(
            XPath(self.XPATH_CASE_NAME),
            "case name",
            min_count=1,
            max_count=1,
        )
        case_name = case_name_elems[0].text_content().strip() or "Unknown"

        # Extract status - required
        status_elems = page.query(
            XPath(self.XPATH_STATUS),
            "case status",
            min_count=1,
            max_count=1,
        )
        status = status_elems[0].text_content().strip() or "Unknown"

        # Helper to extract date from element (optional fields - min_count=0)
        def extract_date(xpath_expr: str, description: str) -> date | None:
            elems = page.query(XPath(xpath_expr), description, min_count=0)
            if elems:
                date_text = elems[0].text_content().strip()
                match = self.DOCKET_DATE_PATTERN.search(date_text)
                if match:
                    try:
                        return datetime.strptime(
                            match.group(1), "%m/%d/%Y"
                        ).date()
                    except ValueError:
                        pass
            return None

        # Helper to extract text from element (optional fields - min_count=0)
        def extract_text(xpath_expr: str, description: str) -> str | None:
            elems = page.query(XPath(xpath_expr), description, min_count=0)
            if elems:
                text = elems[0].text_content().strip()
                return text if text else None
            return None

        # === Appeal Case Information ===
        date_filed = extract_date(
            "//span[@id='lblDateFiled']",
            "date filed",
        )
        appeal_by = extract_text(
            "//span[@id='lblAppealBy']",
            "appeal by",
        )
        disposition_method = extract_text(
            "//span[@id='lblDispMethod']",
            "disposition method",
        )
        argued_date = extract_date(
            "//span[@id='lblArgSub']",
            "argued date",
        )
        disposition_date = extract_date(
            "//span[@id='lblDispDt']",
            "disposition date",
        )
        submitted_on_briefs_date = extract_date(
            "//span[@id='lblSubmitDt']",
            "submitted on briefs date",
        )
        cite = extract_text(
            "//span[@id='lblRescript']",
            "citation",
        )
        panel = extract_text(
            "//span[@id='lblPanel']",
            "panel",
        )
        response_due_date = extract_date(
            "//span[@id='lblResponse2Docket']",
            "response due date",
        )

        # === Trial Court Information ===
        # Trial court docket is in a table with links (dlTCDockets)
        trial_docket_links = page.find_links(
            XPath(
                "//table[@id='dlTCDockets']//a[contains(@id, 'hlnkDocketNumber')]"
            ),
            "trial court docket links",
            min_count=0,
        )
        trial_court_docket_number = None
        trial_court_docket_url = None
        if trial_docket_links:
            trial_court_docket_url = trial_docket_links[0].url
            trial_court_docket_number = trial_docket_links[0].text

        judgment_for = extract_text(
            "//span[@id='lblJudgementFor'] | "
            "//span[contains(@id, 'JudgementFor')]",
            "judgment for",
        )
        trial_court = extract_text(
            "//span[@id='lblCourt'] | //span[contains(@id, 'Court')]",
            "trial court",
        )
        trial_judge = extract_text(
            "//span[@id='lblTrialJudge'] | "
            "//span[contains(@id, 'TrialJudge')]",
            "trial judge",
        )
        judgment_date = extract_date(
            "//span[@id='lblJudgementdate'] | "
            "//span[contains(@id, 'Judgementdate')]",
            "judgment date",
        )
        case_type = extract_text(
            "//span[@id='lblCaseType'] | //span[contains(@id, 'CaseType')]",
            "case type",
        )

        # Check for e-filed indicator (optional - min_count=0)
        is_efiled_elem = page.query(
            XPath(
                "//span[contains(@id, 'EFiled')] | //img[contains(@alt, 'eFiled')]"
            ),
            "e-filed indicator",
            min_count=0,
        )
        is_efiled = bool(is_efiled_elem)

        # === Parse Parties ===
        parties = self._parse_parties(page)

        # === Parse Case Activity (Docket Entries) ===
        entries = self._parse_docket_entries(page)

        # === Parse Preliminary Papers ===
        preliminary_papers = self._parse_preliminary_papers(page)

        # === Parse Transcripts and Exhibits ===
        transcripts, exhibits_received_by_court = self._parse_transcripts(page)

        # === Extract Subscription URL ===
        subscription_url = self._extract_subscription_url(page)

        # === Yield the ConnDocket (without embedded entries) ===
        docket = ConnDocket(
            crn=crn,
            docket_id=docket_id,
            court_id=court_id,
            case_name=case_name,
            status=status,
            date_filed=date_filed,
            appeal_by=appeal_by,
            disposition_method=disposition_method,
            argued_date=argued_date,
            disposition_date=disposition_date,
            submitted_on_briefs_date=submitted_on_briefs_date,
            cite=cite,
            panel=panel,
            response_due_date=response_due_date,
            trial_court_docket_number=trial_court_docket_number,
            trial_court_docket_url=trial_court_docket_url,
            judgment_for=judgment_for,
            trial_court=trial_court,
            trial_judge=trial_judge,
            judgment_date=judgment_date,
            case_type=case_type,
            parties=parties,
            preliminary_papers=preliminary_papers,
            transcripts=transcripts,
            exhibits_received_by_court=exhibits_received_by_court,
            source_url=response.url,
            subscription_url=subscription_url,
            is_efiled=is_efiled,
        )
        yield ParsedData(docket)

        # === Yield ConnDocketEntry objects ===
        # Entries without documents are yielded directly.
        # Entries with documents trigger an ArchiveRequest for download.
        for entry_data in entries:
            # Build ConnDocketEntry with docket_id foreign key
            entry = ConnDocketEntry(
                docket_id=docket_id,
                court_id=court_id,
                activity_type=entry_data["activity_type"],
                number=entry_data["number"],
                date_filed=entry_data["date_filed"],
                initiated_by=entry_data["initiated_by"],
                description=entry_data["description"],
                action=entry_data["action"],
                action_date=entry_data["action_date"],
                notice_date=entry_data["notice_date"],
                document_url=entry_data["document_url"],
                is_paperless=entry_data["is_paperless"],
            )

            if entry_data["document_url"]:
                # Yield ArchiveRequest for document download
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=entry_data["document_url"],
                    ),
                    continuation=self.handle_docket_document_download,
                    expected_type="pdf",
                    accumulated_data={
                        "entry": entry.model_dump(mode="json"),
                    },
                )
            else:
                # No document - yield entry directly
                yield ParsedData(entry)

        # === Follow Trial Court Docket Link ===
        # If this appellate docket has a linked trial court docket,
        # yield a Request to fetch and parse it
        if trial_court_docket_url:
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=trial_court_docket_url,
                ),
                continuation=self.parse_trial_court_docket,
                accumulated_data={
                    "appellate_docket_id": docket_id,
                    "trial_docket_number": trial_court_docket_number,
                },
            )

    @step
    def handle_docket_document_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ConnDocketEntry], None, None]:
        """Handle a downloaded docket document PDF.

        Yields a single ConnDocketEntry with the downloaded document path.
        """
        entry_data = accumulated_data["entry"]

        # Helper to parse ISO date strings
        def iso_to_date(s: str | None) -> date | None:
            if s:
                return datetime.fromisoformat(s).date()
            return None

        # Rebuild entry with local path
        entry = ConnDocketEntry(
            docket_id=entry_data["docket_id"],
            court_id=entry_data["court_id"],
            activity_type=entry_data["activity_type"],
            number=entry_data.get("number"),
            date_filed=iso_to_date(entry_data.get("date_filed")),
            initiated_by=entry_data.get("initiated_by"),
            description=entry_data.get("description"),
            action=entry_data.get("action"),
            action_date=iso_to_date(entry_data.get("action_date")),
            notice_date=iso_to_date(entry_data.get("notice_date")),
            document_url=entry_data.get("document_url"),
            document_local_path=response.file_url,
            is_paperless=entry_data.get("is_paperless", False),
        )

        yield ParsedData(entry)

    def _parse_parties(self, page: PageElement) -> list[dict]:
        """Parse party information from the docket page.

        Returns a list of dicts with party details including attorneys.
        """
        parties = []

        # Party rows are typically in a table or grid structure (optional - min_count=0)
        party_rows = page.query(
            XPath(
                "//table[contains(@id, 'Party')]//tr | "
                "//div[contains(@id, 'Party')]//div[@class='row'] | "
                "//div[contains(@class, 'party')]"
            ),
            "party rows",
            min_count=0,
        )

        for row in party_rows:
            # Skip header rows
            if row.query(XPath(".//th"), "header cells", min_count=0):
                continue

            cells = row.query(
                XPath(".//td | .//div[contains(@class, 'col')]"),
                "party row cells",
                min_count=0,
            )
            if len(cells) >= 3:
                party: dict[str, Any] = {
                    "name": cells[0].text_content().strip()
                    if cells[0].text_content()
                    else None,
                    "trial_court_class": cells[1].text_content().strip()
                    if len(cells) > 1 and cells[1].text_content()
                    else None,
                    "appeal_class": cells[2].text_content().strip()
                    if len(cells) > 2 and cells[2].text_content()
                    else None,
                }
                # Look for attorneys in remaining cells or nested elements
                attorneys = []
                for cell in cells[3:] if len(cells) > 3 else []:
                    attorney_text = cell.text_content().strip()
                    if attorney_text:
                        attorneys.append(attorney_text)
                if attorneys:
                    party["attorneys"] = attorneys
                if party["name"]:
                    parties.append(party)

        return parties

    def _parse_docket_entries(self, page: PageElement) -> list[dict]:
        """Parse case activity (docket entries) from the page.

        Returns a list of dicts with entry data (without docket_id).
        The caller adds docket_id when constructing ConnDocketEntry objects.

        Table structure (gvActivities):
        Column 0: Activity - activity type with optional document links
        Column 1: Number - e.g., "AC 49011"
        Column 2: Date filed - e.g., "8/7/2025"
        Column 3: Initiated By - party name or empty
        Column 4: Description - activity description
        Column 5: Action - e.g., "Filed", "Granted"
        Column 6: Action Date
        Column 7: Notice Date
        """
        entries: list[dict] = []

        # Find the Case Activity table by ID (gvActivities)
        activity_tables = page.query(
            XPath("//table[@id='gvActivities']"),
            "case activity table",
            min_count=0,
        )

        if not activity_tables:
            return entries

        # Get all rows from the table
        rows = activity_tables[0].query(
            XPath(".//tr"),
            "case activity rows",
            min_count=0,
        )

        for row in rows:
            # Skip header rows (rows containing th elements)
            header_cells = row.query(
                XPath(".//th"),
                "header cells",
                min_count=0,
            )
            if header_cells:
                continue

            # Get data cells - need at least 6 columns for valid entry
            cells = row.query(
                XPath(".//td"),
                "data cells",
                min_count=0,
            )
            if len(cells) < 6:
                continue

            # Column 0: Activity type - extract from lblActivity span or text
            activity_spans = cells[0].query(
                XPath(".//span[contains(@id, 'lblActivity')]"),
                "activity type span",
                min_count=0,
            )
            if activity_spans:
                activity_type = activity_spans[0].text_content().strip()
            else:
                # Fallback to text content (strip document links text)
                activity_type = cells[0].text_content().strip()
            if not activity_type:
                activity_type = "Unknown"

            # Column 1: Number (e.g., "AC 49011")
            number = None
            if len(cells) > 1:
                number_text = cells[1].text_content().strip()
                if number_text:
                    number = number_text

            # Column 2: Date filed
            date_filed = None
            if len(cells) > 2:
                date_text = cells[2].text_content().strip()
                if date_text:
                    date_match = self.DOCKET_DATE_PATTERN.search(date_text)
                    if date_match:
                        try:
                            date_filed = datetime.strptime(
                                date_match.group(1), "%m/%d/%Y"
                            ).date()
                        except ValueError:
                            pass

            # Column 3: Initiated by
            initiated_by = None
            if len(cells) > 3:
                initiated_by_text = cells[3].text_content().strip()
                if initiated_by_text:
                    initiated_by = initiated_by_text

            # Column 4: Description - extract from lblDescription span or text
            description = None
            if len(cells) > 4:
                desc_spans = cells[4].query(
                    XPath(".//span[contains(@id, 'lblDescription')]"),
                    "description span",
                    min_count=0,
                )
                if desc_spans:
                    description = desc_spans[0].text_content().strip()
                else:
                    desc_text = cells[4].text_content().strip()
                    if desc_text:
                        description = desc_text

            # Column 5: Action (e.g., "Filed", "Granted")
            action = None
            if len(cells) > 5:
                action_text = cells[5].text_content().strip()
                if action_text:
                    action = action_text

            # Column 6: Action date
            action_date = None
            if len(cells) > 6:
                action_date_text = cells[6].text_content().strip()
                if action_date_text:
                    date_match = self.DOCKET_DATE_PATTERN.search(
                        action_date_text
                    )
                    if date_match:
                        try:
                            action_date = datetime.strptime(
                                date_match.group(1), "%m/%d/%Y"
                            ).date()
                        except ValueError:
                            pass

            # Column 7: Notice date
            notice_date = None
            if len(cells) > 7:
                notice_date_text = cells[7].text_content().strip()
                if notice_date_text:
                    date_match = self.DOCKET_DATE_PATTERN.search(
                        notice_date_text
                    )
                    if date_match:
                        try:
                            notice_date = datetime.strptime(
                                date_match.group(1), "%m/%d/%Y"
                            ).date()
                        except ValueError:
                            pass

            # Check for PDF document link in the Activity column (first cell)
            document_url = None
            pdf_links = cells[0].query(
                XPath(".//a[contains(@href, 'Document')]"),
                "document PDF link",
                min_count=0,
            )
            if pdf_links:
                href = pdf_links[0].get_attribute("href")
                # Resolve relative URLs against base URL
                document_url = (
                    urljoin(DOCKET_CONFIG["base_url"], href) if href else None
                )

            # Check for paperless filing indicator
            paperless_indicators = row.query(
                XPath(
                    ".//img[contains(@alt, 'aperless') or @title='Paperless']"
                ),
                "paperless filing indicator",
                min_count=0,
            )
            is_paperless = bool(paperless_indicators)

            entry_data = {
                "activity_type": activity_type,
                "number": number,
                "date_filed": date_filed,
                "initiated_by": initiated_by,
                "description": description,
                "action": action,
                "action_date": action_date,
                "notice_date": notice_date,
                "document_url": document_url,
                "is_paperless": is_paperless,
            }
            entries.append(entry_data)

        return entries

    def _parse_preliminary_papers(
        self, page: PageElement
    ) -> list[ConnPreliminaryPaper]:
        """Parse preliminary papers section from the page.

        Returns a list of ConnPreliminaryPaper objects.

        Table structure (gvPrelimPapers):
        Column 0: Party Name
        Column 1: Preliminary Statement of the Issues
        Column 2: Designation of the Proposed Contents of the Clerk Appendix
        Column 3: Certificate re Transcript Received
        Column 4: Docketing Statement
        Column 5: PAC Statement
        Column 6: Constitutionality Notice
        Column 7: Sealing Notice
        Column 8: Certificate of Interested Entities
        """
        papers: list[ConnPreliminaryPaper] = []

        # Find the Preliminary Papers table by ID
        prelim_tables = page.query(
            XPath("//table[@id='gvPrelimPapers']"),
            "preliminary papers table",
            min_count=0,
        )

        if not prelim_tables:
            return papers

        rows = prelim_tables[0].query(
            XPath(".//tr"),
            "preliminary papers rows",
            min_count=0,
        )

        # Helper to extract date from cell
        def get_date_from_cell(cells: list, cell_idx: int) -> date | None:
            if len(cells) <= cell_idx:
                return None
            date_text = cells[cell_idx].text_content().strip()
            if not date_text or date_text == "\xa0":  # &nbsp;
                return None
            date_match = self.DOCKET_DATE_PATTERN.search(date_text)
            if date_match:
                try:
                    return datetime.strptime(
                        date_match.group(1), "%m/%d/%Y"
                    ).date()
                except ValueError:
                    pass
            return None

        for row in rows:
            # Skip header rows
            if row.query(XPath(".//th"), "header cells", min_count=0):
                continue

            cells = row.query(XPath(".//td"), "table cells", min_count=0)
            if len(cells) < 1:
                continue

            # Column 0: Party Name
            party_name = cells[0].text_content().strip()
            if not party_name:
                continue

            paper = ConnPreliminaryPaper(
                party_name=party_name,
                preliminary_statement_of_issues=get_date_from_cell(cells, 1),
                designation_clerk_appendix=get_date_from_cell(cells, 2),
                certificate_transcript_received=get_date_from_cell(cells, 3),
                docketing_statement=get_date_from_cell(cells, 4),
                pac_statement=get_date_from_cell(cells, 5),
                constitutionality_notice=get_date_from_cell(cells, 6),
                sealing_notice=get_date_from_cell(cells, 7),
                certificate_interested_entities=get_date_from_cell(cells, 8),
            )
            papers.append(paper)

        return papers

    def _parse_transcripts(
        self, page: PageElement
    ) -> tuple[list[ConnTranscriptInfo], date | None]:
        """Parse transcripts and exhibits section from the page.

        Returns a tuple of (list of ConnTranscriptInfo objects, exhibits_received_date).

        Table structure (gvTranscripts):
        Column 0: Party
        Column 1: Transcripts Ordered
        Column 2: Estimated Delivery Date
        Column 3: Delivered To Party
        Column 4: Pages
        Column 5: Delivered To Court

        Also extracts "Exhibits Received By Court" date from lblExhbitsRecByCourt.
        """
        transcripts: list[ConnTranscriptInfo] = []
        exhibits_received: date | None = None

        # Extract Exhibits Received By Court date
        exhibits_elem = page.query(
            XPath("//span[@id='lblExhbitsRecByCourt']"),
            "exhibits received by court",
            min_count=0,
        )
        if exhibits_elem:
            exhibits_text = exhibits_elem[0].text_content().strip()
            if exhibits_text:
                date_match = self.DOCKET_DATE_PATTERN.search(exhibits_text)
                if date_match:
                    try:
                        exhibits_received = datetime.strptime(
                            date_match.group(1), "%m/%d/%Y"
                        ).date()
                    except ValueError:
                        pass

        # Find the Transcripts table by ID
        transcript_tables = page.query(
            XPath("//table[@id='gvTranscripts']"),
            "transcripts table",
            min_count=0,
        )

        if not transcript_tables:
            return transcripts, exhibits_received

        rows = transcript_tables[0].query(
            XPath(".//tr"),
            "transcript rows",
            min_count=0,
        )

        # Helper to extract date from cell
        def get_date_from_cell(cells: list, cell_idx: int) -> date | None:
            if len(cells) <= cell_idx:
                return None
            date_text = cells[cell_idx].text_content().strip()
            if not date_text or date_text == "\xa0":  # &nbsp;
                return None
            date_match = self.DOCKET_DATE_PATTERN.search(date_text)
            if date_match:
                try:
                    return datetime.strptime(
                        date_match.group(1), "%m/%d/%Y"
                    ).date()
                except ValueError:
                    pass
            return None

        for row in rows:
            # Skip header rows
            if row.query(XPath(".//th"), "header cells", min_count=0):
                continue

            cells = row.query(XPath(".//td"), "table cells", min_count=0)
            if len(cells) < 1:
                continue

            # Column 0: Party Name
            party_name = cells[0].text_content().strip()
            if not party_name:
                continue

            # Column 4: Pages (integer, not date)
            pages = None
            if len(cells) > 4:
                pages_text = cells[4].text_content().strip()
                if pages_text and pages_text != "\xa0":
                    try:
                        pages = int(pages_text)
                    except ValueError:
                        pass

            transcript = ConnTranscriptInfo(
                party_name=party_name,
                transcripts_ordered=get_date_from_cell(cells, 1),
                estimated_delivery_date=get_date_from_cell(cells, 2),
                delivered_to_party=get_date_from_cell(cells, 3),
                pages=pages,
                delivered_to_court=get_date_from_cell(cells, 5),
            )
            transcripts.append(transcript)

        return transcripts, exhibits_received

    def _extract_subscription_url(self, page: PageElement) -> str | None:
        """Extract the email subscription URL from the page.

        Looks for the "To receive an email when there is activity on this case"
        link (hlnkSubscribe).
        """
        subscribe_links = page.find_links(
            XPath("//a[@id='hlnkSubscribe']"),
            "subscription link",
            min_count=0,
        )
        if subscribe_links:
            return subscribe_links[0].url
        return None

    # =========================================================================
    # Trial Court Docket Scraping Steps
    # =========================================================================

    # XPath patterns for trial court docket page elements (civilinquiry.jud.ct.gov)
    XPATH_TC_CASE_TYPE = "//span[contains(@id, 'lblCaseType') or contains(@id, 'lblBasicCaseType')]"
    XPATH_TC_FILE_DATE = "//span[contains(@id, 'lblFileDate')]"
    XPATH_TC_RETURN_DATE = "//span[contains(@id, 'lblReturnDate')]"
    XPATH_TC_COURT_LOCATION = "//span[contains(@id, 'lblLocation') or contains(@id, 'lblBasicLocation')]"
    XPATH_TC_DISPOSITION = "//span[contains(@id, 'lblDisposition')]"
    XPATH_TC_JUDGE = "//span[contains(@id, 'lblJudge')]"
    XPATH_TC_PARTIES_TABLE = "//table[contains(@id, 'gvParties')]"
    XPATH_TC_DOCUMENTS_TABLE = "//table[contains(@id, 'gvDocuments')]"

    @step
    def parse_trial_court_docket(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            ConnTrialCourtDocket
            | ConnTrialCourtDocketEntry
            | ConnTrialCaseUnavailable
        ],
        None,
        None,
    ]:
        """Parse Connecticut trial court docket page from civilinquiry.jud.ct.gov.

        Extracts:
        - Case information (docket number, case name, type, dates)
        - Parties and attorneys
        - Docket entries (motions/pleadings/documents/case status)

        Many older trial court cases are no longer in civilinquiry and return
        a redirect or empty page. These yield ConnTrialCaseUnavailable instead.

        Entries with documents trigger ArchiveRequest for download.
        """
        appellate_docket_id = accumulated_data.get("appellate_docket_id")
        trial_docket_number = accumulated_data.get("trial_docket_number")

        # Check if the page has actual case detail content.
        # Unavailable cases (e.g., old cases purged from civilinquiry) return
        # a 302 redirect stub with no case detail elements.
        case_banner = page.query(
            XPath(
                "//span[contains(@class, 'casenamebanner')] | //td[contains(@class, 'casenamebanner')]"
            ),
            "case name banner",
            min_count=0,
        )
        has_case_type = page.query(
            XPath(self.XPATH_TC_CASE_TYPE),
            "case type",
            min_count=0,
        )
        if not case_banner and not has_case_type:
            # No case content found — this trial court case is unavailable
            trial_docket_id = trial_docket_number
            if not trial_docket_id and "DocketNo=" in response.url:
                trial_docket_id = response.url.split("DocketNo=")[-1].split(
                    "&"
                )[0]
            if trial_docket_id:
                yield ParsedData(
                    ConnTrialCaseUnavailable(
                        court_id="connsuperct",
                        trial_docket_id=trial_docket_id,
                        appellate_docket_id=appellate_docket_id,
                        source_url=response.url,
                        message="Trial court case not available in civilinquiry",
                    )
                )
            return

        # Extract trial docket ID from page title or URL
        # Page title format: "Case Detail - HHD-CV23-5076142-S"
        title_elem = page.query(
            XPath("//title"),
            "page title",
            min_count=0,
        )
        trial_docket_id = trial_docket_number
        if title_elem:
            title_text = title_elem[0].text_content().strip()
            if "Case Detail -" in title_text:
                trial_docket_id = title_text.replace(
                    "Case Detail -", ""
                ).strip()

        if not trial_docket_id and "DocketNo=" in response.url:
            trial_docket_id = response.url.split("DocketNo=")[-1].split("&")[0]

        if not trial_docket_id:
            return  # Cannot parse without docket ID

        # Extract case name from header
        case_name_elems = page.query(
            XPath(
                "//span[contains(@class, 'casenamebanner') and contains(text(), 'v.')]"
                " | //td[contains(@class, 'casenamebanner')]"
            ),
            "case name",
            min_count=0,
        )
        case_name = "Unknown"
        if case_name_elems:
            # Find the element with the case name (contains "v.")
            for elem in case_name_elems:
                text = elem.text_content().strip()
                if " v. " in text or " v " in text.lower():
                    case_name = text
                    break

        # Helper to extract text
        def extract_text(xpath_expr: str) -> str | None:
            elems = page.query(XPath(xpath_expr), "text field", min_count=0)
            if elems:
                text = elems[0].text_content().strip()
                # Clean up text - remove label prefix if present
                if ":" in text:
                    text = text.split(":", 1)[-1].strip()
                return text if text else None
            return None

        # Helper to extract date
        def extract_date(xpath_expr: str) -> date | None:
            text = extract_text(xpath_expr)
            if text:
                date_match = self.DOCKET_DATE_PATTERN.search(text)
                if date_match:
                    try:
                        return datetime.strptime(
                            date_match.group(1), "%m/%d/%Y"
                        ).date()
                    except ValueError:
                        pass
            return None

        # Extract case information
        case_type = extract_text(self.XPATH_TC_CASE_TYPE)
        case_type_description = None
        if case_type and " - " in case_type:
            parts = case_type.split(" - ", 1)
            case_type = parts[0].strip()
            case_type_description = case_type.strip()

        file_date = extract_date(self.XPATH_TC_FILE_DATE)
        return_date = extract_date(self.XPATH_TC_RETURN_DATE)
        court_location = extract_text(self.XPATH_TC_COURT_LOCATION)
        disposition = extract_text(self.XPATH_TC_DISPOSITION)
        judge = extract_text(self.XPATH_TC_JUDGE)

        # Extract disposition date if present (from disposition text)
        disposition_date = None
        if disposition:
            date_match = self.DOCKET_DATE_PATTERN.search(disposition)
            if date_match:
                try:
                    disposition_date = datetime.strptime(
                        date_match.group(1), "%m/%d/%Y"
                    ).date()
                except ValueError:
                    pass

        # Parse parties
        parties = self._parse_trial_court_parties(page)

        # Parse docket entries
        entries = self._parse_trial_court_entries(page)

        # Yield the ConnTrialCourtDocket (without embedded entries)
        docket = ConnTrialCourtDocket(
            court_id="connsuperct",
            trial_docket_id=trial_docket_id,
            appellate_docket_id=appellate_docket_id,
            case_name=case_name,
            case_type=case_type,
            case_type_description=case_type_description,
            court_location=court_location,
            file_date=file_date,
            return_date=return_date,
            disposition=disposition,
            disposition_date=disposition_date,
            judge=judge,
            parties=parties,
            source_url=response.url,
        )
        yield ParsedData(docket)

        # Yield docket entries - with ArchiveRequest for documents
        for entry_data in entries:
            entry = ConnTrialCourtDocketEntry(
                trial_docket_id=trial_docket_id,
                court_id="connsuperct",
                conn_entry_number=entry_data.get("conn_entry_number"),
                date_filed=entry_data.get("date_filed"),
                filed_by=entry_data.get("filed_by"),
                description=entry_data.get("description"),
                additional_description=entry_data.get(
                    "additional_description"
                ),
                result=entry_data.get("result"),
                arguable=entry_data.get("arguable", False),
                document_url=entry_data.get("document_url"),
            )

            if entry_data.get("document_url"):
                # Yield ArchiveRequest for document download
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=entry_data["document_url"],
                    ),
                    continuation=self.handle_trial_court_document_download,
                    expected_type="pdf",
                    accumulated_data={
                        "entry": entry.model_dump(mode="json"),
                    },
                )
            else:
                # No document - yield entry directly
                yield ParsedData(entry)

    @step
    def handle_trial_court_document_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[ConnTrialCourtDocketEntry], None, None]:
        """Handle a downloaded trial court document.

        Yields a single ConnTrialCourtDocketEntry with the downloaded document path.
        """
        entry_data = accumulated_data["entry"]

        # Helper to parse ISO date strings
        def iso_to_date(s: str | None) -> date | None:
            if s:
                return datetime.fromisoformat(s).date()
            return None

        # Rebuild entry with local path
        entry = ConnTrialCourtDocketEntry(
            trial_docket_id=entry_data["trial_docket_id"],
            court_id=entry_data["court_id"],
            conn_entry_number=entry_data.get("conn_entry_number"),
            date_filed=iso_to_date(entry_data.get("date_filed")),
            filed_by=entry_data.get("filed_by"),
            description=entry_data.get("description"),
            additional_description=entry_data.get("additional_description"),
            result=entry_data.get("result"),
            arguable=entry_data.get("arguable", False),
            document_url=entry_data.get("document_url"),
            document_local_path=response.file_url,
        )

        yield ParsedData(entry)

    def _parse_trial_court_parties(
        self, page: PageElement
    ) -> list[ConnTrialCourtParty]:
        """Parse party information from trial court docket page.

        Returns a list of ConnTrialCourtParty objects.

        Table structure (gvParties):
        - Party number (P-01, D-01, etc.)
        - Party name
        - Nested gvAttyInfo table with attorney details
        """
        parties: list[ConnTrialCourtParty] = []

        # Find the parties table
        party_tables = page.query(
            XPath(self.XPATH_TC_PARTIES_TABLE),
            "parties table",
            min_count=0,
        )

        if not party_tables:
            return parties

        # Find all party rows (look for rows with party number spans)
        party_rows = party_tables[0].query(
            XPath(".//tr[.//span[contains(@id, 'lblPlaintDefPartyNo')]]"),
            "party rows",
            min_count=0,
        )

        for row in party_rows:
            # Extract party number
            party_num_elems = row.query(
                XPath(".//span[contains(@id, 'lblPlaintDefPartyNo')]"),
                "party number",
                min_count=0,
            )
            if not party_num_elems:
                continue

            party_number = party_num_elems[0].text_content().strip()

            # Extract party name
            party_name_elems = row.query(
                XPath(".//span[contains(@id, 'lblPtyPartyName')]"),
                "party name",
                min_count=0,
            )
            if not party_name_elems:
                continue

            party_name = party_name_elems[0].text_content().strip()

            # Determine party type from party number
            party_type = None
            if party_number.startswith("P"):
                party_type = "Plaintiff"
            elif party_number.startswith("D"):
                party_type = "Defendant"
            elif party_number.startswith("L"):
                party_type = "For Notice Only"

            # Check for self-represented
            self_rep_elems = row.query(
                XPath(
                    ".//span[contains(@id, 'lblAppearanceTitle') and contains(text(), 'Self-Rep')]"
                ),
                "self-rep indicator",
                min_count=0,
            )
            self_represented = bool(self_rep_elems)

            # Extract attorney info
            attorneys: list[dict] = []
            atty_info_elems = row.query(
                XPath(".//span[contains(@id, 'lblAppearanceInfo1')]"),
                "attorney info",
                min_count=0,
            )
            for atty_elem in atty_info_elems:
                atty_text = atty_elem.text_content().strip()
                if atty_text:
                    # Parse attorney text - typically format:
                    # "NAME (JURIS_NUMBER)\nFIRM\nADDRESS"
                    lines = [
                        line.strip()
                        for line in atty_text.replace("<br />", "\n").split(
                            "\n"
                        )
                        if line.strip()
                    ]
                    atty_info: dict[str, str | None] = {"raw": atty_text}

                    # Try to extract juris number from first line
                    if lines and "(" in lines[0] and ")" in lines[0]:
                        name_part = lines[0]
                        juris_match = re.search(r"\((\d+)\)", name_part)
                        if juris_match:
                            atty_info["juris_number"] = juris_match.group(1)
                            atty_info["name"] = name_part[
                                : juris_match.start()
                            ].strip()
                        else:
                            atty_info["name"] = name_part
                    elif lines:
                        atty_info["name"] = lines[0]

                    attorneys.append(atty_info)

            party = ConnTrialCourtParty(
                party_number=party_number,
                name=party_name,
                party_type=party_type,
                self_represented=self_represented,
                attorneys=attorneys,
            )
            parties.append(party)

        return parties

    def _parse_trial_court_entries(self, page: PageElement) -> list[dict]:
        """Parse docket entries from trial court docket page.

        Returns a list of dicts with entry data.

        Table structure (gvDocuments):
        Columns: Entry No, File Date, Filed By, Description, Arguable
        - Document links in Description column
        - Additional description in lblAddDesc span
        - Result in lblResult span
        """
        entries: list[dict] = []

        # Find the documents table
        doc_tables = page.query(
            XPath(self.XPATH_TC_DOCUMENTS_TABLE),
            "documents table",
            min_count=0,
        )

        if not doc_tables:
            return entries

        # Get all data rows (skip header row)
        rows = doc_tables[0].query(
            XPath(".//tr[td]"),
            "document rows",
            min_count=0,
        )

        for row in rows:
            cells = row.query(XPath(".//td"), "table cells", min_count=0)
            if len(cells) < 4:
                continue

            # Column 0: Entry Number
            conn_entry_number: str | None = cells[0].text_content().strip()
            if conn_entry_number == "\xa0" or not conn_entry_number:
                conn_entry_number = None

            # Column 1: File Date
            date_filed = None
            date_text = cells[1].text_content().strip()
            if date_text:
                date_match = self.DOCKET_DATE_PATTERN.search(date_text)
                if date_match:
                    try:
                        date_filed = datetime.strptime(
                            date_match.group(1), "%m/%d/%Y"
                        ).date()
                    except ValueError:
                        pass

            # Column 2: Filed By
            filed_by_elems = cells[2].query(
                XPath(".//span[contains(@id, 'lblFiledBy')]"),
                "filed by",
                min_count=0,
            )
            filed_by = None
            if filed_by_elems:
                filed_by = filed_by_elems[0].text_content().strip()
                if filed_by == "\xa0" or not filed_by:
                    filed_by = None

            # Column 3: Description - check for document link
            description = None
            document_url = None
            additional_description = None
            result = None

            # Look for document link
            doc_links = cells[3].query(
                XPath(".//a[contains(@id, 'hlnkDocument')]"),
                "document link",
                min_count=0,
            )
            if doc_links:
                description = doc_links[0].text_content().strip()
                href = doc_links[0].get_attribute("href")
                if href:
                    # Resolve relative URL
                    document_url = urljoin(
                        TRIAL_COURT_CONFIG["base_url"], href
                    )
            else:
                # No link - get text directly
                desc_text = cells[3].text_content().strip()
                if desc_text and desc_text != "\xa0":
                    description = desc_text

            # Look for additional description
            add_desc_elems = cells[3].query(
                XPath(".//span[contains(@id, 'lblAddDesc')]"),
                "additional description",
                min_count=0,
            )
            if add_desc_elems:
                add_text = add_desc_elems[0].text_content().strip()
                if add_text and add_text != "\xa0":
                    additional_description = add_text

            # Look for result
            result_elems = cells[3].query(
                XPath(".//span[contains(@id, 'lblResult')]"),
                "result",
                min_count=0,
            )
            if result_elems:
                result_text = result_elems[0].text_content().strip()
                if result_text and result_text != "\xa0":
                    result = result_text

            # Column 4: Arguable
            arguable = False
            if len(cells) > 4:
                arguable_text = cells[4].text_content().strip()
                arguable = arguable_text.lower() == "yes"

            entry_data = {
                "conn_entry_number": conn_entry_number,
                "date_filed": date_filed,
                "filed_by": filed_by,
                "description": description,
                "additional_description": additional_description,
                "result": result,
                "arguable": arguable,
                "document_url": document_url,
            }
            entries.append(entry_data)

        return entries
