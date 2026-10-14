"""Offline tests for the Court-PASS file-name convention and entry linking.

Covers ``juriscraper.state.new_york.nycourts_gov.filename_convention``: the
parse of the Court of Appeals' published PDF naming convention
(https://www.nycourts.gov/ctapps/techspecs.htm) and the join it enables from
``gvFiles`` rows onto FILINGS-table rows.

File names here are taken from the real Court-PASS corpus (including the
malformed ones) so the tolerances the matcher relies on stay pinned.
"""

import unittest
from datetime import date

from jkent.common.lxml_page_element import LxmlPageElement
from lxml import html as lxml_html

from juriscraper.state.new_york.nycourts_gov.filename_convention import (
    FILING_TYPE_MAP,
    align_party_name,
    archive_dedup_keys,
    classify_filing_type,
    describe_filing,
    entry_id_from_document,
    entry_id_from_row,
    parse_file_name,
    reconcile_files_and_entries,
)
from juriscraper.state.new_york.nycourts_gov.models import NYCourtPassDocket
from juriscraper.state.new_york.nycourts_gov.parsers._common import (
    clean_case_title,
    file_type_from_button,
    split_party_side,
)
from juriscraper.state.new_york.nycourts_gov.scraper import NYCourtPassScraper
from juriscraper.state.new_york.nycourts_gov.vocabularies import (
    NOT_ON_FILINGS_TABLE,
    FilingDocType,
    FilingRole,
    FilingType,
    IssueCategory,
    IssueSubcategory,
    classify_issue,
)


class ParseFileNameTest(unittest.TestCase):
    """The convention itself, plus the deviations filers actually commit."""

    def test_spec_examples(self):
        """The five examples published in the tech spec parse exactly."""
        cases = [
            (
                "SmithvJones-app-Smith-brf.pdf",
                "SmithvJones",
                "appellant",
                "Smith",
                "brf",
                None,
            ),
            (
                "SmithvJones-app-Smith-Rec-vol1.pdf",
                "SmithvJones",
                "appellant",
                "Smith",
                "rec",
                1,
            ),
            (
                "SmithvJones-res-Brown-suppappdx.pdf",
                "SmithvJones",
                "respondent",
                "Brown",
                "suppappdx",
                None,
            ),
            (
                "SmithvJones-amic-ConcernedCitizens-amicbrf.pdf",
                "SmithvJones",
                "amicus",
                "ConcernedCitizens",
                "amicbrf",
                None,
            ),
            (
                "SmithvJones-app-Smith-SSMltrbrf.pdf",
                "SmithvJones",
                "appellant",
                "Smith",
                "ssmltrbrf",
                None,
            ),
        ]
        for name, title, role, party, doctype, volume in cases:
            with self.subTest(name):
                parsed = parse_file_name(name)
                self.assertEqual(parsed.title, title)
                self.assertEqual(parsed.role, role)
                self.assertEqual(parsed.party, party)
                self.assertEqual(parsed.doctype, doctype)
                self.assertEqual(parsed.volume, volume)

    def test_appellate_division_types_are_not_coa_types(self):
        """``ADreplybrf`` must not collapse into plain ``replybrf``.

        AD material is Appellate Division record, has no FILINGS row in the
        common case, and would otherwise be mis-linked to the Court of
        Appeals reply-brief entry.
        """
        self.assertEqual(
            parse_file_name("AlfvBuffaloNews-app-Alf-ADreplybrf").doctype,
            "adreplybrf",
        )
        self.assertEqual(parse_file_name("XvY-app-X-ADbrf").doctype, "adbrf")
        self.assertEqual(parse_file_name("XvY-app-X-ADRec").doctype, "adrec")
        self.assertEqual(
            parse_file_name("XvY-app-X-replybrf").doctype, "replybrf"
        )

    def test_glued_and_roman_volumes(self):
        """Filers glue the volume on and use roman numerals."""
        glued = parse_file_name(
            "111West57thInvestmentLLCv111W57Mezz-app-111West57th-RecVol 3"
        )
        self.assertEqual(glued.doctype, "rec")
        self.assertEqual(glued.volume, 3)

        roman = parse_file_name("2020-00044-JPMorganvVigilant-rec-VolVIII")
        self.assertEqual(roman.doctype, "rec")
        self.assertEqual(roman.volume, 8)

        split = parse_file_name("ACMEvOrange-app-ACME-Rec-vol1 part2")
        self.assertEqual(split.doctype, "rec")
        self.assertEqual(split.volume, 1)
        self.assertEqual(split.part, 2)

    def test_volume_and_part_as_separate_segments(self):
        """The part is written as its own segment as often as it is glued to the
        volume, and reading it as the volume used to consume the volume slot and
        leave the doctype unread -- 80 files in the corpus."""
        parsed = parse_file_name("BrownAdminvSNY-app-SNY-Rec-vol1-part2")
        self.assertEqual(parsed.doctype, "rec")
        self.assertEqual(parsed.volume, 1)
        self.assertEqual(parsed.part, 2)
        self.assertEqual(parsed.party, "SNY")

    def test_part_without_a_volume(self):
        """A part on its own is a part, not a volume."""
        parsed = parse_file_name("XvY-app-X-appdx-part3")
        self.assertEqual(parsed.doctype, "appdx")
        self.assertIsNone(parsed.volume)
        self.assertEqual(parsed.part, 3)

    def test_decoration_glued_to_the_doctype(self):
        """Filers glue "sealed" / "redacted" / "amended" onto the doctype, which
        also used to spill the doctype into the party name."""
        cases = [
            ("PeoplevMonk-app-Monk-SEALEDappdx", "appdx", "Monk"),
            ("AptvMorganStanley-app-Apt-RecRedacted", "rec", "Apt"),
            ("XvY-res-B-URealtyCorp-amended.brf", "brf", "B-URealtyCorp"),
            (
                "Article13vPonce-app-LaSalle-replybrf (corrected)",
                "replybrf",
                "LaSalle",
            ),
        ]
        for file_name, doctype, party in cases:
            with self.subTest(file_name):
                parsed = parse_file_name(file_name)
                self.assertEqual(parsed.doctype, doctype)
                self.assertEqual(parsed.party, party)

    def test_a_doctype_that_is_only_decoration_stays_unread(self):
        """Stripping decoration must not invent a doctype out of one."""
        parsed = parse_file_name("XvY-app-X-redacted")
        self.assertIsNone(parsed.doctype)

    def test_stray_extension_in_the_doctype(self):
        """A doubled or dot-trailed extension the outer strip missed."""
        for file_name in (
            "AdarBaysvGeneSYSID-app-GeneSYSID-brf.pdf.",
            "AdarBaysvGeneSYSID-app-GeneSYSID-brf.pdf.pdf",
        ):
            with self.subTest(file_name):
                parsed = parse_file_name(file_name)
                self.assertEqual(parsed.doctype, "brf")
                self.assertEqual(parsed.party, "GeneSYSID")

    def test_cross_appeal_writes_both_roles(self):
        parsed = parse_file_name("K2InvestmentvAmerican-app-res-American-brf")
        self.assertEqual(parsed.role, "appellant-respondent")
        self.assertEqual(parsed.party, "American")
        self.assertEqual(parsed.doctype, "brf")

    def test_soft_hyphen_is_treated_as_a_separator(self):
        """A U+00AD soft hyphen instead of '-' must still split."""
        parsed = parse_file_name("MatterMcLaurin­McLaurinMatthews-suppappdx")
        self.assertEqual(parsed.doctype, "suppappdx")

    def test_court_generated_files_are_flagged(self):
        for name in (
            "041426-41-Oral-Argument-Transcript",
            "41opn26-Decision",
            "SmithvJones-webcast",
        ):
            with self.subTest(name):
                self.assertTrue(parse_file_name(name).is_court_generated)
        self.assertFalse(
            parse_file_name("SmithvJones-app-Smith-brf").is_court_generated
        )

    def test_unrecognized_doctype_degrades_gracefully(self):
        """Pre-2013 and off-convention names must not raise.

        This case used to end ``-JurRsp``, which now reads as a
        ``JURISDICTIONAL_RESPONSE``; the tail below is one the vocabulary
        genuinely has no member for, which is the condition under test.
        """
        parsed = parse_file_name(
            "SchochvLakeChamplain-BklnJamFlshHosp-Boumans"
        )
        self.assertIsNone(parsed.doctype)
        self.assertEqual(parsed.unparsed_token, "Boumans")

    def test_noise_suffix_is_ignored(self):
        parsed = parse_file_name("SmithvJones-app-Smith-brf-redacted")
        self.assertEqual(parsed.doctype, "brf")


