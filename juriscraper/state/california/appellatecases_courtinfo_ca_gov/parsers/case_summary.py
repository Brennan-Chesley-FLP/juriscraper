"""Parser for the Case Summary tab (``parse_case_summary``).

Both Supreme Court (``dist=0``) and Court of Appeal pages render their
metadata as a ``<dl>`` definition list, but with different term labels and
extra fields, so the parser branches on ``is_supreme``.

The returned ``DeferredValidation[CaAppDocket]`` is a *partial* field-bag,
not a finished record: the scraper step merges its ``raw_data`` into
``accumulated_data`` and the docket is only assembled once every tab has
been visited. Alongside model fields the bag carries a navigation helper the
step consumes and discards (``trial_court_case_single`` for the CoA
fallback). Dates are real ``date`` objects; they survive the trip through
``accumulated_data`` because the queue's JSON encoder serializes them to ISO
and pydantic re-parses at confirm.

Opinion files are handled entirely by the step, not here: it finds the
``a#pdf`` / ``a#doc`` links and yields one archive request each, so the
selector the Playwright driver clicks stays out of the parser and every file
becomes a ``CaDocument``. This parser deliberately extracts no opinion
URLs — it used to set ``opinion_pdf_url`` / ``opinion_docx_url`` on the
Supreme Court branch, but those never produced a value (they passed an
``@href`` XPath to ``query()``, which yields elements and so silently matched
nothing, with ``min_count=0`` hiding it) and they could not represent the
``.DOC`` files anyway.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.california.appellatecases_courtinfo_ca_gov.models import (
    CaAppDocket,
)

from ._common import (
    DefinitionPair,
    cell_lines,
    clean_optional,
    clean_text,
    definition_list_pairs,
    definition_term,
    fields_from_definition_list,
    parse_date,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class CaseSummaryParser(JKentParser[CaAppDocket]):
    """Extract the Case Summary definition list and opinion links.

    ``from_string`` exercises the Court-of-Appeal layout (``is_supreme``
    defaults to False); construct ``CaseSummaryParser(is_supreme=True)``
    directly to test the Supreme Court layout.
    """

    def __init__(self, is_supreme: bool = False) -> None:
        self.is_supreme = is_supreme

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[CaAppDocket]]:
        bag: dict = {}

        # Email-notification subscription URL (data, kept on the docket).
        # Matched on the anchor id rather than on ``/email.cfm``: the left-hand
        # nav carries an "E-mail" button pointing at the court-wide
        # ``/email.cfm?dist=0`` form, which is site chrome, not a subscription
        # for this case -- it was landing on every docket alongside the real
        # per-case link.
        sub_links = page.find_links(
            XPath("//a[starts-with(@id, 'emailLink')]"),
            "case e-mail notification link",
            min_count=0,
        )
        bag["subscription_urls"] = [link.url for link in sub_links]

        pairs = definition_list_pairs(page)
        fields = fields_from_definition_list(pairs)

        # Cross-referenced cases, read off their own anchors rather than by
        # term lookup -- the block's label has no <dd>, and each case's number
        # is the <dt> with the caption in the paired <dd>.
        bag["cross_referenced_cases"] = self._cross_referenced(pairs)

        if self.is_supreme:
            bag["case_name"] = fields.get("Case Caption", "")
            bag["case_type"] = clean_text(fields.get("Case Category"))
            bag["date_filed"] = parse_date(fields.get("Start Date"))
            bag["case_status"] = clean_text(fields.get("Case Status"))
            bag["issues"] = clean_text(fields.get("Issues"))
            bag["case_citation"] = clean_optional(fields.get("Case Citation"))
            # The SC's equivalent of the CoA "Completion Date". Present on
            # 12,445 of 12,500 sampled SC summaries, yet ``date_terminated``
            # was null on all 302,103 SC dockets of a full sweep -- the field
            # was simply never read off the page.
            bag["date_terminated"] = parse_date(fields.get("Disposition Date"))

            # Trial courts named on the summary page. Consumed by the step
            # rather than kept here: they seed ``trial_court_case_numbers``
            # and, when the Lower Court tab turns out to have no data, that
            # tab's ``trial_courts``.
            bag["summary_trial_courts"] = self._summary_trial_courts(pairs)

            coa_links = page.find_links(
                XPath("//dd//a[starts-with(@href, 'mainCaseScreen')]"),
                "CoA case links",
                min_count=0,
            )
            bag["coa_case_numbers"] = [link.text for link in coa_links]
        else:
            bag["case_name"] = fields.get("Case Caption", "")
            bag["case_type"] = clean_text(fields.get("Case Type"))
            bag["division"] = clean_text(fields.get("Division"))
            bag["date_filed"] = parse_date(fields.get("Filing Date"))
            bag["date_terminated"] = parse_date(fields.get("Completion Date"))
            bag["date_argued"] = clean_text(
                fields.get("Oral Argument Date/Time")
            )
            # Singular case-summary "Trial Court Case" field. The step only
            # uses it when the multi-result fan-out hasn't already supplied
            # an authoritative list of trial-court numbers.
            bag["trial_court_case_single"] = clean_text(
                fields.get("Trial Court Case")
            )

            # Reciprocal of the SC branch's coa_case_numbers: the upward link
            # to the Supreme Court case, present when review was sought
            # (18,663 of 98,002 Third District pages). Matched on dist=0 so
            # the sibling-tab mainCaseScreen links can't be mistaken for it.
            # max_count=1 because the field carries exactly one link wherever
            # it appears -- drift should surface as a structural error rather
            # than a silent truncation.
            sc_links = page.find_links(
                XPath(
                    "//dl/dd//a[starts-with(@href, 'mainCaseScreen')"
                    " and contains(@href, 'dist=0')]"
                ),
                "Supreme Court case link",
                min_count=0,
                max_count=1,
            )
            bag["supreme_court_case_number"] = (
                sc_links[0].text if sc_links else None
            )

        return [CaAppDocket.raw(**bag)]

    @classmethod
    def _summary_trial_courts(cls, pairs: list[DefinitionPair]) -> list[dict]:
        """Read the Supreme Court summary's "Trial Court Case" block.

        Its ``<dd>`` is a ``<br>``-separated run rather than a field: a court
        name followed by its case number ("Fresno County Superior Court -
        Main" / "3237203"), repeated once per consolidated matter, and
        sometimes just a bare number with no court named at all. Across 4,490
        sampled SC summaries the block held two lines on 371 pages, one on
        132, and four or six -- several matters, each flagged "(lead)" -- on
        three.

        So the lines are walked rather than positionally indexed: a line
        naming a court opens an entry, and anything else is a case number for
        the entry most recently opened.
        """
        for dt_el, dd_el in pairs:
            if dd_el is None or definition_term(dt_el) != "Trial Court Case":
                continue
            return cls._split_trial_courts(cell_lines(dd_el))
        return []

    @staticmethod
    def _split_trial_courts(lines: list[str]) -> list[dict]:
        """Split ``Trial Court Case`` lines into one dict per matter."""
        courts: list[dict] = []
        for line in lines:
            if "court" in line.lower():
                courts.append(
                    {"name": line, "case_number": None, "is_lead": False}
                )
                continue
            number, lead, _ = line.partition("(lead)")
            entry = {
                "name": None,
                "case_number": clean_text(number),
                "is_lead": bool(lead),
            }
            if courts and courts[-1]["case_number"] is None:
                courts[-1].update(
                    case_number=entry["case_number"], is_lead=entry["is_lead"]
                )
            else:
                courts.append(entry)
        return [c for c in courts if c["name"] or c["case_number"]]

    @staticmethod
    def _cross_referenced(pairs: list[DefinitionPair]) -> list[dict]:
        """Read the "Cross Referenced Cases" block into one dict per case.

        Each case is a ``<dt>`` wrapping
        ``<a id="relatedCase_S168103" href="mainCaseScreen.cfm?...">S168103</a>``
        with its caption in the paired ``<dd>``. Keying off the ``relatedCase_``
        anchor id rather than the "Cross Referenced Cases:" label is what makes
        this work: that label is a ``<dt>`` with no ``<dd>`` of its own, so it
        names no value to walk from, and the cases are siblings of it rather
        than children.
        """
        cases: list[dict] = []
        for dt_el, dd_el in pairs:
            links = dt_el.find_links(
                XPath(".//a[starts-with(@id, 'relatedCase_')]"),
                "cross-referenced case link",
                min_count=0,
            )
            for link in links:
                cases.append(
                    {
                        "docket_number": link.text.strip(),
                        "case_name": clean_text(
                            dd_el.text_content() if dd_el is not None else None
                        ),
                        "case_link": link.url,
                    }
                )
        return cases
