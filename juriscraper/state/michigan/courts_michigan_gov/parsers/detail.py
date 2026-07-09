"""Parser for the Michigan case-detail JSON (``get*casedetaildata``).

This is the rich, invisible-hCaptcha-gated payload the SPA fetches when a
case page loads. The scraper reaches it by navigating a real browser to the
case page and promoting the resulting XHR (see the driver's
``Request.incidental`` mechanism); this parser turns that JSON into a fully
populated :class:`MichDocket` (parties, attorneys, docket entries, judges,
judgments, cross-references).

This is a JSON parser, not an HTML ``JKentParser`` (the site is a JSON API);
it keeps the callable-returning-``list[DeferredValidation]`` contract so the
step stays thin and extraction is unit-testable offline against a saved
payload.

The payload carries per-court variants of several fields (Court of Appeals
vs Supreme Court parties/status/number); the parser selects the variant for
the ``court`` it is bound to.
"""

from __future__ import annotations

from jkent.common.deferred_validation import DeferredValidation

from juriscraper.state.michigan.courts_michigan_gov.models import (
    MichAttorney,
    MichDocket,
    MichDocketEntry,
    MichDocument,
    MichJudgment,
    MichParty,
    MichTrialCourtRef,
)

from ._common import clean_str, parse_filing_date


def _appoint_type(value: object) -> str | None:
    """Flatten the site's ``appointType`` object to its description string."""
    if isinstance(value, dict):
        return clean_str(value.get("description")) or clean_str(
            value.get("abbreviation")
        )
    return clean_str(value)


def _attorney(item: dict) -> MichAttorney:
    return MichAttorney(
        name=clean_str(item.get("name")) or "",
        p_number=item.get("pNumber"),
        appoint_type=_appoint_type(item.get("appointType")),
    )


def _party(item: dict) -> MichParty:
    attorneys = [
        _attorney(a)
        for a in (item.get("attorneys") or [])
        if isinstance(a, dict) and a.get("name")
    ]
    return MichParty(
        name=clean_str(item.get("name")) or "",
        number=item.get("number"),
        connections=clean_str(item.get("connectionsValue")),
        self_represented=item.get("selfRepresentedParty"),
        prisoner_id=clean_str(item.get("prisonerID")),
        attorneys=attorneys,
    )


def _documents(entry: dict) -> list[MichDocument]:
    """Extract linked documents from a docket entry.

    The public JSON keys documents under ``documents`` / ``episerverDocuments``;
    both are modeled leniently since a case with linked PDFs is needed to pin
    the exact shape. Common keys (name/title, url/href, type) are mapped.
    """
    docs: list[MichDocument] = []
    for key in ("documents", "episerverDocuments"):
        for d in entry.get(key) or []:
            if not isinstance(d, dict):
                continue
            description = (
                clean_str(d.get("description"))
                or clean_str(d.get("name"))
                or clean_str(d.get("title"))
            )
            url = clean_str(d.get("url")) or clean_str(d.get("href"))
            if description is None and url is None:
                continue
            docs.append(
                MichDocument(
                    description=description,
                    url=url,
                    document_type=clean_str(d.get("documentType"))
                    or clean_str(d.get("type")),
                )
            )
    return docs


def _docket_entry(item: dict) -> MichDocketEntry:
    attorney = item.get("attorney")
    filing_attorney = (
        clean_str(attorney.get("name")) if isinstance(attorney, dict) else None
    )
    return MichDocketEntry(
        event_number=item.get("eventNumber"),
        date_event=parse_filing_date(item.get("eventDate")),
        event_description=clean_str(item.get("eventDescription")),
        event_abbreviation=clean_str(item.get("eventAbbreviation")),
        event_type=clean_str(item.get("eventType")),
        docket_type=clean_str(item.get("docketType")),
        date_service=parse_filing_date(item.get("serviceDate")),
        filing_attorney=filing_attorney,
        fee_code=clean_str(item.get("feeCode")),
        is_open=item.get("isOpen"),
        documents=_documents(item),
    )


def _judgment(item: dict) -> MichJudgment:
    return MichJudgment(
        case_type=clean_str(item.get("caseType")),
        trial_court_name=clean_str(item.get("trialCourtName")),
        trial_court_case_number=clean_str(item.get("trialCourtCaseNumber")),
        trial_court_judge_name=clean_str(item.get("trialCourtJudgeName")),
    )


def _int_list(value: object) -> list[int]:
    return [v for v in (value or []) if isinstance(v, int)]


class CaseDetailParser:
    """Parse the ``get*casedetaildata`` JSON into a full ``MichDocket``.

    Bound to a CourtListener ``court`` id, which selects the per-court
    party/status/number variant of the payload.
    """

    def __init__(self, court: str) -> None:
        self.court = court

    def __call__(self, data: dict) -> list[DeferredValidation[MichDocket]]:
        is_coa = self.court == "michctapp"
        number = (
            data.get("courtOfAppealsCaseNumber")
            if is_coa
            else data.get("supremeCourtCaseNumber")
        )
        if not number:
            return []

        status = (
            data.get("courtOfAppealsStatus")
            if is_coa
            else data.get("supremeCourtStatus")
        )
        raw_parties = (
            data.get("courtOfAppealsParties")
            if is_coa
            else data.get("supremeCourtParties")
        ) or []

        case_name = clean_str(data.get("title")) or f"{self.court} {number}"
        trial_courts = [
            MichTrialCourtRef(name=name)
            for name in (data.get("courts") or [])
            if isinstance(name, str) and name.strip()
        ]

        docket = MichDocket.raw(
            docket_number=str(number),
            court=self.court,
            case_name=case_name,
            date_filed=parse_filing_date(data.get("filingDate")),
            case_status=clean_str(status),
            date_last_updated=parse_filing_date(data.get("caseLastUpdated")),
            has_opinions=bool(data.get("opinionDockets"))
            or bool(data.get("opinionDocketsWithDocuments")),
            has_orders=bool(data.get("orderDockets"))
            or bool(data.get("orderDocketsWithDocuments")),
            coa_case_number=data.get("courtOfAppealsCaseNumber"),
            msc_case_number=data.get("supremeCourtCaseNumber"),
            coc_case_number=clean_str(data.get("courtOfClaimsCaseNumber")),
            trial_courts=trial_courts,
            case_types=[
                s for s in (data.get("caseTypes") or []) if clean_str(s)
            ],
            parties=[_party(p) for p in raw_parties if isinstance(p, dict)],
            docket_entries=[
                _docket_entry(d)
                for d in (data.get("dockets") or [])
                if isinstance(d, dict)
            ],
            judges=[s for s in (data.get("judges") or []) if clean_str(s)],
            judgments=[
                _judgment(j)
                for j in (data.get("judgments") or [])
                if isinstance(j, dict)
            ],
            related_coa_case_numbers=_int_list(
                data.get("uniqueCourtOfAppealsCaseNumbers")
            ),
            related_msc_case_numbers=_int_list(
                data.get("uniqueSupremeCourtCaseNumbers")
            ),
            has_detail=True,
        )
        return [docket]
