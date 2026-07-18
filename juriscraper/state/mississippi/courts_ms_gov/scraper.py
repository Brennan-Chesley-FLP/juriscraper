"""Mississippi Appellate Courts scraper.

Pulls dockets from the unified ``courts.ms.gov/appellatecourts/docket/``
backend that serves both the Mississippi Supreme Court (``miss``) and the
Court of Appeals of Mississippi (``missctapp``).

The site exposes only an autocomplete search (capped at 7 results) and a
direct lookup by an internal sequential ``case_num``. The scraper therefore
uses a single speculative entry over the unified ``case_num`` integer
space; the public docket number's ``-SCT`` / ``-COA`` suffix is parsed from
the response and used to assign ``court``. Because the court is *derived*
from the response rather than addressed, this is a plain ``SpeculativeRange``
entry (not a per-court ``CourtRange``).

Each case requires up to four detail fetches against ``build_docket.php``
(case + parties + trial-court + oral-args) which are chained via
``accumulated_data``. Per-page HTML extraction lives in the ``parsers``
package; the steps keep only navigation (the build_docket.php sub-fetches and
the per-PDF archive fan-out). Every referenced PDF is yielded as an archive
Request resolved separately into ``MsAppDocument``.

Entry point (§4):
    - dockets_by_internal_id(internal_id)  — speculative walk of the unified
      ``case_num`` space; both courts emerge from it.

Flow:
    dockets_by_internal_id
        └→ parse_docket_page (docket_type=docket)
            ├→ parse_parties (apinfo, listby=pty)
            │    └→ parse_trial_court (lcinfo)
            │        └→ parse_oral_arguments (oralarg) → ParsedData(MsAppDocket)
            └→ (per PDF) download_document (archive=True) → ParsedData(MsAppDocument)
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING, ClassVar

from jkent.common.decorators import entry, step
from jkent.common.exceptions import TransientException
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

from juriscraper.state.common.headers import FF_HEADERS
from juriscraper.state.common.params import PersistedSpeculativeRange

from .models import (
    BUILD_DOCKET_URL,
    INDEX_URL,
    MsAppDocket,
    MsAppDocketEntry,
    MsAppDocument,
    MsAppParty,
    MsAppTrialCourt,
)
from .parsers import (
    DocketPageParser,
    OralArgumentsParser,
    PartiesParser,
    TrialCourtParser,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.common.page_element import PageElement
    from jkent.data_types import ScraperYield


# Form bodies for build_docket.php, merged with ``case_num`` per request.
# Dicts, not pre-encoded strings: the httpx transport form-encodes dict
# ``data`` but silently drops a plain-str body. ``limit=true`` caps the
# returned PDF metadata (without it we still get the full entry list, but
# the response can be ~5x larger for very long dockets).
DOCKET_BODY = {"docket_type": "docket", "sortdir": "desc", "limit": "true"}
PARTIES_BODY = {"docket_type": "apinfo", "listby": "pty"}
LCOURT_BODY = {"docket_type": "lcinfo"}
ORALARG_BODY = {"docket_type": "oralarg"}

XHR_HEADERS: dict[str, str] = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": INDEX_URL,
}

# String present in the case-header response when the requested case_num
# is not assigned to any public case.
SOFT_404_NEEDLE = "No public results were found for your search"

# Title of the WAF's captcha interstitial, served with a 200 in place of
# the requested resource under sustained request volume.
CAPTCHA_NEEDLE = "Firewall Captcha Authentication"

_ENTRY_POINT = "dockets_by_internal_id"


class MississippiAppellateScraper(BaseScraper[MsAppDocket | MsAppDocument]):
    """Scraper for the Mississippi Supreme Court and Court of Appeals."""

    # === Metadata (§3) ===
    court_ids: ClassVar[set[str]] = {"miss", "missctapp"}
    court_url: ClassVar[str] = INDEX_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-06-27"
    last_verified: ClassVar[str] = "2026-05-03"
    requires_auth: ClassVar[bool] = False
    driver_requirements: ClassVar[list[DriverRequirement]] = []
    # The front-end WAF 500s on non-browser User-Agents (even plain GETs),
    # so every request must present a full browser fingerprint.
    default_headers: ClassVar[Mapping[str, str]] = FF_HEADERS
    # The WAF also load-sheds with 500s (observed on sendPDF.php fetches
    # that succeed on retry). The framework default treats 500 as
    # persistent, which on a speculative probe silently records a miss —
    # so a throttling burst would corrupt the case_num walk.
    HTTP_CODE_TYPES: ClassVar[dict[int, HTTPCodeType]] = {
        500: HTTPCodeType.TRANSIENT,
    }
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Soft-404 (§10)
    # =========================================================================

    def actually_successful(self, response: Response) -> bool:
        """Return ``False`` for the public 'no case' page served for
        unassigned ``case_num`` values (a 200 with an error body)."""
        return SOFT_404_NEEDLE not in response.text

    @staticmethod
    def _check_challenge(response: Response) -> None:
        """Raise ``TransientException`` when the WAF serves its captcha
        interstitial (a 200) in place of the requested resource, so the
        request is retried instead of being parsed or — worse — counted
        as a speculation outcome for a ``case_num`` it says nothing about.
        """
        if CAPTCHA_NEEDLE in response.text:
            raise TransientException("WAF captcha challenge page")

    # =========================================================================
    # Entry point (§4)
    # =========================================================================

    @entry(MsAppDocket)
    def dockets_by_internal_id(
        self, internal_id: PersistedSpeculativeRange
    ) -> Request:
        """Speculative docket fetcher across the unified case-num space.

        ``internal_id`` is the integer ``case_num`` assigned at filing time,
        shared between the Supreme Court and the Court of Appeals; the
        scraper decides ``court`` after seeing the docket-number suffix on
        the response. The court is not addressable, so this is a plain
        ``SpeculativeRange`` (not a per-court ``CourtRange``).
        """
        cn = internal_id.min
        return Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=BUILD_DOCKET_URL,
                data={**DOCKET_BODY, "case_num": str(cn)},
                headers=XHR_HEADERS,
            ),
            continuation=self.parse_docket_page,
            accumulated_data={"case_num": cn},
            deduplication_key=f"docket_page:{cn}",
        )

    # =========================================================================
    # Step 1: docket page (header + entries + PDF refs) — priority 4
    # =========================================================================

    @step(priority=4)
    def parse_docket_page(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MsAppDocument], None, None]:
        """Parse case header + docket entries and chain into the parties tab.

        ``DocketPageParser`` owns the extraction; the step yields a fresh
        archive Request for every referenced PDF and a follow-on Request for
        the parties tab whose continuation eventually emits the assembled
        ``MsAppDocket``.
        """
        self._check_challenge(response)
        # Speculative miss (unassigned case_num): the driver has already
        # counted the outcome via actually_successful, but it still runs
        # the continuation — bail before the parser trips on the error page.
        if SOFT_404_NEEDLE in response.text:
            return

        cn = int(accumulated_data["case_num"])

        parser = DocketPageParser()
        raw = parser(page)[0].raw_data
        docket_number = raw["docket_number"]
        # The parser passed already-built ``MsAppDocketEntry`` instances into
        # ``.raw()``, so ``raw["entries"]`` holds model instances.
        entries: list[MsAppDocketEntry] = list(raw.get("entries", []))

        documents = parser.documents(
            page,
            base_url=response.url,
            docket_number=docket_number,
            case_num=cn,
            entries=entries,
        )

        # Schedule each PDF as an archive Request — resolved into
        # ParsedData(MsAppDocument) by ``download_document``.
        for doc in documents:
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET, url=doc.download_url
                ),
                continuation=self.download_document,
                expected_type="pdf",
                accumulated_data={"doc": doc.model_dump(mode="json")},
                deduplication_key=f"{cn}-{doc.file_name}",
            )

        accumulated_data.update(
            {
                "docket_number": docket_number,
                "case_name": raw["case_name"],
                "court": raw["court"],
                "date_filed": raw["date_filed"].isoformat()
                if raw.get("date_filed")
                else None,
                "entries": [e.model_dump(mode="json") for e in entries],
                "document_count": len(documents),
            }
        )

        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=BUILD_DOCKET_URL,
                data={**PARTIES_BODY, "case_num": str(cn)},
                headers=XHR_HEADERS,
            ),
            continuation=self.parse_parties,
            accumulated_data=accumulated_data,
            deduplication_key=f"parse_parties:{cn}",
        )

    # =========================================================================
    # Step 2: parties (listby=pty) — priority 3
    # =========================================================================

    @step(priority=3)
    def parse_parties(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Parse the parties + attorneys block, then chain to lcinfo."""
        self._check_challenge(response)
        parties = [dv.confirm() for dv in PartiesParser()(page)]
        accumulated_data["parties"] = [
            p.model_dump(mode="json") for p in parties
        ]

        cn = int(accumulated_data["case_num"])
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=BUILD_DOCKET_URL,
                data={**LCOURT_BODY, "case_num": str(cn)},
                headers=XHR_HEADERS,
            ),
            continuation=self.parse_trial_court,
            accumulated_data=accumulated_data,
            deduplication_key=f"parse_trial_court:{cn}",
        )

    # =========================================================================
    # Step 3: trial court info (lcinfo) — priority 2
    # =========================================================================

    @step(priority=2)
    def parse_trial_court(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield, None, None]:
        """Parse the trial-court block(s) and chain to oralarg."""
        self._check_challenge(response)
        trial_courts = [
            dv.confirm()
            for dv in TrialCourtParser(
                appellate_docket_number=accumulated_data.get("docket_number")
                or "",
                case_name=accumulated_data.get("case_name") or "",
            )(page)
        ]
        accumulated_data["trial_courts"] = [
            tc.model_dump(mode="json") for tc in trial_courts
        ]

        cn = int(accumulated_data["case_num"])
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.POST,
                url=BUILD_DOCKET_URL,
                data={**ORALARG_BODY, "case_num": str(cn)},
                headers=XHR_HEADERS,
            ),
            continuation=self.parse_oral_arguments,
            accumulated_data=accumulated_data,
            deduplication_key=f"parse_oral_arguments:{cn}",
        )

    # =========================================================================
    # Step 4: oral arguments + final assembly — priority 2
    # =========================================================================

    @step(priority=2)
    def parse_oral_arguments(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MsAppDocket], None, None]:
        """Parse the oral-arg pane and yield the assembled docket."""
        self._check_challenge(response)
        oral_arguments = [dv.confirm() for dv in OralArgumentsParser()(page)]

        cn = int(accumulated_data["case_num"])
        date_filed_raw = accumulated_data.get("date_filed")
        date_filed = (
            date.fromisoformat(date_filed_raw) if date_filed_raw else None
        )

        docket = MsAppDocket.raw(
            docket_number=accumulated_data["docket_number"],
            court=accumulated_data["court"],
            case_num=cn,
            case_name=accumulated_data["case_name"],
            date_filed=date_filed,
            entries=[
                MsAppDocketEntry(**e)
                for e in accumulated_data.get("entries", [])
            ],
            parties=[
                MsAppParty(**p) for p in accumulated_data.get("parties", [])
            ],
            trial_courts=[
                MsAppTrialCourt(**tc)
                for tc in accumulated_data.get("trial_courts", [])
            ],
            oral_arguments=oral_arguments,
            document_count=int(accumulated_data.get("document_count", 0)),
            source_url=f"{INDEX_URL}?cn={cn}#dispArea",
            source_entry_point=_ENTRY_POINT,
        )
        yield ParsedData(docket)

    # =========================================================================
    # Step: document download completion — priority 1 (archive)
    # =========================================================================

    @step()
    def download_document(
        self,
        local_filepath: str | None,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[MsAppDocument], None, None]:
        """Finalize an archived PDF into an ``MsAppDocument`` record."""
        doc_dict = dict(accumulated_data["doc"])
        date_raw = doc_dict.get("date_filed")
        doc = MsAppDocument.raw(
            docket_number=doc_dict["docket_number"],
            case_num=int(doc_dict["case_num"]),
            file_name=doc_dict["file_name"],
            download_url=response.url,
            description=doc_dict.get("description"),
            date_filed=date.fromisoformat(date_raw) if date_raw else None,
            document_index=doc_dict.get("document_index"),
            local_path=local_filepath,
        )
        yield ParsedData(doc)
