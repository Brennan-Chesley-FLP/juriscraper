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
excluded from *matching* up front -- a decision is not the appellant's brief and
must never claim a FILINGS row -- but they do get a synthesized entry, so every
document on the docket hangs off exactly one. They keep
``link_status='court_generated'`` to stay distinguishable from filer
submissions, which is the only thing separating them once both are inferred.

Both directions are therefore plain group-bys over the returned pair; see
:func:`reconcile_files_and_entries` for the exact keys.

Every entry also gets a ``docket_entry_id`` — unique within the docket and
stable between scrapes, which no position on the page is. Court-PASS sorts
FILINGS by ``date_due`` ascending with blank-due rows first, so a newly
scheduled filing is *inserted above* existing rows rather than appended, and
``gvFiles`` is sorted alphabetically by file name, so a new PDF lands mid-table.
Both make row position useless as an identity across runs. See
:func:`entry_id_from_row` and :func:`entry_id_from_document`.

A synthesized entry's *party* also comes off the file name, which carries a
squashed short form of it (``1995CAM``, ``Scharf``, ``CityofNY``) where the
FILINGS table and the ATTORNEY DETAILS section carry the party's full name. So
such an entry reads worse than the entries beside it for no reason other than
which page it came off. :func:`align_party_name` resolves the short form back
onto the docket's own wording, which lands 94.6% of the historical corpus's
inferred parties.
"""

from __future__ import annotations

import collections
import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

from .vocabularies import (
    COURT_GENERATED_DOCTYPES,
    DOCTYPE_LABELS,
    ROLE_LABELS,
    FilingDocType,
    FilingRole,
    FilingType,
    filing_type_from_value,
)

__all__ = [
    "FILING_TYPE_MAP",
    "FilingTypeClassification",
    "ParsedFileName",
    "archive_dedup_keys",
    "classify_filing_type",
    "describe_filing",
    "entry_id_from_document",
    "entry_id_from_row",
    "parse_file_name",
    "reconcile_files_and_entries",
]

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

#: Party-role abbreviations. The spec defines ``app`` / ``res`` / ``amic``;
#: the rest are variants filers actually use.
ROLES: dict[str, FilingRole] = {
    "app": FilingRole.APPELLANT,
    "appellant": FilingRole.APPELLANT,
    "appellants": FilingRole.APPELLANT,
    "apps": FilingRole.APPELLANT,
    "aplt": FilingRole.APPELLANT,
    "defapp": FilingRole.APPELLANT,
    "res": FilingRole.RESPONDENT,
    "respondent": FilingRole.RESPONDENT,
    "respondents": FilingRole.RESPONDENT,
    "resp": FilingRole.RESPONDENT,
    "rspt": FilingRole.RESPONDENT,
    "amic": FilingRole.AMICUS,
    "amici": FilingRole.AMICUS,
    "amicus": FilingRole.AMICUS,
    "amicis": FilingRole.AMICUS,
    "pet": FilingRole.PETITIONER,
    "petitioner": FilingRole.PETITIONER,
    "petitioners": FilingRole.PETITIONER,
    "lawguardian": FilingRole.LAW_GUARDIAN,
    "lg": FilingRole.LAW_GUARDIAN,
    "afc": FilingRole.LAW_GUARDIAN,
    "attyforchild": FilingRole.LAW_GUARDIAN,
    "at": FilingRole.LAW_GUARDIAN,
    "scjc": FilingRole.SCJC,
    "prose": FilingRole.PRO_SE,
    "ivnr": FilingRole.INTERVENOR,
    "intervenor": FilingRole.INTERVENOR,
    "intv": FilingRole.INTERVENOR,
}

#: Cross-appeals are written as two adjacent role segments
#: (``...-app-res-Name-brf``).
_ROLE_PAIRS: dict[tuple[FilingRole, FilingRole], FilingRole] = {
    (FilingRole.APPELLANT, FilingRole.RESPONDENT): (
        FilingRole.APPELLANT_RESPONDENT
    ),
    (FilingRole.RESPONDENT, FilingRole.APPELLANT): (
        FilingRole.RESPONDENT_APPELLANT
    ),
    # an intervenor names the side it came in on the same way
    (FilingRole.INTERVENOR, FilingRole.APPELLANT): (
        FilingRole.INTERVENOR_APPELLANT
    ),
    (FilingRole.INTERVENOR, FilingRole.RESPONDENT): (
        FilingRole.INTERVENOR_RESPONDENT
    ),
}

#: Role words filers glue onto the doctype segment: ``ATappbrf``,
#: ``PeopleADbrf``, ``ADresSuppBrf``, ``jtbrf``. Written as a repeatable group
#: in the patterns below (``{_ROLE_PREFIX}*``) because they stack -- ``at`` +
#: ``app`` + ``brf`` -- and matching them one at a time meant enumerating every
#: combination a filer might reach for. Longest alternatives first, so
#: ``response`` is not consumed as ``resp`` with a dangling ``onse``.
_ROLE_PREFIX = (
    r"(?:appellant|respondent|petitioner|response|intervenor|amicus|amici"
    r"|prose|people|cross|joint|resp|amic|ivnr|intv|app|res|pet|jt|at|afc|lg)"
)

#: "Supplemental", in the spellings filers use. Only ``SUPPLEMENTAL_BRIEF`` and
#: ``SUPPLEMENTAL_APPENDIX`` are vocabulary members; on the other types the word
#: is a modifier the canonical type absorbs (``supprec`` -> RECORD).
_SUPPLEMENTAL = r"(?:supplemental|suppl|supp)"

#: Canonical document type -> pattern matching the trailing doctype segment.
#: Order matters: the Appellate Division variants must precede their Court of
#: Appeals counterparts or ``ADreplybrf`` matches the plain ``replybrf``
#: pattern. Doctypes prefixed ``_`` are court-generated, not filer
#: submissions. Types marked (spec) appear in the published abbreviation list.
_DOCTYPE_PATTERNS: tuple[tuple[FilingDocType, str], ...] = (
    # --- types the Court does not publish -------------------------------
    # First, because each is a *narrower* reading of a token a later pattern
    # would otherwise take: "adorder" would fall to DECISION's bare ``order``,
    # "aos" is not the ``aff`` that MOTION matches, and a trial transcript is
    # not this Court's oral-argument recording. See ``FilingDocType``.
    (
        FilingDocType.PRE_SENTENCE_REPORT,
        r"^p(re)?s(entence)?(investigation|invest|i)?(report|rpt|r)?$"
        r"|^presentence(investigation|invest)?(report|rpt)?$",
    ),
    (FilingDocType.AD_ORDER, r"^ad(order|ord|dec(ision)?)$"),
    (
        FilingDocType.AD_MOTION,
        rf"^ad{_ROLE_PREFIX}*(rearg(ument)?|reconsideration)?"
        r"mot(ion)?(forlv|forleave|forrearg(ument)?)?$",
    ),
    (
        FilingDocType.AFFIDAVIT_OF_SERVICE,
        r"^a(ff|ffidavit|ffirmation)?o(f)?s(ervice)?$"
        r"|^(aff|affidavit|affirmation|aos)ofservice$",
    ),
    (
        FilingDocType.JURISDICTIONAL_RESPONSE,
        r"^jur(is|isdiction|isdictional)?r(e)?sp(onse)?$"
        r"|^jurisdictional(response|rsp|letter|ltr)$",
    ),
    (
        FilingDocType.APPELLATE_TERM_BRIEF,
        rf"^(appterm|appellateterm|apterm|atterm){_ROLE_PREFIX}*"
        r"(repl(y)?)?(brf|brief|br)$",
    ),
    (
        FilingDocType.POST_ARGUMENT_BRIEF,
        r"^(ad)?postarg(ument)?(brf|brief|br|sub|submission|ltr|letter)?$",
    ),
    (
        FilingDocType.HEARING_TRANSCRIPT,
        r"^(oath|trial|hearing|admin(istrative)?|dep(osition)?"
        r"|suppression|plea|sentenc(e|ing)|grandjury|gj)"
        rf"{_ROLE_PREFIX}*transcript(s)?$",
    ),
    # --- the Court's own vocabulary --------------------------------------
    (
        FilingDocType.SSM_REPLY_LETTER,
        r"^ssmreplyltr(brf|brief)?$|^ssmltrreplybrf$"
        r"|^replyssmltrbrf$|^ssmltrbrfreply$|^ssmreply$"
        r"|^ssmltrreply$|^replyltrbrf$|^ssmreplybrf$",
    ),
    (
        FilingDocType.SSM_LETTER,
        # ``lrt`` is the transposition filers make of ``ltr``; the bare ``br``
        # suffix and bare ``letter`` are both attested.
        r"^ssm(ltr|lrt|letter)?(brf|brief|br)?$"  # (spec)
        r"|^(ssm)?l(e)?t(te)?r(brf|brief)$|^letterbrief$|^ltr$|^letter$"
        rf"|^{_ROLE_PREFIX}*ltrbrf$",
    ),
    (
        FilingDocType.RESPONSE_TO_AMICUS_BRIEF,
        r"^brf?rs?p?amic.*$"  # (spec)
        # ``(to)?`` and not ``to?``: the latter demands a literal "t", so
        # ``brfrespamic`` and ``brfinrspamic`` -- the two commonest spellings
        # after the spec's own -- fell through to no doctype at all.
        r"|^(brf|brief|resp(onse)?)(in)?(rsp|resp)?(onse)?(to)?amic.*$"
        r"|^amic(us|i)?resp(onse)?$|^rspamicbrf$",
    ),
    (
        FilingDocType.AMICUS_BRIEF,
        r"^amic(us|i)?(ltr)?(brf|brief|br)?$",
    ),  # (spec)
    (
        FilingDocType.AD_REPLY_BRIEF,
        rf"^ad{_ROLE_PREFIX}*r(e)?p(l)?(y)?(brf|brief|br)$"  # (spec)
        rf"|^ad{_ROLE_PREFIX}*repl(y)?$"
        rf"|^{_ROLE_PREFIX}*adr(e)?p(l)?(y)?(brf|brief)$",
    ),
    (
        FilingDocType.REPLY_BRIEF,
        rf"^{_ROLE_PREFIX}*r(e)?pl(y)?(brf|brief|br)$"
        r"|^reply$|^replybr$",
    ),  # (spec)
    (
        FilingDocType.SUPPLEMENTAL_APPENDIX,
        r"^s(upp|uppl|upplemental)?(app|jt|joint)?"  # (spec)
        r"app(dx|endix|x|pdx)$",
    ),
    (
        FilingDocType.SUPPLEMENTAL_BRIEF,
        r"^s(upp|uppl|upplemental)?(brf|brief|br)$",
    ),
    (
        FilingDocType.AD_APPENDIX,
        rf"^ad{_ROLE_PREFIX}*{_SUPPLEMENTAL}?ap(p)?(dx|endix|x|px)$"
        rf"|^{_ROLE_PREFIX}*adap(p)?(dx|endix|x|px)$",
    ),
    (
        FilingDocType.AD_RECORD,
        rf"^ad{_ROLE_PREFIX}*{_SUPPLEMENTAL}?rec(ord)?$"  # (spec)
        rf"|^{_ROLE_PREFIX}*adrec(ord)?$",
    ),
    (
        FilingDocType.AD_BRIEF,
        rf"^ad{_ROLE_PREFIX}*{_SUPPLEMENTAL}?(brf|brief|br)$"  # (spec)
        rf"|^{_ROLE_PREFIX}*ad{_SUPPLEMENTAL}?(brf|brief|br)$",
    ),
    (
        FilingDocType.OPPOSITION_TO_MOTION_FOR_LEAVE_TO_APPEAL,
        r"^opp(osition|osn)?to?mot(ion)?"
        r"for(lv|leave|leavetoappeal|lve)$",
    ),
    (
        FilingDocType.MOTION_FOR_LEAVE_TO_APPEAL,
        r"^mot(ion)?for"
        r"(lv|leave|leavetoappeal|lve|reargument|reconsideration)$",
    ),
    (
        FilingDocType.OPPOSITION,
        r"^opp(osition|osn)?(to?mot(ion)?)?$"
        r"|^opposingaffirmation$|^oppaff$",
    ),
    (
        FilingDocType.MOTION,
        r"^mot(ion)?$|^affirmation$|^affidavit$|^supportingpapers$|^aff$",
    ),
    (
        FilingDocType.COMPENDIUM,
        rf"^{_ROLE_PREFIX}*(repl(y)?|{_SUPPLEMENTAL})?"
        r"comp(end|endium|endia|endiumofauthorities)?$",
    ),
    (FilingDocType.ADDENDUM, r"^add(end|endum|enda)?$"),
    (
        FilingDocType.RECORD,
        # ``onreview`` for the Record on Review the FILINGS table names, which
        # filers write across segments (``-Record-on-Review-``); the join in
        # ``parse_file_name`` hands it here as one token.
        rf"^{_ROLE_PREFIX}*{_SUPPLEMENTAL}?rec(ord)?(onappeal|onreview)?$"
        rf"|^rec(ord)?{_ROLE_PREFIX}*$",  # (spec)
    ),
    (
        FilingDocType.APPENDIX,
        rf"^{_ROLE_PREFIX}*ap(p)?(dx|endix|x|pdx|end|px)$"
        rf"|^ap(p)?(dx|endix|x|px){_ROLE_PREFIX}*$",
    ),  # (spec)
    (FilingDocType.EXHIBITS, r"^(trial)?exh(s|ibits)?$"),
    (
        FilingDocType.BRIEF,
        rf"^{_ROLE_PREFIX}*(brf|brief|br)$",  # (spec)
    ),
    # court-generated, never a filer submission
    (
        FilingDocType.DECISION,
        r"^decision(s)?$|^opn$|^opinion$|^memorandum$|^order$",
    ),
    (
        FilingDocType.ORAL_ARGUMENT_TRANSCRIPT,
        # ``trialtranscript`` used to be here. It is a transcript of the trial
        # below, filed by a party -- reading it as this Court's oral argument
        # made it court-generated, which barred it from matching at all. It is
        # HEARING_TRANSCRIPT now.
        r"^transcript(s)?$|^oralargumenttranscript$"
        r"|^technicalrecordingfailure$",
    ),
    (FilingDocType.ORAL_ARGUMENT_WEBCAST, r"^webcast$|^video$|^audio$"),
)

#: One PDF satisfying two filings (e.g. ``-brf&appdx``).
_COMBINED = re.compile(
    r"^(brf|brief)(and|&|\+)app(dx|endix|x)$"
    r"|^(brf|brief)(and|&|\+)rec(ord)?$"
    r"|^app(dx|endix|x)(and|&|\+)(brf|brief)$"
)
#: FILINGS-table filing type -> the (role, document type) it implies.
FILING_TYPE_MAP: dict[
    FilingType, tuple[FilingRole | None, FilingDocType | None]
] = {
    FilingType.APPELLANT_BRIEF: (FilingRole.APPELLANT, FilingDocType.BRIEF),
    FilingType.RESPONDENT_BRIEF: (FilingRole.RESPONDENT, FilingDocType.BRIEF),
    FilingType.PETITIONER_BRIEF: (FilingRole.PETITIONER, FilingDocType.BRIEF),
    FilingType.APPELLANT_REPLY_BRIEF: (
        FilingRole.APPELLANT,
        FilingDocType.REPLY_BRIEF,
    ),
    FilingType.PETITIONER_REPLY_BRIEF: (
        FilingRole.PETITIONER,
        FilingDocType.REPLY_BRIEF,
    ),
    FilingType.AMICUS_BRIEF: (FilingRole.AMICUS, FilingDocType.AMICUS_BRIEF),
    FilingType.APPELLANT_APPENDIX: (
        FilingRole.APPELLANT,
        FilingDocType.APPENDIX,
    ),
    FilingType.RESPONDENT_APPENDIX: (
        FilingRole.RESPONDENT,
        FilingDocType.APPENDIX,
    ),
    FilingType.APPELLANT_COA_RECORD: (
        FilingRole.APPELLANT,
        FilingDocType.RECORD,
    ),
    FilingType.RESPONDENT_COA_RECORD: (
        FilingRole.RESPONDENT,
        FilingDocType.RECORD,
    ),
    FilingType.APPELLANT_RECORD: (FilingRole.APPELLANT, FilingDocType.RECORD),
    FilingType.RECORD_ON_REVIEW: (None, FilingDocType.RECORD),
    FilingType.APPELLANT_SSM_LETTER: (
        FilingRole.APPELLANT,
        FilingDocType.SSM_LETTER,
    ),
    FilingType.RESPONDENT_SSM_LETTER: (
        FilingRole.RESPONDENT,
        FilingDocType.SSM_LETTER,
    ),
    FilingType.LAW_GUARDIAN_SSM_LETTER: (
        FilingRole.LAW_GUARDIAN,
        FilingDocType.SSM_LETTER,
    ),
    FilingType.RESPONDENT_RESPONSE_TO_AMICUS_BRIEF: (
        FilingRole.RESPONDENT,
        FilingDocType.RESPONSE_TO_AMICUS_BRIEF,
    ),
    FilingType.APPELLANT_RESPONSE_TO_AMICUS_BRIEF: (
        FilingRole.APPELLANT,
        FilingDocType.RESPONSE_TO_AMICUS_BRIEF,
    ),
    FilingType.AD_RECORD: (None, FilingDocType.AD_RECORD),
    FilingType.AD_APPENDIX: (None, FilingDocType.AD_APPENDIX),
    FilingType.AD_APPELLANT_BRIEF: (
        FilingRole.APPELLANT,
        FilingDocType.AD_BRIEF,
    ),
    FilingType.AD_RESPONDENT_BRIEF: (
        FilingRole.RESPONDENT,
        FilingDocType.AD_BRIEF,
    ),
    FilingType.AD_APPELLANT_REPLY_BRIEF: (
        FilingRole.APPELLANT,
        FilingDocType.AD_REPLY_BRIEF,
    ),
    FilingType.AD_RESPONDENT_APPENDIX: (
        FilingRole.RESPONDENT,
        FilingDocType.AD_APPENDIX,
    ),
    FilingType.APPELLANT_RESPONDENT_BRIEF: (
        FilingRole.APPELLANT_RESPONDENT,
        FilingDocType.BRIEF,
    ),
    FilingType.RESPONDENT_APPELLANT_BRIEF: (
        FilingRole.RESPONDENT_APPELLANT,
        FilingDocType.BRIEF,
    ),
    FilingType.APPELLANT_RESPONDENT_REPLY_BRIEF: (
        FilingRole.APPELLANT_RESPONDENT,
        FilingDocType.REPLY_BRIEF,
    ),
    FilingType.RESPONDENT_APPELLANT_REPLY_BRIEF: (
        FilingRole.RESPONDENT_APPELLANT,
        FilingDocType.REPLY_BRIEF,
    ),
    FilingType.LAW_GUARDIAN_BRIEF: (
        FilingRole.LAW_GUARDIAN,
        FilingDocType.BRIEF,
    ),
    FilingType.PRO_SE_SUPPLEMENTAL_BRIEF: (
        None,
        FilingDocType.SUPPLEMENTAL_BRIEF,
    ),
    FilingType.PETITIONER_RESPONSE_REVIEW: (
        FilingRole.PETITIONER,
        FilingDocType.BRIEF,
    ),
    FilingType.PETITIONER_RESPONSE_SUSPENSION: (
        FilingRole.PETITIONER,
        FilingDocType.BRIEF,
    ),
    FilingType.RESPONDENT_RESPONSE_SUSPENSION: (
        FilingRole.RESPONDENT,
        FilingDocType.BRIEF,
    ),
    FilingType.SCJC_RESPONSE_SUSPENSION: (
        FilingRole.SCJC,
        FilingDocType.BRIEF,
    ),
    FilingType.SCJC_DETERMINATION: (FilingRole.SCJC, None),
}
#: Roles close enough to match on when the file name and the FILINGS row state
#: different ones. Filers routinely write ``app`` on a cross-appeal the table
#: calls "Appellant-Respondent", and write the side an amicus supports
#: (``res``) rather than ``amic``.
#:
#: Stated one way round and symmetrized, like :data:`_COMPATIBLE_PAIRS`, since
#: matching cares only that the two roles are compatible. The asymmetry this
#: replaced was silently costly: ``APPELLANT`` accepted ``APPELLANT_RESPONDENT``
#: but ``RESPONDENT`` accepted only ``RESPONDENT_APPELLANT``, so on a
#: cross-appeal one direction's files were vetoed off their own party's row and
#: took whatever row was left -- observed as two files swapping parties on
#: APL-2022-00042.
_ROLE_COMPATIBLE_PAIRS: tuple[tuple[FilingRole, FilingRole], ...] = (
    (FilingRole.APPELLANT, FilingRole.APPELLANT_RESPONDENT),
    (FilingRole.APPELLANT, FilingRole.RESPONDENT_APPELLANT),
    (FilingRole.RESPONDENT, FilingRole.APPELLANT_RESPONDENT),
    (FilingRole.RESPONDENT, FilingRole.RESPONDENT_APPELLANT),
    (FilingRole.APPELLANT, FilingRole.PETITIONER),
    (FilingRole.LAW_GUARDIAN, FilingRole.APPELLANT),
    (FilingRole.LAW_GUARDIAN, FilingRole.RESPONDENT),
    (FilingRole.INTERVENOR, FilingRole.INTERVENOR_APPELLANT),
    (FilingRole.INTERVENOR, FilingRole.INTERVENOR_RESPONDENT),
    (FilingRole.APPELLANT, FilingRole.INTERVENOR_APPELLANT),
    (FilingRole.RESPONDENT, FilingRole.INTERVENOR_RESPONDENT),
)
#: ``AMICUS`` is deliberately absent, even though an amicus names the side it
#: supports (``-res-DAASNY-amicbrf``) as often as it names itself: BRIEF and
#: AMICUS_BRIEF are compatible doctypes, so pairing the roles too would let a
#: party's own brief outrank the party's own FILINGS row on the strength of a
#: doubly-loose match. That spelling is instead reached by the exact-doctype
#: waiver below, which needs no role agreement at all.
_COMPATIBLE_ROLES: frozenset[tuple[FilingRole, FilingRole]] = frozenset(
    _ROLE_COMPATIBLE_PAIRS
) | frozenset((b, a) for a, b in _ROLE_COMPATIBLE_PAIRS)
#: Document-type pairs close enough to match on when the exact type differs.
#: Stated one way round and symmetrized, since matching cares only that the two
#: types are compatible.
_COMPATIBLE_PAIRS: tuple[tuple[FilingDocType, FilingDocType], ...] = (
    (FilingDocType.BRIEF, FilingDocType.SUPPLEMENTAL_BRIEF),
    (FilingDocType.APPENDIX, FilingDocType.SUPPLEMENTAL_APPENDIX),
    (FilingDocType.APPENDIX, FilingDocType.AD_APPENDIX),
    (FilingDocType.RECORD, FilingDocType.AD_RECORD),
    (FilingDocType.RECORD, FilingDocType.APPENDIX),
    (FilingDocType.SSM_LETTER, FilingDocType.SSM_REPLY_LETTER),
    (FilingDocType.BRIEF, FilingDocType.AD_BRIEF),
    (FilingDocType.REPLY_BRIEF, FilingDocType.AD_REPLY_BRIEF),
    (FilingDocType.BRIEF, FilingDocType.AMICUS_BRIEF),
    (FilingDocType.BRIEF, FilingDocType.RESPONSE_TO_AMICUS_BRIEF),
    (FilingDocType.BRIEF, FilingDocType.SSM_LETTER),
    (FilingDocType.APPENDIX, FilingDocType.COMPENDIUM),
    (FilingDocType.RECORD, FilingDocType.COMPENDIUM),
    (FilingDocType.APPENDIX, FilingDocType.ADDENDUM),
    (FilingDocType.APPENDIX, FilingDocType.EXHIBITS),
    (FilingDocType.RECORD, FilingDocType.EXHIBITS),
)
_COMPATIBLE_DOCTYPES: frozenset[tuple[FilingDocType, FilingDocType]] = (
    frozenset(_COMPATIBLE_PAIRS)
    | frozenset((b, a) for a, b in _COMPATIBLE_PAIRS)
)

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

#: ``vol1`` / ``volIV`` / ``vol 3`` / ``vol1 part2``
_VOLUME = re.compile(
    r"^(?:vol(?:ume)?|v)\s*0*(\d+|[ivxl]+)"
    r"(?:\s*(?:part|pt)\s*0*(\d+|[ivxl]+))?$"
)
#: ``part2`` / ``pt II`` on its own, which filers write as a segment of its own
#: as often as they glue it to the volume (``-Rec-vol1-part2``).
_PART = re.compile(r"^(?:part|pt)\s*0*(\d+|[ivxl]+)$")
#: The volume marker with its number split off into the next segment
#: (``-Rec-vol-1``). Bare ``v`` is deliberately excluded: it is how every case
#: title separates the parties, and ``Smith-v-Jones`` must not read as a volume.
_BARE_VOLUME_WORD = re.compile(r"^(?:vol|volume|part|pt)$")
#: doctype and volume glued into one segment: ``Rec Vol 1``, ``recvol2``
_GLUED_VOLUME = re.compile(
    r"^(?P<doctype>.*?)\s*(?P<volume>(?:vol(?:ume)?|part|pt)\s*0*(?:\d+|[ivxl]+)"
    r"(?:\s*(?:part|pt)\s*0*(?:\d+|[ivxl]+))?)$",
    re.IGNORECASE,
)
#: Decorative words filers add to a file name. They appear as segments of their
#: own (``-brf-redacted``) and glued onto the doctype (``-RecRedacted``,
#: ``-amended.brf``), so both spellings are stripped before classification.
_NOISE_WORDS = (
    r"redacted|unredacted|revised|rev|corrected|corr|amended|amend|final"
    r"|sealed|unsealed|conf|confidential|replacement|resubmitted|resubmission"
    r"|copy|new|updated"
)
#: A decorative word glued to either end of the doctype segment.
_GLUED_NOISE = re.compile(rf"^(?:{_NOISE_WORDS})|(?:{_NOISE_WORDS})$")
#: ``brf.pdf.`` -- a doubled or dot-trailed extension the outer strip missed.
_STRAY_EXTENSION = re.compile(r"(?:\.pdf)+\.*$", re.IGNORECASE)
#: decorative trailing segments that are not the doctype. ``\d{1,4}`` and not
#: ``\d{1,3}``: filers date the tail of a name (``-ADRec-vol1-2013``), and a
#: four-digit year left unconsumed becomes the doctype token, hiding the real
#: one in front of it.
_NOISE = re.compile(
    r"^(redacted|revised|rev|corrected|corr|amended|amend|final|sealed"
    r"|unsealed|conf|confidential|replacement|resubmitted|resubmission|copy"
    r"|new|updated|of|and|\d{1,4}|[a-z])$"
)
#: Ceiling on a word-overlap party score, keeping it below the 0.9 a whole-name
#: containment earns. See :func:`_party_score`.
_MAX_WORD_OVERLAP = 0.85

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
    role: FilingRole | None = None
    """The role the name states, or ``None`` when it states none this
    vocabulary recognizes."""
    party: str | None = None
    """Party name segment, un-normalized (``ConcernedCitizens``)."""
    doctype: FilingDocType | None = None
    """The document type the name states, or ``None`` when the trailing token
    is unrecognizable. The ``_``-prefixed members are court output."""
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
        return self.doctype is FilingDocType.BRIEF_AND_APPENDIX


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


def _part_number(token: str) -> int | None:
    """``"part2"`` -> ``2``; ``"pt II"`` -> ``2``. None when not a part."""
    cleaned = re.sub(r"[^a-z0-9 ]", "", _clean(token).lower()).strip()
    match = _PART.match(cleaned)
    if not match:
        return None
    raw = match.group(1)
    return int(raw) if raw.isdigit() else _ROMAN.get(raw)


def _strip_decoration(token: str) -> str:
    """Peel the decorations filers glue onto a doctype off both ends.

    ``"RecRedacted"`` -> ``"rec"``, ``"amended.brf"`` -> ``"brf"``,
    ``"brf.pdf."`` -> ``"brf"``. A token that is *only* decoration is returned
    untouched, since there is no doctype hiding in it.
    """
    stripped = _normalize(_STRAY_EXTENSION.sub("", token))
    while True:
        peeled = _GLUED_NOISE.sub("", stripped)
        if peeled == stripped or not peeled:
            return stripped
        stripped = peeled


def _match_doctype(normalized: str) -> FilingDocType | None:
    if _COMBINED.match(normalized):
        return FilingDocType.BRIEF_AND_APPENDIX
    for canonical, pattern in _DOCTYPE_PATTERNS:
        if re.match(pattern, normalized):
            return canonical
    return None


def _classify_doctype(token: str) -> FilingDocType | None:
    normalized = _normalize(token)
    doctype = _match_doctype(normalized)
    if doctype is not None:
        return doctype
    # Try again without the decorations, so a filer writing "SEALEDappdx" or
    # "brf.pdf." still gets read. Only ever a second attempt: an undecorated
    # token that already matched is never touched.
    undecorated = _strip_decoration(token)
    if undecorated and undecorated != normalized:
        return _match_doctype(undecorated)
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
    filing_type: FilingType | None = None
    role: FilingRole | None = None
    doctype: FilingDocType | None = None
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
    filing_type = filing_type_from_value(raw_filing_type)
    if filing_type is None:
        return FilingTypeClassification(raw=raw_filing_type, recognized=False)
    role, doctype = FILING_TYPE_MAP[filing_type]
    return FilingTypeClassification(
        raw=raw_filing_type,
        filing_type=filing_type,
        role=role,
        doctype=doctype,
        recognized=True,
    )


def describe_filing(
    role: FilingRole | None, doctype: FilingDocType | None
) -> str:
    """Compose a FILINGS-style label, for entries the table never carried.

    ``(APPELLANT, MOTION_FOR_LEAVE_TO_APPEAL)`` ->
    ``"Appellant Motion for Leave to Appeal"``.
    """
    doctype_label = DOCTYPE_LABELS.get(doctype) if doctype else None
    if doctype_label is None:
        return UNCLASSIFIED_FILING_LABEL
    role_label = ROLE_LABELS.get(role) if role else None
    if role_label is None:
        return doctype_label
    # "Amicus" + "Amicus Brief" reads badly; the doctype already says it
    if doctype_label.startswith(role_label):
        return doctype_label
    # keep the court's "AD - X" prefix in front: "AD - Appellant Brief"
    if doctype_label.startswith("AD - "):
        return f"AD - {role_label} {doctype_label[len('AD - ') :]}"
    return f"{role_label} {doctype_label}"


def _id_slug(value: str | None) -> str:
    """Fold one ``docket_entry_id`` component to a stable token."""
    slug = re.sub(r"[^a-z0-9]+", "-", _clean(value).lower()).strip("-")
    return slug or "none"


def entry_id_from_row(
    filing_type: str | None, party: str | None, ordinal: int
) -> str:
    """Compose the ``e:`` id for a real FILINGS row.

    Built from ``(filing_type, party, ordinal)`` and nothing else. Both dates
    are deliberately excluded: ``date_received`` fills in blank -> date, and
    ``date_due`` gets adjourned, so either in the key would retire the id on a
    routine update. Measured over 14647 FILINGS rows, this is unique within a
    docket, whereas ``(filing_type, party)`` alone collides on 156 rows and the
    full four-column row still collides on 39.
    """
    return f"e:{_id_slug(filing_type)}:{_id_slug(party)}:{ordinal}"


def _document_id_components(
    parsed: ParsedFileName,
) -> tuple[str | None, str | None, str | None]:
    """The ``(role, party, doctype)`` an inferred entry's id is built from."""
    if parsed.is_court_generated:
        # Court output carries no role or party -- the title is what separates
        # one decision from another ("123ent25" vs "51opn21"), and a docket can
        # hold several. Without it every decision on a docket would differ only
        # by an ordinal taken over alphabetical file order, so a newly published
        # decision sorting first would re-key the others.
        doctype = parsed.doctype.value if parsed.doctype else ""
        return "court", parsed.title, doctype.lstrip("_")
    return (
        parsed.role.value if parsed.role else None,
        parsed.party,
        parsed.doctype.value if parsed.doctype else parsed.unparsed_token,
    )


