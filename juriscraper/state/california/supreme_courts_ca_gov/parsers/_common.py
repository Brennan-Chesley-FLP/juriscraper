"""Shared helpers for the California Supreme Court briefs page parsers."""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import unquote, urlsplit

from juriscraper.state.california.supreme_courts_ca_gov.models import (
    DOCKET_PREFIX_COURTS,
    CalSupremeSessionType,
)

_MONTHS: dict[str, int] = {
    name: number
    for number, name in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}

#: What every session title ends with, e.g. "Oral Argument Cases",
#: "Oral Arguments Cases", "Oral Argument Briefs". The court has used all
#: three spellings; none of them carry information.
_SESSION_TRAILER_RE = re.compile(
    r"\s*Oral\s+Arguments?\s+(?:Cases?|Briefs?)\s*$", re.IGNORECASE
)

#: The two session kinds the court names in the title.
_SESSION_KIND_RE = re.compile(
    r"\s*(Special|Outreach)\s+Session\s*", re.IGNORECASE
)

#: A parenthetical the court appends to a few titles to say which half-days
#: the session covered ("(October 6 Afternoon Session and October 7
#: Session)"). It restates the dates already in the title.
_TITLE_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")

#: A month name or a bare number inside a session title's date span.
_DATE_TOKEN_RE = re.compile(r"([A-Za-z]+)|(\d{1,2})")

#: Words the court joins days with, which carry no date of their own.
#: Any *other* word inside a date span is unrecognised, and fails the parse
#: rather than being skipped over.
_DATE_JOINERS = frozenset({"and", "to", "through", "thru"})

#: "Filed on May 10, 2024" -- the text beside every brief link.
_FILED_ON_RE = re.compile(
    r"Filed\s+on\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", re.IGNORECASE
)

#: A case heading: the case number, then optionally a separator and the
#: caption. The separator is a hyphen, an en/em dash, or (on one 2012
#: heading) nothing at all.
_CASE_HEADING_RE = re.compile(
    r"^(?P<number>[A-Z]\d{6})\s*(?:[-\u2010-\u2015]+\s*)?(?P<name>.*)$"
)

#: A California appellate case number anywhere in a note, for the
#: "Consolidated case with S289441 - G. (A.) ON H.C." parentheticals.
_CASE_NUMBER_RE = re.compile(r"\b([A-Z]\d{6})\b")

#: The docket number the court builds each PDF filename around, e.g.
#: "4-115-s279242-resps-answer-pet-rev-042423.pdf" or the pre-2013
#: "2. S176943 Real Party's in Interest Answer to Petition for Review
#: 102309.pdf". Used only to recover a case number the heading failed to
#: state.
_FILENAME_DOCKET_RE = re.compile(r"(?:^|[-.\s])([A-Za-z]\d{6})(?:[-.\s]|$)")

#: "Amicus Curiae Brief of <whoever filed it>" -- the court's title form for
#: an amicus filing, where the filer follows the document kind instead of
#: preceding it.
_AMICUS_TITLE_RE = re.compile(
    r"^(?P<doc>Amicus\s+Curiae\s+Brief)\s+of\s+(?P<filer>.+)$", re.IGNORECASE
)

#: "<Filer>'s <Document>" -- the dominant form (7,972 of 11,478 titles).
#: The filer part may not contain a comma, which keeps the apostrophe in
#: "Respondent, Workers' Compensation Appeals Board, ..." from splitting a
#: title that is really the comma form below.
_POSSESSIVE_TITLE_RE = re.compile(
    r"^(?P<filer>[^,]{2,60}?)['’]s?\s+(?P<doc>\S.*)$"
)

#: The party roles the court opens a comma-form title with,
#: "Real Party in Interest, The People, Answer Brief on the Merits".
#:
#: Singular forms only: :func:`_role_phrase_matches` depluralises before
#: looking a phrase up, and splits a conjoined role ("Intervener and
#: Respondent") into its conjuncts first, so the set stays the list of roles
#: the court actually has rather than the cross-product of their spellings.
_COMMA_FORM_ROLES = frozenset(
    {
        "appellant",
        "respondent",
        "petitioner",
        "real party in interest",
        "non-title respondent",
        "defendant",
        "plaintiff",
        "intervener",
        "intervenor",
        "applicant",
        "amicus curiae",
        "referee",
        # Roles the 2026-10-17 data audit found the court using in the
        # comma form, which the original set did not list -- 19 titles.
        "pub/depublication requestor",
        "publication/depublication requestor",
        "interested entities/parties",
        "overview party",
        "non-party movant",
        "attorney general",
        "presiding justice",
        "minor",
    }
)

