"""Offline parser tests for the PA appellate JSON-API scraper.

Exercises the parsers against saved API responses. Because this is a JSON
API, the parsers are plain callables over the decoded body rather than
``JKentParser`` subclasses (see ``parsers/_common.py``), so the fixtures are
loaded with ``json.load`` instead of ``from_file``. No network access.

Run:
    uv run python -m pytest \
        juriscraper/state/pennsylvania/service_pacourts_us/test_parsers.py
"""

from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path
from typing import Any

from .models import PACMSDocket, PaDocketRange
from .parsers import (
    CaseDetailParser,
    SearchResultsParser,
    court_id_for,
    parse_date,
    parse_docket_number,
    parse_time,
)

ASSETS = Path(__file__).parent / "test_assets"


def _load(name: str) -> dict[str, Any]:
    """Read a saved API response fixture."""
    return json.loads((ASSETS / name).read_text())


def _docket(name: str = "case_1_MAP_2024.json") -> PACMSDocket:
    """Build a fully-validated docket the way ``parse_case`` does."""
    fields = CaseDetailParser()(_load(name))
    fields["source_url"] = "test"
    fields["source_entry_point"] = "docket_by_number"
    return PACMSDocket(**fields)


# =========================================================================
# Case detail — core fields
# =========================================================================


def test_case_core_fields() -> None:
    d = _docket()
    assert d.docket_number == "1 MAP 2024"
    assert d.court == "pa"
    assert d.docket_type == "MAP"
    assert d.district == "Middle"
    assert d.filing_year == 2024
    assert d.case_name == "M.T., Aplt. v. Pa State Police"
    assert d.date_filed == date(2024, 1, 2)
    assert d.status_name == "Closed"
    assert d.case_category == "Appeal"
    assert d.court_office_name == "Supreme Court Middle District"
    assert d.court_office_code == "AP-SUP-M"
    assert d.pacms_case_id == "100398741"
    assert d.case_system == "PACMS"


def test_case_flags_and_types() -> None:
    d = _docket()
    assert d.is_sealed_record is True
    assert d.case_flags == ["Sealed Record"]
    assert d.case_types == ["Megan's Law / SORNA", "State Police"]
    assert d.initiating_document_name == "Notice of Appeal"
    assert d.lower_tribunal_category == "Administrative Agency"


def test_long_caption_is_joined_and_kept_lineswise() -> None:
    d = _docket()
    assert len(d.caption_lines) == 3
    assert d.case_name_full is not None
    assert d.case_name_full.startswith("M. T., Appellant")
    assert "Pennsylvania State Police" in d.case_name_full


def test_date_terminated_comes_from_final_disposition() -> None:
    d = _docket()
    assert d.date_terminated == date(2024, 8, 20)


def test_date_last_filing_is_the_latest_entry() -> None:
    d = _docket()
    assert d.date_last_filing == max(
        e.date_filed for e in d.docket_entries if e.date_filed
    )


def test_allocatur_grant_maps_to_cert_granted() -> None:
    """PA allocatur is the CL ``date_cert_granted`` analogue."""
    d = _docket()
    assert d.date_cert_granted == date(2023, 11, 17)
    assert d.supreme_court_information is not None
    assert d.supreme_court_information.allocatur_docket_number == "98 MM 2023"
    assert d.supreme_court_information.allocatur_grant_order_lines


def test_misspelled_lower_court_date_key_is_tolerated() -> None:
    """The API ships both ``lowerCourtAppleal...`` (sic) and the fix."""
    case = _load("case_1_MAP_2024.json")
    expected = date(2024, 1, 2)
    assert (
        CaseDetailParser()(case)["date_lower_court_appeal_filing"] == expected
    )

    only_misspelled = dict(case)
    only_misspelled.pop("lowerCourtAppealFilingDate")
    assert (
        CaseDetailParser()(only_misspelled)["date_lower_court_appeal_filing"]
        == expected
    )

    only_correct = dict(case)
    only_correct.pop("lowerCourtApplealFilingDate")
    assert (
        CaseDetailParser()(only_correct)["date_lower_court_appeal_filing"]
        == expected
    )


# =========================================================================
# Docket entries
# =========================================================================


def test_registry_entries_and_singletons_are_merged() -> None:
    case = _load("case_1_MAP_2024.json")
    d = _docket()
    # 13 register rows + the final-disposition and remittal singletons; the
    # two reargument slots are null placeholders and must be dropped.
    assert len(case["registryEntries"]) == 13
    assert len(d.docket_entries) == 15
    roles = {e.entry_role for e in d.docket_entries}
    assert roles == {"registry", "final_disposition", "remittal"}