class ReconcileFilesAndEntriesTest(unittest.TestCase):
    """The gvFiles <-> FILINGS join, in both directions."""

    ENTRIES = [
        {
            "filing_type": "Appellant COA Record",
            "party": "111 West 57th Investment LLC (A)",
            "date_due": None,
            "date_received": date(2025, 5, 27),
        },
        {
            "filing_type": "Appellant Brief",
            "party": "111 West 57th Investment LLC (A)",
            "date_due": date(2025, 5, 27),
            "date_received": date(2025, 5, 27),
        },
        {
            "filing_type": "Respondent Brief",
            "party": "Spruce Capital Partners LLC (R)",
            "date_due": date(2025, 8, 5),
            "date_received": date(2025, 8, 5),
        },
    ]

    @staticmethod
    def _files(*names):
        return [{"file_name": n, "file_index": i} for i, n in enumerate(names)]

    def test_links_and_inherits_dates(self):
        files = self._files(
            "111West57thInvestmentLLCv111W57Mezz-app-111West57thInvestmentLLC-Brf",
            "111West57thInvestmentLLCv111W57Mezz-res-SpruceCapitalPartners-brf",
        )
        linked, _ = reconcile_files_and_entries(files, self.ENTRIES)

        self.assertEqual(linked[0]["docket_entry_index"], 1)
        self.assertEqual(linked[0]["match_confidence"], "exact")
        self.assertEqual(linked[0]["date_received"], date(2025, 5, 27))
        self.assertEqual(linked[0]["date_due"], date(2025, 5, 27))

        self.assertEqual(linked[1]["docket_entry_index"], 2)
        self.assertEqual(linked[1]["date_received"], date(2025, 8, 5))

    def test_all_volumes_share_one_entry(self):
        """A five-volume record is five files but one FILINGS row."""
        files = self._files(
            *[
                "111West57thInvestmentLLCv111W57Mezz-app-111West57thInvestmentLLC"
                "-RecVol %d" % n
                for n in range(1, 6)
            ]
        )
        linked, _ = reconcile_files_and_entries(files, self.ENTRIES)
        self.assertEqual(
            [f["docket_entry_index"] for f in linked], [0, 0, 0, 0, 0]
        )
        self.assertEqual([f["volume"] for f in linked], [1, 2, 3, 4, 5])

    def test_court_generated_files_get_their_own_entry(self):
        """Court output is not a filing, but it still gets an entry.

        It may never *match* a FILINGS row -- a decision is not the appellant's
        brief -- but it is synthesized like any other document the table omits,
        so nothing is reachable only through ``files``. ``link_status`` is what
        keeps it distinguishable from a filer document.
        """
        linked, entries = reconcile_files_and_entries(
            self._files(
                "41opn26-Decision", "041426-41-Oral-Argument-Transcript"
            ),
            self.ENTRIES,
        )
        for row in linked:
            self.assertIsNotNone(row["docket_entry_index"])
            self.assertIsNotNone(row["docket_entry_id"])
            self.assertIsNotNone(row["document_group"])
            self.assertEqual(row["link_status"], "court_generated")
            # gvFiles carries no dates and the entry is synthesized, so there
            # is nothing to inherit
            self.assertIsNone(row["date_received"])

        inferred = [e for e in entries if e["inferred_from_file"]]
        self.assertEqual(
            [e["filing_type"] for e in inferred],
            ["Decision", "Oral Argument Transcript"],
        )
        # and none of them stole a real FILINGS row
        for entry in entries:
            if not entry["inferred_from_file"]:
                self.assertEqual(entry["file_indexes"], [])

    def test_two_decisions_on_one_docket_stay_separate(self):
        """A docket can carry an entry order and an opinion.

        Both parse to ``doctype='_decision'`` with no role or party, so the id
        has to key on the title or they collapse into one entry.
        """
        linked, entries = reconcile_files_and_entries(
            self._files("51opn21-Decision", "71ent20-Decision"), []
        )
        ids = [e["docket_entry_id"] for e in entries]
        self.assertEqual(
            ids,
            ["d:court:51opn21:decision:1", "d:court:71ent20:decision:1"],
        )
        self.assertEqual(
            [f["docket_entry_id"] for f in linked],
            ids,
        )

    def test_motion_papers_have_no_entry(self):
        """FILINGS lists merits filings only; motion papers link to nothing."""
        linked, entries = reconcile_files_and_entries(
            self._files(
                "111West57thv111W57Mezz-app-111West57thInvestment-mot",
                "111West57thv111W57Mezz-res-SpruceCapital-opp",
            ),
            self.ENTRIES,
        )
        self.assertEqual([f["doc_type"] for f in linked], ["mot", "opp"])
        # no FILINGS row lists motion papers, so each gets a synthetic entry
        self.assertEqual([f["link_status"] for f in linked], ["inferred"] * 2)
        inferred = [e for e in entries if e["inferred_from_file"]]
        self.assertEqual(len(inferred), 2)
        self.assertEqual(
            [e["filing_type"] for e in inferred],
            ["Appellant Motion", "Respondent Opposition"],
        )
        # ...and that absence is expected for these doctypes
        for e in inferred:
            self.assertIn(e["entry_doctype"], NOT_ON_FILINGS_TABLE)

    def test_two_same_type_entries_split_by_party(self):
        """Two respondent briefs must not both land on the first row."""
        entries = [
            {
                "filing_type": "Respondent Brief",
                "party": "Alpha Holdings LLC",
                "date_due": None,
                "date_received": date(2025, 1, 1),
            },
            {
                "filing_type": "Respondent Brief",
                "party": "Beta Partners LLC",
                "date_due": None,
                "date_received": date(2025, 2, 2),
            },
        ]
        linked, _ = reconcile_files_and_entries(
            self._files(
                "XvY-res-BetaPartners-brf", "XvY-res-AlphaHoldings-brf"
            ),
            entries,
        )
        self.assertEqual(linked[0]["docket_entry_index"], 1)
        self.assertEqual(linked[0]["date_received"], date(2025, 2, 2))
        self.assertEqual(linked[1]["docket_entry_index"], 0)
        self.assertEqual(linked[1]["date_received"], date(2025, 1, 1))

    def test_misspelled_party_still_matches(self):
        """'Scharff' in the file name vs 'Scharf' on the docket."""
        entries = [
            {
                "filing_type": "Appellant Brief",
                "party": "Joseph  Scharf (A)",
                "date_due": None,
                "date_received": date(2023, 3, 3),
            }
        ]
        linked, _ = reconcile_files_and_entries(
            self._files("122 East42ndvScharf-app-Scharff-brf"), entries
        )
        self.assertEqual(linked[0]["docket_entry_index"], 0)
        self.assertEqual(linked[0]["date_received"], date(2023, 3, 3))

    def test_no_entries_leaves_components_but_no_link(self):
        linked, _ = reconcile_files_and_entries(
            self._files("SmithvJones-app-Smith-brf"), []
        )
        self.assertEqual(linked[0]["doc_type"], "brf")
        self.assertEqual(linked[0]["doc_role"], "appellant")
        self.assertEqual(linked[0]["doc_party"], "Smith")
        # with no FILINGS table at all, the file still gets an entry
        self.assertEqual(linked[0]["docket_entry_index"], 0)
        self.assertEqual(linked[0]["link_status"], "inferred")

    def test_input_is_not_mutated(self):
        files = self._files("SmithvJones-app-Smith-brf")
        entries = [dict(e) for e in self.ENTRIES]
        reconcile_files_and_entries(files, self.ENTRIES)
        self.assertEqual(set(files[0]), {"file_name", "file_index"})
        self.assertEqual(self.ENTRIES, entries)


class ReverseDirectionTest(unittest.TestCase):
    """Entry -> zero-or-more files, and the composite join key."""

    def test_entry_with_no_document(self):
        """A FILINGS row whose PDF was never uploaded has file_indexes == []."""
        entries = [
            {
                "filing_type": "Appellant Brief",
                "party": "Smith",
                "date_due": date(2025, 1, 1),
                "date_received": None,
            },
            {
                "filing_type": "Respondent Brief",
                "party": "Jones",
                "date_due": date(2025, 2, 1),
                "date_received": date(2025, 2, 1),
            },
        ]
        files = [{"file_name": "SmithvJones-res-Jones-brf", "file_index": 0}]
        linked, reconciled = reconcile_files_and_entries(files, entries)

        self.assertEqual(reconciled[0]["file_indexes"], [])
        self.assertEqual(reconciled[1]["file_indexes"], [0])
        self.assertFalse(reconciled[0]["inferred_from_file"])
        self.assertEqual(linked[0]["docket_entry_index"], 1)

    def test_file_indexes_use_gvfiles_row_number_not_list_position(self):
        """The join key is ``file_index``, which skips malformed gvFiles rows."""
        entries = [
            {
                "filing_type": "Appellant COA Record",
                "party": "Smith",
                "date_due": None,
                "date_received": date(2025, 1, 1),
            }
        ]
        # the parser dropped row 0, so file_index starts at 1
        files = [
            {"file_name": "SmithvJones-app-Smith-Rec-vol1", "file_index": 1},
            {"file_name": "SmithvJones-app-Smith-Rec-vol2", "file_index": 2},
        ]
        _, reconciled = reconcile_files_and_entries(files, entries)
        self.assertEqual(reconciled[0]["file_indexes"], [1, 2])

    def test_multiple_files_in_one_inferred_entry(self):
        """A multi-volume document the FILINGS table omitted is ONE entry."""
        files = [
            {
                "file_name": "SmithvJones-app-Smith-ADRec-vol%d" % n,
                "file_index": n - 1,
            }
            for n in (1, 2, 3)
        ]
        linked, reconciled = reconcile_files_and_entries(files, [])

        inferred = [e for e in reconciled if e["inferred_from_file"]]
        self.assertEqual(len(inferred), 1)
        self.assertEqual(inferred[0]["file_indexes"], [0, 1, 2])
        self.assertEqual(inferred[0]["filing_type"], "AD - Appellant Record")
        self.assertEqual(inferred[0]["entry_doctype"], "adrec")
        self.assertIsNone(inferred[0]["raw_filing_type"])
        self.assertIsNone(inferred[0]["date_received"])
        # all three files share one document group and one entry
        self.assertEqual({f["document_group"] for f in linked}, {0})
        self.assertEqual({f["docket_entry_index"] for f in linked}, {0})

    def test_duplicate_uploads_stay_separate_entries(self):
        """Same role/party/doctype with no volume markers is not one document."""
        files = [
            {"file_name": "SmithvJones-app-Smith-mot", "file_index": 0},
            {"file_name": "SmithvJones-app-Smith-mot", "file_index": 1},
        ]
        linked, reconciled = reconcile_files_and_entries(files, [])
        self.assertEqual(len(reconciled), 2)
        self.assertEqual([f["document_group"] for f in linked], [0, 1])

    def test_entry_index_is_stable_and_real_rows_come_first(self):
        entries = [
            {
                "filing_type": "Appellant Brief",
                "party": "Smith",
                "date_due": None,
                "date_received": date(2025, 1, 1),
            }
        ]
        files = [
            {"file_name": "SmithvJones-app-Smith-brf", "file_index": 0},
            {"file_name": "SmithvJones-app-Smith-MotforLv", "file_index": 1},
        ]
        _, reconciled = reconcile_files_and_entries(files, entries)
        self.assertEqual([e["entry_index"] for e in reconciled], [0, 1])
        self.assertEqual(
            [e["inferred_from_file"] for e in reconciled], [False, True]
        )
        self.assertEqual(
            reconciled[1]["filing_type"],
            "Appellant Motion for Leave to Appeal",
        )