#: Misspellings of a role the court has published. Each is the court's own
#: typo in a brief title, mapped to the role it meant; correcting them here
#: keeps 5 titles from being filed under a filer of ``None``.
_ROLE_TYPOS: dict[str, str] = {
    "real pary in interest": "real party in interest",
    "applellant": "appellant",
    "resp": "respondent",
    "resps": "respondent",
}

#: What the court joins two roles with in a single filer phrase --
#: "Intervener and Respondent", "Defendant and Appellant". Both conjuncts
#: must be roles for the phrase to be one.
_ROLE_CONJUNCTION = " and "

#: Irregular plurals of the role phrases above.
_ROLE_PLURALS: dict[str, str] = {
    "real parties in interest": "real party in interest",
    "parties": "party",
    "attorneys general": "attorney general",
}


def _singular_role(phrase: str) -> str:
    """One role phrase, casefolded and reduced to the spelling the set holds.

    Applies, in order: the court's known typos, the irregular plurals, then a
    bare trailing ``s`` -- but only when dropping it lands on a real role, so
    "Interested Entities/Parties" is not mangled into something unlisted.
    """
    normalised = " ".join(phrase.split()).casefold()
    normalised = _ROLE_TYPOS.get(normalised, normalised)
    normalised = _ROLE_PLURALS.get(normalised, normalised)
    if normalised not in _COMMA_FORM_ROLES and normalised.endswith("s"):
        depluralised = normalised[:-1]
        if depluralised in _COMMA_FORM_ROLES:
            return depluralised
    return normalised


def _role_phrase_matches(phrase: str) -> bool:
    """Whether a title's leading chunk names one or more party roles.

    ``"Intervener and Respondent"`` and ``"Non-Title Respondents"`` do;
    ``"Declaration of Charles H. Bell"`` and ``"Response to June 15"`` do
    not. Deliberately strict: anything that is not a listed role leaves the
    title unsplit, which costs a ``filed_by`` but never invents one.
    """
    conjuncts = phrase.casefold().split(_ROLE_CONJUNCTION)
    return bool(phrase) and all(
        _singular_role(conjunct) in _COMMA_FORM_ROLES for conjunct in conjuncts
    )


#: Characters that can only come out of reading a UTF-8 lead byte through
#: cp1252: the C2-F4 range, re-encoded. Text with none of these cannot be
#: double-encoded, which skips the round trip below for 11,493 of the
#: corpus's 11,506 brief titles.
_MOJIBAKE_LEADS = re.compile("[\u00c2-\u00df\u00e0-\u00ef\u00f0-\u00f4]")


def fix_mojibake(text: str) -> str:
    """Undo one round of UTF-8-read-as-cp1252, when that is what happened.

    13 brief titles in the 2010-2026 corpus are double-encoded *on the court's
    own server* -- ``"Amicus Curiae Brief of George Gasc\u00c3\u00b3n"``, ``"... Death
    Penalty \u00e2\u20ac\u201c No on Prop. 62"``. The response is valid UTF-8 and declares
    ``charset=UTF-8``, so nothing in the fetch is wrong; the court encoded the
    text twice before writing it out. Re-encoding through cp1252 and decoding
    as UTF-8 recovers the character the court meant.

    The round trip is its own filter, and a strict one: text that is *not*
    double-encoded almost never survives it. ``"Gasc\u00f3n"`` spelled correctly
    encodes to ``b"Gasc\xf3n"``, which is not valid UTF-8; an em dash encodes
    to ``b"\x97"``, a bare continuation byte. Both raise, and the original
    comes back untouched. Only a string whose bytes already spell a UTF-8
    sequence -- which is what double encoding produces -- round-trips
    cleanly.
    """
    if not _MOJIBAKE_LEADS.search(text):
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return text if not repaired or "\ufffd" in repaired else repaired


