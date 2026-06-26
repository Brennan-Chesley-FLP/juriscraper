"""Parsers for the appellate ``CaseDetail.aspx`` page.

``AppealCaseParser`` extracts the docket (with nested parties, originating
court, preliminary papers, and transcripts). ``ActivitiesParser`` extracts the
Case Activity rows as docket entries. Both stay on the public ``PageElement``
API; URL resolution and the ``crn``/``source_url`` provenance are the step's job.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.exceptions import HTMLStructuralAssumptionException
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.connecticut.appellateinquiry_jud_ct_gov.models import (
    DOCKET_PREFIX_TO_COURT,
    ConnAppAttorney,
    ConnAppDocket,
    ConnAppDocketEntry,
    ConnAppOriginatingCourt,
    ConnAppParty,
    ConnAppPreliminaryPaper,
    ConnAppTranscript,
)

from ._common import (
    cell_date,
    clean_text,
    juris_number,
    parse_date,
    span_date,
    span_text,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

# "SC 250277" / "AC09930" / "SC  21125" -> ("SC", "250277")
_DOCKET_RE = re.compile(r"^\s*(SC|AC)\s*0*(\d+)\s*$", re.IGNORECASE)


class AppealCaseParser(JKentParser[ConnAppDocket]):
    """Parse one appellate ``CaseDetail.aspx`` page into a ``ConnAppDocket``.

    The returned record omits ``crn``, ``source_url``, and
    ``source_entry_point`` — those are not on the page and are supplied by the
    step from the request context.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[ConnAppDocket]]:
        raw_no = span_text(page, "lblAppealNo")
        if not raw_no:
            raise HTMLStructuralAssumptionException(
                selector="//span[@id='lblAppealNo']",
                selector_type="xpath",
                description="appellate docket number (lblAppealNo)",
                expected_min=1,
                expected_max=1,
                actual_count=0,
                request_url="",
            )
        m = _DOCKET_RE.match(raw_no.replace("\xa0", " "))
        if not m:
            raise HTMLStructuralAssumptionException(
                selector="//span[@id='lblAppealNo']",
                selector_type="xpath",
                description=f"SC/AC docket number, got {raw_no!r}",
                expected_min=1,
                expected_max=1,
                actual_count=1,
                request_url="",
            )
        prefix = m.group(1).upper()
        docket_number = f"{prefix} {m.group(2)}"
        court = DOCKET_PREFIX_TO_COURT[prefix]

        subscribe = page.find_links(
            XPath("//a[@id='hlnkSubscribe']"), "subscribe link", min_count=0
        )

        docket = ConnAppDocket.raw(
            court=court,
            docket_number=docket_number,
            docket_number_raw=raw_no,
            case_name=span_text(page, "lblCaseName") or "Unknown",
            case_status=span_text(page, "lblCaseStatus"),
            date_filed=span_date(page, "lblDateFiled"),
            date_argued=span_date(page, "lblArgSub"),
            date_terminated=span_date(page, "lblDispDt"),
            panel_str=span_text(page, "lblPanel"),
            appeal_by=span_text(page, "lblAppealBy"),
            disposition_method=span_text(page, "lblDispMethod"),
            date_submitted_on_briefs=span_date(page, "lblSubmitDt"),
            date_response_due=span_date(page, "lblResponse2Docket"),
            date_record_filed=span_date(page, "lblRecordFiled"),
            date_exhibits_received=span_date(page, "lblExhbitsRecByCourt"),
            citation=span_text(page, "lblRescript"),
            is_efiled=self._is_efiled(page),
            originating_court=self._parse_originating_court(page),
            parties=self._parse_parties(page),
            preliminary_papers=self._parse_preliminary_papers(page),
            transcripts=self._parse_transcripts(page),
            subscription_url=subscribe[0].url if subscribe else None,
        )
        return [docket]

    @staticmethod
    def _is_efiled(page: PageElement) -> bool:
        hits = page.query(
            XPath(
                "//span[contains(@id, 'EFiled')]"
                " | //img[contains(@alt, 'eFiled')]"
            ),
            "e-filed indicator",
            min_count=0,
        )
        return bool(hits)

    @staticmethod
    def _parse_originating_court(
        page: PageElement,
    ) -> ConnAppOriginatingCourt | None:
        tc_links = page.find_links(
            XPath(
                "//table[@id='dlTCDockets']//a"
                "[contains(@href, 'civilinquiry') or contains(@href, 'DocketNo')]"
            ),
            "trial court docket link",
            min_count=0,
        )
        tc_number_spans = page.query(
            XPath(
                "//span[contains(@id, 'dlTCDockets') and contains(@id, 'lblDocketNumber')]"
            ),
            "trial court docket number",
            min_count=0,
        )
        docket_number = (
            clean_text(tc_number_spans[0].text_content())
            if tc_number_spans
            else (tc_links[0].text if tc_links else None)
        )
        info = ConnAppOriginatingCourt(
            docket_number=docket_number,
            docket_number_url=tc_links[0].url if tc_links else None,
            court_name=span_text(page, "lblCourt"),
            assigned_to_str=span_text(page, "lblTrialJudge"),
            date_judgment=span_date(page, "lblJudgementdate"),
            judgment_for=span_text(page, "lblJudgementFor"),
            case_type=span_text(page, "lblCaseType"),
        )
        # Drop a block where nothing was found.
        if not any(info.model_dump().values()):
            return None
        return info

    @staticmethod
    def _parse_parties(page: PageElement) -> list[ConnAppParty]:
        rows = page.query(
            XPath(
                "//table[@id='gvPartyCounsel']//tr"
                "[.//span[contains(@id, 'lblPartyName')]]"
            ),
            "appellate party rows",
            min_count=0,
        )
        parties: list[ConnAppParty] = []
        for row in rows:
            name_spans = row.query(
                XPath(".//span[contains(@id, 'lblPartyName')]"),
                "party name",
                min_count=1,
                max_count=1,
            )
            name = clean_text(name_spans[0].text_content())
            if not name:
                continue

            appeal_class = row.query(
                XPath(".//span[contains(@id, 'lblAppealPartyClass')]"),
                "appeal party class",
                min_count=0,
            )
            trial_class = row.query(
                XPath(".//span[contains(@id, 'lblTrialCourtPartyClass')]"),
                "trial court party class",
                min_count=0,
            )

            attorneys: list[ConnAppAttorney] = []
            for sub in row.query(
                XPath(".//table[contains(@id, 'tblJurisInfo')]"),
                "counsel juris tables",
                min_count=0,
            ):
                atty_name_cells = sub.query(
                    XPath(".//td[contains(@id, 'tdJurisName')]"),
                    "juris name cell",
                    min_count=0,
                )
                atty_name = (
                    clean_text(atty_name_cells[0].text_content())
                    if atty_name_cells
                    else None
                )
                if not atty_name:
                    continue
                num_cells = sub.query(
                    XPath(".//td[contains(@id, 'tdJurisNumber')]"),
                    "juris number cell",
                    min_count=0,
                )
                attorneys.append(
                    ConnAppAttorney(
                        name=atty_name,
                        juris_number=(
                            juris_number(num_cells[0].text_content())
                            if num_cells
                            else None
                        ),
                    )
                )

            parties.append(
                ConnAppParty(
                    name=name,
                    party_type=(
                        clean_text(appeal_class[0].text_content())
                        if appeal_class
                        else None
                    ),
                    trial_court_party_class=(
                        clean_text(trial_class[0].text_content())
                        if trial_class
                        else None
                    ),
                    attorneys=attorneys,
                )
            )
        return parties

    @staticmethod
    def _parse_preliminary_papers(
        page: PageElement,
    ) -> list[ConnAppPreliminaryPaper]:
        """Per-party preliminary-paper dates (``gvPrelimPapers``).

        Columns: party name, then eight filing-date columns. Best-effort —
        absent on most cases.
        """
        rows = page.query(
            XPath("//table[@id='gvPrelimPapers']//tr[td]"),
            "preliminary paper rows",
            min_count=0,
        )
        papers: list[ConnAppPreliminaryPaper] = []
        for row in rows:
            cells = row.query(XPath("./td"), "prelim cells", min_count=0)
            if not cells:
                continue
            party_name = clean_text(cells[0].text_content())
            if not party_name:
                continue

            papers.append(
                ConnAppPreliminaryPaper(
                    party_name=party_name,
                    preliminary_statement_of_issues=cell_date(cells, 1),
                    designation_clerk_appendix=cell_date(cells, 2),
                    certificate_transcript_received=cell_date(cells, 3),
                    docketing_statement=cell_date(cells, 4),
                    pac_statement=cell_date(cells, 5),
                    constitutionality_notice=cell_date(cells, 6),
                    sealing_notice=cell_date(cells, 7),
                    certificate_interested_entities=cell_date(cells, 8),
                )
            )
        return papers

    @staticmethod
    def _parse_transcripts(page: PageElement) -> list[ConnAppTranscript]:
        """Per-party transcript info (``gvTranscripts``). Best-effort."""
        rows = page.query(
            XPath("//table[@id='gvTranscripts']//tr[td]"),
            "transcript rows",
            min_count=0,
        )
        transcripts: list[ConnAppTranscript] = []
        for row in rows:
            cells = row.query(XPath("./td"), "transcript cells", min_count=0)
            if not cells:
                continue
            party_name = clean_text(cells[0].text_content())
            if not party_name:
                continue
            pages = None
            if len(cells) > 4:
                pages_text = clean_text(cells[4].text_content())
                if pages_text and pages_text.isdigit():
                    pages = int(pages_text)
            transcripts.append(
                ConnAppTranscript(
                    party_name=party_name,
                    transcripts_ordered=cell_date(cells, 1),
                    estimated_delivery_date=cell_date(cells, 2),
                    delivered_to_party=cell_date(cells, 3),
                    pages=pages,
                    delivered_to_court=cell_date(cells, 5),
                )
            )
        return transcripts


