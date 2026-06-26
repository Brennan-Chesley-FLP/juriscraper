"""California Appellate Courts Case Information scraper, parsers, and models."""

from .models import (
    CaAppAttorney,
    CaAppBrief,
    CaAppCaseUnavailable,
    CaAppCoaCaseLink,
    CaAppDisposition,
    CaAppDocket,
    CaAppDocketEntry,
    CaAppLowerCourtInfo,
    CaAppOpinionFile,
    CaAppParty,
    CaAppTrialCourtInfo,
)
from .parsers import (
    BriefsParser,
    CaseSummaryParser,
    DispositionParser,
    DocketEntriesParser,
    PartiesParser,
    TrialCourtParser,
)
from .scraper import CaAppScraper, CaCourtRange

__all__ = [
    "CaAppScraper",
    "CaCourtRange",
    "CaAppAttorney",
    "CaAppBrief",
    "CaAppCaseUnavailable",
    "CaAppCoaCaseLink",
    "CaAppDisposition",
    "CaAppDocket",
    "CaAppDocketEntry",
    "CaAppLowerCourtInfo",
    "CaAppOpinionFile",
    "CaAppParty",
    "CaAppTrialCourtInfo",
    "BriefsParser",
    "CaseSummaryParser",
    "DispositionParser",
    "DocketEntriesParser",
    "PartiesParser",
    "TrialCourtParser",
]
