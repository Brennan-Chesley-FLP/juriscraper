# Delaware CourtConnect (courtconnect.courts.delaware.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> **Plain HTTP** (`driver_requirements = []`): server-rendered HTML, no bot
> protection, no cookies, no session state. Scope is **appellate**: `delch`
> (Chancery, in full), `delsuperct` (Superior Court sitting as Delaware's
> intermediate appellate court) and `delctcompl` (Common Pleas hearing JP
> appeals) — reached by **speculative enumeration over six number spaces**,
> which is the only route in: the portal's two name-based searches index
> neither Chancery nor any appellate case type. HTML extraction lives in the
> `parsers/` package (§9); the single step keeps the soft-404 rule, the
> truncated-response guard and the court derivation. Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court`, `docket_number`,
> `assigned_to_str`, `date_*`, `contact_raw`.

CourtConnect is Delaware's public Avenu Insights / Neumo **Contexte** portal.
It fronts every Delaware trial court from one docket-report endpoint, and the
court a case belongs to is encoded in the *shape of its case id* rather than in
any request parameter.

## Site Overview

- **Base URL**: `https://courtconnect.courts.delaware.gov/cc/cconnect`
- **Docket report** (the only endpoint this scraper reads):
  `GET ck_public_qry_doct.cp_dktrpt_docket_report?backto=D&case_id=<id>&begin_date=&end_date=`
  Returns the entire case — description, related cases, event schedule,
  parties, docket entries — as one server-rendered page.
- **Driver requirements**: `[]`. `curl` gets the full page on the first try;
  no challenge, no JS, no cookie handshake. The page carries a 1990s frameset
  app's markup (rollover-image JavaScript, `<font>` tags, unclosed `<tr>`) but
  nothing that needs executing.
- **Rate limit**: 2 req/s. Roughly 250 probes at ~3/s during reconnaissance
  drew no throttling or block, so this is politeness, not a measured ceiling.

### Frameset chrome to ignore

Every `*_idx` URL is a two-frame wrapper whose inner `Big` frame holds the real
page. The scraper addresses the inner endpoint directly and never sees a
frameset. The `*_setup_idx` / `*_redirect` / `cp_main_disclaimer` chain exists
only to walk a human through the disclaimer; none of it sets state the docket
report needs.

The portal's own redirect page is **broken**: `cp_personcase_redirect` builds
its target from the form's `base_url` hidden field and emits
`…/ck_public_qry_cpty.cp_personcase_srch_setup/ck_public_qry_cpty.cp_personcase_details_idx?…`
— a path segment too deep, which 404s. The working URL is the same script name
under `/cc/cconnect/`.

## Courts Covered

| Court | CourtListener ID | Reached via | In scope because |
|---|---|---|---|
| Delaware Court of Chancery | `delch` | `chancery`, `chancery_legacy` | wanted in full |
| Superior Court of Delaware | `delsuperct` | `superior_appeal`, `superior_appeal_archival` | sits as Delaware's intermediate appellate court |
| Delaware Court of Common Pleas | `delctcompl` | `common_pleas`, `common_pleas_legacy` | hears appeals up from the Justice of the Peace courts |

**Delaware's Supreme Court is not on this portal.** The case-type vocabulary
has no Supreme Court family, and every id shape observed resolves to Chancery,
Superior, Common Pleas or JP. Family Court is likewise absent — its records are
confidential. The Justice of the Peace courts are on the portal but have no
appellate jurisdiction, so they are out of scope; `docket_by_number` will still
fetch one on request.

The full id census below covers every shape the portal serves, in and out of
scope, because the scope tests are written against it:

Census from 639 distinct case ids harvested off the party search (2026-09-14),
with the court read from each family's case-type code:

