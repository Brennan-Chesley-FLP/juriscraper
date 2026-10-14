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
    parse_session_title,
    split_brief_title,
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
        <p>Oral Argument Calendar for February 4, 2026 at UC Davis</p>
      </div>
    </header>
    <div class="jcc-body__main-text usa-prose clearfix"></div>
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


if __name__ == "__main__":
    unittest.main()
