"""Offline test for the Maryland Case Search case-detail parser.

The site is JSON-only and gated by DataDome, so there's no offline HTML
fixture to drive a live ``kent`` run cheaply. Instead this exercises
``CaseDetailParser`` directly against a small representative payload, the same
way a ``JKentParser.from_string`` test would for an HTML site.

Run with:
    uv run python -m juriscraper.state.maryland.casesearch_courts_state_md_us.test
"""

from __future__ import annotations

from .parsers import CaseDetailParser

_SAMPLE_PAYLOAD: dict = {
    "caseDetail": {
        "caseNumber": "ACM-REG-2487-2024",
        "caseTitle": "KIRBY v. State of Maryland",
        "filedDate": "06/14/2024",
        "internalId": 123456,
        "courtSystem": "Appellate Court of Maryland",
        "caseCategory": "AP",
        "caseType": "Appeal of Criminal Case",
        "caseStatus": {"caseStatusType": "Open", "date": "06/14/2024"},
        "caseEventInfo": [
            {
                "fileDate": "06/14/2024",
                "documentName": "Notice of Appeal",
                "internalEventID": 9001,
                "createdDate": "2024-06-14T10:00:00",
            }
        ],
        "hearing": [
            {
                "eventType": "Oral Argument",
                "eventDate": "11/01/2024",
                "eventTime": "10:00 AM",
                "location": "Annapolis",
                "result": None,
                "internalHearingEventID": 7001,
            }
        ],
        "judgmentEventInfo": [
            {
                "judgmentEventType": "Affirmed",
                "issueDate": "12/15/2024",
                "comment": ["Judgment of the circuit court affirmed."],
            }
        ],
        "involvedParties": [
            {
                "partyName": "Kirby, John",
                "partyType": "Appellant",
                "partyTypeCode": "APL",
                "involvedPartyAddresses": [],
                "attorneyInfo": [
                    {
                        "attorneyName": "Jane Doe",
                        "appearanceDate": "06/20/2024",
                        "removalDate": None,
                        "attorneyAddress": [
                            {
                                "addressType": "Business",
                                "addressLine1": "1 Main St",
                                "city": "Baltimore",
                                "state": "MD",
                                "zip": "21201",
                                "currentAddress": "Yes",
                            }
                        ],
                    }
                ],
            }
        ],
        "relatedCases": [
            {"caseNumber": "C-02-CR-23-000123", "reason": "Trial court"}
        ],
        "caseCrossReferences": [],
    }
}


def main() -> None:
    deferred = CaseDetailParser.from_json(_SAMPLE_PAYLOAD)
    assert len(deferred) == 1, "expected one docket"
    docket = deferred[0].confirm()
    assert docket.docket_number == "ACM-REG-2487-2024"
    assert docket.court == "mdctspecapp"
    assert docket.case_name  # harmonized, non-empty
    assert docket.date_filed is not None
    assert len(docket.entries) == 1
    assert len(docket.hearings) == 1
    assert len(docket.judgments) == 1
    assert len(docket.parties) == 1
    assert docket.parties[0].attorneys[0].name == "Jane Doe"
    assert len(docket.related_cases) == 1
    print("OK:", docket.docket_number, "->", docket.court)


if __name__ == "__main__":
    main()
