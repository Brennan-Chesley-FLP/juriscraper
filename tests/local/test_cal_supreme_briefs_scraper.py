"""Offline parser tests for the California Supreme Court briefs scraper.

The HTML fixtures are compact but structurally faithful to
``supreme.courts.ca.gov/case-information/briefs-argued-cases``: the same
Drupal wrappers, class names, and flat ``h2``/``p``/``jcc-list`` sibling run
the live session pages use, plus the hand-authored ``jcc-body`` variant six
of them carry. They exercise the real XPath in each ``JKentParser`` and the
site defects documented in the scraper's CC_NOTES.md.
"""

import unittest
from datetime import date

import lxml.html
from jkent.common.page_element import PageElement

from juriscraper.state.california.supreme_courts_ca_gov.models import (
    CalSupremeArgumentSession,
    CalSupremeBriefCase,
    CalSupremeSessionType,
)
from juriscraper.state.california.supreme_courts_ca_gov.parsers import (
    BriefsIndexParser,
    SessionPageParser,
)
from juriscraper.state.california.supreme_courts_ca_gov.parsers._common import (  # noqa: E501
    fix_mojibake,
    parse_session_title,
    split_brief_title,
)
from juriscraper.state.california.supreme_courts_ca_gov.vocabularies import (
    CaBriefDocumentType,
)

INDEX_URL = (
    "https://supreme.courts.ca.gov/case-information/briefs-argued-cases"
)
SESSION_URL = f"{INDEX_URL}/february-4-2026-oral-argument-cases"

INDEX_HTML = """
<html><body><div class="page"><main><article>
  <div class="usa-accordion">
    <h4><button class="usa-accordion__button">Current Year</button></h4>
    <div class="usa-accordion__content">
      <ul>
        <li><a href="/case-information/briefs-argued-cases/february-4-2026-oral-argument-cases">February 4, 2026 Oral Argument Cases</a></li>
        <li><a href="/case-information/briefs-argued-cases/may-6-7-2026-oral-argument-cases">May 6 &amp; 7, 2026 Oral Argument Cases</a></li>
      </ul>
    </div>
    <h4><button class="usa-accordion__button">2013</button></h4>
    <div class="usa-accordion__content">
      <ul>
        <li><a href="/case-information/briefs-argued-cases/october-9-2013-special-session-oral-argument-cases">October 9, 2013 Special Session Oral Argument Cases</a></li>
      </ul>
    </div>
  </div>
  <nav><a href="/case-information/oral-arguments">Oral Arguments</a>
       <a href="/case-information/briefs-argued-cases">Briefs of Argued Cases</a></nav>
</article></main></div></body></html>
"""  # noqa: E501