def entry_id_from_document(parsed: ParsedFileName, ordinal: int) -> str:
    """Compose the ``d:`` id for an entry synthesized from a file name.

    Keyed on ``(role, party, doctype)`` -- the triple that groups volumes
    together -- rather than on any one file name, so withdrawing one volume of a
    record leaves the surviving siblings' id untouched.
    """
    role, party, doctype = _document_id_components(parsed)
    return (
        f"d:{_id_slug(role)}:{_id_slug(party)}:{_id_slug(doctype)}:{ordinal}"
    )


#: Byte cap for one archive key. The key is used verbatim as a single
#: directory name (``{storage}/{xx}/{yy}/{key}/{sha256}.pdf``), and the common
#: filesystem limit for one component is 255; leave headroom.
_MAX_KEY_BYTES = 200


#: Trailing extension on a ``gvFiles`` file name. Court-PASS is inconsistent
#: about printing one -- 152 of 14221 names in the 2026-08-22 corpus end in
#: ``.pdf`` and the rest do not, sometimes both on the same docket -- so it is
#: stripped before the key is built and re-attached from ``expected_type``.
_FILE_NAME_EXTENSION_RE = re.compile(r"\.(?:pdf|asx|txt|docx?|rtf)$", re.I)


def _archive_key_body(file_row: dict) -> str:
    """The document-identifying middle of an archive key.

    The file name exactly as ``gvFiles`` prints it, slugified. This is
    deliberately *not* derived from the reconciled ``docket_entry_id``: that
    id is the matcher's opinion about which FILINGS row a document belongs to,
    and when the matcher changes its mind -- as it does, the pairing being
    contested for any file whose party name the table states differently --
    every affected file silently changes its name on disk and in the archive.
    A brief kept the name of whichever amicus the matcher had guessed that
    run, and two runs a fortnight apart disagreed.

    The page's own file name has no such dependency. It is what the Court
    published, it is stable across runs, and it is wrong only if the Court
    renames the file.
    """
    # Trailing dots and spaces come first: the Court prints names like
    # ``...-Appx.pdf.``, and an extension the trailing dot hides survives into
    # the key as a ``-pdf`` segment that reads like part of the document name.
    name = (file_row.get("file_name") or "").strip().rstrip(". ")
    name = _FILE_NAME_EXTENSION_RE.sub("", name)
    return _id_slug(name) or "unnamed"


