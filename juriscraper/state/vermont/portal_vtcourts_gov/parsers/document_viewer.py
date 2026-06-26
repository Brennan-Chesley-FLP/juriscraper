"""Parser for the Vermont Public Portal Document Viewer landing page.

Under ``FOLLOW_REDIRECTS`` the ``DisplayDoc`` 302 lands on
``/Portal/DocumentViewer/Index/...``, an HTML shell carrying a
``Download Document`` link. :func:`extract_download_href` lifts that
href; the step resolves it against the response URL and archives the PDF.

This is a single-value lift rather than a record, so it is exposed as a
function (not a :class:`~jkent.common.parser.JKentParser`); it still uses
the public ``PageElement`` query API with count assertions so a layout
change fails loudly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.data_types import XPath

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


def extract_download_href(page: PageElement) -> str | None:
    """Return the ``Download Document`` href, or ``None`` if absent.

    Restricted-access documents (rare for Supreme Court cases) render the
    viewer without a download link; the caller treats ``None`` as a
    silent skip.
    """
    hrefs = page.query_strings(
        XPath("//a[normalize-space()='Download Document']/@href"),
        "download document href",
        min_count=0,
        max_count=1,
    )
    return hrefs[0] if hrefs else None
