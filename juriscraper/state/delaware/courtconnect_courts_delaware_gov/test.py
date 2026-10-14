"""Offline parser tests for the Delaware CourtConnect scraper.

The docket report is one self-contained page, so every parser is exercisable
with ``JKentParser.from_string`` against inline fixtures -- no run db needed.
The fixtures are trimmed from real pages fetched on 2026-09-14, keeping the
markup quirks the parsers actually contend with: unclosed ``<tr>``/``<td>``
tags, ``<br>``-split date/time and address cells, and the ``&nbsp;`` that opens
every value cell.
"""

from __future__ import annotations

import unittest
from datetime import date, time

from pydantic import ValidationError

from .models import DeNumberSpace as S
from .parsers import (
    CaseDescriptionParser,
    CaseEventsParser,
    DocketEntriesParser,
    PartiesParser,
    RelatedCasesParser,
)
from .parsers._common import (
    parse_date,
    parse_time,
    split_code_description,
)
from .scraper import (
    CHANCERY_LEGACY_MAX,
    DeCaseRange,
    DeCourtConnectScraper,
    seed_templates,
)

# A Court of Chancery docket report, trimmed to its four data sections. The
# unclosed tags are the site's, not a transcription error: they are why the
# parsers group sibling rows by cell count instead of reading nested rows.
CHANCERY_PAGE = """
<html><body>
<a name="selection">
<table>
<tr valign="top"><td>&nbsp;<td><b>Case ID:</b><td>&nbsp;2025-1110
<tr valign="top"><td>&nbsp;<td><b>Docket Start Date:</b><td>&nbsp;
</table>
<a name="description">
<table>
<tr valign="top"><td>&nbsp;<td><b>Case ID:</b><td>&nbsp;2025-1110
 - IMO 221 CHESTNUT STREET - NEW CASTLE, DE
<tr valign="top"><td>&nbsp;<td><b>Filing Date:</b><td>&nbsp;Tuesday  , September 30th, 2025
<tr valign="top"><td>&nbsp;<td><b>Type:</b>
<td>&nbsp;2A - CIVIL ACTIONS
<tr valign="top"><td>&nbsp;<td><b>Status:</b>
<td>&nbsp;CLOSED - CLOSED
</table>
<a name="related">
<b><u>Related Cases</u></b>
<i>No related cases were found.</i>
<a name="events">
<b><u>Case Event Schedule</u></b>
<i>No case events were found.</i>
<a name="parties">
<table nowrap="nowrap" border width=100%>
<tr>
<th align="right">Seq #</th><th align="right">Assoc</th>
<th align="left">Party End Date</th><th align="left">Type</th>
<th align="left">ID</th><th align="left">Name</th>
</tr>
<tr valign="top">
<td align="right">1</td><td align="right">3</td><td>&nbsp;</td>
<td>PLAINTIFF</td>
<td><a href="ck_public_qry_cpty.cp_personcase_details_idx?id_code=@4209677">@4209677</a></td>
<td><b>IMO 221 CHESTNUT STREET, NEW CASTLE, DE </b></td>
<tr align="left" valign="top">
<td align="right"><b>Address:</b></td>
<td COLSPAN=2><i>unavailable</i></td>
<td align="right"><b>Aliases:</b></td>
<td COLSPAN=2><i>none</i></td>
</tr>
<tr><td colspan="6">&nbsp;</td></tr>
<tr valign="top">
<td align="right">2</td><td>&nbsp;</td><td>15-JAN-2026</td>
<td>ATTORNEY</td>
<td><a href="ck_public_qry_cpty.cp_personcase_details_idx?id_code=002234">002234</a></td>
<td><b>GOUGE JR, DONALD L</b></td>
<tr align="left" valign="top">
<td align="right"><b>Address:</b></td>
<td COLSPAN=2>DONALD L. GOUGE JR LLC
<br />800 N. KING STREET
<br />WILMINGTON DE 19801</td>
<td align="right"><b>Aliases:</b></td>
<td COLSPAN=2>GOUGE, DON<br />GOUGE, DONALD</td>
</tr>
<tr><td colspan="6">&nbsp;</td></tr>
</table>
<a name="dockets">
<table nowrap="nowrap" border width=100%>
<tr>
<th align="left">Filing Date</th><th align="left">Description</th>
<th align="left">Name</th><th align="right">Monetary</th>
</tr>
<tr valign="top">
<td nowrap="nowrap">30-SEP-2025<br />11:37 AM</td>
<td COLSPAN=1>
CIVIL ACTION CASE FILED
<td>IMO 221 CHESTNUT STREET, NEW CASTLE, DE,  </td>
<td align=right nowrap>&nbsp;</td>
<tr>
<td><b>Entry:</b></td>
<td align="left" colspan="3">THE DOCKET AND PLEADINGS ARE AVAILABLE THROUGH:
1.\thttp://www.fileandservexpress.com

DATE DOCKETED: OCTOBER 2, 2025
</td>
</tr>
<tr><td colspan="4">&nbsp;</td></tr>
<tr valign="top">
<td nowrap="nowrap">02-OCT-2025<br />09:04 AM</td>
<td COLSPAN=1>
ORDER ENTERED
<td>&nbsp;</td>
<td align=right nowrap>$1728.52</td>
<tr><td colspan="4">&nbsp;</td></tr>
</table>
</body></html>
"""

