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

All entries take ``court_ids: set[str]`` and a ``DateRange`` (seeded by the
driver). The docket and event flows delegate to ``TRPortalMixin``; the opinion
(publications) and historical flows are Alabama-specific.

Opinions Flow (opinions_by_bulk):
  1. opinions_by_bulk -> publications list request per court (bulk; the endpoint
     has no server-side date filter)
  2. parse_publications_list -> delegates to the mixin, which paginates and
     applies the client-side date-range filter, yielding detail requests
  3. parse_publication_detail -> fetches full data from detail endpoint
     - Parses items, extracts lower court info and "In re:" case names
     - Opinions/Decisions (documentName) -> AlaOpinionCluster, yields archive
     - Orders/Special Writings/etc -> AlaOrder, yields archive
  4. handle_opinion_download -> stores local paths, yields final AlaOpinionClusters
  5. handle_order_download -> stores local paths, yields final AlaOrders

Historical Opinions Flow (historical_opinions_by_bulk):
  1. historical_opinions_by_bulk -> HTML requests to judicial.alabama.gov decisions pages
  2. parse_historical_decisions_list -> parses HTML table, filters by date range,
     yields archive requests for PDFs
  3. handle_historical_pdf_download -> stores local paths, yields AlaHistoricalReleaseList

Dockets Flow (dockets_by_filing_date):
  1. dockets_by_filing_date -> date range search requests
  2. parse_dockets_search -> handles 10,000 result limit by splitting date ranges
     and drops detail requests for courts outside court_ids
  3. parse_case_detail -> parses case header, yields party fetch request
  4. parse_case_parties -> parses parties, yields docket entries fetch request
  5. parse_docket_entries -> parses docket entries, chains into documents fetch
  6. parse_documents_list -> queues per-document archive downloads, yields AlaDocket
  7. parse_document_download -> emits an AlaDocument per archived file

Oral Arguments Flow (oral_arguments_by_argument_date):
  1. oral_arguments_by_argument_date -> events API search
  2. parse_events_list -> filters the all-courts feed by court_ids/date range,
     yields event-hearing requests (delegates to the mixin)
  3. parse_event_hearings -> parses cases, yields AlaOralArgument objects

Design decisions:
- Uses JSON API endpoints for current opinions, dockets, and oral arguments
- Uses plain-HTML scraping for historical opinions (pre-May 2023)
- Opinions use two-step fetch: list endpoint for UUIDs, detail endpoint for full data
- Splits items by documentName: Opinion/Decision -> AlaOpinionCluster, else -> AlaOrder
- Handles "In re:" case name extraction from parenthetical
- Archives opinion/order PDFs via Request(archive=True)
- Extracts lower court info from case title parenthetical
- Handles "Per Curiam" and "On Rehearing" designations
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urlparse

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import DateRange
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    XPath,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.tr.scraper import TRPortalMixin