| Shape | n | Example | Court | Case types seen |
|---|---:|---|---|---|
| `JP{C}-{YY}-{NNNNNN}` | 150 | `JP13-22-005065`, `JP9-07-000042` | Justice of the Peace (`deljustpct`) | `60`, `61`, `63` |
| `{County}{YY}{T}-{MM}-{NNN}` | 115 | `N24C-04-195`, `S21C-03-021`, `K09L-11-052` | Superior Court (`delsuperct`) | `CP`, `CF`, `CR`, `CS`, `L3`, `LM` |
| `S{County}{YY}{T}-{MM}-{NNN}` | 110 | `SN00C-03-226`, `SK09J-02-072` | Superior Court (older/archival) | `CR`, `JD`, `JM` |
| `J{NNNNNNNNNN}` | 88 | `J0504023213`, `J0105046113` | Justice of the Peace (legacy) | `60`, `61` |
| `U{NNN}-{MM}-{NNN}` / `-{NNNN}` | 71 | `U497-02-290`, `U500-08-0015` | Court of Common Pleas (`delctcompl`) | `4A`, `4M`, `4N` |
| `{County}{YY}J-{NNNNN}` | 37 | `K21J-01335`, `N26J-02383` | Superior Court judgments | `JE`, `JH`, `JL`, `JM` |
| `CPU{N}-{YY}-{NNNNNN}` | 36 | `CPU4-23-000459`, `CPU6-20-000527` | Court of Common Pleas | `4B`, `4K`, `4L`, `4X` |
| `S{County}{YY}{T}-{MM}-{NNN}J` | 11 | `SN01C-03-176J`, `SN94J-03-071J` | Superior Court judgments | `JB`, `JS` |
| `{YYYY}-{NNNN}` | 4 | `2024-0360` | **Court of Chancery (`delch`)** | `2A` |
| bare `{N...}` | 6 | `11087`, `5195` | **Court of Chancery (legacy)** | `2A` |
| assorted legacy | ~10 | `13-87-C1227`, `JP 13 87 C5610`, `JP17-85-C-1190`, `86-4449`, `N21-00360` | mostly JP, one Superior judgment | `60`, `63`, `64`, `JH` |

County letters are `N` New Castle, `K` Kent, `S` Sussex; the type letter is `C`
civil, `L` lien/mortgage, `J` judgment, `T` monitions.

**Shape does not determine court — the case-type code does.** The two cross-cut:
`J0001016812` looks like a judgment id but is `61 - JP LANDLORD TENANT`, and
`SK03T-10-001` is a Superior Court monitions judgment despite the Sussex/Kent
double prefix. The type-code families are `2*` Chancery, `3*`/`C*`/`L*`/`M*`
Superior, `4*` Common Pleas, `6*` Justice of the Peace, `J*` judgment dockets
(whose second letter names the *originating* court: `JD` Common Pleas, `JL`
Justice of the Peace, `JE` criminal, `JH` Division of Revenue).

Every **modern** non-Chancery id carries a leading county or court letter, so
the `{YYYY}-{NNNN}` space cannot collide with them. The **bare-integer** space
is the exception and is shared — see "Legacy Chancery numbering" below.

### How the court is determined

The page never names its court. The only signal it carries is the leading
character of the **case-type code** on the Type line:

    Type:  2A - CIVIL ACTIONS      ->  "2" -> delch

`models.CASE_TYPE_COURTS` maps that character; anything unmapped falls back to
the court the seed supplied. Mapped families, each checked against a live
docket on 2026-09-14:

| Prefix | Court | Evidence |
|---|---|---|
| `2` | `delch` | All 110 `{YYYY}-{NNNN}` cases sampled returned `2A - CIVIL ACTIONS`, on pages naming the Register in Chancery and sitting Vice Chancellors (ZURN, GIBBS, MOLINA). |
| `A` | `delsuperct` | `N24A-01-001`, `S24A-01-001`, `K24A-02-001`. |
| `C`, `L` | `delsuperct` | `N24C-04-195`, `N19L-10-078`. |
| `4` | `delctcompl` | `CPU4-23-000459`, `U497-02-290`. |
| `6` | `deljustpct` | `JP13-22-005065`, `J0105046113`. |
| `3` | `delsuperct` | Not confirmed live; every `3*` label in the site's own vocabulary reads "SUPERIOR CT …". |

