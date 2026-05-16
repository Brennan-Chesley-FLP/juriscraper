"""New Jersey Judiciary scraper (njcourts.gov).

Scrapes appellate dockets from three public listing pages on
https://www.njcourts.gov:

- ``/courts/supreme/appeals`` — pending and decided Supreme Court
  appeals (mixed). Filterable by event date via ``filter_by``,
  ``start``, ``end``.
- ``/courts/appellate/argument-schedule`` — upcoming SCAD oral
  arguments. Snapshot only (no historical access).
- ``/courts/appellate/briefs-from-argued-cases`` — SCAD cases that
  have been argued, listed by argument date.

All endpoints serve full server-rendered HTML with no JS challenge or
CSRF gate, so the scraper runs over plain ``httpx``. Brief / order /
opinion PDFs are downloaded with ``archive=True`` and emitted as
``NJDocument``.

The ``missing_entries_reason`` field on ``NJDocket`` is populated when
the page indicates that documents have been withheld from public view —
either ``RECORD IMPOUNDED`` (SCAD) or ``Briefs are sealed`` (SCOTNJ).

See ``DESIGN.md`` for the full investigation.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlencode, urljoin

from jkent.common.decorators import entry, step
from jkent.common.page_element import PageElement
from jkent.common.param_models import DateRange
from jkent.data_types import (
    BaseScraper,
    HttpMethod,
    HTTPRequestParams,
    ParsedData,
    Request,
    Response,
    ScraperStatus,
    SkipDeduplicationCheck,
)
from pyrate_limiter import Duration, Rate

from .models import COURT_IDS, NJDocket, NJDocketEntry, NJDocument

if TYPE_CHECKING:
    from collections.abc import Generator

    from jkent.data_types import ScraperYield


BASE_URL = "https://www.njcourts.gov"
SCOTNJ_LISTING_URL = f"{BASE_URL}/courts/supreme/appeals"
SCAD_ARGUMENT_SCHEDULE_URL = f"{BASE_URL}/courts/appellate/argument-schedule"
SCAD_ARGUED_LISTING_URL = (
    f"{BASE_URL}/courts/appellate/briefs-from-argued-cases"
)


# ─── Surface-string parsing ──────────────────────────────────────────

# Caption parenthetical e.g. "(091434)" — six-digit CMS id on SCOTNJ rows.
_CMS_ID_RE = re.compile(r"\((\d{5,7})\)\s*$")

# "RECORD IMPOUNDED" appears at the end of SCAD argument-schedule captions.
_IMPOUNDED_RE = re.compile(r"\(RECORD IMPOUNDED\)\s*$", re.IGNORECASE)

# Right-column event row: "Event Name : Date" (sometimes "Event Name: Date").
_EVENT_LINE_RE = re.compile(r"^(?P<name>[^:]+?)\s*:\s*(?P<rest>.+)$")


def _normalise(text: str | None) -> str:
    """Collapse whitespace and trim."""
    if not text:
        return ""
    return " ".join(text.split())


def _parse_date(text: str | None) -> date | None:
    """Parse a date string from any of the formats used on njcourts.gov.

    Examples observed: ``April 10, 2026``, ``Jan. 21, 2026``,
    ``Feb. 24, 2026``, ``July 2, 2026``, ``Sept. 3, 2025``. The site
    uses both 3-letter abbreviations and the 4-letter ``Sept`` form,
    so we normalise that quirk before strptime.
    """
    if not text:
        return None
    s = _normalise(text).rstrip(".")
    s = re.sub(r"^[A-Za-z]+,\s+", "", s)
    s = re.sub(r"\bSept\.\s", "Sep. ", s)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%b. %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _abs(href: str | None, base: str = BASE_URL) -> str | None:
    """Resolve a possibly-relative href against the site base URL."""
    if not href:
        return None
    return urljoin(base, href)


def _parse_caption_block(p_h5_text: str) -> tuple[str, str | None]:
    """Pull the trailing ``(NNNNNN)`` CMS id out of an SCOTNJ caption.

    The ``<p class="h5">`` contains ``"A-40-25 In re … (091434)"`` after
    text-content normalisation. Returns ``(text_without_cms, cms_id)``.
    """
    text = _normalise(p_h5_text)
    m = _CMS_ID_RE.search(text)
    if not m:
        return text, None
    return text[: m.start()].rstrip(), m.group(1)


# ─── Listing-row helpers (shared across SCOTNJ + SCAD-argued) ────────

# Each row is a `<tr><td><div class="row"> <div class="col-lg-9"> caption + opinion link + question + briefs button + modal </div> <div class="col-lg-3"> events </div> </div> </td></tr>`.


def _row_docket_id(row: PageElement) -> str | None:
    """Extract the docket id (text *before* the caption ``<u>``).

    Two surface shapes:

    - Pending: ``<p class="h5">A-40-25 <u>caption</u> (091434)</p>``
    - Decided: ``<p class="h5"><a href="opinion.pdf">A-1-25 <u>caption</u> (091055)</a></p>``

    Both put the docket id as the leading token before the
    ``<u>`` element, so we extract by string-splitting the normalised
    text on the caption substring.
    """
    h5 = row.query_xpath(".//p[contains(@class, 'h5')]", "p.h5", min_count=0)
    if not h5:
        return None
    underline = h5[0].query_xpath(".//u", "u", min_count=0)
    if not underline:
        return None
    full = _normalise(h5[0].text_content())
    caption = _normalise(underline[0].text_content())
    if caption and caption in full:
        head = full.split(caption, 1)[0].strip()
        return head or None
    return full.split()[0] if full else None


def _row_caption(row: PageElement) -> str | None:
    """Case caption text — content of the first ``<u>`` element in the row."""
    underline = row.query_xpath(
        ".//p[contains(@class, 'h5')]//u", "caption", min_count=0
    )
    if not underline:
        return None
    return _normalise(underline[0].text_content())


def _row_h5_text(row: PageElement) -> str:
    """Full text content of the row's ``<p class='h5'>`` block."""
    h5 = row.query_xpath(".//p[contains(@class, 'h5')]", "p.h5", min_count=0)
    return _normalise(h5[0].text_content()) if h5 else ""