class ActivitiesParser(JKentParser[ConnAppDocketEntry]):
    """Parse the Case Activity table (``gvActivities``) into docket entries.

    Eight columns: Activity, Number, Date filed, Initiated By, Description,
    Action, Action Date, Notice Date. Document links live in the Activity cell.
    The parser captures **relative** document hrefs in ``document_urls``; the
    step resolves them against the site base and ``docket_number``/``court`` are
    added by the step.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[ConnAppDocketEntry]]:
        rows = page.query(
            XPath(
                "//table[@id='gvActivities']//tr"
                "[.//span[contains(@id, 'lblActivity')]]"
            ),
            "case activity rows",
            min_count=0,
        )
        entries: list[DeferredValidation[ConnAppDocketEntry]] = []
        for row in rows:
            cells = row.query(XPath("./td"), "activity cells", min_count=0)
            if len(cells) < 8:
                continue

            activity_spans = cells[0].query(
                XPath(".//span[contains(@id, 'lblActivity')]"),
                "activity type",
                min_count=0,
            )
            activity_type = (
                clean_text(activity_spans[0].text_content())
                if activity_spans
                else clean_text(cells[0].text_content())
            ) or "Unknown"

            desc_spans = cells[4].query(
                XPath(".//span[contains(@id, 'lblDescription')]"),
                "description",
                min_count=0,
            )
            description = (
                clean_text(desc_spans[0].text_content())
                if desc_spans
                else clean_text(cells[4].text_content())
            )

            doc_hrefs = [
                href
                for link in cells[0].query(
                    XPath(".//a[contains(@href, 'DocumentDisplayer')]"),
                    "activity document links",
                    min_count=0,
                )
                if (href := link.get_attribute("href"))
            ]

            is_paperless = bool(
                row.query(
                    XPath(
                        ".//img[contains(@alt, 'aperless') or @title='Paperless']"
                    ),
                    "paperless indicator",
                    min_count=0,
                )
            )

            entries.append(
                ConnAppDocketEntry.raw(
                    activity_type=activity_type,
                    number=clean_text(cells[1].text_content()),
                    date_filed=parse_date(cells[2].text_content()),
                    initiated_by=clean_text(cells[3].text_content()),
                    description=description,
                    action=clean_text(cells[5].text_content()),
                    action_date=parse_date(cells[6].text_content()),
                    notice_date=parse_date(cells[7].text_content()),
                    is_paperless=is_paperless,
                    document_urls=doc_hrefs,
                )
            )
        return entries