class ClassifyFilingTypeTest(unittest.TestCase):
    """(role, doctype) | None classification, and drift detection."""

    def test_known_type(self):
        c = classify_filing_type("Appellant Reply Brief")
        self.assertEqual((c.role, c.doctype), ("appellant", "replybrf"))
        self.assertTrue(c.recognized)

    def test_known_type_with_no_doctype_is_still_recognized(self):
        """The distinction a bare (role, doctype) tuple cannot express."""
        c = classify_filing_type("SCJC Determination")
        self.assertEqual(c.role, "scjc")
        self.assertIsNone(c.doctype)
        self.assertTrue(c.recognized)

    def test_unknown_type_is_flagged(self):
        c = classify_filing_type("Some New Filing Kind")
        self.assertIsNone(c.role)
        self.assertIsNone(c.doctype)
        self.assertFalse(c.recognized)

    def test_unknown_type_still_matches_a_file(self):
        """Drift must not break matching, only be visible."""
        entries = [
            {
                "filing_type": "Some New Filing Kind",
                "party": "Smith",
                "date_due": None,
                "date_received": date(2025, 1, 1),
            }
        ]
        linked, reconciled = reconcile_files_and_entries(
            [{"file_name": "SmithvJones-app-Smith-brf", "file_index": 0}],
            entries,
        )
        self.assertEqual(linked[0]["docket_entry_index"], 0)
        self.assertEqual(linked[0]["date_received"], date(2025, 1, 1))
        self.assertFalse(reconciled[0]["filing_type_recognized"])
        self.assertEqual(
            reconciled[0]["raw_filing_type"], "Some New Filing Kind"
        )

    def test_describe_filing_labels(self):
        cases = [
            (("appellant", "brf"), "Appellant Brief"),
            (("respondent", "replybrf"), "Respondent Reply Brief"),
            (
                ("appellant", "motforlv"),
                "Appellant Motion for Leave to Appeal",
            ),
            (("respondent", "adrec"), "AD - Respondent Record"),
            # role already implied by the doctype label
            (("amicus", "amicbrf"), "Amicus Brief"),
            ((None, "rec"), "Record"),
            (("appellant", None), "Unclassified Filing"),
        ]
        for (role, doctype), expected in cases:
            with self.subTest(expected):
                self.assertEqual(describe_filing(role, doctype), expected)


class DocketEntryIdTest(unittest.TestCase):
    """``docket_entry_id`` -- stable across scrapes, unique within a docket.

    Each case here pins a property measured against the run-db corpus: what
    Court-PASS actually mutates between scrapes, and what it never does.
    """

    @staticmethod
    def _files(*names):
        return [{"file_name": n, "file_index": i} for i, n in enumerate(names)]

    def test_row_id_shape(self):
        self.assertEqual(
            entry_id_from_row("Appellant Reply Brief", "Ray  Vassell (A)", 1),
            "e:appellant-reply-brief:ray-vassell-a:1",
        )

    def test_document_id_shape(self):
        parsed = parse_file_name("MatterofSTPCVTAvDHCR-app-STPCVTA-mot")
        self.assertEqual(
            entry_id_from_document(parsed, 1), "d:appellant:stpcvta:mot:1"
        )

    def test_neither_date_is_in_the_id(self):
        """date_received fills in and date_due gets adjourned -- both routine."""
        scheduled = [
            {
                "filing_type": "Appellant Reply Brief",
                "party": "Ray Vassell (A)",
                "date_due": date(2026, 7, 14),
                "date_received": None,
            }
        ]
        # the reply brief arrives, and the due date was adjourned meanwhile
        received = [
            {
                "filing_type": "Appellant Reply Brief",
                "party": "Ray Vassell (A)",
                "date_due": date(2026, 7, 28),
                "date_received": date(2026, 7, 13),
            }
        ]
        _, before = reconcile_files_and_entries([], scheduled)
        _, after = reconcile_files_and_entries([], received)
        self.assertEqual(
            before[0]["docket_entry_id"], after[0]["docket_entry_id"]
        )

    def test_row_inserted_above_does_not_re_key(self):
        """Court-PASS prepends: blank-due rows sort to the top of FILINGS.

        Every observed FILINGS row addition was an insertion above existing
        rows, which is exactly what ``entry_index`` cannot survive.
        """
        brief = {
            "filing_type": "Appellant Brief",
            "party": "David T. (A)",
            "date_due": date(2026, 7, 16),
            "date_received": date(2026, 7, 16),
        }
        appendix = {
            "filing_type": "Appellant Appendix",
            "party": "David T. (A)",
            "date_due": None,
            "date_received": date(2026, 7, 16),
        }
        _, before = reconcile_files_and_entries([], [brief])
        _, after = reconcile_files_and_entries([], [appendix, brief])

        self.assertEqual(before[0]["entry_index"], 0)
        self.assertEqual(after[1]["entry_index"], 1)  # index moved
        self.assertEqual(  # id did not
            before[0]["docket_entry_id"], after[1]["docket_entry_id"]
        )

    def test_repeated_type_and_party_get_distinct_ordinals(self):
        entries = [
            {
                "filing_type": "Respondent Response to Amicus Brief",
                "party": "Article 13 LLC (R)",
                "date_due": None,
                "date_received": date(2025, 9, 26),
            },
            {
                "filing_type": "Respondent Response to Amicus Brief",
                "party": "Article 13 LLC (R)",
                "date_due": None,
                "date_received": date(2025, 10, 3),
            },
        ]
        _, reconciled = reconcile_files_and_entries([], entries)
        ids = [e["docket_entry_id"] for e in reconciled]
        self.assertEqual(len(set(ids)), 2)
        self.assertTrue(ids[0].endswith(":1"))
        self.assertTrue(ids[1].endswith(":2"))

    def test_inferred_id_survives_losing_a_volume(self):
        """The ``d:`` id keys on the group, not on any one file name.

        Documents do get withdrawn -- a misfiled brief was pulled from
        APL-2026-00036 between runs -- so losing a volume must not re-key the
        siblings that remain.
        """
        all_volumes = self._files(
            "PeoplevManor-app-Manor-Rec-vol1",
            "PeoplevManor-app-Manor-Rec-vol2",
            "PeoplevManor-app-Manor-Rec-vol3",
        )
        without_first = self._files(
            "PeoplevManor-app-Manor-Rec-vol2",
            "PeoplevManor-app-Manor-Rec-vol3",
        )
        _, before = reconcile_files_and_entries(all_volumes, [])
        _, after = reconcile_files_and_entries(without_first, [])
        self.assertTrue(before[0]["inferred_from_file"])
        self.assertEqual(
            before[0]["docket_entry_id"], after[0]["docket_entry_id"]
        )

    def test_files_carry_their_entry_id_and_volumes_share_it(self):
        entries = [
            {
                "filing_type": "Appellant COA Record",
                "party": "Manor (A)",
                "date_due": None,
                "date_received": date(2015, 3, 2),
            }
        ]
        files = self._files(
            "PeoplevManor-app-Manor-Rec-vol1",
            "PeoplevManor-app-Manor-Rec-vol2",
        )
        linked, reconciled = reconcile_files_and_entries(files, entries)
        entry_id = reconciled[0]["docket_entry_id"]
        self.assertEqual(linked[0]["link_status"], "matched")
        self.assertEqual(
            [f["docket_entry_id"] for f in linked], [entry_id, entry_id]
        )

    def test_court_generated_files_carry_a_court_entry_id(self):
        linked, _ = reconcile_files_and_entries(
            self._files(
                "123ent25-Decision", "060618-79-Oral Argument-Transcript"
            ),
            [],
        )
        self.assertEqual(
            [row["docket_entry_id"] for row in linked],
            [
                "d:court:123ent25:decision:1",
                "d:court:060618-79-oral-argument:transcript:1",
            ],
        )
        for row in linked:
            self.assertEqual(row["link_status"], "court_generated")

    def test_clerical_correction_re_keys(self):
        """A party fix is a delete plus insert, not an update.

        Observed 3 times in ~1180 docket-transitions, e.g. ``Ermelinda
        DaCruz (A)`` -> ``Albertino DaCruz (A)``. Nothing on the page can
        prevent this -- the FILINGS table carries no row identifier.
        """
        wrong = [
            {
                "filing_type": "Appellant Reply Brief",
                "party": "Ermelinda DaCruz (A)",
                "date_due": date(2011, 1, 17),
                "date_received": None,
            }
        ]
        fixed = [{**wrong[0], "party": "Albertino DaCruz (A)"}]
        _, before = reconcile_files_and_entries([], wrong)
        _, after = reconcile_files_and_entries([], fixed)
        self.assertNotEqual(
            before[0]["docket_entry_id"], after[0]["docket_entry_id"]
        )


