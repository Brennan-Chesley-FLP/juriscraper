"""Parser for a Michigan case-search listing ``searchItem``.

Both the paginated listing endpoint and the single-case lookup endpoint
return the same ``searchItem`` JSON shape (see ``CC_NOTES.md`` →
"searchItem schema"). :class:`ListingItemParser` turns one such item into
a single :class:`MichDocket`. The ``court``, ``source_url`` (when the item
carries no ``caseUrl``), and ``source_entry_point`` provenance fields are
stamped by the calling step.

This is a JSON parser, not an HTML ``JKentParser`` (the site is a pure
JSON API). It keeps the JKentParser contract — a callable returning
``list[DeferredValidation[T]]`` — so the scraper step stays thin and the
extraction is unit-testable offline against a saved JSON fragment.
"""

from __future__ import annotations

from jkent.common.deferred_validation import DeferredValidation

from juriscraper.state.michigan.courts_michigan_gov.models import (
    SITE_BASE,
    MichDocket,
    MichTrialCourtRef,
)

from ._common import clean_str, parse_filing_date


class ListingItemParser:
    """Parse one Michigan ``searchItem`` dict into a ``MichDocket``.

    Returns a one-element list (or empty when the item carries no case
    number for the requested ``court``), matching the JKentParser
    single-record convention.
    """

    def __init__(self, court: str) -> None:
        """Build a parser bound to a CourtListener ``court`` id.

        The court selects which of the item's per-system case-number /
        status fields is treated as this docket's identity.
        """
        self.court = court

    def __call__(self, item: dict) -> list[DeferredValidation[MichDocket]]:
        """Extract a single ``MichDocket`` from a listing item."""
        if self.court == "michctapp":
            number = item.get("courtOfAppealsCaseNumber")
            status = item.get("courtOfAppealsCaseStatus")
        else:
            number = item.get("supremeCourtCaseNumber")
            status = item.get("supremeCourtCaseStatus")

        if not number:
            return []

        case_name = clean_str(item.get("title")) or f"{self.court} {number}"

        case_url = item.get("caseUrl") or ""
        source_url = (
            f"{SITE_BASE}{case_url}"
            if isinstance(case_url, str) and case_url.startswith("/")
            else (case_url or None)
        )

        trial_courts = [
            MichTrialCourtRef(name=name)
            for name in (item.get("courts") or [])
            if isinstance(name, str) and name.strip()
        ]

        docket = MichDocket.raw(
            docket_number=str(number),
            court=self.court,
            case_name=case_name,
            date_filed=parse_filing_date(item.get("filingDate")),
            case_status=clean_str(status),
            has_opinions=item.get("hasOpinions"),
            has_orders=item.get("hasOrders"),
            coa_case_number=item.get("courtOfAppealsCaseNumber"),
            msc_case_number=item.get("supremeCourtCaseNumber"),
            coc_case_number=clean_str(item.get("courtOfClaimsCaseNumber")),
            trial_courts=trial_courts,
            source_url=source_url,
        )
        return [docket]