def archive_dedup_keys(
    docket_number: str | None, files: list[dict]
) -> list[str]:
    """One archive/deduplication key per file, unique within the docket.

    Takes the reconciled file rows for a single docket -- all of them, not just
    the fetchable ones, so a file that becomes available later keeps the same
    key -- and returns keys positionally.

    Shaped ``{docket}_{file name}_{n}``, e.g.
    ``APL-2025-00221_vassellvvassell-app-vassell-brf_1``. jkent stores the
    download at ``{storage}/{xx}/{yy}/{key}/{sha256}.{expected_type}``, so the
    key is the directory and the extension arrives separately, off the
    download button -- see ``file_type_from_button``.

    The docket number is required because the key must be unique across the
    whole run and 443 file names in the corpus appear on more than one docket,
    some legitimately (one decision resolving ten companion appeals).

    ``n`` counts how many times this file name has been seen on this docket,
    1-based. It is counted over the *slugified* name rather than the raw one:
    two names differing only in punctuation or case slugify to one string, and
    counting before that collapse would give each its own ``_1`` and lose the
    second file. Over the 14221 files of the 2026-08-22 corpus no name repeats
    within a docket, so ``n`` is always 1 -- it exists for the day that stops
    being true, which the ``UNIQUE ON CONFLICT IGNORE`` on
    ``requests.deduplication_key`` would otherwise turn into a dropped
    download rather than an error.

    Note what is *not* here: ``volume``, ``part``, and the old ``altK``
    disambiguator all existed to separate files that the entry-id scheme
    collapsed together -- volumes of one record, a redacted and an unredacted
    upload of one brief. The Court gives each of those its own file name, so
    naming from the page separates them without help.
    """
    prefix = (
        re.sub(r"[^A-Za-z0-9.-]+", "-", docket_number or "").strip("-")
        or "no-docket-number"
    )
    keys: list[str] = []
    seen: dict[str, int] = {}
    for file_row in files:
        body = _archive_key_body(file_row)
        seen[body] = seen.get(body, 0) + 1
        key = f"{prefix}_{body}_{seen[body]}"
        if len(key.encode()) > _MAX_KEY_BYTES:
            # keep the head readable and make the tail carry the uniqueness;
            # the digest is of the full key, so two names that truncate to the
            # same prefix still part ways
            digest = hashlib.sha1(key.encode()).hexdigest()[:8]
            room = _MAX_KEY_BYTES - len(digest) - 1
            key = f"{key.encode()[:room].decode(errors='ignore')}-{digest}"
        keys.append(key)
    return keys