class ArchiveDedupKeyTest(unittest.TestCase):
    """The archive key, which is also the download deduplication key.

    It lands on disk as a single directory name, and
    ``requests.deduplication_key`` is ``UNIQUE ON CONFLICT IGNORE`` -- a repeat
    means the second file is never downloaded, silently. So uniqueness within a
    docket is a correctness property, not a cosmetic one.
    """

    @staticmethod
    def _files(*names):
        return [{"file_name": n, "file_index": i} for i, n in enumerate(names)]

    def _keys(self, entries, *names):
        linked, _ = reconcile_files_and_entries(self._files(*names), entries)
        return archive_dedup_keys("APL-2025-00221", linked)

    ENTRIES = [
        {
            "filing_type": "Appellant Brief",
            "party": "Ray Vassell (A)",
            "date_due": date(2026, 3, 31),
            "date_received": date(2026, 3, 26),
        },
        {
            "filing_type": "Appellant Appendix",
            "party": "Ray Vassell (A)",
            "date_due": None,
            "date_received": date(2026, 3, 26),
        },
    ]

    def test_key_is_the_page_file_name(self):
        """The key is what the Court printed, slugified -- not a match."""
        keys = self._keys(self.ENTRIES, "PeoplevVassell-app-Vassell-brf")
        self.assertEqual(
            keys, ["APL-2025-00221_peoplevvassell-app-vassell-brf_1"]
        )

    def test_key_does_not_move_when_the_match_does(self):
        """The whole point of naming off the page.

        Same file, same docket, but a FILINGS table that states a different
        party -- so the reconciler pairs it with a different entry, or with
        none. The key must not notice: a document that changed nothing about
        itself must not change its name on disk, which is exactly what the
        entry-id scheme did between two runs a fortnight apart.
        """
        name = "PeoplevVassell-app-Vassell-brf"
        matched = self._keys(self.ENTRIES, name)
        other_party = self._keys(
            [{**self.ENTRIES[0], "party": "Someone Else (R)"}], name
        )
        unmatched = self._keys([], name)
        self.assertEqual(matched, other_party)
        self.assertEqual(matched, unmatched)

    def test_volumes_are_distinguished(self):
        """A multi-volume record is several files under one entry.

        The old scheme needed ``volume`` appended because the entry id was the
        same for every volume. The Court names each volume differently, so
        naming off the page separates them with no help.
        """
        keys = self._keys(
            self.ENTRIES,
            "PeoplevVassell-app-Vassell-appdx-vol1",
            "PeoplevVassell-app-Vassell-appdx-vol2",
        )
        self.assertEqual(len(set(keys)), 2)
        self.assertTrue(keys[0].endswith("appdx-vol1_1"))
        self.assertTrue(keys[1].endswith("appdx-vol2_1"))

    def test_part_is_distinguished(self):
        keys = self._keys(
            self.ENTRIES,
            "PeoplevVassell-app-Vassell-appdx-vol1 part1",
            "PeoplevVassell-app-Vassell-appdx-vol1 part2",
        )
        self.assertEqual(len(set(keys)), 2)
        self.assertTrue(keys[0].endswith("vol1-part1_1"))
        self.assertTrue(keys[1].endswith("vol1-part2_1"))

    def test_court_generated_files_are_named_the_same_way(self):
        """A fifth of all files are court output; nothing special about them."""
        keys = self._keys(
            [],
            "123ent25-Decision",
            "060618-79-Oral Argument-Transcript",
        )
        self.assertEqual(
            keys,
            [
                "APL-2025-00221_123ent25-decision_1",
                "APL-2025-00221_060618-79-oral-argument-transcript_1",
            ],
        )

    def test_redacted_variant_does_not_collide(self):
        """``redacted`` is noise to the matcher but a distinct document here.

        Corpus-measured: 13 such keys covering 26 files, including revised and
        redacted variants. The Court names them apart, so the key does too.
        """
        keys = self._keys(
            self.ENTRIES,
            "PeoplevVassell-app-Vassell-appdx-vol1",
            "PeoplevVassell-app-Vassell-appdx-vol1-redacted",
        )
        self.assertEqual(len(set(keys)), 2)

    def test_repeated_file_name_gets_an_incrementing_suffix(self):
        """The counter is the only thing standing between a repeated name and
        a silently dropped download."""
        keys = self._keys(
            self.ENTRIES,
            "PeoplevVassell-app-Vassell-brf",
            "PeoplevVassell-app-Vassell-brf",
            "PeoplevVassell-app-Vassell-brf",
        )
        self.assertEqual(
            keys,
            [
                "APL-2025-00221_peoplevvassell-app-vassell-brf_1",
                "APL-2025-00221_peoplevvassell-app-vassell-brf_2",
                "APL-2025-00221_peoplevvassell-app-vassell-brf_3",
            ],
        )

    def test_counter_runs_over_the_slugified_name(self):
        """Names differing only in punctuation slugify to one string.

        Counted before that collapse they would each take ``_1`` and the
        second download would be dropped.
        """
        keys = self._keys(self.ENTRIES, "Vassell-Brf.", "Vassell-Brf")
        self.assertEqual(len(set(keys)), 2)

    def test_printed_extension_is_stripped(self):
        """Court-PASS prints ``.pdf`` on 152 of 14221 names and not the rest.

        The extension comes back from ``expected_type``, so leaving it in the
        key would give one file in a hundred a doubled suffix.
        """
        with_ext = self._keys(
            self.ENTRIES, "PeoplevVassell-app-Vassell-brf.pdf"
        )
        without = self._keys(self.ENTRIES, "PeoplevVassell-app-Vassell-brf")
        self.assertEqual(with_ext, without)

    def test_key_is_path_safe_and_bounded(self):
        long_party = "Nomura Asset Acceptance Corporation " * 12
        entries = [
            {
                "filing_type": "Respondent Response to Amicus Brief",
                "party": f"{long_party}(R)",
                "date_due": None,
                "date_received": None,
            }
        ]
        keys = self._keys(entries, "NomuravX-res-Nomura-brfrspamic")
        for key in keys:
            with self.subTest(key):
                self.assertLessEqual(len(key.encode()), 200)
                self.assertNotIn(":", key)
                self.assertNotIn("/", key)
                self.assertRegex(key, r"^[A-Za-z0-9._-]+$")

    def test_missing_docket_number_still_yields_a_key(self):
        linked, _ = reconcile_files_and_entries(
            self._files("PeoplevVassell-app-Vassell-brf"), self.ENTRIES
        )
        keys = archive_dedup_keys(None, linked)
        self.assertTrue(keys[0].startswith("no-docket-number_"))


class DownloadButtonTypeTest(unittest.TestCase):
    """The ``gvFiles`` download button states the file's type.

    Court-PASS labels the button by what it will hand back, so the extension
    is data the page gives us before the download rather than something to
    infer from the bytes afterwards. Over the 5091 filing-detail pages of the
    2026-08-22 corpus the label and the ``aria-label`` extension agreed on
    every one of 21382 rows.
    """

    @staticmethod
    def _button(markup):
        return LxmlPageElement(lxml_html.fromstring(markup))

    def test_pdf_button(self):
        button = self._button(
            '<input type="submit" value="Download PDF" '
            'aria-label="Download PDF: 54opn21-Decision.pdf" />'
        )
        self.assertEqual(file_type_from_button(button), "pdf")

    def test_video_button_is_an_asx_playlist(self):
        """``Video`` hands back an ASX playlist pointing at an mms:// stream.

        Sniffing the bytes calls these XML, because that is what a playlist
        is; the label is the only thing that says ``asx``.
        """
        button = self._button(
            '<input type="submit" value="Video" '
            'aria-label="Video: 111914-228-Oral-Argument-Webcast.asx" />'
        )
        self.assertEqual(file_type_from_button(button), "asx")

    def test_unavailable_row_falls_back_to_the_aria_extension(self):
        """Sealed rows are the only place the extension is not in the label,
        and the only place it varies."""
        button = self._button(
            '<input type="submit" value="Not Available" disabled="disabled" '
            'aria-label="Not Available: SomeRecord-Vol 1.txt" />'
        )
        self.assertEqual(file_type_from_button(button), "txt")

    def test_no_button_and_no_labels_are_survivable(self):
        """A restyled grid should cost the hint, not the scrape."""
        self.assertIsNone(file_type_from_button(None))
        self.assertIsNone(
            file_type_from_button(self._button('<input type="submit" />'))
        )


