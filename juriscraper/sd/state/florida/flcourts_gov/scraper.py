"""Florida appellate courts scraper.

Scrapes opinions from Florida Supreme Court and District Courts of Appeal
using the unified flcourts.gov website and its JSON API.

Supported courts:
- fla: Florida Supreme Court
- fladistctapp1-6: District Courts of Appeal (1st through 6th)

Data types scraped:
- Opinions (via flcourts-media.flcourts.gov API)
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar

from juriscraper.scraper_driver.common.decorators import step
from juriscraper.scraper_driver.data_types import (
    ArchiveRequest,
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    NavigatingRequest,
    ParsedData,
)

from .models import (
    API_CONFIG,
    COURT_CONFIG,
    COURT_IDS,
    FloridaOpinion,
    FloridaOpinionCluster,
)

if TYPE_CHECKING:
    from juriscraper.scraper_driver.common.scraper import ScraperParams
    from juriscraper.scraper_driver.data_types import (
        ArchiveResponse,
        ScraperYield,
    )


class FloridaScraper(BaseScraper[FloridaOpinionCluster]):
    """Scraper for Florida appellate court opinions.

    Uses the flcourts-media.flcourts.gov JSON API to fetch opinions
    for the Florida Supreme Court and all six District Courts of Appeal.
    """

    # === Scraper Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = "https://www.flcourts.gov/"
    data_types: ClassVar[set[str]] = {"opinions"}
    version: ClassVar[str] = "2026-01-22"
    requires_auth: ClassVar[bool] = False
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # API pagination settings
    PAGE_SIZE: ClassVar[int] = 50

    def __init__(self, params: ScraperParams | None = None) -> None:
        """Initialize the scraper with optional parameters."""
        self._params = params

    def _get_requested_court_ids(self) -> set[str]:
        """Get the set of court IDs to scrape based on params.

        Returns all court IDs if no filter is set.
        """
        if not self._params:
            return set(COURT_IDS.keys())

        model_params = getattr(self._params, "FloridaOpinionCluster", None)
        if model_params is None:
            return set()

        searchable = model_params.get_searchable_fields()
        court_filter = searchable.get("court_id")

        if court_filter and court_filter.is_set():
            return court_filter.values
        return set(COURT_IDS.keys())

    def _get_date_range(self) -> tuple[date | None, date | None]:
        """Get date range filter from params."""
        if not self._params:
            return None, None

        model_params = getattr(self._params, "FloridaOpinionCluster", None)
        if model_params is None:
            return None, None

        searchable = model_params.get_searchable_fields()
        date_filter = searchable.get("date_filed")

        if date_filter and date_filter.is_set():
            return date_filter.gte, date_filter.lte
        return None, None

    def _get_case_number_filter(self) -> str | None:
        """Get specific case number to look up."""
        if not self._params:
            return None

        model_params = getattr(self._params, "FloridaOpinionCluster", None)
        if model_params is None:
            return None

        searchable = model_params.get_searchable_fields()
        case_filter = searchable.get("case_number")

        if case_filter and case_filter.is_set():
            return case_filter.value
        return None

    def _build_api_url(
        self,
        court_id: str,
        offset: int = 0,
        query: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> str:
        """Build the API URL for fetching opinions.

        Args:
            court_id: The CourtListener court ID (e.g., 'fla', 'fladistctapp1')
            offset: Pagination offset
            query: Search query text
            start_date: Filter for opinions on or after this date
            end_date: Filter for opinions on or before this date

        Returns:
            Full API URL with query parameters
        """
        config = COURT_CONFIG[court_id]
        siteaccess = config["siteaccess"]

        # Build URL parameters
        params = [
            f"siteaccess={siteaccess}",
            "searchtype=opinions",
            f"offset={offset}",
            f"limit={self.PAGE_SIZE}",
            "sort=opinion/disposition_date desc, opinion/case_number asc",
            "types[0]=Written",
            "types[1]=PCA",
            "types[2]=Citation",
        ]

        if query:
            params.append(f"query={query}")
        else:
            params.append("query=")

        if start_date:
            params.append(f"startDate={start_date.isoformat()}")

        if end_date:
            params.append(f"endDate={end_date.isoformat()}")

        return f"{API_CONFIG['search_endpoint']}?{'&'.join(params)}"

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Entry point - fetch opinions for each requested court."""
        requested_courts = self._get_requested_court_ids()
        date_gte, date_lte = self._get_date_range()
        case_number = self._get_case_number_filter()

        # If no courts requested, don't do anything
        if not requested_courts:
            return

        # For each court, start fetching opinions
        for court_id in requested_courts:
            if court_id not in COURT_CONFIG:
                continue

            api_url = self._build_api_url(
                court_id=court_id,
                offset=0,
                query=case_number or "",
                start_date=date_gte,
                end_date=date_lte,
            )

            yield NavigatingRequest(
                request=HTTPRequestParams(method=HttpMethod.GET, url=api_url),
                continuation=self.parse_opinions_api,
                accumulated_data={
                    "court_id": court_id,
                    "offset": 0,
                    "date_gte": date_gte.isoformat() if date_gte else None,
                    "date_lte": date_lte.isoformat() if date_lte else None,
                    "query": case_number or "",
                },
            )

    @step
    def parse_opinions_api(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Parse the opinions API response.

        The API returns a JSON object with:
        - searchResults: Array of opinion entries
        - totalCount: Total number of results
        - searchParams: The search parameters used
        """
        court_id = accumulated_data["court_id"]
        current_offset = accumulated_data["offset"]

        search_results = json_content.get("searchResults", [])
        total_count = json_content.get("totalCount", 0)

        # Process each opinion in the results
        for result in search_results:
            content = result.get("content", {})
            fields = content.get("fields", {})

            # Extract case number
            case_number = fields.get("case_number", "")
            if not case_number:
                continue

            # Extract case name
            case_name = fields.get("case_style", "Unknown")

            # Extract disposition date
            disposition_date_obj = fields.get("disposition_date", {})
            date_info = disposition_date_obj.get("date", {})
            date_str = date_info.get("date", "")

            if date_str:
                # Parse "2026-01-22 00:00:00.000000" format
                dt = datetime.strptime(date_str.split()[0], "%Y-%m-%d")
                date_filed = dt.date()
            else:
                continue  # Skip if no date

            # Extract PDF info
            opinion_info = fields.get("opinion", {})
            pdf_uri = opinion_info.get("uri", "")

            if not pdf_uri:
                continue  # Skip if no PDF

            # Build full PDF URL
            # URI format: /content/download/2484015/opinion/Opinion_SC2025-1378.pdf
            pdf_url = f"https://flcourts-media.flcourts.gov{pdf_uri}"

            # Extract content ID from URI
            # Example: /content/download/2484015/opinion/...
            content_id = None
            if "/content/download/" in pdf_uri:
                parts = pdf_uri.split("/")
                for i, part in enumerate(parts):
                    if part == "download" and i + 1 < len(parts):
                        content_id = parts[i + 1]
                        break

            # Extract note field (e.g., "Corrected Opinion")
            note = fields.get("note")

            # Extract oral argument URL if available
            oral_arg_url = result.get("oralArgUrl")

            # Yield ArchiveRequest to download the PDF
            yield ArchiveRequest(
                request=HTTPRequestParams(method=HttpMethod.GET, url=pdf_url),
                continuation=self.handle_pdf_download,
                expected_type="pdf",
                accumulated_data={
                    "court_id": court_id,
                    "case_number": case_number,
                    "case_name": case_name,
                    "date_filed": date_filed.isoformat(),
                    "note": note,
                    "oral_argument_url": oral_arg_url,
                    "pdf_url": pdf_url,
                    "content_id": content_id,
                    "source_url": COURT_CONFIG[court_id]["opinions_url"],
                },
            )

        # Check if there are more pages
        next_offset = current_offset + self.PAGE_SIZE
        if next_offset < total_count:
            # Build URL for next page
            date_gte_str = accumulated_data.get("date_gte")
            date_lte_str = accumulated_data.get("date_lte")
            date_gte = (
                date.fromisoformat(date_gte_str) if date_gte_str else None
            )
            date_lte = (
                date.fromisoformat(date_lte_str) if date_lte_str else None
            )

            api_url = self._build_api_url(
                court_id=court_id,
                offset=next_offset,
                query=accumulated_data.get("query", ""),
                start_date=date_gte,
                end_date=date_lte,
            )

            yield NavigatingRequest(
                request=HTTPRequestParams(method=HttpMethod.GET, url=api_url),
                continuation=self.parse_opinions_api,
                accumulated_data={
                    **accumulated_data,
                    "offset": next_offset,
                },
            )

    @step
    def handle_pdf_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Handle the downloaded PDF and create the final OpinionCluster."""
        # Build the opinion with the local path
        opinion = FloridaOpinion(
            download_url=accumulated_data["pdf_url"],
            type="010combined",
            content_id=accumulated_data.get("content_id"),
            local_path=str(response.file_url),
        )

        # Parse date
        date_filed = date.fromisoformat(accumulated_data["date_filed"])

        # Create the opinion cluster
        cluster = FloridaOpinionCluster(
            case_number=accumulated_data["case_number"],
            court_id=accumulated_data["court_id"],
            date_filed=date_filed,
            case_name=accumulated_data["case_name"],
            note=accumulated_data.get("note"),
            oral_argument_url=accumulated_data.get("oral_argument_url"),
            opinions=[opinion],
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)
