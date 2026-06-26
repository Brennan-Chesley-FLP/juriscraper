"""Parser for a West Virginia courtswv.gov case-detail page.

Each detail page is a Drupal node rendering one block per field, with
class names prefixed ``field--name-field-{prefix}-docket-*`` (``{prefix}``
is ``sca`` or ``ica``). :class:`CaseDetailParser` extracts the case scalars
into a single :class:`WVDocket`; the briefs file-field is pulled separately
via :meth:`extract_briefs` because each brief becomes its own archive
download (and top-level :class:`WVBrief`) in the calling step.

The page does *not* carry the ``court``, the source URL, or the listing
fallback values — the step stamps those onto the returned ``raw_data``
before emitting (see ``scraper.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin

from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.west_virginia.courtswv_gov.models import WVDocket

from ._common import (
    clerk_holds_briefs,
    component_for_brief,
    parse_detail_iso_datetime,
    parse_detail_rendered_date,
    split_docket_numbers,
)

if TYPE_CHECKING:
    from jkent.common.deferred_validation import DeferredValidation
    from jkent.common.page_element import PageElement


class CaseDetailParser(JKentParser[WVDocket]):
    """Parse one Drupal case-detail page into a single ``WVDocket``.

    Returns a one-element list (or an empty list when the page carries no
    ``*-docket-case-no`` block — a calendar/month-aggregator page rather
    than a single case). ``court``, ``source_url``, ``source_entry_point``,
    and the listing fallback values (``listing_case_no``,
    ``listing_docket_date``, ``listing_youtube_url``) are stamped by the
    calling step.
    """

    def __init__(self, field_prefix: str) -> None:
        self.field_prefix = field_prefix

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[WVDocket]]:
        case_no_text = (self._field_text(page, "case-no") or "").strip()
        if not case_no_text:
            # Some ICA listing rows link to month-aggregator pages with
            # no case-no field. They're not single cases — skip.
            return []

        consolidated = split_docket_numbers(case_no_text)
        primary_docket_number = (
            consolidated[0] if consolidated else case_no_text
        )

        case_name = self._field_text(page, "case-name") or case_no_text
        date_argued = self._parse_detail_date(page)
        argument_time = self._field_text(page, "time")
        argument_type = self._field_text(page, "argument-type")
        youtube_url = self._field_link(page, "youtube-link")
        note_text = self._field_text(page, "note")

        docket = WVDocket.raw(
            docket_number=primary_docket_number,
            consolidated_docket_numbers=consolidated,
            case_name=case_name,
            date_argued=date_argued,
            argument_time=argument_time,
            argument_type=argument_type,
            youtube_url=youtube_url,
            clerk_has_briefs=clerk_holds_briefs(note_text),
            note=note_text,
        )
        return [docket]

    # =====================================================================
    # Briefs (one archive download / WVBrief each — handled by the step)
    # =====================================================================

    def extract_briefs(
        self,
        page: PageElement,
        *,
        primary_docket_number: str,
        consolidated_numbers: list[str],
        base_url: str | None,
    ) -> list[dict]:
        """Pull brief / order references from the case-detail page.

        Returns a list of plain dicts (``docket_number``, ``description``,
        ``download_url``) suitable for plumbing into archive Requests via
        ``accumulated_data``. The brief field is absent entirely for
        clerk-only cases; missing block → ``[]``.
        """
        prefix = self.field_prefix
        items = page.query(
            XPath(
                f"//div[contains(@class,'field--name-field-{prefix}-docket-briefs')]"
                f"//div[contains(@class,'field__item')]"
            ),
            "brief items",
            min_count=0,
        )
        briefs: list[dict] = []
        for item in items:
            hrefs = item.query_strings(
                XPath(".//a/@href"), "brief href", min_count=0, max_count=1
            )
            if not hrefs:
                continue
            url = urljoin(base_url or "", hrefs[0])
            label_parts = item.query_strings(
                XPath(".//a//text()"), "brief label", min_count=0
            )
            description = " ".join(p.strip() for p in label_parts if p.strip())

            component = component_for_brief(
                description, consolidated_numbers, primary_docket_number
            )
            briefs.append(
                {
                    "docket_number": component,
                    "description": description or None,
                    "download_url": url,
                }
            )
        return briefs

    # =====================================================================
    # Drupal field helpers
    # =====================================================================

    def _field_text(self, page: PageElement, suffix: str) -> str | None:
        """Extract the rendered text from a Drupal field block.

        Drupal renders a field with class
        ``field--name-field-{prefix}-docket-{suffix}``. The value lives
        inside ``.field__item`` (sometimes nested with ``<p>`` /
        ``<strong>`` tags). We collect every text node under that block,
        join with spaces, and trim.
        """
        prefix = self.field_prefix
        text_nodes = page.query_strings(
            XPath(
                f"//div[contains(@class,'field--name-field-{prefix}-docket-{suffix}')]"
                f"//div[contains(@class,'field__item')]//text()"
            ),
            f"{prefix}-{suffix} text",
            min_count=0,
        )
        text = " ".join(t.strip() for t in text_nodes if t.strip())
        return text or None

    def _field_link(self, page: PageElement, suffix: str) -> str | None:
        """Extract the first ``<a href>`` from a Drupal field block."""
        prefix = self.field_prefix
        hrefs = page.query_strings(
            XPath(
                f"//div[contains(@class,'field--name-field-{prefix}-docket-{suffix}')]"
                f"//a/@href"
            ),
            f"{prefix}-{suffix} href",
            min_count=0,
            max_count=1,
        )
        return hrefs[0] if hrefs else None

    def _parse_detail_date(self, page: PageElement):
        """Pull the ISO date attribute from the docket-date ``<time>``,
        falling back to the rendered text."""
        prefix = self.field_prefix
        iso_values = page.query_strings(
            XPath(
                f"//div[contains(@class,'field--name-field-{prefix}-docket-date')]"
                f"//time/@datetime"
            ),
            f"{prefix}-docket-date datetime",
            min_count=0,
            max_count=1,
        )
        if iso_values:
            parsed = parse_detail_iso_datetime(iso_values[0])
            if parsed is not None:
                return parsed
        # Fall back to the rendered text (e.g. "Wednesday, April 22, 2026").
        return parse_detail_rendered_date(self._field_text(page, "date"))