def _row_question(row: PageElement) -> str | None:
    """Question paragraph (SCOTNJ only) — the ``<p>`` after the opinion link."""
    paragraphs = row.query_xpath(
        ".//div[contains(@class, 'col-lg-9')]/p[not(contains(@class, 'h5'))]",
        "case paragraphs",
        min_count=0,
    )
    # Skip the "Read Appellate Opinion" paragraph (contains a single <a>).
    for p in paragraphs:
        text = _normalise(p.text_content())
        if not text:
            continue
        if (
            "appellate opinion" in text.lower()
            or "opinion " in text.lower()[:20]
        ):
            anchors = p.query_xpath("./a", "anchors", min_count=0)
            if anchors and _normalise(anchors[0].text_content()) == text:
                continue
        return text
    return None


def _row_opinion_links(row: PageElement) -> list[tuple[str, str]]:
    """All opinion-style anchor links inside the row body (col-lg-9).

    Returns a list of ``(text, absolute_url)`` for every ``<a>`` whose
    href points under ``/system/files/court-opinions/`` — covers both
    SCOTNJ-issued opinions (decided rows; link wraps the h5 caption)
    and the cross-referenced SCAD ``Read Appellate Opinion`` link.
    Excludes modal-body brief links, which live under ``.modal``.
    """
    anchors = row.query_xpath(
        ".//div[contains(@class, 'col-lg-9')]"
        "//a[contains(@href, '/system/files/court-opinions/')]"
        "[not(ancestor::div[contains(@class, 'modal')])]",
        "opinion links",
        min_count=0,
    )
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for a in anchors:
        url = _abs(a.get_attribute("href"))
        if not url or url in seen:
            continue
        seen.add(url)
        out.append((_normalise(a.text_content()) or "Opinion", url))
    return out


def _appellate_docket_id_from_opinions(
    opinions: list[tuple[str, str]],
) -> str | None:
    """Pull an originating SCAD docket id (e.g. ``A-1602-24``) from a
    ``Read Appellate Opinion A-1602-24`` link's text. Returns ``None``
    when no matching link is present (decided / SCOTNJ-only rows).
    """
    for text, _ in opinions:
        if "appellate opinion" not in text.lower():
            continue
        m = re.search(r"A-?\d{1,4}-\d{2,4}", text)
        if m:
            return m.group(0)
    return None


