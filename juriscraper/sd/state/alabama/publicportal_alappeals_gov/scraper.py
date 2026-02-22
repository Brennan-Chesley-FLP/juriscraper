"""Alabama Appellate Courts Scraper.

This module contains a unified scraper for opinions, oral arguments,
dockets, and historical opinions from Alabama appellate courts:

- Alabama Supreme Court (ala)
- Alabama Court of Civil Appeals (alactapp)
- Alabama Court of Criminal Appeals (alacrimapp)

Entry points:

- Opinions (Release Lists/Publications, May 2023+):

  - API: https://publicportal-api.alappeals.gov/courts/cms/publications
  - Portal: https://publicportal.alappeals.gov/portal/search/publication

- Historical Opinions (Pre-May 2023):

  - Source: https://judicial.alabama.gov/decision/*
  - PDFs: https://acis.alabama.gov/displaydocs2.cfm

- Dockets/Cases:

  - API: https://publicportal-api.alappeals.gov/courts/cms/cases
  - Portal: https://publicportal.alappeals.gov/portal/search/case

- Oral Arguments (Calendar):

  - API: https://publicportal-api.alappeals.gov/courts/cms/events
  - Portal: https://publicportal.alappeals.gov/portal/search/calendar

Opinions Flow (get_opinions):
  1. get_opinions -> API call to publications endpoint for selected courts
  2. parse_publications_list -> extracts release lists, yields archive requests for PDFs
     - Processes all publications on current page (not just first)
     - Automatically paginates to next page if needed
     - Respects date range filters and stops when outside range
  3. handle_opinion_download -> stores local paths, yields final AlaOpinionClusters

Historical Opinions Flow (get_historical_opinions):
  1. get_historical_opinions -> HTML requests to judicial.alabama.gov decisions pages
  2. parse_historical_decisions_list -> parses HTML table, yields archive requests for PDFs
  3. handle_historical_pdf_download -> stores local paths, yields AlaHistoricalReleaseList

Dockets Flow (get_dockets):
  1. get_dockets -> yields date range search requests
  2. parse_dockets_search -> handles 10,000 result limit by splitting date ranges
     - If results >= 10,000, splits date range in half and searches both halves
     - Otherwise, yields case detail requests for each case found
     - Paginates through all results
  3. parse_case_detail -> parses case header, yields party fetch request
  4. parse_case_parties -> parses parties, yields docket entries fetch request
  5. parse_docket_entries -> parses docket entries, yields final AlaDocket

Oral Arguments Flow (get_oral_arguments):
  1. get_oral_arguments -> API call to events endpoint
  2. parse_events_list -> extracts calendar events, yields requests for event hearings
     - Filters by court_id and date range
     - Processes all pages until pagination is exhausted
  3. parse_event_hearings -> parses cases for each event, yields AlaOralArgument objects

Design decisions:
- Uses JSON API endpoints for data retrieval (current opinions, dockets, oral args)
- Uses HTML scraping for historical opinions (pre-May 2023)
- Uses DateRange filter on date_filed for searching
- Uses SetFilter on court_id to select which courts to scrape
- Archives opinion PDFs via Request(archive=True)
- Extracts lower court info from case title parenthetical
- Handles "Per Curiam" and "On Rehearing" designations
- Pagination: processes all pages until date range is exhausted
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urlencode, urlparse

from kent.common.decorators import entry, step
from kent.common.page_element import PageElement
from kent.data_types import (
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
    API_CONFIG,
    COURT_CONFIG,
    AlaDocket,
    AlaDocketEntry,
    AlaHistoricalReleaseList,
    AlaOpinion,
    AlaOpinionCluster,
    AlaOralArgument,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from kent.data_types import ScraperYield


class AlabamaScraper(
    BaseScraper[
        AlaOpinionCluster
        | AlaOralArgument
        | AlaDocket
        | AlaHistoricalReleaseList
    ]
):
    """Unified scraper for Alabama appellate court data.

    Scrapes opinions, oral argument information, and docket information
    from Alabama courts.

    Supports Alabama Supreme Court (ala), Court of Civil Appeals (alactapp),
    and Court of Criminal Appeals (alacrimapp).

    Usage:
        # Scrape everything (all data types, all courts)
        scraper = AlabamaScraper()

        # Scrape only opinions (disable other data types)
        params = AlabamaScraper.params()
        params.AlaOralArgument = None
        params.AlaDocket = None
        scraper = AlabamaScraper(params=params)

        # Scrape only opinions from Supreme Court
        params = AlabamaScraper.params()
        params.AlaOralArgument = None
        params.AlaDocket = None
        params.AlaOpinionCluster.court_id.values = {"ala"}
        scraper = AlabamaScraper(params=params)

        # Filter opinions by date range
        params = AlabamaScraper.params()
        params.AlaOpinionCluster.date_filed.gte = date(2025, 1, 1)
        params.AlaOpinionCluster.date_filed.lte = date(2025, 12, 31)
        scraper = AlabamaScraper(params=params)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"ala", "alactapp", "alacrimapp"}
    court_url: ClassVar[str] = "https://publicportal.alappeals.gov/"
    data_types: ClassVar[set[str]] = {
        "opinions",
        "historical_opinions",
        "oral_arguments",
        "dockets",
    }
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-01-21"
    requires_auth: ClassVar[bool] = False

    rate_limits: ClassVar[list[Rate] | None] = [Rate(4, Duration.SECOND)]

    # === Dockets API limits ===
    # The API returns a maximum of 10,000 results per search
    # If a date range exceeds this, we split it in half
    DOCKETS_MAX_RESULTS: ClassVar[int] = 10000
    DOCKETS_PAGE_SIZE: ClassVar[int] = 50

    # === Regex patterns ===
    # Pattern to extract lower court info from case title
    # Format: "Case Name (Appeal from <court>: <number>)"
    LOWER_COURT_PATTERN = re.compile(
        r"\(Appeal from (?P<lower_court>.+?): (?P<lower_court_number>.+?)\)"
    )

    # === Historical Opinions Patterns ===
    # Regex to parse release date from link text
    # Format: "Decisions on Friday, May 19, 2023"
    HISTORICAL_DATE_PATTERN = re.compile(
        r"Decisions on \w+,\s+(\w+)\s+(\d{1,2}),\s+(\d{4})"
    )

    # Month name to number mapping
    MONTH_MAP: ClassVar[dict[str, int]] = {
        "January": 1,
        "February": 2,
        "March": 3,
        "April": 4,
        "May": 5,
        "June": 6,
        "July": 7,
        "August": 8,
        "September": 9,
        "October": 10,
        "November": 11,
        "December": 12,
    }

    def _parse_date(self, date_str: str) -> date | None:
        """Parse ISO 8601 date string from Alabama API.

        The API returns dates in ISO 8601 format like:
        - 2023-11-09T14:15:00.000+00:00

        Args:
            date_str: ISO 8601 date string.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        if not date_str:
            return None

        try:
            # Extract just the date portion (YYYY-MM-DD)
            return datetime.fromisoformat(date_str[:10]).date()
        except (ValueError, IndexError):
            pass

        return None

    def _parse_historical_release_date(self, text: str) -> date | None:
        """Parse release date from historical link text.

        Args:
            text: Link text like "Decisions on Friday, May 19, 2023"

        Returns:
            Parsed date object, or None if parsing fails.
        """
        match = self.HISTORICAL_DATE_PATTERN.search(text)
        if not match:
            return None

        month_name = match.group(1)
        day = int(match.group(2))
        year = int(match.group(3))

        month = self.MONTH_MAP.get(month_name)
        if not month:
            return None

        try:
            return date(year, month, day)
        except ValueError:
            return None

    # =========================================================================
    # Parameter extraction
    # =========================================================================

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
            model_proxy = self._params.AlaOpinionCluster
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

    def _get_dockets_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters for dockets from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, case_number, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.AlaDocket
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

    def _get_oral_arguments_search_params(
        self,
    ) -> tuple[date | None, date | None, str | None, set[str] | None]:
        """Extract search parameters for oral arguments from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, case_number, court_ids)
        """
        if self._params is None:
            return None, None, None, None

        try:
            model_proxy = self._params.AlaOralArgument
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

    def _get_historical_search_params(
        self,
    ) -> tuple[date | None, date | None, set[str] | None]:
        """Extract search parameters for historical opinions from ScraperParams.

        Returns:
            Tuple of (date_gte, date_lte, court_ids)
        """
        if self._params is None:
            return None, None, None

        try:
            model_proxy = self._params.AlaHistoricalReleaseList
        except AttributeError:
            return None, None, None

        date_gte = None
        date_lte = None
        court_ids = None

        searchable = model_proxy.get_searchable_fields()

        date_field = searchable.get("date_filed")
        if date_field and date_field.is_set():
            date_gte = date_field.gte
            date_lte = date_field.lte

        court_field = searchable.get("court_id")
        if court_field and court_field.is_set():
            court_ids = court_field.values

        return date_gte, date_lte, court_ids

    def _get_target_courts(self, data_type: str) -> set[str]:
        """Get the set of court IDs to scrape for a given data type."""
        if data_type == "opinions":
            _, _, _, court_ids = self._get_opinions_search_params()
        elif data_type == "historical_opinions":
            _, _, court_ids = self._get_historical_search_params()
        elif data_type == "dockets":
            _, _, _, court_ids = self._get_dockets_search_params()
        elif data_type == "oral_arguments":
            _, _, _, court_ids = self._get_oral_arguments_search_params()
        else:
            court_ids = None

        if court_ids:
            valid_courts = court_ids & set(COURT_CONFIG.keys())
            if valid_courts:
                return valid_courts

        return set(COURT_CONFIG.keys())

    # =========================================================================
    # Opinions Entry Point & Scraping Steps
    # =========================================================================

    @entry(AlaOpinionCluster)
    def get_opinions(self) -> Generator[Request, None, None]:
        """Yield initial requests for opinions scraping.

        Makes API calls to the publications endpoint for each target court.
        """
        target_courts = self._get_target_courts("opinions")

        for court_id in sorted(target_courts):
            config = COURT_CONFIG[court_id]
            court_guid = config["court_guid"]

            # Build API URL
            # Example: https://publicportal-api.alappeals.gov/courts/cms/publications?courtID={guid}&page=0&size=25&sort=publicationDate%2Cdesc
            api_url = f"{API_CONFIG['base_url']}{API_CONFIG['publications_endpoint']}"
            params = {
                "courtID": court_guid,
                "page": "0",
                "size": "25",
                "sort": "publicationDate,desc",
            }

            # Build URL with query params
            url = f"{api_url}?{urlencode(params)}"

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={
                        "Accept": "application/json",
                    },
                ),
                continuation=self.parse_publications_list,
                accumulated_data={
                    "court_id": court_id,
                    "court_guid": court_guid,
                },
            )

    @step(
        xsd="xsds/parse_publications_list.xsd",
        json_model="api.responses.PublicationsListResponse",
    )
    def parse_publications_list(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse the publications API response and yield archive requests for PDFs.

        The API returns JSON with a structure like::

            {
                "_embedded": {
                    "results": [
                        {
                            "publicationUUID": "...",
                            "publicationNumber": "SC-RELEASE-2023-11-09",
                            "scheduledDate": "2023-11-09T14:15:00.000+00:00",
                            "publicationItems": [
                                {
                                    "publicationItemUUID": "...",
                                    "caseInstanceUUID": "...",
                                    "caseNumber": "SC-2023-0123",
                                    "groupName": "Justice Smith",
                                    "title": "Case Name (Appeal from Circuit Court: CV-123)",
                                    "decision": "Affirmed.",
                                    "documents": [
                                        {
                                            "documentLinkUUID": "...",
                                            "documentName": "Decision"
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            }
        """
        court_id: str = accumulated_data.get("court_id", "")
        court_guid: str = accumulated_data.get("court_guid", "")

        # Navigate to results
        embedded = json_content.get("_embedded", {})
        results = embedded.get("results", [])

        if not results:
            return

        # Get pagination info
        page_info = json_content.get("page", {})
        current_page = page_info.get("number", 0)
        total_pages = page_info.get("totalPages", 1)

        # Get date filter parameters
        date_gte, date_lte, _, _ = self._get_opinions_search_params()

        # Track if we should continue paginating
        should_paginate = False
        earliest_date_seen = None

        # Process all results in current page (not just the first one)
        for publication in results:
            publication_uuid = publication.get("publicationUUID")
            publication_number = publication.get("publicationNumber")
            scheduled_date_str = publication.get("scheduledDate", "")
            date_filed = self._parse_date(scheduled_date_str)

            if not date_filed:
                continue

            # Track the earliest date we've seen for pagination decisions
            if earliest_date_seen is None or date_filed < earliest_date_seen:
                earliest_date_seen = date_filed

            # Check if this publication is within date range
            if date_lte and date_filed > date_lte:
                # Publication is too new, skip it
                continue

            if date_gte and date_filed < date_gte:
                # Publication is too old, stop processing this page
                # Don't paginate further
                break

            # If we're still in range, we might need to paginate
            if date_gte is None or date_filed >= date_gte:
                should_paginate = True

            publication_items = publication.get("publicationItems", [])

            for item in publication_items:
                documents = item.get("documents", [])
                if not documents:
                    continue

                case_number = item.get("caseNumber", "")
                title = item.get("title", "")
                group_name = item.get("groupName", "")
                decision = item.get("decision", "")
                case_instance_uuid = item.get("caseInstanceUUID", "")
                publication_item_uuid = item.get("publicationItemUUID", "")

                # Extract lower court info from title
                lower_court = ""
                lower_court_number = ""
                match = self.LOWER_COURT_PATTERN.search(title)
                if match:
                    lower_court = match.group("lower_court").strip()
                    lower_court_number = match.group(
                        "lower_court_number"
                    ).strip()
                    # Remove the parenthetical from the title
                    title = title[: match.start()].rstrip()

                # Determine authoring judge and per curiam status
                judge = group_name
                per_curiam = False
                on_rehearing = False

                if "On Rehearing" in judge:
                    on_rehearing = True
                    judge = ""
                elif "curiam" in judge.lower():
                    per_curiam = True
                    judge = ""

                # Build document download URL
                # Format: https://publicportal-api.alappeals.gov/courts/{court-guid}/cms/case/{case-guid}/docketentrydocuments/{doc-guid}
                doc_uuid = documents[0].get("documentLinkUUID", "")
                if not doc_uuid:
                    continue

                download_url = f"{API_CONFIG['base_url']}/courts/{court_guid}/cms/case/{case_instance_uuid}/docketentrydocuments/{doc_uuid}"

                # Create opinion cluster
                cluster = AlaOpinionCluster(
                    case_number=case_number,
                    court_id=court_id,
                    date_filed=date_filed,
                    case_name=title,
                    publication_number=publication_number,
                    authoring_judge=judge if judge else None,
                    decision_text=decision if decision else None,
                    lower_court=lower_court if lower_court else None,
                    lower_court_number=lower_court_number
                    if lower_court_number
                    else None,
                    per_curiam=per_curiam,
                    on_rehearing=on_rehearing,
                    publication_uuid=publication_uuid,
                    publication_item_uuid=publication_item_uuid,
                    case_instance_uuid=case_instance_uuid,
                    source_url=response.url,
                    opinions=[],
                )

                # Create opinion
                opinion = AlaOpinion(
                    download_url=download_url,
                    type="majority",
                    authoring_judge=judge if judge else None,
                    decision_text=decision if decision else None,
                )

                cluster.opinions.append(opinion)

                # Yield archive request for PDF
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=download_url,
                    ),
                    continuation=self.handle_opinion_download,
                    accumulated_data={
                        "cluster": cluster.model_dump(mode="json"),
                        "opinion_index": 0,
                    },
                )

        # Pagination logic: fetch next page if needed
        if (
            should_paginate
            and current_page + 1 < total_pages
            and (
                date_gte is None
                or (earliest_date_seen and earliest_date_seen >= date_gte)
            )
        ):
            # Build next page URL
            api_url = f"{API_CONFIG['base_url']}{API_CONFIG['publications_endpoint']}"
            params = {
                "courtID": court_guid,
                "page": str(current_page + 1),
                "size": "25",
                "sort": "publicationDate,desc",
            }
            url = f"{api_url}?{urlencode(params)}"

            yield Request(
                nonnavigating=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={
                        "Accept": "application/json",
                    },
                ),
                continuation=self.parse_publications_list,
                accumulated_data={
                    "court_id": court_id,
                    "court_guid": court_guid,
                },
            )

    @step()
    def handle_opinion_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Handle the downloaded opinion PDF and yield the final cluster.

        Args:
            local_filepath: Local path where the PDF was archived
            accumulated_data: Contains cluster and opinion_index
        """
        cluster_data = accumulated_data.get("cluster")
        opinion_index = accumulated_data.get("opinion_index", 0)

        if not cluster_data:
            return

        cluster = AlaOpinionCluster.model_validate(cluster_data)
        if not cluster.opinions:
            return

        # Update the opinion with the local path
        if opinion_index < len(cluster.opinions):
            cluster.opinions[opinion_index].local_path = local_filepath

        # Yield the complete cluster
        yield ParsedData(data=cluster)

    # =========================================================================
    # Historical Opinions Entry Point & Scraping Steps (pre-May 2023)
    # =========================================================================

    @entry(AlaHistoricalReleaseList)
    def get_historical_opinions(self) -> Generator[Request, None, None]:
        """Yield initial requests for historical opinions scraping.

        Fetches the decisions listing pages from judicial.alabama.gov
        for each target court. These pages contain links to weekly PDF
        release lists on acis.alabama.gov.
        """
        target_courts = self._get_target_courts("historical_opinions")

        for court_id in sorted(target_courts):
            config = COURT_CONFIG[court_id]
            url = config["decisions_url"]

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={
                        "Accept": "text/html",
                    },
                ),
                continuation=self.parse_historical_decisions_list,
                accumulated_data={
                    "court_id": court_id,
                },
            )

    @step()
    def parse_historical_decisions_list(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse the historical decisions listing page and yield archive requests for PDFs.

        The page contains a DataTables table where each row has a link to
        a release list PDF on acis.alabama.gov.

        The table HTML structure:
        <table>
          <tbody>
            <tr>
              <td>
                <a href="https://acis.alabama.gov/displaydocs2.cfm?no=...&event=...">
                  Decisions on Friday, May 19, 2023
                </a>
              </td>
            </tr>
          </tbody>
        </table>
        """
        court_id: str = accumulated_data.get("court_id", "")

        # Get date filter parameters
        date_gte, date_lte, _ = self._get_historical_search_params()

        # Find all links to acis.alabama.gov release list PDFs
        links = page.query_xpath(
            "//a[contains(@href, 'acis.alabama.gov/displaydocs2.cfm')]",
            "historical decisions PDF links",
            min_count=0,
        )

        for link_el in links:
            pdf_url = link_el.get_attribute("href")
            if not pdf_url:
                continue
            link_text = link_el.text_content().strip()

            # Parse the release date from link text
            release_date = self._parse_historical_release_date(link_text)
            if not release_date:
                continue

            # Check date range filters
            if date_lte and release_date > date_lte:
                continue
            if date_gte and release_date < date_gte:
                continue

            # Parse ACIS parameters from URL
            parsed = urlparse(pdf_url.strip())
            params = parse_qs(parsed.query)
            acis_doc_no = params.get("no", [""])[0]
            acis_event = params.get("event", [""])[0]

            # Create release list object
            release_list = AlaHistoricalReleaseList(
                court_id=court_id,
                date_filed=release_date,
                case_name=link_text,
                pdf_url=pdf_url.strip(),
                source_url=response.url,
                acis_doc_no=acis_doc_no.strip() if acis_doc_no else None,
                acis_event=acis_event.strip() if acis_event else None,
            )

            # Yield archive request to download the PDF
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=pdf_url.strip(),
                ),
                continuation=self.handle_historical_pdf_download,
                accumulated_data={
                    "release_list": release_list.model_dump(mode="json"),
                },
            )

    @step()
    def handle_historical_pdf_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Handle the downloaded historical PDF and yield the final release list.

        Args:
            local_filepath: Local path where the PDF was archived
            accumulated_data: Contains release_list object
        """
        release_list_data = accumulated_data.get("release_list")
        if not release_list_data:
            return

        release_list = AlaHistoricalReleaseList.model_validate(
            release_list_data
        )

        # Update the release list with the local path
        release_list.local_path = local_filepath

        # Yield the complete release list
        yield ParsedData(data=release_list)

    # =========================================================================
    # Oral Arguments Entry Point & Scraping Steps
    # =========================================================================

    @entry(AlaOralArgument)
    def get_oral_arguments(self) -> Generator[Request, None, None]:
        """Yield initial requests for oral arguments scraping.

        Makes API calls to the events endpoint to get calendar events
        (oral argument sessions) for all courts.
        """
        date_gte, date_lte, case_number, _ = (
            self._get_oral_arguments_search_params()
        )

        # If a specific case number is requested, we can't search by case
        # number in the events API directly - events are searched by date
        # The case filtering happens in parse_event_hearings
        # So we proceed with date-based search even if case_number is set
        pass

        # Default date range if not specified
        # Events API searches for upcoming and recent events
        if date_gte is None:
            date_gte = date.today() - timedelta(days=180)  # 6 months ago
        if date_lte is None:
            date_lte = date.today() + timedelta(days=365)  # 1 year ahead

        # Build API URL for events
        # Example: https://publicportal-api.alappeals.gov/courts/cms/events?startDateFrom=...&startDateTo=...
        api_url = f"{API_CONFIG['base_url']}{API_CONFIG['events_endpoint']}"
        params = {
            "startDateFrom": self._format_api_datetime(
                date_gte, end_of_day=False
            ),
            "startDateTo": self._format_api_datetime(
                date_lte, end_of_day=True
            ),
            "page": "0",
            "size": "100",
            "sort": "startDate,desc",
        }

        url = f"{api_url}?{urlencode(params)}"

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={
                    "Accept": "application/json",
                },
            ),
            continuation=self.parse_events_list,
            accumulated_data={
                "start_date": date_gte.isoformat(),
                "end_date": date_lte.isoformat(),
                "is_first_page": True,
            },
        )

    @step(
        xsd="xsds/parse_events_list.xsd",
        json_model="api.responses.EventsListResponse",
    )
    def parse_events_list(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse the events API response and yield requests for event hearings.

        The API returns JSON with calendar events (oral argument sessions).
        For each event, we fetch the hearings (cases scheduled for that session).

        API Response structure::

            {
                "_embedded": {
                    "results": [
                        {
                            "eventUUID": "...",
                            "eventName": "Oral Argument",
                            "courtID": "1",
                            "courtAbbreviation": "Alabama Supreme Court",
                            "courtSessionType": "Oral Argument",
                            "startDate": "2026-02-04T06:00:00.000+00:00",
                            "location": "Heflin-Torbert Judicial Building"
                        }
                    ]
                },
                "page": {
                    "size": 100,
                    "totalElements": 3,
                    "totalPages": 1,
                    "number": 0
                }
            }
        """
        start_date = date.fromisoformat(accumulated_data["start_date"])
        end_date = date.fromisoformat(accumulated_data["end_date"])

        # Get pagination info
        page_info = json_content.get("page", {})
        current_page = page_info.get("number", 0)
        total_pages = page_info.get("totalPages", 1)

        # Get target courts (filter by court if specified)
        target_courts = self._get_target_courts("oral_arguments")

        # Process events
        results = json_content.get("_embedded", {}).get("results", [])
        for event in results:
            event_uuid = event.get("eventUUID")
            court_abbr = event.get("courtAbbreviation", "")
            event_start_date_str = event.get("startDate")
            location = event.get("location", "")

            if not event_uuid:
                continue

            # Map court abbreviation to court_id
            court_id = self._get_court_id_from_abbreviation(court_abbr)
            if not court_id or court_id not in target_courts:
                continue

            # Parse event date
            event_date = self._parse_date(event_start_date_str)
            if not event_date:
                continue

            # Check if event is within date range
            if event_date < start_date or event_date > end_date:
                continue

            # Get court GUID
            config = COURT_CONFIG.get(court_id)
            if not config:
                continue

            court_guid = config["court_guid"]

            # Fetch hearings for this event
            hearings_url = (
                f"{API_CONFIG['base_url']}/courts/{court_guid}"
                f"/cms/events/{event_uuid}/hearings"
                "?page=0&size=100&sort=orderBy,asc"
            )

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=hearings_url,
                    headers={
                        "Accept": "application/json",
                    },
                ),
                continuation=self.parse_event_hearings,
                accumulated_data={
                    "court_id": court_id,
                    "court_guid": court_guid,
                    "event_uuid": event_uuid,
                    "event_date": event_date.isoformat(),
                    "location": location,
                },
            )

        # Handle pagination
        if current_page + 1 < total_pages:
            # Fetch next page
            api_url = (
                f"{API_CONFIG['base_url']}{API_CONFIG['events_endpoint']}"
            )
            params = {
                "startDateFrom": self._format_api_datetime(
                    start_date, end_of_day=False
                ),
                "startDateTo": self._format_api_datetime(
                    end_date, end_of_day=True
                ),
                "page": str(current_page + 1),
                "size": "100",
                "sort": "startDate,desc",
            }

            url = f"{api_url}?{urlencode(params)}"

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={
                        "Accept": "application/json",
                    },
                ),
                continuation=self.parse_events_list,
                accumulated_data={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "is_first_page": False,
                },
            )

    @step(
        xsd="xsds/parse_event_hearings.xsd",
        json_model="api.responses.EventHearingsResponse",
    )
    def parse_event_hearings(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse hearings for an oral argument event and yield AlaOralArgument objects.

        API Response structure::

            {
                "_embedded": {
                    "results": [
                        {
                            "startDate": "2026-02-04T16:00:00.000+00:00",
                            "hearingType": "Oral Argument",
                            "hearingStatus": "Scheduled",
                            "caseHeader": {
                                "caseInstanceUUID": "...",
                                "caseNumber": "SC-2024-0672",
                                "caseTitle": "Ex parte Altonio Spencer...",
                                "courtID": "1"
                            }
                        }
                    ]
                }
            }
        """
        court_id = accumulated_data["court_id"]
        court_guid = accumulated_data["court_guid"]
        event_uuid = accumulated_data["event_uuid"]
        event_date = date.fromisoformat(accumulated_data["event_date"])

        # Get case number filter if specified
        _, _, case_number_filter, _ = self._get_oral_arguments_search_params()

        # Get hearings
        results = json_content.get("_embedded", {}).get("results", [])

        for hearing in results:
            case_header = hearing.get("caseHeader", {})
            case_instance_uuid = case_header.get("caseInstanceUUID")
            case_number = case_header.get("caseNumber", "")
            case_title = case_header.get("caseTitle", "")
            hearing_start = hearing.get("startDate")

            if not case_number or not case_instance_uuid:
                continue

            # Filter by case number if specified
            if case_number_filter and case_number != case_number_filter:
                continue

            # Parse hearing date/time
            date_argued = self._parse_date(hearing_start)
            if not date_argued:
                date_argued = event_date

            # Build source URL
            source_url = f"{API_CONFIG['portal_url']}/portal/court/{court_guid}/case/{case_instance_uuid}"

            # Create oral argument object
            oral_arg = AlaOralArgument(
                case_number=case_number,
                court_id=court_id,
                date_argued=date_argued,
                case_name=case_title,
                source_url=source_url,
                calendar_uuid=event_uuid,
                case_instance_uuid=case_instance_uuid,
            )

            yield ParsedData(data=oral_arg)

    def _get_court_id_from_abbreviation(self, abbr: str) -> str | None:
        """Map court abbreviation to court_id.

        Args:
            abbr: Court abbreviation (e.g., "Alabama Supreme Court")

        Returns:
            Court ID or None if not found
        """
        court_mapping = {
            "Alabama Supreme Court": "ala",
            "Alabama Court of Civil Appeals": "alactapp",
            "Alabama Court of Criminal Appeals": "alacrimapp",
        }
        return court_mapping.get(abbr)

    # =========================================================================
    # Dockets Entry Point & Scraping Steps
    # =========================================================================

    def _format_api_datetime(self, d: date, end_of_day: bool = False) -> str:
        """Format a date for the Alabama API.

        Args:
            d: The date to format.
            end_of_day: If True, use 23:59:59.900, otherwise 00:00:00.001.

        Returns:
            ISO 8601 formatted datetime string with timezone.
        """
        if end_of_day:
            return f"{d.isoformat()}T23:59:59.900-06:00"
        return f"{d.isoformat()}T00:00:00.001-06:00"

    @entry(AlaDocket)
    def get_dockets(self) -> Generator[Request, None, None]:
        """Yield initial requests for dockets scraping.

        Uses date range splitting to handle the 10,000 result limit.
        If no date range is specified, defaults to searching year by year
        starting from 1985.
        """
        date_gte, date_lte, case_number, _ = self._get_dockets_search_params()

        # If a specific case number is requested, search for it directly
        # For now, we use date range search since the API doesn't have a direct
        # case number search endpoint. The filtering happens in parse_case_detail
        # where we can check if the case_number matches the requested one
        pass

        # Default date range if not specified
        if date_gte is None:
            date_gte = date(1985, 1, 1)
        if date_lte is None:
            date_lte = date.today()

        # Start with the full date range - we'll split if needed
        yield from self._yield_dockets_search_request(date_gte, date_lte)

    def _yield_dockets_search_request(
        self, start_date: date, end_date: date
    ) -> Generator[Request, None, None]:
        """Yield a search request for dockets in the given date range.

        Args:
            start_date: Start of the date range (inclusive).
            end_date: End of the date range (inclusive).
        """
        # Build API URL
        # Example: https://publicportal-api.alappeals.gov/courts/cms/cases?caseHeader.filedDateFrom=...&caseHeader.filedDateTo=...
        api_url = f"{API_CONFIG['base_url']}/courts/cms/cases"
        params = {
            "caseHeader.filedDateFrom": self._format_api_datetime(
                start_date, end_of_day=False
            ),
            "caseHeader.filedDateTo": self._format_api_datetime(
                end_date, end_of_day=True
            ),
            "page": "0",
            "size": str(self.DOCKETS_PAGE_SIZE),
            "sort": "caseHeader.filedDate,asc",
        }

        url = f"{api_url}?{urlencode(params)}"

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=url,
                headers={
                    "Accept": "application/json",
                },
            ),
            continuation=self.parse_dockets_search,
            accumulated_data={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "is_first_page": True,
            },
        )

    @step(
        xsd="xsds/parse_dockets_search.xsd",
        json_model="api.responses.DocketsSearchResponse",
    )
    def parse_dockets_search(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse the case search API response.

        Handles the 10,000 result limit by splitting date ranges.
        Yields requests for case details for each case found.

        API Response structure::

            {
                "_embedded": {
                    "results": [
                        {
                            "caseHeader": {
                                "caseInstanceUUID": "...",
                                "caseNumber": "SC-2023-0123",
                                "caseTitle": "...",
                                "courtID": 123,
                                "filedDate": "2023-11-09T14:15:00.000+00:00",
                                ...
                            }
                        }
                    ]
                },
                "page": {
                    "size": 50,
                    "number": 0,
                    "totalElements": 12345,
                    "totalPages": 247
                }
            }
        """
        start_date = date.fromisoformat(accumulated_data["start_date"])
        end_date = date.fromisoformat(accumulated_data["end_date"])
        is_first_page = accumulated_data.get("is_first_page", False)

        # Get pagination info
        page_info = json_content.get("page", {})
        current_page = page_info.get("number", 0)
        total_pages = page_info.get("totalPages", 1)
        total_elements = page_info.get("totalElements", 0)

        # Check if we hit the 10,000 limit on the first page
        if is_first_page and total_elements >= self.DOCKETS_MAX_RESULTS:
            # Split the date range in half and search both halves
            yield from self._split_date_range(start_date, end_date)
            return

        # Navigate to results
        embedded = json_content.get("_embedded", {})
        results = embedded.get("results", [])

        # Process each case in the results
        for result in results:
            case_header = result.get("caseHeader", {})
            case_instance_uuid = case_header.get("caseInstanceUUID")
            court_id_num = case_header.get("courtID")

            if not case_instance_uuid or not court_id_num:
                continue

            # Map numeric court ID to court_guid
            court_guid = self._get_court_guid_from_id(court_id_num)
            if not court_guid:
                continue

            # Yield request for case detail
            detail_url = (
                f"{API_CONFIG['base_url']}/courts/{court_guid}"
                f"/cms/cases/{case_instance_uuid}"
            )

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=detail_url,
                    headers={
                        "Accept": "application/json",
                    },
                ),
                continuation=self.parse_case_detail,
                accumulated_data={
                    "case_instance_uuid": case_instance_uuid,
                    "court_guid": court_guid,
                },
            )

        # Paginate if there are more pages
        if current_page + 1 < total_pages:
            api_url = f"{API_CONFIG['base_url']}/courts/cms/cases"
            params = {
                "caseHeader.filedDateFrom": self._format_api_datetime(
                    start_date, end_of_day=False
                ),
                "caseHeader.filedDateTo": self._format_api_datetime(
                    end_date, end_of_day=True
                ),
                "page": str(current_page + 1),
                "size": str(self.DOCKETS_PAGE_SIZE),
                "sort": "caseHeader.filedDate,asc",
            }
            url = f"{api_url}?{urlencode(params)}"

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={
                        "Accept": "application/json",
                    },
                ),
                continuation=self.parse_dockets_search,
                accumulated_data={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "is_first_page": False,
                },
            )

    def _split_date_range(
        self, start_date: date, end_date: date
    ) -> Generator[Request, None, None]:
        """Split a date range in half and yield searches for both halves.

        This is used when the API returns 10,000+ results for a date range.

        Args:
            start_date: Start of the date range.
            end_date: End of the date range.
        """
        # Calculate the midpoint
        days_diff = (end_date - start_date).days
        if days_diff <= 0:
            # Can't split further - single day with 10,000+ results
            # We'll just process what we can get (first 10,000 results)
            # Log a warning since we're losing data
            # Note: This is a very rare edge case for extremely high-volume days
            # In production, this should log a warning or error
            yield from self._yield_dockets_search_request(start_date, end_date)
            return

        mid_date = start_date + timedelta(days=days_diff // 2)

        # Search first half
        yield from self._yield_dockets_search_request(start_date, mid_date)

        # Search second half (day after midpoint to end)
        yield from self._yield_dockets_search_request(
            mid_date + timedelta(days=1), end_date
        )

    def _get_court_guid_from_id(self, court_id: int | str) -> str | None:
        """Map court ID to court GUID.

        The API returns court IDs as strings ("1", "2", "3") in case search
        results. We need GUIDs for detail requests.
        """
        # Convert to string for consistent lookup
        court_id_str = str(court_id)

        # Mapping discovered from API responses
        court_id_to_guid = {
            "1": COURT_CONFIG["ala"]["court_guid"],  # Supreme Court
            "2": COURT_CONFIG["alacrimapp"]["court_guid"],  # Criminal Appeals
            "3": COURT_CONFIG["alactapp"]["court_guid"],  # Civil Appeals
        }
        return court_id_to_guid.get(court_id_str)

    def _get_court_id_from_guid(self, court_guid: str) -> str | None:
        """Map court GUID to our court_id string."""
        for court_id, config in COURT_CONFIG.items():
            if config["court_guid"] == court_guid:
                return court_id
        return None

    @step(
        xsd="xsds/parse_case_detail.xsd",
        json_model="api.responses.CaseDetailResponse",
    )
    def parse_case_detail(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse case detail API response and fetch parties/docket entries.

        API Response structure::

            {
                "caseHeader": {
                    "caseInstanceUUID": "...",
                    "caseNumber": "SC-2023-0123",
                    "caseTitle": "...",
                    "caseCaption": "...",
                    "closedFlag": false,
                    "caseClassification": "Appeal - Civil - Other",
                    "filedDate": "2023-11-09T14:15:00.000+00:00",
                    "originatingCourtCases": [
                        {
                            "originatingCourtName": "Circuit Court",
                            "originatingCaseNumber": "CV-123"
                        }
                    ]
                }
            }
        """
        case_instance_uuid = accumulated_data["case_instance_uuid"]
        court_guid = accumulated_data["court_guid"]

        case_header = json_content.get("caseHeader", {})

        # Extract basic case info
        case_number = case_header.get("caseNumber", "")
        case_title = case_header.get("caseTitle", "")
        case_caption = case_header.get("caseCaption", "")
        case_classification = case_header.get("caseClassification")
        filed_date_str = case_header.get("filedDate", "")
        closed_flag = case_header.get("closedFlag", False)

        # Filter by case number if specified
        _, _, case_number_filter, _ = self._get_dockets_search_params()
        if case_number_filter and case_number != case_number_filter:
            return

        # Parse filed date
        date_filed = self._parse_date(filed_date_str)

        # Extract originating court info
        originating_court = None
        originating_court_number = None
        orig_cases = case_header.get("originatingCourtCases", [])
        if orig_cases:
            originating_court = orig_cases[0].get("originatingCourtName")
            originating_court_number = orig_cases[0].get(
                "originatingCaseNumber"
            )

        # Get court_id from guid
        court_id = self._get_court_id_from_guid(court_guid)
        if not court_id:
            return

        # Use case_caption if available, otherwise case_title
        case_name = case_caption if case_caption else case_title

        # Build the source URL
        source_url = (
            f"{API_CONFIG['portal_url']}/portal/court/{court_guid}"
            f"/case/{case_instance_uuid}"
        )

        # Create the docket object (will be completed with parties/entries)
        docket = AlaDocket(
            case_instance_uuid=case_instance_uuid,
            case_number=case_number,
            court_id=court_id,
            date_filed=date_filed,
            case_name=case_name,
            case_classification=case_classification,
            originating_court=originating_court,
            originating_court_number=originating_court_number,
            status="Closed" if closed_flag else "Open",
            court_guid=court_guid,
            source_url=source_url,
            parties=[],
            entries=[],
            oral_arguments=[],
        )

        # Fetch parties
        parties_url = (
            f"{API_CONFIG['base_url']}/courts/{court_guid}"
            f"/cms/cases/{case_instance_uuid}/parties"
            "?sort=orderBy,asc&sort=partyNumber,asc&size=100"
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=parties_url,
                headers={
                    "Accept": "application/json",
                },
            ),
            continuation=self.parse_case_parties,
            accumulated_data={
                "docket_data": docket.model_dump(mode="json"),
            },
        )

    @step(
        xsd="xsds/parse_case_parties.xsd",
        json_model="api.responses.CasePartiesResponse",
    )
    def parse_case_parties(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse case parties and fetch docket entries.

        API Response structure::

            {
                "_embedded": {
                    "results": [
                        {
                            "casePartyUUID": "...",
                            "partyType": "Party",
                            "partySubType": "Appellant",
                            "partyStatus": "Active",
                            "actor": {
                                "displayName": "John Doe",
                                "sortName": "Doe, John"
                            },
                            "legalRepresentations": [
                                {
                                    "actor": {
                                        "displayName": "Jane Attorney"
                                    },
                                    "primaryFlag": true
                                }
                            ],
                            "proSeFlag": false
                        }
                    ]
                }
            }
        """
        docket = AlaDocket.model_validate(accumulated_data["docket_data"])

        embedded = json_content.get("_embedded", {})
        results = embedded.get("results", [])

        parties = []
        for party_data in results:
            # Party info is nested under partyHeader
            party_header = party_data.get("partyHeader", {})
            party_type = party_header.get("partyType", "")
            party_subtype = party_header.get("partySubType", "")
            party_status = party_header.get("partyStatus", "")
            pro_se = party_data.get("proSeFlag", False)

            # Actor info is under partyHeader.partyActorInstance
            actor = party_header.get("partyActorInstance", {})
            display_name = actor.get("displayName", "")

            # Get legal representations (attorneys)
            attorneys = []
            legal_reps = party_data.get("legalRepresentations", [])
            for rep in legal_reps:
                # Attorney info is under attorneyPartyHeader.partyActorInstance
                attorney_header = rep.get("attorneyPartyHeader", {})
                rep_actor = attorney_header.get("partyActorInstance", {})
                attorney_name = rep_actor.get("displayName", "")
                is_primary = rep.get("primaryFlag", False)
                if attorney_name:
                    attorneys.append(
                        {
                            "name": attorney_name,
                            "is_primary": is_primary,
                        }
                    )

            party = {
                "name": display_name,
                "type": party_type,
                "role": party_subtype,
                "status": party_status,
                "pro_se": pro_se,
                "attorneys": attorneys,
            }
            parties.append(party)

        docket.parties = parties

        # Now fetch docket entries
        entries_url = (
            f"{API_CONFIG['base_url']}/courts/{docket.court_guid}"
            f"/cms/cases/{docket.case_instance_uuid}/docketentries"
            f"?page=0&size={self.DOCKETS_PAGE_SIZE}"
            "&sort=docketEntryHeader.filedDate,asc"
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=entries_url,
                headers={
                    "Accept": "application/json",
                },
            ),
            continuation=self.parse_docket_entries,
            accumulated_data={
                "docket_data": docket.model_dump(mode="json"),
            },
        )

    @step(
        xsd="xsds/parse_docket_entries.xsd",
        json_model="api.responses.DocketEntriesResponse",
    )
    def parse_docket_entries(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse docket entries and yield the complete docket.

        API Response structure::

            {
                "_embedded": {
                    "results": [
                        {
                            "docketEntryHeader": {
                                "docketEntryUUID": "...",
                                "docketEntryType": "Filing",
                                "docketEntrySubType": "Notice of Appeal",
                                "filedDate": "2023-11-09T14:15:00.000+00:00",
                                "description": "..."
                            },
                            "documentCount": 1
                        }
                    ]
                },
                "page": {...}
            }
        """
        docket = AlaDocket.model_validate(accumulated_data["docket_data"])

        embedded = json_content.get("_embedded", {})
        results = embedded.get("results", [])

        # Get pagination info
        page_info = json_content.get("page", {})
        current_page = page_info.get("number", 0)
        total_pages = page_info.get("totalPages", 1)

        entries = list(docket.entries)  # Copy existing entries

        for entry_data in results:
            header = entry_data.get("docketEntryHeader", {})
            entry_uuid = header.get("docketEntryUUID", "")
            entry_type = header.get("docketEntryType", "")
            entry_subtype = header.get("docketEntrySubType", "")
            filed_date_str = header.get("filedDate", "")
            # Field is named docketEntryDescription in the API
            description = header.get("docketEntryDescription", "")

            filed_date = self._parse_date(filed_date_str)

            entry = AlaDocketEntry(
                date_filed=filed_date,
                document_type=entry_type if entry_type else None,
                document_subtype=entry_subtype if entry_subtype else None,
                description=description if description else None,
                document_uuid=entry_uuid if entry_uuid else None,
            )
            entries.append(entry)

        docket.entries = entries

        # Check if we need to paginate
        if current_page + 1 < total_pages:
            entries_url = (
                f"{API_CONFIG['base_url']}/courts/{docket.court_guid}"
                f"/cms/cases/{docket.case_instance_uuid}/docketentries"
                f"?page={current_page + 1}&size={self.DOCKETS_PAGE_SIZE}"
                "&sort=docketEntryHeader.filedDate,asc"
            )

            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=entries_url,
                    headers={
                        "Accept": "application/json",
                    },
                ),
                continuation=self.parse_docket_entries,
                accumulated_data={
                    "docket_data": docket.model_dump(mode="json"),
                },
            )
        else:
            # All entries fetched, yield the complete docket
            yield ParsedData(data=docket)
