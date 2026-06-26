"""Parser for the row-based NJ Courts listing pages.

Both paginated listings share one row layout:

- SCOTNJ ``/courts/supreme/appeals`` — Supreme Court appeals (pending +
  decided). Rows carry a question paragraph, opinion links, and inline
  oral-argument media in addition to briefs.
- SCAD ``/courts/appellate/briefs-from-argued-cases`` — Appellate
  Division argued cases. Rows carry only an ``Argued`` event and briefs.

Each row is a ``<tr><td><div class="row"><div class="col-lg-9"> caption +
opinion link + question + briefs button + modal </div><div
class="col-lg-3"> events </div></div></td></tr>``.

:class:`ListingParser` returns one :class:`NJDocket` per row, with nested
:class:`NJDocketEntry` events and :class:`NJDocument` records (briefs,
opinions, and SCOTNJ oral-argument media). The scraper step owns the
download fan-out (re-reads ``documents`` for ``archive=True`` requests)
and the pagination follow (:func:`next_page_url`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.new_jersey.njcourts_gov.models import (
    NJDocket,
    NJDocketEntry,
    NJDocument,
)

from ._common import (
    APPELLATE_DOCKET_RE,
    EVENT_LINE_RE,
    abs_url,
    normalise,
    parse_caption_block,
    parse_date,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class ListingParser(JKentParser[NJDocket]):
    """Parse one page of an NJ Courts row-based listing into dockets.

    Args:
        court: CourtListener court id stamped onto the dockets and their
            documents (``nj`` for SCOTNJ, ``njsuperctappdiv`` for SCAD).
        include_question: ``True`` for SCOTNJ rows (which carry a question
            paragraph, opinion links, and oral-argument media); ``False``
            for SCAD-argued rows.

    Both default so :meth:`JKentParser.from_string` / ``from_file`` (which
    call the parser with no arguments) work for offline structural tests.
    """

    def __init__(
        self, court: str = "", *, include_question: bool = True
    ) -> None:
        self.court = court
        self.include_question = include_question

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[NJDocket]]:
        rows = page.query(
            XPath("//table//tr[td]"), "listing rows", min_count=0
        )
        out: list[DeferredValidation[NJDocket]] = []
        for row in rows:
            docket = self._parse_row(row)
            if docket is not None:
                out.append(docket)
        return out

    # =====================================================================
    # Row → docket
    # =====================================================================

    def _parse_row(
        self, row: PageElement
    ) -> DeferredValidation[NJDocket] | None:
        docket_number = self._row_docket_id(row)
        caption = self._row_caption(row)
        if not docket_number or not caption:
            return None

        # CMS id lives in the trailing parenthetical of the SCOTNJ caption.
        _, cms_id = parse_caption_block(self._row_h5_text(row))

        entries = self._row_events(row)
        briefs, missing_reason = self._row_briefs(row)

        # date_filed: earliest dated event on the row.
        dated = [e["date_filed"] for e in entries if e["date_filed"]]
        date_filed = min(dated) if dated else None

        # date_argued: the ``Argued`` event if there is one.
        date_argued = next(
            (
                e["date_filed"]
                for e in entries
                if e["description"].lower().startswith("argued")
                and e["date_filed"]
            ),
            None,
        )

        opinions = (
            self._row_opinion_links(row) if self.include_question else []
        )
        appellate_docket_number = self._appellate_docket_id(opinions)
        appellate_opinion_url = self._appellate_opinion_url(opinions)
        question = self._row_question(row) if self.include_question else None
        oa_media = self._row_oa_media(row) if self.include_question else []

        # Aggregate every downloadable artefact for the docket. SCOTNJ
        # rows can carry briefs (PDF), opinion PDFs, plus oral-argument
        # MP4/MP3 from the Supreme Court library.
        all_links: list[tuple[str, str]] = (
            list(briefs)
            + list(opinions)
            + [(desc, url) for desc, url, _ in oa_media]
        )

        documents = [
            NJDocument(
                docket_number=docket_number,
                court=self.court,
                document_url=url,
                description=desc,
            )
            for desc, url in all_links
        ]

        entry_models = [
            NJDocketEntry(
                description=e["description"],
                date_filed=e["date_filed"],
                notes=e["notes"],
            )
            for e in entries
        ]

        return NJDocket.raw(
            docket_number=docket_number,
            court=self.court,
            case_name=caption,
            date_filed=date_filed,
            cms_id=cms_id,
            question_presented=question,
            appellate_docket_number=appellate_docket_number,
            appellate_opinion_url=appellate_opinion_url,
            date_argued=date_argued,
            missing_entries_reason=missing_reason,
            entries=entry_models,
            documents=documents,
        )

    # =====================================================================
    # Row field extractors
    # =====================================================================

    @staticmethod
    def _row_docket_id(row: PageElement) -> str | None:
        """Extract the docket id (text *before* the caption ``<u>``).

        Two surface shapes:

        - Pending: ``<p class="h5">A-40-25 <u>caption</u> (091434)</p>``
        - Decided: ``<p class="h5"><a href="opinion.pdf">A-1-25
          <u>caption</u> (091055)</a></p>``

        Both put the docket id as the leading token before the ``<u>``
        element, so we extract by splitting the normalised text on the
        caption substring.
        """
        h5 = row.query(
            XPath(".//p[contains(@class, 'h5')]"), "p.h5", min_count=0
        )
        if not h5:
            return None
        underline = h5[0].query(XPath(".//u"), "u", min_count=0)
        if not underline:
            return None
        full = normalise(h5[0].text_content())
        caption = normalise(underline[0].text_content())
        if caption and caption in full:
            head = full.split(caption, 1)[0].strip()
            return head or None
        return full.split()[0] if full else None

    @staticmethod
    def _row_caption(row: PageElement) -> str | None:
        """Case caption — content of the first ``<u>`` element in the row."""
        underline = row.query(
            XPath(".//p[contains(@class, 'h5')]//u"), "caption", min_count=0
        )
        if not underline:
            return None
        return normalise(underline[0].text_content())

    @staticmethod
    def _row_h5_text(row: PageElement) -> str:
        """Full text content of the row's ``<p class='h5'>`` block."""
        h5 = row.query(
            XPath(".//p[contains(@class, 'h5')]"), "p.h5", min_count=0
        )
        return normalise(h5[0].text_content()) if h5 else ""

    @staticmethod
    def _row_question(row: PageElement) -> str | None:
        """Question paragraph (SCOTNJ only) — the ``<p>`` after the
        opinion link."""
        paragraphs = row.query(
            XPath(
                ".//div[contains(@class, 'col-lg-9')]"
                "/p[not(contains(@class, 'h5'))]"
            ),
            "case paragraphs",
            min_count=0,
        )
        # Skip the "Read Appellate Opinion" paragraph (a single <a>).
        for p in paragraphs:
            text = normalise(p.text_content())
            if not text:
                continue
            if (
                "appellate opinion" in text.lower()
                or "opinion " in text.lower()[:20]
            ):
                anchors = p.query(XPath("./a"), "anchors", min_count=0)
                if anchors and normalise(anchors[0].text_content()) == text:
                    continue
            return text
        return None

    @staticmethod
    def _row_opinion_links(row: PageElement) -> list[tuple[str, str]]:
        """All opinion-style anchor links inside the row body (col-lg-9).

        Returns ``(text, absolute_url)`` for every ``<a>`` whose href
        points under ``/system/files/court-opinions/`` — covers both
        SCOTNJ-issued opinions (decided rows) and the cross-referenced
        SCAD ``Read Appellate Opinion`` link. Excludes modal-body brief
        links (which live under ``.modal``).
        """
        anchors = row.query(
            XPath(
                ".//div[contains(@class, 'col-lg-9')]"
                "//a[contains(@href, '/system/files/court-opinions/')]"
                "[not(ancestor::div[contains(@class, 'modal')])]"
            ),
            "opinion links",
            min_count=0,
        )
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for a in anchors:
            url = abs_url(a.get_attribute("href"))
            if not url or url in seen:
                continue
            seen.add(url)
            out.append((normalise(a.text_content()) or "Opinion", url))
        return out

    @staticmethod
    def _appellate_docket_id(
        opinions: list[tuple[str, str]],
    ) -> str | None:
        """Pull an originating SCAD docket id (e.g. ``A-1602-24``) from a
        ``Read Appellate Opinion A-1602-24`` link's text.
        """
        for text, _ in opinions:
            if "appellate opinion" not in text.lower():
                continue
            m = APPELLATE_DOCKET_RE.search(text)
            if m:
                return m.group(0)
        return None

    @staticmethod
    def _appellate_opinion_url(
        opinions: list[tuple[str, str]],
    ) -> str | None:
        """Return the URL of the cross-referenced SCAD appellate opinion."""
        for text, url in opinions:
            if "appellate opinion" in text.lower():
                return url
        return None

    @staticmethod
    def _row_oa_media(
        row: PageElement,
    ) -> list[tuple[str, str, str]]:
        """Extract oral-argument media (video / audio) for the row.

        SCOTNJ rows whose oral argument has been recorded include a
        Bootstrap modal containing a ``<video><source src="...mp4">`` and
        a sibling ``<a href="...mp3">`` audio link. Both media URLs live
        on ``library.njcourts.gov`` and are returned as
        ``(description, url, expected_type)`` tuples for archiving.
        """
        out: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        sources = row.query(
            XPath(".//source[contains(@src, 'library.njcourts.gov')]"),
            "video sources",
            min_count=0,
        )
        for s in sources:
            url = s.get_attribute("src") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(("Oral Argument Video", url, "mp4"))
        audio = row.query(
            XPath(
                ".//a[contains(@href, 'library.njcourts.gov')"
                " and contains(@href, '.mp3')]"
            ),
            "audio links",
            min_count=0,
        )
        for a in audio:
            url = a.get_attribute("href") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(("Oral Argument Audio", url, "mp3"))
        return out

    @staticmethod
    def _row_events(row: PageElement) -> list[dict]:
        """Parse the right-hand event list into event dicts.

        SCOTNJ rows format each event as ``<li>Event : Date</li>``.
        SCAD-argued rows format the only event as a label outside the
        ``<li>`` (``Argued:`` followed by an ``<li>April 30, 2026</li>``).
        Both shapes are handled by joining the ``col-lg-3`` text and
        splitting on the colon.

        Returns plain dicts (``description``/``date_filed``/``notes``);
        the caller derives ``date_filed``/``date_argued`` and builds the
        :class:`NJDocketEntry` records.
        """
        block = row.query(
            XPath(".//div[contains(@class, 'col-lg-3')]"),
            "events block",
            min_count=0,
        )
        if not block:
            return []

        entries: list[dict] = []
        # Strategy 1 (SCOTNJ): each <li> has its own "Event : Date".
        items = block[0].query(XPath(".//li"), "li", min_count=0)
        seen_lines: set[str] = set()
        for li in items:
            line = normalise(li.text_content())
            if not line or line in seen_lines:
                continue
            seen_lines.add(line)
            entry = ListingParser._event_from_line(line)
            if entry:
                entries.append(entry)
        if entries:
            return entries

        # Strategy 2 (SCAD-argued): plain "Argued:" label outside the <li>.
        entry = ListingParser._event_from_line(
            normalise(block[0].text_content())
        )
        return [entry] if entry else []

    @staticmethod
    def _event_from_line(line: str) -> dict | None:
        """Split an ``Event : value`` line into an event dict."""
        m = EVENT_LINE_RE.match(line)
        if not m:
            return None
        name = normalise(m.group("name"))
        rest = normalise(m.group("rest"))
        parsed = parse_date(rest)
        return {
            "description": name,
            "date_filed": parsed,
            "notes": rest if not parsed else None,
        }

    @staticmethod
    def _row_briefs(
        row: PageElement,
    ) -> tuple[list[tuple[str, str]], str | None]:
        """Return ``(briefs, missing_reason)`` for a listing row.

        ``briefs`` is a list of ``(description, absolute_url)`` tuples.
        ``missing_reason`` is set to ``"Briefs are sealed"`` when the
        Bootstrap modal title contains that phrase — even if the modal
        body still lists a few public order PDFs.
        """
        modals = row.query(
            XPath(".//div[contains(@class, 'modal') and @id]"),
            "modal",
            min_count=0,
        )
        if not modals:
            return [], None
        modal = modals[0]

        title_nodes = modal.query(
            XPath(".//*[@id='modal-title']"), "title", min_count=0
        )
        title_text = (
            normalise(title_nodes[0].text_content()) if title_nodes else ""
        )
        missing = (
            "Briefs are sealed" if "sealed" in title_text.lower() else None
        )

        briefs: list[tuple[str, str]] = []
        anchors = modal.query(
            XPath(".//div[contains(@class, 'modal-body')]//a[@href]"),
            "brief link",
            min_count=0,
        )
        for a in anchors:
            url = abs_url(a.get_attribute("href"))
            if not url:
                continue
            briefs.append((normalise(a.text_content()) or "Brief", url))
        return briefs, missing


def next_page_url(page: PageElement, current_url: str) -> str | None:
    """Find the Drupal pager's "Next page" link, resolved against the
    current URL so that all filter params (``filter_by``, ``start``,
    ``end``, ``field_argued_dates_value``) are preserved.
    """
    links = page.query(
        XPath(
            "//nav[@aria-label='pagination-heading']"
            "//a[@title='Go to next page']"
        ),
        "next page",
        min_count=0,
    )
    if not links:
        return None
    href = links[0].get_attribute("href") or ""
    return urljoin(current_url, href) if href else None
