"""Shared utilities for C-Track HTML-form (Public Access) scrapers.

This module covers the older Thomson Reuters / Travelers C-Track web app
that exposes ``/public/caseSearch.do`` (POST) and
``/public/caseView.do?csIID=N`` (GET). Multiple state appellate courts
run this same web app:

- South Carolina: https://ctrack.sccourts.org/
- DC Court of Appeals: https://efile.dcappeals.gov/
- Nevada: https://caseinfo.nvsupremecourt.us/ (forms differ slightly;
  Nevada uses speculative csIID enumeration rather than the search form)
- Minnesota: https://macsnc.courts.state.mn.us/ctrack/ (Volterra-protected
  Java/JSP variant under a `/ctrack/` prefix)

The newer Thomson Reuters Public Portal (REST/JSON) used by Alabama,
Oregon, Wyoming, North Dakota lives in ``juriscraper.state.common.tr``
— that is a different code path despite the shared "C-Track" branding.

What the sites have in common (and is captured here):

- The hidden-fields skeleton on the search form
  (``submitValue``, ``startRow``, ``displayRows``, ``orderBy``,
  ``orderDir``, ``href``, ``action``).
- The ``MM/DD/YYYY`` date format on every visible field.
- The ``"You do not have rights to view this case"`` marker that the
  app emits for sealed cases and out-of-range csIIDs.
- The DWR-based document-link resolution: a POST to
  ``…/dwr/call/plaincall/AJAX.getViewDocumentLinks.dwr`` whose response
  embeds ``<a href="…documentID=N">label</a>`` anchors.
- The ``<td class="label">`` (or ``"Label"``) key/value layout used on
  the case-detail page's case-info section.

What is **not** shared and stays per-scraper:

- The exact set of visible search fields (DC adds ``lcCsNumber``;
  SC adds ``csGroupID``/``csTypeID``/``courtID``).
- The party-table column count (NV=3, SC=4, DC=6).
- The events/docket-entries column layout.
- The DWR call's parameter shape — SC sends one ``string:{deID}`` param,
  DC splits the icon ``name`` ``"{flag}:{deID}:{csIID}"`` into three
  params.
- Soft-404 status code: NV serves the marker as HTTP 200, DC as HTTP 500.
- Bot protection. MN sits behind a Volterra/F5 challenge; the others
  serve the same HTML to a plain ``curl``.
"""

from .utils import (
    SOFT_404_MARKER,
    build_dwr_doc_links_body,
    build_search_form_skeleton,
    parse_dwr_doc_link_anchors,
    parse_label_value_table,
    parse_mmddyyyy,
)

__all__ = [
    "SOFT_404_MARKER",
    "build_dwr_doc_links_body",
    "build_search_form_skeleton",
    "parse_dwr_doc_link_anchors",
    "parse_label_value_table",
    "parse_mmddyyyy",
]
