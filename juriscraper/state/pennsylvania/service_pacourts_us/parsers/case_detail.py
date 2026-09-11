"""Parser for the PA appellate case-detail document.

``GET /public/v1/cases/{docket_number}`` returns the whole case in one JSON
document — register of actions, parties, attorneys, dispositions, briefing
schedule, lower-court origins and related dockets all inline. This module
maps that document onto :class:`PACMSDocket` and its child models.

Not a ``JKentParser`` subclass — see ``_common.py`` for why.
"""

from __future__ import annotations

from typing import Any

from juriscraper.state.pennsylvania.service_pacourts_us.models import (
    DOCKET_TYPES,
    SITE_COURT_NAME_TO_COURT_ID,
    PACMSAddress,
    PACMSAssessmentTotals,
    PACMSAttorney,
    PACMSBriefingScheduleItem,
    PACMSDisposition,
    PACMSDocketEntry,
    PACMSFiler,
    PACMSOriginalRecordItem,
    PACMSOriginatingCourt,
    PACMSParty,
    PACMSProcessingStatus,
    PACMSRelatedCase,
    PACMSService,
    PACMSSupremeCourtInfo,
)

from ._common import (
    as_dict,
    as_list,
    clean_str,
    dig,
    entity_id,
    lines_of,
    name_of,
    name_parts,
    parse_date,
    parse_time,
)

#: The four singleton registry-entry slots the API surfaces alongside the
#: ``registryEntries`` array. Each is the *same shape* as a register row and
#: duplicates one of its members, so they are folded into ``docket_entries``
#: tagged with ``entry_role`` rather than modelled separately.
_SINGLETON_ENTRY_SLOTS: dict[str, str] = {
    "finalDispositionRegistryEntry": "final_disposition",
    "remittalRegistryEntry": "remittal",
    "reArgumentPetitionRegistryEntry": "reargument_petition",
    "reArgumentDispositionRegistryEntry": "reargument_disposition",
}


def parse_docket_number(
    docket_number: str | None,
) -> tuple[str | None, int | None]:
    """Split ``"1 MAP 2024"`` into its type prefix and year.

    Returns ``(None, None)`` for anything that isn't a three-token appellate
    docket number — notably the ``CP-``/``MJ-`` trial-court numbers the search
    endpoint also returns.
    """
    if not docket_number:
        return None, None
    parts = docket_number.split()
    if len(parts) != 3:
        return None, None
    _sequence, docket_type, year = parts
    if docket_type not in DOCKET_TYPES:
        return None, None
    return docket_type, int(year) if year.isdigit() else None


def court_id_for(
    case: dict[str, Any], docket_number: str | None
) -> str | None:
    """Resolve the CourtListener court id for a case document.

    Prefers the court name the API reports on the case itself; falls back to
    the docket-number type prefix, which encodes the court independently.
    """
    court_name = clean_str(dig(case, "courtOffice", "court", "displayName"))
    if court_name and court_name in SITE_COURT_NAME_TO_COURT_ID:
        return SITE_COURT_NAME_TO_COURT_ID[court_name]
    docket_type, _year = parse_docket_number(docket_number)
    if docket_type:
        return DOCKET_TYPES[docket_type][0]
    return None


def _address(raw: Any) -> PACMSAddress:
    """Map one ``caseMemberAddresses`` element."""
    address = as_dict(raw)
    return PACMSAddress(
        address_lines=lines_of(address.get("addressLines")),
        address_type=clean_str(address.get("addressType")),
        employer_name=name_of(address.get("employerName")),
        phone=clean_str(address.get("primaryPhoneNumber")),
        secondary_phone=clean_str(address.get("secondaryPhoneNumber")),
        fax=clean_str(address.get("primaryFaxNumber")),
        receives_email=address.get("receivesEMail"),
        receives_fax=address.get("receivesFax"),
        receives_mail=address.get("receivesMail"),
    )