class VocabularyTest(unittest.TestCase):
    """Classification into the Court's published vocabularies."""

    def test_parse_yields_vocabulary_members(self):
        """Does parsing a file name classify its role and document type,
        rather than handing back whatever the filer typed?"""
        parsed = parse_file_name("SmithvJones-aplt-Smith-ADreplybrf.pdf")
        self.assertIs(parsed.role, FilingRole.APPELLANT)
        self.assertIs(parsed.doctype, FilingDocType.AD_REPLY_BRIEF)

    def test_filing_type_is_classified(self):
        """Is the FILINGS-table string classified, including the whitespace the
        table is inconsistent about?"""
        for raw in ("Appellant Reply Brief", "Appellant  Reply Brief"):
            with self.subTest(raw):
                classification = classify_filing_type(raw)
                self.assertIs(
                    classification.filing_type,
                    FilingType.APPELLANT_REPLY_BRIEF,
                )

    def test_unknown_filing_type_has_no_member(self):
        """A type the vocabulary predates is reported, not guessed at."""
        classification = classify_filing_type("Some New Filing Kind")
        self.assertIsNone(classification.filing_type)
        self.assertFalse(classification.recognized)

    def test_reconciled_entries_carry_the_classified_type(self):
        """Does a real FILINGS row come back classified, while an entry
        reconstructed from a document has no table type to classify?"""
        entries = [
            {
                "filing_type": "Appellant Brief",
                "party": "Smith",
                "date_due": None,
                "date_received": date(2025, 1, 1),
            }
        ]
        files = [
            {"file_name": "SmithvJones-app-Smith-brf", "file_index": 0},
            {"file_name": "SmithvJones-app-Smith-MotforLv", "file_index": 1},
        ]
        _, reconciled = reconcile_files_and_entries(files, entries)

        self.assertIs(
            reconciled[0]["entry_filing_type"], FilingType.APPELLANT_BRIEF
        )
        self.assertIs(reconciled[0]["entry_doctype"], FilingDocType.BRIEF)
        inferred = reconciled[1]
        self.assertTrue(inferred["inferred_from_file"])
        self.assertIsNone(inferred["entry_filing_type"])
        self.assertIs(
            inferred["entry_doctype"],
            FilingDocType.MOTION_FOR_LEAVE_TO_APPEAL,
        )

    def test_classify_issue(self):
        """Both halves of an issue string, and what the Court leaves out."""
        cases = [
            (
                "Judgments--Confession of Judgment",
                IssueCategory.JUDGMENTS,
                IssueSubcategory.CONFESSION_OF_JUDGMENT,
                True,
            ),
            # The Court states roughly 13% of issues as a bare category.
            ("Crimes", IssueCategory.CRIMES, None, True),
            # It also pads the dashes on some pages.
            (
                "Crimes -- Right to Counsel",
                IssueCategory.CRIMES,
                IssueSubcategory.RIGHT_TO_COUNSEL,
                True,
            ),
            # A subcategory it shares across categories.
            (
                "Trusts--Accounting",
                IssueCategory.TRUSTS,
                IssueSubcategory.ACCOUNTING,
                True,
            ),
            ("Cryptocurrency--Staking", None, None, False),
            (
                "Crimes--Cryptocurrency Staking",
                IssueCategory.CRIMES,
                None,
                False,
            ),
        ]
        for raw, category, subcategory, recognized in cases:
            with self.subTest(raw):
                classification = classify_issue(raw)
                self.assertEqual(classification.raw, raw)
                self.assertIs(classification.category, category)
                self.assertIs(classification.subcategory, subcategory)
                self.assertEqual(classification.recognized, recognized)


FILING_DETAIL_PAGE = """
<html><body><span id="cphMain_lbDetails2">
  <div class="case-caption">Smith,<br/>Appellant,<br/>v.<br/>Jones,<br/>Respondent.</div>
  <dl class="case-details">
    <dt>Argument Date:</dt><dd>05/24/2011</dd>
    <dt>Decision Date:</dt><dd>06/14/2011</dd>
    <dt>Official Citation:</dt><dd>17 NY3d 1</dd>
    <dt>Reported Below:</dt><dd>102 AD3d 543</dd>
  </dl>
  <section class="case-issues">
    <p class="case-issues-category">Judgments--Confession of Judgment</p>
    <p class="case-issues-text">Whether the judgments were improperly entered.</p>
    <p class="case-issues-category">Crimes</p>
  </section>
  <div>There are no files available for this case</div>
</span></body></html>
"""


class FilingDetailHandoffTest(unittest.TestCase):
    """The parser-to-model handoff for the filing-detail page.

    ``NYCourtPassIssue`` rows arrive from the parser as ``DeferredValidation``
    wrappers, and a wrapper cannot survive its parent's ``confirm()`` --
    pydantic sees an opaque object where a submodel belongs. The adapter has to
    flatten them to plain dicts, so these tests assert on the flattening and on
    the ``confirm()`` it exists to protect.
    """

    def _fields(self) -> dict:
        page = LxmlPageElement(lxml_html.fromstring(FILING_DETAIL_PAGE))
        fields, _files = NYCourtPassScraper._parse_filing_detail(page)
        return fields

    def test_issues_are_flattened_to_plain_dicts(self):
        """Issues come back as dicts, not DeferredValidation wrappers."""
        issues = self._fields()["issues"]
        self.assertEqual(len(issues), 2)
        for issue in issues:
            self.assertIsInstance(issue, dict)
        self.assertEqual(
            issues[0]["category_raw"], "Judgments--Confession of Judgment"
        )
        self.assertIs(issues[0]["category"], IssueCategory.JUDGMENTS)
        self.assertIs(
            issues[0]["subcategory"], IssueSubcategory.CONFESSION_OF_JUDGMENT
        )
        self.assertEqual(
            issues[0]["detail"],
            "Whether the judgments were improperly entered.",
        )
        # The detail list runs out on a bare category; the pairing tolerates it.
        self.assertIsNone(issues[1]["detail"])

    def test_a_docket_carrying_the_issues_validates(self):
        """The docket the adapter's fields feed actually confirms -- this is
        the failure the flattening exists to prevent."""
        fields = self._fields()
        docket = NYCourtPassDocket.raw(
            case_name="Smith v Jones",
            issues=fields["issues"],
            no_files_for_case=fields["no_files_for_case"],
        ).confirm()

        self.assertEqual(len(docket.issues), 2)
        self.assertIs(docket.issues[0].category, IssueCategory.JUDGMENTS)
        self.assertTrue(docket.issues[0].recognized)
        self.assertTrue(docket.no_files_for_case)

    def test_an_empty_issue_paragraph_yields_no_issue(self):
        """The Court publishes an empty category paragraph on some decided
        cases; that is no issue, not a blank one."""
        page = LxmlPageElement(
            lxml_html.fromstring(
                FILING_DETAIL_PAGE.replace(
                    '<p class="case-issues-category">Judgments'
                    "--Confession of Judgment</p>",
                    '<p class="case-issues-category"></p>',
                )
                .replace(
                    '<p class="case-issues-text">Whether the judgments'
                    " were improperly entered.</p>",
                    "",
                )
                .replace('<p class="case-issues-category">Crimes</p>', "")
            )
        )
        fields, _files = NYCourtPassScraper._parse_filing_detail(page)
        self.assertEqual(fields["issues"], [])


class DoctypeSpellingTest(unittest.TestCase):
    """Spellings measured in the corpus that used to yield no document type.

    Each of these left ``doctype`` None, which is not merely a missing field:
    an unreadable type also disables the type veto in the matcher, so the file
    became eligible to claim any FILINGS row left in the docket.
    """

    def test_spellings(self):
        cases = [
            # a joint or role-prefixed brief
            ("Amazonv.NYS-res-NYS-jtbrf", FilingDocType.BRIEF),
            ("HaussmannvBaumann-res-jointbrf", FilingDocType.BRIEF),
            ("PeoplevEsposito-app-People-ATappbrf", FilingDocType.BRIEF),
            # "response brief", the cross-appeal's answering brief
            (
                "HarkenridervHochul-App-Res-Harkenrider-ResponseBRF",
                FilingDocType.BRIEF,
            ),
            # the response to an amicus brief: ``to?`` demanded a literal "t"
            (
                "ContactChiropracticvNYCT-app-NYCT-brfrespamic",
                (FilingDocType.RESPONSE_TO_AMICUS_BRIEF),
            ),
            (
                "PeoplevBlue-Resp-AmicusResp",
                (FilingDocType.RESPONSE_TO_AMICUS_BRIEF),
            ),
            # supplemental, which only two doctypes carry as a member
            ("CDRvCohen-res-CDR-supprec", FilingDocType.RECORD),
            (
                "DeutscheBankvFlagstar-res-Quicken-ADsupprec",
                (FilingDocType.AD_RECORD),
            ),
            ("PeoplevCarman-app-Carman-ADressuppbrf", FilingDocType.AD_BRIEF),
            # reply, in its several spellings
            ("AcevDBStructured-App-Ace-RplyBrf", FilingDocType.REPLY_BRIEF),
            ("JacobvFranklin-app-Jacob-ADreply", FilingDocType.AD_REPLY_BRIEF),
            (
                "MattervAnderson-Respondent-ADrepbrf",
                (FilingDocType.AD_REPLY_BRIEF),
            ),
            # compendium with a modifier in front
            (
                "HomeEquityvDLJ-app-DLJ-replycompendium",
                (FilingDocType.COMPENDIUM),
            ),
            (
                "AmbacvCountrywide-amic-Browne-amiccompendium",
                (FilingDocType.COMPENDIUM),
            ),
            # AD brief with the role written before or after the "AD"
            (
                "PeoplevBlandford-app-Blandford-PeopleADbrf",
                (FilingDocType.AD_BRIEF),
            ),
            ("PeoplevBrown-app-Brown-ADprosebrf", FilingDocType.AD_BRIEF),
            # transposed and truncated SSM letters
            (
                "MatterofTyrellFF-res-SchenectadyCoDSS-ssmlrtbrf",
                (FilingDocType.SSM_LETTER),
            ),
            ("MatterofAdonnisM-res-Child-ssmltrbr", FilingDocType.SSM_LETTER),
            ("ColevCole-February 8 2018-letter", FilingDocType.SSM_LETTER),
            # appendix missing a "p"
            (
                "CarothersvProgressive-app-Carothers-apdx",
                (FilingDocType.APPENDIX),
            ),
        ]
        for file_name, expected in cases:
            with self.subTest(file_name=file_name):
                self.assertEqual(parse_file_name(file_name).doctype, expected)

    def test_a_role_prefix_does_not_invent_a_doctype(self):
        """The repeatable role prefix must still require a doctype after it."""
        for file_name in (
            "SmithvJones-app-Smith-appellant",
            "SmithvJones-app-Smith-people",
        ):
            with self.subTest(file_name=file_name):
                self.assertIsNone(parse_file_name(file_name).doctype)