# A docket report whose Related Cases and Case Event Schedule sections are both
# populated -- the markup of both taken verbatim from the run corpus (Chancery
# legacy case 6495 for the related cases, Superior Court N11A-04-016 for the
# event schedule). They are rare: of 54,502 stored pages, 2 list related cases
# and 65 carry a scheduled event.
#
# The two sections are built quite differently, which is the point of the
# fixture. Related Cases is *not a table* -- it is a bare run of ``<a>`` links
# separated by ``&nbsp;&nbsp;`` -- while the event schedule is a five-column
# table (Event, Date/Time, Room, Location, Judge) whose Date/Time cell is
# ``<br>``-split.
POPULATED_SECTIONS_PAGE = """
<html><body>
<a name="description">
<table>
<tr valign="top"><td>&nbsp;<td><b>Case ID:</b><td>&nbsp;2025-0001
<tr valign="top"><td>&nbsp;<td><b>Filing Date:</b><td>&nbsp;Monday, January 6th, 2025
<tr valign="top"><td>&nbsp;<td><b>Status:</b><td>&nbsp;<i>none</i>
</table>
<a name="related">
<br />
<br />
<b><u>Related Cases</u></b>
<br />
<br />
<a href="ck_public_qry_doct.cp_dktrpt_frames?backto=D&case_id=8918&begin_date=&end_date=" TARGET="_parent">8918</a>
&nbsp;&nbsp;
<a href="ck_public_qry_doct.cp_dktrpt_frames?backto=D&case_id=CPU4-13-003466&begin_date=&end_date=" TARGET="_parent">CPU4-13-003466</a>
&nbsp;&nbsp;
<a name="events">
<br />
<br />
<b><u>Case Event Schedule</u></b>
<br />
<br />
<table  nowrap="nowrap" border width=100% cellspacing=1 cellpadding=4>
<tr align="left">
<th>Event</th>
<th>Date/Time</th>
<th>Room</th>
<th>Location</th>
<th>Judge</th>
</tr>
<tr valign="top">
<td>MOTION TO STAY</td>
<td nowrap="nowrap">14-JUN-2011<br>09:00 AM</td>
<td>SCN COURTROOM TBD</td>
<td>SUPERIOR CT NEW CASTLE COUNTY</td>
<td nowrap="nowrap">SCOTT, CALVIN L</td>
</table>
<a name="parties">
<a name="dockets">
<b><u>Docket Entries</u></b>
<i>No docket entries found.</i>
</body></html>
"""


