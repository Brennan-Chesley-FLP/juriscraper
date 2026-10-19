"""The filing vocabulary supreme.courts.ca.gov publishes in its brief titles.

Each member's value is the string the court itself prints, so a member
compares and serializes as that string. ``None`` -- never a member -- is what
the scraper reports when the court stated nothing, or when it stated something
no member covers; the verbatim text is always kept in the field's ``*_raw``
sibling, so nothing is lost either way.

Codes 0 and 999 are reserved and never belong to a member, so a consumer
storing codes can tell "the court stated nothing" from "the court stated
something this vocabulary does not cover".

Adding to this is expected. A value no member covers is reported as
unrecognized rather than guessed at, which is the signal that the court has
started filing something new.

Mirrors the ``CourtVocabulary`` convention in the sibling
``appellatecases_courtinfo_ca_gov`` scraper.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated

from pydantic import BeforeValidator

__all__ = [
    "CaBriefDocumentType",
    "CodedBriefDocumentType",
    "CourtVocabulary",
]


class CourtVocabulary(str, Enum):
    """Base for the vocabulary below.

    A member is the string the court prints, plus ``code`` -- a small integer
    that never changes or gets reused -- and ``label``, its display form.
    """

    code: int
    label: str

    def __new__(cls, value: str, code: int, label: str) -> CourtVocabulary:
        member = str.__new__(cls, value)
        member._value_ = value
        member.code = code
        member.label = label
        return member


#: A trailing "Filed" the court appends to some brief titles -- "Opening Brief
#: on the Merits Filed". It restates what the listing already is and is the
#: only difference between 20 pairs of otherwise identical titles, so it is
#: stripped before matching rather than doubling the member list.
_TRAILING_FILED_RE = re.compile(r"\s+filed$")

#: The court writes the same letter "Additional Authority Letter" and
#: "Additional Authorities Letter", and likewise for "New" and "Supplemental".
#: Pure spelling variance -- 26 titles use the singular.
_AUTHORITY_RE = re.compile(r"\bauthority\b")


def _normalise(value: str) -> str:
    """A brief's document type reduced to the spelling the members hold."""
    text = " ".join(value.split()).casefold()
    text = _TRAILING_FILED_RE.sub("", text)
    return _AUTHORITY_RE.sub("authorities", text)