def _group_id_key(parsed: ParsedFileName) -> tuple:
    """The components :func:`entry_id_from_document` builds an id from.

    Must stay in step with that function: the ordinal exists only to separate
    groups whose ids would otherwise be identical, so counting it over a
    different set of fields would either hand out a spurious ordinal or let two
    groups collide.
    """
    role, party, doctype = _document_id_components(parsed)
    return (role, _normalize(party), doctype)


def _ordinals(keys: list) -> list[int]:
    """1-based occurrence counter per repeated key, in source order."""
    seen: dict = {}
    out = []
    for key in keys:
        seen[key] = seen.get(key, 0) + 1
        out.append(seen[key])
    return out


def _join_split_volumes(segments: list[str]) -> list[str]:
    """Rejoin ``-vol-1-`` into a single ``vol 1`` segment.

    Filers write the volume marker and its number as separate segments as often
    as they glue them together. Split, neither half reads: ``vol`` alone is not
    a volume, and the number alone is consumed as noise -- so the walk stops on
    ``vol`` and the real doctype in front of it is never reached.
    """
    joined: list[str] = []
    index = 0
    while index < len(segments):
        current = segments[index]
        following = segments[index + 1] if index + 1 < len(segments) else None
        merged = f"{current} {following}" if following is not None else ""
        if (
            following is not None
            and _BARE_VOLUME_WORD.match(_normalize(current))
            and (
                _volume_numbers(merged) is not None
                or _part_number(merged) is not None
            )
        ):
            joined.append(merged)
            index += 2
            continue
        joined.append(current)
        index += 1
    return joined