def collapse_ws(text: str | None) -> str | None:
    """Collapse whitespace runs to single spaces; ``None`` if nothing is left.

    The Drupal templates indent every value, so a bare ``.strip()`` leaves the
    page's layout inside multi-line values such as a case heading that wrapped.
    Double-encoded text is repaired here too (see :func:`fix_mojibake`), so
    every value the parsers read passes through the same single point.
    """
    if text is None:
        return None
    collapsed = " ".join(text.split())
    return fix_mojibake(collapsed) if collapsed else None


def parse_session_title(
    title: str,
) -> tuple[date, date, CalSupremeSessionType] | None:
    """A session title as ``(first day, last day, kind)``.

    The court writes the span a dozen ways -- ``"January 27, 2010"``,
    ``"May 25 - 27, 2010"``, ``"June 2 and 3, 2026"``, ``"May 6 & 7, 2026"``,
    ``"November 8, 9, and 10, 2011"``, ``"May 31 - June 3, 2011"`` -- so the
    dates are read as a token stream (month names latch until the next one)
    rather than matched against a list of formats. Only the first and last
    day are returned: whether the separator meant a range or an enumeration
    does not change them, and the page never says which day inside the span a
    given case was argued.

    Returns ``None`` when the title carries no parseable date, which is the
    signal that the index's shape has changed.
    """
    remainder = _TITLE_PARENTHETICAL_RE.sub("", title.strip())
    remainder = _SESSION_TRAILER_RE.sub("", remainder).strip()

    kind = CalSupremeSessionType.REGULAR
    kind_match = _SESSION_KIND_RE.search(remainder)
    if kind_match is not None:
        kind = CalSupremeSessionType(kind_match.group(1).lower())
        remainder = _SESSION_KIND_RE.sub(" ", remainder).strip()

    remainder = remainder.strip(" ,")
    year_match = re.search(r"(\d{4})\s*$", remainder)
    if year_match is None:
        return None
    year = int(year_match.group(1))

    days: list[date] = []
    month: int | None = None
    for token in _DATE_TOKEN_RE.finditer(remainder[: year_match.start()]):
        word, number = token.groups()
        if word is not None:
            named_month = _MONTHS.get(word.capitalize())
            if named_month is None:
                if word.casefold() in _DATE_JOINERS:
                    continue
                return None
            month = named_month
        elif month is None:
            return None
        else:
            try:
                days.append(date(year, month, int(number)))
            except ValueError:
                return None
    if not days:
        return None
    return min(days), max(days), kind


def parse_filed_on(text: str | None) -> date | None:
    """The date out of a ``"Filed on May 10, 2024"`` label, or ``None``."""
    if not text:
        return None
    match = _FILED_ON_RE.search(text)
    if match is None:
        return None
    month = _MONTHS.get(match.group(1).capitalize())
    if month is None:
        return None
    try:
        return date(
            year=int(match.group(3)), month=month, day=int(match.group(2))
        )
    except ValueError:
        return None


def split_case_heading(heading: str) -> tuple[str | None, str | None]:
    """A case heading as ``(case number, caption)``.

    ``"S280572 - IN RE Ja.O."`` -> ``("S280572", "IN RE Ja.O.")``. Both come
    back ``None`` for a heading that states no case number at all -- the
    corpus has one, reading ``"NO CASE ASSIGNED"``.
    """
    collapsed = collapse_ws(heading)
    if collapsed is None:
        return None, None
    match = _CASE_HEADING_RE.match(collapsed)
    if match is None:
        return None, None
    return match.group("number"), collapse_ws(match.group("name"))


def court_for_docket_number(docket_number: str) -> str | None:
    """The CourtListener court id a California case number belongs to.

    ``None`` for a prefix outside :data:`DOCKET_PREFIX_COURTS`, which is the
    signal to widen that map rather than to file the case under the wrong
    court.
    """
    if not docket_number:
        return None
    return DOCKET_PREFIX_COURTS.get(docket_number[0].upper())


def docket_number_from_filename(filename: str) -> str | None:
    """The case number a brief's filename is built around, upper-cased.

    The court names every PDF after the case it belongs to, which is what
    recovers the case when the heading above the list does not state one.
    """
    match = _FILENAME_DOCKET_RE.search(filename)
    return match.group(1).upper() if match else None


