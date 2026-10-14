"""Parsers for the Related Cases and Case Event Schedule sections.

Both sections render on every docket report and are empty on the overwhelming
majority of them, so their real shape only showed up in a 54,502-page corpus:
**65 pages** carry a populated event schedule and **2** a populated related-case
list. Both are now read against the shape those pages show, rather than
generically.

The two sections are built quite differently:

* **Related Cases is not a table.** It is a bare run of ``<a>`` links separated
  by ``&nbsp;&nbsp;``, each pointing the frameset wrapper
  (``cp_dktrpt_frames``) at another case id and carrying that id as its text.
  There are no columns and no relationship label -- the site says the cases are
  related, never how. A table-based reader finds nothing here, which is why
  ``related_cases`` came back empty on all 26,962 records of the corpus even
  though two of the pages behind them list three related cases each.
* **Case Event Schedule is a five-column table**: Event, Date/Time, Room,
  Location, Judge. The Date/Time cell is ``<br>``-split the same way a docket
  entry's is ("14-JUN-2011" / "09:00 AM").

A scheduled event is emitted as a ``DeCourtConnectDocketEntry`` tagged
``source_section="case_event_schedule"``, not as a record type of its own: a
future-dated calendar entry is a docket entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.delaware.courtconnect_courts_delaware_gov.models import (
    DeCourtConnectDocketEntry,
    DeCourtConnectRelatedCase,
)

from ._common import (
    cell_lines,
    clean_text,
    header_labels,
    parse_date,
    parse_time,
)

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement

#: The Related Cases links, selected by position: everything between the
#: section's anchor and the next one. The section has no container and no
#: table, so there is nothing else to select on.
_RELATED_LINKS = XPath(
    '//a[@name="related"]/following::a[@href][following::a[@name="events"]]'
)

#: Event-schedule header labels, mapped to the entry field each fills. The
#: column set is the one every populated schedule in the corpus renders; a
#: label not listed here lands in ``extra_fields``.
_EVENT_COLUMNS: dict[str, str] = {
    "event": "description",
    "date/time": "_date_time",
    "room": "courtroom",
    "location": "location",
    "judge": "name",
}


def section_tables(
    page: PageElement, start_anchor: str, end_anchor: str
) -> list[PageElement]:
    """Return the tables rendered between two of the page's section anchors.

    The page marks each section with ``<a name="related">``, ``<a
    name="events">`` and so on, but never closes those anchors and never wraps
    a section in a container -- so a section's content cannot be selected by
    descent, only by position between two markers.

    Both anchor sets are counted rather than compared for identity: the tables
    belonging to the section are the leading ``count(after start) - count(after
    end)`` of those following ``start_anchor``. This needs no element equality,
    which ``PageElement`` does not define.
    """
    after_start = page.query(
        XPath(f'//a[@name="{start_anchor}"]/following::table'),
        f"tables after the {start_anchor} anchor",
        min_count=0,
    )
    after_end = page.query(
        XPath(f'//a[@name="{end_anchor}"]/following::table'),
        f"tables after the {end_anchor} anchor",
        min_count=0,
    )
    span = len(after_start) - len(after_end)
    return after_start[:span] if span > 0 else []


def _rows_as_maps(table: PageElement) -> list[dict[str, str]]:
    """Read a table as one ``{column label: value}`` map per data row.

    Rows with more cells than there are labels keep the surplus under
    positional ``column N`` keys, so nothing is lost when the header is
    narrower than the body (which is how the parties and docket tables are
    built).
    """
    rows = table.query(XPath("./tr | ./tbody/tr"), "section rows", min_count=0)
    labels = header_labels(rows)
    maps: list[dict[str, str]] = []
    for row in rows:
        cells = row.query(XPath("./td"), "section cells", min_count=0)
        if not cells:
            continue
        values = ["\n".join(cell_lines(cell)) for cell in cells]
        if not any(value.strip() for value in values):
            # The one-cell spacer row the site puts between records.
            continue
        row_map: dict[str, str] = {}
        for index, value in enumerate(values):
            label = labels[index] if index < len(labels) else ""
            row_map[label or f"column {index + 1}"] = value
        maps.append(row_map)
    return maps


class RelatedCasesParser(JKentParser[DeCourtConnectRelatedCase]):
    """Parse the Related Cases link list into one record per related case.

    Each link's ``case_id`` query parameter and its text are the same case id;
    the parameter is preferred because it is what the site would use to fetch
    the case, and the text is the fallback for a link the site renders without
    one.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[DeCourtConnectRelatedCase]]:
        links = page.query(_RELATED_LINKS, "related case links", min_count=0)
        records: list[DeferredValidation[DeCourtConnectRelatedCase]] = []
        seen: set[str] = set()
        for link in links:
            docket_number = self._case_id(link)
            if docket_number is None or docket_number in seen:
                continue
            seen.add(docket_number)
            records.append(
                DeCourtConnectRelatedCase.raw(docket_number=docket_number)
            )
        return records

    @staticmethod
    def _case_id(link: PageElement) -> str | None:
        """Read the linked case id, from the href's query or the link text.

        The link text is read through :func:`cell_lines` -- i.e. through a
        ``.//text()`` query -- rather than ``text_content()``, so that
        ``jent residuals`` sees the text node as consumed. ``text_content()``
        reads it without querying it, which leaves the case id looking like
        unclaimed page text.
        """
        text = clean_text(" ".join(cell_lines(link)))
        href = link.get_attribute("href")
        if href:
            values = parse_qs(urlparse(href).query).get("case_id")
            if values and (case_id := clean_text(values[0])):
                return case_id
        return text


class CaseEventsParser(JKentParser[DeCourtConnectDocketEntry]):
    """Parse the Case Event Schedule into docket-entry records.

    Columns are matched by header label rather than by position, because the
    schedule's header is the one part of this page the site could reorder
    without breaking its own layout. An unrecognised label keeps its value in
    ``extra_fields`` instead of being dropped.
    """

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[DeCourtConnectDocketEntry]]:
        records: list[DeferredValidation[DeCourtConnectDocketEntry]] = []
        for table in section_tables(page, "events", "parties"):
            for index, row in enumerate(_rows_as_maps(table)):
                fields, extra = self._split_columns(row)
                # "14-JUN-2011<br>09:00 AM" -- the same two-line cell the
                # Docket Entries table uses for its Filing Date.
                lines = (fields.pop("_date_time", "") or "").split("\n")
                records.append(
                    DeCourtConnectDocketEntry.raw(
                        date_filed=parse_date(lines[0] if lines else None),
                        time_filed=parse_time(
                            lines[1] if len(lines) > 1 else None
                        ),
                        description=clean_text(fields.get("description")),
                        name=clean_text(fields.get("name")),
                        courtroom=clean_text(fields.get("courtroom")),
                        location=clean_text(fields.get("location")),
                        sequence_number=index,
                        source_section="case_event_schedule",
                        extra_fields=extra,
                    )
                )
        return records

    @staticmethod
    def _split_columns(
        row: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Split a row into named fields and the leftovers."""
        fields: dict[str, str] = {}
        extra: dict[str, str] = {}
        for label, value in row.items():
            field = _EVENT_COLUMNS.get(label.strip().lower())
            if field is None:
                if value.strip():
                    extra[label] = value
            else:
                fields[field] = value
        return fields, extra