SESSION_HTML = """
<html><head><title>February 4, 2026 Oral Argument Cases | Supreme Court of California</title></head>
<body><div class="page"><main><article>
  <h1 class="jcc-hero__main-title"><span>February 4, 2026 Oral Argument Cases</span></h1>
  <section class="jcc-section"><div class="jcc-section__inner">
    <div class="views-element-container">
      <section class="jcc-section"><div class="jcc-section__inner">

        <h2>S289430 - IN RE Z.G.</h2>
        <p><em>(Consolidated case with S289441 - G. (A.) ON H.C.)</em></p>
        <p><em>(Baltodano, J., assigned justice pro tempore)</em></p>
        <div class="jcc-list jcc-list--style-bullet"><ol>
          <li class="jcc-list__item">
            <a class="jcc-list__link" href="/sites/default/files/supremecourt/default/documents/1-10-s289430-app-pet-rev-022425.pdf">Appellant&rsquo;s Petition for Review </a>
            Filed on February 24, 2025
          </li>
          <li class="jcc-list__item">
            <a class="jcc-list__link" href="/sites/default/files/supremecourt/default/documents/2-90-s289430-ac-consumer-attorneys-050325.pdf">Amicus Curiae Brief of Consumer Attorneys of California </a>
            Filed on May 3, 2025
          </li>
        </ol></div>

        <h2>S277314 &ndash; PEOPLE v. MITCHELL (SUNEE LYNN)</h2>
        <p></p>
        <div class="jcc-list jcc-list--style-bullet"><ol>
          <li class="jcc-list__item">
            <a class="jcc-list__link" href="/sites/default/files/supremecourt/default/documents/1.%20S277314%20Real%20Party%27s%20in%20Interest%20Answer%20Brief%20on%20the%20Merits%20102309.pdf">Real Party&rsquo;s in Interest Answer Brief on the Merits </a>
            Filed on October 23, 2009
          </li>
          <li class="jcc-list__item">
            Respondent, L.A. Truck Centers, LLC, Opening Brief on the Merits
            Filed on April 27, 2017
          </li>
        </ol></div>

        <h2>NO CASE ASSIGNED</h2>
        <p></p>
        <div class="jcc-list jcc-list--style-bullet"><ol>
          <li class="jcc-list__item">
            <a class="jcc-list__link" href="/sites/default/files/supremecourt/default/documents/1-s198132-app-opening-brief-012214_0.pdf">Appellant&rsquo;s Opening Brief </a>
            Filed on January 22, 2014
          </li>
        </ol></div>

      </div></section>
    </div>
  </div></section>

  <div class="jcc-body"><div class="jcc-body__content"><div class="jcc-body__main">
    <header class="jcc-section-heading">
      <h2 class="jcc-section-heading__title"><span>C061011 &ndash; PROFESSIONAL ENGINEERS v. SCHWARZENEGGER</span></h2>
      <div class="jcc-section-heading__lead usa-prose">
        <p><em><strong>(To be called and continued to a future oral argument calendar.)</strong></em></p>
      </div>
    </header>
    <div class="jcc-body__main-text usa-prose clearfix">
      <ol><li><a href="https://live-jcc-supremecourt.pantheonsite.io/sites/default/files/supremecourt/default/documents/7-c061011-app-focus-issues-ltr-052220.pdf">Appellant&rsquo;s Opening Brief</a> Filed on April 28, 2014</li></ol>
    </div>
  </div></div></div>

  <div class="jcc-body"><div class="jcc-body__content"><div class="jcc-body__main">
    <header class="jcc-section-heading">
      <h2 class="jcc-section-heading__title"><span>Special Note:  </span></h2>
      <div class="jcc-section-heading__lead usa-prose">
        <p><a href="/sites/default/files/supremecourt/default/2022-06/SSFEB0426A.pdf">Oral Argument Calendar for February 4, 2026 at UC Davis</a></p>
        <p><a href="/sites/default/files/supremecourt/default/2022-06/davis_case_summaries.pdf">Expanded Case Summaries</a></p>
      </div>
    </header>
    <div class="jcc-body__main-text usa-prose clearfix"></div>
  </div></div></div>

  <div class="jcc-body"><div class="jcc-body__content"><div class="jcc-body__main">
    <div class="jcc-body__main-text usa-prose clearfix">
      <p><em>The morning session was dedicated to a special outreach program.</em></p>
      <p>1. S289430 - IN RE Z.G.</p>
    </div>
  </div></div></div>
</article></main></div></body></html>
"""  # noqa: E501


class SessionTitleTest(unittest.TestCase):
    """The date span lives only in the session title, in a dozen spellings."""

    def test_every_spelling_the_court_uses(self):
        cases = [
            (
                "January 27, 2010 Oral Argument Cases",
                "2010-01-27",
                "2010-01-27",
            ),
            (
                "May 25 – 27, 2010 Oral Argument Cases",
                "2010-05-25",
                "2010-05-27",
            ),
            (
                "June 2 and 3, 2026 Oral Argument Cases",
                "2026-06-02",
                "2026-06-03",
            ),
            (
                "May 6 & 7, 2026 Oral Argument Cases",
                "2026-05-06",
                "2026-05-07",
            ),
            (
                "February 7 - 10, 2011 Oral Argument Cases",
                "2011-02-07",
                "2011-02-10",
            ),
            (
                "May 31 - June 3, 2011 Oral Argument Cases",
                "2011-05-31",
                "2011-06-03",
            ),
            (
                "November 8, 9, and 10, 2011 Oral Argument Cases",
                "2011-11-08",
                "2011-11-10",
            ),
            (
                "January 5, 2016, Oral Argument Cases",
                "2016-01-05",
                "2016-01-05",
            ),
            (
                "January 12, 2022 Oral Arguments Cases",
                "2022-01-12",
                "2022-01-12",
            ),
            ("May 3, 2022 Oral Argument Briefs", "2022-05-03", "2022-05-03"),
        ]
        for title, start, end in cases:
            with self.subTest(title=title):
                parsed = parse_session_title(title)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed[0].isoformat(), start)
                self.assertEqual(parsed[1].isoformat(), end)
                self.assertEqual(parsed[2], CalSupremeSessionType.REGULAR)

    def test_session_kind_and_trailing_parenthetical(self):
        parsed = parse_session_title(
            "October 6, 2015 Outreach Session Oral Argument Cases "
            "(Morning Session)"
        )
        self.assertEqual(parsed[0], date(2015, 10, 6))
        self.assertEqual(parsed[2], CalSupremeSessionType.OUTREACH)

        parsed = parse_session_title(
            "October 9, 2013 Special Session Oral Argument Cases"
        )
        self.assertEqual(parsed[2], CalSupremeSessionType.SPECIAL)

    def test_unparseable_title_is_none_not_a_guess(self):
        self.assertIsNone(parse_session_title("Oral Argument Cases"))


