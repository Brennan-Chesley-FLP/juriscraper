"""Offline parser tests for the C-Track HTML-form appellate scrapers.

Covers South Carolina (ctrack.sccourts.org) and the District of Columbia
(efile.dcappeals.gov). The HTML fixtures are compact but structurally
faithful to the live pages (table shapes, class names, and the
documentLink icon ``name`` encodings documented in each scraper's
CC_NOTES.md), so they exercise the real XPath in each ``JKentParser``.
"""

import unittest

from juriscraper.state.district_of_columbia.efile_dcappeals_gov.parsers import (  # noqa: E501
    CaseDetailParser as DCCaseDetailParser,
)
from juriscraper.state.district_of_columbia.efile_dcappeals_gov.parsers import (  # noqa: E501
    SearchListingParser as DCSearchListingParser,
)
from juriscraper.state.south_carolina.ctrack_sccourts_org.parsers import (
    CaseDetailParser as SCCaseDetailParser,
)
from juriscraper.state.south_carolina.ctrack_sccourts_org.parsers import (
    SearchListingParser as SCSearchListingParser,
)

# ---------------------------------------------------------------------------
# South Carolina fixtures
# ---------------------------------------------------------------------------

SC_LISTING_HTML = """
<html><body>
<table id="results">
  <tr class="TableSubHeading"><td>Court</td><td>Appellate Case No.</td>
    <td>Short Title</td><td>Group</td><td>Type</td><td>Subtype</td>
    <td>Filed Date</td><td>Status</td></tr>
  <tr>
    <td>Supreme Court</td>
    <td><a href="/public/caseView.do?csIID=70001">2026-000911</a></td>
    <td>Miller v. Blanton</td><td>Appeal</td><td>Common Pleas</td>
    <td>Other</td><td>04/02/2026</td><td>Pending</td>
  </tr>
  <tr>
    <td>Court of Appeals</td>
    <td><a href="/public/caseView.do?csIID=70002">2026-000912</a></td>
    <td>State v. Doe</td><td>Appeal</td><td>General Sessions</td>
    <td>Other</td><td>04/03/2026</td><td>Pending</td>
  </tr>
</table>
<a href="javascript:postPaging(201,200)">Next</a>
</body></html>
"""

SC_DETAIL_HTML = """
<html><body>
<span id="csNumber">2026-000911</span>
<table class="FormTable">
  <tr><td class="Label">Court:</td><td>Supreme Court</td>
      <td class="Label">Classification:</td>
      <td>Appeal - Common Pleas - Other</td></tr>
  <tr><td class="Label">Short Title:</td><td>Miller v. Blanton</td></tr>
  <tr><td class="Label">Case Status:</td><td>Pending</td></tr>
  <tr><td class="Label">Filed Date:</td><td>04/02/2026</td>
      <td class="Label">Oral Argument Date:</td><td>05/10/2026</td></tr>
  <tr><td class="Label">Disposition Date:</td><td></td>
      <td class="Label">Disposition Type:</td><td></td></tr>
  <tr><td class="Label">Remittitur Date:</td><td></td></tr>
  <tr><td class="Label">Lower Court or Tribunal:</td>
      <td>Spartanburg (2022CP4200573)</td></tr>
</table>
<div id="fullTitle" style="display:none;">
  Charity Lynn Miller, Appellant, v. James S. Blanton, Respondent.
</div>
<table id="partyInfo"><tbody>
  <tr class="TableSubHeading"><td>Appellate Role</td><td>Party Name</td>
      <td>Former</td><td>Attorney(s)</td></tr>
  <tr><td>Appellant</td><td>Charity Lynn Miller</td><td>N</td>
      <td>Jane Roe\nJohn Poe</td></tr>
  <tr><td>Respondent</td><td>James S. Blanton</td><td>Y</td>
      <td>Self Represented</td></tr>
</tbody></table>
<table class="FormTable">
  <tr><td>Filed Date</td><td>Event Information</td><td>Doc</td></tr>
  <tr><td>04/02/2026</td><td>Notice of Appeal (Civil) - Initial</td>
      <td><img class="documentLink" name="deID:555001"
           src="/public/images/document.png"></td></tr>
  <tr><td>04/05/2026</td><td>Correspondence - Outgoing</td><td></td></tr>
</table>
</body></html>
"""


class SouthCarolinaParserTest(unittest.TestCase):
    def test_search_listing(self):
        rows = [
            dv.raw_data
            for dv in SCSearchListingParser.from_string(
                SC_LISTING_HTML, "https://ctrack.sccourts.org/"
            )
        ]
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            rows[0],
            {
                "court": "sc",
                "docket_number": "2026-000911",
                "site_case_id": "70001",
            },
        )
        self.assertEqual(rows[1]["court"], "scctapp")
        self.assertEqual(rows[1]["site_case_id"], "70002")

    def test_case_detail(self):
        raw = SCCaseDetailParser.from_string(SC_DETAIL_HTML)[0].raw_data
        self.assertEqual(raw["docket_number"], "2026-000911")
        self.assertEqual(raw["court"], "sc")
        self.assertEqual(raw["case_name"], "Miller v. Blanton")
        self.assertIn("Charity Lynn Miller", raw["case_name_full"])
        self.assertEqual(
            raw["classification"], "Appeal - Common Pleas - Other"
        )
        self.assertEqual(raw["date_filed"].isoformat(), "2026-04-02")
        self.assertEqual(raw["date_argued"].isoformat(), "2026-05-10")
        self.assertIsNone(raw["date_disposed"])
        self.assertEqual(raw["appeal_from_str"], "Spartanburg (2022CP4200573)")

        parties = raw["parties"]
        self.assertEqual(len(parties), 2)
        self.assertEqual(parties[0].role, "Appellant")
        self.assertEqual(parties[0].attorneys, ["Jane Roe", "John Poe"])
        self.assertFalse(parties[0].is_former)
        self.assertTrue(parties[1].is_former)

        entries = raw["docket_entries"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].event_id, "555001")
        self.assertTrue(entries[0].has_documents)
        self.assertIsNone(entries[1].event_id)
        self.assertFalse(entries[1].has_documents)


