"""Page parsers for the Iowa Appellate Courts scraper.

One extractor per page-type of the ESAWebApp case flow:

- :class:`SearchResultsParser` — docket numbers off the advanced-search
  results page.
- :class:`CaseSummaryParser` — header scalars off the Summary tab.
- :class:`LongTitleParser` — the formal caption off the Long Title tab.
- :class:`DocketEntriesParser` — register-of-actions rows off the Docket tab.
- :class:`PartiesParser` — party/attorney rows off the Parties tab.
"""

from .case_summary import CaseSummaryParser
from .docket_entries import DocketEntriesParser
from .long_title import LongTitleParser
from .parties import PartiesParser
from .search_results import SearchResultsParser

__all__ = [
    "CaseSummaryParser",
    "DocketEntriesParser",
    "LongTitleParser",
    "PartiesParser",
    "SearchResultsParser",
]
