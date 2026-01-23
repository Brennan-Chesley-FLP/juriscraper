"""Kentucky Appellate Courts Scraper.

This module scrapes opinions from the Kentucky Supreme Court and
Court of Appeals using the C-Track Public Access system.

Entry point:
- Opinion Search: https://appellatepublic.kycourts.net/search/opinion

IMPORTANT: This scraper REQUIRES the PlaywrightDriver due to the
Vue.js SPA architecture of the C-Track system. The site loads data
via JavaScript XHR requests, so static HTTP requests will not work.

Flow:
1. get_entry -> Opinion search URL with date filters
2. parse_opinion_search -> parses search results table
3. For each opinion with documents:
   - Parse case number, type, subtype, description, date
   - Yield ArchiveRequest for document PDFs
4. handle_opinion_download -> yields final KentuckyOpinionCluster

Design decisions:
- Uses PlaywrightDriver for JavaScript rendering (Vue.js SPA)
- Scrapes from opinion search results which include key metadata
- Each opinion row may have a "Documents List" button for PDFs
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Pagination via next page button (25 results per page)
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlencode

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
    CASE_PREFIX_TO_COURT,
    SITE_COURT_NAME_TO_ID,
    KentuckyOpinion,
    KentuckyOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# Base URLs
BASE_URL = "https://appellatepublic.kycourts.net"
OPINION_SEARCH_URL = f"{BASE_URL}/search/opinion"


class KentuckyScraper(BaseScraper[KentuckyOpinionCluster]):
    """Scraper for Kentucky appellate court opinions via C-Track Public Access.

    IMPORTANT: This scraper requires PlaywrightDriver for JavaScript rendering.
    The C-Track system is a Vue.js SPA that loads data via XHR requests.

    Scrapes opinions from the Kentucky Supreme Court (ky) and
    Court of Appeals (kyctapp).

    Usage:
        # Scrape all opinions from both courts
        scraper = KentuckyScraper()

        # Scrape only Supreme Court opinions
        params = KentuckyScraper.params()
        params.KentuckyOpinionCluster.court_id.values = {"ky"}
        scraper = KentuckyScraper(params=params)

        # Scrape only Court of Appeals opinions
        params = KentuckyScraper.params()
        params.KentuckyOpinionCluster.court_id.values = {"kyctapp"}
        scraper = KentuckyScraper(params=params)

        # Filter opinions by date range
        params = KentuckyScraper.params()
        params.KentuckyOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.KentuckyOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = KentuckyScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ky", "kyctapp"}
    court_url: ClassVar[str] = "https://appellatepublic.kycourts.net/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False
    requires_playwright: ClassVar[bool] = True

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 2000

    # === Regex patterns ===
    # Case number pattern: YYYY-SC-NNNN or YYYY-CA-NNNN
    CASE_NUMBER_PATTERN = re.compile(r"(\d{4})-(SC|CA)-(\d{4})")

    # Date pattern: MM/DD/YYYY
    DATE_PATTERN = re.compile(r"(\d{2})/(\d{2})/(\d{4})")

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "KentuckyOpinionCluster": "opinions",
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
            model_proxy = self._params.KentuckyOpinionCluster
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

    def _get_court_id_from_case_number(self, case_number: str) -> str | None:
        """Determine court ID from case number prefix.

        Args:
            case_number: Case number like '2024-SC-0123' or '2024-CA-0456'

        Returns:
            Court ID ('ky' or 'kyctapp') or None if unrecognized
        """
        match = self.CASE_NUMBER_PATTERN.match(case_number)
        if match:
            prefix = match.group(2)
            return CASE_PREFIX_TO_COURT.get(prefix)
        return None

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from MM/DD/YYYY format.

        Args:
            date_str: Date like '01/22/2026'

        Returns:
            Parsed date or None
        """
        match = self.DATE_PATTERN.match(date_str.strip())
        if match:
            month, day, year = match.groups()
            try:
                return date(int(year), int(month), int(day))
            except ValueError:
                return None
        return None

    def _build_search_url(
        self,
        page_num: int = 1,
        date_gte: date | None = None,
        date_lte: date | None = None,
        case_number: str | None = None,
    ) -> str:
        """Build opinion search URL with filters.

        The C-Track system uses query parameters for search filters.
        """
        params: dict[str, str] = {
            "q": "true",
            "advanced": "true",
            "p.page": str(page_num),
            "p.sort": "parentDate",
            "p.sortdir": "desc",
        }

        field_index = 0

        # Add date filters if specified
        if date_gte:
            params[f"searchFields[{field_index}].searchType"] = "GreaterThan"
            params[f"searchFields[{field_index}].operation"] = "="
            params[f"searchFields[{field_index}].values[0]"] = (
                date_gte.strftime("%m/%d/%Y")
            )
            params[f"searchFields[{field_index}].indexFieldName"] = "filedDate"
            field_index += 1

        if date_lte:
            params[f"searchFields[{field_index}].searchType"] = "LessThan"
            params[f"searchFields[{field_index}].operation"] = "="
            params[f"searchFields[{field_index}].values[0]"] = (
                date_lte.strftime("%m/%d/%Y")
            )
            params[f"searchFields[{field_index}].indexFieldName"] = "filedDate"
            field_index += 1

        if case_number:
            params[f"searchFields[{field_index}].searchType"] = "Contains"
            params[f"searchFields[{field_index}].operation"] = "="
            params[f"searchFields[{field_index}].values[0]"] = case_number
            params[f"searchFields[{field_index}].indexFieldName"] = (
                "caseHeader.caseNumber"
            )
            field_index += 1

        return f"{OPINION_SEARCH_URL}?{urlencode(params)}"

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial request to opinion search."""
        requested = self._get_requested_data_types()

        if "opinions" in requested:
            date_gte, date_lte, docket_id, _ = self._get_search_params()

            # Build search URL with any filters
            search_url = self._build_search_url(
                page_num=1,
                date_gte=date_gte,
                date_lte=date_lte,
                case_number=docket_id,
            )

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=search_url,
                ),
                continuation=self.parse_opinion_search,
                accumulated_data={
                    "page_num": 1,
                    "date_gte": date_gte.isoformat() if date_gte else None,
                    "date_lte": date_lte.isoformat() if date_lte else None,
                    "docket_id": docket_id,
                },
            )

    # =========================================================================
    # Opinion Search Parsing
    # =========================================================================

    @step(xsd="xsds/parse_opinion_search.xsd")
    def parse_opinion_search(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KentuckyOpinionCluster], None, None]:
        """Parse opinion search results page."""
        _, _, _, court_ids = self._get_search_params()

        # Find all result rows in the table
        # The table has structure: table > tbody (rowgroup) > tr (row)
        rows = lxml_tree.checked_xpath(
            "//table//tbody/tr[contains(@class, 'v-data-table__tr')]"
            " | //table//tbody[not(@class='v-data-table__progress')]/tr[td]",
            "opinion result rows",
            min_count=0,
        )

        if not rows:
            # Try alternative selector for Vue-rendered content
            rows = lxml_tree.checked_xpath(
                "//table/tbody/tr[td[a]]",
                "opinion result rows (alt)",
                min_count=0,
            )

        for row in rows:
            # Extract cells
            cells = row.checked_xpath(
                "td",
                "row cells",
                min_count=5,
            )

            # Cell 0: Case Number (with link to case detail)
            case_link = cells[0].checked_xpath(
                ".//a/@href",
                "case link",
                min_count=0,
                max_count=1,
                type=str,
            )
            case_number_text = cells[0].checked_xpath(
                ".//a/text() | .//text()",
                "case number text",
                min_count=1,
                type=str,
            )
            case_number = "".join(t.strip() for t in case_number_text).strip()

            # Skip if case number doesn't match expected pattern
            if not self.CASE_NUMBER_PATTERN.match(case_number):
                continue

            # Determine court from case number
            court_id = self._get_court_id_from_case_number(case_number)
            if court_id is None:
                continue

            # Filter by court if specified
            if court_ids and court_id not in court_ids:
                continue

            # Cell 1: Type (e.g., "DISPOSITION - MEMORANDUM OPINION")
            opinion_type_texts = cells[1].checked_xpath(
                ".//text()",
                "opinion type",
                min_count=0,
                type=str,
            )
            opinion_type = " ".join(
                t.strip() for t in opinion_type_texts
            ).strip()

            # Cell 2: Subtype (e.g., "AFFIRMING")
            subtype_texts = cells[2].checked_xpath(
                ".//text()",
                "opinion subtype",
                min_count=0,
                type=str,
            )
            subtype = (
                " ".join(t.strip() for t in subtype_texts).strip() or None
            )

            # Cell 3: Description
            desc_texts = cells[3].checked_xpath(
                ".//text()",
                "description",
                min_count=0,
                type=str,
            )
            description = " ".join(t.strip() for t in desc_texts).strip()

            # Cell 4: Filed Date
            date_texts = cells[4].checked_xpath(
                ".//text()",
                "filed date",
                min_count=1,
                type=str,
            )
            date_str = "".join(t.strip() for t in date_texts).strip()
            filed_date = self._parse_date(date_str)

            if filed_date is None:
                continue

            # Check date filters
            date_gte_str = accumulated_data.get("date_gte")
            date_lte_str = accumulated_data.get("date_lte")
            if date_gte_str:
                date_gte = date.fromisoformat(date_gte_str)
                if filed_date < date_gte:
                    continue
            if date_lte_str:
                date_lte = date.fromisoformat(date_lte_str)
                if filed_date > date_lte:
                    continue

            # Cell 5 (optional): Documents List button
            # Check if there's a documents list button
            doc_button = (
                cells[5].checked_xpath(
                    ".//button",
                    "documents button",
                    min_count=0,
                    max_count=1,
                )
                if len(cells) > 5
                else []
            )

            # Build case detail URL from link
            case_detail_url = None
            if case_link:
                href = case_link[0]
                if href.startswith("/"):
                    case_detail_url = f"{BASE_URL}{href}"
                else:
                    case_detail_url = href

            # For opinions with documents, we need to fetch the case detail page
            # to get the actual document download URLs
            if doc_button or case_detail_url:
                # Yield request to fetch case detail page
                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=case_detail_url
                        or f"{BASE_URL}/case/{case_number}",
                    ),
                    continuation=self.parse_case_detail,
                    accumulated_data={
                        "docket_id": case_number,
                        "court_id": court_id,
                        "date_filed": filed_date.isoformat(),
                        "opinion_type": opinion_type,
                        "subtype": subtype,
                        "description": description,
                        "source_url": response.url,
                    },
                )
            else:
                # No documents - yield cluster without PDFs
                cluster = KentuckyOpinionCluster(
                    docket_id=case_number,
                    court_id=court_id,
                    date_filed=filed_date,
                    case_name=description or case_number,
                    opinions=[],
                    source_url=response.url,
                    case_detail_url=case_detail_url,
                    precedential_status="Unknown",
                )
                yield ParsedData(cluster)

        # Check for pagination - look for next page button
        next_button = lxml_tree.checked_xpath(
            "//button[contains(@aria-label, 'Next') and not(@disabled)]"
            " | //button[.//text()[contains(., 'chevron_right')] and not(@disabled)]",
            "next page button",
            min_count=0,
            max_count=1,
        )

        if next_button:
            # Get current page number and increment
            current_page = accumulated_data.get("page_num", 1)
            next_page = current_page + 1

            # Build next page URL
            date_gte_str = accumulated_data.get("date_gte")
            date_lte_str = accumulated_data.get("date_lte")
            docket_id = accumulated_data.get("docket_id")

            date_gte_filter: date | None = (
                date.fromisoformat(date_gte_str) if date_gte_str else None
            )
            date_lte_filter: date | None = (
                date.fromisoformat(date_lte_str) if date_lte_str else None
            )

            next_url = self._build_search_url(
                page_num=next_page,
                date_gte=date_gte_filter,
                date_lte=date_lte_filter,
                case_number=docket_id,
            )

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_url,
                ),
                continuation=self.parse_opinion_search,
                accumulated_data={
                    **accumulated_data,
                    "page_num": next_page,
                },
            )

    # =========================================================================
    # Case Detail Parsing
    # =========================================================================

    @step(xsd="xsds/parse_case_detail.xsd")
    def parse_case_detail(
        self,
        lxml_tree: CheckedHtmlElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KentuckyOpinionCluster], None, None]:
        """Parse case detail page to extract case metadata and document URLs."""
        case_number = accumulated_data["docket_id"]

        # Extract case title from the Details section
        title_elems = lxml_tree.checked_xpath(
            "//dt[text()='Title']/following-sibling::dd[1]/text()"
            " | //dd[preceding-sibling::dt[1][text()='Title']]/text()",
            "case title",
            min_count=0,
            type=str,
        )
        case_name = (
            " ".join(t.strip() for t in title_elems).strip()
            if title_elems
            else case_number
        )

        # Extract classification
        class_elems = lxml_tree.checked_xpath(
            "//dt[text()='Classification']/following-sibling::dd[1]/text()"
            " | //dd[preceding-sibling::dt[1][text()='Classification']]/text()",
            "classification",
            min_count=0,
            type=str,
        )
        classification = (
            " ".join(t.strip() for t in class_elems).strip() or None
        )

        # Extract case status
        status_elems = lxml_tree.checked_xpath(
            "//dt[text()='Case Status']/following-sibling::dd[1]/text()"
            " | //dd[preceding-sibling::dt[1][text()='Case Status']]/text()",
            "case status",
            min_count=0,
            type=str,
        )
        case_status = " ".join(t.strip() for t in status_elems).strip() or None

        # Extract court name
        court_elems = lxml_tree.checked_xpath(
            "//dt[text()='Court']/following-sibling::dd[1]/text()"
            " | //dd[preceding-sibling::dt[1][text()='Court']]/text()",
            "court",
            min_count=0,
            type=str,
        )
        court_name = " ".join(t.strip() for t in court_elems).strip()

        # Get court ID from court name if available
        court_id = accumulated_data["court_id"]
        if court_name and court_name in SITE_COURT_NAME_TO_ID:
            court_id = SITE_COURT_NAME_TO_ID[court_name]

        # Find docket entries that have opinion documents
        # Look for rows with "MEMORANDUM OPINION" or similar in description
        # and that have a Documents List button
        opinion_entries = lxml_tree.checked_xpath(
            "//table//tbody/tr[td[contains(text(), 'OPINION') or "
            "contains(text(), 'MEMORANDUM') or contains(text(), 'ORDER')]]",
            "opinion docket entries",
            min_count=0,
        )

        document_urls: list[dict[str, str]] = []
        judges_participating = None

        for entry in opinion_entries:
            # Check if this entry has documents
            doc_links = entry.checked_xpath(
                ".//a[contains(@href, '/documents/')]/@href",
                "document links",
                min_count=0,
                type=str,
            )

            # Extract comments which may contain judge participation info
            comments = entry.checked_xpath(
                "td[4]/text() | td[4]//text()",
                "comments",
                min_count=0,
                type=str,
            )
            if comments:
                comment_text = " ".join(t.strip() for t in comments).strip()
                # Check for judge participation pattern
                if any(
                    indicator in comment_text.upper()
                    for indicator in ["CONCUR", "DISSENT", "SITTING", "C.J."]
                ):
                    judges_participating = comment_text

            for href in doc_links:
                if href.startswith("/"):
                    doc_url = f"{BASE_URL}{href}"
                else:
                    doc_url = href
                subtype = accumulated_data.get("subtype")
                doc_entry: dict[str, str] = {
                    "url": doc_url,
                    "type": accumulated_data.get("opinion_type", "Opinion"),
                }
                if subtype:
                    doc_entry["subtype"] = subtype
                document_urls.append(doc_entry)

        # Also look for document links anywhere on the page
        all_doc_links = lxml_tree.checked_xpath(
            "//a[contains(@href, '/documents/') and contains(@href, '/download')]/@href",
            "all document download links",
            min_count=0,
            type=str,
        )

        existing_urls = {d["url"] for d in document_urls}
        for href in all_doc_links:
            if href.startswith("/"):
                doc_url = f"{BASE_URL}{href}"
            else:
                doc_url = href
            if doc_url not in existing_urls:
                subtype = accumulated_data.get("subtype")
                doc_entry = {
                    "url": doc_url,
                    "type": accumulated_data.get("opinion_type", "Opinion"),
                }
                if subtype:
                    doc_entry["subtype"] = subtype
                document_urls.append(doc_entry)
                existing_urls.add(doc_url)

        filed_date = date.fromisoformat(accumulated_data["date_filed"])

        if document_urls:
            # Start downloading documents
            cluster_data = {
                "docket_id": case_number,
                "court_id": court_id,
                "date_filed": accumulated_data["date_filed"],
                "case_name": case_name,
                "source_url": accumulated_data["source_url"],
                "case_detail_url": response.url,
                "classification": classification,
                "case_status": case_status,
                "judges_participating": judges_participating,
                "document_urls": document_urls,
                "pending_downloads": len(document_urls),
                "completed_downloads": 0,
                "downloaded_paths": {},
            }

            # Yield ArchiveRequest for first document
            first_doc = document_urls[0]
            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=first_doc["url"],
                ),
                continuation=self.handle_opinion_download,
                expected_type="pdf",
                accumulated_data={
                    **cluster_data,
                    "current_download_index": 0,
                },
            )
        else:
            # No documents found - yield cluster without PDFs
            cluster = KentuckyOpinionCluster(
                docket_id=case_number,
                court_id=court_id,
                date_filed=filed_date,
                case_name=case_name,
                opinions=[],
                source_url=accumulated_data["source_url"],
                case_detail_url=response.url,
                classification=classification,
                case_status=case_status,
                judges_participating=judges_participating,
                precedential_status="Unknown",
            )
            yield ParsedData(cluster)

    # =========================================================================
    # Download Handler
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[KentuckyOpinionCluster], None, None]:
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
            # Download next file
            next_index = current_index + 1
            document_urls = accumulated_data["document_urls"]
            next_doc = document_urls[next_index]

            yield ArchiveRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=next_doc["url"],
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
    ) -> Generator[ScraperYield[KentuckyOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        document_urls = accumulated_data["document_urls"]

        for i, doc_data in enumerate(document_urls):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                KentuckyOpinion(
                    download_url=doc_data["url"],
                    opinion_type=doc_data["type"],
                    subtype=doc_data.get("subtype"),
                    local_path=local_path,
                )
            )

        filed_date = date.fromisoformat(accumulated_data["date_filed"])

        # Determine precedential status from opinion type
        opinion_type = accumulated_data.get("opinion_type", "")
        judges = accumulated_data.get("judges_participating", "")

        precedential_status = "Unknown"
        if "NOT TO BE PUBLISHED" in judges.upper() if judges else False:
            precedential_status = "Unpublished"
        elif "MEMORANDUM" in opinion_type.upper():
            precedential_status = (
                "Unpublished"  # Memorandum opinions typically unpublished
            )

        cluster = KentuckyOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=filed_date,
            case_name=accumulated_data["case_name"],
            opinions=opinions,
            source_url=accumulated_data["source_url"],
            case_detail_url=accumulated_data.get("case_detail_url"),
            classification=accumulated_data.get("classification"),
            case_status=accumulated_data.get("case_status"),
            judges_participating=accumulated_data.get("judges_participating"),
            precedential_status=precedential_status,
        )

        yield ParsedData(cluster)