class DoctypeAcrossSegmentsTest(unittest.TestCase):
    """Doctypes and volumes filers split across the ``-`` separator."""

    def test_record_on_review_spans_three_segments(self):
        parsed = parse_file_name(
            "SimonvSCJC-pet-Simon-Record-on-Review-Vol 1-of-4-Redacted"
        )
        self.assertEqual(parsed.doctype, FilingDocType.RECORD)
        self.assertEqual(parsed.volume, 1)
        self.assertEqual(parsed.party, "Simon")

    def test_volume_split_from_its_number(self):
        """``-Rec-vol-1`` -- neither half reads alone."""
        parsed = parse_file_name("Burrowsv75-25-app-Burrows-Rec-vol-1")
        self.assertEqual(parsed.doctype, FilingDocType.RECORD)
        self.assertEqual(parsed.volume, 1)

    def test_a_case_title_v_is_never_a_volume(self):
        """Bare ``v`` separates parties; only ``vol``/``part`` may join."""
        parsed = parse_file_name("Smith-v-Jones-app-Smith-brf")
        self.assertIsNone(parsed.volume)
        self.assertEqual(parsed.doctype, FilingDocType.BRIEF)
        self.assertEqual(parsed.party, "Smith")

    def test_a_trailing_year_is_noise(self):
        """A four-digit year used to become the doctype token."""
        parsed = parse_file_name("KimmelvSNY-app-SNY-ADRec-vol1-2013")
        self.assertEqual(parsed.doctype, FilingDocType.AD_RECORD)
        self.assertEqual(parsed.volume, 1)

    def test_the_join_stops_at_a_role_segment(self):
        """``-Resp-AmicusResp`` classifies either way; the role must survive."""
        parsed = parse_file_name("PeoplevBlue-Resp-AmicusResp")
        self.assertEqual(
            parsed.doctype, FilingDocType.RESPONSE_TO_AMICUS_BRIEF
        )
        self.assertEqual(parsed.role, FilingRole.RESPONDENT)


class UnreadableDoctypeTest(unittest.TestCase):
    """What an unreadable trailing segment may and may not cost."""

    def test_it_is_dropped_from_a_party_that_has_other_segments(self):
        parsed = parse_file_name("AvB_Res_App_Hochul_SomethingOdd")
        self.assertIsNone(parsed.doctype)
        self.assertEqual(parsed.unparsed_token, "SomethingOdd")
        self.assertEqual(parsed.party, "Hochul")

    def test_it_is_kept_when_it_is_the_only_party_segment(self):
        """``-OpptoMotionforLv-Alea`` puts the party last and the type first;
        dropping the tail unconditionally would lose the party entirely."""
        parsed = parse_file_name("SmithvJones-app-Smith")
        self.assertIsNone(parsed.doctype)
        self.assertEqual(parsed.party, "Smith")


class MatchEvidenceTest(unittest.TestCase):
    """A FILINGS row may only be claimed on evidence."""

    ENTRIES = [
        {
            "filing_type": "Appellant Brief",
            "party": "25 Avenue C New Realty, LLC (A)",
            "date_due": date(2013, 5, 1),
            "date_received": date(2013, 5, 1),
        },
        {
            "filing_type": "Respondent Brief",
            "party": "Alea North America Insurance Company (R)",
            "date_due": date(2013, 6, 1),
            "date_received": date(2013, 6, 1),
        },
    ]

    def test_a_file_with_nothing_in_common_stays_unmatched(self):
        """An opposition to a leave motion is not anybody's brief.

        Its doctype token sits mid-name, so the parse yields no type, no role
        and no party -- which used to *enable* the match rather than prevent
        it, since an unreadable type skips the type veto. It then inherited a
        date_received from a filing it has nothing to do with.
        """
        files = [
            {
                "file_name": "25AvenueCvAlea-OpptoMotionforLv-Alea",
                "file_index": 0,
            }
        ]
        linked, entries = reconcile_files_and_entries(files, self.ENTRIES)

        self.assertEqual(linked[0]["link_status"], "inferred")
        self.assertIsNone(linked[0]["date_received"])
        self.assertIsNone(linked[0]["date_due"])
        self.assertTrue(
            entries[linked[0]["docket_entry_index"]]["inferred_from_file"]
        )
        # and neither real row was consumed by it
        self.assertEqual(entries[0]["file_indexes"], [])
        self.assertEqual(entries[1]["file_indexes"], [])

    def test_a_party_name_alone_is_enough(self):
        """Evidence need not be the doctype: the party name will do."""
        files = [
            {"file_name": "25AvenueCvAlea-app-25AvenueC-Odd", "file_index": 0}
        ]
        linked, _ = reconcile_files_and_entries(files, self.ENTRIES)

        self.assertEqual(linked[0]["link_status"], "matched")
        self.assertEqual(linked[0]["docket_entry_index"], 0)


class CrossAppealRoleTest(unittest.TestCase):
    """Both directions of a cross-appeal must reach their own party's rows.

    Drawn from APL-2022-00042, where ``APPELLANT`` accepted
    ``APPELLANT_RESPONDENT`` but ``RESPONDENT`` accepted only
    ``RESPONDENT_APPELLANT``, so files were vetoed off their own party's row
    and took whichever row elimination left them.
    """

    ENTRIES = [
        {
            "filing_type": "Appellant Brief",
            "party": "Carl  Heastie",
            "date_due": date(2022, 4, 23),
            "date_received": date(2022, 4, 23),
        },
        {
            "filing_type": "Appellant Brief",
            "party": "Tim  Harkenrider",
            "date_due": date(2022, 4, 23),
            "date_received": date(2022, 4, 23),
        },
        {
            "filing_type": "Respondent Brief",
            "party": "Carl  Heastie",
            "date_due": date(2022, 4, 24),
            "date_received": date(2022, 4, 24),
        },
        {
            "filing_type": "Respondent Brief",
            "party": "Tim  Harkenrider",
            "date_due": date(2022, 4, 24),
            "date_received": date(2022, 4, 24),
        },
    ]

    def test_every_file_reaches_its_own_party(self):
        names = [
            "Harkenrider v Hochul_App-Res_Harkenrider_BRF",
            "Harkenrider v Hochul_App_Res_Harkenrider_ResponseBRF",
            "Harkenrider v Hochul_Res-App_Heastie_BRF",
            "Harkenrider v Hochul_Res_App_Heastie_ResponseBRF",
        ]
        files = [
            {"file_name": n, "file_index": i} for i, n in enumerate(names)
        ]
        linked, entries = reconcile_files_and_entries(files, self.ENTRIES)

        for file_row in linked:
            with self.subTest(file_name=file_row["file_name"]):
                entry = entries[file_row["docket_entry_index"]]
                party = (
                    "Harkenrider"
                    if "Harkenrider_" in (file_row["file_name"])
                    else "Heastie"
                )
                self.assertEqual(file_row["link_status"], "matched")
                self.assertIn(party, entry["party"])
        # all four rows claimed, none left holding a file it never saw
        self.assertTrue(all(e["file_indexes"] for e in entries))

    def test_an_exact_doctype_outranks_a_disagreeing_role(self):
        """The filer wrote ``app``; the table calls the row Respondent. The
        document type and the party name both agree exactly, so the row is
        still this file's."""
        entries = [
            {
                "filing_type": "Respondent COA Record",
                "party": "Audthan LLC",
                "date_due": None,
                "date_received": date(2023, 5, 22),
            }
        ]
        files = [
            {
                "file_name": "AudthanvNick-app-Audthan-JointRecord",
                "file_index": 0,
            }
        ]
        linked, _ = reconcile_files_and_entries(files, entries)

        self.assertEqual(linked[0]["link_status"], "matched")
        self.assertEqual(linked[0]["date_received"], date(2023, 5, 22))

    def test_an_amicus_naming_the_side_it_supports_still_matches(self):
        entries = [
            {
                "filing_type": "Amicus Brief",
                "party": "District Attorneys Association of the State of New"
                " York",
                "date_due": None,
                "date_received": date(2025, 12, 17),
            }
        ]
        files = [
            {
                "file_name": "PeoplevAmbrosio-resp-DAASNY-amicbrf",
                "file_index": 0,
            }
        ]
        linked, _ = reconcile_files_and_entries(files, entries)

        self.assertEqual(linked[0]["link_status"], "matched")

    def test_a_party_brief_does_not_take_an_amicus_row(self):
        """The counterweight to the waiver above: BRIEF and AMICUS_BRIEF are
        compatible types, so a party's own brief must not reach an amicus row
        while its own row is free."""
        entries = [
            {
                "filing_type": "Amicus Brief",
                "party": "New York State Department of Health",
                "date_due": None,
                "date_received": date(2020, 3, 9),
            },
            {
                "filing_type": "Respondent Brief",
                "party": "People Care Incorporated (R)",
                "date_due": None,
                "date_received": date(2020, 4, 1),
            },
        ]
        files = [
            {
                "file_name": "PeopleCarevCNY-app-PeopleCare-brf",
                "file_index": 0,
            }
        ]
        linked, _ = reconcile_files_and_entries(files, entries)

        self.assertEqual(linked[0]["docket_entry_index"], 1)