def _doctype_across_segments(
    segments: list[str], index: int
) -> tuple[FilingDocType | None, int]:
    """Read a doctype the filer wrote across segment boundaries.

    ``-Record-on-Review-`` is three segments, none of which classifies alone.
    Returns the doctype and how many *extra* segments it consumed, or
    ``(None, 0)``. Only ever reached once the trailing segment has failed to
    classify on its own, and only a successful classification is accepted, so
    this cannot pull a party name into the doctype.

    It stops at a segment naming a role, though, because that one *would*
    classify: ``-Resp-AmicusResp`` reads as a response to an amicus brief with
    or without the ``Resp``, and swallowing it costs the role for nothing.
    """
    for extra in (1, 2):
        if index - extra < 0:
            break
        if ROLES.get(_normalize(segments[index - extra])) is not None:
            break
        doctype = _classify_doctype(
            "".join(segments[index - extra : index + 1])
        )
        if doctype is not None:
            return doctype, extra
    return None, 0


def parse_file_name(file_name: str) -> ParsedFileName:
    """Split a Court-PASS file name into its convention components.

    Reads right-to-left: trailing volume/noise segments are consumed first,
    then the doctype, then the remaining left segments are split at the role
    into title and party. Any field the filer omitted or mangled comes back
    ``None`` rather than raising -- roughly 6% of the corpus has an
    unrecognizable doctype token and pre-2013 filings predate the convention.
    """
    stem = re.sub(
        r"\.pdf$", "", _clean(file_name).strip(), flags=re.IGNORECASE
    )
    segments = _join_split_volumes(stem.split("-"))

    volume: int | None = None
    part: int | None = None
    index = len(segments) - 1
    while index >= 0:
        token = _normalize(segments[index])
        numbers = _volume_numbers(segments[index])
        if numbers and volume is None:
            volume, glued_part = numbers
            if part is None:
                part = glued_part
            index -= 1
            continue
        # A part on its own must not be read as the volume, or a tail written
        # ``-vol1-part2`` consumes its volume slot and the doctype is never
        # reached.
        part_only = _part_number(segments[index])
        if part_only is not None and part is None:
            part = part_only
            index -= 1
            continue
        if not token or _NOISE.match(token):
            index -= 1
            continue
        break

    doctype: str | None = None
    unparsed_token: str | None = None
    joined_back = 0
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
        if doctype is None:
            doctype, joined_back = _doctype_across_segments(segments, index)
        if doctype is not None:
            index -= 1 + joined_back
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

    def party(after_role: int) -> str | None:
        """The party segments following the role, as one string.

        An unreadable doctype is still sitting at the end of ``remaining`` --
        it has to be, because a name whose last segment is the party and whose
        doctype is elsewhere (``-OpptoMotionforLv-Alea``) would otherwise lose
        the party entirely. But when it is not the *only* thing after the role,
        it is decoration on a party that is already there, and leaving it in
        wrecks the comparison: ``Harkenrider-ResponseBRF`` scores far worse
        against "Tim Harkenrider" than ``Harkenrider`` does.
        """
        segs = remaining[after_role:]
        if unparsed_token is not None and len(segs) > 1:
            segs = segs[:-1]
        return "-".join(segs) or None

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
                    party=party(position + 2),
                    **common,
                )
        return ParsedFileName(
            title="-".join(remaining[:position]) or None,
            role=role,
            party=party(position + 1),
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

    Word overlap is capped below the containment tier because it is computed
    over *significant* words only, and dropping the stopwords can erase the
    whole distinction between two parties: "New York State Bar Association"
    and "Association of the Bar of the City of New York" both reduce to
    ``{association, bar}`` and scored a perfect 1.0 against each other, which
    on APL-2015-00236 was enough to outrank the first party's own exact match
    and hand each brief the other's row. A match on the whole string is
    stronger evidence than a match on what survives the stopword list, and the
    scores now say so.
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
    return min(
        overlap / min(len(left_words), len(right_words)), _MAX_WORD_OVERLAP
    )


#: Party agreement reached by initialism rather than by string overlap. Below
#: the containment tier -- initials are lossy, and two of a docket's parties
#: can share them -- but far above the 0.0 that string comparison alone
#: returns for the abbreviations filers actually write.
_INITIALISM_PARTY_SCORE = 0.75

#: Party agreement reached by initializing only the distinctive tail of a
#: name. Below the whole-initialism tier: less of the name had to agree.
_TAIL_INITIALISM_PARTY_SCORE = 0.7

#: A tail initialism shorter than this is coincidence -- two letters end a
#: great many names' initials.
_MIN_TAIL_INITIALISM_LEN = 3

#: Party agreement reached by an anchored subsequence. Weakest tier that still
#: counts as evidence; see :func:`_anchored_at_word` for why the anchor is what
#: keeps it from matching everything.
_SUBSEQUENCE_PARTY_SCORE = 0.6


def _party_match_score(
    file_party: str | None, entry_party: str | None
) -> float:
    """:func:`_party_score`, plus the abbreviation tiers used for synthesis.

    Amicus filers name themselves by initialism far more often than not --
    ``NYSATL``, ``NYSAC``, ``ALFN``, ``SIFMA``, ``DFS`` -- and against the
    FILINGS table's full legal name every one of those scores 0.0 on string
    agreement. :func:`align_party_name` already resolves them when it needs a
    name for a *synthesized* entry, so the knowledge is in the module; the
    matcher just wasn't consulting it, and a docket's amicus briefs were left
    to be dealt out among its amicus rows in source order.

    The tiers rank below containment deliberately. An initialism is lossy
    evidence, so a rival with real string agreement should still win; the
    point is only that it beats no evidence at all.
    """
    score = _party_score(file_party, entry_party)
    if score or not file_party or not entry_party:
        return score

    probes = _party_probes(file_party)
    initials = _initialism(entry_party)
    for probe in probes:
        token = _normalize(probe)
        if not 2 <= len(token) <= _MAX_INITIALISM_LEN or not token.isalpha():
            continue
        if token and token == initials:
            return _INITIALISM_PARTY_SCORE
        # A filer who writes "DFS" for "New York State Department of Financial
        # Services" has initialized the distinctive tail and dropped the
        # jurisdictional prefix every party on a New York docket shares. The
        # tail is the part that identifies, so a token ending the candidate's
        # initialism counts -- but only as a suffix, since a *leading* run
        # would be that shared prefix and would match half the docket.
        if (
            len(token) >= _MIN_TAIL_INITIALISM_LEN
            and len(token) < len(initials)
            and initials.endswith(token)
        ):
            return _TAIL_INITIALISM_PARTY_SCORE

    normalized_entry = _normalize(entry_party)
    for probe in probes:
        token = _normalize(probe)
        if len(token) < _MIN_SUBSEQUENCE_LEN:
            continue
        if _is_subsequence(token, normalized_entry) and _anchored_at_word(
            token, entry_party
        ):
            return _SUBSEQUENCE_PARTY_SCORE
    return 0.0


# --------------------------------------------------------------------------
# Party-name alignment
# --------------------------------------------------------------------------

#: Dropped when reading a name as an initialism, so "State of New York" gives
#: ``sny`` -- which is what filers actually write. Narrower than
#: ``_PARTY_STOPWORDS``, which drops whole words like "people" and "york" that
#: an initialism keeps a letter of.
_INITIALISM_SKIP = frozenset({"a", "an", "and", "for", "in", "of", "the"})

#: An initialism is short by nature. Above this a token is a squashed name, and
#: matching it letter-by-letter against initials invites coincidence.
_MAX_INITIALISM_LEN = 8

#: Below this a subsequence match is coincidence -- three letters in order turn
#: up in almost any name.
_MIN_SUBSEQUENCE_LEN = 4

#: How many leading characters of a token must begin one of the candidate's
#: words for a subsequence match to count. See :func:`_anchored_at_word`.
_SUBSEQUENCE_ANCHOR = 3


def _party_probes(party: str) -> list[str]:
    """The party segment, then each shorter prefix of its ``-`` segments.

    The convention gives the party *one* segment, so anything after the first
    is decoration the filer glued on -- a doctype the reader could not
    classify, a volume marker, the opposing party, a note to the clerk
    (``Bonczar-ADreplybrf-Appeal 2``, ``DeptSocSvcs-ADresbrf1``). Trying every
    prefix rather than guessing which tail is decoration also keeps genuinely
    hyphenated names intact, because the full token is tried first and a
    longer probe can only score higher: ``409-411 Sixth Street`` matches on
    ``409-411`` and ``Peguero-Sanchez`` on the whole thing.
    """
    segments = [seg for seg in party.split("-") if seg.strip()]
    return [
        "-".join(segments[:count]) for count in range(len(segments), 0, -1)
    ]


#: A name's words, splitting the CamelCase filers squash them into.
_WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+")

#: ``ColeS`` -- a surname with a given-name initial pinned on, which is how
#: filers tell two same-surname parties apart. See :func:`_by_given_initial`.
_SURNAME_INITIAL = re.compile(r"^([A-Za-z][a-z]+)([A-Z])$")


def _name_words(name: str) -> list[str]:
    return _WORDS.findall(_clean(name))


def _initialism(name: str) -> str:
    """A candidate's words reduced to their first letters (``sny``, ``nycta``)."""
    return "".join(
        word[0].lower()
        for word in _name_words(name)
        if word.lower() not in _INITIALISM_SKIP
    )


def _is_subsequence(token: str, name: str) -> bool:
    """Whether ``token``'s characters appear in ``name`` in order."""
    remaining = iter(name)
    return all(char in remaining for char in token)


def _anchored_at_word(token: str, name: str) -> bool:
    """Whether ``token`` starts where one of ``name``'s words starts.

    The anchor is what keeps the subsequence tier honest. Without it "Lee"
    matches any name whose letters happen to run l...e...e, and with it
    ``DeptSocSvcs`` still reaches "Department of Social Services of City of
    New York" because it begins where "Department" does.
    """
    prefix = token[:_SUBSEQUENCE_ANCHOR]
    return any(word.lower().startswith(prefix) for word in _name_words(name))


def _by_given_initial(probe: str, tied: list[str]) -> str | None:
    """The tied candidate whose given name starts with the token's initial.

    Filers already disambiguate two same-surname parties the way we would want
    to: they pin the given-name initial on the end (``ColeS`` and ``ColeJ``
    against Samantha and Jesse Cole; ``NunezR`` against Reinaldo Nunez). The
    surname alone is what ties, so the initial is the whole of the evidence and
    throwing it away is what left these unresolved.

    Only the initial-last shape is read. Written first it is indistinguishable
    from a doctype token -- ``RRec``, ``ADresp`` -- and the corpus's one
    initial-first party name (``BStrianese``, against both Bernadette and
    Bernard V. Strianese) is ambiguous regardless, so there is nothing to win.
    """
    match = _SURNAME_INITIAL.match(probe.strip())
    if match is None:
        return None
    surname, initial = match.group(1).lower(), match.group(2).lower()
    hits = [
        candidate
        for candidate in tied
        if (words := [w.lower() for w in _name_words(candidate)])
        and surname in words
        and words[0].startswith(initial)
    ]
    return _unique(hits)


def _is_short_for(probe: str, name: str) -> bool:
    """Whether ``probe`` is a whole reference to ``name``, not a fragment of it.

    True when the token is exactly what ``name`` *ends* with -- for a person the
    surname, for an entity its distinctive tail. That is what separates a rival
    reading from a coincidence: "Bloomberg" is how you refer to Michael
    Bloomberg, whereas the "J.P. Morgan" buried inside "Bank of New York
    Mellon, Securities Administrator for J.P. Morgan Acquisition Trust
    2006-WMC4" is a modifier in a trust's legal name and refers to nobody.
    """
    token = _normalize(probe)
    words = _name_words(name)
    return any(
        _normalize("".join(words[start:])) == token
        for start in range(len(words))
    )


def _named_from_the_start(probe: str, tied: list[str]) -> str | None:
    """The one tied candidate the token names from its beginning.

    A token that matches inside two names usually belongs to the one it *opens*
    (``JPMorgan`` -> "J.P. Morgan Mortgage Acquisition Corporation", not the
    trust that carries "J.P. Morgan" mid-name; ``WyomingCountySoil`` -> the
    conservation district itself, not the joint board of two of them).

    Unless some other tied candidate is one the token is a whole reference to,
    in which case both readings are live and this declines to choose --
    ``Bloomberg`` fits "Bloomberg L.P." from the start but is also exactly how
    one refers to "Michael Bloomberg", and the docket has both.
    """
    starters = [
        candidate
        for candidate in tied
        if _normalize(candidate).startswith(_normalize(probe))
        or _normalize(probe).startswith(_normalize(candidate))
    ]
    winner = _unique(starters)
    if winner is None:
        return None
    rivals = [c for c in tied if _normalize(c) != _normalize(winner)]
    if any(_is_short_for(probe, rival) for rival in rivals):
        return None
    return winner


def _break_tie(probes: list[str], tied: list[str]) -> str | None:
    """One winner among candidates a tier scored equally, or None.

    Applied at whichever tier tied, because which one that is depends on the
    token: ``JPMorgan`` ties on containment, ``ColeS`` on word overlap.
    """
    for resolve in (_by_given_initial, _named_from_the_start):
        for probe in probes:
            winner = resolve(probe, tied)
            if winner is not None:
                return winner
    return None


def _unique(candidates: list[str]) -> str | None:
    """The one candidate in ``candidates``, or None when they disagree.

    Two candidates that normalize alike are one name written twice -- the same
    party as the FILINGS table and the attorney table spell it -- so that is
    not a disagreement.
    """
    if not candidates:
        return None
    if len({_normalize(candidate) for candidate in candidates}) > 1:
        return None
    return candidates[0]


def align_party_name(
    party: str | None, candidates: Sequence[str]
) -> tuple[str | None, str | None]:
    """Resolve a file-name party segment to a party name the docket states.

    Court-PASS names a file after a squashed short form of the filer
    (``1995CAM``, ``Scharf``, ``CityofNY``) while the FILINGS table and the
    ATTORNEY DETAILS section carry the party's full name (``1995 CAM LLC``,
    ``Joseph Scharf``, ``City of New York``). An entry synthesized from a file
    name therefore reads worse than every entry beside it, for no reason other
    than which page it came off. This picks the docket's own wording for it.

    Returns ``(name, tier)`` -- the resolved name and how it was reached, or
    ``(None, None)`` when nothing in ``candidates`` matched well enough to say.
    Tiers, strongest first:

    * ``'exact'`` / ``'containment'`` -- :func:`_party_score` at 1.0 / 0.9,
      the same string agreement that links files to FILINGS rows.
    * ``'initialism'`` -- the token is a run of the candidate's initials
      (``NYCTA``, ``DHCR``, ``SNY``).
    * ``'subsequence'`` -- the token's letters run through the candidate in
      order from one of its word boundaries, which is what survives a filer
      abbreviating mid-name or misspelling (``IroquoisCSD``, ``DLJMortage``,
      ``Wiliam``).
    * ``'overlap'`` -- significant-word overlap, the weakest tier
      (``Alf`` -> "Christopher J. Alf").

    Every tier requires the winner to be *unique*. A tie is usually two
    relatives or two co-parties, where picking wrong is worse than not picking,
    so it falls to :func:`_break_tie` -- which resolves only the two ties that
    carry their own evidence (a pinned-on given initial, and a token that opens
    one of the names) and otherwise leaves the file name's word in place
    (``Bennett`` against both Joseph and Tracey Bennett).
    """
    if not party or not candidates:
        return None, None
    probes = _party_probes(party)

    scored = [
        (score, candidate)
        for probe in probes
        for candidate in candidates
        if (score := _party_score(probe, candidate)) >= 0.9
    ]

    def decide(tied: list[str], tier: str) -> tuple[str | None, str | None]:
        winner = _unique(tied) or _break_tie(probes, tied)
        return (winner, tier) if winner else (None, None)

    if scored:
        best = max(score for score, _ in scored)
        tier = "exact" if best >= 1.0 else "containment"
        return decide([name for score, name in scored if score == best], tier)

    for probe in probes:
        token = _normalize(probe)
        if not 2 <= len(token) <= _MAX_INITIALISM_LEN or not token.isalpha():
            continue
        hits = [c for c in candidates if token in _initialism(c)]
        if hits:
            return decide(hits, "initialism")

    for probe in probes:
        token = _normalize(probe)
        if len(token) < _MIN_SUBSEQUENCE_LEN:
            continue
        hits = [
            c
            for c in candidates
            if _is_subsequence(token, _normalize(c))
            and _anchored_at_word(token, c)
        ]
        if hits:
            return decide(hits, "subsequence")

    overlaps = [
        (score, candidate)
        for candidate in candidates
        if (score := max(_party_score(p, candidate) for p in probes)) >= 0.8
    ]
    if overlaps:
        best = max(score for score, _ in overlaps)
        return decide(
            [name for score, name in overlaps if score == best], "overlap"
        )

    return None, None


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


def _party_name_pool(
    docket_entries: list[dict], party_names: Sequence[str]
) -> list[str]:
    """The party names this docket states, for :func:`align_party_name`.

    FILINGS rows come first and the ATTORNEY DETAILS names after, deduplicated
    on the normalized form. The two agree on 95.5% of the 9034 FILINGS names
    exactly, so the order rarely decides anything; where only one has the party
    it is usually the attorney table missing a pro-se filer or an individual
    amicus, which is why both are pooled.
    """
    pool: dict[str, str] = {}
    for entry in docket_entries:
        name = (entry.get("party") or "").strip()
        if name:
            pool.setdefault(_normalize(name), name)
    for name in party_names:
        name = (name or "").strip()
        if name:
            pool.setdefault(_normalize(name), name)
    return list(pool.values())


def reconcile_files_and_entries(
    files: list[dict],
    docket_entries: list[dict],
    *,
    party_names: Sequence[str] = (),
) -> tuple[list[dict], list[dict]]:
    """Join ``gvFiles`` rows to FILINGS rows in both directions.

    Returns ``(files, entries)`` -- new dicts, inputs are never mutated.

    ``party_names`` are the ATTORNEY DETAILS party names, pooled with the
    FILINGS parties so a synthesized entry can be given the docket's own
    wording for its filer rather than the squashed short form the file name
    carries -- see :func:`align_party_name`.

    Each **file** gains the convention components (``doc_role``,
    ``doc_party``, ``doc_type``, ``volume``, ``part``), its logical-document
    id (``document_group``), a ``link_status``, and -- when it belongs to an
    entry -- ``docket_entry_index``, ``match_confidence``, and the
    ``date_received`` / ``date_due`` only the FILINGS table carries.

    Each **entry** gains ``entry_index`` (so ``(docket_number, entry_index)``
    is a stable composite key for the file -> entry join), the
    ``raw_filing_type`` / ``entry_role`` / ``entry_doctype`` /
    ``filing_type_recognized`` classification, ``file_indexes`` listing its
    zero or more files, ``inferred_from_file``, and ``party_match``.

    Entries are returned in two blocks. The real FILINGS rows come first, at
    their original indexes, followed by one **synthesized** entry per document
    group that no FILINGS row claimed -- each carrying
    ``inferred_from_file=True``, a ``filing_type`` composed from the file
    name, ``raw_filing_type=None`` because no table row said it, and a
    ``party`` aligned onto the docket's own wording where that was possible
    (``party_match`` records the tier). Real indexes therefore never shift,
    and every filer-submitted file ends up under exactly one entry, which is
    what makes each of these a plain group-by:

    * FILINGS rows with no document -> ``file_indexes == []``
    * documents with no FILINGS row -> ``inferred_from_file is True``
    * several files in one such entry -> ``len(file_indexes) > 1``
    * whether those files are fetchable -> join to ``available``
    * whether the absence is expected -> ``entry_doctype`` in
      :data:`NOT_ON_FILINGS_TABLE`

    Court-generated files (``-Decision``, ``-Transcript``, ``-Webcast``) take
    part in synthesis but not in matching: they are the court's own output, so
    they may not claim a FILINGS row, but they do get an entry of their own.
    They come back ``link_status='court_generated'`` rather than ``'inferred'``
    -- both have a synthesized entry, only one is something a party filed.
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
            docket_entry_id=None,
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
    # Ordinal is taken over FILINGS table order. The table is sorted by
    # date_due ascending with blank-due rows first (100% of 3210 tables), so
    # this only matters for rows sharing a (filing_type, party) -- 124 such
    # groups, 65 of them identical in all four columns. Ordering the ordinal by
    # date_received or date_due instead was measured to be indistinguishable
    # here (same 0 collisions, 0 identity breakage), so table order wins on
    # needing no extra sort.
    row_ordinals = _ordinals(
        [
            (entry.get("filing_type"), entry.get("party"))
            for entry in docket_entries
        ]
    )
    reconciled_entries = [
        {
            **entry,
            "entry_index": entry_index,
            "docket_entry_id": entry_id_from_row(
                entry.get("filing_type"), entry.get("party"), ordinal
            ),
            "raw_filing_type": entry.get("filing_type"),
            "entry_filing_type": classification.filing_type,
            "entry_role": classification.role,
            "entry_doctype": classification.doctype,
            "filing_type_recognized": classification.recognized,
            "inferred_from_file": False,
            # the table stated the party outright; nothing was aligned
            "party_match": None,
            "file_indexes": [],
        }
        for entry_index, (entry, classification, ordinal) in enumerate(
            zip(docket_entries, classifications, row_ordinals, strict=True)
        )
    ]

    if not parsed_all:
        return linked, reconciled_entries

    groups = _group_volumes(parsed_all)
    for group_index, group in enumerate(groups):
        for file_index in group.file_indexes:
            linked[file_index]["document_group"] = group_index

    # Ordinals span *all* groups, not just the unclaimed ones, so a group's id
    # does not shift when a sibling with the same key stops being claimed by a
    # FILINGS row.
    group_ordinals = _ordinals([_group_id_key(g.parsed) for g in groups])

    # How many FILINGS rows share each (role, doctype). Where that is more
    # than one, the shape cannot identify a row on its own and the party name
    # is the only thing left that can -- see the rivals veto below.
    shape_counts = collections.Counter(
        (classification.role, classification.doctype)
        for classification in classifications
    )

    candidates: list[_Candidate] = []
    for entry_index, classification in enumerate(classifications):
        entry = docket_entries[entry_index]
        entry_role, entry_doctype = classification.role, classification.doctype
        has_rivals = shape_counts[(entry_role, entry_doctype)] > 1
        for group_index, group in enumerate(groups):
            parsed = group.parsed
            if parsed.is_court_generated:
                # The court's own output is never a filing, so it must not be
                # able to claim a FILINGS row -- a decision is not the
                # appellant's brief. It still gets a synthesized entry below.
                continue
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
            role_contradicted = False
            if entry_role and parsed.role:
                if parsed.role == entry_role:
                    role_score, role_exact = 1.0, True
                elif (entry_role, parsed.role) in _COMPATIBLE_ROLES:
                    role_score = 0.4
                elif not doctype_exact:
                    continue
                else:
                    role_contradicted = True
                # An exact document type outranks the stated role. Filers get
                # the role wrong in both directions -- naming the opposing
                # party's side, or the side an amicus supports -- and vetoing
                # on it cost matches where the type and the party name both
                # agreed exactly (``-app-Audthan-JointRecord`` against
                # "Respondent COA Record | Audthan LLC"). Role contributes no
                # score here, so the party name decides between rivals.

            party_score = _party_match_score(parsed.party, entry.get("party"))
            # ...but the waiver above is only as good as the evidence left
            # standing once the role is set aside, and an exact doctype alone
            # is not evidence about *whose* filing this is: every brief on the
            # docket has doctype ``brf``. With the role contradicted and the
            # party silent there is nothing tying this file to this row, so
            # the pairing is decided by nothing but which rivals were already
            # claimed -- an amicus brief landing on "Respondent Brief |
            # Attorney General", a party's own brief on an opponent's row.
            # The motivating case for the waiver had the party agreeing
            # exactly, so requiring any positive party signal keeps it and
            # drops only the matches that were guesses.
            if role_contradicted and party_score == 0:
                continue

            # Same reasoning one step further: when the docket states several
            # rows of this exact shape, matching the shape says only "one of
            # these", and with the party silent there is nothing to say which.
            # The pairing then falls out of candidate order -- which is how a
            # docket's amicus briefs came to be dealt round its amicus rows,
            # each brief wearing the next filer's name. Better the synthesized
            # entry below, which claims no party and no dates, than a row
            # picked by position. Rows with no same-shape rival are unaffected:
            # there the shape *is* identifying.
            if has_rivals and party_score == 0:
                continue
            # Require at least one *positive* signal. Without this a file whose
            # doctype token is unreadable skips the doctype veto above
            # (``doctype_score = 0.4``) and can claim any FILINGS row left over
            # in the docket purely by elimination, inheriting a date_received
            # nothing tied it to -- an opposition to a leave motion landing on
            # the Appellant Brief row, a record volume on a Respondent Brief.
            # A merely *compatible* role is not evidence: it is what admitted
            # those matches in the first place. Such a file is better served by
            # the synthesized entry it gets below, which claims no dates.
            if doctype_score < 0.8 and not role_exact and party_score == 0:
                continue

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
                docket_entry_id=entry["docket_entry_id"],
                match_confidence=confidence,
                date_received=entry.get("date_received"),
                date_due=entry.get("date_due"),
                link_status="matched",
            )

    # Synthesize an entry per document group no FILINGS row claimed, so every
    # filer-submitted file hangs off exactly one entry. Appended after the
    # real rows, so real entry_index values stay put.
    pool = _party_name_pool(docket_entries, party_names)
    for group_index, group in enumerate(groups):
        if group_index in claimed_groups:
            continue
        parsed = group.parsed
        entry_index = len(reconciled_entries)
        # Keyed on the *raw* segment, deliberately. The id has to mean the same
        # thing on every run, and the aligned name depends on an attorney table
        # that gains and loses parties between scrapes -- a party dropping off
        # it would silently re-key the entry.
        entry_id = entry_id_from_document(parsed, group_ordinals[group_index])
        aligned, party_match = align_party_name(parsed.party, pool)
        reconciled_entries.append(
            {
                "filing_type": describe_filing(parsed.role, parsed.doctype),
                "party": aligned or parsed.party,
                "party_match": party_match,
                "date_due": None,
                "date_received": None,
                "entry_index": entry_index,
                "docket_entry_id": entry_id,
                # nothing on the page said this; it is read off the file name
                "raw_filing_type": None,
                "entry_filing_type": None,
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
                docket_entry_id=entry_id,
                match_confidence=None,
                # 'court_generated' is kept rather than folded into 'inferred':
                # both now have a synthesized entry, but only one of them is
                # something a party filed
                link_status=(
                    "court_generated"
                    if parsed.is_court_generated
                    else "inferred"
                ),
            )
    return linked, reconciled_entries