Deliberately **unmapped**, so they fall back rather than guess: `J` (judgment
dockets, whose second letter names the *originating* court — `JD` Common Pleas,
`JL` Justice of the Peace, `JH` Division of Revenue — while the docket itself is
Superior Court's), and `D`/`M`/`N`/`I`/`Z`, none of which were observed.

The case-type dropdown lists three other Chancery families — `2D` technology
disputes, `2G` guardianships, `2M` miscellaneous, `2T` trusts — none of which
turned up in the number space. They would still resolve to `delch` through the
same `2` prefix if they appear.

## Search Capabilities

| Rank | Mode | Verdict |
|---|---|---|
| 1 | Date-based search | **Does not exist.** No endpoint takes a filing-date window as its primary key. |
| 2 | Case number | **The docket report.** Takes a bare `case_id`; no court parameter, no result list — it either renders the case or says "No case was found." |
| 3 | Party name (`cp_personcase_srch_setup`) | **Reaches no case this scraper wants.** |
| 4 | Judgment search (`search_option=judge`) | Judgments against a person; same index as the party search. |

**Recommended approach: speculative enumeration.** It is not a preference — it
is the only access path. A party search for `SMITH` with `case_type=2A` returns
"No records found", while the same search with `case_type=ALL` returns hundreds
of Superior Court, CCP and JP rows: Chancery parties are simply not in the
person index. The same filter returns nothing for **every appellate type
tried** (`AA`, `AB`, `AC`, `AD`, `AF`, `3A`, `CA`, `4M`) against several common
surnames, so the person index is no route to the appellate dockets either.

The party search *does* accept a `begin_date`/`end_date` filing-date window,
but only alongside a required last name, so it cannot enumerate a date range
on its own even for the courts it does index.

### Docket-report parameters

`begin_date` / `end_date` nominally bound the docket-entry window
(`DD-MON-YYYY`). The scraper sends them empty because the site's own form
always sends them, but a populated window (`01-JAN-2024`..`31-DEC-2024` against
a case with entries spanning 2022–2025) returned the identical 23 entries — so
they are not usable for paging or filtering. There is no pagination anywhere on
the report; an 85 KB docket renders all its entries in one page.

## Docket Number Format (`delch`)

- **Shape**: `{YYYY}-{NNNN}` — four-digit filing year, hyphen, zero-padded
  four-digit sequence restarting each January.
- **This format starts in 2017.** `2017-0001` resolves; 2016, 2015 and 2014
  return "No case was found" at 0001, 0100 and 0500 alike. That is a change of
  *format*, not the start of coverage — see "Legacy Chancery numbering" below,
  which reaches back to 2007 and is **not** covered by any entry point today.
- **Density**: a contiguous scan of `2024-0001..0060` found exactly one missing
  number (`2024-0007`) and no run of two. `gap=25` is therefore generous.
- **Highest observed per year** (2026-09-14), also in `scraper.SEED_HINTS`:

  | Year | ≈ highest | Year | ≈ highest |
  |---|---|---|---|
  | 2019 | 1000 | 2023 | 1300 |
  | 2020 | 1100 | 2024 | 1300 |
  | 2021 | 1100 | 2025 | **1507** (last of the year) |
  | 2022 | 1200 | 2026 | 1100 (open) |

  Volume grows steadily: ~1,000/year in 2019 to ~1,500 in 2025.

### Legacy Chancery numbering (pre-2017) — NOT YET COVERED

Before 2017, Chancery used a **flat, continuous integer** with no year part and
no padding, and the portal still serves those cases. Verified 2026-09-14:

| Case id | Filed | Type |
|---|---|---|
| `3000` | 2007-06-05 | `2A - CIVIL ACTIONS` |
| `5000` | 2009-10-28 | `2A - CIVIL ACTIONS` |
| `8000` | 2012-11-01 | `2A - CIVIL ACTIONS` |
| `10000` | 2014-08-04 | `2A - CIVIL ACTIONS` |
| `13013` | 2016-12-30 | `2A - CIVIL ACTIONS` |
| `13014`+ | — | miss |

The sequence ends at **13013 (30 December 2016)** and `2017-0001` picks up the
next business day — a clean format changeover, not a gap.

**Density rises with recency**, so this is a partial archive, not a full one:
a 30-wide contiguous scan found 30/30 hits at 11000 and at 9000, 15/30 at 6000,
and roughly 1-2/30 around 3000. Practically: complete from ~2013, patchy
2010-2012, sparse before that.

**The bare-integer space is shared, and low numbers are not Chancery.** `1`,
`2` and `500` are Justice of the Peace cases (`61 - JP LANDLORD TENANT`,
`69 - JP DEBT FOR CRIMINAL TRANSFER`) filed 2013-2019 — unrelated to the
Chancery run, which only starts somewhere below 3000. A speculative entry over
this space must therefore **not** assume `delch`; it has to take the court from
the case-type code, which `_court_for` already does (`2` -> `delch`), and drop
or re-court anything that comes back non-`2`.

Adding this would be a second entry — a flat `SpeculativeRange` (or
`CourtRange`) over roughly `2800..13013`, ~13,000 probes for ~10,000 cases —
rather than a change to `dockets_by_number`, whose param is year-partitioned by
construction.

## The six number spaces

Scope is **appellate**: Chancery in full, Superior Court sitting as Delaware's
intermediate appellate court, and Common Pleas hearing appeals up from the
Justice of the Peace courts. That lands on six distinct number spaces, because
two of these courts renumbered and because a docket can be partitioned by
county, month and unit at once.

| Space | Format | Era | Partitioned by | Scope test |
|---|---|---|---|---|
| `chancery` | `{YYYY}-{NNNN}` | 2017→ | year | court is `delch` |
| `chancery_legacy` | flat integer, ≤13013 | →2016 | — | court is `delch` |
| `superior_appeal` | `{County}{YY}A-{MM}-{NNN}` | 2009→ | county, year, month | none needed |
| `superior_appeal_archival` | `S{County}{YY}A-{MM}-{NNN}` | 1991–2008 | county, year, month | none needed |
| `common_pleas` | `CPU{unit}-{YY}-{NNNNNN}` | 2009→ | unit, year | case type is an appeal |
| `common_pleas_legacy` | `U{unit}{YY}-{MM}-{NNN}` | 1993–2008 | unit, year, month | case type is an appeal |

All six share **one** entry, `dockets_by_number`, whose `DeCaseRange` param
carries the space plus its partition and renders `min` into that space's case
id. It has to be one entry: a speculative entry is dispatched with only its
speculative param, so the space cannot be a separate argument.

### Why each space has the scope test it does

- **Superior's `A` dockets need no test.** The `A` type letter *is* the
  appellate docket — every case in the space carries an `A*` case type (`AA`
  administrative agency, `AB` from Common Pleas, `AC` certiorari, `AD`
  industrial accident board, `AE` public service commission, `AF`
  unemployment, `AG` marijuana commission, `AH` purchaser card, `AI` board of
  assessment).
- **Chancery is wanted as a court**, so the test only exists to drop the
  handful of unrelated Justice of the Peace cases sharing the low end of the
  pre-2017 integers.
- **Common Pleas interleaves.** A JP appeal carries an ordinary `CPU…` number
  indistinguishable from a first-instance debt claim, so the only separator is
  the case type (`4L`, `4M`, `4P`, `4Q`, `4R`, `4S`, `4T`, `4Y`). Expect to
  discard most of what you fetch — a 15-case slice of `CPU4-14` yielded 3
  appeals.

A filtered-out case is **not** a speculation miss: the step emits nothing but
the probe still counts as a hit, so the walk keeps going. That is the
difference between "this partition is exhausted" and "this case is not ours".

### Sequence widths and other formatting traps

- Chancery legacy integers are **unpadded** — the site serves `5195` and
  `13013`, never `05195`.
- Legacy Common Pleas pads the sequence to a width that depends on the
  **unit, not the year**: 3 digits for units 4 and 6, 4 digits for unit 5.
  Verified by probing the same month of 2000 and 2005 across units —
  `U400-05-001` and `U500-05-0001` both hit, while `U400-05-0001` and
  `U500-05-001` both miss.
- **Legacy Common Pleas ids carry a type suffix**, and it is part of the id:
  `U598-01-0094AP` is a JP appeal (`4M`), while `U598-01-0094` — the same
  number without the suffix — does not exist. `U501-05-0047NC` is a
  change-of-name petition. One monthly sequence is shared between the
  suffixed and unsuffixed forms (`U598-01-0001`, `0010` and `0050` exist bare;
  `0090` and `0094` exist only as `…AP`).
- A malformed id does not fail loudly; it just misses, and a run of misses
  reads as an empty partition. `DeCaseRange` therefore rejects a template
  missing any component its space is addressed by, rather than letting `None`
  format into the URL.

### Seeding

Use `seed_templates(space, years=None)`, which expands the partition grid —
writing 36 templates per year by hand for the county-and-month-partitioned
Superior dockets is impractical:

```python
from .models import DeNumberSpace
from .scraper import seed_templates

seed_params = [
    {"dockets_by_number": {"docket_number": template}}
    for space in (DeNumberSpace.CHANCERY, DeNumberSpace.SUPERIOR_APPEAL)
    for template in seed_templates(space)
]
```

Template counts over each space's full observed span: `chancery` 10,
`chancery_legacy` 1, `superior_appeal` 648, `superior_appeal_archival` 648,
`common_pleas` 54, `common_pleas_legacy` 576.

A **closed** partition is a finite set — seed it `should_advance: false` so the
driver does not spend a `gap`-length tail proving what the calendar already
settled. Only the current year should advance.

### Cost, before you seed Common Pleas

The spaces differ by three orders of magnitude in yield per probe, so seed them
deliberately rather than all at once:

| Space | ≈ probes | ≈ records kept |
|---|---:|---:|
| `chancery` (2017–2026) | 14,000 | 13,000 |
| `chancery_legacy` (2007–2016) | 13,000 | ~10,000 |
| `superior_appeal` (2009–2026) | 12,000 | ~2,000 |
| `superior_appeal_archival` (1991–2008) | 12,000 | ~2,000 |
| `common_pleas` (2009–2026) | **~200,000** | ~20,000 |
| `common_pleas_legacy` (1993–2008) | **~100,000** | ~10,000 |

Common Pleas is roughly 85% of the total request budget for roughly 25% of the
records, and every one of those records is a Justice of the Peace appeal heard
by a court CourtListener types as `trial`. At 2 req/s the two Common Pleas
spaces are about 40 hours of wall clock.

### Caveat: `common_pleas_legacy` is the least-established space

It is wired up and its id rendering is verified against four live ids, but it
is **not ready for a production sweep**, for two reasons:

1. **The suffix vocabulary is not established.** `AP` is confirmed for `4M`
   (JP appeal with fees) and `NC` for `4N` (change of name). What `4L` (JP
   appeal *without* fees) uses here is unknown — in the modern `CPU` space
   `4L` carries no suffix at all. `seed_templates` seeds `suffix="AP"`, so
   any appeal filed under a different suffix is currently unreachable.
2. **Speculation cannot find its own end.** Appeals are a sparse minority of a
   shared monthly sequence (`0090AP` and `0094AP` hit; `0010AP` through
   `0070AP`, and `0110AP` onward, all miss), so a gap-based walk stops at the
   first quiet stretch. Seed it as a bounded sweep — `should_advance: false`
   with `soft_max` past the month's highest number — not as a walk.

Resolving (1) needs a pass that sweeps a few unit-months in *both* forms and
tabulates suffix against case type. Until then the other five spaces are the
complete ones.

### Known gap: `CA` appeals on Superior's civil docket

`CA - AUTO ARBITRATION APPEAL` is an appellate case type that sits on Superior
Court's ordinary `{County}{YY}C-{MM}-{NNN}` civil docket, not on the `A`
docket. Reaching those means walking the entire Superior civil space — the
largest on the portal — for one minor type, so it is **not covered**. `CA` is
in `APPEAL_CASE_TYPES` already, so adding a `superior_civil` space later would
pick them up with no other change.

## Data Available

### Case Description

| Field | Notes |
|---|---|
| `docket_number` / `docket_number_raw` | `2025-1110` |
| `case_name` | **Truncated by the site to ~50 characters** ("MIAMI BEACH FIRE & POLICE PENSION FND v JBS WISCON"). There is no full caption anywhere on the portal. |
| `date_filed` | Printed as `Thursday , February 27th, 2025` — padded weekday, padded month, ordinal day. |
| `case_type` / `case_type_code` / `case_type_description` | `2A - CIVIL ACTIONS` |
| `status_code` / `status_description` | `CLOSED - CLOSED` or `ACTIVE - ACTIVE`; the halves were identical on every case sampled. Some non-Chancery cases print `none`, which is normalised away. |

### Case Parties

One row per party, judge **and** attorney — CourtConnect has no separate judge
or attorney table. `assigned_to_str` on the docket is derived from the `JUDGE`
row; every Chancery case sampled had exactly one.

| Field | Notes |
|---|---|
| `sequence_number` / `associated_sequence_number` | "Seq #" and "Assoc". Assoc is how an `ATTORNEY` row names the party it represents. |
| `id_code` | `@4209677` (case-specific party record) or `002234` (bar-registered attorney/judge). See the caveat below. |
| `party_type` | `PLAINTIFF`, `DEFENDANT`, `JUDGE`, `ATTORNEY`; elsewhere on the portal also `SHERIFF`, `COMMISSIONER`, `MEDIATOR`, `ATTORNEY FOR PLAINTIFF`, … |
| `name`, `date_terminated`, `contact_raw`, `aliases` | `unavailable` / `none` placeholders normalised to `None` / `[]`. |

**The `id_code` is captured but never followed.** The page links each id to
`cp_personcase_details_idx?…&id_code=<id>`, but that lookup is broken: an
id-only query returns "9. Search criteria entered is invalid", and the name
search that would otherwise reach the person record returns nothing at all for
Chancery case types. The id is kept anyway — it is the only stable identifier
the portal gives a person, and it joins parties across cases without name
matching.

### Docket Entries

| Field | Notes |
|---|---|
| `date_filed` / `time_filed` | One cell, `<br>`-separated. Read whole it says "30-SEP-202511:37 AM". |
| `description` | `CIVIL ACTION CASE FILED` |
| `name` | The filing party, as printed. |
| `monetary` | Blank on every Chancery entry; judgment dockets carry amounts in the entry text instead. |
| `entry_text` | The "Entry:" continuation row, newlines preserved (the court pre-formats it: numbered lists, tab-aligned amounts, a trailing `DATE DOCKETED:` line). Absent on some entries. |
| `sequence_number` | Page order, so same-day entries stay ordered. |

**Chancery dockets on CourtConnect are stubs.** 111 of 112 sampled cases had
exactly one or two entries, all variants of `CIVIL ACTION CASE FILED`, whose
text says the real docket and pleadings are available only through
**File & ServeXpress** (paid) or a public terminal in the Register in Chancery.
Other Delaware courts publish real registers of actions through the same table
(a Superior Court judgment case sampled had 23 entries). Do not expect Chancery
docket *activity* from this source — expect case existence, caption, filing
date, judge, parties and counsel.

### Related Cases / Case Event Schedule

Both sections render on every report and were **empty on all 128 cases
sampled** (110 Chancery across 2017–2026, plus 18 from Superior Court, Common
Pleas and JP reached through the party search). Their column sets have
therefore never been observed.

Rather than guess a shape, `parsers/sections.py` reads both generically: each
row is zipped against the table's `<th>` labels and stored as a `{label:
value}` map, with recognised columns promoted onto named fields and the rest
kept in `extra_fields`. When a populated one finally appears, `jent residuals`
will surface the real columns and the mapping can be tightened.

Event-schedule rows are emitted as **`DeCourtConnectDocketEntry`** tagged
`source_section="case_event_schedule"`, not as a separate record type: a
future-dated calendar entry is a docket entry.

### Documents

**None.** No sampled page linked a file of any kind — no PDF, no image, no
attachment. Chancery's own docket text is explicit that the pleadings live
behind File & ServeXpress. There are no `archive=True` requests in this
scraper.

## Email Notifications

**Not available.** The portal has no subscribe/notify affordance of any kind —
no "email me about this case" link on the docket report, and nothing in the
search hub (`cp_main_srch_options`), which offers exactly three options: party
search, judgment search, docket report.

## Oral Arguments Calendar

**Not available** on this host. CourtConnect is a case-records portal only.
Chancery's own site (`courts.delaware.gov/chancery`) publishes calendars
separately; that would be a different scraper.

## Bot Protection Notes

None. No hidden form tokens, no ViewState, no session cookie, no referer check,
no user-agent check. The docket report is fully addressable by URL.

Two response quirks that are *not* bot protection but do need handling:

1. **Soft-404.** A case id that does not exist returns **HTTP 200** with the
   Report Selection Criteria block and the single line "No case was found." in
   place of the case. `actually_successful` detects it, which is what stops
   speculation. The step checks for it **again** — the driver tracks the
   speculation outcome but runs the continuation regardless, so without the
   second check every probe past the end of a year raises on the absent Case
   Description table.
2. **Truncated bodies.** Roughly 1 probe in 250 came back HTTP 200 with a
   122-byte fragment of the `<head>`. A truncated page is indistinguishable
   from a miss by content alone, so the step requires the footer marker
   (`id="docket-nav"`) and raises `TransientException` without it — turning a
   dropped connection into a retry instead of a phantom hole in the number
   space.

## Markup Quirks (why the parsers look the way they do)

- **Unclosed `<tr>` and `<td>`.** Neither the parties table nor the docket
  table closes a record's main row before the continuation row. lxml repairs
  this by flattening them into *siblings*, so a party is a 6-cell row followed
  by a 4-cell Address/Aliases row followed by a 1-cell spacer, and an entry is
  a 4-cell row followed by a 2-cell "Entry:" row followed by a spacer. Both
  parsers therefore group by **cell count**, not by descent.
- **Unclosed `<a name="…">` section anchors.** Sections are marked, not
  wrapped, so a section's tables cannot be selected by descent.
  `parsers/sections.py:section_tables` counts instead: the section's tables are
  the leading `count(tables after start anchor) - count(tables after end
  anchor)` — arithmetic that needs no element identity, which `PageElement`
  does not define.
- **`&nbsp;` opens every value cell**, and `\xa0` is in `str.split`'s
  whitespace set, so `clean_text` handles it without a special case.
- **`<br>` inside cells** carries the date/time split and every address line
  break. `text_content()` drops it; `cell_lines` reads the text nodes
  individually.
- **Two label/value tables of identical shape.** The Report Selection Criteria
  block (echoing the request) precedes the Case Description block. The
  description parser selects on the `Filing Date:` label, which only the second
  has.
- **The case id and caption share one cell**, separated by a newline and a
  dash. The split is on that newline, not on `" - "` anywhere, so a caption
  containing a dash survives intact.

## Scraper Architecture

### Entry points

| Entry | Addressing arg | Purpose |
|---|---|---|
| `dockets_by_number(docket_number: DeCaseRange)` | a space + its partition | The workhorse, covering all six number spaces. Speculative, so it takes **only** its speculative param (§4) — which is exactly why the space rides *inside* `DeCaseRange` rather than being a second argument. `court_id` on the param is the space's expected court; the court actually recorded comes from the page. |
| `docket_by_number(court_id: str, docket_number: str)` | a known case id | Single-record lookup. Accepts any Delaware case id the portal serves, in scope or not — the caller asked for this specific case, so no scope filter applies. Must be a **generator**: the driver seeds a non-speculative entry with `yield from`, and returning a bare `Request` fails at run open. |

### Flow

One request per case; there is nothing to follow.

```
dockets_by_number / docket_by_number
  -> parse_docket_report (priority 2)
       CaseDescriptionParser  -> case metadata
       PartiesParser          -> parties (litigants, judges, attorneys)
       DocketEntriesParser    -> docket entries
       CaseEventsParser       -> scheduled events, as docket entries
       RelatedCasesParser     -> related cases
     -> ParsedData(DeCourtConnectDocket)