def _attorney(raw: Any) -> PACMSAttorney:
    """Map one ``caseParticipantAttorneys`` element."""
    attorney = as_dict(raw)
    return PACMSAttorney(
        **name_parts(attorney.get("participantName")),
        pa_bar_number=clean_str(attorney.get("paBarNumber")),
        is_active=attorney.get("isActive"),
        representation_type=clean_str(attorney.get("representationType")),
        date_entry_of_appearance=parse_date(
            attorney.get("entryOfAppearanceFiledDateTime")
        ),
        date_withdrawal_of_appearance=parse_date(
            attorney.get("withdrawalOfAppearanceFiledDateTime")
        ),
        ifp_status_type=clean_str(attorney.get("ifpStatusType")),
        represented_party_name=name_of(attorney.get("caseParticipantName")),
        represented_party_role=clean_str(
            dig(attorney, "caseParticipantRole", "name")
        ),
        addresses=[
            _address(a) for a in as_list(attorney.get("caseMemberAddresses"))
        ],
        phone_numbers=lines_of(attorney.get("phoneNumbers")),
    )


def participant_key(name_object: Any) -> str:
    """Build the join key linking an attorney appearance to its participant.

    PACMS gives every participant a stable numeric id inside its name object,
    and each attorney record echoes that id under ``caseParticipantName`` —
    so the id is the reliable join. Names are the fallback only: two parties
    on one caption can share a ``documentName`` (consolidated appeals, or a
    party appearing in two roles), which would silently merge their
    representation.
    """
    identifier = entity_id(as_dict(name_object).get("id"))
    if identifier:
        return f"id:{identifier}"
    return f"name:{name_of(name_object) or ''}"


def _party(
    raw: Any, attorneys_by_participant: dict[str, list[PACMSAttorney]]
) -> PACMSParty:
    """Map one ``caseParticipants`` element, attaching its attorneys."""
    party = as_dict(raw)
    return PACMSParty(
        **name_parts(party.get("participantName")),
        role=clean_str(dig(party, "role", "name")),
        role_sort_order=dig(party, "role", "sortOrder"),
        is_pro_se=party.get("isProSe"),
        aliases=[
            alias
            for alias in (name_of(a) for a in as_list(party.get("aliases")))
            if alias
        ],
        date_of_birth=parse_date(party.get("primaryDateOfBirth")),
        gender=clean_str(party.get("gender")),
        race=clean_str(party.get("race")),
        fingerprint_status=clean_str(party.get("fingerprintStatus")),
        ifp_status_type=clean_str(party.get("ifpStatusType")),
        addresses=[
            _address(a) for a in as_list(party.get("caseMemberAddresses"))
        ],
        attorneys=attorneys_by_participant.get(
            participant_key(party.get("participantName")), []
        ),
    )


def _filer(raw: Any) -> PACMSFiler:
    """Map one registry-entry ``filers`` element."""
    filer = as_dict(raw)
    return PACMSFiler(
        filer_type=clean_str(filer.get("filerType")),
        name=name_of(filer.get("participantName")),
        participant_role=clean_str(filer.get("participantRole")),
        representing=[
            name
            for name in (
                name_of(r) for r in as_list(filer.get("representing"))
            )
            if name
        ],
    )


def _service(raw: Any) -> PACMSService:
    """Map one registry-entry ``service`` element."""
    service = as_dict(raw)
    return PACMSService(
        sent_method_name=clean_str(service.get("sentMethodName")),
        date_sent=parse_date(service.get("sentDateTime")),
        status=clean_str(service.get("status")),
        date_status=parse_date(service.get("statusDateTime")),
        served_by_name=name_of(service.get("servedByName")),
        served_to_name=name_of(service.get("servedToName")),
    )