def _appellate_opinion_url(
    opinions: list[tuple[str, str]],
) -> str | None:
    """Return the URL of the cross-referenced SCAD appellate opinion,
    if the row has a ``Read Appellate Opinion …`` link.
    """
    for text, url in opinions:
        if "appellate opinion" in text.lower():
            return url
    return None


def _row_oa_media(row: PageElement) -> list[tuple[str, str, str]]:
    """Extract oral-argument media (video / audio) URLs for the row.

    SCOTNJ rows whose oral argument has been recorded include a
    ``<a>Oral Argument Video for A-NN-YY</a>`` button that opens a
    Bootstrap modal containing a ``<video><source src="...mp4">`` and a
    sibling ``<a href="...mp3">`` audio link. Both media URLs live on
    ``library.njcourts.gov`` and are returned here as
    ``(description, url, expected_type)`` tuples for archiving.
    """
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    sources = row.query_xpath(
        ".//source[contains(@src, 'library.njcourts.gov')]",
        "video sources",
        min_count=0,
    )
    for s in sources:
        url = s.get_attribute("src") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(("Oral Argument Video", url, "mp4"))
    audio = row.query_xpath(
        ".//a[contains(@href, 'library.njcourts.gov') and contains(@href, '.mp3')]",
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


def _row_events(row: PageElement) -> list[NJDocketEntry]:
    """Parse the right-hand event list into ``NJDocketEntry`` rows.

    SCOTNJ rows format each event as a ``<li>Event : Date</li>``.
    SCAD-argued rows format the only event as a label outside the
    ``<li>`` (``Argued:`` followed by an ``<li>April 30, 2026</li>``).
    Both shapes are handled by joining all text under ``col-lg-3`` and
    splitting on the colon.
    """
    block = row.query_xpath(
        ".//div[contains(@class, 'col-lg-3')]", "events block", min_count=0
    )
    if not block:
        return []

    entries: list[NJDocketEntry] = []
    # Strategy 1 (SCOTNJ): each <li> has its own "Event : Date".
    items = block[0].query_xpath(".//li", "li", min_count=0)
    seen_lines: set[str] = set()
    for li in items:
        line = _normalise(li.text_content())
        if not line or line in seen_lines:
            continue
        seen_lines.add(line)
        m = _EVENT_LINE_RE.match(line)
        if m:
            name = _normalise(m.group("name"))
            rest = _normalise(m.group("rest"))
            entries.append(
                NJDocketEntry(
                    description=name,
                    date_filed=_parse_date(rest),
                    notes=rest if not _parse_date(rest) else None,
                )
            )
    if entries:
        return entries

    # Strategy 2 (SCAD-argued): plain "Argued:" label outside the <li>.
    full = _normalise(block[0].text_content())
    m = _EVENT_LINE_RE.match(full)
    if m:
        name = _normalise(m.group("name"))
        rest = _normalise(m.group("rest"))
        entries.append(
            NJDocketEntry(
                description=name,
                date_filed=_parse_date(rest),
                notes=rest if not _parse_date(rest) else None,
            )
        )
    return entries


def _row_briefs(
    row: PageElement,
) -> tuple[list[tuple[str, str]], str | None]:
    """Return ``(briefs, missing_reason)`` for a listing row.

    ``briefs`` is a list of ``(description, absolute_url)`` tuples.
    ``missing_reason`` is set to ``"Briefs are sealed"`` when the
    Bootstrap modal title contains that phrase — even if the modal
    body still lists a few public order PDFs.
    """
    modals = row.query_xpath(
        ".//div[contains(@class, 'modal') and @id]", "modal", min_count=0
    )
    if not modals:
        return [], None
    modal = modals[0]

    title_nodes = modal.query_xpath(
        ".//*[@id='modal-title']", "title", min_count=0
    )
    title_text = (
        _normalise(title_nodes[0].text_content()) if title_nodes else ""
    )
    missing = "Briefs are sealed" if "sealed" in title_text.lower() else None

    briefs: list[tuple[str, str]] = []
    anchors = modal.query_xpath(
        ".//div[contains(@class, 'modal-body')]//a[@href]",
        "brief link",
        min_count=0,
    )
    for a in anchors:
        url = _abs(a.get_attribute("href"))
        if not url:
            continue
        briefs.append((_normalise(a.text_content()) or "Brief", url))
    return briefs, missing


def _next_page_url(page: PageElement, current_url: str) -> str | None:
    """Find the Drupal pager's "Next page" link, resolved against the
    current URL so that all filter params (``filter_by``, ``start``,
    ``end``, ``field_argued_dates_value``) are preserved.
    """
    links = page.query_xpath(
        "//nav[@aria-label='pagination-heading']//a[@title='Go to next page']",
        "next page",
        min_count=0,
    )
    if not links:
        return None
    return urljoin(current_url, links[0].get_attribute("href") or "")


# ─── Scraper ─────────────────────────────────────────────────────────


class NJCourtsScraper(BaseScraper[NJDocket | NJDocument]):
    """Scraper for the New Jersey Judiciary's public appellate listings.

    Three entry points cover the three source pages described in
    ``DESIGN.md``. SCOTNJ filters by ``Posted`` event date so that the
    ``DateRange`` parameter has a clear, stable meaning across runs;
    SCAD-argued filters on the only date column the page exposes
    (``field_argued_dates_value`` — the argument date); and the
    SCAD argument-schedule snapshot has no date filter at all and runs
    as a dateless entry point.
    """

    court_ids: ClassVar[set[str]] = set(COURT_IDS.keys())
    court_url: ClassVar[str] = BASE_URL
    data_types: ClassVar[set[str]] = {"dockets"}
    status: ClassVar[ScraperStatus] = ScraperStatus.IN_DEVELOPMENT
    version: ClassVar[str] = "2026-05-04"
    requires_auth: ClassVar[bool] = False
    rate_limits: ClassVar[list[Rate] | None] = [Rate(1, Duration.SECOND)]

    # =========================================================================
    # Entry points
    # =========================================================================

    @entry(NJDocket)
    def get_scotnj_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """SCOTNJ dockets posted in ``date_range`` (cert/leave granted etc.)."""
        url = (
            SCOTNJ_LISTING_URL
            + "?"
            + urlencode(
                {
                    "filter_by": "Posted",
                    "start": date_range.start.isoformat(),
                    "end": date_range.end.isoformat(),
                }
            )
        )
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=url),
            continuation=self.parse_scotnj_listing,
            accumulated_data={"court_id": "nj", "source_url": url},
            deduplication_key=SkipDeduplicationCheck(),
        )

    @entry(NJDocket)
    def get_scad_argued_dockets_by_date(
        self, date_range: DateRange
    ) -> Generator[Request, None, None]:
        """SCAD cases argued during ``date_range``."""
        url = (
            SCAD_ARGUED_LISTING_URL
            + "?"
            + urlencode(
                {
                    "field_argued_dates_value[min]": date_range.start.isoformat(),
                    "field_argued_dates_value[max]": date_range.end.isoformat(),
                }
            )
        )
        yield Request(
            request=HTTPRequestParams(method=HttpMethod.GET, url=url),
            continuation=self.parse_scad_argued_listing,
            accumulated_data={
                "court_id": "njsuperctappdiv",
                "source_url": url,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    @entry(NJDocket)
    def get_scad_argument_schedule(self) -> Generator[Request, None, None]:
        """Upcoming SCAD oral arguments (snapshot, no date filter)."""
        yield Request(
            request=HTTPRequestParams(
                method=HttpMethod.GET, url=SCAD_ARGUMENT_SCHEDULE_URL
            ),
            continuation=self.parse_argument_schedule,
            accumulated_data={
                "court_id": "njsuperctappdiv",
                "source_url": SCAD_ARGUMENT_SCHEDULE_URL,
            },
            deduplication_key=SkipDeduplicationCheck(),
        )

    # =========================================================================
    # Steps — paginated listings (SCOTNJ + SCAD-argued)
    # =========================================================================

    @step()
    def parse_scotnj_listing(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NJDocket | NJDocument], None, None]:
        """Parse one page of the SCOTNJ ``/courts/supreme/appeals`` listing."""
        yield from self._parse_listing_page(
            page=page,
            response=response,
            accumulated_data=accumulated_data,
            continuation=self.parse_scotnj_listing,
            include_question=True,
        )

    @step()
    def parse_scad_argued_listing(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NJDocket | NJDocument], None, None]:
        """Parse one page of the SCAD ``briefs-from-argued-cases`` listing."""
        yield from self._parse_listing_page(
            page=page,
            response=response,
            accumulated_data=accumulated_data,
            continuation=self.parse_scad_argued_listing,
            include_question=False,
        )

    def _parse_listing_page(
        self,
        *,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
        continuation,
        include_question: bool,
    ) -> Generator[ScraperYield[NJDocket | NJDocument], None, None]:
        court_id: str = accumulated_data["court_id"]
        rows = page.query_xpath("//table//tr[td]", "listing rows", min_count=0)
        for row in rows:
            docket_id = _row_docket_id(row)
            caption = _row_caption(row)
            if not docket_id or not caption:
                continue

            # CMS id lives in the trailing parenthetical of the SCOTNJ caption.
            _h5_text = _row_h5_text(row)
            _, cms_id = _parse_caption_block(_h5_text)

            entries = _row_events(row)
            briefs, missing_reason = _row_briefs(row)

            # date_filed: earliest dated event on the row.
            dated = [e.date_filed for e in entries if e.date_filed]
            date_filed = min(dated) if dated else None

            # argument_date: the ``Argued`` event if there is one.
            argument_date = next(
                (
                    e.date_filed
                    for e in entries
                    if e.description.lower().startswith("argued")
                    and e.date_filed
                ),
                None,
            )

            opinions = _row_opinion_links(row) if include_question else []
            appellate_docket_id = _appellate_docket_id_from_opinions(opinions)
            appellate_opinion_url = _appellate_opinion_url(opinions)
            question = _row_question(row) if include_question else None
            oa_media = _row_oa_media(row) if include_question else []

            # Aggregate every downloadable artefact for the docket.
            # SCOTNJ rows can carry briefs (PDF), opinion PDFs, plus
            # oral-argument MP4/MP3 from the Supreme Court library. All
            # are emitted as NJDocument and archived.
            all_links: list[tuple[str, str, str]] = (
                [(desc, url, "pdf") for desc, url in briefs]
                + [(desc, url, "pdf") for desc, url in opinions]
                + list(oa_media)
            )

            documents = [
                NJDocument(
                    docket_id=docket_id,
                    court_id=court_id,
                    document_url=url,
                    description=desc,
                )
                for desc, url, _kind in all_links
            ]

            docket = NJDocket(
                docket_id=docket_id,
                court_id=court_id,
                case_name=caption,
                date_filed=date_filed,
                cms_id=cms_id,
                question_presented=question,
                appellate_docket_id=appellate_docket_id,
                appellate_opinion_url=appellate_opinion_url,
                argument_date=argument_date,
                missing_entries_reason=missing_reason,
                entries=entries,
                documents=documents,
                source_url=accumulated_data.get("source_url"),
            )
            yield ParsedData(data=docket)

            for desc, url, kind in all_links:
                accept = (
                    "application/pdf"
                    if kind == "pdf"
                    else f"audio/{kind}"
                    if kind == "mp3"
                    else f"video/{kind}"
                )
                yield Request(
                    archive=True,
                    request=HTTPRequestParams(
                        method=HttpMethod.GET,
                        url=url,
                        headers={"Accept": accept},
                    ),
                    continuation=self.handle_document_download,
                    expected_type=kind,
                    accumulated_data={
                        "docket_id": docket_id,
                        "court_id": court_id,
                        "description": desc,
                        "document_url": url,
                    },
                )

        next_url = _next_page_url(page, response.url or "")
        if next_url:
            yield Request(
                request=HTTPRequestParams(method=HttpMethod.GET, url=next_url),
                continuation=continuation,
                accumulated_data={
                    **accumulated_data,
                    "source_url": next_url,
                },
                deduplication_key=SkipDeduplicationCheck(),
            )

    # =========================================================================
    # Step — argument schedule snapshot (SCAD pending OAs)
    # =========================================================================

    @step()
    def parse_argument_schedule(
        self,
        page: PageElement,
        response: Response,
        accumulated_data: dict,
    ) -> Generator[ScraperYield[NJDocket | NJDocument], None, None]:
        """Parse the SCAD argument-schedule single-page snapshot.

        Page structure: ``<div class="view-grouping">`` per date, each
        with a ``view-grouping-header`` ``<h4>`` (date) and a
        ``view-grouping-content`` containing alternating
        ``<span class="secondary-header">`` (location) and
        ``<ul class="list-group">`` of cases.
        """
        court_id: str = accumulated_data["court_id"]
        groupings = page.query_xpath(
            "//div[contains(@class, 'view-grouping')]",
            "argument-schedule groupings",
            min_count=0,
        )
        for grouping in groupings:
            heading = grouping.query_xpath(
                ".//h4[contains(@class, 'header-date')]",
                "date heading",
                min_count=0,
            )
            if not heading:
                continue
            argument_date = _parse_date(heading[0].text_content())
            if not argument_date:
                continue

            content = grouping.query_xpath(
                ".//div[contains(@class, 'view-grouping-content')]",
                "content",
                min_count=0,
            )
            if not content:
                continue

            current_location: str | None = None
            children = content[0].query_xpath(
                "./*", "content children", min_count=0
            )
            for child in children:
                tag = (child.tag_name() or "").lower()
                cls = child.get_attribute("class") or ""
                if "secondary-header" in cls:
                    current_location = _normalise(child.text_content()) or None
                    continue
                if tag == "ul":
                    cases = child.query_xpath("./li", "case rows", min_count=0)
                    for case_li in cases:
                        yield from self._yield_argument_schedule_case(
                            case_li=case_li,
                            court_id=court_id,
                            argument_date=argument_date,
                            location=current_location,
                            source_url=accumulated_data.get("source_url"),
                        )

    def _yield_argument_schedule_case(
        self,
        *,
        case_li: PageElement,
        court_id: str,
        argument_date: date,
        location: str | None,
        source_url: str | None,
    ) -> Generator[ScraperYield[NJDocket | NJDocument], None, None]:
        bold = case_li.query_xpath(
            ".//span[contains(@class, 'fw-bold')]",
            "docket id span",
            min_count=0,
        )
        if not bold:
            return
        docket_id = _normalise(bold[0].text_content())
        if not docket_id:
            return

        h6 = case_li.query_xpath(
            ".//div[contains(@class, 'h6')]", "h6", min_count=0
        )
        if not h6:
            return
        full_text = _normalise(h6[0].text_content())
        caption_raw = full_text
        if caption_raw.startswith(docket_id):
            caption_raw = caption_raw[len(docket_id) :].strip()

        impounded_match = _IMPOUNDED_RE.search(caption_raw)
        missing_reason: str | None = None
        if impounded_match:
            missing_reason = "RECORD IMPOUNDED"
            caption = caption_raw[: impounded_match.start()].rstrip()
        else:
            caption = caption_raw

        anchors = case_li.query_xpath(".//a[@href]", "case links", min_count=0)
        briefs: list[tuple[str, str]] = []
        for a in anchors:
            url = _abs(a.get_attribute("href"))
            if not url:
                continue
            briefs.append((_normalise(a.text_content()) or "Briefs", url))

        documents = [
            NJDocument(
                docket_id=docket_id,
                court_id=court_id,
                document_url=url,
                description=desc,
            )
            for desc, url in briefs
        ]

        entries = [
            NJDocketEntry(
                description="Oral Argument",
                date_filed=argument_date,
                notes=location,
            )
        ]

        docket = NJDocket(
            docket_id=docket_id,
            court_id=court_id,
            case_name=caption or docket_id,
            date_filed=argument_date,
            argument_date=argument_date,
            argument_location=location,
            missing_entries_reason=missing_reason,
            entries=entries,
            documents=documents,
            source_url=source_url,
        )
        yield ParsedData(data=docket)

        for desc, url in briefs:
            yield Request(
                archive=True,
                request=HTTPRequestParams(
                    method=HttpMethod.GET,
                    url=url,
                    headers={"Accept": "application/pdf"},
                ),
                continuation=self.handle_document_download,
                expected_type="pdf",
                accumulated_data={
                    "docket_id": docket_id,
                    "court_id": court_id,
                    "description": desc,
                    "document_url": url,
                },
            )

    # =========================================================================
    # Step — document archival
    # =========================================================================

    @step()
    def handle_document_download(
        self,
        accumulated_data: dict,
        local_filepath: str | None = None,
    ) -> Generator[ScraperYield[NJDocument], None, None]:
        """Emit an ``NJDocument`` for an archived PDF."""
        yield ParsedData(
            data=NJDocument(
                docket_id=accumulated_data["docket_id"],
                court_id=accumulated_data["court_id"],
                document_url=accumulated_data["document_url"],
                description=accumulated_data.get("description"),
                local_path=local_filepath,
            )
        )