class CaBriefDocumentType(CourtVocabulary):
    """The kind of document a brief listing names.

    The 37 members are every document type the court filed 10 or more times
    across the 11,506 brief listings in the 2010-2026 corpus, after the
    spelling variants above are merged. Together they cover **90.2%** of
    listings.

    The remaining 9.8% is a genuinely open long tail, not more spellings of
    these: 692 of the 894 distinct post-split values occur exactly once
    (``P(unseen) = 0.060``), and stripping leading modifiers such as
    "Amended" or "Second Supplemental" collapses only 0.3 points of it. These
    are one-off filings the court titled for the occasion ("Request for
    Judicial Notice in Support of Petitioner's Reply to Returns Submitted by
    Respondent ..."), and they report ``None`` here with the full text in
    ``document_type_raw``.
    """

    AMICUS_CURIAE_BRIEF = "Amicus Curiae Brief", 1, "Amicus curiae brief"
    ANSWER_BRIEF_ON_THE_MERITS = (
        "Answer Brief on the Merits",
        2,
        "Answer brief on the merits",
    )
    OPENING_BRIEF_ON_THE_MERITS = (
        "Opening Brief on the Merits",
        3,
        "Opening brief on the merits",
    )
    REPLY_BRIEF_ON_THE_MERITS = (
        "Reply Brief on the Merits",
        4,
        "Reply brief on the merits",
    )
    PETITION_FOR_REVIEW = "Petition for Review", 5, "Petition for review"
    SUPPLEMENTAL_BRIEF = "Supplemental Brief", 6, "Supplemental brief"
    REQUEST_FOR_JUDICIAL_NOTICE = (
        "Request for Judicial Notice",
        7,
        "Request for judicial notice",
    )
    ANSWER_TO_PETITION_FOR_REVIEW = (
        "Answer to Petition for Review",
        8,
        "Answer to petition for review",
    )
    RESPONSE_TO_AMICUS_CURIAE_BRIEF = (
        "Response to Amicus Curiae Brief",
        9,
        "Response to amicus curiae brief",
    )
    FOCUS_ISSUES_LETTER = "Focus Issues Letter", 10, "Focus issues letter"
    REPLY_TO_ANSWER_TO_PETITION_FOR_REVIEW = (
        "Reply to Answer to Petition for Review",
        11,
        "Reply to answer to petition for review",
    )
    REPLY_BRIEF = "Reply Brief", 12, "Reply brief"
    BRIEF = "Brief", 13, "Brief"
    OPENING_BRIEF = "Opening Brief", 14, "Opening brief"
    ADDITIONAL_AUTHORITIES_LETTER = (
        "Additional Authorities Letter",
        15,
        "Additional authorities letter",
    )
    OPPOSITION = "Opposition", 16, "Opposition"
    NOTICE_OF_ERRATA = "Notice of Errata", 17, "Notice of errata"
    LETTER_BRIEF = "Letter Brief", 18, "Letter brief"
    REPLY_TO_SUPPLEMENTAL_BRIEF = (
        "Reply to Supplemental Brief",
        19,
        "Reply to supplemental brief",
    )
    SUPPLEMENTAL_REPLY_BRIEF = (
        "Supplemental Reply Brief",
        20,
        "Supplemental reply brief",
    )
    SUPPLEMENTAL_LETTER_BRIEF = (
        "Supplemental Letter Brief",
        21,
        "Supplemental letter brief",
    )
    REQUEST_TO_ANSWER_QUESTION_OF_STATE_LAW = (
        "Request to Answer Question of State Law",
        22,
        "Request to answer question of state law",
    )
    WRITTEN_RETURN = "Written Return", 23, "Written return"
    NEW_AUTHORITIES_LETTER = (
        "New Authorities Letter",
        24,
        "New authorities letter",
    )
    SUPPLEMENTAL_OPENING_BRIEF = (
        "Supplemental Opening Brief",
        25,
        "Supplemental opening brief",
    )
    MOTION = "Motion", 26, "Motion"
    TRAVERSE = "Traverse", 27, "Traverse"
    LETTER = "Letter", 28, "Letter"
    JOINDER_TO_BRIEF_ON_THE_MERITS = (
        "Joinder to Brief on the Merits",
        29,
        "Joinder to brief on the merits",
    )
    PETITION_FOR_WRIT_OF_HABEAS_CORPUS = (
        "Petition for Writ of Habeas Corpus",
        30,
        "Petition for writ of habeas corpus",
    )
    JOINDER_TO_PETITION = "Joinder to Petition", 31, "Joinder to petition"
    INFORMAL_RESPONSE = "Informal Response", 32, "Informal response"
    RESPONSE_BRIEF_RE_REFEREES_REPORT = (
        "Response Brief re Referee's Report",
        33,
        "Response brief re referee's report",
    )
    REPLY_TO_INFORMAL_RESPONSE = (
        "Reply to Informal Response",
        34,
        "Reply to informal response",
    )
    EXHIBITS = "Exhibits", 35, "Exhibits"
    SUPPLEMENTAL_AUTHORITIES_LETTER = (
        "Supplemental Authorities Letter",
        36,
        "Supplemental authorities letter",
    )
    ORDER = "Order", 37, "Order"

    @classmethod
    def parse(cls, value: str | None) -> CaBriefDocumentType | None:
        """The member for ``value``, or None when nothing covers it.

        Matching is exact on the court's own string, then on the normalised
        form -- casefolded, with a trailing "Filed" dropped and
        "Authority" read as "Authorities". Those three are spelling variance
        in the court's own titles, not distinctions it draws.
        """
        if not value:
            return None
        text = " ".join(value.split())
        try:
            return cls(text)
        except ValueError:
            pass
        normalised = _normalise(text)
        for member in cls:
            if _normalise(member.value) == normalised:
                return member
        return None

    @property
    def is_amicus(self) -> bool:
        """Whether the filing is an amicus brief or a response to one."""
        return self in {
            CaBriefDocumentType.AMICUS_CURIAE_BRIEF,
            CaBriefDocumentType.RESPONSE_TO_AMICUS_CURIAE_BRIEF,
        }

    @property
    def is_letter(self) -> bool:
        """Whether the court styled the filing a letter rather than a brief.

        Letter filings are how the court takes focused post-grant briefing;
        a consumer separating merits briefing from correspondence wants this
        rather than a match on five strings.
        """
        return self in {
            CaBriefDocumentType.FOCUS_ISSUES_LETTER,
            CaBriefDocumentType.ADDITIONAL_AUTHORITIES_LETTER,
            CaBriefDocumentType.NEW_AUTHORITIES_LETTER,
            CaBriefDocumentType.SUPPLEMENTAL_AUTHORITIES_LETTER,
            CaBriefDocumentType.LETTER,
            CaBriefDocumentType.LETTER_BRIEF,
            CaBriefDocumentType.SUPPLEMENTAL_LETTER_BRIEF,
        }

    @property
    def is_review_stage(self) -> bool:
        """Whether the filing belongs to the petition-for-review stage.

        As opposed to merits briefing after review was granted. The court
        files these before it has a case, so they date from the Court of
        Appeal proceeding rather than from this docket.
        """
        return self in {
            CaBriefDocumentType.PETITION_FOR_REVIEW,
            CaBriefDocumentType.ANSWER_TO_PETITION_FOR_REVIEW,
            CaBriefDocumentType.REPLY_TO_ANSWER_TO_PETITION_FOR_REVIEW,
            CaBriefDocumentType.JOINDER_TO_PETITION,
        }


def _coerce_document_type(value: object) -> object:
    """Map a raw title onto a member, or to None when nothing covers it.

    A field annotated with this can never fail validation on an unrecognised
    value, which matters more than it looks: a pydantic error would make jkent
    store the whole *case* as an unvalidated ``dict`` row, losing every other
    brief on it. A vocabulary the court has outgrown should surface as a coded
    None beside a populated ``document_type_raw`` -- a flag -- not as a lost
    record.
    """
    if isinstance(value, CaBriefDocumentType) or value is None:
        return value
    if isinstance(value, str):
        return CaBriefDocumentType.parse(value)
    return value


CodedBriefDocumentType = Annotated[
    CaBriefDocumentType | None, BeforeValidator(_coerce_document_type)
]
"""``CaBriefDocumentType`` that degrades to None rather than raising."""
