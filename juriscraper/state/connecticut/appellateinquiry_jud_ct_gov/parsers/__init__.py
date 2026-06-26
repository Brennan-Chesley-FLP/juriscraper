"""Page parsers for the Connecticut appellate-inquiry docket scraper."""

from .case_detail import ActivitiesParser, AppealCaseParser
from .trial_court import TrialActivitiesParser, TrialCourtCaseParser

__all__ = [
    "ActivitiesParser",
    "AppealCaseParser",
    "TrialActivitiesParser",
    "TrialCourtCaseParser",
]
