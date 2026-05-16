"""Arizona appellate-courts scraper (Supreme + Court of Appeals Div. 1).

Scrapes active case-list pages and three index pages (Lower Court, Party,
Attorney) from the AppellaDockets system at apps.azcourts.gov.

Both supported courts (``ariz`` and ``arizctapp``) sit on the same backend
and share the same HTML row format. Each entry takes a ``court_id``
parameter and dispatches to the matching site URLs.

Closed-case docket PDFs are deleted from the public site 15 days after the
case closes — see DESIGN.md.

Flow per court:
    active_updated_after(CourtCutoff) ─┐
                                       ├─> parse_case_list_update ─> archive PDF
    active_all(CourtParam) ────────────┴─> parse_case_list_full   ─> archive PDF
    lower_court_index(CourtParam) ─> parse_lower_court_index
    party_index(CourtParam)       ─> parse_party_index
    attorney_index(CourtParam)    ─> parse_attorney_index
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.exceptions import ScraperAssumptionException
from jkent.common.page_element import PageElement
from jkent.data_types import (
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
    COURTS,
    AzAppAttorneyCase,
    AzAppDocket,
    AzAppDocument,
    AzAppLowerCourtCase,
    AzAppPartyCase,
    CourtCutoff,
    CourtParam,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://apps.azcourts.gov/aacc/appella/"

# Hidden-cell text format: "M/D/YYYY HH:MM:SS\<COURT>\<TYPE>\<FILE>.PDF".
# Extract the timestamp prefix (left of the first backslash).
_TIMESTAMP_PATH_RE = re.compile(
    r"^(?P<ts>\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2})\\(?P<path>.+)$"
)
# Match attorney bracket suffix: "[AZ-9001]", "[AZ]", "[OH]", etc.
# Captures (jurisdiction, optional number).
_BAR_BRACKET_RE = re.compile(
    r"\[\s*(?P<juris>[A-Za-z]+)\s*(?:-?\s*(?P<num>\d+))?\s*\]"
)
_PDF_HREF_RE = re.compile(r"\.pdf$", re.I)


def _site_id(court_id: str) -> str:
    """Resolve a courts-db ``court_id`` to its AppellaDockets site code."""
    try:
        return COURTS[court_id]["site_id"]
    except KeyError as exc:
        raise ScraperAssumptionException(
            f"Unsupported court_id {court_id!r}; known: {sorted(COURTS)!r}"
        ) from exc


def _case_list_url(court_id: str, case_type: str, *, by_update: bool) -> str:
    """Build a case-type list URL.

    The ``_update`` variant is sorted by Last Updated descending; the
    canonical variant is sorted by case number ascending.
    """
    site = _site_id(court_id)
    suffix = "_update" if by_update else ""
    return f"{BASE_URL}stage_{site}_{case_type}{suffix}.htm"


def _index_url(court_id: str, kind: str) -> str:
    """Build an index page URL.

    ``kind`` is one of ``lower_court``, ``party``, ``attorney`` —
    matching the three iframe-embedded indices on each court's portal.
    """
    site = _site_id(court_id)
    paths = {
        "lower_court": f"000_{site}_LOWERCOURT_INDEX.HTM",
        "party": f"000_{site}_party_index.HTM",
        "attorney": f"000_{site}_ATTY_INDEX.HTM",
    }
    return BASE_URL + paths[kind]


class ArizonaAppellateScraper(
    BaseScraper[
        AzAppDocket
        | AzAppDocument
        | AzAppLowerCourtCase
        | AzAppPartyCase
        | AzAppAttorneyCase
    ],
):
    """Scraper for the Arizona Supreme Court and Court of Appeals (Div. 1).

    See ``DESIGN.md`` in this directory for site analysis. Each entry
    point takes a ``court_id`` (``ariz`` or ``arizctapp``).
    """

    court_ids: ClassVar[set[str]] = set(COURTS)
    court_url: ClassVar[str] = "https://www.azcourts.gov/appellatecourtcases/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-02"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _normalise_pdf_href(href: str) -> str:
        """Convert backslash-style hrefs to a clean absolute URL.

        AppellaDockets emits Windows paths (``ASC\\CR\\CR260127.PDF``).
        The server accepts backslashes verbatim, but we normalise to
        forward slashes so the URLs round-trip cleanly through dedup
        keys, logging, and any downstream consumer.
        """
        clean = href.replace("\\", "/").lstrip("/")
        return BASE_URL + clean

    @staticmethod
    def _parse_timestamp(raw: str) -> datetime | None:
        """Parse the M/D/YYYY HH:MM:SS hidden timestamp."""
        try:
            return datetime.strptime(raw.strip(), "%m/%d/%Y %H:%M:%S")
        except ValueError:
            return None

    @staticmethod
    def _safe_text(element: PageElement) -> str:
        try:
            return element.text_content().strip()
        except Exception:
            return ""

    def _extract_row_pdf_link(
        self, row: PageElement
    ) -> tuple[str, str] | None:
        """Return ``(docket_number, pdf_url)`` for a case row, or ``None``.

        The PDF anchor is in column 0 on case-type pages, but in column 1
        on the index pages (lower-court / party / attorney). We match the
        anchor by href shape rather than position.

        State Bar (SB) anchors include a ``<small> [Ending]</small>``
        status badge inside the anchor; we use the anchor's first text
        node so ``docket_number`` doesn't pick up that badge.
        """
        anchors = row.query_xpath(".//a[@href]", "row anchors", min_count=0)
        for a in anchors:
            href = a.get_attribute("href") or ""
            if not _PDF_HREF_RE.search(href):
                continue
            leading = a.query_xpath_strings(
                "./text()[1]",
                "anchor leading text",
                min_count=0,
                max_count=1,
            )
            if leading and leading[0].strip():
                docket_number = leading[0].strip()
            else:
                docket_number = self._safe_text(a)
            if not docket_number:
                continue
            return docket_number, self._normalise_pdf_href(href)
        return None

    def _extract_row_timestamp_and_path(
        self, row: PageElement
    ) -> tuple[datetime | None, str | None]:
        """Pull the (timestamp, path) pair out of a row's hidden cells.

        Hidden cell format: ``M/D/YYYY HH:MM:SS\\<COURT>\\<TYPE>\\<FILE>.PDF``.
        Both the canonical and ``_update`` variants emit it.
        """
        hidden_cells = row.query_xpath(
            ".//td[contains(@style, 'visibility:hidden')]",
            "hidden cells",
            min_count=0,
        )
        for cell in hidden_cells:
            text = self._safe_text(cell)
            match = _TIMESTAMP_PATH_RE.match(text)
            if match:
                ts = self._parse_timestamp(match.group("ts"))
                return ts, match.group("path")
        return None, None

    def _yield_pdf_archive(
        self,
        pdf_url: str,
        docket_number: str,
        court_id: str,
        source: str,
    ) -> Request:
        """Build an archive request for a docket PDF.

        Dedup is left to kent's URL-based default — same PDF URL referenced
        from multiple indices (case-list / lower-court / party / attorney)
        is fetched only once.
        """
        return Request(
            archive=True,
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=pdf_url,
            ),
            continuation=self.handle_pdf_archive,
            expected_type="pdf",
            accumulated_data={
                "court_id": court_id,
                "docket_number": docket_number,
                "document_url": pdf_url,
                "source": source,
            },
        )

    @staticmethod
    def _validate_court(court_id: str) -> None:
        if court_id not in COURTS:
            raise ScraperAssumptionException(
                f"Unsupported court_id {court_id!r}; known: {sorted(COURTS)!r}"
            )

    # =========================================================================
    # Entry: incremental by Last Updated
    # =========================================================================

    @entry(AzAppDocket)
    def active_updated_after(
        self, params: CourtCutoff
    ) -> Generator[Request, None, None]:
        """Fetch every active docket for ``params.court_id`` updated
        strictly after ``params.cutoff``.

        Walks each case-type ``_update`` page (sorted by Last Updated
        DESC) and short-circuits once it sees a row older than the
        cutoff.
        """
        self._validate_court(params.court_id)
        for case_type in COURTS[params.court_id]["case_types"]:
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=_case_list_url(
                        params.court_id, case_type, by_update=True
                    ),
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_case_list_update,
                accumulated_data={
                    "court_id": params.court_id,
                    "case_type": case_type,
                    "cutoff": params.cutoff.isoformat(),
                },
            )

    @entry(AzAppDocket)
    def active_all(self, params: CourtParam) -> Generator[Request, None, None]:
        """Fetch every active docket for ``params.court_id``.

        Walks every case-type ``stage_<COURT>_<TYPE>.htm`` page
        end-to-end. Use this for an initial backfill or anytime a full
        snapshot is wanted; for incremental nightly runs, prefer
        ``active_updated_after``.
        """
        self._validate_court(params.court_id)
        for case_type in COURTS[params.court_id]["case_types"]:
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=_case_list_url(
                        params.court_id, case_type, by_update=False
                    ),
                    headers={"Accept": "text/html"},
                ),
                continuation=self.parse_case_list_full,
                accumulated_data={
                    "court_id": params.court_id,
                    "case_type": case_type,
                },
            )

    @entry(AzAppLowerCourtCase)
    def lower_court_index(
        self, params: CourtParam
    ) -> Generator[Request, None, None]:
        """Fetch and parse the Lower Court Index for ``params.court_id``."""
        self._validate_court(params.court_id)
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=_index_url(params.court_id, "lower_court"),
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_lower_court_index,
            accumulated_data={"court_id": params.court_id},
        )

    @entry(AzAppPartyCase)
    def party_index(
        self, params: CourtParam
    ) -> Generator[Request, None, None]:
        """Fetch and parse the Party Index for ``params.court_id``."""
        self._validate_court(params.court_id)
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=_index_url(params.court_id, "party"),
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_party_index,
            accumulated_data={"court_id": params.court_id},
        )

    @entry(AzAppAttorneyCase)
    def attorney_index(
        self, params: CourtParam
    ) -> Generator[Request, None, None]:
        """Fetch and parse the Attorney Index for ``params.court_id``."""
        self._validate_court(params.court_id)
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=_index_url(params.court_id, "attorney"),
                headers={"Accept": "text/html"},
            ),
            continuation=self.parse_attorney_index,
            accumulated_data={"court_id": params.court_id},
        )

    # =========================================================================
    # Step: parse case-type list (incremental)
    # =========================================================================

    @step()
    def parse_case_list_update(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AzAppDocket | AzAppDocument], None, None]:
        """Parse a ``stage_<COURT>_<TYPE>_update.htm`` page top-down.

        Stops as soon as a row's ``last_updated`` is on or before
        ``accumulated_data['cutoff']``.
        """
        court_id = accumulated_data["court_id"]
        case_type = accumulated_data["case_type"]
        cutoff_dt = datetime.fromisoformat(accumulated_data["cutoff"])

        for row in self._iter_pdf_rows(page):
            extracted = self._extract_row_pdf_link(row)
            if extracted is None:
                continue
            docket_number, pdf_url = extracted
            ts, _ = self._extract_row_timestamp_and_path(row)
            if ts is None:
                # Without a timestamp we can't reason about ordering;
                # play it safe and yield the row, but don't stop the walk.
                yield from self._emit_docket_row(
                    row,
                    court_id=court_id,
                    case_type=case_type,
                    docket_number=docket_number,
                    pdf_url=pdf_url,
                    last_updated=None,
                    source_url=response.url,
                    archive_source="case_list",
                )
                continue
            if ts <= cutoff_dt:
                # Rows are sorted DESC; everything after this is older.
                break
            yield from self._emit_docket_row(
                row,
                court_id=court_id,
                case_type=case_type,
                docket_number=docket_number,
                pdf_url=pdf_url,
                last_updated=ts,
                source_url=response.url,
                archive_source="case_list",
            )

    @step()
    def parse_case_list_full(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AzAppDocket | AzAppDocument], None, None]:
        """Parse a ``stage_<COURT>_<TYPE>.htm`` page in full."""
        court_id = accumulated_data["court_id"]
        case_type = accumulated_data["case_type"]
        for row in self._iter_pdf_rows(page):
            extracted = self._extract_row_pdf_link(row)
            if extracted is None:
                continue
            docket_number, pdf_url = extracted
            ts, _ = self._extract_row_timestamp_and_path(row)
            yield from self._emit_docket_row(
                row,
                court_id=court_id,
                case_type=case_type,
                docket_number=docket_number,
                pdf_url=pdf_url,
                last_updated=ts,
                source_url=response.url,
                archive_source="case_list",
            )

    def _iter_pdf_rows(self, page: PageElement) -> list[PageElement]:
        """Return all ``<tr>`` rows containing a PDF link.

        The anchor may be in column 0 (case-type pages) or column 1 (index
        pages), so we match by href suffix anywhere in the row.
        """
        return page.query_xpath(
            "//tr[.//a[contains(translate(@href,"
            " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            " 'abcdefghijklmnopqrstuvwxyz'), '.pdf')]]",
            "case rows",
            min_count=0,
        )

    def _emit_docket_row(
        self,
        row: PageElement,
        *,
        court_id: str,
        case_type: str,
        docket_number: str,
        pdf_url: str,
        last_updated: datetime | None,
        source_url: str,
        archive_source: str,
    ) -> Generator[ScraperYield[AzAppDocket | AzAppDocument], None, None]:
        """Yield the docket record + an archive request for the PDF."""
        cells = row.query_xpath(".//td", "row cells", min_count=1)
        case_name = self._safe_text(cells[1]) if len(cells) > 1 else ""
        docket = AzAppDocket(
            docket_number=docket_number,
            court_id=court_id,
            case_type=case_type,
            case_name=case_name,
            last_updated=last_updated,
            pdf_url=pdf_url,
            source_url=source_url,
        )
        yield ParsedData(data=docket)
        yield self._yield_pdf_archive(
            pdf_url,
            docket_number,
            court_id=court_id,
            source=archive_source,
        )

    # =========================================================================
    # Step: parse Lower Court Index
    # =========================================================================

    @step()
    def parse_lower_court_index(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[AzAppLowerCourtCase | AzAppDocument], None, None
    ]:
        """Parse the Lower Court Index, tracking section headings."""
        court_id = accumulated_data["court_id"]
        all_rows = page.query_xpath("//tr", "rows", min_count=1)

        current_court_name: str | None = None
        current_court_anchor: str | None = None

        for row in all_rows:
            heading = self._extract_lower_court_heading(row)
            if heading is not None:
                current_court_name, current_court_anchor = heading
                continue

            extracted = self._extract_row_pdf_link(row)
            if extracted is None:
                continue
            our_docket, pdf_url = extracted
            cells = row.query_xpath(".//td", "row cells", min_count=3)
            if len(cells) < 3:
                continue
            lower_case_no = self._safe_text(cells[0])
            case_title = self._safe_text(cells[2])
            if not current_court_name:
                # No heading yet; skip until we see one. The page should
                # always emit a heading before its rows.
                continue

            yield ParsedData(
                data=AzAppLowerCourtCase(
                    court_id=court_id,
                    lower_court_case_number=lower_case_no,
                    lower_court_name=current_court_name,
                    lower_court_anchor=current_court_anchor,
                    our_docket_number=our_docket,
                    our_case_pdf_url=pdf_url,
                    case_title=case_title,
                )
            )
            yield self._yield_pdf_archive(
                pdf_url,
                our_docket,
                court_id=court_id,
                source="lower_court_index",
            )

    @staticmethod
    def _extract_lower_court_heading(
        row: PageElement,
    ) -> tuple[str, str] | None:
        """If this row is a specific-court heading, return (name, anchor).

        Heading rows look like::

            <TR>
              <TD ...><b>COURT OF APPEALS, DIVISION ONE</b></TD>
              <TD ...><b><a name="1 CA">1 CA</a></b></TD>
              ...
            </TR>

        ASC's index also has category-marker rows whose anchors are pure
        digits (``150`` for "Appellate Court", ``200`` for "Superior
        Court", ``500`` for "Other Court, Board, or Commission"). These
        precede the specific courts in their group; we skip them so that
        data rows under e.g. "MARICOPA COUNTY SUPERIOR COURT" are not
        attributed to the generic "Superior Court" parent. COA1's index
        has fewer category markers but the rule is the same.
        """
        anchors = row.query_xpath(
            ".//a[@name]", "heading anchors", min_count=0
        )
        named = [a for a in anchors if (a.get_attribute("name") or "").strip()]
        if not named:
            return None
        anchor_name = (named[0].get_attribute("name") or "").strip()
        if not anchor_name or anchor_name.isdigit():
            # Category marker (e.g. "150", "200", "500"); not a real court.
            return None
        bold_texts: list[str] = []
        for b in row.query_xpath(".//b", "bold spans", min_count=0):
            text = b.text_content().strip()
            if text and text != anchor_name:
                bold_texts.append(text)
        if not bold_texts:
            return None
        return bold_texts[0], anchor_name

    # =========================================================================
    # Step: parse Party Index
    # =========================================================================

    @step()
    def parse_party_index(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AzAppPartyCase | AzAppDocument], None, None]:
        """Parse the Party Index — flat rows; letter-section headers ignored."""
        court_id = accumulated_data["court_id"]
        for row in self._iter_pdf_rows(page):
            extracted = self._extract_row_pdf_link(row)
            if extracted is None:
                continue
            docket_number, pdf_url = extracted
            cells = row.query_xpath(".//td", "row cells", min_count=3)
            if len(cells) < 3:
                continue
            party_name = self._safe_text(cells[0])
            case_title = self._safe_text(cells[2])
            if not party_name:
                continue
            yield ParsedData(
                data=AzAppPartyCase(
                    court_id=court_id,
                    party_name=party_name,
                    docket_number=docket_number,
                    case_pdf_url=pdf_url,
                    case_title=case_title,
                )
            )
            yield self._yield_pdf_archive(
                pdf_url,
                docket_number,
                court_id=court_id,
                source="party_index",
            )

    # =========================================================================
    # Step: parse Attorney Index
    # =========================================================================

    @step()
    def parse_attorney_index(
        self,
        page: PageElement,
        accumulated_data: dict,
    ) -> Generator[
        ScraperYield[AzAppAttorneyCase | AzAppDocument], None, None
    ]:
        """Parse the Attorney Index, splitting bar number from name.

        Each cell looks like ``ABNEY, DAVID <SMALL ...>[AZ-9001]</small>``
        (or `[OH]` / `[CA]` / `[VA]` for out-of-state counsel). We pull
        the jurisdiction and any digits out of the bracket and strip the
        bracket out of the name.
        """
        court_id = accumulated_data["court_id"]
        for row in self._iter_pdf_rows(page):
            extracted = self._extract_row_pdf_link(row)
            if extracted is None:
                continue
            docket_number, pdf_url = extracted
            cells = row.query_xpath(".//td", "row cells", min_count=3)
            if len(cells) < 3:
                continue

            full_text = self._safe_text(cells[0])
            bar_match = _BAR_BRACKET_RE.search(full_text)
            bar_number = bar_match.group("num") if bar_match else None
            bar_jurisdiction = (
                bar_match.group("juris").upper() if bar_match else None
            )
            attorney_name = (
                _BAR_BRACKET_RE.sub("", full_text).strip().rstrip(",")
            ).strip()

            case_title = self._safe_text(cells[2])

            if not attorney_name:
                continue

            yield ParsedData(
                data=AzAppAttorneyCase(
                    court_id=court_id,
                    attorney_name=attorney_name,
                    bar_number=bar_number,
                    bar_jurisdiction=bar_jurisdiction,
                    docket_number=docket_number,
                    case_pdf_url=pdf_url,
                    case_title=case_title,
                )
            )
            yield self._yield_pdf_archive(
                pdf_url,
                docket_number,
                court_id=court_id,
                source="attorney_index",
            )

    # =========================================================================
    # Step: archive a PDF
    # =========================================================================

    @step()
    def handle_pdf_archive(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[AzAppDocument], None, None]:
        """Emit an ``AzAppDocument`` record for an archived PDF."""
        yield ParsedData(
            data=AzAppDocument(
                court_id=accumulated_data["court_id"],
                docket_number=accumulated_data["docket_number"],
                document_url=accumulated_data["document_url"],
                local_path=local_filepath,
                source=accumulated_data.get("source"),
            )
        )