class TestCommonHelpers(unittest.TestCase):
    def test_parses_both_date_forms(self) -> None:
        self.assertEqual(parse_date("30-SEP-2025"), date(2025, 9, 30))
        self.assertEqual(
            parse_date("Tuesday  , September 30th, 2025"), date(2025, 9, 30)
        )
        self.assertEqual(
            parse_date("Monday, January 6th, 2025"), date(2025, 1, 6)
        )
        self.assertIsNone(parse_date("&nbsp;"))
        self.assertIsNone(parse_date(""))

    def test_parses_meridiem_times(self) -> None:
        self.assertEqual(parse_time("11:37 AM"), time(11, 37))
        self.assertEqual(parse_time("02:43 PM"), time(14, 43))
        self.assertEqual(parse_time("12:05 AM"), time(0, 5))
        self.assertEqual(parse_time("12:05 PM"), time(12, 5))
        self.assertIsNone(parse_time("  "))

    def test_splits_code_from_description(self) -> None:
        self.assertEqual(
            split_code_description("2A - CIVIL ACTIONS"),
            ("2A", "CIVIL ACTIONS"),
        )
        self.assertEqual(
            split_code_description("64 - JP GARAGEKEEPER'S LIEN"),
            ("64", "JP GARAGEKEEPER'S LIEN"),
        )
        # The site's placeholder, not a code named "none".
        self.assertEqual(split_code_description("none"), (None, None))


class TestCaseDescriptionParser(unittest.TestCase):
    def test_reads_case_metadata(self) -> None:
        data = CaseDescriptionParser.from_string(CHANCERY_PAGE)[0].raw_data
        self.assertEqual(data["docket_number"], "2025-1110")
        self.assertEqual(data["date_filed"], date(2025, 9, 30))
        self.assertEqual(data["case_type_code"], "2A")
        self.assertEqual(data["case_type_description"], "CIVIL ACTIONS")
        self.assertEqual(data["status_code"], "CLOSED")

    def test_keeps_a_caption_containing_a_dash(self) -> None:
        """The id/caption split is on the newline, not on " - "."""
        data = CaseDescriptionParser.from_string(CHANCERY_PAGE)[0].raw_data
        self.assertEqual(
            data["case_name"], "IMO 221 CHESTNUT STREET - NEW CASTLE, DE"
        )

    def test_reads_the_description_block_not_the_selection_block(self) -> None:
        """Both blocks print a Case ID row; only one prints a Filing Date."""
        data = CaseDescriptionParser.from_string(CHANCERY_PAGE)[0].raw_data
        self.assertIsNotNone(data["date_filed"])


class TestPartiesParser(unittest.TestCase):
    def setUp(self) -> None:
        self.parties = [
            party.raw_data
            for party in PartiesParser.from_string(CHANCERY_PAGE)
        ]

    def test_one_record_per_party(self) -> None:
        self.assertEqual(len(self.parties), 2)

    def test_captures_the_site_person_id(self) -> None:
        self.assertEqual(self.parties[0]["id_code"], "@4209677")
        self.assertEqual(self.parties[1]["id_code"], "002234")

    def test_reads_the_association_columns(self) -> None:
        self.assertEqual(self.parties[0]["sequence_number"], 1)
        self.assertEqual(self.parties[0]["associated_sequence_number"], 3)
        self.assertIsNone(self.parties[1]["associated_sequence_number"])

    def test_placeholders_become_absent(self) -> None:
        self.assertIsNone(self.parties[0]["contact_raw"])
        self.assertEqual(self.parties[0]["aliases"], [])

    def test_address_keeps_its_line_breaks(self) -> None:
        self.assertEqual(
            self.parties[1]["contact_raw"],
            "DONALD L. GOUGE JR LLC\n800 N. KING STREET\nWILMINGTON DE 19801",
        )

    def test_reads_aliases_and_end_date(self) -> None:
        self.assertEqual(
            self.parties[1]["aliases"], ["GOUGE, DON", "GOUGE, DONALD"]
        )
        self.assertEqual(self.parties[1]["date_terminated"], date(2026, 1, 15))


