"""Page parsers for the Arizona appellate-courts (AppellaDockets) scraper."""

from .attorney_index import AttorneyIndexParser
from .case_list import CaseListParser
from .lower_court_index import LowerCourtIndexParser
from .party_index import PartyIndexParser

__all__ = [
    "AttorneyIndexParser",
    "CaseListParser",
    "LowerCourtIndexParser",
    "PartyIndexParser",
]
