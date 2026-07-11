"""Connecticut appellate-inquiry docket scraper.

Scrapes dockets for the Connecticut Supreme Court (``conn``) and Appellate
Court (``connappct``) from ``appellateinquiry.jud.ct.gov``, addressed by the
site's opaque internal **CRN** (Case Record Number). A single speculative entry,
``dockets_by_internal_id``, probes ``CaseDetail.aspx?CRN={n}``; the driver
advances the range and a missing CRN (302 → ``ErrorPage.aspx``) is a miss. The
court is read from the docket number on the page (``SC`` → ``conn`` / ``AC`` →
``connappct``), so the speculative param carries no court — the CRN space is
shared across both courts.

Each civil appellate case links to its trial-court case on
``civilinquiry.jud.ct.gov``; that link is followed and the Superior Court
(``connsuperct``) case scraped as well.

Flow (priorities descend by depth; downloads at 1)::

    dockets_by_internal_id (entry, speculative)
      → parse_case_detail        (3)  AppealCaseParser + ActivitiesParser
          ├ ParsedData(ConnAppDocket)
          ├ ParsedData(ConnAppDocketEntry) per activity
          ├ archive document → handle_appellate_document (1) → ConnAppFile
          └ civil trial link → parse_trial_court_detail
      → parse_trial_court_detail  (2)  TrialCourtCaseParser + TrialActivitiesParser
          ├ ParsedData(ConnTrialCourtDocket) / ConnTrialCaseUnavailable
          ├ ParsedData(ConnTrialCourtDocketEntry) per row
          └ archive document → handle_trial_document (1) → ConnTrialFile

Per-page HTML extraction lives in the ``parsers`` package; the steps keep
navigation, URL resolution, archive requests, and unavailable-page detection.
"""

from __future__ import annotations

import re
import ssl
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin, urlparse

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
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

from juriscraper.state.common.params import PersistedSpeculativeRange