def _docket_entry(raw: Any, entry_role: str) -> PACMSDocketEntry | None:
    """Map one registry entry.

    Returns ``None`` for the fully-null placeholder objects the API returns in
    the singleton slots when the case has no such entry.
    """
    entry = as_dict(raw)
    if not entry:
        return None
    code = clean_str(entry.get("registryEntryCode"))
    title = clean_str(entry.get("documentTitle"))
    description = title or code or clean_str(entry.get("description"))
    filed = entry.get("filedDateTime")
    date_filed = parse_date(filed)
    # A placeholder slot has no code, no title and no real filed date.
    if description is None and date_filed is None:
        return None
    return PACMSDocketEntry(
        date_filed=date_filed,
        time_filed=parse_time(filed),
        entry_number=entry.get("sequenceNumber"),
        description=description,
        registry_entry_code=code,
        document_title=title,
        document_number=clean_str(entry.get("documentNumber")),
        date_document=parse_date(entry.get("documentDateTime")),
        is_sealed=entry.get("isSealed"),
        date_order_exited=parse_date(entry.get("orderExitedDate")),
        comment_lines=[
            line
            for comment in as_list(entry.get("comments"))
            for line in lines_of(as_dict(comment).get("commentLines"))
        ],
        applies_to=[
            name
            for name in (
                name_of(as_dict(a).get("participantName"))
                for a in as_list(entry.get("appliesTo"))
            )
            if name
        ],
        filers=[_filer(f) for f in as_list(entry.get("filers"))],
        service=[_service(s) for s in as_list(entry.get("service"))],
        entry_role=entry_role,
    )


def _disposition(raw: Any) -> PACMSDisposition:
    """Map one ``dispositionEvents`` element."""
    event = as_dict(raw)
    return PACMSDisposition(
        disposition=clean_str(event.get("disposition")),
        disposition_category=clean_str(event.get("dispositionCategory")),
        date_disposition=parse_date(event.get("dispositionDate")),
        date_disposition_filed=parse_date(
            event.get("dispositionFiledDateTime")
        ),
        disposition_method=clean_str(event.get("dispositionMethod")),
        is_final=event.get("isFinal"),
        journal_number=clean_str(event.get("journalNumber")),
        date_judgment=parse_date(event.get("judgmentDateTime")),
        was_defendant_present=event.get("wasDefendantPresent"),
        disposing_authority_str=name_of(event.get("disposingAuthority")),
        filer_names=[
            name
            for name in (
                name_of(n) for n in as_list(event.get("dispositionFilerNames"))
            )
            if name
        ],
        comment_lines=lines_of(event.get("commentLines")),
    )


def _briefing_items(raw: Any) -> list[PACMSBriefingScheduleItem]:
    """Flatten ``briefingSchedule[].paperBooks[]`` into a single ledger.

    The outer ``briefingSchedule`` grouping carries no fields of its own
    beyond an id, so it is collapsed away.
    """
    items: list[PACMSBriefingScheduleItem] = []
    for schedule in as_list(raw):
        for book in as_list(as_dict(schedule).get("paperBooks")):
            paper_book = as_dict(book)
            items.append(
                PACMSBriefingScheduleItem(
                    type_name=clean_str(paper_book.get("typeName")),
                    date_due=parse_date(paper_book.get("currentDueDate")),
                    date_filed=parse_date(paper_book.get("filedDate")),
                    party_name=name_of(paper_book.get("caseParticipantName")),
                    party_role=clean_str(
                        dig(paper_book, "caseParticipantRole", "name")
                    ),
                )
            )
    return items


def _originating_court(raw: Any) -> PACMSOriginatingCourt:
    """Map one ``caseOriginations`` element."""
    origination = as_dict(raw)
    organization = as_dict(origination.get("originatingOrganization"))
    return PACMSOriginatingCourt(
        docket_number=clean_str(origination.get("originatingDocumentNumber")),
        court_name=name_of(organization.get("name")),
        court_office_name=clean_str(
            dig(organization, "courtOffice", "displayName")
        ),
        assigned_to_str=name_of(
            dig(origination, "originatingAuthority", "name")
        ),
        initial_authority_str=name_of(
            dig(origination, "initialOriginatingAuthority", "name")
        ),
        otn=clean_str(origination.get("otn")),
        ltn=clean_str(origination.get("ltn")),
    )