#: The Pantheon staging host the court left in 27 hand-authored brief links.
#: It serves the same files as the canonical host, but a scrape should not
#: depend on the court's staging box staying up.
_STAGING_HOST = "live-jcc-supremecourt.pantheonsite.io"
_CANONICAL_HOST = "supreme.courts.ca.gov"


def canonical_brief_url(url: str | None) -> str | None:
    """A brief URL with the court's staging host rewritten to the live one.

    Six session pages carry hand-authored case blocks whose links point at
    ``live-jcc-supremecourt.pantheonsite.io``. Both hosts serve the identical
    file; the path is untouched, only the host is replaced.
    """
    if not url:
        return None
    return url.replace(f"//{_STAGING_HOST}/", f"//{_CANONICAL_HOST}/", 1)


def filename_from_url(url: str) -> str:
    """The URL-decoded basename of a brief's URL.

    Pre-2013 filenames are percent-encoded spaces and apostrophes
    (``"2.%20S176943%20Real%20Party%27s..."``), so the raw path segment is
    not the name the court gave the file.
    """
    return unquote(urlsplit(url).path.rsplit("/", 1)[-1])


def consolidated_case_numbers(
    note: str | None, exclude: str | None
) -> list[str]:
    """Case numbers a heading note names as consolidated with this case.

    Only notes that say so are read -- a pro tempore note names justices, not
    cases -- and ``exclude`` (the case's own number) is dropped so a note that
    restates it does not consolidate the case with itself.
    """
    if not note or "consolidat" not in note.casefold():
        return []
    found = [
        number
        for number in _CASE_NUMBER_RE.findall(note)
        if number != (exclude or "")
    ]
    return list(dict.fromkeys(found))


def split_brief_title(title: str) -> tuple[str | None, str | None]:
    """A brief's link text as ``(filer, document type)``.

    The court writes these three ways, in descending frequency::

        Appellant's Opening Brief on the Merits        -> possessive
        Amicus Curiae Brief of Consumer Attorneys ...  -> amicus
        Real Party in Interest, The People, Answer ... -> comma form

    Anything else -- notably the bare pre-2011 titles like ``"Petition for
    Review"``, and one-word entries like ``"Order"`` -- comes back as
    ``(None, the whole title)``: the document kind is stated, the filer is
    not. ``(None, None)`` only for an empty title.
    """
    collapsed = collapse_ws(title)
    if collapsed is None:
        return None, None

    amicus = _AMICUS_TITLE_RE.match(collapsed)
    if amicus is not None:
        return (
            collapse_ws(amicus.group("filer")),
            collapse_ws(amicus.group("doc")),
        )

    possessive = _POSSESSIVE_TITLE_RE.match(collapsed)
    if possessive is not None:
        filer = possessive.group("filer")
        document = possessive.group("doc")
        # The pre-2013 listings misplace the apostrophe on this one role,
        # writing "Real Party's in Interest Answer Brief on the Merits". Put
        # the role back together rather than filing 38 briefs under a filer of
        # "Real Party" and a document type starting "in Interest".
        trailing_role = re.match(
            r"^(in Interest)\s+(\S.*)$", document, re.IGNORECASE
        )
        if trailing_role is not None:
            filer = f"{filer} {trailing_role.group(1)}"
            document = trailing_role.group(2)
        return collapse_ws(filer), collapse_ws(document)

    parts = [part.strip() for part in collapsed.split(",")]
    if len(parts) >= 3 and _role_phrase_matches(parts[0]):
        return collapse_ws(", ".join(parts[:-1])), collapse_ws(parts[-1])

    # "Real Parties in Interest - Preliminary Opposition": the same filer-then-
    # document order, written with a dash instead of commas. 6 titles, all on
    # the May 2016 page. Only a leading role phrase qualifies, so a document
    # title that merely contains " - " is left whole.
    dashed = collapsed.split(" - ", 1)
    if len(dashed) == 2 and _role_phrase_matches(dashed[0]):
        return collapse_ws(dashed[0]), collapse_ws(dashed[1])

    return None, collapsed