from .models import (
    API_CONFIG,
    COURT_CONFIG,
    AlaDocket,
    AlaDocketEntry,
    AlaDocument,
    AlaHistoricalReleaseList,
    AlaOpinion,
    AlaOpinionCluster,
    AlaOralArgument,
    AlaOrder,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


class AlabamaScraper(
    TRPortalMixin,
    BaseScraper[
        AlaOpinionCluster
        | AlaOrder
        | AlaOralArgument
        | AlaDocket
        | AlaDocument
        | AlaHistoricalReleaseList
    ],
):
    """Unified scraper for Alabama appellate court data.

    Scrapes opinions, oral argument information, and docket information
    from Alabama courts.

    Supports Alabama Supreme Court (ala), Court of Civil Appeals (alactapp),
    and Court of Criminal Appeals (alacrimapp).

    Entry points (driver seeds ``court_ids`` and the date range):
        - ``opinions_by_bulk(court_ids, date_range)`` — opinion/order release
          lists from the publications API (bulk pull, client-side date filter).
        - ``historical_opinions_by_bulk(court_ids, date_range)`` — pre-May-2023
          weekly release-list PDFs from judicial.alabama.gov / acis.alabama.gov.
        - ``oral_arguments_by_argument_date(court_ids, date_range)`` — calendar
          events scheduled in the window.
        - ``dockets_by_filing_date(court_ids, date_range)`` — cases filed in the
          window, server-side filtered by filed date.
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
    version: ClassVar[str] = "2026-06-25"
    last_verified: ClassVar[str] = "2026-01-21"
    requires_auth: ClassVar[bool] = False
    # Pure JSON REST API (current data) plus plain-HTML release-list pages
    # (historical) — no browser/JS needed.
    driver_requirements: ClassVar[list[DriverRequirement]] = []

    rate_limits: ClassVar[list[Rate] | None] = [Rate(4, Duration.SECOND)]

    # === TR Portal configuration (consumed by TRPortalMixin) ===
    TR_API_BASE_URL: ClassVar[str] = API_CONFIG["base_url"]
    TR_PORTAL_URL: ClassVar[str] = API_CONFIG["portal_url"]
    TR_COURT_CONFIG: ClassVar[dict] = COURT_CONFIG

    # === Model classes (consumed by TRPortalMixin) ===
    DOCKET_CLASS: ClassVar[type] = AlaDocket
    DOCKET_ENTRY_CLASS: ClassVar[type] = AlaDocketEntry
    DOCUMENT_CLASS: ClassVar[type] = AlaDocument
    ORAL_ARGUMENT_CLASS: ClassVar[type] = AlaOralArgument

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

    # Pattern to extract case name from "In re:" parenthetical
    # For cases like: "Ex parte Doe ... (In re: Jane Doe v. John Doe)"
    IN_RE_PATTERN = re.compile(r"\((In re: .*?)\)")

    # Document names that represent opinions (vs orders)
    OPINION_DOCUMENT_NAMES: ClassVar[set[str]] = {"Opinion", "Decision"}

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
    # Opinions Entry Point & Scraping Steps
    # =========================================================================

    @entry(AlaOpinionCluster)
    def opinions_by_bulk(
        self,
        court_ids: set[str],
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Enumerate opinion release lists (publications) for ``court_ids``.

        The publications endpoint has no server-side date filter, so this is
        a bulk pull per court that ``parse_publications_list`` paginates and
        filters client-side to ``date_range`` (results are sorted by
        publication date descending).
        """
        target_courts = self._tr_get_target_courts(court_ids)
        yield from self._tr_yield_publications_request(
            date_range.start, date_range.end, target_courts
        )

    @step(priority=4)
    def parse_publications_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Paginate the publications list and yield publication-detail requests.

        Delegates to the shared TRPortalMixin handler, which applies the
        client-side date-range filter and chains detail requests into
        ``parse_publication_detail``.
        """
        yield from self._tr_handle_publications_list(
            json_content, accumulated_data
        )

    @step(priority=3)
    def parse_publication_detail(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse detailed publication data and yield archive requests.

        Fetches the full publication from the detail endpoint, which
        includes titles, documents, decisions, and authoring information.
        Splits items into AlaOpinionCluster (Opinion/Decision documents)
        and AlaOrder (all other document types).

        Detail Response structure::

            {
                "publicationNumber": "SC-RELEASE-2023-11-09",
                "publicationDate": "2023-11-09T14:20:37.335+00:00",
                "publicationItems": [
                    {
                        "caseNumber": "SC-2024-0492",
                        "groupName": "Wise, J.",
                        "title": "Case Name (Appeal from Circuit Court: CV-123)",
                        "decision": "Affirmed.",
                        "documents": [
                            {
                                "documentLinkUUID": "...",
                                "documentName": "Opinion"
                            }
                        ]
                    }
                ]
            }
        """
        court_id: str = accumulated_data.get("court_id", "")
        court_guid: str = accumulated_data.get("court_guid", "")

        publication_number = json_content.get("publicationNumber", "")
        publication_date_str = json_content.get("publicationDate", "")
        date_filed = self._tr_parse_date(publication_date_str)

        if not date_filed:
            return

        publication_items = json_content.get("publicationItems", [])

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
            document_name = documents[0].get("documentName", "")

            doc_uuid = documents[0].get("documentLinkUUID", "")
            if not doc_uuid:
                continue

            # Extract lower court info from title
            lower_court = ""
            lower_court_number = ""
            match = self.LOWER_COURT_PATTERN.search(title)
            if match:
                lower_court = match.group("lower_court").strip()
                lower_court_number = match.group("lower_court_number").strip()
                # Remove the parenthetical from the title
                title = title[: match.start()].rstrip()

            # For "In re:" cases, extract the actual case name
            in_re_match = self.IN_RE_PATTERN.search(title)
            if in_re_match:
                title = in_re_match.group(1).strip()

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
            download_url = (
                f"{API_CONFIG['base_url']}/courts/{court_guid}"
                f"/cms/case/{case_instance_uuid}"
                f"/docketentrydocuments/{doc_uuid}"
            )

            # Branch: Opinion/Decision → AlaOpinionCluster, else → AlaOrder
            if document_name in self.OPINION_DOCUMENT_NAMES:
                cluster = AlaOpinionCluster(
                    docket_number=case_number,
                    court=court_id,
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
                    publication_uuid=None,
                    publication_item_uuid=publication_item_uuid,
                    case_instance_uuid=case_instance_uuid,
                    source_url=None,
                    opinions=[
                        AlaOpinion(
                            download_url=download_url,
                            type="majority",
                            authoring_judge=judge if judge else None,
                            decision_text=decision if decision else None,
                        )
                    ],
                )

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
            else:
                order = AlaOrder(
                    docket_number=case_number,
                    court=court_id,
                    date_filed=date_filed,
                    case_name=title,
                    document_name=document_name if document_name else None,
                    decision_text=decision if decision else None,
                    publication_number=publication_number,
                    publication_uuid=None,
                    publication_item_uuid=publication_item_uuid,
                    case_instance_uuid=case_instance_uuid,
                    authoring_judge=judge if judge else None,
                    per_curiam=per_curiam,
                    on_rehearing=on_rehearing,
                    lower_court=lower_court if lower_court else None,
                    lower_court_number=lower_court_number
                    if lower_court_number
                    else None,
                    download_url=download_url,
                    source_url=None,
                )

                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=download_url,
                    ),
                    continuation=self.handle_order_download,
                    accumulated_data={
                        "order": order.model_dump(mode="json"),
                    },
                )

    @step(priority=2)
    def handle_opinion_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
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

    @step(priority=2)
    def handle_order_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Handle the downloaded order PDF and yield the final order.

        Args:
            local_filepath: Local path where the PDF was archived
            accumulated_data: Contains order data
        """
        order_data = accumulated_data.get("order")
        if not order_data:
            return

        order = AlaOrder.model_validate(order_data)
        order.local_path = local_filepath

        yield ParsedData(data=order)

    # =========================================================================
    # Historical Opinions Entry Point & Scraping Steps (pre-May 2023)
    # =========================================================================

    @entry(AlaHistoricalReleaseList)
    def historical_opinions_by_bulk(
        self,
        court_ids: set[str],
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Enumerate pre-May-2023 weekly release-list PDFs for ``court_ids``.

        Fetches the decisions listing pages from judicial.alabama.gov for
        each court. These plain-HTML pages link to weekly PDF release lists
        on acis.alabama.gov; ``parse_historical_decisions_list`` filters them
        client-side to ``date_range``.
        """
        target_courts = self._tr_get_target_courts(court_ids)

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
                    "date_gte": date_range.start.isoformat(),
                    "date_lte": date_range.end.isoformat(),
                },
                deduplication_key=f"historical_decisions:{court_id}",
            )

    @step(priority=3)
    def parse_historical_decisions_list(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
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

        # Date filter window, seeded by the entry from its date_range arg.
        date_gte_str = accumulated_data.get("date_gte")
        date_lte_str = accumulated_data.get("date_lte")
        date_gte = date.fromisoformat(date_gte_str) if date_gte_str else None
        date_lte = date.fromisoformat(date_lte_str) if date_lte_str else None

        # Find all links to acis.alabama.gov release list PDFs
        # find_links resolves URLs automatically
        links = page.find_links(
            XPath("//a[contains(@href, 'acis.alabama.gov/displaydocs2.cfm')]"),
            "historical decisions PDF links",
            min_count=0,
        )

        for link in links:
            pdf_url = link.url
            link_text = link.text

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
            parsed = urlparse(pdf_url)
            params = parse_qs(parsed.query)
            acis_doc_no = params.get("no", [""])[0]
            acis_event = params.get("event", [""])[0]

            # Create release list object
            release_list = AlaHistoricalReleaseList(
                court=court_id,
                date_filed=release_date,
                case_name=link_text,
                pdf_url=pdf_url,
                source_url=response.url,
                acis_doc_no=acis_doc_no.strip() if acis_doc_no else None,
                acis_event=acis_event.strip() if acis_event else None,
            )

            # Yield archive request to download the PDF
            # verify=False: acis.alabama.gov has a cert issued to
            # www.acis.alabama.gov with no SAN for the bare domain
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=pdf_url,
                    verify=False,
                ),
                continuation=self.handle_historical_pdf_download,
                accumulated_data={
                    "release_list": release_list.model_dump(mode="json"),
                },
                deduplication_key=(
                    f"{court_id}-historical-{release_date.isoformat()}"
                ),
            )

    @step(priority=2)
    def handle_historical_pdf_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
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
    def oral_arguments_by_argument_date(
        self,
        court_ids: set[str],
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Enumerate oral arguments scheduled within ``date_range``.

        The events endpoint searches server-side by start (argument) date;
        ``parse_events_list`` filters the all-courts feed down to
        ``court_ids``.
        """
        target_courts = self._tr_get_target_courts(court_ids)
        yield from self._tr_yield_events_request(
            date_range.start, date_range.end, target_courts
        )

    @step(priority=3)
    def parse_events_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse the events list and yield event-hearing requests."""
        yield from self._tr_handle_events_list(json_content, accumulated_data)

    @step(priority=2)
    def parse_event_hearings(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse event hearings and yield AlaOralArgument objects."""
        yield from self._tr_handle_event_hearings(
            json_content, accumulated_data
        )

    # =========================================================================
    # Dockets Entry Point & Scraping Steps
    # =========================================================================

    @entry(AlaDocket)
    def dockets_by_filing_date(
        self,
        court_ids: set[str],
        date_range: DateRange,
    ) -> Generator[Request, None, None]:
        """Enumerate dockets filed within ``date_range`` for ``court_ids``.

        The ``cms/cases`` endpoint searches server-side by filed date;
        ``parse_dockets_search`` splits the range when a window exceeds the
        10,000-result cap and drops detail requests for courts outside the
        requested set.
        """
        target_courts = self._tr_get_target_courts(court_ids)
        yield from self._tr_yield_dockets_search_request(
            date_range.start, date_range.end, target_courts
        )

    @step(priority=6)
    def parse_dockets_search(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
            | AlaOralArgument
            | AlaDocket
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse the case search API response.

        Delegates to the shared TRPortalMixin handler, which paginates,
        splits the date range on the 10,000-result cap, and yields
        case-detail requests.
        """
        yield from self._tr_handle_dockets_search(
            json_content, accumulated_data
        )

    @step(priority=5)
    def parse_case_detail(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
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
        yield from self._tr_handle_case_detail(json_content, accumulated_data)

    @step(priority=4)
    def parse_case_parties(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
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
        yield from self._tr_handle_case_parties(json_content, accumulated_data)

    @step(priority=3)
    def parse_docket_entries(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
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
        yield from self._tr_handle_docket_entries(
            json_content, accumulated_data
        )

    @step(priority=2)
    def parse_documents_list(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[
            AlaOpinionCluster
            | AlaOrder
            | AlaOralArgument
            | AlaDocket
            | AlaDocument
            | AlaHistoricalReleaseList
        ],
        None,
        None,
    ]:
        """Parse the documents-access listing and queue document downloads.

        Yielded after docket entries are fully fetched. The mixin emits
        one archive Request per document and yields the assembled
        AlaDocket when the documents list is exhausted.
        """
        yield from self._tr_handle_documents_list(
            json_content, accumulated_data
        )

    @step(priority=2)
    def parse_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AlaDocument], None, None]:
        """Emit an AlaDocument record for an archived file.

        Alabama appellate documents are paywalled, so ``local_filepath``
        will typically be ``None``; metadata is still captured.
        """
        yield from self._tr_handle_document_download(
            local_filepath, accumulated_data
        )
