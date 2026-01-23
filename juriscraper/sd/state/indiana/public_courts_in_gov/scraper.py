"""Indiana Appellate Courts Scraper.

This module scrapes opinions from the Indiana Supreme Court, Court of Appeals,
and Tax Court using the decisions portal API.

Entry point:
- API Search: https://public.courts.in.gov/decisions/api/Opinion/Search

Flow:
1. get_entry -> API search request with date range and court filters
2. parse_api_results -> parses JSON response, yields ArchiveRequests for PDFs
3. handle_opinion_download -> yields final IndianaOpinionCluster

Design decisions:
- Uses the decisions portal JSON API for reliable structured data
- API accepts date range, court ID, case category, and pagination params
- Each result contains metadata plus a unique opinion ID for PDF download
- PDF URLs: api/Document/Opinion?Id={opinion_id}
- Rate limiting recommended per court terms of use
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

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
    API_COURT_ID_TO_CL,
    COURT_ID_MAP,
    IndianaOpinion,
    IndianaOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


# API endpoints
API_BASE_URL = "https://public.courts.in.gov/decisions"
API_SEARCH_URL = f"{API_BASE_URL}/api/Opinion/Search"
API_DOCUMENT_URL = f"{API_BASE_URL}/api/Document/Opinion"


class IndianaScraper(BaseScraper[IndianaOpinionCluster]):
    """Scraper for Indiana appellate court opinions via decisions portal API.

    Scrapes opinions from the Indiana Supreme Court (ind),
    Court of Appeals (indctapp), and Tax Court (indtc).

    Usage:
        # Scrape all opinions from all courts (defaults to last 30 days)
        scraper = IndianaScraper()

        # Scrape only Supreme Court opinions
        params = IndianaScraper.params()
        params.IndianaOpinionCluster.court_id.values = {"ind"}
        scraper = IndianaScraper(params=params)

        # Scrape Court of Appeals and Tax Court opinions
        params = IndianaScraper.params()
        params.IndianaOpinionCluster.court_id.values = {"indctapp", "indtc"}
        scraper = IndianaScraper(params=params)

        # Filter opinions by date range
        params = IndianaScraper.params()
        params.IndianaOpinionCluster.date_filed.gte = date(2026, 1, 1)
        params.IndianaOpinionCluster.date_filed.lte = date(2026, 1, 31)
        scraper = IndianaScraper(params=params)

        # Search for a specific case
        params = IndianaScraper.params()
        params.IndianaOpinionCluster.docket_id.value = "25A-CR-00675"
        scraper = IndianaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ind", "indctapp", "indtc"}
    court_url: ClassVar[str] = "https://public.courts.in.gov/decisions"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful per Supreme Court rules
    # "Data mining from this website is prohibited by Supreme Court rule"
    msec_per_request_rate_limit: ClassVar[int] = 2000

    # Default date range (30 days) when no date filter specified
    DEFAULT_DATE_RANGE_DAYS: ClassVar[int] = 30

    # Page size for API requests
    PAGE_SIZE: ClassVar[int] = 25

    # Mapping from model name to data type
    MODEL_TO_DATA_TYPE: ClassVar[dict[str, str]] = {
        "IndianaOpinionCluster": "opinions",
    }

    # Regex patterns
    JUDGES_CONCUR_PATTERN = re.compile(
        r"(?:Judge|Justice)s?\s+([^.]+?)\s+(?:and\s+(?:Judge|Justice)\s+)?([^\s.]+)\s+concur",
        re.IGNORECASE,
    )
    SINGLE_CONCUR_PATTERN = re.compile(
        r"(?:Judge|Justice)\s+(\w+)\s+concurs",
        re.IGNORECASE,
    )
    DISSENT_PATTERN = re.compile(
        r"(?:Judge|Justice)\s+(\w+)\s+dissents",
        re.IGNORECASE,
    )

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
            model_proxy = self._params.IndianaOpinionCluster
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

    def _format_date(self, d: date) -> str:
        """Format date for API request (MM/DD/YYYY format)."""
        return d.strftime("%m/%d/%Y")

    def _parse_date(self, date_str: str) -> date | None:
        """Parse date from API response.

        Args:
            date_str: Date string in format "January 22, 2026" or "01/22/2026"

        Returns:
            Parsed date or None
        """
        # Try "Month DD, YYYY" format first
        try:
            dt = datetime.strptime(date_str.strip(), "%B %d, %Y")
            return dt.date()
        except ValueError:
            pass

        # Try "MM/DD/YYYY" format
        try:
            dt = datetime.strptime(date_str.strip(), "%m/%d/%Y")
            return dt.date()
        except ValueError:
            pass

        return None

    def _extract_judges(self, judge_text: str) -> list[str]:
        """Extract individual judge names from concurrence/dissent text.

        Args:
            judge_text: Text like "Judge Vaidik and Judge Pyle concur"

        Returns:
            List of judge names
        """
        judges = []

        # Try multi-judge pattern first
        match = self.JUDGES_CONCUR_PATTERN.search(judge_text)
        if match:
            # First group may contain multiple names
            first_part = match.group(1)
            # Split on "and" and "," to get individual names
            names = re.split(r"\s+and\s+|,\s*", first_part)
            for name in names:
                name = name.strip()
                # Remove "Judge " prefix if present
                name = re.sub(r"^(?:Judge|Justice)\s+", "", name, flags=re.IGNORECASE)
                if name:
                    judges.append(name)
            # Add the last name
            last_name = match.group(2).strip()
            if last_name:
                judges.append(last_name)
            return judges

        # Try single concur pattern
        match = self.SINGLE_CONCUR_PATTERN.search(judge_text)
        if match:
            judges.append(match.group(1))

        return judges

    def _build_api_request(
        self,
        court_id: int | str,
        from_date: date,
        to_date: date,
        case_party: str = "",
        page_number: int = 1,
        show_memorandum: bool = True,
    ) -> dict:
        """Build API request body."""
        return {
            "caseParty": case_party,
            "courtId": str(court_id) if court_id else "",
            "caseCategoryId": "",
            "judgeId": "",
            "fromDate": self._format_date(from_date),
            "toDate": self._format_date(to_date),
            "countyId": "",
            "showMemorandum": show_memorandum,
            "pageNumber": page_number,
            "pageSize": self.PAGE_SIZE,
        }

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial API search requests.

        If specific courts are requested, makes one request per court.
        Otherwise queries all courts at once (courtId="").
        """
        requested = self._get_requested_data_types()

        if "opinions" not in requested:
            return

        date_gte, date_lte, docket_id, court_ids = self._get_search_params()

        # Set default date range if not specified
        if date_lte is None:
            date_lte = date.today()
        if date_gte is None:
            date_gte = date_lte - timedelta(days=self.DEFAULT_DATE_RANGE_DAYS)

        # If searching for a specific docket, include it in caseParty
        case_party = docket_id or ""

        # Determine which courts to query
        if court_ids:
            # Query each requested court separately
            for cl_court_id in court_ids:
                api_court_id = COURT_ID_MAP.get(cl_court_id)
                if api_court_id is None:
                    continue

                request_body = self._build_api_request(
                    court_id=api_court_id,
                    from_date=date_gte,
                    to_date=date_lte,
                    case_party=case_party,
                    page_number=1,
                )

                yield NavigatingRequest(
                    request=HTTPRequestParams(
                        method=HttpMethod.POST,
                        url=API_SEARCH_URL,
                        json=request_body,
                        headers={"Content-Type": "application/json"},
                    ),
                    continuation=self.parse_api_results,
                    accumulated_data={
                        "api_court_id": api_court_id,
                        "from_date": date_gte.isoformat(),
                        "to_date": date_lte.isoformat(),
                        "case_party": case_party,
                        "page_number": 1,
                        "target_docket": docket_id,
                    },
                )
        else:
            # Query all courts at once (empty courtId)
            request_body = self._build_api_request(
                court_id="",
                from_date=date_gte,
                to_date=date_lte,
                case_party=case_party,
                page_number=1,
            )

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=API_SEARCH_URL,
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                ),
                continuation=self.parse_api_results,
                accumulated_data={
                    "api_court_id": "",
                    "from_date": date_gte.isoformat(),
                    "to_date": date_lte.isoformat(),
                    "case_party": case_party,
                    "page_number": 1,
                    "target_docket": docket_id,
                },
            )

    # =========================================================================
    # API Results Parsing
    # =========================================================================

    @step(xsd="xsds/parse_api_results.xsd")
    def parse_api_results(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[IndianaOpinionCluster], None, None]:
        """Parse API JSON response and yield requests for each opinion.

        API response structure:
        {
            "totalRecords": int,
            "pageNumber": int,
            "pageSize": int,
            "opinions": [
                {
                    "caseTitle": "Devon Makel Jones v. State of Indiana",
                    "opinionDate": "January 22, 2026",
                    "courtId": 9530,
                    "courtName": "Court of Appeals",
                    "caseNumber": "25A-CR-00675",
                    "lowerCaseNumber": "48C04-2312-F1-003574",
                    "lowerCourtName": "Madison Circuit Court 4",
                    "categoryName": "Criminal",
                    "judgeName": "Mathias",
                    "disposition": "Affirmed",
                    "concurringJudges": "Judge Vaidik and Judge Pyle concur",
                    "dissentingJudges": "",
                    "isMemorandum": true,
                    "opinionId": "14qhbbHnhfrM_A7WeRi1bLIgbGGYrPCWY5YRPMpRBAcs-HMgaJe9r8SDHW4QBtWY0",
                    "countyName": "Madison"
                },
                ...
            ]
        }
        """
        target_docket = accumulated_data.get("target_docket")

        # Extract opinions from response
        opinions = json_content.get("opinions", [])
        total_records = json_content.get("totalRecords", 0)
        page_number = json_content.get("pageNumber", 1)
        page_size = json_content.get("pageSize", self.PAGE_SIZE)

        for opinion_data in opinions:
            case_number = opinion_data.get("caseNumber", "")

            # Filter by specific docket if specified
            if target_docket and case_number != target_docket:
                continue

            # Extract court ID and map to CourtListener ID
            api_court_id = opinion_data.get("courtId")
            court_id = API_COURT_ID_TO_CL.get(api_court_id, "indctapp")

            # Extract and parse date
            date_str = opinion_data.get("opinionDate", "")
            opinion_date = self._parse_date(date_str)
            if opinion_date is None:
                continue

            # Extract case metadata
            case_name = opinion_data.get("caseTitle", "Unknown")
            opinion_id = opinion_data.get("opinionId", "")

            if not opinion_id:
                continue

            # Build PDF URL
            pdf_url = f"{API_DOCUMENT_URL}?Id={opinion_id}"

            # Extract judges
            authoring_judge = opinion_data.get("judgeName", "")
            concur_text = opinion_data.get("concurringJudges", "")
            dissent_text = opinion_data.get("dissentingJudges", "")

            concurring_judges = self._extract_judges(concur_text) if concur_text else []
            dissenting_judges = self._extract_judges(dissent_text) if dissent_text else []

            # Build accumulated data for download handler
            cluster_data = {
                "docket_id": case_number,
                "court_id": court_id,
                "date_filed": opinion_date.isoformat(),
                "case_name": case_name,
                "source_url": response.url,
                "trial_court_case_number": opinion_data.get("lowerCaseNumber"),
                "trial_court_name": opinion_data.get("lowerCourtName"),
                "case_category": opinion_data.get("categoryName"),
                "disposition": opinion_data.get("disposition"),
                "authoring_judge": authoring_judge,
                "concurring_judges": concurring_judges,
                "dissenting_judges": dissenting_judges,
                "is_memorandum": opinion_data.get("isMemorandum", False),
                "county": opinion_data.get("countyName"),
                "pdf_url": pdf_url,
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

        # Check if there are more pages
        if opinions and page_number * page_size < total_records:
            next_page = page_number + 1
            from_date = date.fromisoformat(accumulated_data["from_date"])
            to_date = date.fromisoformat(accumulated_data["to_date"])

            request_body = self._build_api_request(
                court_id=accumulated_data["api_court_id"],
                from_date=from_date,
                to_date=to_date,
                case_party=accumulated_data.get("case_party", ""),
                page_number=next_page,
            )

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=API_SEARCH_URL,
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                ),
                continuation=self.parse_api_results,
                accumulated_data={
                    **accumulated_data,
                    "page_number": next_page,
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
    ) -> Generator[ScraperYield[IndianaOpinionCluster], None, None]:
        """Handle a downloaded opinion PDF and yield final cluster."""
        date_filed = datetime.fromisoformat(
            accumulated_data["date_filed"]
        ).date()

        # Create opinion object
        opinion = IndianaOpinion(
            download_url=accumulated_data["pdf_url"],
            type="010combined",
            local_path=response.file_url,
        )

        # Build the final cluster
        cluster = IndianaOpinionCluster(
            docket_id=accumulated_data["docket_id"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            opinions=[opinion],
            source_url=accumulated_data["source_url"],
            trial_court_case_number=accumulated_data.get("trial_court_case_number"),
            trial_court_name=accumulated_data.get("trial_court_name"),
            case_category=accumulated_data.get("case_category"),
            disposition=accumulated_data.get("disposition"),
            authoring_judge=accumulated_data.get("authoring_judge"),
            concurring_judges=accumulated_data.get("concurring_judges", []),
            dissenting_judges=accumulated_data.get("dissenting_judges", []),
            is_memorandum=accumulated_data.get("is_memorandum", False),
            county=accumulated_data.get("county"),
            precedential_status="Unpublished" if accumulated_data.get("is_memorandum") else "Published",
        )

        yield ParsedData(cluster)
