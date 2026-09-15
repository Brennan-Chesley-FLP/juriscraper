"""Page parsers for the Delaware CourtConnect docket report.

The docket report is a single page with four data sections, so each parser
reads one section of the *same* page rather than one page of a tab flow.
"""

from .case_description import CaseDescriptionParser
from .docket_entries import DocketEntriesParser
from .parties import PartiesParser
from .sections import CaseEventsParser, RelatedCasesParser

__all__ = [
    "CaseDescriptionParser",
    "CaseEventsParser",
    "DocketEntriesParser",
    "PartiesParser",
    "RelatedCasesParser",
]
