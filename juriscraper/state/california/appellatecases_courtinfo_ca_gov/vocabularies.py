"""The vocabularies appellatecases.courtinfo.ca.gov publishes.

Each is a ``str`` enum whose members' values are what the site itself prints,
so a member compares and serializes as that string. ``None`` -- never a member
-- is what the scraper reports when the court stated nothing, or when it stated
something no member covers; the verbatim text is always kept in the field's
``*_raw`` sibling, so nothing is lost either way.

Codes 0 and 999 are reserved and never belong to a member, so a consumer
storing codes can tell "the court stated nothing" from "the court stated
something this vocabulary does not cover".

Adding to these is expected. A value no member covers is reported as
unrecognized rather than guessed at, which is the signal that the site has
started publishing something new.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BeforeValidator

__all__ = ["CaPublicationStatus", "CodedPublicationStatus", "CourtVocabulary"]


class CourtVocabulary(str, Enum):
    """Base for the vocabularies below.

    A member is the string the site prints, plus ``code`` -- a small integer
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

    @classmethod
    def parse(cls, value: str | None) -> CourtVocabulary | None:
        """Return the member for ``value``, or None when nothing covers it.

        Matching is exact on the site's own string, then case-insensitive --
        the site is consistent about casing in this field, but a vocabulary
        that silently drops a value on a capitalisation change is worse than
        one that tolerates it.
        """
        if not value:
            return None
        text = value.strip()
        try:
            return cls(text)
        except ValueError:
            pass
        folded = text.casefold()
        for member in cls:
            if member.value.casefold() == folded:
                return member
        return None


class CaPublicationStatus(CourtVocabulary):
    """The Publication Status a Court of Appeal disposition states.

    Court of Appeal only: the Supreme Court has no Publication Status field at
    all (null on all 296,776 of its dockets in the August 2026 sweep), and its
    opinions are published as a matter of course.

    The eight members are the complete set observed over 350,258 Court of
    Appeal dispositions across all eight districts, with an unseen-value
    estimate of 0 -- every value occurs at least 39 times, so there is no
    singleton tail suggesting the vocabulary is still open.

    The values are compositional on two axes, exposed as ``by_the_court`` (who
    issued it) and ``published``/``partial`` (what became of it), so a consumer
    can ask the question it actually has rather than match on eight strings.
    """

    SIGNED_UNPUBLISHED = "Signed Unpublished", 1, "Signed, unpublished"
    SIGNED_PUBLISHED = "Signed Published", 2, "Signed, published"
    BY_THE_COURT_UNPUBLISHED = (
        "By the Court - Unpublished",
        3,
        "By the court, unpublished",
    )
    SIGNED_PARTIAL_PUBLISHED = (
        "Signed Partial Published",
        4,
        "Signed, partially published",
    )
    ORDERED_PUBLISHED = "Ordered Published", 5, "Ordered published"
    DEPUBLISHED = (
        "Depublished - Review Granted or By Order",
        6,
        "Depublished (review granted or by order)",
    )
    BY_THE_COURT_PUBLISHED = (
        "By the Court - Published",
        7,
        "By the court, published",
    )
    BY_THE_COURT_PARTIAL_PUBLISHED = (
        "By the Court - Partial Published",
        8,
        "By the court, partially published",
    )

    @property
    def published(self) -> bool:
        """Whether the opinion is published, in whole or in part.

        ``DEPUBLISHED`` is False: a publication later withdrawn is not a
        published opinion, and the string contains "published" only by
        accident of spelling.
        """
        return self in {
            CaPublicationStatus.SIGNED_PUBLISHED,
            CaPublicationStatus.SIGNED_PARTIAL_PUBLISHED,
            CaPublicationStatus.ORDERED_PUBLISHED,
            CaPublicationStatus.BY_THE_COURT_PUBLISHED,
            CaPublicationStatus.BY_THE_COURT_PARTIAL_PUBLISHED,
        }

    @property
    def partial(self) -> bool:
        """Whether only part of the opinion is published."""
        return self in {
            CaPublicationStatus.SIGNED_PARTIAL_PUBLISHED,
            CaPublicationStatus.BY_THE_COURT_PARTIAL_PUBLISHED,
        }

    @property
    def by_the_court(self) -> bool:
        """Whether the court issued it per curiam rather than over a signature."""
        return self in {
            CaPublicationStatus.BY_THE_COURT_UNPUBLISHED,
            CaPublicationStatus.BY_THE_COURT_PUBLISHED,
            CaPublicationStatus.BY_THE_COURT_PARTIAL_PUBLISHED,
        }


def _coerce_publication_status(value: object) -> object:
    """Map a raw site string onto a member, or to None when nothing covers it.

    A field annotated with this can never fail validation on an unrecognised
    value, which matters more than it looks: a pydantic error would make jkent
    store the whole docket as an unvalidated ``dict`` row, losing every other
    field on it. A vocabulary the site has outgrown should surface as a coded
    None beside a populated ``*_raw`` -- a flag -- not as a lost record.
    """
    if isinstance(value, CaPublicationStatus) or value is None:
        return value
    if isinstance(value, str):
        return CaPublicationStatus.parse(value)
    return value


CodedPublicationStatus = Annotated[
    CaPublicationStatus | None, BeforeValidator(_coerce_publication_status)
]
"""``CaPublicationStatus`` that degrades to None rather than raising."""
