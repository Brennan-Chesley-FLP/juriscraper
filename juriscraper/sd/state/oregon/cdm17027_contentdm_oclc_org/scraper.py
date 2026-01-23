"""Oregon Appellate Courts Opinion Scraper.

This module contains a unified scraper for opinions from Oregon courts
using the State of Oregon Law Library's CONTENTdm digital collection:
- Oregon Supreme Court (or) - Collection p17027coll3
- Court of Appeals of Oregon (orctapp) - Collection p17027coll5

Entry points:
- Supreme Court: https://cdm17027.contentdm.oclc.org/digital/collection/p17027coll3
- Court of Appeals: https://cdm17027.contentdm.oclc.org/digital/collection/p17027coll5

API endpoints used:
- Query: /digital/bl/dmwebservices/index.php?q=dmQuery/{collection}/{searchterm}/...
- Item info: /digital/bl/dmwebservices/index.php?q=dmGetItemInfo/{collection}/{pointer}/json
- PDF download: https://ojd.contentdm.oclc.org/digital/api/collection/{collection}/id/{pointer}/download

CONTENTdm metadata fields:
- title: Document title (e.g., "S070647, Opinion")
- subjec: Case name (e.g., "Crandall v. State of Oregon")
- relispt: Case number (e.g., "S070647")
- type: Opinion type (e.g., "Opinion", "nonprecedential opinion")
- dated: Date decided (e.g., "2026-01-22")
- judge: Author (e.g., "Flynn")
- cita: Citation (e.g., "374 Or 699")
- subjec1: Parties (semicolon-separated)
- descri: Notes/disposition
- relhapt: Additional case number
- dmrecord: CONTENTdm record ID

Flow:
  1. get_entry -> query API for each collection (if "opinions" requested)
  2. parse_query_results -> extracts record IDs and basic metadata
  3. fetch_item_details -> gets full metadata for each record
  4. yields ArchiveRequests for PDFs
  5. handle_opinion_download -> stores local paths, yields final clusters

Design decisions:
- Uses CONTENTdm JSON API for efficiency over HTML scraping
- Uses DateRange filter on date_decided for searching
- Uses SetFilter on court_id to select which courts to scrape
- Archives opinion PDFs via ArchiveRequest
- Filters by opinion type to exclude petitions for review, etc.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import quote

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
    COLLECTION_TO_COURT_ID,
    COURT_ID_TO_COLLECTION,
    COURT_IDS,
    OregonOpinion,
    OregonOpinionCluster,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from juriscraper.scraper_driver.data_types import ScraperYield


class OregonScraper(BaseScraper[OregonOpinionCluster]):
    """Unified scraper for Oregon appellate court opinions.

    Scrapes opinions from Oregon Supreme Court and Court of Appeals
    via the State of Oregon Law Library's CONTENTdm digital collection.

    Usage:
        # Scrape all courts (default)
        scraper = OregonScraper()

        # Scrape only Supreme Court
        params = OregonScraper.params()
        params.OregonOpinionCluster.court_id.values = {"or"}
        scraper = OregonScraper(params=params)

        # Filter by date range
        params = OregonScraper.params()
        params.OregonOpinionCluster.date_decided.gte = date(2026, 1, 1)
        params.OregonOpinionCluster.date_decided.lte = date(2026, 1, 31)
        scraper = OregonScraper(params=params)

        # Lookup specific case number
        params = OregonScraper.params()
        params.OregonOpinionCluster.case_number.value = "S070647"
        scraper = OregonScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = COURT_IDS
    court_url: ClassVar[str] = "https://cdm17027.contentdm.oclc.org/"
    data_types: ClassVar[set[str]] = {"opinions"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-23"
    requires_auth: ClassVar[bool] = False

    # Rate limiting - be respectful to court servers
    msec_per_request_rate_limit: ClassVar[int] = 1000

    # Base URLs
    API_BASE = "https://cdm17027.contentdm.oclc.org/digital/bl/dmwebservices/index.php"
    PDF_BASE = "https://ojd.contentdm.oclc.org/digital/api/collection"

    # Fields to request in query
    QUERY_FIELDS = "title!subjec!relispt!type!dated!judge!cita"

    # Opinion types to include (exclude petitions for review, miscellaneous)
    INCLUDED_TYPES = {
        "opinion",
        "nonprecedential opinion",
        "awop",
        "banc",
    }

    # Maximum results per query page
    MAX_RESULTS_PER_PAGE = 100

    def _parse_date(self, date_str: str) -> date | None:
        """Parse a date string in YYYY-MM-DD format.

        Args:
            date_str: Date string in YYYY-MM-DD format.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        if not date_str:
            return None
        # Handle multiple dates (e.g., "1997-08-12 ; 1997-08-20")
        # Take the first date
        date_str = date_str.split(";")[0].strip()
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            return None

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
            model_proxy = self._params.OregonOpinionCluster
        except AttributeError:
            return None, None, None, None

        date_gte = None
        date_lte = None
        case_number = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_decided")
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

    def _get_target_collections(self) -> list[str]:
        """Get the list of collection IDs to scrape based on court_ids filter.

        Returns list of CONTENTdm collection IDs.
        """
        _, _, _, court_ids = self._get_opinions_search_params()

        if court_ids:
            collections = []
            for court_id in court_ids:
                if court_id in COURT_ID_TO_COLLECTION:
                    collections.append(COURT_ID_TO_COLLECTION[court_id])
            return collections if collections else ["p17027coll3"]

        # Default: both courts
        return ["p17027coll3", "p17027coll5"]

    def _build_query_url(
        self,
        collection: str,
        start: int = 1,
        date_gte: date | None = None,
        date_lte: date | None = None,
        case_number: str | None = None,
    ) -> str:
        """Build the CONTENTdm query URL.

        The dmQuery format is:
        dmQuery/{collection}/{searchterm}/{fields}/{sortby}/{maxrecs}/{start}/{suppress}/{docptr}/{suggest}/{facets}/{format}

        Args:
            collection: CONTENTdm collection ID
            start: Starting record (1-indexed)
            date_gte: Filter by date >= this value
            date_lte: Filter by date <= this value
            case_number: Filter by specific case number

        Returns:
            Full query URL
        """
        # Build search term
        if case_number:
            # Search by case number in relispt field
            searchterm = f"relispt^{case_number}"
        elif date_gte and date_lte:
            # Date range search - CONTENTdm uses ^ for starts with
            # For date ranges, we'll query by year-month prefix
            searchterm = f"dated^{date_gte.year}"
        elif date_gte:
            searchterm = f"dated^{date_gte.year}"
        else:
            # Default: get all, sorted by date descending
            searchterm = "CISOSEARCHALL"

        # Sort by dated descending
        sortby = "dated!desc"

        # URL encode the search term
        searchterm_encoded = quote(searchterm, safe="^!")

        # Build query URL
        # Format: dmQuery/collection/searchterm/fields/sortby/maxrecs/start/suppress/docptr/suggest/facets/format
        url = (
            f"{self.API_BASE}?q=dmQuery/{collection}/{searchterm_encoded}/"
            f"{self.QUERY_FIELDS}/{sortby}/{self.MAX_RESULTS_PER_PAGE}/{start}/0/0/0/0/json"
        )

        return url

    def _build_item_url(self, collection: str, pointer: int) -> str:
        """Build URL to get full item metadata.

        Args:
            collection: CONTENTdm collection ID
            pointer: Record pointer/ID

        Returns:
            URL for dmGetItemInfo API call
        """
        return f"{self.API_BASE}?q=dmGetItemInfo/{collection}/{pointer}/json"

    def _build_pdf_url(self, collection: str, pointer: int) -> str:
        """Build URL to download PDF.

        Args:
            collection: CONTENTdm collection ID
            pointer: Record pointer/ID

        Returns:
            Direct PDF download URL
        """
        return f"{self.PDF_BASE}/{collection}/id/{pointer}/download"

    # =========================================================================
    # Entry Point
    # =========================================================================

    def get_entry(self) -> Generator[NavigatingRequest, None, None]:
        """Yield initial requests for opinion scraping.

        Yields separate NavigatingRequests for each collection.
        """
        collections = self._get_target_collections()
        date_gte, date_lte, case_number, _ = self._get_opinions_search_params()

        first_collection = collections[0]
        remaining_collections = collections[1:]

        url = self._build_query_url(
            first_collection,
            start=1,
            date_gte=date_gte,
            date_lte=date_lte,
            case_number=case_number,
        )

        yield NavigatingRequest(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
            ),
            continuation=self.parse_query_results,
            accumulated_data={
                "collection": first_collection,
                "remaining_collections": remaining_collections,
                "start": 1,
                "date_gte": date_gte.isoformat() if date_gte else None,
                "date_lte": date_lte.isoformat() if date_lte else None,
                "case_number": case_number,
            },
        )

    # =========================================================================
    # Query Results Parsing
    # =========================================================================

    @step
    def parse_query_results(
        self,
        json_content: dict[str, Any],
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OregonOpinionCluster], None, None]:
        """Parse the CONTENTdm query results.

        Filters by opinion type and date range, then fetches full
        metadata for each matching record.
        """
        collection = accumulated_data.get("collection", "p17027coll3")
        remaining_collections = accumulated_data.get("remaining_collections", [])
        start = accumulated_data.get("start", 1)
        case_number = accumulated_data.get("case_number")
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")

        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        court_id = COLLECTION_TO_COURT_ID.get(collection, "or")

        # Parse pager info
        pager = json_content.get("pager", {})
        total = int(pager.get("total", 0))

        # Parse records
        records = json_content.get("records", [])

        for record in records:
            # Skip non-PDF records (jpg are image pages of compound objects)
            filetype = record.get("filetype", "")
            if filetype not in ("pdf", "cpd"):
                continue

            # Get basic metadata
            pointer = record.get("pointer")
            if not pointer:
                continue

            opinion_type = (record.get("type") or "").lower()

            # Filter by opinion type
            if opinion_type not in self.INCLUDED_TYPES:
                continue

            # Get date for filtering
            dated = record.get("dated", "")
            record_date = self._parse_date(dated)

            # Apply date filters
            if record_date:
                if date_gte and record_date < date_gte:
                    continue
                if date_lte and record_date > date_lte:
                    continue

            # Fetch full item details
            item_url = self._build_item_url(collection, pointer)

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=item_url,
                ),
                continuation=self.parse_item_details,
                accumulated_data={
                    "collection": collection,
                    "pointer": pointer,
                    "court_id": court_id,
                    "basic_record": record,
                },
            )

        # Handle pagination
        next_start = start + self.MAX_RESULTS_PER_PAGE
        if next_start <= total:
            url = self._build_query_url(
                collection,
                start=next_start,
                date_gte=date_gte,
                date_lte=date_lte,
                case_number=case_number,
            )

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_query_results,
                accumulated_data={
                    "collection": collection,
                    "remaining_collections": remaining_collections,
                    "start": next_start,
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
                    "case_number": case_number,
                },
            )

        # Move to next collection after processing this one
        elif remaining_collections:
            next_collection = remaining_collections[0]
            url = self._build_query_url(
                next_collection,
                start=1,
                date_gte=date_gte,
                date_lte=date_lte,
                case_number=case_number,
            )

            yield NavigatingRequest(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                ),
                continuation=self.parse_query_results,
                accumulated_data={
                    "collection": next_collection,
                    "remaining_collections": remaining_collections[1:],
                    "start": 1,
                    "date_gte": date_gte_str,
                    "date_lte": date_lte_str,
                    "case_number": case_number,
                },
            )

    # =========================================================================
    # Item Details Parsing
    # =========================================================================

    @step
    def parse_item_details(
        self,
        json_content: dict[str, Any],
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OregonOpinionCluster], None, None]:
        """Parse full item metadata and request PDF download.

        CONTENTdm fields:
        - title: Document title (e.g., "S070647, Opinion")
        - subjec: Case name (e.g., "Crandall v. State of Oregon")
        - relispt: Case number (e.g., "S070647")
        - type: Opinion type
        - dated: Date decided
        - judge: Author
        - cita: Citation (e.g., "374 Or 699")
        - subjec1: Parties (semicolon-separated)
        - descri: Notes/disposition
        - relhapt: Additional case number
        - dmrecord: CONTENTdm record ID
        """
        collection = accumulated_data.get("collection", "p17027coll3")
        pointer = accumulated_data.get("pointer")
        court_id = accumulated_data.get("court_id", "or")

        # Extract metadata
        case_number = json_content.get("relispt") or ""
        case_name = json_content.get("subjec") or json_content.get("title") or ""
        dated = json_content.get("dated") or ""
        date_decided = self._parse_date(dated)
        citation = json_content.get("cita") or None
        author = json_content.get("judge") or None
        opinion_type = json_content.get("type") or None
        notes = json_content.get("descri") or None
        additional_case_number = json_content.get("relhapt") or None
        parties_str = json_content.get("subjec1") or ""
        contentdm_id = json_content.get("dmrecord")

        # Parse parties (semicolon-separated)
        parties = None
        if parties_str:
            parties = [p.strip() for p in parties_str.split(";") if p.strip()]

        # If no case number, try to extract from title
        if not case_number:
            title = json_content.get("title") or ""
            match = re.match(r"([SA]\d+)", title)
            if match:
                case_number = match.group(1)

        if not case_number or not date_decided:
            # Skip records without essential metadata
            return

        # Build PDF URL
        pdf_url = self._build_pdf_url(collection, pointer)

        # Source URL for the record page
        source_url = f"https://cdm17027.contentdm.oclc.org/digital/collection/{collection}/id/{pointer}"

        # Build cluster data for accumulated_data
        cluster_data: dict[str, Any] = {
            "case_number": case_number,
            "court_id": court_id,
            "case_name": case_name,
            "date_decided": date_decided.isoformat() if date_decided else None,
            "citation": citation,
            "author": author,
            "opinion_type": opinion_type,
            "parties": parties,
            "notes": notes,
            "additional_case_number": additional_case_number,
            "contentdm_id": contentdm_id,
            "collection_id": collection,
            "source_url": source_url,
            "opinions_data": [{"download_url": pdf_url, "type": "majority"}],
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

    # =========================================================================
    # PDF Download Handling
    # =========================================================================

    @step
    def handle_opinion_download(
        self,
        response: ArchiveResponse,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[OregonOpinionCluster], None, None]:
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
            # Handle multiple PDFs per cluster (if needed in future)
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
    ) -> Generator[ScraperYield[OregonOpinionCluster], None, None]:
        """Build and yield the final OpinionCluster with all PDFs downloaded."""
        opinions = []
        for i, op_data in enumerate(accumulated_data["opinions_data"]):
            local_path = accumulated_data["downloaded_paths"].get(i)
            opinions.append(
                OregonOpinion(
                    download_url=op_data["download_url"],
                    type=op_data.get("type", "majority"),
                    local_path=local_path,
                    author=accumulated_data.get("author"),
                )
            )

        date_decided = None
        if accumulated_data.get("date_decided"):
            date_decided = date.fromisoformat(accumulated_data["date_decided"])

        cluster = OregonOpinionCluster(
            case_number=accumulated_data["case_number"],
            court_id=accumulated_data["court_id"],
            date_decided=date_decided,
            case_name=accumulated_data["case_name"],
            citation=accumulated_data.get("citation"),
            author=accumulated_data.get("author"),
            opinion_type=accumulated_data.get("opinion_type"),
            parties=accumulated_data.get("parties"),
            notes=accumulated_data.get("notes"),
            additional_case_number=accumulated_data.get("additional_case_number"),
            contentdm_id=accumulated_data.get("contentdm_id"),
            collection_id=accumulated_data.get("collection_id"),
            opinions=opinions,
            source_url=accumulated_data.get("source_url"),
        )

        yield ParsedData(cluster)
