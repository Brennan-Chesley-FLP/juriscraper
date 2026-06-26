"""Page parsers for the Massachusetts Appellate Courts scraper."""

from .calendar import CalendarParser
from .case_detail import CaseDetailParser

__all__ = ["CalendarParser", "CaseDetailParser"]
