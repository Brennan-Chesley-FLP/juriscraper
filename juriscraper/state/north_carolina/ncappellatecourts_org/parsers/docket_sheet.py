"""Parser for an NC appellate docket sheet.

One ``dockets.php?…&pdf=1`` page renders a rich (HTML, despite the
``pdf`` param) register of actions. :class:`DocketSheetParser` extracts
every section into a single :class:`NCAppealsDocket`. The page does
*not* carry the visible docket number, the CL court id, the source URL,
or the originating entry point — the step stamps those onto the returned
``raw_data`` before emitting (see ``scraper.py``).

The Attorneys section and the register-of-actions free-text expansion
are *malformed* HTML (stray ``</strong></b>``, ``<br><hr>``-delimited
text that is not a real container), so they are parsed off the page's
markup string (``PageElement.inner_html()``) rather than by walking the
tree — ``text_content()`` collapses the ``<br>``/``<blockquote>`` markers
that carry their structure.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.north_carolina.ncappellatecourts_org.models import (
    NCAppealsAttorney,
    NCAppealsDocket,
    NCAppealsDocketEntry,
    NCAppealsLowerCourt,
    NCAppealsParty,
)

from ._common import _BR_RE, clean, parse_date, parse_yes_no, strip_tags

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


# A "docket entry" expansion below the Documents table looks like::
#
#     2 - M-SEAL  (Allowed) - 04-06-2026
#     Filed: 04-02-2026 @ 09:37:13
#     FOR: Defendant-Appellant Sings, Janice Elaine
#     BY   : Ms. Callie S. Thomas
#               OFFICE OF THE APPELLATE DEFENDER
#
# We pull the index/type/ruling/ruling-date from the header line and
# then ``Filed:`` / ``FOR:`` / ``BY:`` from the body lines. Document
# types may contain parentheses (e.g. ``RECORD RULE 9(D) COPIES …``), so
# the type is matched non-greedily. The ruling tail only fires when both
# the parenthesised verdict *and* the trailing date are present,
# anchoring at end of line.
_ENTRY_HEADER_RE = re.compile(
    r"^(?P<idx>\d+)\s*-\s*"
    r"(?P<type>[^\n]+?)"
    r"(?:\s+\((?P<ruling>[^)\n]+)\)\s*-\s*"
    r"(?P<rdate>\d{2}-\d{2}-\d{4}))?\s*$"
)


class DocketSheetParser(JKentParser[NCAppealsDocket]):
    """Parse one docket-sheet page into a single ``NCAppealsDocket``.

    The returned ``raw_data`` carries the page-derived fields only;
    ``docket_number``, ``court``, ``source_url``, and
    ``source_entry_point`` are stamped by the calling step.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[NCAppealsDocket]]:
        raw_html = page.inner_html()

        # SC dockets show only ``Docket Date``; COA shows both, with the
        # same value. Fall back to ``Docket Date`` when the more specific
        # label isn't on the page.
        date_filed = parse_date(
            self._label_value(page, "File Date")
        ) or parse_date(self._label_value(page, "Docket Date"))

        docket = NCAppealsDocket.raw(
            # docket_number / court / source_url / source_entry_point are
            # stamped by the step; case_name may be overridden there with
            # the listing hint when the long title is absent.
            case_name=self._extract_long_title(page),
            date_filed=date_filed,
            case_type=self._label_value(page, "Case Type"),
            case_closed=parse_yes_no(self._label_value(page, "Case Closed")),
            date_closed=parse_date(self._label_value(page, "Case Close Date")),
            mediation=parse_yes_no(self._label_value(page, "Mediation")),
            docket_date=parse_date(self._label_value(page, "Docket Date")),
            file_time=self._label_value(page, "File Time"),
            acquire_date=parse_date(self._label_value(page, "Acquire Date")),
            bond_collection=parse_yes_no(
                self._label_value(page, "Bond Collection")
            ),
            docket_fee=parse_yes_no(self._label_value(page, "Docket Fee")),
            pauper=parse_yes_no(self._label_value(page, "Pauper")),
            print_deposit=parse_yes_no(
                self._label_value(page, "Print Deposit")
            ),
            state_appeals=parse_yes_no(
                self._label_value(page, "State Appeals")
            ),
            as_of_date=parse_date(self._label_value(page, "As of")),
            venue=self._label_value(page, "Venue"),
            heard_in=self._label_value(page, "Heard In"),
            previous_venue=self._label_value(page, "Previous Venue"),
            to_sc=self._label_value(page, "To SC"),
            from_sc=self._label_value(page, "From SC"),
            lower_courts=self._extract_lower_courts(page),
            parties=self._extract_parties_with_attorneys(page, raw_html),
            entries=self._extract_docket_entries(page, raw_html),
        )
        return [docket]

    # =====================================================================
    # Header label/value lookup
    # =====================================================================

    @staticmethod
    def _label_value(page: PageElement, label: str) -> str | None:
        """Return the value cell after a ``<td><b|strong>{label}:</…></td>``.

        The docket sheet alternates label / value cells inside ``<table>``
        rows. The label might be wrapped in ``<b>`` or in ``<strong>``,
        so we match ``*`` (any element) whose normalised text is exactly
        ``{label}:``.
        """
        xpath = (
            f"//td[*[normalize-space(text())='{label}:']]"
            "/following-sibling::td[1]"
        )
        cells = page.query(
            XPath(xpath), f"label:{label}", min_count=0, max_count=1
        )
        if not cells:
            return None
        return clean(cells[0].text_content())

    @staticmethod
    def _extract_long_title(page: PageElement) -> str | None:
        """Pull the case caption from ``<div class='long_title'>``."""
        parts = page.query_strings(
            XPath("//div[contains(@class, 'long_title')]//text()"),
            "long title",
            min_count=0,
        )
        if not parts:
            return None
        joined = " ".join(p.strip() for p in parts if p.strip())
        return clean(joined)

    # =====================================================================
    # Lower court(s)
    # =====================================================================

    def _extract_lower_courts(
        self, page: PageElement
    ) -> list[NCAppealsLowerCourt]:
        """Pull the Lower Court Number(s) block(s).

        The block uses the same ``<td><b>{label}:</b></td><td>{value}</td>``
        pattern. Most cases have exactly one such block; a few have
        several (one per origin court).
        """
        out: list[NCAppealsLowerCourt] = []
        # Each block lives inside a table that follows a
        # ``<div class='section_tab'>Lower Court Number(s)</div>``.
        tables = page.query(
            XPath(
                "//div[contains(@class, 'section_tab')"
                " and contains(., 'Lower Court Number')]"
                "/following-sibling::table[1]"
            ),
            "lower court tables",
            min_count=0,
            max_count=1,
        )
        for table in tables:
            # The fields are repeated inside the table; collect them in
            # order and split into per-block records by every appearance
            # of "Location:".
            rows = table.query(
                XPath(".//tr[td]"), "lower-court rows", min_count=0
            )
            current: dict[str, str] = {}
            for row in rows:
                cell_elements = row.query(
                    XPath("./td"), "lower-court cells", min_count=0
                )
                cells = [clean(c.text_content()) or "" for c in cell_elements]
                if len(cells) < 2:
                    continue
                label = (cells[0] or "").rstrip(":")
                value = cells[1]
                if label.lower() == "location":
                    if current:
                        out.append(self._build_lower_court(current))
                    current = {"location": value or ""}
                elif label.lower() == "judge":
                    current["judge"] = value or ""
                elif label.lower() in {"case", "case #"}:
                    current["docket_number"] = value or ""
            if current:
                out.append(self._build_lower_court(current))
        return out

    @staticmethod
    def _build_lower_court(d: dict[str, str]) -> NCAppealsLowerCourt:
        return NCAppealsLowerCourt(
            location=d.get("location") or None,
            judge=d.get("judge") or None,
            docket_number=d.get("docket_number") or None,
        )

    # =====================================================================
    # Parties & attorneys
    # =====================================================================

    def _extract_parties_with_attorneys(
        self, page: PageElement, raw_html: str = ""
    ) -> list[NCAppealsParty]:
        """Pull the Parties table and zip it with the Attorneys section.

        Parties are read from the structured table; their attorneys are
        parsed best-effort from the free-text Attorneys section. The
        section is malformed HTML (stray ``</strong></b>`` after the
        first party), so we operate on the page-markup slice between the
        ``<div … >Attorneys</div>`` heading and the closing ``</main>``
        rather than walking the lxml tree.
        """
        party_names_elems = page.query(
            XPath("//td[@headers='party_name_id']"),
            "party names",
            min_count=0,
        )
        party_roles_elems = page.query(
            XPath("//td[@headers='role_id']"),
            "party roles",
            min_count=0,
        )
        raw_pairs: list[tuple[str, str]] = []
        for name_el, role_el in zip(party_names_elems, party_roles_elems):
            name = clean(name_el.text_content())
            role = clean(role_el.text_content())
            if name:
                raw_pairs.append((name, role or ""))

        attorneys_by_party = self._extract_attorney_blocks_from_html(raw_html)

        parties: list[NCAppealsParty] = []
        for name, role in raw_pairs:
            parties.append(
                NCAppealsParty(
                    name=name,
                    role=role or None,
                    attorneys=attorneys_by_party.get(name, []),
                )
            )
        return parties

    def _extract_attorney_blocks_from_html(
        self, raw_html: str
    ) -> dict[str, list[NCAppealsAttorney]]:
        """Best-effort attorney parser keyed on the trailing party name.

        Slices the markup between the ``Attorneys`` section heading and
        the closing ``</main>``, then splits on ``Attorney for {role} -
        {party}`` markers. The shared firm / address / phone block at the
        end of each party's section is copied onto every attorney in that
        block.
        """
        out: dict[str, list[NCAppealsAttorney]] = {}
        if not raw_html:
            return out
        section_match = re.search(
            r"<div[^>]*class='section_tab'[^>]*>\s*Attorneys\s*</div>"
            r"(.*?)</main>",
            raw_html,
            re.DOTALL | re.IGNORECASE,
        )
        if not section_match:
            return out
        section_text = section_match.group(1)
        # Split on the per-party heading. The site sometimes typos the
        # closing tag (``</stong>`` instead of ``</strong>``); we accept
        # either.
        party_chunks = re.split(
            r"<strong>\s*Attorney for ([^<]+)</(?:strong|stong)>",
            section_text,
        )
        # re.split with a capture group emits:
        # [pre, group1, body1, group2, body2, ...]
        for i in range(1, len(party_chunks), 2):
            heading = party_chunks[i]
            body_html = (
                party_chunks[i + 1] if i + 1 < len(party_chunks) else ""
            )
            # Heading shape: ``{role} - {party_name}``
            _, _, party_name = heading.partition(" - ")
            party_name = clean(party_name) or clean(heading) or ""
            if not party_name:
                continue
            body_text = strip_tags(_BR_RE.sub("\n", body_html))
            lines = [
                line.strip() for line in body_text.split("\n") if line.strip()
            ]
            attorneys = self._parse_attorney_lines(lines)
            if attorneys:
                out.setdefault(party_name, []).extend(attorneys)
        return out

    @staticmethod
    def _parse_attorney_lines(lines: list[str]) -> list[NCAppealsAttorney]:
        """Walk one party's attorney block.

        Heuristics: any line that starts with an honorific (``Mr.``,
        ``Ms.``, ``Mrs.``, ``Mx.``, ``Dr.``, ``Hon.``) starts a new
        attorney; the next line is the title; subsequent lines are the
        shared firm / address / phone block applied retroactively to all
        attorneys parsed from this block.
        """
        HONORIFICS = ("Mr.", "Ms.", "Mrs.", "Mx.", "Dr.", "Hon.")
        attorneys: list[NCAppealsAttorney] = []
        shared_lines: list[str] = []
        pending: NCAppealsAttorney | None = None
        expecting_title = False

        def _commit_pending() -> None:
            nonlocal pending, expecting_title
            if pending is not None:
                attorneys.append(pending)
                pending = None
                expecting_title = False

        for raw in lines:
            line = raw.strip()
            # Cloudflare's email placeholder appears as ``[email protected]``
            # after &nbsp; / &#160; have been collapsed to spaces; skip it.
            if not line or line.lower() == "[email protected]":
                continue
            if line.startswith(HONORIFICS):
                _commit_pending()
                name = line
                role = None
                if "[" in line and "]" in line:
                    name, _, bracket = line.partition("[")
                    role = bracket.rstrip("]").strip() or None
                pending = NCAppealsAttorney(
                    name=clean(name) or line, role=role
                )
                expecting_title = True
                continue
            if pending is not None and expecting_title:
                pending.title = line
                expecting_title = False
                continue
            # Anything after the title belongs to the shared firm block.
            shared_lines.append(line)

        _commit_pending()

        # Distribute the shared firm/address/phone block.
        if shared_lines and attorneys:
            firm = shared_lines[0]
            phone: str | None = None
            address_lines = shared_lines[1:]
            if address_lines and re.match(
                r"^\(?\d{3}\)?\s*\d{3}\s*[-]?\s*\d{4}", address_lines[-1]
            ):
                phone = address_lines.pop().strip()
            address = ", ".join(address_lines) if address_lines else None
            for atty in attorneys:
                atty.firm = firm
                atty.address = address
                atty.phone = phone
        return attorneys

    # =====================================================================
    # Register of actions (Documents table + free-text expansion)
    # =====================================================================

    def _extract_docket_entries(
        self, page: PageElement, raw_html: str
    ) -> list[NCAppealsDocketEntry]:
        """Pull the Documents table rows and merge in the free-text
        expansion (filed_at / filed_for / filed_by / order_text)."""
        rows = page.query(
            XPath("//table[@aria-labelledby='document_tab']//tr[td]"),
            "document table rows",
            min_count=0,
        )
        entries: list[NCAppealsDocketEntry] = []
        for row in rows:
            cell_elements = row.query(
                XPath("./td"), "document cells", min_count=0
            )
            cells = [clean(c.text_content()) or "" for c in cell_elements]
            if len(cells) < 9:
                continue
            first = cells[0] or ""
            match = re.match(r"\((\d+)\)\s*(.+)$", first)
            if not match:
                continue
            idx = int(match.group(1))
            doc_type = clean(match.group(2)) or ""
            entries.append(
                NCAppealsDocketEntry(
                    number=idx,
                    document_type=doc_type,
                    date_received=parse_date(cells[1]),
                    cert_of_service=parse_date(cells[2]),
                    rec_brf_due=cells[3] or None,
                    response_due=cells[4] or None,
                    response_received=parse_date(cells[5]),
                    mailed_out=parse_date(cells[6]),
                    ruling=cells[7] or None,
                    ruling_date=parse_date(cells[8]),
                )
            )
        if not entries:
            return entries

        # Merge in the free-text expansion: the chunk between the
        # Documents table and the next ``<div … class='section_tab'>``
        # heading. We parse this off the markup rather than the lxml tree
        # because the structure is just hr-separated text, not a real
        # container.
        expansions = self._extract_entry_expansions(raw_html)
        for entry_obj in entries:
            details = expansions.get(entry_obj.number)
            if not details:
                continue
            entry_obj.filed_at = details.get("filed_at")
            entry_obj.filed_for = details.get("filed_for")
            entry_obj.filed_by = details.get("filed_by")
            entry_obj.order_text = details.get("order_text")
        return entries

    def _extract_entry_expansions(
        self, raw_html: str
    ) -> dict[int, dict[str, str]]:
        """Grab the free-text register-of-actions expansion blocks.

        The block sits between the Documents table close-tag and the next
        ``<div … class='section_tab'>`` heading. Each entry is delimited
        by ``<br><hr>`` and starts with ``N - TYPE  (Ruling) -
        RulingDate``.
        """
        end_re = re.search(
            r"</table>\s*(?:<\s*br\s*/?\s*>\s*)*<\s*hr\s*/?\s*>"
            r"(.*?)<div[^>]*class='section_tab'",
            raw_html,
            re.DOTALL | re.IGNORECASE,
        )
        if not end_re:
            return {}
        chunk = end_re.group(1)
        raw_blocks = re.split(r"<\s*hr\s*/?\s*>", chunk, flags=re.IGNORECASE)
        out: dict[int, dict[str, str]] = {}
        for raw_block in raw_blocks:
            if not raw_block.strip():
                continue
            # Pull the order text before stripping HTML (so we keep the
            # blockquote whitespace).
            order_match = re.search(
                r"<blockquote[^>]*>(.*?)</blockquote>",
                raw_block,
                re.DOTALL | re.IGNORECASE,
            )
            order_text = (
                clean(strip_tags(order_match.group(1)))
                if order_match
                else None
            )

            body_html = (
                raw_block[: order_match.start()] if order_match else raw_block
            )
            plain = strip_tags(_BR_RE.sub("\n", body_html))
            lines = [
                stripped
                for stripped in (line.strip() for line in plain.split("\n"))
                if stripped
            ]
            if not lines:
                continue
            header = _ENTRY_HEADER_RE.match(lines[0])
            if not header:
                continue
            idx = int(header.group("idx"))
            details: dict[str, str] = {}
            for line in lines[1:]:
                if line.lower().startswith("filed:"):
                    details["filed_at"] = clean(line[len("filed:") :]) or ""
                elif line.lower().startswith("for:"):
                    details["filed_for"] = clean(line[len("for:") :]) or ""
                elif line.lower().startswith("by"):
                    # e.g. ``BY   : Ms. Callie S. Thomas``
                    _, _, after = line.partition(":")
                    details["filed_by"] = clean(after) or ""
            if order_text:
                details["order_text"] = order_text
            out[idx] = details
        return out