class UnpublishedVocabularyTest(unittest.TestCase):
    """Document kinds the Court's abbreviation list does not name.

    Each is reached only from a file name -- no FILINGS filing type maps to
    one -- so the guarantee that matters is that they classify, that they stay
    out of the Court's own namespace, and that none of them can claim a
    FILINGS row.
    """

    def test_spellings(self):
        cases = [
            (
                "PeoplevCazaKaren-app-Caza-PSI",
                FilingDocType.PRE_SENTENCE_REPORT,
            ),
            (
                "PeoplevHarrison-app-Harrison-psr",
                (FilingDocType.PRE_SENTENCE_REPORT),
            ),
            ("AmberRvPediatric-res-AmberR-ADorder", FilingDocType.AD_ORDER),
            ("BoylevStarwood-app-Boyle-ADreargmot", FilingDocType.AD_MOTION),
            (
                "PeoplevGuerrero-app-Guerrero-AOS",
                (FilingDocType.AFFIDAVIT_OF_SERVICE),
            ),
            (
                "Article13vPonce-res-Article13-Aff of Service",
                (FilingDocType.AFFIDAVIT_OF_SERVICE),
            ),
            (
                "BoardofManagersvKhan-app-Khan-JurRsp",
                (FilingDocType.JURISDICTIONAL_RESPONSE),
            ),
            (
                "CarothersvProgressive-app-Carothers-AppTermappbrf",
                (FilingDocType.APPELLATE_TERM_BRIEF),
            ),
            (
                "CarothersvProgressive-app-Carothers-AppTermreplybrf",
                (FilingDocType.APPELLATE_TERM_BRIEF),
            ),
            (
                "BennettvSt.Johns-app-Bennett-ADpostargbrf",
                (FilingDocType.POST_ARGUMENT_BRIEF),
            ),
            (
                "WardvCNY-app-CNY-OATH transcript",
                (FilingDocType.HEARING_TRANSCRIPT),
            ),
            (
                "PeoplevHeatley-app-Heatley-TrialTranscript",
                (FilingDocType.HEARING_TRANSCRIPT),
            ),
        ]
        for file_name, expected in cases:
            with self.subTest(file_name=file_name):
                self.assertEqual(parse_file_name(file_name).doctype, expected)

    def test_a_transcript_of_proceedings_below_is_not_court_output(self):
        """``-TrialTranscript`` used to read as this Court's oral argument,
        which made a party's record material court-generated and barred it
        from matching."""
        below = parse_file_name("PeoplevHeatley-app-Heatley-TrialTranscript")
        self.assertFalse(below.is_court_generated)

        ours = parse_file_name("042622-60-Oral Argument-Transcript")
        self.assertEqual(ours.doctype, FilingDocType.ORAL_ARGUMENT_TRANSCRIPT)
        self.assertTrue(ours.is_court_generated)

    def test_none_of_them_can_claim_a_filings_row(self):
        """No FILINGS filing type maps to one, so each must be listed in
        NOT_ON_FILINGS_TABLE -- otherwise a synthesized entry for one reads as
        the table having dropped something it usually lists."""
        unpublished = [
            doctype for doctype in FilingDocType if doctype.code >= 26
        ]
        self.assertTrue(unpublished)
        mapped = {
            doctype
            for _role, doctype in FILING_TYPE_MAP.values()
            if doctype is not None
        }
        for doctype in unpublished:
            with self.subTest(doctype=doctype.value):
                self.assertNotIn(doctype, mapped)
                self.assertIn(doctype, NOT_ON_FILINGS_TABLE)

    def test_codes_are_unique_and_reserved_values_are_free(self):
        codes = [doctype.code for doctype in FilingDocType]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertNotIn(0, codes)
        self.assertNotIn(999, codes)
        role_codes = [role.code for role in FilingRole]
        self.assertEqual(len(role_codes), len(set(role_codes)))

    def test_an_intervenor_names_the_side_it_came_in_on(self):
        """``-intervenor-res-County-`` is a role pair, like a cross-appeal;
        reading only the first of the two left ``res`` stuck on the party."""
        parsed = parse_file_name("PeoplevMarquanM-intervenor-res-County-brf")
        self.assertEqual(parsed.role, FilingRole.INTERVENOR_RESPONDENT)
        self.assertEqual(parsed.party, "County")

        plain = parse_file_name("PeoplevCabrera-ivnr-NYAG-brf")
        self.assertEqual(plain.role, FilingRole.INTERVENOR)
        self.assertEqual(plain.party, "NYAG")

    def test_an_intervenor_brief_still_reaches_an_appellant_row(self):
        """The Attorney General intervenes on a side; its brief should be able
        to match that side's row when the party name agrees."""
        entries = [
            {
                "filing_type": "Appellant Brief",
                "party": "New York State Attorney General",
                "date_due": None,
                "date_received": date(2022, 6, 1),
            }
        ]
        files = [
            {
                "file_name": "PeoplevCabrera-ivnr-app-"
                "NewYorkStateAttorneyGeneral-brf",
                "file_index": 0,
            }
        ]
        linked, _ = reconcile_files_and_entries(files, entries)
        self.assertEqual(linked[0]["link_status"], "matched")


class PartyScoreTest(unittest.TestCase):
    """A whole-name match must outrank a surviving-words match."""

    def test_two_bar_associations_are_told_apart(self):
        """Both reduce to ``{association, bar}`` once the stopword list has
        taken "new", "york", "state" and "city", so word overlap scored them a
        perfect 1.0 against each other -- enough, on APL-2015-00236, to beat
        the first party's own exact match and swap the two briefs."""
        entries = [
            {
                "filing_type": "Amicus Brief",
                "party": "Association of the Bar of the City of New York",
                "date_due": None,
                "date_received": date(2016, 4, 28),
            },
            {
                "filing_type": "Amicus Brief",
                "party": "New York State Bar Association",
                "date_due": None,
                "date_received": date(2016, 5, 11),
            },
        ]
        files = [
            {
                "file_name": "BrookeSBvElizabethACC-amic-"
                "NewYorkStateBarAssociation-amicbrf",
                "file_index": 0,
            },
            {
                "file_name": "BrookeBvElizabethCC-amic-"
                "TheAssociationoftheBaroftheCityofNewYork-amicbrf",
                "file_index": 1,
            },
        ]
        linked, _ = reconcile_files_and_entries(files, entries)

        self.assertEqual(linked[0]["docket_entry_index"], 1)
        self.assertEqual(linked[1]["docket_entry_index"], 0)


class SplitPartySideTest(unittest.TestCase):
    """The FILINGS table's ``(A)`` / ``(R)`` is a role, not part of the name."""

    def test_side_markers_are_lifted_out_of_the_name(self):
        cases = [
            ("Joseph  Scharf (A)", "Joseph Scharf", "Appellant"),
            ("The People (R)", "The People", "Respondent"),
            (
                "122 East 42nd Street, LLC (R)",
                "122 East 42nd Street, LLC",
                "Respondent",
            ),
        ]
        for cell, name, side in cases:
            with self.subTest(cell=cell):
                self.assertEqual(split_party_side(cell), (name, side))

    def test_a_name_with_no_marker_is_only_collapsed(self):
        self.assertEqual(
            split_party_side("New York Civil Liberties Union"),
            ("New York Civil Liberties Union", None),
        )

    def test_parentheticals_that_are_part_of_the_name_survive(self):
        """40 of the corpus's 13,535 trailing parentheticals are name, not side
        -- and one of them is a lowercase ``(b)``, so the match is
        case-sensitive rather than merely single-letter."""
        for cell in (
            "National Employment Lawyers Association/New York (NELA/NY)",
            "Board of Assessment Review (Town of Esopus)",
            "Kaiser (Confidential)",
            "Exhibit (b)",
        ):
            with self.subTest(cell=cell):
                self.assertEqual(split_party_side(cell), (cell, None))

    def test_an_empty_cell_stays_empty(self):
        self.assertEqual(split_party_side("   "), (None, None))
        self.assertEqual(split_party_side(None), (None, None))


