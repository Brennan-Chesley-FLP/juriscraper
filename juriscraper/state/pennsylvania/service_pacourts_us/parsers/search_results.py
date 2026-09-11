"""Parser for the PA courts case-search response.

``POST /public/v1/cases/search`` returns an envelope whose ``results`` array
holds *summary* rows — docket number, caption, filing date, status and court
office, plus an ``href`` to the full case document. The summaries carry far
less than the case document, so the scraper uses them only to discover docket
numbers and then fetches each case in full.

Not a ``JKentParser`` subclass — see ``_common.py`` for why.
"""

from __future__ import annotations

from typing import Any

from juriscraper.state.pennsylvania.service_pacourts_us.models import (
    SITE_COURT_NAME_TO_COURT_ID,
)

from ._common import as_dict, as_list, clean_str, dig, parse_date

#: Hard result cap the endpoint applies. The response echoes ``startIndex`` /
#: ``endIndex``, but supplying them in the request body does **not** page —
#: the server ignores them and always returns the first window — so a search
#: that comes back at the cap is silently truncated.
SEARCH_RESULT_CAP = 150


class SearchResultsParser:
    """Extract appellate case summaries from a search response."""

    def __call__(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Return one summary dict per result row.

        Every row is returned, trial-court rows included; filtering to the
        appellate courts is the caller's job (it depends on the requested
        ``court_ids``, which live in ``accumulated_data``).
        """
        summaries: list[dict[str, Any]] = []
        for raw in as_list(payload.get("results")):
            row = as_dict(raw)
            court_name = clean_str(
                dig(row, "courtOffice", "court", "displayName")
            )
            summaries.append(
                {
                    "docket_number": clean_str(row.get("docketNumber")),
                    "case_name": clean_str(row.get("shortCaption")),
                    "date_filed": parse_date(row.get("filingDate")),
                    "status_name": clean_str(row.get("statusName")),
                    "court": SITE_COURT_NAME_TO_COURT_ID.get(court_name or ""),
                    "court_name": court_name,
                    "court_office_name": clean_str(
                        dig(row, "courtOffice", "displayName")
                    ),
                    "case_system": clean_str(dig(row, "id", "caseSystem")),
                    "api_url": clean_str(row.get("href")),
                }
            )
        return summaries

    @staticmethod
    def error_messages(payload: dict[str, Any]) -> list[str]:
        """Return the endpoint's validation errors, if it rejected the search.

        The API answers an under-specified search with **HTTP 200** and an
        ``{"errorMessages": [...]}`` body, so this is the soft-failure signal.
        """
        return [
            message
            for message in (
                clean_str(m) for m in as_list(payload.get("errorMessages"))
            )
            if message
        ]

    @staticmethod
    def hit_result_cap(payload: dict[str, Any]) -> bool:
        """Whether the response came back at the truncation cap."""
        return len(as_list(payload.get("results"))) >= SEARCH_RESULT_CAP
