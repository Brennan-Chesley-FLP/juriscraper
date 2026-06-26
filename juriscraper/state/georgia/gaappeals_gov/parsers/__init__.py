"""Page parsers for the Georgia Court of Appeals scraper."""

from .case_detail import CaseDetailParser
from .opinion_search import OpinionSearchParser, OpinionSearchRow

__all__ = ["CaseDetailParser", "OpinionSearchParser", "OpinionSearchRow"]
