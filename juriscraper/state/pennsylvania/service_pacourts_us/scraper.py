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

Entry points (§4):
    - dockets_by_number(docket_number)        — speculative walk of one
      ``(court, docket type, year)`` number space.
    - docket_by_number(court_id, docket_number) — single known docket.
    - dockets_by_participant_name(court_ids, last_name) — name search,
      server-filtered to one appellate court.

Flow:
    dockets_by_number / docket_by_number → parse_case (3) → ParsedData
    dockets_by_participant_name → parse_search_results (4)
                                    → (per appellate row) parse_case (3)

Rate limiting is the dominant operational constraint: the API answers **429**
well before most sites would, and the penalty persists for minutes after the
offending burst. See ``rate_limits`` below and ``CC_NOTES.md``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import quote

from jkent.common.decorators import entry, step
from jkent.common.exceptions import ScraperAssumptionException
from jkent.data_types import (
    BaseScraper,
    DriverRequirement,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
)
from pyrate_limiter import Duration, Rate

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
    version: ClassVar[str] = "2026-09-08"
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
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND * 10)]

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
            continuation=self.parse_case,
            reseedable=reseedable,
            accumulated_data={
                "docket_number": docket_number,
                "court": court_id,
                "entry_point": entry_point,
            },
            deduplication_key=f"case:{docket_number}",
            permanent={"headers": BROWSER_HEADERS},
        )

    # =====================================================================
    # Entry points
    # =====================================================================

    @entry(PACMSDocket)
    def dockets_by_number(self, docket_number: PaDocketRange) -> Request:
        """Speculatively walk one ``(court, docket type, year)`` number space.

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
        number or state ID as an anchor — so this is the only non-speculative
        way in, and it is a targeted lookup rather than a bulk enumerator: the
        response is capped at 150 rows and does not page.

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
                continuation=self.parse_search_results,
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
