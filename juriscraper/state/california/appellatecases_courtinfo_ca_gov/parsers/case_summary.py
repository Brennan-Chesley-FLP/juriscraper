"""Parser for the Case Summary tab (``parse_case_summary``).

Both Supreme Court (``dist=0``) and Court of Appeal pages render their
metadata as a ``<dl>`` definition list, but with different term labels and
extra fields, so the parser branches on ``is_supreme``.

The returned ``DeferredValidation[CaAppDocket]`` is a *partial* field-bag,
not a finished record: the scraper step merges its ``raw_data`` into
``accumulated_data`` and the docket is only assembled once every tab has
been visited. Alongside model fields the bag carries navigation helpers the
step consumes and discards (``opinion_file_urls`` for archive requests,
``trial_court_case_single`` for the CoA fallback). Dates are real ``date``
objects; they survive the trip through ``accumulated_data`` because the
queue's JSON encoder serializes them to ISO and pydantic re-parses at
confirm.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.california.appellatecases_courtinfo_ca_gov.models import (
    CaAppDocket,
)

from ._common import clean_text, fields_from_definition_list, parse_date

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

        # Email-notification subscription URLs (data, kept on the docket).
        sub_links = page.find_links(
            XPath("//a[contains(@href, '/email.cfm')]"),
            "email notification links",
            min_count=0,
        )
        bag["subscription_urls"] = [link.url for link in sub_links]

        dts = page.query(
            XPath("//dl/dt"), "summary definition terms", min_count=0
        )
        dds = page.query(
            XPath("//dl/dd"), "summary definition values", min_count=0
        )
        fields = fields_from_definition_list(dts, dds)

        if self.is_supreme:
            bag["case_name"] = fields.get("Case Caption", "")
            bag["case_type"] = clean_text(fields.get("Case Category"))
            bag["date_filed"] = parse_date(fields.get("Start Date"))
            bag["case_status"] = clean_text(fields.get("Case Status"))
            bag["issues"] = clean_text(fields.get("Issues"))
            bag["case_citation"] = clean_text(fields.get("Case Citation"))

            pdf_links = page.query(
                XPath("//a[contains(@href, '.PDF')]/@href"),
                "opinion PDF link",
                min_count=0,
                max_count=1,
            )
            docx_links = page.query(
                XPath("//a[contains(@href, '.DOCX')]/@href"),
                "opinion DOCX link",
                min_count=0,
                max_count=1,
            )
            bag["opinion_pdf_url"] = (
                pdf_links[0].text_content() if pdf_links else None
            )
            bag["opinion_docx_url"] = (
                docx_links[0].text_content() if docx_links else None
            )

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

        # Opinion file links (id=pdf / id=doc) for archive requests. The
        # step turns these into archive Requests; the filename extension
        # rides along so it can hint ``expected_type``.
        opinion_file_urls: list[dict] = []
        for link in page.find_links(
            XPath("//a[@id='pdf' or @id='doc']"),
            "opinion file links",
            min_count=0,
        ):
            url = link.url
            m = re.search(r"\.([A-Za-z]{2,4})(?:$|\?)", url)
            ext = m.group(1).lower() if m else "bin"
            opinion_file_urls.append({"url": url, "ext": ext})
        bag["opinion_file_urls"] = opinion_file_urls

        return [CaAppDocket.raw(**bag)]
