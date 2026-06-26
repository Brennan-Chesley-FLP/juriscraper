"""Pydantic models for the Montana Supreme Court docket JSON API.

These describe the wire format returned by the endpoints:

- ``POST /api/docket/search``                     → :class:`SearchResponse`
- ``GET  /api/docket/case-info?caseId=<id>``      → :class:`CaseInfoResponse`
- ``GET  /api/docket/case-info-pre-2006?...``     → :class:`CaseInfoResponse`

They are distinct from the scraper's output models in :mod:`models` — these
are strictly the raw API payloads, used only inside the scraper to validate
incoming JSON and translate it into ``ScrapedData`` records.

Python-style snake_case field names are used with ``Field(alias=...)`` to
keep the wire protocol's camelCase aliases. ``extra="allow"`` keeps the
models forward-compatible when the API adds new fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _ApiModel(BaseModel):
    """Shared config: accept camelCase aliases and unknown fields."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
    )


# ---------------------------------------------------------------------------
# Search API
# ---------------------------------------------------------------------------


class SearchHit(_ApiModel):
    """A single row in ``SearchResponse.content``.

    ``caseId`` is null for pre-2006 archive hits; those are fetched via the
    ``case-info-pre-2006`` endpoint using ``caseNumber`` as the key.
    """

    case_id: int | None = Field(default=None, alias="caseId")
    case_number: str = Field(alias="caseNumber")
    case_title: str | None = Field(default=None, alias="caseTitle")
    attorneys: list[str] = Field(default_factory=list)


class SearchPage(_ApiModel):
    """The ``page`` block on every paginated response."""

    size: int
    number: int
    """Zero-indexed page number currently returned."""

    total_elements: int = Field(alias="totalElements")
    total_pages: int = Field(alias="totalPages")


class SearchResponse(_ApiModel):
    """Response shape of ``POST /api/docket/search``."""

    content: list[SearchHit] = Field(default_factory=list)
    page: SearchPage


# ---------------------------------------------------------------------------
# Case-info API (modern + pre-2006)
# ---------------------------------------------------------------------------


class CaseInfoDocumentRef(_ApiModel):
    """A single document reference inside a docket entry.

    Sealed placeholders have ``document_id == "0"``,
    ``document_location == "Unavailable.pdf"`` and
    ``filenet_object_id == "{0}"``.
    """

    document_id: str = Field(default="", alias="documentId")
    document_location: str = Field(default="", alias="documentLocation")
    filenet_object_id: str = Field(default="", alias="filenetObjectId")


class CaseInfoDocketEntry(_ApiModel):
    """A single row of the ``dockets`` array in a case-info response."""

    document_description: str | None = Field(
        default=None, alias="documentDescription"
    )
    filing_date: str | None = Field(default=None, alias="filingDate")
    """ISO-8601 timestamp string, e.g. ``"2004-05-12T22:33:33.000+00:00"``."""

    documents: list[CaseInfoDocumentRef] = Field(default_factory=list)


class CaseInfoParty(_ApiModel):
    """Modern case-info party record. ``parties`` is null for pre-2006."""

    appellate_role: str | None = Field(default=None, alias="appellateRole")
    party_name: str | None = Field(default=None, alias="partyName")
    comment: str | None = None
    attorney: str | None = None
    """Comma-joined attorney names or a string like ``"Pro Se"``."""

    attorneys: list[str] | None = None


class CaseInfoExtraInfo(_ApiModel):
    """Only populated on pre-2006 archive responses."""

    attorneys_list: str | None = Field(default=None, alias="attorneysList")
    partys_list: str | None = Field(default=None, alias="partysList")
    trial_court_judge: str | None = Field(
        default=None, alias="trialCourtJudge"
    )


class CaseInfoResponse(_ApiModel):
    """Response shape of ``GET /api/docket/case-info(-pre-2006)``.

    Both endpoints return the same top-level schema; the pre-2006 variant
    simply leaves ``case_id`` and ``parties`` null and populates
    ``extra_case_info``.
    """

    case_number: str | None = Field(default=None, alias="caseNumber")
    court: str | None = None
    original_court: str | None = Field(default=None, alias="originalCourt")
    case_type: str | None = Field(default=None, alias="caseType")
    short_title: str | None = Field(default=None, alias="shortTitle")
    full_title: str | None = Field(default=None, alias="fullTitle")
    summary: str | None = None
    case_filing_date: str | None = Field(default=None, alias="caseFilingDate")
    """``YYYY-MM-DD`` string; null on pre-2006 archive records."""

    original_case_number: str | None = Field(
        default=None, alias="originalCaseNumber"
    )
    case_status: str | None = Field(default=None, alias="caseStatus")
    """Site's short status code (e.g., ``"PB"``, ``"C"``)."""

    citation: str | None = None
    case_id: int | None = Field(default=None, alias="caseId")

    parties: list[CaseInfoParty] | None = None
    dockets: list[CaseInfoDocketEntry] = Field(default_factory=list)
    extra_case_info: CaseInfoExtraInfo | None = Field(
        default=None, alias="extraCaseInfo"
    )
