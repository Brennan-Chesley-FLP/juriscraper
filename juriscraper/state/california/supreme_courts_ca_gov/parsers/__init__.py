"""Page parsers for the California Supreme Court briefs scraper."""

from .briefs_index import BriefsIndexParser
from .session_page import SessionPageParser

__all__ = ["BriefsIndexParser", "SessionPageParser"]
