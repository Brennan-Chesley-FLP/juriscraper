"""Parser for a Maryland Case Search case-detail JSON payload.

``GET /api-casedetails/v1/public/cases/{caseId}`` returns the full docket as
one JSON document (parties, attorneys, hearings, register-of-actions entries,
judgment events, related cases, cross-references). :class:`CaseDetailParser`
walks that payload into a single :class:`MdAppellateDocket`.

This site is JSON-only, so the parser operates on the decoded ``dict`` rather
than a ``PageElement``. ``JKentParser[T]`` (SCRAPER_STANDARDS §9) is bound to
the HTML ``PageElement`` API (its ``__call__``/``from_string`` assume markup),
so it does not fit a JSON feed. The parser still follows the §9 contract that
matters here: it lives under ``parsers/``, keeps all extraction out of the
``@step`` methods, returns ``DeferredValidation`` records, and is exercisable
offline via :meth:`from_json` against a saved payload.

The payload does not carry the dashless ``caseId`` URL key, the resolved
CourtListener ``court`` id, or the source URL/entry-point — the calling step
stamps those onto ``raw_data`` before emitting (see ``scraper.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation

from juriscraper.state.maryland.casesearch_courts_state_md_us.models import (
    COURT_PREFIX_TO_ID,
    MdAppellateAddress,
    MdAppellateAttorney,
    MdAppellateDocket,
    MdAppellateDocketEntry,
    MdAppellateHearing,
    MdAppellateJudgment,
    MdAppellateParty,
    MdAppellateRelatedCase,
)

from ._common import clean, parse_us_date

if TYPE_CHECKING:
    from collections.abc import Mapping


class CaseDetailParser:
    """Parse a case-detail JSON payload into one ``MdAppellateDocket``.

    Returns a single-element list with one deferred ``MdAppellateDocket``
    carrying the header scalars and the nested party / attorney / entry /
    hearing / judgment / related-case records. ``court``, ``case_id_param``,
    ``source_url``, and ``source_entry_point`` are stamped by the calling
    step.
    """

    def __call__(
        self, json_content: Mapping
    ) -> list[DeferredValidation[MdAppellateDocket]]:
        detail = json_content.get("caseDetail") or {}

        docket_number_raw = detail.get("caseNumber")
        docket_number = clean(docket_number_raw)

        court = self._derive_court(docket_number)
        status_block = detail.get("caseStatus") or {}

        docket = MdAppellateDocket.raw(
            docket_number=docket_number or "",
            docket_number_raw=docket_number_raw,
            court=court,
            case_name=detail.get("caseTitle") or docket_number or "",
            date_filed=parse_us_date(detail.get("filedDate")),
            internal_id=detail.get("internalId"),
            court_system=clean(detail.get("courtSystem")),
            case_category=clean(detail.get("caseCategory")),
            case_type=clean(detail.get("caseType")),
            case_status=clean(status_block.get("caseStatusType")),
            case_status_date=parse_us_date(status_block.get("date")),
            entries=self._parse_entries(detail.get("caseEventInfo")),
            hearings=self._parse_hearings(detail.get("hearing")),
            judgments=self._parse_judgments(detail.get("judgmentEventInfo")),
            parties=self._parse_parties(detail.get("involvedParties")),
            related_cases=self._parse_related(detail.get("relatedCases")),
            cross_references=self._parse_cross_refs(
                detail.get("caseCrossReferences")
            ),
        )
        return [docket]

    # =====================================================================
    # Offline testing
    # =====================================================================

    @classmethod
    def from_json(
        cls, json_content: Mapping
    ) -> list[DeferredValidation[MdAppellateDocket]]:
        """Run the parser on a decoded JSON payload (offline test hook)."""
        return cls()(json_content)

    # =====================================================================
    # Helpers
    # =====================================================================

    @staticmethod
    def _derive_court(docket_number: str | None) -> str | None:
        """Map a case number's 3-letter prefix to a CourtListener id."""
        if not docket_number:
            return None
        prefix = docket_number.split("-", 1)[0].upper()
        return COURT_PREFIX_TO_ID.get(prefix)

    # =====================================================================
    # Entries / hearings / judgments
    # =====================================================================

    @staticmethod
    def _parse_entries(
        events: list[dict] | None,
    ) -> list[MdAppellateDocketEntry]:
        if not events:
            return []
        return [
            MdAppellateDocketEntry(
                date_filed=parse_us_date(e.get("fileDate")),
                description=clean(e.get("documentName")),
                internal_event_id=e.get("internalEventID"),
                created_date=clean(e.get("createdDate")),
            )
            for e in events
        ]

    @staticmethod
    def _parse_hearings(
        hearings: list[dict] | None,
    ) -> list[MdAppellateHearing]:
        if not hearings:
            return []
        return [
            MdAppellateHearing(
                event_type=clean(h.get("eventType")),
                event_date=parse_us_date(h.get("eventDate")),
                event_time=clean(h.get("eventTime")),
                location=clean(h.get("location")),
                result=clean(h.get("result")),
                internal_hearing_event_id=h.get("internalHearingEventID"),
            )
            for h in hearings
        ]

    @staticmethod
    def _parse_judgments(
        judgments: list[dict] | None,
    ) -> list[MdAppellateJudgment]:
        if not judgments:
            return []
        out: list[MdAppellateJudgment] = []
        for j in judgments:
            comments = j.get("comment") or []
            out.append(
                MdAppellateJudgment(
                    judgment_event_type=clean(j.get("judgmentEventType")),
                    issue_date=parse_us_date(j.get("issueDate")),
                    comments=[
                        c for c in (str(x).strip() for x in comments) if c
                    ],
                )
            )
        return out

    # =====================================================================
    # Parties & attorneys
    # =====================================================================

    @classmethod
    def _parse_parties(
        cls, parties: list[dict] | None
    ) -> list[MdAppellateParty]:
        if not parties:
            return []
        return [
            MdAppellateParty(
                name=clean(p.get("partyName")) or "",
                party_type=clean(p.get("partyType")),
                party_type_code=clean(p.get("partyTypeCode")),
                addresses=cls._parse_addresses(
                    p.get("involvedPartyAddresses")
                ),
                attorneys=cls._parse_attorneys(p.get("attorneyInfo")),
            )
            for p in parties
        ]

    @classmethod
    def _parse_attorneys(
        cls, attorneys: list[dict] | None
    ) -> list[MdAppellateAttorney]:
        if not attorneys:
            return []
        return [
            MdAppellateAttorney(
                name=clean(a.get("attorneyName")) or "",
                appearance_date=parse_us_date(a.get("appearanceDate")),
                removal_date=parse_us_date(a.get("removalDate")),
                addresses=cls._parse_addresses(a.get("attorneyAddress")),
            )
            for a in attorneys
        ]

    @classmethod
    def _parse_addresses(
        cls, addresses: list[dict] | None
    ) -> list[MdAppellateAddress]:
        if not addresses:
            return []
        return [cls._parse_address(addr) for addr in addresses]

    @staticmethod
    def _parse_address(addr: dict) -> MdAppellateAddress:
        current = addr.get("currentAddress")
        is_current: bool | None = None
        if isinstance(current, str):
            is_current = current.strip().lower() == "yes"
        elif isinstance(current, bool):
            is_current = current
        return MdAppellateAddress(
            address_type=clean(addr.get("addressType")),
            address_line_1=clean(addr.get("addressLine1")),
            address_line_2=clean(addr.get("addressLine2")),
            address_line_3=clean(addr.get("addressLine3")),
            city=clean(addr.get("city")),
            state=clean(addr.get("state")),
            zip_code=clean(addr.get("zip")),
            is_current=is_current,
        )

    # =====================================================================
    # Related cases / cross-references
    # =====================================================================

    @staticmethod
    def _parse_related(
        related: list[dict] | None,
    ) -> list[MdAppellateRelatedCase]:
        if not related:
            return []
        out = [
            MdAppellateRelatedCase(
                docket_number=clean(r.get("caseNumber")) or "",
                reason=clean(r.get("reason")),
                internal_case_id=clean(r.get("caseID")),
            )
            for r in related
        ]
        return [r for r in out if r.docket_number]

    @staticmethod
    def _parse_cross_refs(
        refs: list[dict] | None,
    ) -> list[MdAppellateRelatedCase]:
        if not refs:
            return []
        out = [
            MdAppellateRelatedCase(
                docket_number=clean(r.get("crossCaseNumber")) or "",
                cross_reference_type=clean(r.get("caseCrossReferenceType")),
                internal_case_id=clean(r.get("caseCrossReferenceID")),
            )
            for r in refs
        ]
        return [r for r in out if r.docket_number]