def _related_case(raw: Any, relationship: str) -> PACMSRelatedCase:
    """Map one ``caseHistory`` / ``crossCourtCaseHistory`` element."""
    related = as_dict(raw)
    court_name = clean_str(dig(related, "courtOffice", "court", "displayName"))
    return PACMSRelatedCase(
        docket_number=clean_str(related.get("docketNumber")),
        case_name=clean_str(related.get("shortCaption")),
        date_filed=parse_date(related.get("filingDate")),
        status_name=clean_str(related.get("statusName")),
        court=SITE_COURT_NAME_TO_COURT_ID.get(court_name or ""),
        court_name=court_name,
        court_office_name=clean_str(
            dig(related, "courtOffice", "displayName")
        ),
        api_url=clean_str(related.get("href")),
        relationship=relationship,
    )


def _supreme_court_info(raw: Any) -> PACMSSupremeCourtInfo | None:
    """Map ``supremeCourtInformation``, or ``None`` when it is a placeholder."""
    info = as_dict(raw)
    if not info or not any(
        info.get(key)
        for key in (
            "allocaturDocketNumber",
            "allocaturGrantDate",
            "appealJurisdictionNotedDate",
            "intermediateDocketNumber",
            "referringCourtName",
        )
    ):
        return None
    return PACMSSupremeCourtInfo(
        allocatur_docket_number=clean_str(info.get("allocaturDocketNumber")),
        date_allocatur_granted=parse_date(info.get("allocaturGrantDate")),
        allocatur_grant_order_lines=lines_of(
            info.get("allocaturGrantOrderLines")
        ),
        date_appealed_order=parse_date(info.get("appealedOrderDate")),
        date_appeal_jurisdiction_noted=parse_date(
            info.get("appealJurisdictionNotedDate")
        ),
        appeal_of_paragraph_lines=lines_of(info.get("appealOfParagraphLines")),
        comment_lines=lines_of(info.get("commentLines")),
        intermediate_court_name=clean_str(info.get("intermediateCourtName")),
        intermediate_docket_number=clean_str(
            info.get("intermediateDocketNumber")
        ),
        intermediate_disposition=clean_str(
            info.get("intermediateDisposition")
        ),
        date_reargument_denied=parse_date(info.get("reArgumentDeniedDate")),
        reargument_disposition=clean_str(info.get("reArgumentDisposition")),
        referring_court_name=clean_str(info.get("referringCourtName")),
        panel_member_names=[
            name
            for name in (
                name_of(n) for n in as_list(info.get("panelMemberNames"))
            )
            if name
        ],
    )


def _assessment_totals(raw: Any) -> list[PACMSAssessmentTotals]:
    """Map the category rollups under ``assessmentGrandTotals``."""
    totals = as_dict(raw)
    rows: list[PACMSAssessmentTotals] = []
    for category in as_list(totals.get("assessmentCategoryTotals")):
        row = as_dict(category)
        rows.append(
            PACMSAssessmentTotals(
                category=clean_str(row.get("category")),
                total_assessments=row.get("totalAssessments"),
                total_payments=row.get("totalPayments"),
                total_adjustments=row.get("totalAdjustments"),
                total_non_monetary=row.get("totalNonMonetary"),
                current_balance=row.get("currentBalance"),
            )
        )
    return rows


