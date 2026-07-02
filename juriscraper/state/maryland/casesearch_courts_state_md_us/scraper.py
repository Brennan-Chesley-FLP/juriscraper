"""Maryland Judiciary Case Search & Record Portal scraper.

Scrapes appellate dockets from
https://casesearch.courts.state.md.us/casesearch/.

Supported courts:

- Supreme Court of Maryland (``md``) — case prefix ``SCM-*``
- Appellate Court of Maryland (``mdctspecapp``) — case prefix ``ACM-*``

The portal is fronted by DataDome bot protection, so the scraper must run
under a real browser (JS_EVAL / FF_ALIKE). Once the DataDome cookie is issued
the underlying JSON case-detail API becomes callable:

- ``GET /api-casedetails/v1/public/cases/{caseId}`` — one case detail payload.

There is no public way to enumerate cases by date alone (every search form
requires a Last Name), so we speculate against the case-detail API. Case
numbers follow ``{COURT3}-{TYPE3}-{NNNN}-{YYYY}`` with a new sequence each
year, and the URL strips the dashes:
``caseId={COURT3}{TYPE3}{NNNN}{YYYY}``. Invalid case IDs return HTTP 400,
which we reclassify as a clean speculative "miss" (see ``HTTP_CODE_TYPES`` and
``actually_successful``).

JSON extraction lives in the ``parsers`` package (``CaseDetailParser``); the
steps keep navigation concerns (request building, the entry-point stamp).

Entry point (§4):
    - dockets_by_number(case_id)  — one speculative ``@entry`` covering all
      (court, case-type) prefixes; the target court+type rides on the
      ``MdCaseRange`` speculative param, seeded once per prefix per year.

Flow:
    dockets_by_number → parse_case_detail → ParsedData
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
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
)
from pyrate_limiter import Duration, Rate

from juriscraper.state.common.params import YearlySpeculativeRange

from .models import (
    COURT_PREFIX_TO_ID,
    DETAIL_API,
    DETAIL_PAGE,
    SEARCH_FORM_URL,
    MdAppellateDocket,
)
from .parsers import CaseDetailParser

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

    from jkent.data_types import ScraperYield


class MdCaseRange(YearlySpeculativeRange):
    """A year-partitioned speculative range tagged with court+case-type.

    A speculative ``@entry`` is dispatched by the driver with **only** its
    speculative param (SCRAPER_STANDARDS §4, "Multi-court speculative
    entries"), so the target court and case-type ride here rather than as
    separate entry arguments. Seed one ``MdCaseRange`` per ``(court3, type3,
    year)`` prefix; ``from_int`` advancement preserves ``court3``/``type3``
    because it copies via ``model_copy``.

    Seed example (``seed_params``)::

        [
          {"dockets_by_number": {"case_id":
            {"court3": "ACM", "type3": "REG", "year": 2024,
             "min": 1, "soft_max": 1, "gap": 30}}},
          {"dockets_by_number": {"case_id":
            {"court3": "SCM", "type3": "PET", "year": 2025,
             "min": 1, "soft_max": 1, "gap": 30}}},
          # ... one per (court3, type3, year) prefix.
        ]
    """

    court3: str
    """Three-letter site court prefix: ``ACM`` or ``SCM``."""
    type3: str
    """Three-letter site case-type prefix: ``REG`` / ``ALA`` / ``PET`` /
    ``MISC``."""

    @property
    def court_id(self) -> str:
        """CourtListener court id for this prefix (``md`` / ``mdctspecapp``)."""
        return COURT_PREFIX_TO_ID.get(self.court3.upper(), "")

    def case_id_param(self) -> str:
        """The dashless ``caseId`` URL key, e.g. ``ACMREG24872024``."""
        return f"{self.court3}{self.type3}{self.min:04d}{self.year}"

    def docket_number(self) -> str:
        """The display case number, e.g. ``ACM-REG-2487-2024``."""
        return f"{self.court3}-{self.type3}-{self.min:04d}-{self.year}"


class MarylandJudiciaryCaseSearchScraper(BaseScraper[MdAppellateDocket]):
    """Scraper for the Maryland Judiciary Case Search & Record Portal.

    One speculative ``@entry`` (``dockets_by_number``) covers every
    ``(court, case-type)`` prefix; the prefix and year ride on the
    ``MdCaseRange`` speculative param and the driver advances each seeded
    range independently. Each probe fetches one case from the detail JSON
    API.
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = {"md", "mdctspecapp"}
    court_url: ClassVar[str] = SEARCH_FORM_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    # DataDome JS challenge gates every request, so we need a real browser.
    driver_requirements: ClassVar[list[DriverRequirement]] = [
        DriverRequirement.JS_EVAL,
        DriverRequirement.FF_ALIKE,
    ]

    # The detail API returns HTTP 400 (with a JSON error body) for
    # non-existent case numbers — not a soft-404 page. Treat 400 as a
    # successful fetch so the speculation driver records it as a clean miss
    # (``actually_successful`` + ``parse_case_detail`` swallow the error
    # body) rather than fail-fast on the default PERSISTENT classification.
    HTTP_CODE_TYPES: ClassVar[dict[int, HTTPCodeType]] = {
        400: HTTPCodeType.SUCCESSFUL,
    }

    # =========================================================================
    # Entry point (§4)
    # =========================================================================

    @entry(MdAppellateDocket)
    def dockets_by_number(self, case_id: MdCaseRange) -> Request:
        """Speculatively fetch one docket by case number for one prefix.

        ``case_id`` carries the court+type prefix and year; the driver
        probes ascending sequence numbers and advances until ``gap``
        consecutive misses. Seed once per ``(court3, type3, year)`` prefix
        (see :class:`MdCaseRange`).
        """
        case_id_param = case_id.case_id_param()
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{DETAIL_API}/{case_id_param}",
                headers={"Accept": "application/json"},
            ),
            continuation=self.parse_case_detail,
            accumulated_data={
                "case_id_param": case_id_param,
                "docket_number": case_id.docket_number(),
                "court": case_id.court_id,
                "entry_point": "dockets_by_number",
            },
            deduplication_key=f"case_detail:{case_id_param}",
        )

    # =========================================================================
    # Step: case-detail JSON
    # =========================================================================

    @step()
    def parse_case_detail(
        self,
        json_content: dict,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MdAppellateDocket], None, None]:
        """Parse the case-detail JSON payload into a ``MdAppellateDocket``.

        ``CaseDetailParser`` owns the payload extraction; the step stamps the
        fields the payload doesn't carry (``court``, ``case_id_param``,
        ``source_url``, ``source_entry_point``). On a speculative miss
        (HTTP 400 → no ``caseDetail`` block) nothing is emitted.
        """
        if not self._has_case_detail(json_content):
            return

        case_id_param = accumulated_data["case_id_param"]
        raw = CaseDetailParser()(json_content)[0].raw_data
        # Fall back to the seeded values when the payload omits them.
        if not raw.get("docket_number"):
            raw["docket_number"] = accumulated_data["docket_number"]
        if not raw.get("court"):
            raw["court"] = accumulated_data["court"]
        raw["case_id_param"] = case_id_param
        raw["source_url"] = f"{DETAIL_PAGE}?caseId={case_id_param}"
        raw["source_entry_point"] = accumulated_data.get("entry_point")
        yield ParsedData(data=MdAppellateDocket.raw(**raw))

    # =========================================================================
    # Speculative-miss detection
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Let 400 error bodies through as clean misses.

        ``HTTP_CODE_TYPES`` already classifies 400 as successful so the
        response reaches ``parse_case_detail``; that step yields nothing for
        a payload with no ``caseDetail`` block, which the speculation driver
        records as a normal miss.
        """
        return True

    @staticmethod
    def _has_case_detail(json_content: Mapping | None) -> bool:
        """True when the payload carries a real case-detail block."""
        return bool(json_content) and bool(json_content.get("caseDetail"))
