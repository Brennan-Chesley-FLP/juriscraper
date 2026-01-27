"""Tennessee Appellate Courts Scraper.

This module contains a unified scraper for judges, opinions, oral arguments,
and dockets from Tennessee courts::

    - Tennessee Supreme Court (tenn)
    - Court of Appeals of Tennessee (tennctapp)
    - Court of Criminal Appeals of Tennessee (tenncrimapp)

Entry points::

    - Judges:
      - https://www.tncourts.gov/courts/{court}/judges
    - Opinions:
      - https://www.tncourts.gov/courts/{court}/opinions
    - Oral Arguments:
      - https://www.tncourts.gov/courts/{court}/oral-arguments (YouTube videos)
    - Dockets:
      - https://pch.tncourts.gov/CaseDetails.aspx?id={N}

Judges Flow::

    1. get_entry -> judges list page for selected courts (if "judges" requested)
    2. parse_judges_list -> yields requests for each judge detail page
    3. parse_judge_detail -> extracts profile, yields ArchiveRequest for photo
    4. handle_judge_photo -> stores local path, yields final TennJudge

Opinions Flow::

    1. get_entry -> opinions page for selected courts (if "opinions" requested)
    2. parse_opinions_list -> extracts opinion metadata, handles pagination
    3. yields ArchiveRequests for PDFs
    4. handle_opinion_download -> stores local paths, yields final clusters

Oral Arguments Flow::

    1. get_entry -> oral arguments page for selected courts (if "oral_arguments" requested)
    2. parse_oral_args_index -> extracts year links
    3. parse_oral_args_videos -> extracts YouTube URLs, yields TennOralArgument

Dockets Flow::

    1. @speculate fetch_docket -> generates requests for PCH IDs (seeded by driver)
    2. parse_docket_page -> parses case detail, yields TennDocket

Design decisions::

    - Uses restrictive checked_xpaths to catch structural changes early
    - Uses DateRange filter on date_filed/date_argued for searching
    - Uses SetFilter on court_id to select which courts to scrape
    - Uses @speculate fetch_docket for speculative docket scraping
    - Archives judge photos and opinion PDFs via ArchiveRequest
    - YouTube videos are not downloaded, only URLs captured
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin

from juriscraper.scraper_driver.common.checked_html import CheckedHtmlElement
from juriscraper.scraper_driver.common.decorators import speculate, step
from juriscraper.scraper_driver.data_types import (
    ArchiveRequest,
    ArchiveResponse,
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    NavigatingRequest,
    ParsedData,
    Response,
    ScraperStatus,
)

from .models import (
    COURT_CONFIG,
    DOCKET_CONFIG,
    TennDocket,
    TennDocketEntry,
    TennJudge,
    TennOpinion,
    TennOpinionCluster,
    TennOralArgument,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


class TennScraper(
    BaseScraper[TennJudge | TennOpinionCluster | TennOralArgument | TennDocket]
):
    """Unified scraper for Tennessee appellate court data.

    Scrapes judges, opinions, oral argument videos, and docket information
    from Tennessee courts.

    Supports Tennessee Supreme Court (tenn), Court of Appeals (tennctapp),
    and Court of Criminal Appeals (tenncrimapp).

    Usage:
        # Scrape everything (all data types, all courts)
        scraper = TennScraper()

        # Scrape only judges (disable other data types)
        params = TennScraper.params()
        params.TennOpinionCluster = None
        params.TennOralArgument = None
        params.TennDocket = None
        scraper = TennScraper(params=params)

        # Scrape only opinions from Supreme Court
        params = TennScraper.params()
        params.TennJudge = None
        params.TennOralArgument = None
        params.TennDocket = None
        params.TennOpinionCluster.court_id.values = {"tenn"}
        scraper = TennScraper(params=params)

        # Scrape dockets starting from a specific ID
        params = TennScraper.params()
        params.TennJudge = None
        params.TennOpinionCluster = None
        params.TennOralArgument = None
        params.TennDocket.pch_id.gt = 89580
        scraper = TennScraper(params=params)

        # Scrape a specific docket by PCH ID
        params = TennScraper.params()
        params.TennJudge = None
        params.TennOpinionCluster = None
        params.TennOralArgument = None
        params.TennDocket.pch_id.eq = 89587
        scraper = TennScraper(params=params)

        # Filter opinions by date range
        params = TennScraper.params()
        params.TennOpinionCluster.date_filed.gte = date(2025, 1, 1)
        params.TennOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = TennScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"tenn", "tennctapp", "tenncrimapp"}
    court_url: ClassVar[str] = "https://www.tncourts.gov/"
    data_types: ClassVar[set[str]] = {
        "judges",
        "opinions",
        "oral_arguments",
        "dockets",
    }
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2025-01-13"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # === Regex patterns ===
    # Date patterns: various formats seen on TN courts
    # Supports both 4-digit and 2-digit years (e.g., 12/22/2025 or 12/22/25)
    DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})")
    YEAR_PATTERN = re.compile(r"(\d{4})")
    # Case number pattern: e.g., "M2023-01234-SC-R11-CV"
    CASE_NUMBER_PATTERN = re.compile(
        r"([MEWC]\d{4}-\d{4,5}(?:-[A-Z]{2,3})?(?:-[A-Z]\d+)?(?:-[A-Z]{2,3})?)"
    )
    # YouTube URL pattern
    YOUTUBE_PATTERN = re.compile(
        r"(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]+)"
    )
    YOUTUBE_PLAYLIST_PATTERN = re.compile(r"list=([a-zA-Z0-9_-]+)")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "TennJudge": "judges",
        "TennOpinionCluster": "opinions",
        "TennOralArgument": "oral_arguments",
        "TennDocket": "dockets",
    }

    def _parse_date(self, date_str: str) -> date | None:
        """Parse a date string that may have 2 or 4 digit year.

        Supports formats like:
        - 12/22/2025 (4-digit year)
        - 12/22/25 (2-digit year, assumes 2000s)

        Args:
            date_str: Date string in MM/DD/YY or MM/DD/YYYY format.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        try:
            # Try 4-digit year first
            return datetime.strptime(date_str, "%m/%d/%Y").date()
        except ValueError:
            pass

        try:
            # Try 2-digit year (strptime interprets 00-68 as 2000-2068, 69-99 as 1969-1999)
            return datetime.strptime(date_str, "%m/%d/%y").date()
        except ValueError:
            pass

        return None

    def _get_requested_data_types(self) -> set[str]:
        """Get the set of data types to scrape based on enabled models.

        Maps enabled model names to their corresponding data types.
        If no params are set, returns all data types.
        """
        if self._params is None:
            return self.data_types

        enabled_models = self._params.get_enabled_models()
        if not enabled_models:
            # No models enabled means all disabled - return empty
            return set()

        # Map enabled model names to data types
        enabled_data_types = set()
        for model_name in enabled_models:
            if model_name in self.MODEL_TO_DATA_TYPE:
                enabled_data_types.add(self.MODEL_TO_DATA_TYPE[model_name])

        return enabled_data_types & self.data_types

    # =========================================================================
    # Parameter extraction
    # =========================================================================

    def _get_judges_search_params(self) -> tuple[str | None, set[str] | None]:
        """Extract search parameters for judges from ScraperParams.

        Returns:
            Tuple of (slug, court_ids)
        """
        if self._params is None:
            return None, None

        try:
            model_proxy = self._params.TennJudge
        except AttributeError:
            return None, None

        slug = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        slug_field = searchable.get("slug")
        if slug_field and slug_field.is_set():
            slug = slug_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return slug, court_ids

    def _get_opinions_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters for opinions from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, case_number, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.TennOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        case_number = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        case_field = searchable.get("case_number")
        if case_field and case_field.is_set():
            case_number = case_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, case_number, court_ids

    def _get_oral_args_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters for oral arguments from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, case_number, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.TennOralArgument
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        case_number = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_argued")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        case_field = searchable.get("case_number")
        if case_field and case_field.is_set():
            case_number = case_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, case_number, court_ids

    def _get_docket_search_params(
        self,
    ) -> tuple[int | None, int | None, set[str] | None]:
        """Extract search parameters for dockets from ScraperParams.

        Returns:
            Tuple of (pch_id_gt, pch_id_eq, court_ids)
            - pch_id_gt: Start scraping after this ID (exclusive)
            - pch_id_eq: Scrape exactly this ID
            - court_ids: Filter to specific courts (applied after fetching)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.TennDocket
        except AttributeError:
            return None, None, None

        pch_id_gt = None
        pch_id_eq = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        pch_field = searchable.get("pch_id")
        if pch_field and pch_field.is_set():
            pch_id_gt = pch_field.gt
            pch_id_eq = pch_field.eq

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return pch_id_gt, pch_id_eq, court_ids

    def _get_target_courts(self, data_type: str) -> set[str]:
        """Get the set of court IDs to scrape for a given data type."""
        if data_type == "judges":
            _, court_ids = self._get_judges_search_params()
        elif data_type == "opinions":
            _, _, _, court_ids = self._get_opinions_search_params()
        elif data_type == "oral_arguments":
            _, _, _, court_ids = self._get_oral_args_search_params()
        elif data_type == "dockets":
            _, _, court_ids = self._get_docket_search_params()
        else:
            court_ids = None

        if court_ids:
            valid_courts = court_ids & set(COURT_CONFIG.keys())
            if valid_courts:
                return valid_courts

        return set(COURT_CONFIG.keys())

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(
        self,
    ) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for each enabled data type.

        Yields separate NavigatingRequests for judges, opinions, oral arguments,
        and dockets based on which models are enabled in params.
        """
        requested = self._get_requested_data_types()

        if "judges" in requested:
            yield from self._get_judges_entry()

        if "opinions" in requested:
            yield from self._get_opinions_entry()

        if "oral_arguments" in requested:
            yield from self._get_oral_args_entry()

        # Dockets are handled by @speculate fetch_docket - no entry request needed
        # The driver discovers fetch_docket and seeds the queue directly

    # =========================================================================
    # Judges Scraping Steps
    # =========================================================================

    def _get_judges_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for judges scraping."""
        target_courts = self._get_target_courts("judges")
        first_court = sorted(target_courts)[0]
        config = COURT_CONFIG[first_court]

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=config["judges_url"],
            ),
            continuation=self.parse_judges_list,
            accumulated_data={
                "court_id": first_court,
                "remaining_courts": sorted(target_courts - {first_court}),
            },
        )

    @step(xsd="xsds/parse_judges_list.xsd")
    def parse_judges_list(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            TennJudge | TennOpinionCluster | TennOralArgument | TennDocket
        ],
        None,
        None,
    ]:
        """Parse the judges list page and yield requests for each judge detail."""
        court_id = accumulated_data.get("court_id")
        remaining_courts = accumulated_data.get("remaining_courts", [])
        target_slug, _ = self._get_judges_search_params()

        # Find judge links - they appear as image links or text links
        # Look for links containing /judges/ in the href
        judge_links = lxml_tree.xpath(
            "//a[contains(@href, '/judges/') and not(contains(@href, '/judges?'))]"
        )

        seen_slugs: set[str] = set()

        for link in judge_links:
            href = link.get("href", "")
            if not href:
                continue

            # Extract slug from URL
            # URL format: /courts/{court}/judges/{slug}
            parts = href.rstrip("/").split("/")
            if len(parts) < 2:
                continue

            slug = parts[-1]
            if not slug or slug in seen_slugs:
                continue

            # Filter by target slug if specified
            if target_slug and slug != target_slug:
                continue

            seen_slugs.add(slug)

            judge_url = urljoin(response.url, href)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=judge_url,
                ),
                continuation=self.parse_judge_detail,
                accumulated_data={
                    "court_id": court_id,
                    "slug": slug,
                },
            )

        # After processing all judges for this court, move to next court
        if remaining_courts:
            next_court = remaining_courts[0]
            config = COURT_CONFIG[next_court]
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=config["judges_url"],
                ),
                continuation=self.parse_judges_list,
                accumulated_data={
                    "court_id": next_court,
                    "remaining_courts": remaining_courts[1:],
                },
            )

    @step(xsd="xsds/parse_judge_detail.xsd")
    def parse_judge_detail(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            TennJudge | TennOpinionCluster | TennOralArgument | TennDocket
        ],
        None,
        None,
    ]:
        """Parse a judge's detail page and yield ArchiveRequest for photo."""
        court_id: str = accumulated_data.get("court_id", "")
        slug: str = accumulated_data.get("slug", "")

        # Extract name and title from page
        # Title is usually in a heading
        title_elem = lxml_tree.xpath(
            "//h1[@class='page-title'] | //h1 | //div[contains(@class, 'field-name-field-title')]//div[@class='field-item']"
        )
        full_title = ""
        if title_elem:
            full_title = title_elem[0].text_content().strip()

        # Parse title and name
        # Format might be "Chief Justice Jeffrey S. Bivins" or similar
        title = ""
        name_first = ""
        name_middle = ""
        name_last = ""

        if full_title:
            # Common titles
            title_prefixes = [
                "Chief Justice",
                "Justice",
                "Presiding Judge",
                "Judge",
            ]
            for prefix in title_prefixes:
                if full_title.startswith(prefix):
                    title = prefix
                    name_parts = full_title[len(prefix) :].strip().split()
                    break
            else:
                name_parts = full_title.split()

            if name_parts:
                name_first = name_parts[0] if name_parts else ""
                name_last = name_parts[-1] if len(name_parts) > 1 else ""
                if len(name_parts) > 2:
                    name_middle = " ".join(name_parts[1:-1])

        # Extract biography sections
        biography = self._extract_field_text(lxml_tree, "body")
        year_elected = self._extract_year_elected(lxml_tree)
        prior_judicial = self._extract_field_text(
            lxml_tree, "field-prior-judicial-experience"
        )
        previous_employment = self._extract_field_text(
            lxml_tree, "field-previous-employment"
        )
        education = self._extract_education(lxml_tree)
        memberships = self._extract_field_text(lxml_tree, "field-memberships")
        community = self._extract_field_text(
            lxml_tree, "field-community-involvement"
        )
        contact_info = self._extract_field_text(
            lxml_tree, "field-contact-info"
        )
        address = self._extract_field_text(lxml_tree, "field-address")

        # Find photo URL
        photo_url = None
        photo_elems = lxml_tree.xpath(
            "//div[contains(@class, 'field-name-field-image')]//img/@src | "
            "//img[contains(@class, 'judge-photo')]/@src | "
            "//div[contains(@class, 'judge')]//img/@src"
        )
        if photo_elems:
            photo_url = urljoin(response.url, photo_elems[0])

        # Determine position type
        position_type = None
        if "Chief Justice" in title:
            position_type = "c-jus"
        elif "Justice" in title:
            position_type = "jus"
        elif "Judge" in title:
            position_type = "jud"

        # Build judge data for accumulated_data
        judge_data: dict[str, Any] = {
            "slug": slug,
            "court_id": court_id,
            "name_first": name_first,
            "name_middle": name_middle if name_middle else None,
            "name_last": name_last,
            "title": title,
            "biography": biography,
            "year_elected": year_elected,
            "prior_judicial_experience": prior_judicial,
            "previous_employment": previous_employment,
            "education": education,
            "memberships": memberships,
            "community_involvement": community,
            "contact_info": contact_info,
            "address": address,
            "photo_url": photo_url,
            "position_type": position_type,
            "source_url": response.url,
        }

        if photo_url:
            # Archive the photo
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=photo_url,
                ),
                continuation=self.handle_judge_photo,
                expected_type="image",
                accumulated_data=judge_data,
            )
        else:
            # No photo, yield judge directly
            yield ParsedData(
                TennJudge(
                    **{k: v for k, v in judge_data.items() if v is not None}
                )
            )

    def _extract_field_text(
        self, lxml_tree: CheckedHtmlElement, field_class: str
    ) -> str | None:
        """Extract text content from a Drupal field div."""
        elems = lxml_tree.xpath(
            f"//div[contains(@class, 'field-name-{field_class}')]//div[@class='field-item'] | "
            f"//div[contains(@class, '{field_class}')]"
        )
        if elems:
            text = elems[0].text_content().strip()
            return text if text else None
        return None

    def _extract_year_elected(
        self, lxml_tree: CheckedHtmlElement
    ) -> int | None:
        """Extract year elected/appointed from the page."""
        elems = lxml_tree.xpath(
            "//div[contains(@class, 'field-name-field-year-elected')]//div[@class='field-item'] | "
            "//div[contains(text(), 'Year Elected') or contains(text(), 'Year Appointed')]/following-sibling::div"
        )
        if elems:
            text = elems[0].text_content().strip()
            match = self.YEAR_PATTERN.search(text)
            if match:
                return int(match.group(1))
        return None

    def _extract_education(self, lxml_tree: CheckedHtmlElement) -> list[str]:
        """Extract education entries from the page."""
        education: list[str] = []
        elems = lxml_tree.xpath(
            "//div[contains(@class, 'field-name-field-education')]//div[@class='field-item']"
        )
        for elem in elems:
            text = elem.text_content().strip()
            if text:
                education.append(text)
        return education

    @step
    def handle_judge_photo(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            TennJudge | TennOpinionCluster | TennOralArgument | TennDocket
        ],
        None,
        None,
    ]:
        """Handle a downloaded judge photo."""
        accumulated_data["photo_local_path"] = response.file_url

        # Filter out None values and create TennJudge
        judge_data = {
            k: v for k, v in accumulated_data.items() if v is not None
        }
        yield ParsedData(TennJudge(**judge_data))

    # =========================================================================
    # Opinions Scraping Steps
    # =========================================================================

    def _get_opinions_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinions scraping."""
        target_courts = self._get_target_courts("opinions")
        first_court = sorted(target_courts)[0]
        config = COURT_CONFIG[first_court]

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=config["opinions_url"],
            ),
            continuation=self.parse_opinions_list,
            accumulated_data={
                "court_id": first_court,
                "remaining_courts": sorted(target_courts - {first_court}),
                "page": 0,
            },
        )

    @step(xsd="xsds/parse_opinions_list.xsd")
    def parse_opinions_list(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            TennJudge | TennOpinionCluster | TennOralArgument | TennDocket
        ],
        None,
        None,
    ]:
        """Parse the opinions listing page and yield opinion clusters."""
        court_id: str = accumulated_data.get("court_id", "")
        remaining_courts = accumulated_data.get("remaining_courts", [])
        current_page = accumulated_data.get("page", 0)
        date_gte, date_lte, target_case_number, _ = (
            self._get_opinions_search_params()
        )

        # Find opinion rows in the table
        # Look for table rows with PDF links
        opinion_rows = lxml_tree.xpath(
            "//table//tr[.//a[contains(@href, '.pdf')]] | "
            "//div[contains(@class, 'view-content')]//div[contains(@class, 'views-row')]"
        )

        for row in opinion_rows:
            # Extract PDF link
            pdf_links = row.xpath(".//a[contains(@href, '.pdf')]")
            if not pdf_links:
                continue

            pdf_url = urljoin(response.url, pdf_links[0].get("href", ""))

            # Extract case number
            case_number = None
            case_num_elems = row.xpath(
                ".//td[1] | .//div[contains(@class, 'case-number')]"
            )
            if case_num_elems:
                text = case_num_elems[0].text_content().strip()
                match = self.CASE_NUMBER_PATTERN.search(text)
                if match:
                    case_number = match.group(1)

            if not case_number:
                # Try to extract from link text
                link_text = pdf_links[0].text_content().strip()
                match = self.CASE_NUMBER_PATTERN.search(link_text)
                if match:
                    case_number = match.group(1)

            if not case_number:
                continue

            # Filter by target case number
            if target_case_number and case_number != target_case_number:
                continue

            # Extract case name
            case_name = "Unknown"
            case_name_elems = row.xpath(
                ".//td[2] | .//div[contains(@class, 'case-name')]"
            )
            if case_name_elems:
                case_name = case_name_elems[0].text_content().strip()

            # Extract date
            date_filed = None
            date_elems = row.xpath(
                ".//td[contains(@class, 'date')] | "
                ".//div[contains(@class, 'date')] | "
                ".//td[3]"
            )
            if date_elems:
                date_text = date_elems[0].text_content().strip()
                match = self.DATE_PATTERN.search(date_text)
                if match:
                    date_filed = self._parse_date(match.group(1))

            # Apply date filters
            if date_filed:
                if date_gte and date_filed < date_gte:
                    continue
                if date_lte and date_filed > date_lte:
                    continue

            # Extract authoring judge
            authoring_judge = None
            judge_elems = row.xpath(
                ".//td[contains(@class, 'author')] | "
                ".//div[contains(@class, 'authoring-judge')] | "
                ".//td[4]"
            )
            if judge_elems:
                authoring_judge = judge_elems[0].text_content().strip() or None

            # Extract trial court judge
            trial_court_judge = None
            trial_judge_elems = row.xpath(
                ".//td[contains(@class, 'trial-judge')] | "
                ".//div[contains(@class, 'trial-judge')] | "
                ".//td[5]"
            )
            if trial_judge_elems:
                trial_court_judge = (
                    trial_judge_elems[0].text_content().strip() or None
                )

            # Extract county
            county = None
            county_elems = row.xpath(
                ".//td[contains(@class, 'county')] | "
                ".//div[contains(@class, 'county')]"
            )
            if county_elems:
                county = county_elems[0].text_content().strip() or None

            # Build cluster data
            cluster_data: dict[str, Any] = {
                "case_number": case_number,
                "court_id": court_id,
                "case_name": case_name,
                "date_filed": date_filed.isoformat() if date_filed else None,
                "authoring_judge": authoring_judge,
                "trial_court_judge": trial_court_judge,
                "county": county,
                "source_url": response.url,
                "opinions_data": [
                    {"download_url": pdf_url, "type": "majority"}
                ],
                "pending_downloads": 1,
                "completed_downloads": 0,
                "downloaded_paths": {},
            }

            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=pdf_url,
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data={
                    **cluster_data,
                    "current_download_index": 0,
                },
            )

        # Handle pagination - look for next page link
        next_page_links = lxml_tree.xpath(
            "//a[contains(@class, 'pager-next')] | "
            "//li[contains(@class, 'pager-next')]/a | "
            "//a[contains(text(), 'next') or contains(text(), 'Next')]"
        )

        if next_page_links:
            next_url = urljoin(
                response.url, next_page_links[0].get("href", "")
            )
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_url,
                ),
                continuation=self.parse_opinions_list,
                accumulated_data={
                    "court_id": court_id,
                    "remaining_courts": remaining_courts,
                    "page": current_page + 1,
                },
            )
        elif remaining_courts:
            # Move to next court
            next_court = remaining_courts[0]
            config = COURT_CONFIG[next_court]
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=config["opinions_url"],
                ),
                continuation=self.parse_opinions_list,
                accumulated_data={
                    "court_id": next_court,
                    "remaining_courts": remaining_courts[1:],
                    "page": 0,
                },
            )

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            TennJudge | TennOpinionCluster | TennOralArgument | TennDocket
        ],
        None,
        None,
    ]:
        """Handle a downloaded opinion PDF."""
        current_index = accumulated_data["current_download_index"]

        accumulated_data["downloaded_paths"][current_index] = response.file_url
        accumulated_data["completed_downloads"] += 1

        if (
            accumulated_data["completed_downloads"]
            >= accumulated_data["pending_downloads"]
        ):
            yield from self._yield_final_opinion_cluster(accumulated_data)
        else:
            next_index = current_index + 1
            opinions_data = accumulated_data["opinions_data"]
            next_opinion = opinions_data[next_index]

            yield ArchiveRequest(
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

    def _yield_final_opinion_cluster(
        self, accumulated_data: dict
    ) -> Generator[
        ScraperYield[
            TennJudge | TennOpinionCluster | TennOralArgument | TennDocket
        ],
        None,
        None,
    ]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                TennOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "majority"),
                    local_path=local_path,
                    authoring_judge=accumulated_data.get("authoring_judge"),
                    trial_court_judge=accumulated_data.get(
                        "trial_court_judge"
                    ),
                )
            )

        date_filed = None
        if accumulated_data.get("date_filed"):
            date_filed = datetime.fromisoformat(
                accumulated_data["date_filed"]
            ).date()

        cluster = TennOpinionCluster(
            case_number=accumulated_data["case_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            authoring_judge=accumulated_data.get("authoring_judge"),
            trial_court_judge=accumulated_data.get("trial_court_judge"),
            county=accumulated_data.get("county"),
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)

    # =========================================================================
    # Oral Arguments Scraping Steps
    # =========================================================================

    def _get_oral_args_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for oral arguments scraping."""
        target_courts = self._get_target_courts("oral_arguments")
        first_court = sorted(target_courts)[0]
        config = COURT_CONFIG[first_court]

        # Oral arguments page with court-specific ?c= parameter
        oral_args_url = f"https://www.tncourts.gov/courts/{config['court_path']}/oral-arguments?c={config['oral_args_c']}"

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=oral_args_url,
            ),
            continuation=self.parse_oral_args_index,
            accumulated_data={
                "court_id": first_court,
                "remaining_courts": sorted(target_courts - {first_court}),
            },
        )

    @step(xsd="xsds/parse_oral_args_list.xsd")
    def parse_oral_args_index(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            TennJudge | TennOpinionCluster | TennOralArgument | TennDocket
        ],
        None,
        None,
    ]:
        """Parse the oral arguments index page and yield requests for year pages."""
        court_id = accumulated_data.get("court_id")
        remaining_courts = accumulated_data.get("remaining_courts", [])
        date_gte, date_lte, _, _ = self._get_oral_args_search_params()

        # Look for year links to video pages
        # Pattern: /oral-arguments/videos/{year}
        year_links = lxml_tree.xpath(
            "//a[contains(@href, '/oral-arguments/') and contains(@href, 'videos')] | "
            "//a[contains(@href, '/videos/')]"
        )

        seen_years: set[str] = set()

        for link in year_links:
            href = link.get("href", "")
            if not href:
                continue

            # Extract year from URL
            match = self.YEAR_PATTERN.search(href)
            if not match:
                continue

            year_str = match.group(1)
            year = int(year_str)

            if year_str in seen_years:
                continue
            seen_years.add(year_str)

            # Filter by date range (approximate by year)
            if date_gte and year < date_gte.year:
                continue
            if date_lte and year > date_lte.year:
                continue

            video_url = urljoin(response.url, href)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=video_url,
                ),
                continuation=self.parse_oral_args_videos,
                accumulated_data={
                    "court_id": court_id,
                    "argument_year": year,
                },
            )

        # Move to next court after processing year links
        if remaining_courts:
            next_court = remaining_courts[0]
            config = COURT_CONFIG[next_court]
            oral_args_url = f"https://www.tncourts.gov/courts/{config['court_path']}/oral-arguments?c={config['oral_args_c']}"
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=oral_args_url,
                ),
                continuation=self.parse_oral_args_index,
                accumulated_data={
                    "court_id": next_court,
                    "remaining_courts": remaining_courts[1:],
                },
            )

    @step(xsd="xsds/parse_oral_args_videos.xsd")
    def parse_oral_args_videos(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            TennJudge | TennOpinionCluster | TennOralArgument | TennDocket
        ],
        None,
        None,
    ]:
        """Parse a year's oral arguments videos page and yield TennOralArgument."""
        court_id: str = accumulated_data.get("court_id", "")
        argument_year = accumulated_data.get("argument_year")
        date_gte, date_lte, target_case_number, _ = (
            self._get_oral_args_search_params()
        )

        # Find YouTube links
        youtube_links = lxml_tree.xpath(
            "//a[contains(@href, 'youtube.com') or contains(@href, 'youtu.be')]"
        )

        for link in youtube_links:
            youtube_url = link.get("href", "")
            if not youtube_url:
                continue

            # Extract video ID
            video_id = None
            video_match = self.YOUTUBE_PATTERN.search(youtube_url)
            if video_match:
                video_id = video_match.group(1)

            # Extract playlist ID
            playlist_id = None
            playlist_match = self.YOUTUBE_PLAYLIST_PATTERN.search(youtube_url)
            if playlist_match:
                playlist_id = playlist_match.group(1)

            # Extract case info from surrounding text
            # The link text or parent element often contains case details
            parent = link.getparent()
            context_text = ""
            if parent is not None:
                context_text = parent.text_content().strip()
            else:
                context_text = link.text_content().strip()

            # Try to extract case number
            case_number = None
            case_match = self.CASE_NUMBER_PATTERN.search(context_text)
            if case_match:
                case_number = case_match.group(1)

            # Filter by target case number
            if target_case_number and case_number != target_case_number:
                continue

            # Extract case name (text after case number, before YouTube link)
            case_name = context_text
            if case_number:
                # Remove case number from case name
                case_name = context_text.replace(case_number, "").strip()
                # Clean up common separators
                case_name = re.sub(r"^[\s\-:]+", "", case_name)

            if not case_name:
                case_name = link.text_content().strip() or "Unknown"

            # Try to extract date from context
            date_argued = None
            date_match = self.DATE_PATTERN.search(context_text)
            if date_match:
                date_argued = self._parse_date(date_match.group(1))

            # If no date found but we have argument_year, use Jan 1 of that year
            if not date_argued and argument_year:
                date_argued = date(argument_year, 1, 1)

            # Apply date filters
            if date_argued:
                if date_gte and date_argued < date_gte:
                    continue
                if date_lte and date_argued > date_lte:
                    continue

            oral_arg = TennOralArgument(
                case_number=case_number or "Unknown",
                court_id=court_id,
                date_argued=date_argued or date(argument_year or 2020, 1, 1),
                case_name=case_name,
                youtube_url=youtube_url,
                youtube_video_id=video_id,
                youtube_playlist_id=playlist_id,
                source_url=response.url,
                argument_year=argument_year,
            )

            yield ParsedData(oral_arg)

    # =========================================================================
    # Dockets Scraping Steps (Speculative)
    # =========================================================================

    @speculate(highest_observed=1000, largest_observed_gap=20)
    def fetch_docket(self, pch_id: int) -> NavigatingRequest:
        """Generate a speculative request for a docket by PCH ID.

        The driver calls this function for each ID in the speculative range.
        Configure the range via params.speculative.fetch_docket:
            - definite_range = (start, end) to specify exact range
            - plus = N to probe N IDs beyond highest successful

        The request is processed by parse_docket_page.
        """
        # Get court_ids filter from params (if set)
        _, _, court_ids = self._get_docket_search_params()

        return NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{DOCKET_CONFIG['case_detail_url']}?id={pch_id}",
            ),
            continuation=self.parse_docket_page,
            accumulated_data={
                "pch_id": pch_id,
                "court_ids": list(court_ids) if court_ids else None,
            },
        )

    @step(xsd="xsds/parse_docket_page.xsd")
    def parse_docket_page(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            TennJudge | TennOpinionCluster | TennOralArgument | TennDocket
        ],
        bool | None,
        None,
    ]:
        """Parse a PCH docket page and yield TennDocket.

        Extracts:
        - Case overview (case number, style, trial court info)
        - Case milestones (dates for various stages)
        - Parties (names, roles, counsel)
        - Document history (docket entries)
        """
        pch_id = accumulated_data.get("pch_id")
        court_ids_filter = accumulated_data.get("court_ids")

        # Check if we got an error page or no case found
        # Look for indicators that this ID doesn't exist
        error_indicators = lxml_tree.xpath(
            "//div[contains(@class, 'error')] | "
            "//span[contains(text(), 'No case found')] | "
            "//div[contains(text(), 'not found')]"
        )
        if error_indicators:
            return  # No docket at this ID

        # Extract case number (Inter. Case No.)
        case_number = None
        case_num_elems = lxml_tree.xpath(
            "//*[contains(text(), 'Inter. Case No.')]/following-sibling::* | "
            "//td[contains(text(), 'Inter. Case No.')]/following-sibling::td | "
            "//span[contains(@id, 'CaseNumber')] | "
            "//div[contains(@class, 'case-number')]"
        )
        if case_num_elems:
            case_number = case_num_elems[0].text_content().strip()

        if not case_number:
            return  # Can't find case number

        # Determine court_id from case number pattern
        # Patterns like M2023-... (Middle TN), E2023-... (East TN), W2023-... (West TN)
        # SC for Supreme Court, COA for Court of Appeals, CCA for Criminal Appeals
        court_id = None
        if "-SC-" in case_number or case_number.endswith("-SC"):
            court_id = "tenn"
        elif "-COA-" in case_number or "-CA-" in case_number:
            court_id = "tennctapp"
        elif "-CCA-" in case_number:
            court_id = "tenncrimapp"
        else:
            # Default to Court of Appeals if can't determine
            court_id = "tennctapp"

        # Filter by court_id if specified
        if court_ids_filter and court_id not in court_ids_filter:
            return  # Skip this docket - not in requested courts

        # Extract case name/style
        case_name = "Unknown"
        style_elems = lxml_tree.xpath(
            "//*[contains(text(), 'Style')]/following-sibling::* | "
            "//td[contains(text(), 'Style')]/following-sibling::td | "
            "//span[contains(@id, 'Style')] | "
            "//div[contains(@class, 'case-style')]"
        )
        if style_elems:
            case_name = style_elems[0].text_content().strip()

        # Helper to extract text
        def extract_text(xpath_expr: str) -> str | None:
            elems = lxml_tree.xpath(xpath_expr)
            if elems:
                text = elems[0].text_content().strip()
                return text if text else None
            return None

        # Helper to extract date
        def extract_date(xpath_expr: str) -> date | None:
            text = extract_text(xpath_expr)
            if text:
                match = self.DATE_PATTERN.search(text)
                if match:
                    return self._parse_date(match.group(1))
            return None

        # Extract trial court info
        trial_court = extract_text(
            "//*[contains(text(), 'Trial Court')]/following-sibling::* | "
            "//td[contains(text(), 'Trial Court')]/following-sibling::td[1]"
        )
        trial_court_judge = extract_text(
            "//*[contains(text(), 'Trial Court Judge')]/following-sibling::* | "
            "//td[contains(text(), 'Trial Court Judge')]/following-sibling::td"
        )
        trial_court_number = extract_text(
            "//*[contains(text(), 'Trial Court No')]/following-sibling::* | "
            "//td[contains(text(), 'Trial Court No')]/following-sibling::td"
        )

        # Extract case milestones
        application_filed_date = extract_date(
            "//*[contains(text(), 'Application Filed')]/following-sibling::* | "
            "//td[contains(text(), 'Application Filed')]/following-sibling::td"
        )
        disposition_date = extract_date(
            "//*[contains(text(), 'Disposition')]/following-sibling::*[contains(text(), '/')] | "
            "//td[contains(text(), 'Disposition')]/following-sibling::td"
        )
        disposition = extract_text(
            "//*[contains(text(), 'Disposition')]/following-sibling::* | "
            "//td[contains(text(), 'Disposition')]/following-sibling::td"
        )
        record_filed_date = extract_date(
            "//*[contains(text(), 'Record Filed')]/following-sibling::* | "
            "//td[contains(text(), 'Record Filed')]/following-sibling::td"
        )
        briefing_complete_date = extract_date(
            "//*[contains(text(), 'Briefing')]/following-sibling::* | "
            "//td[contains(text(), 'Briefing')]/following-sibling::td"
        )
        oral_argument_date = extract_date(
            "//*[contains(text(), 'Oral Argument')]/following-sibling::* | "
            "//td[contains(text(), 'Oral Argument')]/following-sibling::td"
        )
        decision_date = extract_date(
            "//*[contains(text(), 'Decision')]/following-sibling::* | "
            "//td[contains(text(), 'Decision')]/following-sibling::td"
        )

        # Set date_filed to application_filed_date
        date_filed = application_filed_date

        # Parse parties
        parties = self._parse_docket_parties(lxml_tree)

        # Parse document history / docket entries
        entries = self._parse_docket_entries(lxml_tree)

        # Build and yield the TennDocket
        docket = TennDocket(
            pch_id=pch_id,
            case_number=case_number,
            court_id=court_id,
            date_filed=date_filed,
            case_name=case_name,
            trial_court=trial_court,
            trial_court_judge=trial_court_judge,
            trial_court_number=trial_court_number,
            application_filed_date=application_filed_date,
            disposition_date=disposition_date,
            disposition=disposition,
            record_filed_date=record_filed_date,
            briefing_complete_date=briefing_complete_date,
            oral_argument_date=oral_argument_date,
            decision_date=decision_date,
            parties=parties,
            entries=entries,
            source_url=response.url,
        )

        yield ParsedData(docket)

    def _parse_docket_parties(
        self, lxml_tree: CheckedHtmlElement
    ) -> list[dict]:
        """Parse party information from the docket page."""
        parties: list[dict] = []

        # Look for parties section
        # Format varies but typically has name, role, and counsel
        party_rows = lxml_tree.xpath(
            "//table[.//th[contains(text(), 'Name') or contains(text(), 'Party')]]//tr | "
            "//div[contains(@class, 'parties')]//div[contains(@class, 'party')]"
        )

        for row in party_rows:
            # Skip header rows
            if row.xpath(".//th"):
                continue

            cells = row.xpath(".//td")
            if len(cells) >= 2:
                party = {
                    "name": cells[0].text_content().strip()
                    if cells[0].text_content()
                    else None,
                    "role": cells[1].text_content().strip()
                    if len(cells) > 1 and cells[1].text_content()
                    else None,
                }
                # Counsel might be in third cell
                if len(cells) > 2:
                    counsel = cells[2].text_content().strip()
                    if counsel:
                        party["counsel"] = counsel

                if party.get("name"):
                    parties.append(party)

        return parties

    def _parse_docket_entries(
        self, lxml_tree: CheckedHtmlElement
    ) -> list[TennDocketEntry]:
        """Parse document history / docket entries from the page."""
        entries: list[TennDocketEntry] = []

        # Look for document history table
        entry_rows = lxml_tree.xpath(
            "//table[.//th[contains(text(), 'Date') or contains(text(), 'Event') or contains(text(), 'Document')]]//tr | "
            "//div[contains(@class, 'document-history')]//div[contains(@class, 'entry')]"
        )

        for row in entry_rows:
            # Skip header rows
            if row.xpath(".//th"):
                continue

            cells = row.xpath(".//td | .//div[contains(@class, 'cell')]")
            if len(cells) < 2:
                continue

            # Parse date from first cell
            date_filed = None
            date_text = (
                cells[0].text_content().strip()
                if cells[0].text_content()
                else ""
            )
            if date_text:
                match = self.DATE_PATTERN.search(date_text)
                if match:
                    date_filed = self._parse_date(match.group(1))

            # Event type from second cell
            event = cells[1].text_content().strip() if len(cells) > 1 else None

            # Filer from third cell
            filer = None
            if len(cells) > 2:
                filer = cells[2].text_content().strip() or None

            # Check for PDF link
            document_url = None
            pdf_links = row.xpath(".//a[contains(@href, '.pdf')]")
            if pdf_links:
                document_url = pdf_links[0].get("href")

            entry = TennDocketEntry(
                date_filed=date_filed,
                event=event,
                filer=filer,
                document_url=document_url,
            )
            entries.append(entry)

        return entries
