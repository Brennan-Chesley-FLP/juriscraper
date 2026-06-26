"""Page parsers for the California appellate-courts scraper.

One ``JKentParser`` subclass per page-type (tab). The summary, disposition,
and trial-court layouts differ between the Supreme Court and the Courts of
Appeal, so those parsers take an ``is_supreme`` flag.
"""

from .briefs import BriefsParser
from .case_summary import CaseSummaryParser
from .disposition import DispositionParser
from .docket import DocketEntriesParser
from .parties import PartiesParser
from .trial_court import TrialCourtParser

__all__ = [
    "BriefsParser",
    "CaseSummaryParser",
    "DispositionParser",
    "DocketEntriesParser",
    "PartiesParser",
    "TrialCourtParser",
]