class BriefTitleTest(unittest.TestCase):
    """The link text splits into (filer, document type) three ways."""

    def test_the_three_grammars_and_the_bare_form(self):
        cases = [
            (
                "Appellant’s Opening Brief on the Merits",
                "Appellant",
                "Opening Brief on the Merits",
            ),
            (
                "Amicus Curiae Brief of Consumer Attorneys of California",
                "Consumer Attorneys of California",
                "Amicus Curiae Brief",
            ),
            (
                "Real Party in Interest, The People, Answer Brief on the Merits",
                "Real Party in Interest, The People",
                "Answer Brief on the Merits",
            ),
            ("Petition for Review", None, "Petition for Review"),
        ]
        for title, filer, doc_type in cases:
            with self.subTest(title=title):
                self.assertEqual(split_brief_title(title), (filer, doc_type))

    def test_apostrophe_inside_a_party_name_does_not_split_the_title(self):
        # "Workers' Compensation" would split the possessive form in the
        # wrong place; the comma rules it out.
        self.assertEqual(
            split_brief_title(
                "Respondent, Workers' Compensation Appeals Board, "
                "Answer Brief on the Merits"
            ),
            (
                "Respondent, Workers' Compensation Appeals Board",
                "Answer Brief on the Merits",
            ),
        )

    def test_misplaced_apostrophe_in_real_partys_in_interest(self):
        self.assertEqual(
            split_brief_title("Real Party's in Interest Petition for Review"),
            ("Real Party in Interest", "Petition for Review"),
        )


class ConjoinedAndDashedFilerTest(unittest.TestCase):
    """Title forms the 2026-10-17 data audit found going unsplit.

    78 of the 226 titles that produced no ``filed_by`` were the comma form
    with a filer the role set did not list: a conjunction of two roles, a
    plural, one of the court's four typos, or a role written with a dash
    instead of commas.
    """

    def test_conjoined_and_plural_roles_split(self):
        cases = [
            (
                "Intervener and Respondent, Californians to Mend, "
                "Not End, the Death Penalty, Written Return",
                "Intervener and Respondent, Californians to Mend, "
                "Not End, the Death Penalty",
                "Written Return",
            ),
            (
                "Interveners and Appellants, SEIU Local 1021, "
                "Answer Brief on the Merits",
                "Interveners and Appellants, SEIU Local 1021",
                "Answer Brief on the Merits",
            ),
            (
                "Non-Title Respondents, CDCR, Informal Response",
                "Non-Title Respondents, CDCR",
                "Informal Response",
            ),
            (
                "Real Pary in Interest, The People, Answer Brief on the Merits",
                "Real Pary in Interest, The People",
                "Answer Brief on the Merits",
            ),
        ]
        for title, filer, doc_type in cases:
            with self.subTest(title=title):
                self.assertEqual(split_brief_title(title), (filer, doc_type))

    def test_dashed_filer_splits(self):
        self.assertEqual(
            split_brief_title(
                "Real Parties in Interest - Preliminary Opposition"
            ),
            ("Real Parties in Interest", "Preliminary Opposition"),
        )

    def test_a_leading_phrase_that_is_not_a_role_leaves_the_title_whole(self):
        # The widening must not invent a filer out of a document title that
        # merely opens with a comma- or dash-separated clause.
        for title in (
            "Declaration of Charles H. Bell, Jr., Regarding the Likelihood",
            "Response to June 15, 2016 Order, Exhibit A",
            "Service Employees International Union, Local 1021, Brief",
            "Appendix of Exhibits - Volume 2",
        ):
            with self.subTest(title=title):
                self.assertEqual(split_brief_title(title), (None, title))


