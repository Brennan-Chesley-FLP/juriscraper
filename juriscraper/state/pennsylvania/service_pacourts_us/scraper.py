"""Pennsylvania appellate courts scraper over the public JSON API.

Scrapes ``https://services.pacourts.us/public/v1`` — the REST API behind the
AOPC "PAeDocket" mobile app — for the three Pennsylvania appellate courts
(Supreme, Superior, Commonwealth). The endpoints are advertised by the app's
own remote config at ``https://mobileconfig.pacourts.us``; see ``CC_NOTES.md``
for the discovery trail.

This scraper is complementary to ``pennsylvania/ujsportal_pacourts_us``, which
scrapes the HTML portal for the same three courts. The portal exposes only a
results grid plus an unparsed Crystal-Reports PDF docket sheet; **this** API
returns the full structured case — register of actions, parties, attorneys,
dispositions, briefing schedule and lower-court history — in a single request.
The API exposes no document URLs, so the two remain complementary: structured
data here, PDFs there.

One of the two is **not** complementary, though: the portal's *search*. This
API's own search endpoint refuses to run on a date range alone, so there is no
way to ask it "what was filed last week" — the original design worked around
that by speculatively walking the docket-number space, which is expensive,
error-prone under rate limiting, and can never prove it saw everything. The
portal answers exactly that question, server-side, for the same three courts
and the same case-management system. That was compelling enough to go
**cross-domain**: ``dockets_by_filing_date`` runs the sibling portal's
filing-date search on ``ujsportal.pacourts.us`` purely to *discover docket
numbers*, then fetches each case in full from this API. See ``CC_NOTES.md`` →
"Cross-domain docket discovery".

Entry points (§4):
    - dockets_by_filing_date(court_ids, date_range) — **primary.** Docket
      numbers discovered via the UJS portal's filing-date search (cross-domain),
      then fetched in full from this API.
    - dockets_by_number(docket_number)        — speculative walk of one
      ``(court, docket type, year)`` number space. Fallback for windows the
      portal can't address (and a cross-check on it).
    - docket_by_number(court_id, docket_number) — single known docket.
    - dockets_by_participant_name(court_ids, last_name) — name search,
      server-filtered to one appellate court.

Flow:
    dockets_by_filing_date → submit_portal_search (5) → parse_portal_results (4)
                                ├→ (per row) parse_case (3) → ParsedData
                                └→ (cap hit) split window & resubmit → (4)
    dockets_by_number / docket_by_number → parse_case (3) → ParsedData
    dockets_by_participant_name → parse_search_results (4)
                                    → (per appellate row) parse_case (3)

Rate limiting is the dominant operational constraint: the API answers **429**
well before most sites would, and the penalty persists for minutes after the
offending burst. See ``rate_limits`` below and ``CC_NOTES.md``.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import quote

from jkent.common.decorators import entry, step
from jkent.common.exceptions import ScraperAssumptionException
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HTTPCodeType,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    XPath,
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import InferrableDateRange

# --- Cross-domain: the sibling UJS portal supplies the filing-date search ---
# Imported rather than copied so the two scrapers cannot drift apart on the
# portal's form contract or its row cap. See ``dockets_by_filing_date``.
from juriscraper.state.pennsylvania.ujsportal_pacourts_us.models import (
    BROWSER_HEADERS as PORTAL_HEADERS,
)
from juriscraper.state.pennsylvania.ujsportal_pacourts_us.models import (
    COURT_ID_TO_SITE_COURT as COURT_ID_TO_PORTAL_COURT,
)
from juriscraper.state.pennsylvania.ujsportal_pacourts_us.models import (
    MIN_SPLIT_WINDOW as PORTAL_MIN_SPLIT_WINDOW,
)
from juriscraper.state.pennsylvania.ujsportal_pacourts_us.models import (
    RESULT_ROW_CAP as PORTAL_ROW_CAP,
)
from juriscraper.state.pennsylvania.ujsportal_pacourts_us.models import (
    SEARCH_FORM_XPATH as PORTAL_SEARCH_FORM_XPATH,
)
from juriscraper.state.pennsylvania.ujsportal_pacourts_us.models import (
    SEARCH_URL as PORTAL_SEARCH_URL,
)
from juriscraper.state.pennsylvania.ujsportal_pacourts_us.parsers import (
    RESULTS_TABLE_ID as PORTAL_RESULTS_TABLE_ID,
)
from juriscraper.state.pennsylvania.ujsportal_pacourts_us.parsers import (
    ResultsGridParser as PortalResultsGridParser,
)

from .models import (
    BROWSER_HEADERS,
    CASE_URL,
    COURT_ID_TO_SITE_COURT_NAME,
    COURT_IDS,
    DOCKET_TYPES,
    SEARCH_URL,
    PACMSDocket,
    PaDocketRange,
)
from .parsers import CaseDetailParser, SearchResultsParser, parse_docket_number

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


logger = logging.getLogger(__name__)

_Yield = PACMSDocket


class PaCourtsApiScraper(BaseScraper[_Yield]):
    """Scraper for the Pennsylvania appellate courts' public JSON API.

    Pure HTTP against a REST API — no HTML, no JavaScript, no captcha and no
    session state. The only two site quirks are a mandatory browser
    ``User-Agent`` (the API 401s without one) and an aggressive rate limit.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"pa", "pasuperct", "pacommwct"}
    court_url: ClassVar[str] = CASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-09-15"
    last_verified: ClassVar[str] = "2026-09-08"
    requires_auth: ClassVar[bool] = False

    # Plain JSON over HTTP — nothing needs a browser.
    driver_requirements: ClassVar[list[DriverRequirement]] = []

    # The API rate-limits hard and the penalty is long-lived: a single burst
    # of ~10 concurrent requests earned a sustained 429 that was still in
    # effect more than an hour later, for lone requests spaced 8+ seconds
    # apart. The 429 body reads "Unauthorized request" and carries no
    # Retry-After, so there is nothing to back off *to* — the only safe
    # posture is to stay under the threshold.
    #
    # NOTE: 10 seconds is a conservative guess, NOT a measured sustainable
    # rate — recon tripped the block before a safe rate could be established
    # and the block outlasted the session. It mirrors the ceiling the sibling
    # ujsportal scraper settled on for the same operator (AOPC). Validate on
    # the first real run and back off further on any 429. See CC_NOTES.md.
    #
    # 429 is TRANSIENT in the framework default map, so anything that does
    # slip through is retried rather than dropped; no HTTP_CODE_TYPES
    # override is needed. Note that a throttled speculative walk reads 429s
    # as misses and can end a range early — CC_NOTES.md covers the sequencing
    # that avoids this.
    # The ceiling is run-global, not per-host, so the cross-domain portal
    # searches share this budget with the API fetches. Both hosts are AOPC,
    # and the portal's own scraper settled on a *slower* 15s ceiling, so
    # spending API budget on portal requests is the conservative direction.
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND * 10)]

    # For the cross-domain leg only: the UJS portal intermittently 400s (~1%)
    # on well-formed form POSTs carrying a fresh anti-forgery token. Default
    # classification is persistent, which would silently drop a whole date
    # window's rows; retry instead. The JSON API itself does not use 400 —
    # a missing docket is a hard 404 and an under-specified search is a 200
    # with an ``errorMessages`` body — so this affects nothing else.
    HTTP_CODE_TYPES: ClassVar[dict[int, HTTPCodeType]] = {
        400: HTTPCodeType.TRANSIENT,
    }

    # =====================================================================
    # Helpers
    # =====================================================================

    def _case_request(
        self,
        docket_number: str,
        *,
        court_id: str | None,
        entry_point: str,
        reseedable: bool = False,
    ) -> Request:
        """Build the GET that fetches one full case document.

        The docket number goes in the path with its spaces percent-encoded
        (``"1 MAP 2024"`` → ``".../cases/1%20MAP%202024"``).
        """
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{CASE_URL}/{quote(docket_number)}",
            ),
            step=self.parse_case,
            reseedable=reseedable,
            accumulated_data={
                "docket_number": docket_number,
                "court": court_id,
                "entry_point": entry_point,
            },
            deduplication_key=f"case:{docket_number}",
            permanent={"headers": BROWSER_HEADERS},
        )

    def _portal_search_seed(
        self, court_id: str, start: date, end: date
    ) -> Request:
        """Build the GET that fetches the UJS portal's search form.

        Cross-domain: this and the POST it leads to are the only requests
        this scraper makes to ``ujsportal.pacourts.us``. The browser
        ``User-Agent`` rides on ``permanent`` (the portal 401s without one,
        same quirk as the API) and so cascades into the form POST.
        """
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=PORTAL_SEARCH_URL,
            ),
            step=self.submit_portal_search,
            accumulated_data={
                "court": court_id,
                "date_gte": start.isoformat(),
                "date_lte": end.isoformat(),
                "entry_point": "dockets_by_filing_date",
            },
            # Every court shares the same form URL; key on the court and
            # window so the per-court seeds coexist in one scrape.
            deduplication_key=(
                f"portal_search_seed:{court_id}:"
                f"{start.isoformat()}:{end.isoformat()}"
            ),
            permanent={"headers": PORTAL_HEADERS},
        )

    def _portal_search_submit(
        self,
        page: PageElement,
        court_id: str,
        start: date,
        end: date,
    ) -> Request:
        """Submit the portal's appellate filing-date search for one window.

        Works off whatever page carries the form — the initial form GET or a
        results page from a previous submit (which carries a fresh
        anti-forgery token of its own), which is what lets the cap-split
        resubmit without another round-trip.
        """
        form = page.find_form(PORTAL_SEARCH_FORM_XPATH, "case search form")
        return form.submit(
            data={
                "SearchBy": "AppellateCourtName",
                "AppellateCourtName": COURT_ID_TO_PORTAL_COURT[court_id],
                "FiledStartDate": start.isoformat(),
                "FiledEndDate": end.isoformat(),
            },
            step=self.parse_portal_results,
            accumulated_data={
                "court": court_id,
                "date_gte": start.isoformat(),
                "date_lte": end.isoformat(),
                "entry_point": "dockets_by_filing_date",
            },
            deduplication_key=(
                f"portal_search:{court_id}:"
                f"{start.isoformat()}:{end.isoformat()}"
            ),
        )

    # =====================================================================
    # Entry points
    # =====================================================================

    @entry(PACMSDocket)
    def dockets_by_filing_date(
        self, court_ids: set[str], date_range: InferrableDateRange
    ) -> Generator[Request, None, None]:
        """Enumerate dockets filed in ``date_range`` — **the primary entry**.

        Cross-domain by design. This API has no date-range search: the
        endpoint rejects a search anchored on ``dateFiledRangeBegin`` /
        ``dateFiledRangeEnd`` alone ("Must provide a minimum of organization
        name, participant last name, offense tracking number, police incident
        number or state identification number"), and a docket number is not
        an accepted anchor either. That left speculative enumeration as the
        only bulk strategy — which cannot distinguish "sequence number does
        not exist" from "sequence numbers stop here", and which reads a
        throttled 429 as a miss.

        The sibling UJS portal (``ujsportal.pacourts.us``, same operator,
        same three courts, same PACMS backend) *does* search by filing date,
        server-side, one appellate court per POST. So this entry runs that
        search and uses it only as a **docket-number oracle**: each result
        row contributes a docket number, and the full case is then fetched
        from this API. Nothing is emitted from the portal rows themselves —
        the portal's own scraper already emits those (plus their docket-sheet
        PDFs), so duplicating them here would be redundant.

        One search is seeded per requested court (intersected with the three
        supported). ``parse_portal_results`` halves the window and resubmits
        when a search hits the portal's 500-row cap.
        """
        target_courts = sorted(court_ids & set(COURT_ID_TO_PORTAL_COURT))
        if not target_courts:
            raise ScraperAssumptionException(
                f"no supported PA appellate court in {sorted(court_ids)} "
                f"(supported: {sorted(COURT_ID_TO_PORTAL_COURT)})"
            )
        for court_id in target_courts:
            yield self._portal_search_seed(
                court_id, date_range.start, date_range.end
            )

    @entry(PACMSDocket)
    def dockets_by_number(self, docket_number: PaDocketRange) -> Request:
        """Speculatively walk one ``(court, docket type, year)`` number space.

        No longer the primary bulk strategy — ``dockets_by_filing_date``
        enumerates a window exactly where this estimates it — but kept as the
        fallback for when the portal search is unavailable, and as an
        independent check that the portal is not hiding rows.

        PACMS appellate docket numbers are ``"<seq> <TYPE> <year>"``, where
        ``<seq>`` restarts at 1 each year within each type prefix, and
        ``GET /cases/{docket_number}`` returns a hard 404 for a number that
        does not exist. That makes the space cleanly walkable: the driver
        probes ascending ``<seq>`` and advances until ``gap`` consecutive
        misses.

        Seed one range per ``(docket type, year)`` pair — the 17 appellate
        prefixes in ``DOCKET_TYPES`` × the years wanted, e.g.::

            seed_params = [
                {"dockets_by_number": {"docket_number": {
                    "court_id": "pa", "docket_type": "MAP", "year": 2024,
                    "min": 1, "soft_max": 1, "gap": 25}}},
                {"dockets_by_number": {"docket_number": {
                    "court_id": "pasuperct", "docket_type": "EDA", "year": 2024,
                    "min": 1, "soft_max": 1, "gap": 25}}},
                # ... one per (docket_type, year)
            ]

        ``gap`` wants to be generous. Sequence numbers are *not* dense: within
        1–30 of a given 2024 prefix only a third to a half of the numbers
        resolve, and the space does not always start at 1 (``1 EAL 2024`` is a
        404 while ``3 EAL 2024`` exists). A small gap would stop the walk
        inside an ordinary run of misses.
        """
        return self._case_request(
            docket_number.docket_number_for(docket_number.min),
            court_id=docket_number.court_id,
            entry_point="dockets_by_number",
            reseedable=True,
        )

    @entry(PACMSDocket)
    def docket_by_number(
        self, court_id: str, docket_number: str
    ) -> Generator[Request, None, None]:
        """Fetch one already-known docket, e.g. ``"1 MAP 2024"``."""
        yield self._case_request(
            docket_number,
            court_id=court_id,
            entry_point="docket_by_number",
        )

    @entry(PACMSDocket)
    def dockets_by_participant_name(
        self, court_ids: set[str], last_name: str
    ) -> Generator[Request, None, None]:
        """Search for dockets by participant surname, one court per request.

        The search endpoint refuses to run on a date range alone — it requires
        one of organization name, participant last name, OTN, police incident
        number or state ID as an anchor. This is a targeted lookup, not a bulk
        enumerator: the response is capped at 150 rows and does not page. For
        bulk collection use ``dockets_by_filing_date``, which sidesteps this
        endpoint's limits entirely by searching the UJS portal instead.

        ``courtName`` is applied server-side so trial-court matches (which
        otherwise dominate a common surname) never reach us.
        """
        for court_id in sorted(court_ids & set(COURT_IDS)):
            site_court = COURT_ID_TO_SITE_COURT_NAME[court_id]
            yield Request(
                request=HTTPRequestParams(
                    method=HttpMethod.POST,
                    url=SEARCH_URL,
                    json={
                        "searchBy": "ParticipantName",
                        "participantLastName": last_name,
                        "courtName": site_court,
                    },
                ),
                step=self.parse_search_results,
                accumulated_data={
                    "court": court_id,
                    "last_name": last_name,
                    "entry_point": "dockets_by_participant_name",
                },
                deduplication_key=f"participant_search:{court_id}:{last_name}",
                permanent={"headers": BROWSER_HEADERS},
            )

    # =====================================================================
    # Steps
    # =====================================================================

    @step(priority=5)
    def submit_portal_search(
        self, page: PageElement, accumulated_data: dict
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """POST the UJS portal's filing-date search for one court + window."""
        yield self._portal_search_submit(
            page,
            accumulated_data["court"],
            date.fromisoformat(accumulated_data["date_gte"]),
            date.fromisoformat(accumulated_data["date_lte"]),
        )

    @step(priority=4)
    def parse_portal_results(
        self, page: PageElement, accumulated_data: dict
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Turn portal result rows into API case fetches.

        A thin wrapper over :meth:`_portal_results_to_requests`, which holds
        the logic as a plain generator so it stays unit-testable (a ``@step``
        can only be driven through a real ``Response``).
        """
        yield from self._portal_results_to_requests(page, accumulated_data)

    def _portal_results_to_requests(
        self, page: PageElement, accumulated_data: dict
    ) -> Generator[Request, None, None]:
        """Build the requests one portal results page implies.

        The portal grid is capped at 500 data rows with no pagination, so a
        search that comes back at the cap is presumed truncated: the window is
        halved and both halves resubmitted instead of harvesting docket
        numbers from a result set we know is incomplete. A one-day window at
        the cap is accepted rather than split forever — 500 same-day appellate
        filings do not happen — but it is logged, since it would mean the
        window floor no longer holds.
        """
        court_id = accumulated_data["court"]
        start = date.fromisoformat(accumulated_data["date_gte"])
        end = date.fromisoformat(accumulated_data["date_lte"])

        # Bare row count for cap detection, before parsing or filtering.
        row_count = len(
            page.query(
                XPath(f"//table[@id='{PORTAL_RESULTS_TABLE_ID}']/tbody/tr"),
                "case-search result rows",
                min_count=0,
            )
        )
        if row_count >= PORTAL_ROW_CAP:
            if (end - start) > PORTAL_MIN_SPLIT_WINDOW:
                midpoint = start + (end - start) // 2
                for half_start, half_end in (
                    (start, midpoint),
                    (midpoint + timedelta(days=1), end),
                ):
                    yield self._portal_search_submit(
                        page, court_id, half_start, half_end
                    )
                return
            logger.warning(
                "UJS portal search for court=%s hit the %d-row cap on a "
                "single-day window (%s); results for that day are truncated.",
                court_id,
                PORTAL_ROW_CAP,
                start.isoformat(),
            )

        for deferred in PortalResultsGridParser()(page):
            docket_number = deferred.raw_data.get("docket_number")
            # The search is filtered to one appellate court server-side, so
            # every row should carry a PACMS number this API can retrieve. A
            # row that isn't addressable here (a CP-/MJ- trial-court number)
            # is the portal's to emit, not ours.
            docket_type, _year = parse_docket_number(docket_number)
            if docket_type is None:
                logger.warning(
                    "UJS portal returned a non-PACMS docket number %r in an "
                    "appellate search for court=%s; skipping.",
                    docket_number,
                    court_id,
                )
                continue
            yield self._case_request(
                docket_number,
                # The type prefix encodes the court independently of the
                # form filter; parse_case prefers what the API reports.
                court_id=DOCKET_TYPES[docket_type][0],
                entry_point="dockets_by_filing_date",
            )

    @step(priority=4)
    def parse_search_results(
        self, json_content: dict[str, Any], accumulated_data: dict
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Fan out one full-case fetch per appellate row in a search response."""
        parser = SearchResultsParser()
        errors = parser.error_messages(json_content)
        if errors:
            # The entry always sends a participant surname plus a court name,
            # which the API documents as sufficient criteria. A rejection
            # therefore means the search contract changed under us — exactly
            # the structural drift the framework wants surfaced loudly.
            raise ScraperAssumptionException(
                f"PA case search rejected criteria that should be valid "
                f"(court={accumulated_data.get('court')!r}, "
                f"last_name={accumulated_data.get('last_name')!r}): "
                + "; ".join(errors)
            )

        if parser.hit_result_cap(json_content):
            logger.warning(
                "PA case search for court=%s name=%s came back at the %d-row "
                "cap and cannot page; results are truncated.",
                accumulated_data.get("court"),
                accumulated_data.get("last_name"),
                len(json_content.get("results") or []),
            )

        for summary in parser(json_content):
            docket_number = summary["docket_number"]
            # Belt-and-braces: the court filter is applied server-side, but
            # only appellate docket numbers are parseable by this scraper.
            docket_type, _year = parse_docket_number(docket_number)
            if docket_type is None:
                continue
            yield self._case_request(
                docket_number,
                court_id=summary["court"] or DOCKET_TYPES[docket_type][0],
                entry_point=accumulated_data.get(
                    "entry_point", "dockets_by_participant_name"
                ),
            )

    @step(priority=3)
    def parse_case(
        self,
        json_content: dict[str, Any],
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Map a full case document to a ``PACMSDocket`` and emit it."""
        fields = CaseDetailParser()(json_content)

        # The API is the authority on both; fall back to what we asked for so
        # a record is never emitted without a docket number or a court.
        fields["docket_number"] = fields.get("docket_number") or (
            accumulated_data.get("docket_number")
        )
        fields["court"] = fields.get("court") or accumulated_data.get("court")

        fields["source_url"] = response.url
        fields["source_entry_point"] = accumulated_data.get("entry_point")

        yield ParsedData(PACMSDocket.raw(**fields))