class CaseDetailParser:
    """Map a case-detail JSON document onto ``PACMSDocket`` field values.

    Call with the decoded response body; returns a plain ``dict`` of model
    field values, which the step merges and emits via ``PACMSDocket.raw()``.
    A dict (rather than a ``DeferredValidation``) is returned deliberately:
    ``DeferredValidation`` instances cannot be nested inside one another, so
    the step owns the single top-level ``.raw()`` call.
    """

    def __call__(self, case: dict[str, Any]) -> dict[str, Any]:
        """Extract every ``PACMSDocket`` field from ``case``."""
        docket_number = clean_str(case.get("docketNumber"))
        docket_type, year = parse_docket_number(docket_number)

        # Attorneys are a flat top-level list joined to participants by the
        # participant's id; group them so each party carries its own
        # representation.
        attorneys_by_participant: dict[str, list[PACMSAttorney]] = {}
        for raw_attorney in as_list(case.get("caseParticipantAttorneys")):
            key = participant_key(
                as_dict(raw_attorney).get("caseParticipantName")
            )
            attorneys_by_participant.setdefault(key, []).append(
                _attorney(raw_attorney)
            )

        parties = [
            _party(p, attorneys_by_participant)
            for p in as_list(case.get("caseParticipants"))
        ]

        # An appearance whose participant isn't in ``caseParticipants`` would
        # otherwise vanish. Keep it as a party-less attorney record rather
        # than dropping counsel from the case.
        matched_keys = {
            participant_key(as_dict(p).get("participantName"))
            for p in as_list(case.get("caseParticipants"))
        }
        orphaned = [
            attorney
            for key, group in attorneys_by_participant.items()
            if key not in matched_keys
            for attorney in group
        ]
        if orphaned:
            parties.append(
                PACMSParty(
                    name=None,
                    role=None,
                    attorneys=orphaned,
                )
            )

        entries = [
            entry
            for entry in (
                _docket_entry(e, "registry")
                for e in as_list(case.get("registryEntries"))
            )
            if entry is not None
        ]
        for slot, role in _SINGLETON_ENTRY_SLOTS.items():
            singleton = _docket_entry(case.get(slot), role)
            if singleton is not None:
                entries.append(singleton)

        dispositions = [
            _disposition(d) for d in as_list(case.get("dispositionEvents"))
        ]
        supreme_info = _supreme_court_info(case.get("supremeCourtInformation"))

        entry_dates = [e.date_filed for e in entries if e.date_filed]
        final_disposition_dates = [
            d.date_disposition
            for d in dispositions
            if d.is_final and d.date_disposition
        ]

        court_office = as_dict(case.get("courtOffice"))

        return {
            # --- Identity ---
            "docket_number": docket_number,
            "docket_number_raw": case.get("docketNumber"),
            "court": court_id_for(case, docket_number),
            "docket_type": docket_type,
            "district": (
                DOCKET_TYPES[docket_type][1] if docket_type else None
            ),
            "filing_year": year,
            "pacms_case_id": entity_id(case.get("id")),
            "case_system": clean_str(dig(case, "id", "caseSystem")),
            # --- Caption ---
            "case_name": clean_str(case.get("shortCaption")),
            "case_name_full": " ".join(lines_of(case.get("longCaptionLines")))
            or None,
            "caption_lines": lines_of(case.get("longCaptionLines")),
            # --- Dates ---
            "date_filed": parse_date(case.get("filingDate")),
            "date_docketed": parse_date(case.get("docketedDate")),
            "date_terminated": (
                min(final_disposition_dates)
                if final_disposition_dates
                else parse_date(case.get("dispositionDate"))
            ),
            "date_last_filing": max(entry_dates) if entry_dates else None,
            "date_cert_granted": (
                supreme_info.date_allocatur_granted if supreme_info else None
            ),
            "date_reargument_denied": (
                supreme_info.date_reargument_denied if supreme_info else None
            ),
            # The API ships both spellings of this key — the misspelled
            # ``lowerCourtApplealFilingDate`` and the corrected
            # ``lowerCourtAppealFilingDate``. Prefer the corrected one and
            # fall back, so the record survives either being dropped.
            "date_lower_court_appeal_filing": parse_date(
                case.get("lowerCourtAppealFilingDate")
                or case.get("lowerCourtApplealFilingDate")
            ),
            "date_order_application": parse_date(
                case.get("orderApplicationDate")
            ),
            "date_actual_received": parse_date(case.get("actualReceivedDate")),
            "date_initiation": parse_date(case.get("initiationDate")),
            "date_arrest": parse_date(case.get("arrestDate")),
            "date_complaint": parse_date(case.get("complaintDate")),
            "date_last_payment": parse_date(case.get("lastPaymentDateTime")),
            # --- Status & classification ---
            "status_name": clean_str(case.get("statusName")),
            "current_processing_status": clean_str(
                dig(case, "currentProcessingStatus", "processingStatus")
            ),
            "date_processing_status_change": parse_date(
                dig(case, "currentProcessingStatus", "statusChangeDateTime")
            ),
            "current_program_status": clean_str(
                case.get("currentProgramStatus")
            ),
            "case_category": clean_str(dig(case, "caseCategory", "name")),
            "docket_type_name": clean_str(
                dig(case, "caseCategory", "docketType", "name")
            ),
            "docket_type_category": clean_str(
                dig(case, "caseCategory", "docketType", "category")
            ),
            "case_types": [
                name
                for name in (
                    clean_str(as_dict(t).get("name"))
                    for t in as_list(case.get("caseTypes"))
                )
                if name
            ],
            "case_flags": lines_of(case.get("caseFlags")),
            "is_sealed_record": case.get("isSealedRecord"),
            "is_nebbia_in_effect": case.get("isNebbiaInEffect"),
            "claim_amount": case.get("claimAmount"),
            "order_type": clean_str(case.get("orderType")),
            "initiating_document_name": clean_str(
                case.get("initiatingDocumentName")
            ),
            "lower_tribunal_category": clean_str(
                dig(case, "lowerTribunalCategory", "name")
            ),
            # --- Court office ---
            "court_office_name": clean_str(court_office.get("displayName")),
            "court_office_code": clean_str(court_office.get("officeCode")),
            "court_office_type": clean_str(
                court_office.get("courtOfficeType")
            ),
            "court_name": clean_str(dig(court_office, "court", "displayName")),
            "county": clean_str(dig(case, "county", "name"))
            or clean_str(dig(court_office, "county", "name")),
            "judicial_district": clean_str(
                dig(court_office, "county", "judicialDistrict", "name")
            ),
            # --- People ---
            "assigned_to_str": name_of(case.get("nameOfAssignedJudge")),
            "panel_str": (
                ", ".join(supreme_info.panel_member_names)
                if supreme_info and supreme_info.panel_member_names
                else None
            ),
            # --- Origination ---
            "originating_docket_numbers": clean_str(
                case.get("originatingDocketNumbers")
            ),
            "root_originating_docket_number": clean_str(
                case.get("rootOriginatingDocumentNumber")
            ),
            "root_originating_authority_str": name_of(
                dig(case, "rootOriginatingAuthority", "name")
            ),
            "root_originating_organization_str": name_of(
                case.get("rootOriginatingOrganizationName")
            ),
            "appeal_from_str": name_of(
                case.get("rootOriginatingOrganizationName")
            ),
            # --- Tracking numbers ---
            "primary_otn": clean_str(case.get("primaryOtn")),
            "primary_ltn": clean_str(case.get("primaryLtn")),
            "primary_police_incident_no": clean_str(
                case.get("primaryPoliceIncidentNo")
            ),
            # --- Next event ---
            "next_event": clean_str(dig(case, "latestCaseEvent", "nextEvent")),
            "date_next_event_due": parse_date(
                dig(case, "latestCaseEvent", "nextEventDueDateTime")
            ),
            # --- Child collections ---
            "docket_entries": entries,
            "parties": parties,
            "dispositions": dispositions,
            "briefing_schedule": _briefing_items(case.get("briefingSchedule")),
            "originating_courts": [
                _originating_court(o)
                for o in as_list(case.get("caseOriginations"))
            ],
            "related_cases": [
                _related_case(c, "case_history")
                for c in as_list(case.get("caseHistory"))
            ]
            + [
                _related_case(c, "cross_court_case_history")
                for c in as_list(case.get("crossCourtCaseHistory"))
            ],
            "original_record_contents": [
                PACMSOriginalRecordItem(
                    contents=clean_str(as_dict(r).get("contents")),
                    description=clean_str(as_dict(r).get("description")),
                    date_filed=parse_date(as_dict(r).get("filedDate")),
                    date_remittal=parse_date(as_dict(r).get("remittalDate")),
                    comment_lines=lines_of(as_dict(r).get("commentLines")),
                )
                for r in as_list(case.get("originalRecordContents"))
            ],
            "processing_statuses": [
                PACMSProcessingStatus(
                    processing_status=clean_str(
                        as_dict(s).get("processingStatus")
                    ),
                    date_status_change=parse_date(
                        as_dict(s).get("statusChangeDateTime")
                    ),
                )
                for s in as_list(case.get("caseProcessingStatuses"))
            ],
            "assessment_totals": _assessment_totals(
                case.get("assessmentGrandTotals")
            ),
            "supreme_court_information": supreme_info,
        }
