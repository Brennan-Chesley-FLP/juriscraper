"""Pydantic models for the Washington ACDocPortal JSON API responses.

These models describe the ``/PublicAccess/api/CustomQuery/KeywordSearch``
response verbatim so the framework can do post-hoc validation against
stored runs (via ``@step()``) and surface schema drift as
soon as it appears.

IMPORTANT: Every model sets ``extra="forbid"``.  If the portal starts
returning new fields, validation will fail loudly — update the model
rather than silently ignoring the new keys.

The response shape is identical for the Supreme Court (QueryID=194) and
the Court of Appeals (QueryID=193); only the column headings differ
("SC Filing Type" vs "CA Filing Type", etc.), so :class:`DisplayColumn`
holds ``Heading`` as a free-form string.

Observed shape::

    {
      "Data": [
        {
          "ID": "<opaque token>",
          "Name": "<span ...>...</span> - 1048343 - ...",
          "DisplayType": "OleActivePage",
          "DisplayColumnValues": [
            {"Value": "4/8/2026", "RawValue": "1775606400000"},
            {"Value": "E-Mail",   "RawValue": null},
            ...
          ]
        },
        ...
      ],
      "Truncated": false,
      "DisplayColumns": [
        {"Heading": "Doc Filed Date", "DataType": "Date"},
        ...
      ]                                      // null when Data is empty
    }
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class KeywordSearchCell(BaseModel):
    """A single cell inside a row's ``DisplayColumnValues`` array.

    ``Value`` is the human-readable rendering used for display (e.g. a
    formatted date ``"4/8/2026"`` or an HTML span-wrapped summary).
    ``RawValue`` is the machine-readable form where available — for date
    columns the portal ships a millisecond-epoch string like
    ``"1775606400000"``; for text columns it is ``null``.
    """

    model_config = ConfigDict(extra="forbid")

    Value: str
    RawValue: str | None = None


class KeywordSearchRow(BaseModel):
    """One result row — i.e. one filed or issued document."""

    model_config = ConfigDict(extra="forbid")

    ID: str
    """Opaque token used to construct the document download URL."""

    Name: str
    """Human-readable HTML summary (same content as the ``Document Name``
    display column)."""

    DisplayType: str
    """Document rendering hint.  Observed values: ``"OleActivePage"``."""

    DisplayColumnValues: list[KeywordSearchCell]
    """Parallel to the top-level ``DisplayColumns`` — one cell per column,
    in the same order."""


class DisplayColumn(BaseModel):
    """Describes one of the columns that make up each row.

    Headings differ between Supreme Court (``"SC ..."``) and Court of
    Appeals (``"CA ..."``) responses, but positions are stable:

    0. Doc Filed Date          (DataType ``"Date"``)
    1. {SC,CA} Filing Type     (``"AlphaNumericSingleTableCSInsensitiveSearch"``)
    2. {SC,CA} Filing Subtype  (``"AlphaNumericSingleTableCSInsensitiveSearch"``)
    3. Document Name           (``"AlphaNumeric"``)
    4. {SC,CA} Case {Short ,} Title (``"AlphaNumericSingleTableCSInsensitiveSearch"``)
    5. {SC,CA} Anchor Case Number   (``"LargeNumeric"``)
    """

    model_config = ConfigDict(extra="forbid")

    Heading: str
    DataType: str


class KeywordSearchResponse(BaseModel):
    """Top-level response from ``/api/CustomQuery/KeywordSearch``.

    Empty responses return ``Data=[]`` and ``DisplayColumns=null``.
    """

    model_config = ConfigDict(extra="forbid")

    Data: list[KeywordSearchRow] = []
    Truncated: bool = False
    DisplayColumns: list[DisplayColumn] | None = None