class TestDocketEntriesParser(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = [
            row.raw_data
            for row in DocketEntriesParser.from_string(CHANCERY_PAGE)
        ]

    def test_one_record_per_entry(self) -> None:
        self.assertEqual(len(self.entries), 2)

    def test_splits_date_from_time(self) -> None:
        """text_content() would read this cell as "30-SEP-202511:37 AM"."""
        self.assertEqual(self.entries[0]["date_filed"], date(2025, 9, 30))
        self.assertEqual(self.entries[0]["time_filed"], time(11, 37))

    def test_attaches_the_entry_text_row(self) -> None:
        self.assertIn("DATE DOCKETED", self.entries[0]["entry_text"])
        self.assertIn("\n", self.entries[0]["entry_text"])

    def test_an_entry_without_a_text_row(self) -> None:
        self.assertIsNone(self.entries[1]["entry_text"])
        self.assertEqual(self.entries[1]["description"], "ORDER ENTERED")
        self.assertEqual(self.entries[1]["monetary"], "$1728.52")

    def test_preserves_page_order(self) -> None:
        self.assertEqual([e["sequence_number"] for e in self.entries], [0, 1])

    def test_no_table_yields_no_entries(self) -> None:
        self.assertEqual(
            DocketEntriesParser.from_string(POPULATED_SECTIONS_PAGE), []
        )


class TestIsAppeal(unittest.TestCase):
    """The case-type code is the only trial-vs-appeal signal the page has."""

    def test_appellate_types_are_appeals(self) -> None:
        for code in ("AA", "AB", "AC", "AD", "AF", "AI", "3A", "CA", "4L"):
            with self.subTest(code=code):
                self.assertIs(DeCourtConnectScraper._is_appeal(code), True)

    def test_trial_types_on_the_appellate_docket_are_not(self) -> None:
        """All four were found on Superior's ``A`` docket in the corpus.

        The ``A`` number space is collected wholesale (``_in_scope`` trusts
        it), so these are kept -- but they are trial-court matters and must
        not be labelled appeals.
        """
        for code in ("3C", "MH", "M3", "ME"):
            with self.subTest(code=code):
                self.assertIs(DeCourtConnectScraper._is_appeal(code), False)

    def test_chancery_is_original_jurisdiction(self) -> None:
        self.assertIs(DeCourtConnectScraper._is_appeal("2A"), False)

    def test_no_case_type_is_unknown_not_false(self) -> None:
        self.assertIsNone(DeCourtConnectScraper._is_appeal(None))
        self.assertIsNone(DeCourtConnectScraper._is_appeal(""))


class TestSectionParsers(unittest.TestCase):
    def test_empty_sections_yield_nothing(self) -> None:
        self.assertEqual(RelatedCasesParser.from_string(CHANCERY_PAGE), [])
        self.assertEqual(CaseEventsParser.from_string(CHANCERY_PAGE), [])

    def test_related_cases_read_from_the_link_list(self) -> None:
        """The section is a run of links, not a table -- one record each."""
        related = [
            row.raw_data
            for row in RelatedCasesParser.from_string(POPULATED_SECTIONS_PAGE)
        ]
        self.assertEqual(
            [row["docket_number"] for row in related],
            ["8918", "CPU4-13-003466"],
        )

    def test_events_become_docket_entries(self) -> None:
        events = [
            row.raw_data
            for row in CaseEventsParser.from_string(POPULATED_SECTIONS_PAGE)
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source_section"], "case_event_schedule")
        self.assertEqual(events[0]["date_filed"], date(2011, 6, 14))
        self.assertEqual(events[0]["time_filed"], time(9, 0))
        self.assertEqual(events[0]["description"], "MOTION TO STAY")
        self.assertEqual(events[0]["name"], "SCOTT, CALVIN L")
        self.assertEqual(events[0]["courtroom"], "SCN COURTROOM TBD")
        self.assertEqual(
            events[0]["location"], "SUPERIOR CT NEW CASTLE COUNTY"
        )
        self.assertEqual(events[0]["extra_fields"], {})

    def test_sections_do_not_bleed_into_each_other(self) -> None:
        """The anchors are unclosed, so the span is counted, not descended.

        The related-case reader must not run past the ``events`` anchor and
        pick up the person-detail links in the parties table, and the event
        reader must not take the parties table for its own.
        """
        self.assertEqual(
            len(RelatedCasesParser.from_string(POPULATED_SECTIONS_PAGE)), 2
        )
        self.assertEqual(
            len(CaseEventsParser.from_string(POPULATED_SECTIONS_PAGE)), 1
        )


def _range(**kwargs: object) -> DeCaseRange:
    """Build a ``DeCaseRange`` with a ``soft_max`` that clears validation."""
    kwargs.setdefault("soft_max", int(kwargs["min"]) + 1)  # type: ignore[arg-type]
    return DeCaseRange(**kwargs)  # type: ignore[arg-type]


class TestDeCaseRangeCaseIds(unittest.TestCase):
    """Every expected id below was fetched from the live site on 2026-09-14.

    This is the test that matters most for the multi-space entry: a template
    that renders a *malformed* id does not fail loudly, it just misses — and a
    run of misses is indistinguishable from an empty partition, so the bug
    reads as an answer.
    """

    def test_renders_each_space(self) -> None:
        cases = [
            (
                {
                    "space": S.CHANCERY,
                    "court_id": "delch",
                    "year": 2025,
                    "min": 1110,
                },
                "2025-1110",
            ),
            # Flat and unpadded: the site serves "5195", never "05195".
            (
                {"space": S.CHANCERY_LEGACY, "court_id": "delch", "min": 5195},
                "5195",
            ),
            (
                {
                    "space": S.CHANCERY_LEGACY,
                    "court_id": "delch",
                    "min": 13013,
                },
                "13013",
            ),
            (
                {
                    "space": S.SUPERIOR_APPEAL,
                    "court_id": "delsuperct",
                    "year": 2024,
                    "month": 1,
                    "county": "N",
                    "min": 1,
                },
                "N24A-01-001",
            ),
            (
                {
                    "space": S.SUPERIOR_APPEAL,
                    "court_id": "delsuperct",
                    "year": 2024,
                    "month": 2,
                    "county": "K",
                    "min": 1,
                },
                "K24A-02-001",
            ),
            (
                {
                    "space": S.SUPERIOR_APPEAL_ARCHIVAL,
                    "court_id": "delsuperct",
                    "year": 1998,
                    "month": 1,
                    "county": "N",
                    "min": 1,
                },
                "SN98A-01-001",
            ),
            (
                {
                    "space": S.COMMON_PLEAS,
                    "court_id": "delctcompl",
                    "year": 2023,
                    "unit": 4,
                    "min": 459,
                },
                "CPU4-23-000459",
            ),
            # Legacy Common Pleas pads to a width that depends on the *unit*:
            # 3 digits for units 4 and 6, 4 for unit 5.
            (
                {
                    "space": S.COMMON_PLEAS_LEGACY,
                    "court_id": "delctcompl",
                    "year": 1997,
                    "month": 2,
                    "unit": 4,
                    "min": 290,
                },
                "U497-02-290",
            ),
            (
                {
                    "space": S.COMMON_PLEAS_LEGACY,
                    "court_id": "delctcompl",
                    "year": 2000,
                    "month": 8,
                    "unit": 5,
                    "min": 15,
                },
                "U500-08-0015",
            ),
            (
                {
                    "space": S.COMMON_PLEAS_LEGACY,
                    "court_id": "delctcompl",
                    "year": 2002,
                    "month": 9,
                    "unit": 6,
                    "min": 35,
                },
                "U602-09-035",
            ),
        ]
        for kwargs, expected in cases:
            with self.subTest(space=kwargs["space"], expected=expected):
                self.assertEqual(_range(**kwargs).case_id(), expected)

    def test_advancement_keeps_the_partition(self) -> None:
        """``from_int`` copies, so county/month/year survive speculation."""
        seed = _range(
            space=S.SUPERIOR_APPEAL,
            court_id="delsuperct",
            year=2024,
            month=3,
            county="S",
            min=1,
        )
        advanced = seed.from_int(7)
        self.assertIsInstance(advanced, DeCaseRange)
        self.assertEqual(advanced.case_id(), "S24A-03-007")


class TestDeCaseRangeValidation(unittest.TestCase):
    def test_rejects_a_template_missing_its_partition(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            _range(
                space=S.SUPERIOR_APPEAL,
                court_id="delsuperct",
                year=2024,
                min=1,
            )
        self.assertIn("missing county, month", str(caught.exception))

    def test_rejects_a_common_pleas_template_with_no_year(self) -> None:
        with self.assertRaises(ValidationError):
            _range(space=S.COMMON_PLEAS, court_id="delctcompl", unit=4, min=1)

    def test_rejects_out_of_range_partition_values(self) -> None:
        for kwargs in (
            {"month": 13, "county": "N"},
            {"month": 1, "county": "X"},
        ):
            with self.subTest(**kwargs), self.assertRaises(ValidationError):
                _range(
                    space=S.SUPERIOR_APPEAL,
                    court_id="delsuperct",
                    year=2024,
                    min=1,
                    **kwargs,
                )

    def test_chancery_legacy_needs_no_year(self) -> None:
        """The pre-2017 run is a flat integer with no year component."""
        self.assertEqual(
            _range(space=S.CHANCERY_LEGACY, court_id="delch", min=1).case_id(),
            "1",
        )


class TestSeedTemplates(unittest.TestCase):
    def test_expands_the_county_month_grid(self) -> None:
        """3 counties x 12 months x 1 year."""
        templates = seed_templates(S.SUPERIOR_APPEAL, [2024])
        self.assertEqual(len(templates), 36)
        rendered = {DeCaseRange(**t).case_id() for t in templates}
        self.assertEqual(len(rendered), 36, "grid produced duplicate ids")
        self.assertIn("N24A-01-001", rendered)
        self.assertIn("S24A-12-001", rendered)

    def test_chancery_legacy_is_one_flat_run(self) -> None:
        templates = seed_templates(S.CHANCERY_LEGACY)
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]["soft_max"], CHANCERY_LEGACY_MAX + 1)

    def test_every_template_validates(self) -> None:
        """A template the grid builds must be a legal ``DeCaseRange``."""
        for space in S:
            with self.subTest(space=space):
                for template in seed_templates(space):
                    DeCaseRange(**template)


class TestScopeFilter(unittest.TestCase):
    """Which fetched cases the scraper keeps (``_in_scope``)."""

    scope = staticmethod(DeCourtConnectScraper._in_scope)

    def test_superior_appeal_space_needs_no_type_test(self) -> None:
        self.assertTrue(
            self.scope(S.SUPERIOR_APPEAL.value, "delsuperct", "AD")
        )
        self.assertTrue(
            self.scope(S.SUPERIOR_APPEAL_ARCHIVAL.value, "delsuperct", "AC")
        )

    def test_chancery_spaces_keep_only_chancery(self) -> None:
        self.assertTrue(self.scope(S.CHANCERY.value, "delch", "2A"))
        self.assertTrue(self.scope(S.CHANCERY_LEGACY.value, "delch", "2A"))
        # A Justice of the Peace case sharing the legacy integers.
        self.assertFalse(
            self.scope(S.CHANCERY_LEGACY.value, "deljustpct", "61")
        )

    def test_common_pleas_keeps_only_appeals(self) -> None:
        self.assertTrue(self.scope(S.COMMON_PLEAS.value, "delctcompl", "4L"))
        self.assertTrue(
            self.scope(S.COMMON_PLEAS_LEGACY.value, "delctcompl", "4M")
        )
        # A first-instance debt claim in the same sequence.
        self.assertFalse(self.scope(S.COMMON_PLEAS.value, "delctcompl", "4A"))
        self.assertFalse(self.scope(S.COMMON_PLEAS.value, "delctcompl", None))

    def test_single_record_lookup_is_never_filtered(self) -> None:
        """``docket_by_number`` asked for this exact case; keep it."""
        self.assertTrue(self.scope(None, "deljustpct", "61"))


class TestCourtDerivation(unittest.TestCase):
    court_for = staticmethod(DeCourtConnectScraper._court_for)

    def test_maps_verified_case_type_families(self) -> None:
        for code, expected in [
            ("2A", "delch"),
            ("AD", "delsuperct"),
            ("CR", "delsuperct"),
            ("LM", "delsuperct"),
            ("4L", "delctcompl"),
            ("61", "deljustpct"),
        ]:
            with self.subTest(code=code):
                self.assertEqual(self.court_for(code, "delch"), expected)

    def test_unmapped_families_fall_back(self) -> None:
        """``J*`` judgment dockets name the originating court, not theirs."""
        self.assertEqual(self.court_for("JL", "delsuperct"), "delsuperct")
        self.assertEqual(self.court_for(None, "delch"), "delch")


if __name__ == "__main__":
    unittest.main()