class AlignPartyNameTest(unittest.TestCase):
    """A file name's squashed party segment, onto the docket's own wording."""

    CANDIDATES = [
        "1995 CAM LLC",
        "West Side Advisors, LLC",
        "Joseph Scharf",
        "New York City Transit Authority",
        "City of New York",
    ]

    def test_containment_reaches_the_full_legal_name(self):
        cases = [
            ("1995CAM", "1995 CAM LLC"),
            ("WestSideAdvisors", "West Side Advisors, LLC"),
            ("Scharf", "Joseph Scharf"),
        ]
        for token, expected in cases:
            with self.subTest(token=token):
                name, tier = align_party_name(token, self.CANDIDATES)
                self.assertEqual(name, expected)
                self.assertEqual(tier, "containment")

    def test_an_initialism_resolves(self):
        name, tier = align_party_name("NYCTA", self.CANDIDATES)
        self.assertEqual(name, "New York City Transit Authority")
        self.assertEqual(tier, "initialism")

    def test_a_run_of_initials_need_not_start_the_name(self):
        """``DHCR`` is the tail of ``nysdhcr``, not the whole of it."""
        name, tier = align_party_name(
            "DHCR",
            ["New York State Division of Housing and Community Renewal"],
        )
        self.assertEqual(
            name, "New York State Division of Housing and Community Renewal"
        )
        self.assertEqual(tier, "initialism")

    def test_abbreviated_and_misspelled_names_reach_it_by_subsequence(self):
        cases = [
            ("IroquoisCSD", "Iroquois Central School District"),
            ("DLJMortage", "DLJ Mortgage Capital, Inc."),
            ("CityofNY", "City of New York"),
            ("Wiliam", "William Penn Life Insurance Company of New York"),
        ]
        for token, expected in cases:
            with self.subTest(token=token):
                name, tier = align_party_name(token, [expected])
                self.assertEqual(name, expected)
                self.assertEqual(tier, "subsequence")

    def test_a_subsequence_must_start_at_a_word(self):
        """Without the anchor, "Lee" runs l...e...e through half the corpus."""
        self.assertEqual(
            align_party_name("Lees", ["Charles Ellsworth Ames"]),
            (None, None),
        )

    def test_decoration_glued_after_the_party_is_dropped(self):
        """Filers append the doctype, a volume, a note to the clerk, or the
        opposing party to the segment the convention reserves for the party."""
        cases = [
            "Scharf-ADreplybrf",
            "Scharf-Rec-vol3-Filed Under Seal",
            "Scharf-compendium of cited materials",
        ]
        for token in cases:
            with self.subTest(token=token):
                name, _ = align_party_name(token, self.CANDIDATES)
                self.assertEqual(name, "Joseph Scharf")

    def test_a_hyphenated_name_is_tried_whole_first(self):
        name, _ = align_party_name(
            "409-411SixthStreet", ["409-411 Sixth Street, LLC"]
        )
        self.assertEqual(name, "409-411 Sixth Street, LLC")

    def test_a_pinned_on_given_initial_breaks_the_tie(self):
        """The surname alone ties, so the initial the filer pinned on is the
        whole of the evidence -- ``ColeS`` and ``ColeJ`` on APL-2019-00240."""
        cases = [
            ("ColeS", "Samantha Cole"),
            ("ColeJ", "Jesse Cole"),
        ]
        for token, expected in cases:
            with self.subTest(token=token):
                name, tier = align_party_name(
                    token, ["Samantha Cole", "Child", "Jesse Cole"]
                )
                self.assertEqual(name, expected)
                self.assertEqual(tier, "overlap")

    def test_the_initial_still_has_to_pick_exactly_one(self):
        """Bernadette and Bernard V. Strianese, both parties on APL-2014-00287,
        answer to the same initial."""
        self.assertEqual(
            align_party_name(
                "StrianeseB", ["Bernadette Strianese", "Bernard V. Strianese"]
            ),
            (None, None),
        )

    def test_an_initial_written_first_is_not_read(self):
        """``StrianeseB`` would tie-break; ``BStrianese`` -- the same docket's
        actual file name -- does not, because the tiebreak only reads the
        initial-last shape. Nothing is lost: initial-first is
        indistinguishable from a doctype token (``RRec``, ``ADresp``,
        ``ADrepbrf`` are the corpus's only other examples), and this pair is
        ambiguous either way."""
        strianeses = ["Bernadette Strianese", "Bernard V. Strianese"]
        self.assertEqual(
            align_party_name("BStrianese", strianeses), (None, None)
        )
        # ...and with only one of them on the docket the initial is not needed:
        # the surname alone reaches her, no tiebreak involved.
        name, tier = align_party_name(
            "BStrianese", ["Bernadette Strianese", "Rita Cusimano"]
        )
        self.assertEqual(name, "Bernadette Strianese")
        self.assertEqual(tier, "overlap")

    def test_the_name_the_token_opens_wins(self):
        """``JPMorgan`` fits both parties on APL-2016-00114, but only one of
        them is named J.P. Morgan -- the other carries it mid-name, inside a
        trust's title."""
        name, tier = align_party_name(
            "JPMorgan",
            [
                "Bank of New York Mellon, Securities Adminstrator for "
                "J.P. Morgan Acquisition Trust 2006-WMC4",
                "J.P. Morgan Mortgage Acquisition Corporation, et al.",
            ],
        )
        self.assertEqual(
            name, "J.P. Morgan Mortgage Acquisition Corporation, et al."
        )
        self.assertEqual(tier, "containment")

    def test_a_shorter_candidate_the_token_opens_also_wins(self):
        """Here the *token* is the longer string -- a joint amicus naming two
        organizations -- and it opens with the first one's whole name."""
        name, _ = align_party_name(
            "LawyersforChildrenandChildren'sLawCenter",
            ["Lawyers for Children", "Child"],
        )
        self.assertEqual(name, "Lawyers for Children")

    def test_a_rival_the_token_fully_names_blocks_the_tiebreak(self):
        """``Bloomberg`` opens "Bloomberg L.P." but is also exactly how one
        refers to "Michael Bloomberg", and APL-2019-00218 has both. Two live
        readings is not a tie worth breaking."""
        self.assertEqual(
            align_party_name(
                "Bloomberg-CitedMaterial",
                ["Bloomberg L.P.", "Michael Bloomberg"],
            ),
            (None, None),
        )

    def test_a_token_fitting_two_parties_is_left_alone(self):
        """``ColeS`` and ``ColeJ`` against a single "Samantha Cole" on
        APL-2019-00240 -- the docket has relatives, and guessing is worse than
        keeping the file name's word for it."""
        self.assertEqual(
            align_party_name("Cole", ["Samantha Cole", "Jared Cole"]),
            (None, None),
        )

    def test_one_party_spelled_two_ways_is_not_a_disagreement(self):
        """The FILINGS table and the attorney table both name the party; the
        pool carries whichever came first, and the other must not veto it."""
        name, _ = align_party_name(
            "Scharf", ["Joseph Scharf", "Joseph  Scharf"]
        )
        self.assertEqual(name, "Joseph Scharf")

    def test_nothing_to_match_against(self):
        self.assertEqual(align_party_name("Scharf", []), (None, None))
        self.assertEqual(align_party_name(None, self.CANDIDATES), (None, None))


class InferredPartyAlignmentTest(unittest.TestCase):
    """Alignment, as ``reconcile_files_and_entries`` applies it."""

    ENTRIES = [
        {
            "filing_type": "Appellant Brief",
            "party": "122 East 42nd Street, LLC",
            "date_due": None,
            "date_received": date(2023, 3, 3),
        }
    ]

    def _inferred(self, file_name, **kwargs):
        _, entries = reconcile_files_and_entries(
            [{"file_name": file_name, "file_index": 0}],
            self.ENTRIES,
            **kwargs,
        )
        return next(e for e in entries if e["inferred_from_file"])

    def test_a_filings_party_supplies_the_wording(self):
        entry = self._inferred("122East42ndvScharf-res-122East42ndStreet-opp")
        self.assertEqual(entry["party"], "122 East 42nd Street, LLC")
        self.assertEqual(entry["party_match"], "containment")

    def test_the_attorney_table_supplies_it_when_filings_does_not(self):
        entry = self._inferred(
            "122East42ndvScharf-app-Scharf-mot",
            party_names=["Joseph Scharf"],
        )
        self.assertEqual(entry["party"], "Joseph Scharf")
        self.assertEqual(entry["party_match"], "containment")

    def test_an_unmatched_segment_keeps_the_file_name_wording(self):
        entry = self._inferred("122East42ndvScharf-amic-Apollo-amicbrf")
        self.assertEqual(entry["party"], "Apollo")
        self.assertIsNone(entry["party_match"])

    def test_a_real_row_is_never_aligned(self):
        _, entries = reconcile_files_and_entries([], self.ENTRIES)
        self.assertEqual(entries[0]["party"], "122 East 42nd Street, LLC")
        self.assertIsNone(entries[0]["party_match"])

    def test_the_raw_segment_stays_on_the_file(self):
        linked, _ = reconcile_files_and_entries(
            [
                {
                    "file_name": "122East42ndvScharf-res-122East42ndStreet-opp",
                    "file_index": 0,
                }
            ],
            self.ENTRIES,
        )
        self.assertEqual(linked[0]["doc_party"], "122East42ndStreet")

    def test_the_entry_id_is_keyed_on_the_raw_segment(self):
        """The id has to mean the same thing every run, and the aligned name
        depends on an attorney table that gains and loses parties."""
        without = self._inferred("122East42ndvScharf-app-Scharf-mot")
        with_names = self._inferred(
            "122East42ndvScharf-app-Scharf-mot",
            party_names=["Joseph Scharf"],
        )
        self.assertEqual(without["party"], "Scharf")
        self.assertEqual(with_names["party"], "Joseph Scharf")
        self.assertEqual(
            without["docket_entry_id"], with_names["docket_entry_id"]
        )
        self.assertEqual(
            with_names["docket_entry_id"], "d:appellant:scharf:mot:1"
        )


class CleanCaseTitleTest(unittest.TestCase):
    """Court-PASS's caption typography must not reach the case name."""

    def test_escaped_markup_and_rules_become_a_separator(self):
        """The Title element literally contains ``&lt;br /&gt;----&lt;br /&gt;``
        between the captions of consolidated companion cases."""
        self.assertEqual(
            clean_case_title(
                [
                    "In the Matter of WTC Litigation.",
                    "<br />---------------------------------<br />",
                    "Stanislaw Faltynowicz, et al.,",
                    "Appellants,",
                    "v.",
                    "Battery Park City Authority.",
                ]
            ),
            "In the Matter of WTC Litigation.; Stanislaw Faltynowicz, et al.,"
            " Appellants, v. Battery Park City Authority.",
        )

    def test_a_doubled_comma_is_collapsed(self):
        self.assertEqual(
            clean_case_title(["Harkenrider v. Kathy Hochul,, et al."]),
            "Harkenrider v. Kathy Hochul, et al.",
        )

    def test_a_hyphenated_name_survives(self):
        """Only a *rule* folds; the hyphens inside a party name stay."""
        self.assertEqual(
            clean_case_title(["938 St. Nicholas v. 936-938 Cliffcrest Corp."]),
            "938 St. Nicholas v. 936-938 Cliffcrest Corp.",
        )


if __name__ == "__main__":
    unittest.main()