from .models import (
    COURT_IDS,
    ConnAppDocket,
    ConnAppDocketEntry,
    ConnAppDocketUnavailable,
    ConnAppFile,
    ConnTrialCaseUnavailable,
    ConnTrialCourtDocket,
    ConnTrialCourtDocketEntry,
    ConnTrialFile,
)
from .parsers import (
    ActivitiesParser,
    AppealCaseParser,
    TrialActivitiesParser,
    TrialCourtCaseParser,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield

APPELLATE_BASE = "https://appellateinquiry.jud.ct.gov"
CASE_DETAIL_URL = f"{APPELLATE_BASE}/CaseDetail.aspx"
ERROR_PAGE_MARKER = "ErrorPage.aspx"

_Yield = (
    ConnAppDocket
    | ConnAppDocketEntry
    | ConnAppFile
    | ConnAppDocketUnavailable
    | ConnTrialCourtDocket
    | ConnTrialCourtDocketEntry
    | ConnTrialFile
    | ConnTrialCaseUnavailable
)


def _safe_key(value: str) -> str:
    """Collapse a string to a colon-free, filesystem-safe dedup token."""
    return re.sub(r"[^A-Za-z0-9._-]+", "", value)


class ConnAppInquiryScraper(BaseScraper[_Yield]):
    """Scraper for Connecticut Supreme & Appellate Court dockets.

    The detail pages are plain server-rendered HTML, so no browser is
    required. Both CT Judicial hosts (``appellateinquiry`` and the
    ``civilinquiry`` trial-court host) reject OpenSSL 3.0's default
    ``SECLEVEL=2`` handshake, so ``get_ssl_context`` drops the security level
    to 1. (The legacy combined scraper pinned an ``AES256-SHA256`` cipher,
    which fixed only ``appellateinquiry`` — ``civilinquiry`` rejects it too —
    so don't re-add the pinned cipher.)
    """

    # === Metadata ===
    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = APPELLATE_BASE
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-26"
    last_verified: ClassVar[str] = "2026-06-26"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    rate_limits: ClassVar[list[Rate] | None] = [Rate(2, Duration.SECOND)]

    @classmethod
    def get_ssl_context(cls) -> ssl.SSLContext:
        """Relax the OpenSSL security level for the CT Judicial hosts.

        Both ``appellateinquiry`` and ``civilinquiry`` reject OpenSSL 3.0's
        default ``SECLEVEL=2`` handshake (``SSLV3_ALERT_HANDSHAKE_FAILURE``).
        ``SECLEVEL=1`` keeps the broad default cipher list but allows the
        older handshake both hosts require. Pinning ``AES256-SHA256`` (as the
        legacy scraper did) only fixes ``appellateinquiry``.
        """
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        return ctx

    # =========================================================================
    # Entry point: one speculative CRN probe (shared across both courts).
    # =========================================================================

    @entry(ConnAppDocket)
    def dockets_by_internal_id(
        self, internal_id: PersistedSpeculativeRange
    ) -> Request:
        """Speculatively fetch one docket by CRN.

        CRNs are an opaque, monotonically-issued (but gappy) internal id. The
        driver probes ascending ``internal_id.min`` and advances until ``gap``
        consecutive misses. Court is determined from the page, so a single seed
        space covers both courts. Gaps can be large (hundreds), so seed a
        generous ``gap``, e.g.::

            [{"dockets_by_internal_id": {"internal_id":
                {"min": 1, "soft_max": 105336, "gap": 500}}}]
        """
        crn = internal_id.min
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET,
                url=f"{CASE_DETAIL_URL}?CRN={crn}",
            ),
            continuation=self.parse_case_detail,
            reseedable=True,
            accumulated_data={
                "crn": crn,
                "entry_point": "dockets_by_internal_id",
            },
            deduplication_key=f"parse_case_detail:{crn}",
        )

    # =========================================================================
    # Step: appellate CaseDetail page
    # =========================================================================

    @step(priority=3)
    def parse_case_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the appellate docket, its activities, and follow the trial
        court link.

        A missing CRN redirects to ``ErrorPage.aspx`` (or returns non-200);
        that is a speculation miss, so nothing is yielded. A withheld case
        ("not available at this time") yields ``ConnAppDocketUnavailable``.
        """
        crn = accumulated_data["crn"]

        if response.status_code != 200 or ERROR_PAGE_MARKER in response.url:
            return

        unavailable = page.query(
            XPath("//span[@id='lblNotAvailable']"),
            "not-available message",
            min_count=0,
        )
        if unavailable:
            message = unavailable[0].text_content().strip()
            m = re.match(r"\s*(SC|AC)\s*0*(\d+)", message, re.IGNORECASE)
            docket_number = court = None
            if m:
                prefix = m.group(1).upper()
                docket_number = f"{prefix} {m.group(2)}"
                court = "conn" if prefix == "SC" else "connappct"
            yield ParsedData(
                data=ConnAppDocketUnavailable(
                    crn=crn,
                    docket_number=docket_number,
                    court=court,
                    source_url=response.url,
                    message=message,
                )
            )
            return

        docket_dv = AppealCaseParser()(page)[0]
        bag = docket_dv.raw_data
        docket = ConnAppDocket.raw(
            crn=crn,
            source_url=response.url,
            source_entry_point=accumulated_data.get("entry_point"),
            **bag,
        )
        yield ParsedData(data=docket)

        docket_number = bag["docket_number"]
        court = bag["court"]

        # Docket entries + their documents.
        for e in ActivitiesParser()(page):
            edata = e.raw_data
            doc_urls = [
                urljoin(response.url, h)
                for h in edata.get("document_urls", [])
            ]
            yield ParsedData(
                data=ConnAppDocketEntry.raw(
                    docket_number=docket_number,
                    court=court,
                    **{**edata, "document_urls": doc_urls},
                )
            )
            for doc_url in doc_urls:
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=doc_url
                    ),
                    continuation=self.handle_appellate_document,
                    expected_type="pdf",
                    accumulated_data={
                        "docket_number": docket_number,
                        "court": court,
                        "description": edata.get("description"),
                        "source_url": doc_url,
                    },
                    deduplication_key=(
                        f"{_safe_key(docket_number)}-{_safe_key(doc_url)}"
                    ),
                )

        # Follow the trial-court (civilinquiry) link for civil cases.
        originating = bag.get("originating_court")
        tc_url = getattr(originating, "docket_number_url", None)
        if tc_url:
            tc_raw = self._docket_no_from_url(tc_url)
            yield Request(
                request=HTTPRequestParams(method=HttpMethod.GET, url=tc_url),
                continuation=self.parse_trial_court_detail,
                accumulated_data={
                    "appellate_docket_number": docket_number,
                    "trial_docket_number_raw": tc_raw,
                },
                deduplication_key=f"parse_trial_court_detail:{tc_raw}",
            )

    @step()
    def handle_appellate_document(
        self,
        accumulated_data: dict,
        local_filepath: str | None,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit a ConnAppFile for an archived appellate document."""
        yield ParsedData(
            data=ConnAppFile(
                docket_number=accumulated_data["docket_number"],
                court=accumulated_data["court"],
                description=accumulated_data.get("description"),
                document_url=accumulated_data["source_url"],
                local_path=local_filepath,
                source_url=accumulated_data["source_url"],
            )
        )

    # =========================================================================
    # Step: trial-court (civilinquiry) PublicCaseDetail page
    # =========================================================================

    @step(priority=2)
    def parse_trial_court_detail(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Parse the Superior Court case, or record it as unavailable.

        Cases purged from ``civilinquiry`` (or reached without a session)
        redirect to an error page and have no case content; those yield
        ``ConnTrialCaseUnavailable``.
        """
        appellate_docket_number = accumulated_data.get(
            "appellate_docket_number"
        )
        tc_raw = accumulated_data.get("trial_docket_number_raw")

        has_content = page.query(
            XPath("//span[contains(@id, 'lblCaseCaption')]"),
            "trial case caption",
            min_count=0,
        )
        if (
            response.status_code != 200
            or ERROR_PAGE_MARKER in response.url
            or not has_content
        ):
            if tc_raw:
                yield ParsedData(
                    data=ConnTrialCaseUnavailable(
                        trial_docket_number=tc_raw,
                        appellate_docket_number=appellate_docket_number,
                        source_url=response.url,
                        message="Trial court case not available in civilinquiry",
                    )
                )
            return

        docket_dv = TrialCourtCaseParser()(page)[0]
        bag = docket_dv.raw_data
        docket = ConnTrialCourtDocket.raw(
            docket_number_raw=tc_raw,
            appellate_docket_number=appellate_docket_number,
            source_url=response.url,
            **bag,
        )
        yield ParsedData(data=docket)

        trial_docket_number = bag["docket_number"]
        for e in TrialActivitiesParser()(page):
            edata = e.raw_data
            doc_url = edata.get("document_url")
            if doc_url:
                doc_url = urljoin(response.url, doc_url)
            yield ParsedData(
                data=ConnTrialCourtDocketEntry.raw(
                    trial_docket_number=trial_docket_number,
                    **{**edata, "document_url": doc_url},
                )
            )
            if doc_url:
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET, url=doc_url
                    ),
                    continuation=self.handle_trial_document,
                    expected_type="pdf",
                    accumulated_data={
                        "trial_docket_number": trial_docket_number,
                        "description": edata.get("description"),
                        "source_url": doc_url,
                    },
                    deduplication_key=(
                        f"{_safe_key(trial_docket_number)}-{_safe_key(doc_url)}"
                    ),
                )

    @step()
    def handle_trial_document(
        self,
        accumulated_data: dict,
        local_filepath: str | None,
    ) -> Generator[ScraperYield[_Yield], None, None]:
        """Emit a ConnTrialFile for an archived trial-court document."""
        yield ParsedData(
            data=ConnTrialFile(
                trial_docket_number=accumulated_data["trial_docket_number"],
                description=accumulated_data.get("description"),
                document_url=accumulated_data["source_url"],
                local_path=local_filepath,
                source_url=accumulated_data["source_url"],
            )
        )

    @staticmethod
    def _docket_no_from_url(url: str) -> str | None:
        """Pull the ``DocketNo`` query value out of a civilinquiry URL."""
        query = urlparse(url).query
        m = re.search(r"DocketNo=([^&]+)", query)
        return m.group(1) if m else None