class MojibakeTest(unittest.TestCase):
    """The court double-encodes 13 brief titles; the repair is one-way."""

    def test_double_encoded_text_is_repaired(self):
        self.assertEqual(
            fix_mojibake("Amicus Curiae Brief of George Gasc\u00c3\u00b3n"),
            "Amicus Curiae Brief of George Gasc\u00f3n",
        )
        self.assertEqual(
            fix_mojibake("Death Penalty \u00e2\u20ac\u201c No on Prop. 62"),
            "Death Penalty \u2013 No on Prop. 62",
        )

    def test_correctly_encoded_text_is_untouched(self):
        # These are the near misses: accented characters the court spelled
        # right, which the round trip must reject rather than mangle.
        for text in (
            "San Jos\u00e9 Police & Fire Department Retirement Plan",
            "Hern\u00e1ndez v. Mu\u00f1oz",
            "Appellant's Brief \u2014 Volume I",
            "plain ascii",
        ):
            with self.subTest(text=text):
                self.assertEqual(fix_mojibake(text), text)


class BriefDocumentTypeVocabularyTest(unittest.TestCase):
    """``document_type`` is coded; ``document_type_raw`` keeps the words."""

    def test_spelling_variants_map_to_one_member(self):
        variants = {
            "Opening Brief on the Merits Filed": (
                CaBriefDocumentType.OPENING_BRIEF_ON_THE_MERITS
            ),
            "Additional Authority Letter": (
                CaBriefDocumentType.ADDITIONAL_AUTHORITIES_LETTER
            ),
            "Reply brief": CaBriefDocumentType.REPLY_BRIEF,
            "Answer to Petition For Review": (
                CaBriefDocumentType.ANSWER_TO_PETITION_FOR_REVIEW
            ),
        }
        for raw, member in variants.items():
            with self.subTest(raw=raw):
                self.assertIs(CaBriefDocumentType.parse(raw), member)

    def test_an_uncovered_title_codes_to_none_rather_than_raising(self):
        self.assertIsNone(
            CaBriefDocumentType.parse("Expanded Background Summary")
        )
        self.assertIsNone(CaBriefDocumentType.parse(None))
        self.assertIsNone(CaBriefDocumentType.parse(""))

    def test_reserved_codes_are_never_assigned(self):
        codes = [member.code for member in CaBriefDocumentType]
        self.assertNotIn(0, codes)
        self.assertNotIn(999, codes)
        self.assertEqual(len(codes), len(set(codes)))


class BriefsIndexParserTest(unittest.TestCase):
    def setUp(self):
        self.sessions = [
            record.raw_data
            for record in BriefsIndexParser.from_string(
                INDEX_HTML, url=INDEX_URL
            )
        ]

    def test_only_session_links_are_sessions(self):
        # The nav links to the index itself and to /oral-arguments are not.
        self.assertEqual(len(self.sessions), 3)
        for session in self.sessions:
            CalSupremeArgumentSession(**session)

    def test_dates_and_kind_come_off_the_link_text(self):
        first = self.sessions[0]
        self.assertEqual(first["date_session_start"], date(2026, 2, 4))
        self.assertEqual(first["date_session_end"], date(2026, 2, 4))
        self.assertEqual(first["court"], "cal")
        self.assertTrue(first["source_url"].startswith("https://"))

        self.assertEqual(
            self.sessions[1]["date_session_end"], date(2026, 5, 7)
        )
        self.assertEqual(
            self.sessions[2]["session_type"], CalSupremeSessionType.SPECIAL
        )


