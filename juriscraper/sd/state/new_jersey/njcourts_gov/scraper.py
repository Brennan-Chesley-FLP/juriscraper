"""New Jersey Courts Scraper.

This module scrapes opinions from New Jersey courts:
- Supreme Court of New Jersey (nj)
- Superior Court Appellate Division (njsuperctappdiv)

Entry points:
- Supreme Court: https://www.njcourts.gov/attorneys/opinions/supreme
- Published Appellate: https://www.njcourts.gov/attorneys/opinions/published-appellate
- Unpublished Appellate: https://www.njcourts.gov/attorneys/opinions/unpublished-appellate

Flow:
1. get_entry -> yields requests to opinion list pages based on court filter
2. parse_opinions_list -> parses article elements, yields ArchiveRequests for PDFs
3. handle_opinion_download -> yields final NewJerseyOpinionCluster

Design decisions:
- Each opinion type has its own paginated list page
- Pages are paginated with ?page=N (0-indexed)
- Each opinion entry is an <article> element containing:
  - Case name link (to PDF)
  - Docket number
  - Court type badge (Supreme, Published Appellate, etc.)
  - Date
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from juriscraper.scraper_driver.common.checked_html import CheckedHtmlElement
from juriscraper.scraper_driver.common.decorators import step
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
    CERTIFICATION_PATTERN,
    OPINION_TYPE_TO_COURT,
    OPINION_TYPE_TO_PRECEDENTIAL_STATUS,
    NewJerseyOpinion,
    NewJerseyOpinionCluster,
    parse_nj_date,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URL
BASE_URL = "https://www.njcourts.gov"

# Opinion page URLs by type
OPINION_URLS = {
    "Supreme": f"{BASE_URL}/attorneys/opinions/supreme",
    "Published Appellate": f"{BASE_URL}/attorneys/opinions/published-appellate",
    "Unpublished Appellate": f"{BASE_URL}/attorneys/opinions/unpublished-appellate",
}

# Court IDs to opinion types mapping
COURT_TO_OPINION_TYPES = {
    "nj": ["Supreme"],
    "njsuperctappdiv": ["Published Appellate", "Unpublished Appellate"],
}


class NewJerseyScraper(BaseScraper[NewJerseyOpinionCluster]):
    """Scraper for New Jersey court opinions.

    Scrapes published and unpublished opinions from:
    - New Jersey Supreme Court
    - New Jersey Superior Court Appellate Division

    Usage:
        # Scrape all opinions from all courts
        scraper = NewJerseyScraper()

        # Filter opinions by date range
        params = NewJerseyScraper.params()
        params.NewJerseyOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.NewJerseyOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = NewJerseyScraper(params=params)

        # Scrape only Supreme Court opinions
        params = NewJerseyScraper.params()
        params.NewJerseyOpinionCluster.court_id.values = {"nj"}
        scraper = NewJerseyScraper(params=params)

        # Scrape only Appellate Division opinions
        params = NewJerseyScraper.params()
        params.NewJerseyOpinionCluster.court_id.values = {"njsuperctappdiv"}
        scraper = NewJerseyScraper(params=params)

        # Scrape specific docket number
        params = NewJerseyScraper.params()
        params.NewJerseyOpinionCluster.docket_id.value = "A-45-24"
        scraper = NewJerseyScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"nj", "njsuperctappdiv"}
    court_url: ClassVar[str] = "https://www.njcourts.gov/attorneys/opinions"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "NewJerseyOpinionCluster": "opinions",
    }

    def _get_requested_data_types(self) -> set[str]:
        """Get the set of data types to scrape based on enabled models."""
        if self._params is None:
            return self.data_types

        enabled_models = self._params.get_enabled_models()
        if not enabled_models:
            return set()

        enabled_data_types = set()
        for model_name in enabled_models:
            if model_name in self.MODEL_TO_DATA_TYPE:
                enabled_data_types.add(self.MODEL_TO_DATA_TYPE[model_name])

        return enabled_data_types & self.data_types

    def _get_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, docket_id, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.NewJerseyOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        docket_id = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        docket_field = searchable.get("docket_id")
        if docket_field and docket_field.is_set():
            docket_id = docket_field.value

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, docket_id, court_ids

    def _get_opinion_types_to_scrape(self) -> list[str]:
        """Determine which opinion types to scrape based on court filter.

        Returns:
            List of opinion type keys to scrape
        """
        _, _, _, court_ids = self._get_search_params()

        if court_ids is None:
            # No filter - scrape all opinion types
            return list(OPINION_URLS.keys())

        opinion_types = []
        for court_id in court_ids:
            if court_id in COURT_TO_OPINION_TYPES:
                opinion_types.extend(COURT_TO_OPINION_TYPES[court_id])

        # Remove duplicates while preserving order
        return list(dict.fromkeys(opinion_types))

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests to opinion list pages."""
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        opinion_types = self._get_opinion_types_to_scrape()

        for opinion_type in opinion_types:
            url = OPINION_URLS.get(opinion_type)
            if url:
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                    ),
                    continuation=self.parse_opinions_list,
                    accumulated_data={
                        "opinion_type": opinion_type,
                        "page": 0,
                    },
                )

    # =========================================================================
    # Opinions List Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinions_list.xsd")
    def parse_opinions_list(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NewJerseyOpinionCluster], None, None]:
        """Parse the opinions list page and yield requests for PDFs.

        Each opinion is contained in an <article> element with:
        - A link containing the case name and PDF URL
        - Generic divs containing docket number, court type badge, and date
        """
        date_gte, date_lte, target_docket, _ = self._get_search_params()
        opinion_type = accumulated_data["opinion_type"]
        current_page = accumulated_data["page"]

        # Get all article elements (opinion entries)
        articles = lxml_tree.checked_xpath(
            "//article",
            "opinion articles",
            min_count=0,
        )

        found_opinions = 0
        for article in articles:
            # Extract case name and PDF URL from the first link
            links = article.checked_xpath(
                ".//a[contains(@href, '/system/files/court-opinions/')]",
                "opinion PDF link",
                min_count=0,
                max_count=1,
            )

            if not links:
                continue

            link = links[0]

            # Get case name from link text
            case_name_parts = link.checked_xpath(
                ".//text()",
                "case name text",
                min_count=0,
                type=str,
            )
            case_name = " ".join(
                t.strip() for t in case_name_parts if t.strip()
            )

            if not case_name:
                continue

            # Get PDF URL
            pdf_hrefs = link.checked_xpath(
                "@href",
                "PDF URL",
                min_count=1,
                max_count=1,
                type=str,
            )
            pdf_url = urljoin(response.url, pdf_hrefs[0])

            # Extract docket number from the article
            # It's typically in a generic div before the court type badge
            docket_texts = article.checked_xpath(
                ".//text()",
                "article text",
                min_count=0,
                type=str,
            )

            docket_number = None
            opinion_date = None

            # Parse all text in the article to find docket and date
            all_text = " ".join(t.strip() for t in docket_texts if t.strip())

            # Look for docket number patterns
            # Supreme Court: A-NN-YY (e.g., A-45-24)
            # Appellate: A-NNNN-YY (e.g., A-2236-23)
            # Also handles consolidated like A-2236-23/A-2237-23
            docket_match = re.search(
                r"([ASDM]-\d+(?:/\d+)?-\d{2}(?:/[ASDM]-\d+(?:/\d+)?-\d{2})?)",
                all_text,
                re.IGNORECASE,
            )
            if docket_match:
                docket_number = docket_match.group(1)

            # Look for date pattern (e.g., "Jan. 22, 2026")
            opinion_date = parse_nj_date(all_text)

            if not docket_number or not opinion_date:
                continue

            # Filter by specific docket if specified
            if (
                target_docket
                and docket_number.upper() != target_docket.upper()
            ):
                continue

            # Filter by date range
            if date_gte and opinion_date < date_gte:
                continue
            if date_lte and opinion_date > date_lte:
                continue

            found_opinions += 1

            # Check for certification number
            cert_match = CERTIFICATION_PATTERN.search(case_name)
            certification_number = cert_match.group(1) if cert_match else None

            # Check for redacted/impounded status
            is_redacted = (
                "redacted" in case_name.lower()
                or "redacted" in pdf_url.lower()
            )
            is_record_impounded = "impounded" in case_name.lower()

            # Get court_id from opinion type
            court_id = OPINION_TYPE_TO_COURT.get(opinion_type, "nj")

            # Build accumulated data for download handler
            cluster_data = {
                "docket_id": docket_number,
                "court_id": court_id,
                "date_filed": opinion_date.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "pdf_url": pdf_url,
                "opinion_type": opinion_type,
                "certification_number": certification_number,
                "is_redacted": is_redacted,
                "is_record_impounded": is_record_impounded,
            }

            # Yield ArchiveRequest for the PDF
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=pdf_url,
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data=cluster_data,
            )

        # Handle pagination - check if there's a next page
        # Look for pagination links
        next_page_links = lxml_tree.checked_xpath(
            "//a[contains(@href, '?page=')]/@href",
            "pagination links",
            min_count=0,
            type=str,
        )

        # Find the next page number
        next_page = current_page + 1
        has_next_page = False

        for page_link in next_page_links:
            # Extract page number from link (page_link is a string from xpath)
            page_match = re.search(r"\?page=(\d+)", str(page_link))
            if page_match:
                page_num = int(page_match.group(1))
                if page_num == next_page:
                    has_next_page = True
                    break

        # If we found opinions on this page and there's a next page, continue
        if found_opinions > 0 and has_next_page:
            next_url = f"{OPINION_URLS[opinion_type]}?page={next_page}"
            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_url,
                ),
                continuation=self.parse_opinions_list,
                accumulated_data={
                    "opinion_type": opinion_type,
                    "page": next_page,
                },
            )

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NewJerseyOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        opinion = NewJerseyOpinion(
            download_url=accumulated_data["pdf_url"],
            local_path=response.file_url,
        )

        # Get precedential status from opinion type
        precedential_status = OPINION_TYPE_TO_PRECEDENTIAL_STATUS.get(
            accumulated_data["opinion_type"],
            "Unknown",
        )

        cluster = NewJerseyOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            opinion_type=accumulated_data["opinion_type"],
            certification_number=accumulated_data.get("certification_number"),
            is_redacted=accumulated_data.get("is_redacted", False),
            is_record_impounded=accumulated_data.get(
                "is_record_impounded", False
            ),
            precedential_status=precedential_status,
        )

        yield ParsedData(cluster)