def test_null_placeholder_entries_are_dropped() -> None:
    """The year-1 sentinel date must not fabricate a reargument entry."""
    d = _docket()
    assert not [
        e for e in d.docket_entries if e.entry_role.startswith("reargument")
    ]


def test_docket_entry_detail() -> None:
    d = _docket()
    final = next(
        e for e in d.docket_entries if e.entry_role == "final_disposition"
    )
    assert final.registry_entry_code == "Affirmed"
    assert final.date_filed == date(2024, 8, 20)
    assert len(final.service) == 6
    assert final.service[0].sent_method_name == "eService"
    assert final.service[0].status == "Distributed"
    assert [f.filer_type for f in final.filers] == ["Court"]
    # This entry's only comment line is a single space; whitespace-only
    # comment lines carry no content and must not become empty strings.
    assert final.comment_lines == []


def test_entry_time_is_kept_but_midnight_is_not() -> None:
    d = _docket()
    timed = next(
        e
        for e in d.docket_entries
        if e.description
        and e.description.startswith("Order Granting Application for Leave")
    )
    assert timed.time_filed == time(11, 25)
    # A date-only field (T00:00:00) must not become a fake 00:00 time.
    assert parse_time("2024-02-05T00:00:00-05:00") is None


# =========================================================================
# Parties & attorneys
# =========================================================================


def test_parties_and_roles() -> None:
    d = _docket()
    assert [(p.name, p.role) for p in d.parties] == [
        ("M. T.", "Appellant"),
        ("Pennsylvania State Police", "Appellee"),
    ]
    assert d.parties[0].aliases == ["MARK TINGEY", "Mark Tingey"]
    assert d.parties[0].is_pro_se is False


def test_every_attorney_is_attached_to_a_party() -> None:
    case = _load("case_1_MAP_2024.json")
    d = _docket()
    assert sum(len(p.attorneys) for p in d.parties) == len(
        case["caseParticipantAttorneys"]
    )
    assert len(d.parties[1].attorneys) == 5


def test_attorney_detail() -> None:
    d = _docket()
    attorney = d.parties[0].attorneys[0]
    assert attorney.name == "Jason David Javie, Esq."
    assert attorney.last_name == "Javie"
    assert attorney.pa_bar_number == "309840"
    assert attorney.is_active is True
    assert attorney.represented_party_role == "Appellant"
    address = attorney.addresses[0]
    assert address.employer_name == "Friedman & Levin Associates"
    assert address.phone == "215-563-7642"
    assert address.fax == "215-563-9145"
    assert len(address.address_lines) == 3


def test_attorneys_join_by_participant_id_not_name() -> None:
    """Same-named participants must not pool their representation."""
    case = json.loads(json.dumps(_load("case_1_MAP_2024.json")))
    # Give both participants an identical display/document name, keeping
    # their distinct ids.
    for participant in case["caseParticipants"]:
        participant["participantName"]["documentName"] = "Same Name"
        participant["participantName"]["displayName"] = "Same Name"
    for attorney in case["caseParticipantAttorneys"]:
        attorney["caseParticipantName"]["documentName"] = "Same Name"
        attorney["caseParticipantName"]["displayName"] = "Same Name"
    d = PACMSDocket(**CaseDetailParser()(case))
    assert [len(p.attorneys) for p in d.parties] == [1, 5]


def test_orphaned_attorneys_are_kept_not_dropped() -> None:
    case = json.loads(json.dumps(_load("case_1_MAP_2024.json")))
    case["caseParticipants"] = case["caseParticipants"][:1]
    d = PACMSDocket(**CaseDetailParser()(case))
    assert sum(len(p.attorneys) for p in d.parties) == 6
    assert d.parties[-1].name is None  # the party-less catch-all


# =========================================================================
# Other collections
# =========================================================================


def test_disposition() -> None:
    d = _docket()
    assert len(d.dispositions) == 1
    disposition = d.dispositions[0]
    assert disposition.disposition == "Affirmed"
    assert disposition.disposition_category == "Decided"
    assert disposition.is_final is True
    assert disposition.date_judgment == date(2024, 8, 20)
    assert disposition.filer_names == ["Per Curiam"]
    assert disposition.comment_lines[0].startswith("AND NOW")