class SessionPageParserTest(unittest.TestCase):
    def setUp(self):
        self.cases = [
            record.raw_data
            for record in SessionPageParser.from_string(
                SESSION_HTML, url=SESSION_URL
            )
        ]
        self.by_number = {case["docket_number"]: case for case in self.cases}

    def test_both_page_shapes_are_read_and_the_venue_note_is_not_a_case(self):
        self.assertEqual(
            sorted(self.by_number),
            ["C061011", "S198132", "S277314", "S289430"],
        )
        for case in self.cases:
            CalSupremeBriefCase(**case, source_url=SESSION_URL)

    def test_court_comes_from_the_case_number_prefix(self):
        self.assertEqual(self.by_number["S289430"]["court"], "cal")
        self.assertEqual(self.by_number["C061011"]["court"], "calctapp_3rd")

    def test_single_day_session_sets_date_argued(self):
        case = self.by_number["S289430"]
        self.assertEqual(case["date_argued"], date(2026, 2, 4))
        self.assertEqual(case["date_session_start"], date(2026, 2, 4))
        self.assertEqual(case["date_session_end"], date(2026, 2, 4))
        self.assertEqual(
            case["session_title"], "February 4, 2026 Oral Argument Cases"
        )

    def test_a_case_can_carry_more_than_one_note(self):
        case = self.by_number["S289430"]
        self.assertIn("Consolidated case with S289441", case["notes"])
        self.assertIn("Baltodano", case["notes"])
        self.assertEqual(case["consolidated_with"], ["S289441"])

    def test_a_pro_tempore_note_consolidates_nothing(self):
        self.assertEqual(self.by_number["C061011"]["consolidated_with"], [])

    def test_briefs_are_numbered_by_list_position(self):
        briefs = self.by_number["S289430"]["briefs"]
        self.assertEqual([b["document_number"] for b in briefs], [1, 2])
        self.assertEqual(briefs[0]["filed_by"], "Appellant")
        self.assertEqual(briefs[0]["document_type"], "Petition for Review")
        self.assertEqual(briefs[0]["date_filed"], date(2025, 2, 24))
        self.assertEqual(briefs[1]["document_type"], "Amicus Curiae Brief")

    def test_urls_resolve_and_filenames_are_url_decoded(self):
        briefs = self.by_number["S289430"]["briefs"]
        self.assertEqual(
            briefs[0]["url"],
            "https://supreme.courts.ca.gov/sites/default/files/supremecourt"
            "/default/documents/1-10-s289430-app-pet-rev-022425.pdf",
        )
        self.assertEqual(
            self.by_number["S277314"]["briefs"][0]["filename"],
            "1. S277314 Real Party's in Interest Answer Brief on the "
            "Merits 102309.pdf",
        )

    def test_a_brief_the_court_linked_no_file_for_is_still_recorded(self):
        unlinked = self.by_number["S277314"]["briefs"][1]
        self.assertIsNone(unlinked["url"])
        self.assertIsNone(unlinked["filename"])
        self.assertEqual(unlinked["date_filed"], date(2017, 4, 27))
        self.assertIn("L.A. Truck Centers", unlinked["description"])

    def test_no_case_assigned_recovers_the_number_from_the_filenames(self):
        case = self.by_number["S198132"]
        self.assertEqual(case["heading_raw"], "NO CASE ASSIGNED")
        self.assertIsNone(case["case_name"])

    def test_staging_host_links_are_rewritten_to_the_live_host(self):
        url = self.by_number["C061011"]["briefs"][0]["url"]
        self.assertTrue(url.startswith("https://supreme.courts.ca.gov/"))
        self.assertNotIn("pantheonsite.io", url)


class SessionRecordTest(unittest.TestCase):
    """The session record, and the hand-authored block that is not a case.

    A ``jcc-body__main`` block whose heading states no case number is the
    court's note *about the session* -- the only place the page says which
    venue a Special Session sat at or which program an Outreach session
    served. Six of the corpus's 191 sessions carry one; one of those also
    links the session's printed oral argument calendar.
    """

    def setUp(self):
        # ``from_string`` returns only the cases (the parser's ``__call__``
        # contract), so the session is read through ``parse`` over the
        # ``PageElement`` a step would be handed.
        page = PageElement(
            lxml.html.fromstring(SESSION_HTML), request_url=SESSION_URL
        )
        self.session = SessionPageParser().parse(page)[0].raw_data

    def test_the_session_validates_with_the_url_the_step_adds(self):
        CalSupremeArgumentSession(**self.session, source_url=SESSION_URL)

    def test_note_blocks_are_joined_and_the_special_note_label_is_dropped(
        self,
    ):
        note = self.session["session_note"]
        self.assertIn(
            "Oral Argument Calendar for February 4, 2026 at UC Davis", note
        )
        self.assertIn("The morning session was dedicated", note)
        self.assertIn("1. S289430 - IN RE Z.G.", note)
        self.assertNotIn("Special Note:", note)

    def test_session_documents_are_collected_with_absolute_urls(self):
        documents = self.session["documents"]
        self.assertEqual(
            [document["description"] for document in documents],
            [
                "Oral Argument Calendar for February 4, 2026 at UC Davis",
                "Expanded Case Summaries",
            ],
        )
        self.assertEqual(
            documents[1]["url"],
            "https://supreme.courts.ca.gov/sites/default/files"
            "/supremecourt/default/2022-06/davis_case_summaries.pdf",
        )
        self.assertEqual(documents[1]["filename"], "davis_case_summaries.pdf")

    def test_a_case_block_is_not_mistaken_for_a_session_note(self):
        self.assertNotIn(
            "PROFESSIONAL ENGINEERS", self.session["session_note"]
        )
        self.assertNotIn(
            "7-c061011-app-focus-issues-ltr-052220.pdf",
            str(self.session["documents"]),
        )


if __name__ == "__main__":
    unittest.main()