```

`deduplication_key` is `docket_report:{case_id}`.

### Models

`DeCourtConnectDocket` (top level) → `DeCourtConnectParty`,
`DeCourtConnectDocketEntry`, `DeCourtConnectRelatedCase`.

## Verification (2026-09-14)

- Offline: `uv run python -m pytest juriscraper/state/delaware/courtconnect_courts_delaware_gov/test.py`
  — 37 tests over inline fixtures, including a case-id round-trip for every
  space against ids confirmed live, and the scope filter's truth table.
- Corpus: all 5 parsers over 112 saved pages (94 Chancery + 18 other courts) —
  0 parse failures, 0 model-validation failures. Every parse failure in the
  wider file set corresponded exactly to a soft-404 page.
- Live, Chancery: `dockets_by_number` seeded `2025-1495..1510` plus one
  `docket_by_number` for `N24J-02982` — 24 requests, 0 errors, 14 records,
  speculation stopped correctly after `2025-1507`.
- Live, multi-space: Superior appeals (New Castle, Jan + Jun 2024), Chancery
  legacy (`12995..13015`) and a Common Pleas slice (`CPU4-14-003170..3185`) —
  74 requests, 0 errors, 32 records: 10 Superior appeals (`AA`/`AB`/`AC`/`AD`/
  `AF`, court `delsuperct`), 19 Chancery legacy (`2A`, `delch`) and 3 Common
  Pleas JP appeals (`4L`, `delctcompl`), the scope filter having discarded the
  rest of the Common Pleas slice.
- `jent residuals` over that run: 6 clusters, all page chrome (section
  headings, table headers, the "No … were found" placeholders, the soft-404
  sentinel). No unclaimed data on the page.