def test_briefing_schedule_is_flattened() -> None:
    d = _docket()
    assert len(d.briefing_schedule) == 4
    brief = d.briefing_schedule[0]
    assert brief.type_name == "Brief"
    assert brief.date_due == date(2024, 3, 18)
    assert brief.date_filed == date(2024, 3, 18)
    assert brief.party_role == "Appellant"
    # An outstanding obligation keeps its due date with no filed date.
    reply = next(
        b for b in d.briefing_schedule if b.type_name == "Reply Brief"
    )
    assert reply.date_due == date(2024, 5, 9)
    assert reply.date_filed is None


def test_originating_court() -> None:
    d = _docket()
    origin = d.originating_courts[0]
    assert origin.docket_number == "94 MD 2022"
    assert origin.court_name == "Commonwealth Court of Pennsylvania"
    assert origin.assigned_to_str == "The Honorable Ellen Ceisler"
    assert d.root_originating_docket_number == "94 MD 2022"


def test_related_cases_are_labelled_by_source_list() -> None:
    d = _docket()
    relationships = {r.relationship for r in d.related_cases}
    assert relationships == {"case_history", "cross_court_case_history"}
    related = next(
        r for r in d.related_cases if r.docket_number == "98 MM 2023"
    )
    assert related.court == "pa"
    assert related.api_url is not None


def test_assessment_totals_are_rolled_up() -> None:
    d = _docket()
    assert len(d.assessment_totals) == 1
    assert d.assessment_totals[0].category == "Costs/Fees"
    assert d.assessment_totals[0].total_assessments == 90.25


# =========================================================================
# Docket-number and court resolution
# =========================================================================


def test_parse_docket_number() -> None:
    assert parse_docket_number("1 MAP 2024") == ("MAP", 2024)
    assert parse_docket_number("496 MAL 2026") == ("MAL", 2026)
    # Trial-court numbers are not appellate and must be rejected.
    assert parse_docket_number("CP-12-MD-0000023-2026") == (None, None)
    assert parse_docket_number("1 ZZZ 2024") == (None, None)
    assert parse_docket_number(None) == (None, None)


def test_court_id_falls_back_to_docket_type() -> None:
    """A case whose court name is missing still resolves via its prefix."""
    case = json.loads(json.dumps(_load("case_1_MAP_2024.json")))
    case["courtOffice"]["court"]["displayName"] = None
    assert court_id_for(case, case["docketNumber"]) == "pa"


def test_null_sentinel_and_blank_dates() -> None:
    assert parse_date("0001-01-01T00:00:00-05:00") is None
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("not a date") is None
    # A local-time timestamp keeps its local calendar date.
    assert parse_date("2024-08-20T08:00:00-04:00") == date(2024, 8, 20)


# =========================================================================
# Search results
# =========================================================================


def test_search_results_court_filtered() -> None:
    payload = _load("search_supreme_smith.json")
    parser = SearchResultsParser()
    rows = parser(payload)
    assert len(rows) == 50
    assert parser.error_messages(payload) == []
    assert parser.hit_result_cap(payload) is False
    assert {r["court"] for r in rows} == {"pa"}
    assert rows[0]["docket_number"] == "496 MAL 2026"
    assert rows[0]["date_filed"] == date(2026, 8, 31)


def test_unfiltered_search_hits_cap_and_mixes_in_trial_courts() -> None:
    payload = _load("search_unfiltered_smith.json")
    parser = SearchResultsParser()
    rows = parser(payload)
    assert parser.hit_result_cap(payload) is True
    appellate = [r for r in rows if parse_docket_number(r["docket_number"])[0]]
    assert 0 < len(appellate) < len(rows)


def test_rejected_search_surfaces_error_messages() -> None:
    payload = _load("search_rejected_date_only.json")
    parser = SearchResultsParser()
    assert parser(payload) == []
    messages = parser.error_messages(payload)
    assert len(messages) == 1
    assert "Invalid search criteria" in messages[0]


# =========================================================================
# Speculative range
# =========================================================================


def test_docket_range_builds_numbers_and_survives_advancement() -> None:
    rng = PaDocketRange(
        court_id="pasuperct",
        docket_type="EDA",
        year=2024,
        min=3,
        soft_max=3,
        gap=25,
    )
    assert rng.docket_number_for(rng.min) == "3 EDA 2024"
    assert rng.search_key() == "EDA"
    # The driver advances via from_int/model_copy; all three discriminators
    # must survive or the walk would wander into another court's space.
    advanced = rng.from_int(11)
    assert advanced.court_id == "pasuperct"
    assert advanced.docket_type == "EDA"
    assert advanced.year == 2024
    assert advanced.docket_number_for(advanced.min) == "11 EDA 2024"
