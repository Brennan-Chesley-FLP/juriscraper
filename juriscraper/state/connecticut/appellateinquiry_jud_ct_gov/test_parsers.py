"""Offline parser tests for the Connecticut appellate-inquiry scraper.

Exercises every parser against saved HTML fixtures via
``JKentParser.from_file`` (SCRAPER_STANDARDS §9). No network access.

Run:
    uv run python -m pytest \
        juriscraper/state/connecticut/appellateinquiry_jud_ct_gov/test_parsers.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .models import (
    ConnAppDocket,
    ConnTrialCourtDocket,
)
from .parsers import (
    ActivitiesParser,
    AppealCaseParser,
    TrialActivitiesParser,
    TrialCourtCaseParser,
)

ASSETS = Path(__file__).parent / "test_assets"
CRIMINAL = str(ASSETS / "appellate_criminal_SC250277.html")
CIVIL = str(ASSETS / "appellate_civil_AC49453.html")
TRIAL = str(ASSETS / "trial_HHDCV226160660S.html")


def _docket(path: str, crn: int) -> ConnAppDocket:
    """Build a fully-validated docket the way the step does (adding crn)."""
    bag = AppealCaseParser.from_file(path)[0].raw_data
    return ConnAppDocket(crn=crn, source_url="test", **bag)


def test_criminal_appeal_core_fields() -> None:
    d = _docket(CRIMINAL, 105336)
    assert d.docket_number == "SC 250277"
    assert d.docket_number_raw == "SC 250277"
    assert d.court == "conn"
    assert d.case_name == "STATE OF CONNECTICUT v. VANCE JOHNSON"
    assert d.case_status == "Denied"
    assert d.date_filed == date(2026, 1, 7)
    assert d.date_terminated == date(2026, 4, 28)
    assert d.appeal_by == "Defendant"


def test_criminal_appeal_originating_court_is_plain_text() -> None:
    # Criminal trial dockets render as plain text (no civilinquiry link).
    oc = _docket(CRIMINAL, 105336).originating_court
    assert oc is not None
    assert oc.docket_number == "HHDCR940462885T"
    assert oc.docket_number_url is None
    assert oc.case_type == "CRIMINAL"
    assert oc.assigned_to_str == "HON. FRANK M. D'ADDABBO"
    assert oc.date_judgment == date(2024, 5, 22)


def test_criminal_appeal_parties_and_attorneys() -> None:
    parties = _docket(CRIMINAL, 105336).parties
    assert [p.name for p in parties] == [
        "VANCE JOHNSON",
        "STATE OF CONNECTICUT",
    ]
    petitioner = parties[0]
    assert petitioner.party_type == "Petitioner/Movant"
    assert [(a.name, a.juris_number) for a in petitioner.attorneys] == [
        ("NAOMI T FETTERMAN", "430485"),
    ]
    # The State has multiple attorneys of record.
    assert len(parties[1].attorneys) == 2


def test_civil_appeal_links_to_civilinquiry() -> None:
    d = _docket(CIVIL, 105200)
    assert d.docket_number == "AC 49453"
    assert d.court == "connappct"
    oc = d.originating_court
    assert oc is not None
    assert oc.docket_number == "HHDCV226160660S"
    assert oc.docket_number_url is not None
    assert "civilinquiry.jud.ct.gov" in oc.docket_number_url
    assert "DocketNo=HHDCV226160660S" in oc.docket_number_url


def test_appeal_activities_and_documents() -> None:
    entries = ActivitiesParser.from_file(CRIMINAL)
    assert len(entries) == 3
    first = entries[0].raw_data
    assert first["activity_type"] == "PETITION"
    assert first["number"] == "SC 250277"
    assert first["date_filed"] == date(2026, 1, 7)
    assert first["action"] == "Denied"
    # Every activity here carries exactly one document link.
    assert all(len(e.raw_data["document_urls"]) == 1 for e in entries)
    assert "DocumentDisplayer.aspx" in first["document_urls"][0]


def test_civil_appeal_has_many_activities() -> None:
    entries = ActivitiesParser.from_file(CIVIL)
    assert len(entries) == 16
    assert entries[0].raw_data["activity_type"] == "APPEAL"


def test_trial_court_core_fields() -> None:
    bag = TrialCourtCaseParser.from_file(TRIAL)[0].raw_data
    d = ConnTrialCourtDocket(
        docket_number_raw="HHDCV226160660S",
        appellate_docket_number="AC 49453",
        source_url="test",
        **bag,
    )
    assert d.court == "connsuperct"
    assert d.docket_number == "HHD-CV22-6160660-S"
    assert d.case_type == "T28"
    assert d.case_type_description == "T28 - Torts - Malpractice - Medical"
    assert d.court_location == "HARTFORD JD"
    assert d.list_type == "JURY (JY)"
    assert d.date_filed == date(2022, 9, 19)
    assert d.return_date == date(2022, 10, 4)
    assert d.date_disposed == date(2025, 12, 1)
    assert d.disposition == "SUMMARY JUDGMENT-DEFENDANT"
    assert d.assigned_to_str == "HON STUART ROSEN"


def test_trial_court_parties_and_appellate_backref() -> None:
    bag = TrialCourtCaseParser.from_file(TRIAL)[0].raw_data
    parties = ConnTrialCourtDocket(source_url="t", **bag).parties
    assert len(parties) == 5
    p01 = parties[0]
    assert p01.party_number == "P-01"
    assert p01.party_type == "Plaintiff"
    assert p01.attorneys[0].firm == "MAKI LAW LLC"
    assert p01.attorneys[0].juris_number == "437597"
    assert p01.attorneys[0].date_filed == date(2022, 9, 19)
    # The appellate case appears as a "For Notice Only" / non-appearing party.
    notice = parties[-1]
    assert notice.party_number == "L-01"
    assert notice.non_appearing is True


def test_trial_court_documents() -> None:
    entries = TrialActivitiesParser.from_file(TRIAL)
    assert len(entries) == 101
    first = entries[0].raw_data
    assert first["filed_by"] == "P"
    assert first["description"] == "SUMMONS"
    assert "DocumentInquiry.aspx?DocumentNo=" in first["document_url"]
