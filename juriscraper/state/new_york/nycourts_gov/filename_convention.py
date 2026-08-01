"""Court-PASS PDF file-name convention: parsing and docket-entry linkage.

The Court of Appeals publishes the naming convention its filers must use
(https://www.nycourts.gov/ctapps/techspecs.htm, effective 2/1/13)::

    title of action-role-name-doctype[-volN].pdf

    SmithvJones-app-Smith-brf.pdf
    SmithvJones-app-Smith-Rec-vol1.pdf
    SmithvJones-amic-ConcernedCitizens-amicbrf.pdf

That gives every ``gvFiles`` row three of the same facts the FILINGS table
carries per row (role, party, document type), which is enough to join the
two: ``NYCourtPassFile`` -> ``NYCourtPassDocketEntry``. The join matters
because only the FILINGS table has ``date_received`` / ``date_due``, and only
``gvFiles`` has the actual PDF — downstream (``DocketEntry`` ->
``RECAPDocument``) needs them attached to each other.

The convention is followed well but not perfectly: filers misspell party
names, glue the volume onto the doctype (``Rec Vol 1``), use soft hyphens,
and pre-2013 filings predate the convention entirely. So the matcher scores
candidate pairs on all three fields and takes the best consistent
assignment rather than requiring an exact parse.

Two structural asymmetries are expected and are *not* match failures:

* **Files with no FILINGS row.** The FILINGS table is a merits-filing
  register, so leave-to-appeal motion papers (``mot``, ``opp``, ``MotforLv``,
  ``OpptoMotforLv``), Appellate Division materials, compendia, and addenda
  routinely have no row. :func:`reconcile_files_and_entries` **synthesizes** an
  entry for each such document, flagged ``inferred_from_file=True``, so that
  every filed document is represented as an entry rather than being dropped.
  Whether a given absence is expected is ``entry_doctype in
  NOT_ON_FILINGS_TABLE``.
* **FILINGS rows with no file.** A row exists once a filing is due or was
  received on paper; the PDF may never be uploaded, which is the norm for
  pending cases. Those entries come back with ``file_indexes == []``.

Court-generated artifacts (``-Decision``, ``-Transcript``, ``-Webcast``) are
excluded from matching up front and get no synthesized entry -- they are the
court's own output, not filings.

Both directions are therefore plain group-bys over the returned pair; see
:func:`reconcile_files_and_entries` for the exact keys.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

__all__ = [
    "COURT_GENERATED_DOCTYPES",
    "DOCTYPE_LABELS",
    "FILING_TYPE_MAP",
    "NOT_ON_FILINGS_TABLE",
    "FilingTypeClassification",
    "ParsedFileName",
    "classify_filing_type",
    "describe_filing",
    "parse_file_name",
    "reconcile_files_and_entries",
]

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

#: Party-role abbreviations. The spec defines ``app`` / ``res`` / ``amic``;
#: the rest are variants filers actually use.
ROLES = {
    "app": "appellant",
    "appellant": "appellant",
    "appellants": "appellant",
    "apps": "appellant",
    "aplt": "appellant",
    "defapp": "appellant",
    "res": "respondent",
    "respondent": "respondent",
    "respondents": "respondent",
    "resp": "respondent",
    "rspt": "respondent",
    "amic": "amicus",
    "amici": "amicus",
    "amicus": "amicus",
    "amicis": "amicus",
    "pet": "petitioner",
    "petitioner": "petitioner",
    "petitioners": "petitioner",
    "lawguardian": "law guardian",
    "lg": "law guardian",
    "afc": "law guardian",
    "attyforchild": "law guardian",
    "at": "law guardian",
    "scjc": "scjc",
    "prose": "pro se",
}

#: Cross-appeals are written as two adjacent role segments
#: (``...-app-res-Name-brf``).
_ROLE_PAIRS = {
    ("appellant", "respondent"): "appellant-respondent",
    ("respondent", "appellant"): "respondent-appellant",
}

#: Canonical document type -> pattern matching the trailing doctype segment.
#: Order matters: the Appellate Division variants must precede their Court of
#: Appeals counterparts or ``ADreplybrf`` matches the plain ``replybrf``
#: pattern. Doctypes prefixed ``_`` are court-generated, not filer
#: submissions. Types marked (spec) appear in the published abbreviation list.
_DOCTYPE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "ssmreplyltrbrf",
        r"^ssmreplyltr(brf|brief)?$|^ssmltrreplybrf$"
        r"|^replyssmltrbrf$|^ssmltrbrfreply$|^ssmreply$"
        r"|^ssmltrreply$|^replyltrbrf$|^ssmreplybrf$",
    ),
    (
        "ssmltrbrf",
        r"^ssm(ltr|letter)?(brf|brief)?$"  # (spec)
        r"|^(ssm)?l(e)?t(te)?r(brf|brief)$|^letterbrief$|^ltr$"
        r"|^(app|res|amic)?ltrbrf$",
    ),
    (
        "brfrspamic",
        r"^brf?rs?p?amic.*$"  # (spec)
        r"|^(brf|brief|resp(onse)?)(in)?(rsp|resp)?(onse)?to?amic.*$"
        r"|^amicresp(onse)?$|^rspamicbrf$",
    ),
    ("amicbrf", r"^amic(us|i)?(ltr)?(brf|brief|br)?$"),  # (spec)
    (
        "adreplybrf",
        r"^ad(app|res|resp|appellant|respondent)?"  # (spec)
        r"repl(y)?(brf|brief|br)$"
        r"|^(app|res|resp)adrepl(y)?(brf|brief)$",
    ),
    (
        "replybrf",
        r"^(app|appellant|res|respondent|pet|petitioner|cross|at)?"
        r"repl(y)?(brf|brief|br)$|^reply$|^replybr$",
    ),  # (spec)
    (
        "suppappdx",
        r"^s(upp|uppl|upplemental)?(app|jt|joint)?"  # (spec)
        r"app(dx|endix|x|pdx)$",
    ),
    ("suppbrf", r"^s(upp|uppl|upplemental)?(brf|brief|br)$"),
    (
        "adappdx",
        r"^ad(app|res|resp|jt|joint)?app(dx|endix|x|px)$"
        r"|^(app|res|resp)adapp(dx|endix|x|px)$",
    ),
    ("adrec", r"^ad(jt|joint)?rec(ord)?$|^(jt|joint)adrec(ord)?$"),  # (spec)
    (
        "adbrf",
        r"^ad(app|res|resp|appellant|respondent|pet|amic)?"  # (spec)
        r"(brf|brief|br)$|^(app|res|resp|amic|at)ad(brf|brief|br)$",
    ),
    (
        "opptomotforlv",
        r"^opp(osition|osn)?to?mot(ion)?"
        r"for(lv|leave|leavetoappeal|lve)$",
    ),
    (
        "motforlv",
        r"^mot(ion)?for"
        r"(lv|leave|leavetoappeal|lve|reargument|reconsideration)$",
    ),
    (
        "opp",
        r"^opp(osition|osn)?(to?mot(ion)?)?$"
        r"|^opposingaffirmation$|^oppaff$",
    ),
    ("mot", r"^mot(ion)?$|^affirmation$|^affidavit$|^supportingpapers$|^aff$"),
    ("compendium", r"^comp(end|endium|endia|endiumofauthorities)?$"),
    ("addendum", r"^add(end|endum|enda)?$"),
    (
        "rec",
        r"^(jt|joint)?rec(ord)?(onappeal)?$"  # (spec)
        r"|^rec(ord)?(jt|joint)?$",
    ),
    (
        "appdx",
        r"^(jt|joint|app|res|resp|pet)?app(dx|endix|x|pdx|end|px)$"
        r"|^app(dx|endix|x|px)(jt|joint)?$",
    ),  # (spec)
    ("exhibits", r"^(trial)?exh(s|ibits)?$"),
    (
        "brf",
        r"^(app|appellant|res|resp|respondent|pet|petitioner"  # (spec)
        r"|cross|prose|at)?(brf|brief|br)$",
    ),
    # court-generated, never a filer submission
    ("_decision", r"^decision(s)?$|^opn$|^opinion$|^memorandum$|^order$"),
    (
        "_transcript",
        r"^transcript(s)?$|^oralargumenttranscript$"
        r"|^technicalrecordingfailure$|^trialtranscript(s)?$",
    ),
    ("_webcast", r"^webcast$|^video$|^audio$"),
)

#: One PDF satisfying two filings (e.g. ``-brf&appdx``).
_COMBINED = re.compile(
    r"^(brf|brief)(and|&|\+)app(dx|endix|x)$"
    r"|^(brf|brief)(and|&|\+)rec(ord)?$"
    r"|^app(dx|endix|x)(and|&|\+)(brf|brief)$"
)

#: ``filing_type`` (FILINGS table) -> (role, canonical doctype).
FILING_TYPE_MAP: dict[str, tuple[str | None, str | None]] = {
    "Appellant Brief": ("appellant", "brf"),
    "Respondent Brief": ("respondent", "brf"),
    "Petitioner Brief": ("petitioner", "brf"),
    "Appellant Reply Brief": ("appellant", "replybrf"),
    "Petitioner Reply Brief": ("petitioner", "replybrf"),
    "Amicus Brief": ("amicus", "amicbrf"),
    "Appellant Appendix": ("appellant", "appdx"),
    "Respondent Appendix": ("respondent", "appdx"),
    "Appellant COA Record": ("appellant", "rec"),
    "Respondent COA Record": ("respondent", "rec"),
    "Appellant Record": ("appellant", "rec"),
    "Record on Review": (None, "rec"),
    "Appellant SSM Letter": ("appellant", "ssmltrbrf"),
    "Respondent SSM Letter": ("respondent", "ssmltrbrf"),
    "Law Guardian SSM letter": ("law guardian", "ssmltrbrf"),
    "Respondent Response to Amicus Brief": ("respondent", "brfrspamic"),
    "Appellant Response to Amicus Brief": ("appellant", "brfrspamic"),
    "AD - Record": (None, "adrec"),
    "AD - Appendix": (None, "adappdx"),
    "AD - Appellant Brief": ("appellant", "adbrf"),
    "AD - Respondent Brief": ("respondent", "adbrf"),
    "AD - Appellant Reply Brief": ("appellant", "adreplybrf"),
    "AD - Respondent Appendix": ("respondent", "adappdx"),
    "Appellant-Respondent Brief": ("appellant-respondent", "brf"),
    "Respondent-Appellant Brief": ("respondent-appellant", "brf"),
    "Appellant-Respondent Reply Brief": ("appellant-respondent", "replybrf"),
    "Respondent-Appellant Reply Brief": ("respondent-appellant", "replybrf"),
    "Law Guardian Brief": ("law guardian", "brf"),
    "Pro Se Supplemental Brief": (None, "suppbrf"),
    "Petitioner Response - Review": ("petitioner", "brf"),
    "Petitioner Response - Suspension": ("petitioner", "brf"),
    "Respondent Response - Suspension": ("respondent", "brf"),
    "SCJC Response - Suspension": ("scjc", "brf"),
    "SCJC Determination": ("scjc", None),
}

#: Filename roles that may legitimately stand in for the entry's role. Filers
#: routinely write ``app`` on a cross-appeal the FILINGS table calls
#: "Appellant-Respondent".
_ROLE_COMPATIBLE: dict[str, tuple[str, ...]] = {
    "appellant-respondent": ("appellant", "respondent"),
    "respondent-appellant": ("respondent", "appellant"),
    "appellant": ("appellant-respondent", "petitioner"),
    "respondent": ("respondent-appellant",),
    "petitioner": ("appellant",),
    "law guardian": ("appellant", "respondent"),
}

#: Doctype pairs close enough to match on when the exact type differs.
_COMPATIBLE_DOCTYPES: frozenset[tuple[str, str]] = frozenset(
    {
        ("brf", "suppbrf"),
        ("appdx", "suppappdx"),
        ("appdx", "adappdx"),
        ("rec", "adrec"),
        ("rec", "appdx"),
        ("ssmltrbrf", "ssmreplyltrbrf"),
        ("brf", "adbrf"),
        ("replybrf", "adreplybrf"),
        ("brf", "amicbrf"),
        ("brf", "brfrspamic"),
        ("brf", "ssmltrbrf"),
        ("appdx", "compendium"),
        ("rec", "compendium"),
        ("appdx", "addendum"),
        ("appdx", "exhibits"),
        ("rec", "exhibits"),
    }
)
_COMPATIBLE_DOCTYPES = frozenset(_COMPATIBLE_DOCTYPES) | frozenset(
    (b, a) for a, b in _COMPATIBLE_DOCTYPES
)

#: Doctypes produced by the court rather than filed by a party. These never
#: correspond to a FILINGS row and never get a synthesized entry.
COURT_GENERATED_DOCTYPES = frozenset({"_decision", "_transcript", "_webcast"})

#: Doctypes the FILINGS table never enumerates. A *filed* document of one of
#: these types having no FILINGS row is expected, not a failed match -- so an
#: entry with ``inferred_from_file=True`` and an ``entry_doctype`` in this set
#: is normal, while one outside it means the table omitted something it
#: usually lists.
NOT_ON_FILINGS_TABLE = frozenset(
    {
        "mot",
        "opp",
        "motforlv",
        "opptomotforlv",
        "compendium",
        "addendum",
        "exhibits",
        "ssmreplyltrbrf",
        "suppappdx",
        "adbrf",
        "adrec",
        "adappdx",
        "adreplybrf",
    }
)

#: Human-readable label per canonical doctype, used to synthesize a
#: ``filing_type`` for documents the FILINGS table never listed. Phrased to
#: read like the court's own vocabulary so real and inferred entries sort and
#: display together.
DOCTYPE_LABELS = {
    "brf": "Brief",
    "replybrf": "Reply Brief",
    "suppbrf": "Supplemental Brief",
    "rec": "Record",
    "appdx": "Appendix",
    "suppappdx": "Supplemental Appendix",
    "amicbrf": "Amicus Brief",
    "brfrspamic": "Response to Amicus Brief",
    "ssmltrbrf": "SSM Letter",
    "ssmreplyltrbrf": "SSM Reply Letter",
    "adbrf": "AD - Brief",
    "adreplybrf": "AD - Reply Brief",
    "adrec": "AD - Record",
    "adappdx": "AD - Appendix",
    "mot": "Motion",
    "motforlv": "Motion for Leave to Appeal",
    "opp": "Opposition",
    "opptomotforlv": "Opposition to Motion for Leave to Appeal",
    "compendium": "Compendium",
    "addendum": "Addendum",
    "exhibits": "Exhibits",
    "_combined": "Brief and Appendix",
    "_decision": "Decision",
    "_transcript": "Oral Argument Transcript",
    "_webcast": "Oral Argument Webcast",
}

#: Display form of each normalized role.
ROLE_LABELS = {
    "appellant": "Appellant",
    "respondent": "Respondent",
    "appellant-respondent": "Appellant-Respondent",
    "respondent-appellant": "Respondent-Appellant",
    "amicus": "Amicus",
    "petitioner": "Petitioner",
    "law guardian": "Law Guardian",
    "scjc": "SCJC",
    "pro se": "Pro Se",
}

#: ``filing_type`` used when the file name yielded no recognizable doctype.
UNCLASSIFIED_FILING_LABEL = "Unclassified Filing"

_ROMAN = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
    "xiii": 13,
    "xiv": 14,
    "xv": 15,
    "xvi": 16,
    "xvii": 17,
    "xviii": 18,
    "xix": 19,
    "xx": 20,
    "xxi": 21,
    "xxii": 22,
    "xxiii": 23,
    "xxiv": 24,
    "xxv": 25,
}

#: ``vol1`` / ``volIV`` / ``part2`` / ``vol1 part2`` / ``vol 3``
_VOLUME = re.compile(
    r"^(?:vol(?:ume)?|v|part|pt)\s*0*(\d+|[ivxl]+)"
    r"(?:\s*(?:part|pt)\s*0*(\d+|[ivxl]+))?$"
)
#: doctype and volume glued into one segment: ``Rec Vol 1``, ``recvol2``
_GLUED_VOLUME = re.compile(
    r"^(?P<doctype>.*?)\s*(?P<volume>(?:vol(?:ume)?|part|pt)\s*0*(?:\d+|[ivxl]+)"
    r"(?:\s*(?:part|pt)\s*0*(?:\d+|[ivxl]+))?)$",
    re.IGNORECASE,
)
#: decorative trailing segments that are not the doctype
_NOISE = re.compile(
    r"^(redacted|revised|rev|corrected|corr|amended|amend|final|sealed"
    r"|unsealed|conf|confidential|replacement|resubmitted|resubmission|copy"
    r"|new|updated|of|and|\d{1,3}|[a-z])$"
)
#: dropped when comparing a filename party token to a FILINGS party string
_PARTY_STOPWORDS = frozenset(
    {
        "llc",
        "inc",
        "co",
        "corp",
        "corporation",
        "the",
        "of",
        "a",
        "an",
        "and",
        "lp",
        "llp",
        "ltd",
        "matter",
        "matterof",
        "people",
        "city",
        "state",
        "new",
        "york",
        "nys",
        "et",
        "al",
        "esq",
        "dba",
        "company",
        "claim",
        "claimof",
    }
)
#: unicode look-alikes for the segment separator, which filers do use
_DASH_LOOKALIKES = "­‐‑‒–—−_"


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedFileName:
    """Components recovered from a Court-PASS PDF file name."""

    raw: str
    title: str | None = None
    """Title of the action, as the filer wrote it (``SmithvJones``)."""
    role: str | None = None
    """Normalized party role (``appellant``, ``respondent``, ``amicus``...)."""
    party: str | None = None
    """Party name segment, un-normalized (``ConcernedCitizens``)."""
    doctype: str | None = None
    """Canonical document type, or ``None`` when the token is unrecognized.
    ``_``-prefixed values are court-generated artifacts."""
    volume: int | None = None
    part: int | None = None
    unparsed_token: str | None = None
    """The trailing segment, when it could not be read as a doctype."""

    @property
    def is_court_generated(self) -> bool:
        """True for ``-Decision`` / ``-Transcript`` / ``-Webcast`` rows."""
        return self.doctype in COURT_GENERATED_DOCTYPES

    @property
    def is_combined(self) -> bool:
        """True when one PDF satisfies two filings (``-brf&appdx``)."""
        return self.doctype == "_combined"


def _clean(value: str | None) -> str:
    """Fold unicode dash look-alikes to ``-`` so segment splitting works."""
    text = unicodedata.normalize("NFKC", value or "")
    for char in _DASH_LOOKALIKES:
        text = text.replace(char, "-")
    return text


def _normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9&]", "", _clean(value).lower())


def _volume_numbers(token: str) -> tuple[int, int | None] | None:
    """``"vol1 part2"`` -> ``(1, 2)``; ``"volIV"`` -> ``(4, None)``."""
    cleaned = re.sub(r"[^a-z0-9 ]", "", _clean(token).lower()).strip()
    match = _VOLUME.match(cleaned)
    if not match:
        return None
    major_raw = match.group(1)
    major = int(major_raw) if major_raw.isdigit() else _ROMAN.get(major_raw)
    if major is None:
        return None
    minor_raw = match.group(2)
    minor = None
    if minor_raw:
        minor = (
            int(minor_raw) if minor_raw.isdigit() else _ROMAN.get(minor_raw)
        )
    return major, minor


def _classify_doctype(token: str) -> str | None:
    normalized = _normalize(token)
    if _COMBINED.match(normalized):
        return "_combined"
    for canonical, pattern in _DOCTYPE_PATTERNS:
        if re.match(pattern, normalized):
            return canonical
    return None


@dataclass(frozen=True)
class FilingTypeClassification:
    """The ``(role, doctype)`` reading of a FILINGS-table ``filing_type``.

    ``recognized`` is the field that matters for drift: it separates "the
    site used a ``filing_type`` we have never seen" from "we know this type
    and it legitimately has no document type". Both come back with
    ``doctype is None``, so a bare tuple cannot tell them apart --
    ``SCJC Determination`` is a known type that maps to no doctype.
    """

    raw: str | None
    role: str | None = None
    doctype: str | None = None
    recognized: bool = False


def classify_filing_type(
    raw_filing_type: str | None,
) -> FilingTypeClassification:
    """Read a FILINGS ``filing_type`` string as ``(role, doctype)``.

    An unrecognized type is not an error -- it still participates in matching,
    just without role/doctype constraints -- but it should be noticed, since it
    means Court-PASS has added a filing kind that ``FILING_TYPE_MAP`` predates.
    """
    if raw_filing_type is None:
        return FilingTypeClassification(raw=None)
    mapped = FILING_TYPE_MAP.get(raw_filing_type)
    if mapped is None:
        return FilingTypeClassification(raw=raw_filing_type, recognized=False)
    role, doctype = mapped
    return FilingTypeClassification(
        raw=raw_filing_type, role=role, doctype=doctype, recognized=True
    )


def describe_filing(role: str | None, doctype: str | None) -> str:
    """Compose a FILINGS-style label, for entries the table never carried.

    ``("appellant", "motforlv")`` -> ``"Appellant Motion for Leave to Appeal"``.
    """
    doctype_label = DOCTYPE_LABELS.get(doctype or "")
    if doctype_label is None:
        return UNCLASSIFIED_FILING_LABEL
    role_label = ROLE_LABELS.get(role or "")
    if role_label is None:
        return doctype_label
    # "Amicus" + "Amicus Brief" reads badly; the doctype already says it
    if doctype_label.startswith(role_label):
        return doctype_label
    # keep the court's "AD - X" prefix in front: "AD - Appellant Brief"
    if doctype_label.startswith("AD - "):
        return f"AD - {role_label} {doctype_label[len('AD - ') :]}"
    return f"{role_label} {doctype_label}"


def parse_file_name(file_name: str) -> ParsedFileName:
    """Split a Court-PASS file name into its convention components.

    Reads right-to-left: trailing volume/noise segments are consumed first,
    then the doctype, then the remaining left segments are split at the role
    into title and party. Any field the filer omitted or mangled comes back
    ``None`` rather than raising -- roughly 8% of the historical corpus has an
    unrecognizable doctype token and pre-2013 filings predate the convention.
    """
    stem = re.sub(
        r"\.pdf$", "", _clean(file_name).strip(), flags=re.IGNORECASE
    )
    segments = stem.split("-")

    volume: int | None = None
    part: int | None = None
    index = len(segments) - 1
    while index >= 0:
        token = _normalize(segments[index])
        numbers = _volume_numbers(segments[index])
        if numbers and volume is None:
            volume, part = numbers
            index -= 1
            continue
        if not token or _NOISE.match(token):
            index -= 1
            continue
        break

    doctype: str | None = None
    unparsed_token: str | None = None
    if index >= 0:
        doctype = _classify_doctype(segments[index])
        if doctype is None:
            # the volume may be glued onto the doctype: "Rec Vol 1"
            glued = _GLUED_VOLUME.match(_clean(segments[index]).strip())
            if glued and glued.group("doctype"):
                doctype = _classify_doctype(glued.group("doctype"))
                if doctype is not None and volume is None:
                    numbers = _volume_numbers(glued.group("volume"))
                    if numbers:
                        volume, part = numbers
        if doctype is not None:
            index -= 1
        else:
            unparsed_token = segments[index].strip()[:40] or None

    remaining = [seg for seg in segments[: index + 1] if seg.strip()]
    common = {
        "raw": file_name,
        "doctype": doctype,
        "volume": volume,
        "part": part,
        "unparsed_token": unparsed_token,
    }
    for position, segment in enumerate(remaining):
        role = ROLES.get(_normalize(segment))
        if role is None:
            continue
        # a cross-appeal writes both roles: "...-app-res-Name-brf"
        if position + 1 < len(remaining):
            next_role = ROLES.get(_normalize(remaining[position + 1]))
            pair = _ROLE_PAIRS.get((role, next_role)) if next_role else None
            if pair is not None:
                return ParsedFileName(
                    title="-".join(remaining[:position]) or None,
                    role=pair,
                    party="-".join(remaining[position + 2 :]) or None,
                    **common,
                )
        return ParsedFileName(
            title="-".join(remaining[:position]) or None,
            role=role,
            party="-".join(remaining[position + 1 :]) or None,
            **common,
        )
    return ParsedFileName(title="-".join(remaining) or None, **common)


# --------------------------------------------------------------------------
# Linking
# --------------------------------------------------------------------------


def _party_words(value: str | None) -> set[str]:
    """Significant word tokens, splitting the CamelCase filers use."""
    return {
        word.lower()
        for word in re.findall(
            r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+", _clean(value)
        )
        if len(word) > 1 and word.lower() not in _PARTY_STOPWORDS
    }


def _party_score(file_party: str | None, entry_party: str | None) -> float:
    """0..1 agreement between a filename party token and a FILINGS party.

    The filename carries a squashed short name (``111West57thInvestmentLLC``)
    while FILINGS carries the full legal name plus a role hint
    (``111 West 57th Investment LLC (A)``), so containment and word overlap
    both matter.
    """
    left = _normalize(file_party)
    right = re.sub(r"\(.\)$", "", _normalize(entry_party))
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if len(left) >= 4 and (left in right or right in left):
        return 0.9
    left_words = _party_words(file_party)
    right_words = _party_words(entry_party)
    if not left_words or not right_words:
        return 0.0
    overlap = len(left_words & right_words)
    return overlap / min(len(left_words), len(right_words))


@dataclass
class _Candidate:
    score: float
    party_score: float
    doctype_exact: bool
    role_exact: bool
    entry_index: int
    group_index: int


@dataclass
class _DocumentGroup:
    """One logical document: a single PDF, or a set of volumes/parts."""

    parsed: ParsedFileName
    file_indexes: list[int] = field(default_factory=list)


def _group_volumes(
    parsed_files: list[tuple[int, ParsedFileName]],
) -> list[_DocumentGroup]:
    """Collapse volumes/parts of one logical document into one group.

    A five-volume record is five ``gvFiles`` rows but one FILINGS entry, so
    the volumes must be grouped before matching or four of them look like
    unexplained surplus.
    """
    groups: dict[tuple, _DocumentGroup] = {}
    order: list[tuple] = []
    for file_index, parsed in parsed_files:
        key = (
            parsed.role,
            _normalize(parsed.party),
            parsed.doctype,
            parsed.unparsed_token,
        )
        if key not in groups:
            groups[key] = _DocumentGroup(parsed=parsed)
            order.append(key)
        groups[key].file_indexes.append(file_index)

    result: list[_DocumentGroup] = []
    for key in order:
        group = groups[key]
        members = group.file_indexes
        volumed = sum(
            1
            for i in members
            if next(p for j, p in parsed_files if j == i).volume is not None
        )
        # only collapse when it really looks like a volume set: a repeated
        # (role, party, doctype) with no volume markers is duplicate uploads,
        # which should stay separate documents
        if len(members) > 1 and volumed < len(members) - 1:
            result.extend(
                _DocumentGroup(
                    parsed=next(p for j, p in parsed_files if j == i),
                    file_indexes=[i],
                )
                for i in members
            )
        else:
            result.append(group)
    return result


def _confidence(candidate: _Candidate) -> str:
    if (
        candidate.doctype_exact
        and candidate.role_exact
        and candidate.party_score >= 0.9
    ):
        return "exact"
    if candidate.doctype_exact and (
        candidate.role_exact or candidate.party_score >= 0.9
    ):
        return "strong"
    return "weak"


def reconcile_files_and_entries(
    files: list[dict],
    docket_entries: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Join ``gvFiles`` rows to FILINGS rows in both directions.

    Returns ``(files, entries)`` -- new dicts, inputs are never mutated.

    Each **file** gains the convention components (``doc_role``,
    ``doc_party``, ``doc_type``, ``volume``, ``part``), its logical-document
    id (``document_group``), a ``link_status``, and -- when it belongs to an
    entry -- ``docket_entry_index``, ``match_confidence``, and the
    ``date_received`` / ``date_due`` only the FILINGS table carries.

    Each **entry** gains ``entry_index`` (so ``(docket_number, entry_index)``
    is a stable composite key for the file -> entry join), the
    ``raw_filing_type`` / ``entry_role`` / ``entry_doctype`` /
    ``filing_type_recognized`` classification, ``file_indexes`` listing its
    zero or more files, and ``inferred_from_file``.

    Entries are returned in two blocks. The real FILINGS rows come first, at
    their original indexes, followed by one **synthesized** entry per document
    group that no FILINGS row claimed -- each carrying
    ``inferred_from_file=True``, a ``filing_type`` composed from the file
    name, and ``raw_filing_type=None`` because no table row said it. Real
    indexes therefore never shift, and every filer-submitted file ends up
    under exactly one entry, which is what makes each of these a plain
    group-by:

    * FILINGS rows with no document -> ``file_indexes == []``
    * documents with no FILINGS row -> ``inferred_from_file is True``
    * several files in one such entry -> ``len(file_indexes) > 1``
    * whether those files are fetchable -> join to ``available``
    * whether the absence is expected -> ``entry_doctype`` in
      :data:`NOT_ON_FILINGS_TABLE`

    Court-generated files (``-Decision``, ``-Transcript``, ``-Webcast``) are
    deliberately *not* given synthesized entries: they are the court's own
    output, never a filing, and the FILINGS table is a filing register. They
    come back with ``link_status='court_generated'`` and no entry.
    """
    parsed_all = [
        (index, parse_file_name(file_row.get("file_name") or ""))
        for index, file_row in enumerate(files)
    ]
    # every row gets the full key set, so callers never have to distinguish
    # "no match" from "key absent"
    linked = [dict(file_row) for file_row in files]
    for index, parsed in parsed_all:
        linked[index].update(
            doc_role=parsed.role,
            doc_party=parsed.party,
            doc_type=parsed.doctype,
            volume=parsed.volume,
            part=parsed.part,
            document_group=None,
            docket_entry_index=None,
            match_confidence=None,
            date_received=None,
            date_due=None,
            link_status=(
                "court_generated" if parsed.is_court_generated else "unlinked"
            ),
        )

    # ``file_index`` is the gvFiles row number, which is NOT the list position
    # when the parser skipped a malformed row -- the join key must be the
    # former, while ``linked`` is addressed by the latter.
    def join_keys(positions: list[int]) -> list[int]:
        return [
            files[position].get("file_index", position)
            for position in positions
        ]

    classifications = [
        classify_filing_type(entry.get("filing_type"))
        for entry in docket_entries
    ]
    reconciled_entries = [
        {
            **entry,
            "entry_index": entry_index,
            "raw_filing_type": entry.get("filing_type"),
            "entry_role": classification.role,
            "entry_doctype": classification.doctype,
            "filing_type_recognized": classification.recognized,
            "inferred_from_file": False,
            "file_indexes": [],
        }
        for entry_index, (entry, classification) in enumerate(
            zip(docket_entries, classifications, strict=True)
        )
    ]

    filer_files = [
        (index, parsed)
        for index, parsed in parsed_all
        if not parsed.is_court_generated
    ]
    if not filer_files:
        return linked, reconciled_entries

    groups = _group_volumes(filer_files)
    for group_index, group in enumerate(groups):
        for file_index in group.file_indexes:
            linked[file_index]["document_group"] = group_index

    candidates: list[_Candidate] = []
    for entry_index, classification in enumerate(classifications):
        entry = docket_entries[entry_index]
        entry_role, entry_doctype = classification.role, classification.doctype
        for group_index, group in enumerate(groups):
            parsed = group.parsed
            doctype_exact = False
            if entry_doctype and parsed.doctype and not parsed.is_combined:
                if parsed.doctype == entry_doctype:
                    doctype_score, doctype_exact = 2.0, True
                elif (entry_doctype, parsed.doctype) in _COMPATIBLE_DOCTYPES:
                    doctype_score = 0.8
                else:
                    continue
            else:
                # unrecognized doctype, or one PDF covering two filings
                doctype_score = 0.4

            role_exact = False
            role_score = 0.0
            if entry_role and parsed.role:
                if parsed.role == entry_role:
                    role_score, role_exact = 1.0, True
                elif parsed.role in _ROLE_COMPATIBLE.get(entry_role, ()):
                    role_score = 0.4
                else:
                    continue

            party_score = _party_score(parsed.party, entry.get("party"))
            candidates.append(
                _Candidate(
                    score=doctype_score + role_score + 2.0 * party_score,
                    party_score=party_score,
                    doctype_exact=doctype_exact,
                    role_exact=role_exact,
                    entry_index=entry_index,
                    group_index=group_index,
                )
            )

    # deterministic best-first: highest score, then source order
    candidates.sort(key=lambda c: (-c.score, c.entry_index, c.group_index))
    claimed_entries: set[int] = set()
    claimed_groups: set[int] = set()
    for candidate in candidates:
        if (
            candidate.entry_index in claimed_entries
            or candidate.group_index in claimed_groups
        ):
            continue
        claimed_entries.add(candidate.entry_index)
        claimed_groups.add(candidate.group_index)

        entry = reconciled_entries[candidate.entry_index]
        confidence = _confidence(candidate)
        positions = groups[candidate.group_index].file_indexes
        entry["file_indexes"] = join_keys(positions)
        for file_index in positions:
            linked[file_index].update(
                docket_entry_index=candidate.entry_index,
                match_confidence=confidence,
                date_received=entry.get("date_received"),
                date_due=entry.get("date_due"),
                link_status="matched",
            )

    # Synthesize an entry per document group no FILINGS row claimed, so every
    # filer-submitted file hangs off exactly one entry. Appended after the
    # real rows, so real entry_index values stay put.
    for group_index, group in enumerate(groups):
        if group_index in claimed_groups:
            continue
        parsed = group.parsed
        entry_index = len(reconciled_entries)
        reconciled_entries.append(
            {
                "filing_type": describe_filing(parsed.role, parsed.doctype),
                "party": parsed.party,
                "date_due": None,
                "date_received": None,
                "entry_index": entry_index,
                # nothing on the page said this; it is read off the file name
                "raw_filing_type": None,
                "entry_role": parsed.role,
                "entry_doctype": parsed.doctype,
                "filing_type_recognized": parsed.doctype is not None,
                "inferred_from_file": True,
                "file_indexes": join_keys(group.file_indexes),
            }
        )
        for file_index in group.file_indexes:
            linked[file_index].update(
                docket_entry_index=entry_index,
                match_confidence=None,
                link_status="inferred",
            )
    return linked, reconciled_entries
