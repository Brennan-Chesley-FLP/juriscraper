"""Parser for an OSCN ``GetCaseInformation.aspx`` case page.

One case page renders the full register of actions in plain HTML tables.
:class:`CaseDetailParser` extracts every section into a single
:class:`OkDocket`. The same section parsers are reused by the scraper to
build the nested :class:`OkLowerCourtCase` from a trial-court page.

The page does not carry the numeric source URL or the originating entry
point — the step stamps ``source_url`` / ``source_entry_point`` onto the
returned ``raw_data`` before emitting (see ``scraper.py``).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.oklahoma.oscn_net.models import (
    TRACK_CASE_URL_TEMPLATE,
    OkAttorney,
    OkDocket,
    OkDocketEntry,
    OkEvent,
    OkLowerCourtCount,
    OkParty,
)

from ._common import (
    cell_lines,
    extract_json_style,
    normalize_ws,
    or_none,
    parse_date,
    row_color,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


# Map heading prefix -> CourtListener court_id.
COURT_HEADING_MAP: tuple[tuple[str, str], ...] = (
    ("COURT OF CIVIL APPEALS", "oklacivapp"),
    ("COURT OF CRIMINAL APPEALS", "oklacrimapp"),
    ("COURT ON THE JUDICIARY", "oklacoj"),
    ("JUDICIAL ETHICS ADVISORY PANEL", "oklajeap"),
    ("SUPREME COURT", "okla"),
)

# Oklahoma counties that OSCN exposes as `db={county}` for trial-court
# dockets. Used to detect when a heading suffix is a county hint we can
# follow rather than a COCA division label or unrelated text.
OK_COUNTIES: frozenset[str] = frozenset(
    c.lower()
    for c in (
        "Adair",
        "Alfalfa",
        "Atoka",
        "Beaver",
        "Beckham",
        "Blaine",
        "Bryan",
        "Caddo",
        "Canadian",
        "Carter",
        "Cherokee",
        "Choctaw",
        "Cimarron",
        "Cleveland",
        "Coal",
        "Comanche",
        "Cotton",
        "Craig",
        "Creek",
        "Custer",
        "Delaware",
        "Dewey",
        "Ellis",
        "Garfield",
        "Garvin",
        "Grady",
        "Grant",
        "Greer",
        "Harmon",
        "Harper",
        "Haskell",
        "Hughes",
        "Jackson",
        "Jefferson",
        "Johnston",
        "Kay",
        "Kingfisher",
        "Kiowa",
        "Latimer",
        "LeFlore",
        "Lincoln",
        "Logan",
        "Love",
        "Major",
        "Marshall",
        "Mayes",
        "McClain",
        "McCurtain",
        "McIntosh",
        "Murray",
        "Muskogee",
        "Noble",
        "Nowata",
        "Okfuskee",
        "Oklahoma",
        "Okmulgee",
        "Osage",
        "Ottawa",
        "Pawnee",
        "Payne",
        "Pittsburg",
        "Pontotoc",
        "Pottawatomie",
        "Pushmataha",
        "Roger Mills",
        "Rogers",
        "Seminole",
        "Sequoyah",
        "Stephens",
        "Texas",
        "Tillman",
        "Tulsa",
        "Wagoner",
        "Washington",
        "Washita",
        "Woods",
        "Woodward",
    )
)


def court_id_from_heading(heading: str) -> str:
    """Map a case caption heading like ``IN THE SUPREME COURT OF THE
    STATE OF OKLAHOMA`` to a CourtListener court id.

    Falls back to the Supreme Court — the most common case when the
    heading is unusual.
    """
    upper = heading.upper()
    for prefix, court_id in COURT_HEADING_MAP:
        if prefix in upper:
            return court_id
    return "okla"


def county_hint_from_heading(heading: str) -> str | None:
    """Return a likely county name (lowercased) appended to the heading,
    or ``None`` if the trailing token isn't a known county.

    The COCA case caption appends the originating-county / division token
    after ``OKLAHOMA``, e.g. ``... OF THE STATE OF OKLAHOMA Tulsa``. We use
    that as the ``db=`` parameter for trial-court lookups when it matches a
    known Oklahoma county.
    """
    m = re.search(r"OF\s+OKLAHOMA\s+(.+?)\s*$", heading, re.IGNORECASE)
    if not m:
        return None
    suffix = m.group(1).strip()
    if not suffix:
        return None
    candidates = [suffix, suffix.rsplit(None, 1)[-1]]
    for candidate in candidates:
        if candidate.lower() in OK_COUNTIES:
            return candidate.lower()
    return None


class CaseDetailParser(JKentParser[OkDocket]):
    """Parse an OSCN appellate case-detail page into one ``OkDocket``.

    Returns a single-element list. ``source_url`` / ``source_entry_point``
    are stamped by the calling step. The lower-court reference (when a
    county hint is present) is followed by the scraper, which reuses this
    parser's section methods to populate the nested ``OkLowerCourtCase``.
    """

    def __init__(self, base_url: str = "") -> None:
        """``base_url`` resolves relative document URLs in the docket rows.

        Defaults to ``""`` so the standard ``JKentParser.from_string`` /
        ``from_file`` constructors work for offline tests; the scraper
        step constructs ``CaseDetailParser(response.url)`` for live runs.
        """
        super().__init__()
        self._base_url = base_url

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[OkDocket]]:
        json_style = self.read_json_style(page)
        canonical = json_style.get("casenumber") or ""
        cmid = json_style.get("cmid") or None
        court_token = (json_style.get("court") or "APPELLATE").upper()

        heading = self.parse_heading(page)
        court_id = court_id_from_heading(heading)

        caption = self.parse_caption(page)
        docket_number = canonical or caption.get("url_case_number") or ""

        track_case_url = None
        if docket_number:
            track_case_url = TRACK_CASE_URL_TEMPLATE.format(
                court=court_token, docket_number=docket_number
            )

        docket = OkDocket.raw(
            docket_number=docket_number,
            court=court_id,
            date_filed=caption.get("date_filed"),
            case_name=caption.get("case_name") or docket_number,
            case_classification=caption.get("case_classification"),
            cmid=cmid,
            court_name=heading or None,
            parties=self.parse_parties(page),
            attorneys=self.parse_attorneys(page),
            entries=self.parse_docket_entries(page),
            events=self.parse_events(page),
            lower_court_counts=self.parse_lower_court_counts(page),
            lower_court_case=None,
            opinion_url=caption.get("opinion_url"),
            opinion_citation=caption.get("opinion_citation"),
            track_case_url=track_case_url,
        )
        return [docket]

    @staticmethod
    def read_json_style(page: PageElement) -> dict:
        """Read the embedded ``<script id="json_style">`` JSON block.

        Exposes the canonical case number (which can differ from the URL
        ``number=`` parameter for prefixed case types), ``cmid``, and the
        ``court`` token used to build the Track-Case URL. Returns an empty
        dict when the block is missing or unparseable.
        """
        nodes = page.query(
            XPath("//script[@id='json_style']"),
            "json_style block",
            min_count=0,
            max_count=1,
        )
        if not nodes:
            return {}
        return extract_json_style(nodes[0].text_content() or "")

    # =====================================================================
    # Heading + court detection
    # =====================================================================

    def parse_heading(self, page: PageElement) -> str:
        """Return the ``IN THE ... COURT OF OKLAHOMA`` caption heading."""
        heading_nodes = page.query(
            XPath(
                "//h2[contains(translate(., 'abcdefghijklmnopqrstuvwxyz',"
                " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'STATE OF OKLAHOMA')]"
            ),
            "court heading",
            min_count=0,
            max_count=1,
        )
        return (
            normalize_ws(heading_nodes[0].text_content())
            if heading_nodes
            else ""
        )

    def parse_caption(self, page: PageElement) -> dict:
        """Parse the case caption row: case name, classification, filed
        date, and the opinion link/citation."""
        caption_cells = page.query(
            XPath(
                "(//h2[contains(., 'OKLAHOMA')]/following-sibling::table[1])"
                "//tr[1]/td"
            ),
            "case caption row cells",
            min_count=0,
            max_count=2,
        )
        out: dict = {}
        if caption_cells:
            out["case_name"] = normalize_ws(caption_cells[0].text_content())
        if len(caption_cells) >= 2:
            right_cell = caption_cells[1]
            right_text = right_cell.text_content()
            cls_match = re.search(r"\(([^)]+)\)", right_text)
            if cls_match:
                out["case_classification"] = cls_match.group(1).strip()
            filed_match = re.search(
                r"Filed:\s*(\d{1,2}/\d{1,2}/\d{4})", right_text
            )
            if filed_match:
                out["date_filed"] = parse_date(filed_match.group(1))
            opinion_anchors = right_cell.query(
                XPath(".//a[contains(@href, 'deliverdocument')]"),
                "opinion link in caption",
                min_count=0,
                max_count=1,
            )
            if opinion_anchors:
                out["opinion_url"] = opinion_anchors[0].get_attribute("href")
                out["opinion_citation"] = normalize_ws(
                    opinion_anchors[0].text_content()
                )
        return out

    # =====================================================================
    # Trial-court caption (lower-court page)
    # =====================================================================

    def parse_trial_caption(self, page: PageElement) -> dict:
        """Parse the trial-court page caption (case name + filed date).

        Trial-court pages don't repeat the ``IN THE ... COURT OF
        OKLAHOMA`` heading the appellate pages use, so the caption table
        is located relative to the first ``Parties`` heading instead.
        """
        caption_cells = page.query(
            XPath(
                "(//h2[normalize-space()='Parties']/preceding::table)[last()]"
                "//tr[1]/td"
            ),
            "trial caption row cells",
            min_count=0,
            max_count=2,
        )
        out: dict = {}
        if caption_cells:
            out["case_name"] = normalize_ws(caption_cells[0].text_content())
        if len(caption_cells) >= 2:
            filed_match = re.search(
                r"Filed:\s*(\d{1,2}/\d{1,2}/\d{4})",
                caption_cells[1].text_content(),
            )
            if filed_match:
                out["date_filed"] = parse_date(filed_match.group(1))
        return out

    # =====================================================================
    # Parties
    # =====================================================================

    def parse_parties(self, page: PageElement) -> list[OkParty]:
        spans = page.query(
            XPath(
                "//h2[normalize-space()='Parties']/following-sibling::p[1]"
                "/span[contains(@class, 'parties_party')]"
            ),
            "party spans",
            min_count=0,
        )
        parties: list[OkParty] = []
        for span in spans:
            name_nodes = span.query(
                XPath(".//span[contains(@class, 'parties_partyname')]"),
                "party name span",
                min_count=0,
                max_count=1,
            )
            type_nodes = span.query(
                XPath(".//span[contains(@class, 'parties_type')]"),
                "party type span",
                min_count=0,
                max_count=1,
            )
            name = (
                normalize_ws(name_nodes[0].text_content())
                if name_nodes
                else normalize_ws(span.text_content())
            )
            role = (
                normalize_ws(type_nodes[0].text_content())
                if type_nodes
                else None
            )
            if name:
                parties.append(OkParty(name=name, role=role))
        return parties

    # =====================================================================
    # Attorneys
    # =====================================================================

    def parse_attorneys(self, page: PageElement) -> list[OkAttorney]:
        rows = page.query(
            XPath(
                "//h2[normalize-space()='Attorneys']"
                "/following-sibling::table[1]//tbody/tr"
            ),
            "attorney rows",
            min_count=0,
        )
        attorneys: list[OkAttorney] = []
        for row in rows:
            cells = row.query(XPath("./td"), "attorney row cells", min_count=0)
            if len(cells) < 2:
                continue
            attorney_lines = cell_lines(cells[0])
            represented_lines = cell_lines(cells[1])
            represented_list = [
                p
                for line in represented_lines
                for p in re.split(r",\s*", line)
                if p
            ]
            if not attorney_lines:
                continue
            name_line = attorney_lines[0]
            bar_match = re.search(r"\(Bar\s*#\s*(\d+)\)", name_line)
            bar_number = bar_match.group(1) if bar_match else None
            name = re.sub(r"\(Bar\s*#\s*\d+\)", "", name_line).strip()
            address = (
                "\n".join(attorney_lines[1:])
                if len(attorney_lines) > 1
                else None
            )
            attorneys.append(
                OkAttorney(
                    name=name,
                    bar_number=bar_number,
                    address=address,
                    represented_parties=represented_list,
                )
            )
        return attorneys

    # =====================================================================
    # Events
    # =====================================================================

    def parse_events(self, page: PageElement) -> list[OkEvent]:
        section_nodes = page.query(
            XPath(
                "//h2[contains(translate(., 'abcdefghijklmnopqrstuvwxyz',"
                " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'EVENTS')]"
                "/following-sibling::*[1]"
            ),
            "events section",
            min_count=0,
            max_count=1,
        )
        if not section_nodes:
            return []
        section = section_nodes[0]
        text = normalize_ws(section.text_content())
        if not text or text.lower() == "none":
            return []
        rows = section.query(XPath(".//tr"), "event rows", min_count=0)
        events: list[OkEvent] = []
        for row in rows:
            cells = row.query(XPath("./td"), "event cells", min_count=0)
            if not cells:
                continue
            cell_texts = [normalize_ws(c.text_content()) for c in cells]
            event_date = next(
                (parse_date(t) for t in cell_texts if parse_date(t)),
                None,
            )
            description = " | ".join(t for t in cell_texts if t)
            if description:
                events.append(
                    OkEvent(date_event=event_date, description=description)
                )
        if not events and text:
            events.append(OkEvent(date_event=None, description=text))
        return events

    # =====================================================================
    # Lower court counts
    # =====================================================================

    def parse_lower_court_counts(
        self, page: PageElement
    ) -> list[OkLowerCourtCount]:
        rows = page.query(
            XPath(
                "//h2[contains(., 'Lower Court')]"
                "/following-sibling::table[1]//tbody/tr"
            ),
            "lower court rows",
            min_count=0,
        )
        results: list[OkLowerCourtCount] = []
        for row in rows:
            cells = row.query(
                XPath("./td"), "lower court row cells", min_count=0
            )
            if not cells:
                continue
            values = [normalize_ws(c.text_content()) for c in cells]
            while len(values) < 7:
                values.append("")
            results.append(
                OkLowerCourtCount(
                    count=or_none(values[0]),
                    docket_number=or_none(values[1]),
                    statute=or_none(values[2]),
                    crime=or_none(values[3]),
                    sentence=or_none(values[4]),
                    judge=or_none(values[5]),
                    reporter=or_none(values[6]),
                )
            )
        return results

    def first_lower_court_number(
        self, counts: list[OkLowerCourtCount]
    ) -> str | None:
        """Return the first usable trial-court case number from the counts
        table, or ``None``."""
        for lc in counts:
            if lc.docket_number and lc.docket_number != "-":
                return lc.docket_number
        return None

    # =====================================================================
    # Docket entries
    # =====================================================================

    def parse_docket_entries(self, page: PageElement) -> list[OkDocketEntry]:
        base_url = self._base_url
        rows = page.query(
            XPath("//tr[contains(@class, 'docketRow')]"),
            "docket rows",
            min_count=0,
        )
        entries: list[OkDocketEntry] = []
        for row in rows:
            cells = row.query(XPath("./td"), "docket row cells", min_count=0)
            if len(cells) < 3:
                continue
            date_text = normalize_ws(cells[0].text_content())
            code_text = normalize_ws(cells[1].text_content())
            description_text = normalize_ws(cells[2].text_content())
            count_text = (
                normalize_ws(cells[3].text_content()) if len(cells) > 3 else ""
            )
            party_text = (
                normalize_ws(cells[4].text_content()) if len(cells) > 4 else ""
            )
            amount_text = (
                normalize_ws(cells[5].text_content()) if len(cells) > 5 else ""
            )

            # Strip [BRACKETS] from code if present — keep the inner token.
            code_match = re.match(r"^\[(.+)\]$", code_text)
            code = code_match.group(1) if code_match else code_text or None

            # Document attachments + ID
            doc_id = None
            tiff_url = None
            pdf_url = None
            doc_match = re.search(
                r"Document Available\s*\(#?(\d+)\)", description_text
            )
            if doc_match:
                doc_id = doc_match.group(1)
                description_text = description_text[
                    : doc_match.start()
                ].rstrip()
            anchors = cells[2].query(XPath(".//a"), "doc anchors", min_count=0)
            for a in anchors:
                href = a.get_attribute("href")
                if not href:
                    continue
                absolute = urljoin(base_url, href)
                label = (a.text_content() or "").strip().lower()
                if "fmt=tif" in href.lower() or label == "tiff":
                    tiff_url = absolute
                elif "fmt=pdf" in href.lower() or label == "pdf":
                    pdf_url = absolute

            # Row colour — read the row's inner HTML and find the first
            # <font color="..."> token.
            try:
                color = row_color(row.inner_html() or "")
            except Exception:
                color = None

            entries.append(
                OkDocketEntry(
                    date_filed=parse_date(date_text),
                    code=code,
                    description=description_text or None,
                    color=color,
                    count=count_text or None,
                    party=party_text or None,
                    amount=amount_text or None,
                    document_id=doc_id,
                    tiff_url=tiff_url,
                    pdf_url=pdf_url,
                )
            )
        return entries
