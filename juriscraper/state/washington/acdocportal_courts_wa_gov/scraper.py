"""Washington Appellate Courts docket scraper (ACDocPortal).

Scrapes dockets from the Washington State Appellate Courts Public Case
Document Search portal:

- Supreme Court:      https://acdocportal.courts.wa.gov/PublicAccess/search_sc.html
- Court of Appeals:   https://acdocportal.courts.wa.gov/PublicAccess/search_ca.html

Both search pages are reCAPTCHA-gated in a browser, but the underlying
``/PublicAccess/api/CustomQuery/KeywordSearch`` and
``/PublicAccess/api/Document/<id>/`` endpoints are open to direct HTTP
clients — no captcha, no session cookies required.  That lets us
implement the scraper purely as a JSON API consumer; it runs under plain
HTTP (``driver_requirements = []``).

Entry point (§4): one speculative docket-number probe addressed by court
id. The driver dispatches a speculative entry with ONLY its speculative
param, so the target court rides in the ``CourtRange`` (seed once per
court). See ``SCRAPER_STANDARDS.md`` §4 ("Multi-court speculative
entries").

This is a JSON API, so there is no ``parsers/`` package (per
``SCRAPER_STANDARDS.md`` §9 / §3.5): the wire-format models live in
``api/responses.py`` and reshaping happens in a small module helper.

Flow per case::

    1. dockets_by_number          -> POST /api/CustomQuery/KeywordSearch
    2. parse_search_response      -> build WaDocket from all rows;
                                     yield WaDocket;
                                     yield one archive=True request per row.
    3. handle_document_download   -> yield WaDownloadedDocument with local_path.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import quote

from jkent.common.decorators import entry, step
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    ScraperStatus,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import CourtRange

from .api.responses import KeywordSearchResponse, KeywordSearchRow
from .models import (
    COURT_CASE_NUM_DIGITS,
    COURT_IDS,
    COURT_QUERY_PARAMS,
    WaDocket,
    WaDocketEntry,
    WaDownloadedDocument,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield

# =============================================================================
# URLs and API constants
# =============================================================================

BASE_URL = "https://acdocportal.courts.wa.gov"
PUBLIC_ACCESS_URL = f"{BASE_URL}/PublicAccess"
KEYWORD_SEARCH_URL = f"{PUBLIC_ACCESS_URL}/api/CustomQuery/KeywordSearch"
DOCUMENT_URL_TEMPLATE = (
    f"{PUBLIC_ACCESS_URL}/api/Document/{{doc_id}}/?OverlayMode=View"
)

SEARCH_PAGE_URLS: dict[str, str] = {
    "wash": f"{PUBLIC_ACCESS_URL}/search_sc.html",
    "washctapp": f"{PUBLIC_ACCESS_URL}/search_ca.html",
}

_Yield = WaDocket | WaDownloadedDocument


# =============================================================================
# Scraper
# =============================================================================


class WashingtonAcdocPortalScraper(BaseScraper[_Yield]):
    """Scraper for Washington Supreme Court and Court of Appeals dockets.

    The portal's KeywordSearch API returns every public document filed on
    a given case in a single response; we reshape that into a
    :class:`WaDocket` and archive each document PDF individually.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = f"{PUBLIC_ACCESS_URL}/"
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-04-15"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(3, Duration.SECOND)]

    # =========================================================================
    # Entry point (speculative by case number, one CourtRange per court)
    # =========================================================================

    @entry(WaDocket)
    def dockets_by_number(self, docket_number: CourtRange) -> Request:
        """Speculatively fetch one docket by case number for one court.

        ``docket_number.court_id`` selects the court (``wash`` →
        7-digit Supreme Court numbers, ``washctapp`` → 6-digit Court of
        Appeals numbers across all three divisions). Seed once per court,
        e.g.::

            seed_params = [
                {"dockets_by_number": {"docket_number":
                    {"court_id": "wash", "min": 1048343, "gap": 5}}},
                {"dockets_by_number": {"docket_number":
                    {"court_id": "washctapp", "min": 871463, "gap": 5}}},
            ]
        """
        return self._make_search_request(
            docket_number.court_id, docket_number.min
        )

    # =========================================================================
    # Request builder
    # =========================================================================

    def _make_search_request(self, court_id: str, case_number: int) -> Request:
        """Build the POST request to ``/api/CustomQuery/KeywordSearch``."""
        params = COURT_QUERY_PARAMS[court_id]
        digits = COURT_CASE_NUM_DIGITS[court_id]
        docket_number = f"{case_number:0{digits}d}"

        payload = {
            "QueryID": params["query_id"],
            "Keywords": [
                {
                    "ID": params["keyword_id"],
                    "Value": docket_number,
                    "KeywordOperator": "=",
                }
            ],
            "QueryLimit": 0,
        }

        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=KEYWORD_SEARCH_URL,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/plain, */*",
                    "Origin": BASE_URL,
                    "Referer": SEARCH_PAGE_URLS[court_id],
                },
            ),
            nonnavigating=True,
            continuation=self.parse_search_response,
            accumulated_data={
                "court": court_id,
                "docket_number": docket_number,
                "entry_point": "dockets_by_number",
            },
            deduplication_key=f"search_response:{court_id}:{docket_number}",
        )

    # =========================================================================
    # Search response parsing
    # =========================================================================

    @step(priority=2)
    def parse_search_response(
        self,
        json_content: dict,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Turn the KeywordSearch JSON payload into a ``WaDocket``."""
        court_id = accumulated_data["court"]
        docket_number = accumulated_data["docket_number"]

        parsed = KeywordSearchResponse.model_validate(json_content or {})

        if not parsed.Data:
            # Speculative miss — no case at this case number.
            return

        entries: list[WaDocketEntry] = []
        case_name: str = ""
        anchor_case_number: str | None = None

        for row in parsed.Data:
            entry_record, title_text, anchor_text = _row_to_entry(row)

            if title_text and not case_name:
                case_name = html.unescape(title_text).strip()
            if anchor_text and not anchor_case_number:
                anchor_case_number = anchor_text.strip() or None

            entries.append(entry_record)

        docket = WaDocket.raw(
            docket_number=docket_number,
            court=court_id,
            case_name=case_name or docket_number,
            anchor_case_number=anchor_case_number,
            truncated=parsed.Truncated,
            entries=entries,
            source_url=SEARCH_PAGE_URLS[court_id],
            source_entry_point=accumulated_data.get("entry_point"),
        )
        yield ParsedData(data=docket)

        # Archive each document's PDF.
        for e in entries:
            yield Request(
                archive=True,
                expected_type="pdf",
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=e.document_url,
                    headers={
                        "Accept": "application/pdf, */*",
                        "Referer": SEARCH_PAGE_URLS[court_id],
                    },
                ),
                continuation=self.handle_document_download,
                accumulated_data={
                    "court": court_id,
                    "docket_number": docket_number,
                    "document_id": e.document_id,
                    "document_url": e.document_url,
                },
                deduplication_key=(
                    f"{court_id}-{docket_number}-{_safe_doc_key(e.document_id)}"
                ),
            )

    # =========================================================================
    # Archive download handler
    # =========================================================================

    @step()
    def handle_document_download(
        self,
        local_filepath: str | None,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit a ``WaDownloadedDocument`` with the stored local path."""
        yield ParsedData(
            data=WaDownloadedDocument.raw(
                court=accumulated_data["court"],
                docket_number=accumulated_data["docket_number"],
                document_id=accumulated_data["document_id"],
                document_url=accumulated_data["document_url"],
                local_path=local_filepath,
            )
        )


# =============================================================================
# Helpers
# =============================================================================

# Positional indices of the six columns in DisplayColumnValues.  Order
# is stable across SC (QueryID=194) and CA (QueryID=193) responses;
# only the column headings differ ("SC ..." vs "CA ...").
_COL_FILED_DATE = 0
_COL_FILING_TYPE = 1
_COL_FILING_SUBTYPE = 2
_COL_DOCUMENT_NAME = 3
_COL_CASE_TITLE = 4
_COL_ANCHOR_CASE_NUMBER = 5


def _cell_value(row: KeywordSearchRow, index: int) -> str:
    """Safe positional access to ``row.DisplayColumnValues[index].Value``."""
    if 0 <= index < len(row.DisplayColumnValues):
        return row.DisplayColumnValues[index].Value or ""
    return ""


def _cell_raw(row: KeywordSearchRow, index: int) -> str | None:
    """Safe positional access to ``row.DisplayColumnValues[index].RawValue``."""
    if 0 <= index < len(row.DisplayColumnValues):
        return row.DisplayColumnValues[index].RawValue
    return None


def _row_to_entry(
    row: KeywordSearchRow,
) -> tuple[WaDocketEntry, str, str]:
    """Convert a validated ``KeywordSearchRow`` into a ``WaDocketEntry``.

    Returns ``(entry, title_text, anchor_text)`` — the caller uses the
    last two to derive the case-level ``case_name`` and
    ``anchor_case_number`` (which repeat across every row).
    """
    filed_date_text = _cell_value(row, _COL_FILED_DATE)
    filed_date_raw = _cell_raw(row, _COL_FILED_DATE)
    filing_type = _cell_value(row, _COL_FILING_TYPE) or None
    filing_subtype = _cell_value(row, _COL_FILING_SUBTYPE) or None
    document_name = _strip_span_markup(_cell_value(row, _COL_DOCUMENT_NAME))
    title_text = _cell_value(row, _COL_CASE_TITLE)
    anchor_text = _cell_value(row, _COL_ANCHOR_CASE_NUMBER)

    doc_filed_date = _parse_epoch_ms(filed_date_raw) or _parse_mdyyyy(
        filed_date_text
    )
    document_url = DOCUMENT_URL_TEMPLATE.format(doc_id=quote(row.ID, safe=""))

    entry_record = WaDocketEntry(
        date_filed=doc_filed_date,
        filing_type=filing_type,
        filing_subtype=filing_subtype,
        document_name=document_name,
        anchor_case_number=(anchor_text.strip() or None)
        if anchor_text
        else None,
        document_id=row.ID,
        document_url=document_url,
    )
    return entry_record, title_text, anchor_text


_SPAN_RE = re.compile(
    r"<span[^>]*>.*?</span>", flags=re.DOTALL | re.IGNORECASE
)

_UNSAFE_KEY_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_doc_key(document_id: str) -> str:
    """Render an opaque document id safe for use in a dedup key/filename.

    The portal's document id contains URL-unsafe characters; dedup keys
    for file downloads must avoid colons (they become filenames), so
    collapse anything non-alphanumeric to ``_``.
    """
    return _UNSAFE_KEY_RE.sub("_", document_id).strip("_") or "doc"


def _strip_span_markup(text: str) -> str:
    """Remove the leading ``<span style="color:red;">...</span>`` wrapper and
    unescape HTML entities from a Document Name cell value."""
    if not text:
        return ""
    without_span = _SPAN_RE.sub("", text)
    return html.unescape(without_span).strip()


def _parse_mdyyyy(text: str) -> date | None:
    """Parse ``M/D/YYYY`` into a :class:`date`."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _parse_epoch_ms(text: str | None) -> date | None:
    """Parse a millisecond-epoch string (e.g. ``"1775606400000"``) as a date.

    The portal ships this as a UTC-midnight timestamp; interpreting it in
    UTC keeps the displayed date stable regardless of local timezone.
    """
    if not text:
        return None
    try:
        ts = int(text) / 1000
    except (TypeError, ValueError):
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).date()
    except (OSError, OverflowError, ValueError):
        return None
