"""Pure-function helpers for C-Track HTML-form scrapers.

See the module docstring on ``__init__.py`` for the scope of "C-Track
HTML-form" and which sites use this code path.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from jkent.data_types import XPath

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


SOFT_404_MARKER = "You do not have rights to view this case"
"""Body sentinel emitted for sealed cases and invalid csIIDs.

Sites differ on the HTTP status code that accompanies this body — Nevada
serves it as HTTP 200, DC as HTTP 500 — so the marker is the most
reliable signal. Use it from ``fails_successfully`` against
``response.text``.
"""


_DWR_DOC_LINK_RE = re.compile(
    r'<a\s+href=\\?"([^"\\]*?documentID=(\d+)[^"\\]*)\\?"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
"""Match ``<a href="…documentID=N" …>label</a>`` anchors in a DWR reply.

The DWR plaincall response embeds the HTML as a quoted JS string, so
the angle-quote characters arrive backslash-escaped. Anchoring on
``documentID=`` is more robust than full DWR-payload parsing.
"""


def parse_mmddyyyy(text: str | None) -> date | None:
    """Parse the ``MM/DD/YYYY`` date strings used throughout C-Track."""
    if not text:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%m/%d/%Y").date()
    except ValueError:
        return None


def build_search_form_skeleton(
    *,
    start_row: int = 1,
    display_rows: int = 50,
    order_by: str = "FileDt",
    order_dir: str = "DESC",
    href: str = "/public/caseView.do",
    submit_value: str = "Search",
    action: str = "",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the hidden-fields skeleton for ``/public/caseSearch.do`` POSTs.

    The visible search fields (``csNumber``, ``shortTitle``, ``fromDt``,
    ``toDt``, ``courtID``, etc.) vary per site; pass them in via
    ``extra``. The defaults here mirror what the in-page Search button
    submits when no JS sort/page interaction has happened.

    Sort behavior:
        ``order_by`` is the SQL column name shown in the page's
        ``postSortOrder('FOO', 'ASC|DESC')`` JS calls. Common choices:
        ``FileDt`` (filed date — used by SC), ``CsNumber`` (case number —
        DC's default), ``SQLFileDt`` (Minnesota).
    """
    form: dict[str, str] = {
        "submitValue": submit_value,
        "action": action,
        "startRow": str(start_row),
        "displayRows": str(display_rows),
        "orderBy": order_by,
        "orderDir": order_dir,
        "href": href,
    }
    if extra:
        form.update(
            {k: ("" if v is None else str(v)) for k, v in extra.items()}
        )
    return form


def build_dwr_doc_links_body(
    *,
    case_url: str,
    params: list[str],
    script_session_id: str = "KENT",
) -> bytes:
    """Build the ``text/plain`` body for an ``AJAX.getViewDocumentLinks`` call.

    Args:
        case_url: The case-view URL the user is "on" — only the path
            portion is sent in the ``page=`` field. Either a full URL or
            a path is accepted. Pass the ``caseView.do?csIID=N`` URL,
            *not* the original ``caseSearch.do`` POST URL — kent's
            ``Response.url`` reports the request URL even after a 302,
            so re-deriving from csIID at the call site is safer than
            using ``response.url`` directly.
        params: One string per ``c0-paramN`` slot. South Carolina sends
            one param (the ``deID``); DC splits its ``documentLink``
            icon ``name`` attribute (``"50:1685970:70000"``) into three
            params (``["50", "1685970", "70000"]``).
        script_session_id: Any literal string. The server doesn't
            validate this; the default ``"KENT"`` makes scraper traffic
            recognizable in server logs.

    Returns ``bytes`` (UTF-8) rather than ``str`` because kent's
    ``HTTPRequestParams.data`` is typed
    ``dict | list[tuple] | bytes | BinaryIO | None`` — a ``str`` would
    be JSON-encoded by the persistence layer and the resulting wire
    body would carry surrounding quotes and escaped newlines, which
    DWR's plaintext parser rejects with
    "The specified call count is not a number: null".

    The endpoint is stateless on the C-Track sites observed —
    ``httpSessionId`` may be empty.
    """
    if "//" in case_url:
        page_param = case_url.split("//", 1)[-1].split("/", 1)[-1]
    else:
        page_param = case_url
    if not page_param.startswith("/"):
        page_param = "/" + page_param

    lines = [
        "callCount=1",
        f"page={page_param}",
        "httpSessionId=",
        f"scriptSessionId={script_session_id}",
        "c0-scriptName=AJAX",
        "c0-methodName=getViewDocumentLinks",
        "c0-id=0",
    ]
    for i, value in enumerate(params):
        lines.append(f"c0-param{i}=string:{value}")
    lines.append("batchId=0")
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_dwr_doc_link_anchors(
    response_body: str, base_url: str
) -> list[tuple[str, str, str]]:
    """Parse a DWR ``getViewDocumentLinks`` reply.

    The body is a ``dwr.engine._remoteHandleCallback('0','0', "<a …>")``
    invocation whose third argument is an HTML fragment with one
    ``<a>`` per attached document.

    Returns:
        List of ``(download_url, document_id, label)`` tuples — the URL
        is absolute, joined against ``base_url``; the label is
        whitespace-collapsed and HTML-entity-decoded for ``&amp;``.
    """
    results: list[tuple[str, str, str]] = []
    for match in _DWR_DOC_LINK_RE.finditer(response_body or ""):
        href = match.group(1).replace(r"\/", "/").replace("&amp;", "&")
        document_id = match.group(2)
        label = " ".join(match.group(3).replace("&amp;", "&").split())
        download_url = urljoin(base_url, href)
        results.append((download_url, document_id, label))
    return results


def parse_label_value_table(
    page: PageElement, *, label_class: str = "label"
) -> dict[str, str]:
    """Parse ``<td class="label">Label:</td><td>Value</td>`` pairs.

    The C-Track case-info section places its key/value pairs in a flat
    table where label cells carry ``class="label"`` (or ``"Label"`` —
    case varies between deployments). Each label cell's
    *immediate-following sibling* ``<td>`` holds the value.

    A single ``<tr>`` may carry multiple label/value pairs, so we walk
    label cells globally rather than row-by-row.

    Args:
        label_class: The class attribute the site uses on label cells.
            Default ``"label"`` matches DC. Pass ``"Label"`` for SC, or
            adapt for any other variant. Matching is exact, so use the
            site's literal casing.

    Returns:
        Dict keyed on the trimmed label text with the trailing colon
        removed. The first occurrence of a label wins so that label
        re-use (rare in practice) doesn't silently overwrite.
    """
    result: dict[str, str] = {}
    label_cells = page.query(
        XPath(f"//td[@class='{label_class}']"),
        f"label cells (class={label_class!r})",
        min_count=0,
    )
    for label_cell in label_cells:
        label_text = " ".join(label_cell.text_content().split()).rstrip(":")
        value_cells = label_cell.query(
            XPath("./following-sibling::td[1]"),
            "value cell",
            min_count=0,
            max_count=1,
        )
        if not value_cells:
            continue
        value = " ".join(value_cells[0].text_content().split())
        if label_text and label_text not in result:
            result[label_text] = value
    return result
