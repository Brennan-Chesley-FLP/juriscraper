"""Page parsers for the Alaska appellate-records scraper.

One ``JKentParser`` subclass per page-type; ``_common`` holds shared
extraction helpers.
"""

from .brief_history import BriefHistoryParser
from .briefs import BriefsParser
from .case_general import CaseGeneralParser
from .docket import DocketParser
from .motion_detail import MotionDetailParser
from .motions import MotionsParser
from .parties import PartiesParser
from .records import RecordParser
from .search_results import SearchResultsParser

__all__ = [
    "BriefHistoryParser",
    "BriefsParser",
    "CaseGeneralParser",
    "DocketParser",
    "MotionDetailParser",
    "MotionsParser",
    "PartiesParser",
    "RecordParser",
    "SearchResultsParser",
]