# ---------------------------------------------------------------------------
# District of Columbia fixtures
# ---------------------------------------------------------------------------

DC_LISTING_HTML = """
<html><body>
<table id="results">
  <tr><td>Case No.</td><td>Short Caption</td><td>Group</td><td>Type</td>
      <td>Subtype</td><td>Status</td><td>Sup. Ct. / Agency No.</td></tr>
  <tr>
    <td><a href="/public/caseView.do?csIID=71088">26-CV-0339</a></td>
    <td>Smith v. Acme Corp</td><td>Appeals</td><td>Civil</td>
    <td>Other Civil</td><td>Pending</td><td>2024-CA-000378</td>
  </tr>
</table>
<a href="javascript:postPaging(201,200)">Next</a>
</body></html>
"""

DC_DETAIL_HTML = """
<html><head><title>26-CV-0339: Case View</title></head><body>
<input type="hidden" name="csIID" value="71088">
<table>
  <tr><td class="label">Short Caption:</td><td>Smith v. Acme Corp</td>
      <td class="label">Classification:</td>
      <td>Appeals - Civil - Other Civil</td></tr>
  <tr><td class="label">Superior Court or Agency Case Number:</td>
      <td>2024-CA-000378</td></tr>
  <tr><td class="label">Filed Date:</td><td>04/02/2026</td>
      <td class="label">Case Status:</td><td>Pending</td></tr>
  <tr><td class="label">Argued/Submitted:</td><td>05/12/2026</td>
      <td class="label">Mandate Issued:</td><td></td></tr>
  <tr><td class="label">Costs Waived</td></tr>
</table>
<table>
  <tr><td>Party Information</td></tr>
  <tr><td>Appellate Role</td><td>Party Name</td><td>IFP</td>
      <td>Attorney(s)</td><td>Arguing Attorney</td><td>E-Filer</td></tr>
  <tr><td>Appellant</td><td>John Smith</td><td>Y</td>
      <td>Jane Attorney</td><td></td><td>Y</td></tr>
  <tr><td>Appellee</td><td>Acme Corp</td><td>N</td>
      <td><table>
            <tr><td>Atty One</td><td></td><td>Y</td></tr>
            <tr><td>Atty Two</td><td></td><td>N</td></tr>
          </table></td></tr>
</table>
<table>
  <tr><td>Events</td></tr>
  <tr><td>Event Date</td><td>Status</td><td>Description</td><td>Result</td>
      <td>PDF</td></tr>
  <tr><td>04/02/2026</td><td>Filed</td><td>Notice Of Appeal</td><td></td>
      <td><img class="documentLink" name="50:660001:71088"
           src="/images/document.png"></td></tr>
  <tr><td>04/10/2026</td><td>Filed</td><td>Briefing Order</td><td></td>
      <td></td></tr>
</table>
</body></html>
"""


class DistrictOfColumbiaParserTest(unittest.TestCase):
    def test_search_listing(self):
        rows = [
            dv.raw_data
            for dv in DCSearchListingParser.from_string(
                DC_LISTING_HTML, "https://efile.dcappeals.gov/"
            )
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0],
            {
                "court": "dc",
                "docket_number": "26-CV-0339",
                "site_case_id": "71088",
            },
        )

    def test_case_detail(self):
        raw = DCCaseDetailParser.from_string(DC_DETAIL_HTML)[0].raw_data
        self.assertEqual(raw["docket_number"], "26-CV-0339")
        self.assertEqual(raw["court"], "dc")
        self.assertEqual(raw["case_name"], "Smith v. Acme Corp")
        self.assertEqual(
            raw["classification"], "Appeals - Civil - Other Civil"
        )
        self.assertEqual(raw["lower_court_case_number"], "2024-CA-000378")
        self.assertEqual(raw["date_filed"].isoformat(), "2026-04-02")
        self.assertEqual(raw["date_argued"].isoformat(), "2026-05-12")
        self.assertTrue(raw["costs_waived"])

        parties = raw["parties"]
        self.assertEqual(len(parties), 2)
        # Flat party.
        self.assertEqual(parties[0].role, "Appellant")
        self.assertEqual(parties[0].attorneys, ["Jane Attorney"])
        self.assertIs(parties[0].ifp, True)
        self.assertIs(parties[0].e_filer, True)
        # Nested-attorney party.
        self.assertEqual(parties[1].name, "Acme Corp")
        self.assertEqual(parties[1].attorneys, ["Atty One", "Atty Two"])
        self.assertIs(parties[1].e_filer, False)  # last nested row wins

        entries = raw["docket_entries"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].event_id, "660001")
        self.assertEqual(entries[0].document_link_flag, "50")
        self.assertTrue(entries[0].has_documents)
        self.assertEqual(entries[0].status, "Filed")
        self.assertFalse(entries[1].has_documents)
        self.assertIsNone(entries[1].event_id)


if __name__ == "__main__":
    unittest.main()
