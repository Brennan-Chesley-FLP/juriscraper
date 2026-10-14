# California Appellate Courts Case Information — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Single speculative entry `dockets_by_number(docket_number: CaCourtRange)`
> covers all nine courts/divisions. The target court can't be a separate
> `court_ids` argument — the driver dispatches a speculative entry with only
> its speculative param (see §4 "Multi-court speculative entries") — so it
> rides inside the param: `CaCourtRange` (a shared
> [`CourtRange`](../../../../state/common/params.py)) carries the
> CourtListener `court_id` and translates it to the site case-number prefix
> via `COURT_CONFIG`. Seed once per court (`SEED_HINTS` lists each
> `highest_observed`). Court ids match the classic juriscraper opinion
> scrapers — including a distinct id per Fourth-District division
> (`calctapp_4th_div1/2/3`) — so every prefix maps 1:1 to a court id. HTML
> extraction lives in the `parsers/` package (§9); steps keep navigation
> (tab-URL building, multi-result fan-out, archive requests, transient
> detection).

## Site Overview
- **Base URL**: https://appellatecases.courtinfo.ca.gov
- **Requires Playwright**: Yes -- bot protection (Imperva/Incapsula JS challenge blocks httpx/curl; returns 200 with obfuscated JS payload instead of HTML)
- **Framework**: ColdFusion (`.cfm` pages), server-rendered HTML behind JS challenge gate
- **Search types**: Case Number, Party Name, Attorney, Case Caption (no date-based search for cases)
- **Calendar**: Date-based search for oral arguments only

## Courts Covered

| `dist` Param | Display Name | Docket Prefix | Highest Observed | CourtListener ID |
|--------------|-------------|--------------|-----------------|-----------------|
| 0 | Supreme Court | S | S295928 | `cal` |
| 1 | 1st Appellate District | A | A175975 | `calctapp_1st` |
| 2 | 2nd Appellate District | B | B343601 | `calctapp_2nd` |
| 3 | 3rd Appellate District | C | C102353 | `calctapp_3rd` |
| 41 | 4th Appellate District Div 1 | D | D087818 | `calctapp_4th_div1` |
| 42 | 4th Appellate District Div 2 | E | E088098 | `calctapp_4th_div2` |
| 43 | 4th Appellate District Div 3 | G | G066312 | `calctapp_4th_div3` |
| 5 | 5th Appellate District | F | F091244 | `calctapp_5th` |
| 6 | 6th Appellate District | H | H053901 | `calctapp_6th` |

Note: court ids match the classic juriscraper opinion scrapers
(`juriscraper/opinions/.../state/calctapp_*`), which give each Fourth-District
division its own id — so every site case-number prefix maps 1:1 to a
CourtListener court.

## Search Capabilities

1. **Case Number Search** (primary for scraping) -- Enter case number on the search page for the relevant `dist`. For unique matches, redirects directly to the case detail page. Works for appellate and trial court numbers.
2. **Party Name Search** -- Last name required (min 2 chars). Returns paginated results (25 per page). Useful for probing docket formats.
3. **Attorney Search** -- Similar to party search.
4. **Case Caption Search** -- Search by case title.
5. **Calendar Date Search** -- Oral arguments only; supports date range and division filter.

**Recommended approach**: Speculative entry by case number (one entry per court prefix). No date-based case search exists.

## Docket Number Formats

All courts use a single letter prefix + 6 sequential digits:

| Court | Pattern | Example |
|-------|---------|---------|
| Supreme Court | `S` + 6 digits | S295928 |
| 1st District | `A` + 6 digits | A175975 |
| 2nd District | `B` + 6 digits | B343601 |
| 3rd District | `C` + 6 digits | C102353 |
| 4th District Div 1 | `D` + 6 digits | D087818 |
| 4th District Div 2 | `E` + 6 digits | E088098 |
| 4th District Div 3 | `G` + 6 digits | G066312 |
| 5th District | `F` + 6 digits | F091244 |
| 6th District | `H` + 6 digits | H053901 |

Numbers are continuous (not year-partitioned) and appear to have small gaps. Numbers do not reset yearly.

## Data Available

The site has two distinct page layouts: **Supreme Court** and **Court of Appeal**.

### Case Summary -- Supreme Court (dist=0)
- Supreme Court Case Number (e.g., S280000)
- Supreme Court Opinion — `[PDF]` / `[DOC]` links, `<a id="pdf">` and
  `<a id="doc">`, on 793 of 297,487 pages (0.27%). `id="doc"` serves **both**
  `.DOCX` (484) and `.DOC` (309), which is why `CaDocument` separates
  `file_format` from `document_type`; see "Documents" below.
- Supreme Court Order — a *separate* `<a id="courtOrders">` PDF on 8 pages,
  with a root-relative `/documents/*.pdf` href on the appellatecases host
  (`Link.url` resolves it against the page URL). Archived as a `CaDocument`
  with `document_type=order`; SC-only, 0 on the Third District.
- Court of Appeal Case(s) (district, division, case number with link)
- Case Caption
- Case Category (e.g., "Review - Criminal Appeal", "Review - Civil Appeal")
- Start Date (mm/dd/yyyy)
- Case Status (e.g., "case initiated", "closed; remittitur issued")
- Issues (detailed text describing legal questions)
- Disposition Date — the SC's equivalent of the CoA "Completion Date", so it
  is scraped into `CaAppDocket.date_terminated`. Present on 12,445 of 12,500
  sampled SC summaries; before this was read, `date_terminated` was null on
  **all** 302,103 SC dockets of a full sweep.
- Trial Court Case — a `<br>`-separated run rather than a field: a court name
  followed by its case number ("Fresno County Superior Court - Main" /
  "3237203"), repeated once per consolidated matter and occasionally flagged
  "(lead)". Sometimes just a bare number with no court named. Over 4,490
  sampled SC summaries: two lines on 371 pages, one on 132, four or six on
  three.

  Read into `CaAppTrialCourtRef` records, which feed
  `CaAppDocket.trial_court_case_numbers` and stand in for
  `lower_court_info.trial_courts` when the Lower Court tab has no data at all
  — which it does not on 139,775 of 302,103 SC dockets, mostly the older ones
  and those that never reached a Court of Appeal.
- Case Citation
- Cross Referenced Cases — scraped into
  `CaAppDocket.cross_referenced_cases` (`CaAppCrossReferencedCase`:
  docket_number, case_name, case_link). Present on 9,881 of 297,487 SC pages
  (3.3%) and on **no** Third District page.

  Its markup is unlike every other field in the `<dl>`: the block opens with a
  bare `<dt>Cross Referenced Cases:</dt>` that has **no** `<dd>`, and then each
  case is a further `<dt>` holding
  `<a id="relatedCase_S168103" href="mainCaseScreen.cfm?dist=0&…">S168103</a>`,
  paired with a `<dd>` carrying the caption. It is therefore read off the
  `a[id^="relatedCase_"]` anchors, not by term lookup — the label names no value
  to walk from, and the cases are its siblings rather than its children.

### Case Summary -- Courts of Appeal (dist=1-6, 41-43)
- Trial Court Case Number
- Court of Appeal Case Number
- Division (numeric, e.g., "4")
- Case Caption
- Case Type (e.g., "CV", "CR")
- Filing Date (mm/dd/yyyy)
- Completion Date
- Oral Argument Date/Time
- Supreme Court Case — present only when review was sought (18,663 of 98,002
  Third District pages), as a link to the SC case:
  `<dd><a href="mainCaseScreen.cfm?dist=0&doc_id=…&doc_no=S278438">S278438</a></dd>`.
  Exactly one link wherever the field appears (verified across the full
  district), so it is scraped as the scalar
  `CaAppDocket.supreme_court_case_number` — the reciprocal of the SC page's
  `coa_case_numbers`. Matched on `dist=0` because the sibling-tab links are
  also `mainCaseScreen.cfm`. Recorded only; the scraper does not follow it
  into `dist=0`.

Note: `Division` is present as a label on every CoA page but its `<dd>` is
empty on five of the seven Courts of Appeal — a null `division` there is
correct, not a parse failure. Measured over `cal-august` (all nine courts):
populated on the First (120,259 of 120,260) and Second (334,458 of 334,509)
districts only, and null on **all** dockets of the Third, Fifth, Sixth, and
all three Fourth-District divisions. The Third, Fifth and Sixth have no
divisions at all; the Fourth's divisions are addressed by `dist` (41/42/43)
and so are already carried by the court id, which is why the site leaves the
field blank there rather than printing "3".

Where it *is* populated the vocabulary is not purely numeric. The First
District prints `1`-`5` plus `v` (522), `d` (6) and `a` (2); the Second prints
`1`-`8` plus `p` (30,121) and `a` (2,491). These are the site's own values,
not a parse artifact — B004324's summary literally serves `<dd>p</dd>` and its
tab banner reads "Division p" — so they are stored verbatim. They cluster on
pre-1990 cases and are left uninterpreted rather than mapped to a number.

### The tab banner (every tab except Case Summary)

Each of the other tabs repeats a two-line banner above its content: the case
caption, then `Division X`. `_read_tab_header` reads it on all five, for the
division — a Supreme Court summary `<dl>` has **no** Division term at all, so
this banner is the only place the SC's sitting location is printed ("Division
SF" on 1,877 of 3,000 sampled tab pages, then LA 1,069, SD 40, SA 9, FR 5).
`division` was consequently null on every SC docket.

Reading it also clears what was, before this, the single largest residual
cluster on every non-summary tab of both court types. The caption is taken
only as a fallback; the summary's Case Caption is authoritative where it has
one.

An earlier attempt at the division read looked for
`//div[contains(@class,'caseInfo')]` — a class this site does not emit
anywhere. It matched nothing, on every page, silently.

### Docket Entries (both)
| Field | Type |
|-------|------|
| Date | mm/dd/yyyy |
| Description | str |
| Notes | str (may contain party name, attorney name) |

Scheduled Actions rows are **not** in this list -- they are deadlines, and
live in `CaAppDocket.scheduled_actions`. See that section.

Also shows case caption, division, and case number at top.

### Briefs (both — but column sets differ!)
| Field | Type |
|-------|------|
| Brief type/description | str (e.g., "Opening brief on the merits filed") |
| Due Date | mm/dd/yyyy, usually empty — **Court of Appeal only** |
| Date Filed | mm/dd/yyyy |
| Party and Attorney | str (often empty) |
| Notes | str |

The Supreme Court table omits the Due Date column (4 columns; CoA has 5), so
cells must be mapped by header text, not fixed index. Verified on both sides:
all 4,156 SC brief tables are
`brief | date filed | party and attorney | notes`, and all 50,003 Third
District tables are `brief | due date | date filed | party and attorney |
notes`.

On the Supreme Court side the "Party and Attorney" cell is **always empty**
(`&nbsp;` on all 22,178 SC brief rows) — the filing party is instead described
in Notes prose ("By Apps, Lucia Mar Unified School Dist.", "by respondent
Commission on State Mandates"), with none of the `Party:`/`Attorney:` labels
the CoA cell uses. So an SC brief legitimately has empty `filed_by` and
`notes_filed_by` and keeps everything in `notes`; that is the site, not a
parse failure.

`Due Date` is the deadline for a brief that has **not** been filed yet; the
site clears it once the brief arrives. Measured over the Third District
(137,337 rows): populated on 1,101 rows, and 1,098 of those are exactly the
rows whose `Date Filed` is blank. Dropping it makes pending briefs look like
missing data, so it is scraped as `CaAppBrief.date_due`.

`Party and Attorney` and `Notes` are `<br>`-separated line lists, and `<br>`
contributes no text — so `text_content()` glues the lines together
("The People" + "Attorney: Eric L. Christoffersen" →
`"The PeopleAttorney: Eric L. Christoffersen"`, 64% of rows). Both cells are
read through `BriefsParser._cell_lines`, which pulls the text nodes
individually to keep the boundaries. The party cell's grammar is a
`"<Role>: <Name>"` line followed by zero or more `"Attorney: <Name>"` lines
or a bare `"Pro Per"`, repeatable — one cell can list several parties — so it
parses into `CaAppBrief.filed_by: list[CaAppBriefParty]`.

#### Party/attorney credits inside the `Notes` cell (older cases)
On older cases the `Notes` cell repeats the filing credit as
`Party: Last, First` / `Attorney: Last, First`, and sometimes names an attorney
the party cell omits — e.g. C033959, where the party cell has only
"Defendant and Appellant: Craig Boyd Drennan" while Notes carries
"Attorney: Riordan, Dennis P.". `BriefsParser._parse_notes` lifts those into
`CaAppBrief.notes_filed_by` and leaves the remaining prose in `notes`.

Measured over the Third District: 27,328 rows carry labelled credits (28,351
party + 28,894 attorney values).

Three things make this cell harder than the party cell:

- **Labels are not one per line.** `<br>` is unreliable here — a row can read
  `Attorney: Tilner, Mitchell C. Party: Fire Insurance Exchange` with no `<br>`
  between the two labels (C024332), and a name can also *split across* one
  (`Party: People Of The<br>State Of Califoria.`). So each line is scanned for
  labels rather than matched by prefix. (This is not a fixed-column wrap —
  line widths are spread with a max of 70, so it can't be un-wrapped
  mechanically.)
- **Label spellings vary**: `Party:`, `Attorney:`, `Atty:`, and the `Atty::`
  typo.
- **Parties come first, attorneys after, paired positionally** — *not*
  interleaved the way the party cell is. C025527 lists four parties then
  repeats `Somach, Stuart L.` four times. 92% of rows are the trivial
  1-party/1-attorney shape; 877 rows have ≥2 parties with ≥1 attorney, and 178
  have attorneys with no `Party:` label at all (hence
  `CaAppBriefNotesCredit.party` being optional).

Known limitation: 33 label occurrences across the district (0.06% of 57,245)
sit at the end of a line with their value on the next one
(`… Attorney: Shore, Dennis Party:` / `<br>` / `Wilson, Robin`). Those values
stay in `notes` as prose instead of becoming credits. Stitching them would mean
guessing which `<br>`s are continuations, and the line-width spread rules out
doing that mechanically, so the text is left where it is rather than risk
mis-attributing names.

These values are **deliberately not merged into `filed_by`**, which stays
canonical from the "Party and Attorney" column. They use `Last, First` order,
are sometimes abbreviated to initials (`Atty: Tone, F.`), carry trailing
rule/document parentheticals (`Ott, Thomas H. (Rule 40(k).)`), can be compound
(`Eisen, Jay-Allen & Boone, Daniel`), and ~77% of them merely duplicate the
party cell (attorneys were fully redundant on 20,895 of 27,001 rows). Merging
would trade a clean field for abbreviated duplicates; the genuine gain is
narrow — 2,339 rows where the party cell names no attorney and Notes does,
plus 1,955 where the party cell is empty entirely. Reconciliation is left to
the consumer, which can be done with full information from both fields.

### Disposition -- Supreme Court
Table with Date and Description columns.
- Example: "08/28/2025 | Opinion: Affirmed in part/reversed in part"
- Note: "Only the following dispositions are displayed: Orders Denying Petitions, Orders Granting Rehearing and Opinions."
- Also shows Case Citation.

### Disposition -- Courts of Appeal
Structured key-value fields:
| Field | Type |
|-------|------|
| Description | str (e.g., "Voluntary dismissal") |
| Date | mm/dd/yyyy |
| Disposition Type | str (e.g., "Final") **+ the order's text** — see below |
| Publication Status | str |
| Author | str |
| Participants | str |
| Case Citation | str |

**The `Disposition Type` cell holds two fields.** The site prints the type,
then a `<br>`, then the text of the order itself:

```html
<th scope="row">Disposition Type:</th>
<td>
Final<br>
The petition for writ of mandate, filed May 2, 2022, and the opposition
thereto, filed May 5, 2022, have been read and considered.
The petition is denied.<br>
</td>
```

Read whole, `disposition_type` comes out as a paragraph — which it did on
2,788 of 6,000 sampled Second District dispositions (46%). The first line goes
to `disposition_type`, the remainder to `CaAppDisposition.disposition_notes`.
Observed first lines are `Final`, `Partial`, `Vacated`, `Reverse Final`; a few
old Sixth District rows put a note there with no type at all.

### Parties and Attorneys (both)
Table with Party and Attorney columns:
- **Party cell**: Name, role (e.g., "Defendant and Appellant"), address (multi-line)
- **Attorney cell**: Name, firm/organization, address (multi-line, street + city + state + zip)

### Lower Court -- Supreme Court
| Field | Type |
|-------|------|
| Court of Appeal District/Division | str |
| Court of Appeal Case Number | str (with link) |
| Disposition | str (e.g., "Affirmed in full") |
| Disposition Date | mm/dd/yyyy |
| Trial Court | str |
| Trial Court Case Number | str |

### Trial Court -- Courts of Appeal
| Field | Type |
|-------|------|
| Trial Court Name | str |
| County | str |
| Trial Court Case Number | str |
| Trial Court Judge | str |
| Trial Court Judgment Date | mm/dd/yyyy |

**`trial_court_info` vs `lower_court_info`** — two different court levels, not
two names for one thing:

- `CaAppDocket.trial_court_info` (`CaAppTrialCourtInfo`) is the **CoA-only**
  Trial Court tab above. This is the CL `OriginatingCourtInformation`
  analogue (`court_name`, `docket_number_raw`, `judge_str`, `date_judgment`).
- `CaAppDocket.lower_court_info` (`CaAppLowerCourtInfo`) is the **SC-only**
  Lower Court tab — from the SC's vantage the "lower court" is the Court of
  Appeal, so it holds linked CoA cases, the CoA disposition, *and* a list of
  trial courts one further level down.

For an SC docket the CL OCI analogue is therefore `lower_court_info.coa_cases`
(originating court = the CoA); `lower_court_info.trial_courts` is a second
level that a single CL OCI row cannot hold. In a CoA-only run
`lower_court_info` is null on every docket by design.

### Scheduled Actions -- Courts of Appeal only

Every Court of Appeal case page carries a seventh tab, `a#actionTab` →
`scheduledActions.cfm`, headed "Future Scheduled Actions". Supreme Court
pages have six tabs and no such anchor. `parse_parties` branches on that
anchor -- the site's own signal -- rather than on `is_supreme`.

**Despite the name it is a list of deadlines, not of calendared events.** The
columns are `Description | Due Date | Notes`, inside `div#DispoList` (the
same container id the Docket tab uses):

| Field | Type |
|-------|------|
| Description | str (e.g., "Appellant's opening brief.") |
| Due Date | mm/dd/yyyy, **often blank** |
| Notes | str |

```
Record on appeal filed.                    10/05/2026
Filing fee.                                            No filing fee paid.07/23/2026
Civil case information statement filed.                07/23/2026
Appeal dismissed per rule 8.100(c).        08/10/2026
Something is due; see note.                08/17/2026  check status dismissal order
```

Rows become `CaAppScheduledAction` on `CaAppDocket.scheduled_actions` --
**not** `CaAppDocketEntry`, and not part of `entries`.

The general convention for these scrapers is that a per-case future-calendar
block is just more docket entries, on the reasoning that it is the same shape
(date + description) feeding the same consumer. That reasoning does not reach
this tab. It is a deadline ledger, not a calendar of sittings:

- The date is a **due date**. "Appellant's opening brief." against 06/17/2026
  means the brief is *owed* by then. Carried as `date_filed` it asserts the
  opposite, and every row would enter the CourtListener `DocketEntry` stream
  with a null `date_filed` — which on a real entry means missing data.
- The descriptions are the **anticipated forms of entries the Register of
  Actions gets later**: "Record on appeal filed.", "Filing fee.", "Civil case
  information statement filed.". Merged into one list, a case ends up holding
  both the expected and the actual row for a single event.

The nearest existing analogue is `CaAppBrief.date_due` — a filing the court
is waiting on — not a register-of-actions row. `Due Date` is blank on plenty
of rows (the site puts the detail in Notes instead), so a scheduled action
with neither a date nor a note is normal.

Verified live against G067160 (4th/Div 3, six rows incl. blank due dates),
B353492 (2nd, one row), H000102 (6th, empty) and D088532 (4th/Div 1, empty).
The empty state is the usual `<p>No information found.</p>` -- and it is
common, empty on two of the four. Note `#DispoList` is *absent* on an empty
tab, so the step waits on `#centerColumn` rather than on the table.

**No page of this tab exists in the `cal-complete` corpus** -- the scraper
never requested it before. One consequence: replaying a Court of Appeal chain
against that corpus now stops at `parse_scheduled_actions` and emits no
docket, because there is no stored response to serve. That is the corpus
being older than the scraper. Supreme Court chains replay unchanged.

### Multi-result pages paginate at 25 rows

`searchResults.cfm` caps a result set at 25 and offers the rest behind
`<a class="nextprev btn btnSmaller">next &gt;&gt;</a>` → `&start=26`.
`_fan_out_multi_result` therefore **walks every page before fanning out**,
accumulating `{doc_id: trial_court_numbers}` in `multi_result_groups` on
`accumulated_data` and emitting case requests only once a page arrives with no
next link.

Worked example — B302074 (2nd District), 38 rows over two pages, all of them
the same `doc_id`:

| | URL | rows |
|---|---|---|
| page 1 | `searchResults.cfm?dist=2&search=number&query_caseNumber=B302074` | 25 |
| page 2 | `…&start=26` | 13 |

Reading only page 1 gave that case 25 of its 38 trial-court case numbers.
Measured over 6,000 Second District summary responses, one page was truncated
against ~1,400 complete ones.

**Why the walk, and not just "fetch page 2 as well":** the fan-out has to
*click*. A row's href carries `request_token=auth` — a literal placeholder —
and navigating to it directly lands back on the search form (verified). So a
case can only be reached from a page that still shows its row. `&start=N`
pages themselves *are* directly navigable, which is why the walk between pages
needs no `via`.

Two details the markup makes easy to get wrong:

- Only the *next* control carries `class="nextprev"`; `<< previous` is a plain
  `a.btnSmaller`. The selector asserts the link text as well rather than
  resting on that asymmetry.
- The last page has **no** `nextprev` link at all, which is what ends the walk.

`_fan_out_groups` handles the case where a `doc_id` was seen only on an
earlier page: rather than dropping it, it sends one request back to *that*
page carrying `multi_result_single`, which re-enters the walk with pagination
off and the merge restricted to that one `doc_id`. In the one paginated set
observed, every page repeated the same `doc_id`, so this second hop should
stay rare — it exists so a stranded case fails loudly rather than vanishing.

### Documents -- opinions and orders (`CaDocument`)
The Case Summary page links each document with its own anchor id, and **the id
is the only reliable signal of what the document is** — an order and an opinion
are both served as `.pdf`:

| anchor id | label | `document_type` |
|---|---|---|
| `a#pdf` | Supreme Court / Court of Appeal Opinion | `opinion` |
| `a#doc` | same block, word-processor copy | `opinion` |
| `a#courtOrders` | Supreme Court Order | `order` |

`parse_case_summary` archives each one, yielding a `CaDocument` carrying
`document_type` (the `CaDocumentType` enum), `file_format` (the extension),
`source_url`, and the downloaded `local_path`. `document_type` and
`file_format` are separate fields because they answer different questions: the
same opinion appears as both a PDF and a word file, and `a#doc` serves `.DOCX`
on newer cases but `.DOC` on older ones.

Measured coverage, both runs:

| run | pages | `a#pdf` | `a#doc` | `a#courtOrders` |
|---|---|---|---|---|
| Supreme Court | 297,487 | 793 | 793 | 8 |
| Third District | 114,817 | 14,708 | 14,708 | 0 |

Every case with an opinion has exactly one PDF plus one word file, and no page
carries more than one of any id, so `max_count=1` per id is safe. All 1,586 SC
and 29,416 CA3 files downloaded successfully.

`CaAppDocket` deliberately carries **no** opinion-URL fields. It used to have
`opinion_pdf_url` / `opinion_docx_url`, populated only on the SC branch, but
they never produced a value in either court — null on all 296,617 SC dockets
and all 97,968 Third District dockets — for two independent reasons:

1. The extraction passed an `@href` XPath to `page.query()`, which returns
   *elements* and silently drops lxml's string results (`query()` -> `[]`,
   `query_strings()` -> the href). `min_count=0` meant the empty result raised
   nothing.
2. `.DOCX` was matched literally, but 309 of the 793 SC files (and 6,823 of
   14,708 in the Third District) are `.DOC`.

`CaDocument` covers both, plus the orders those fields could never name.

#### Which collection served the file (`source_collection`)
Opinion URLs carry a collection segment (`/opinions/<segment>/`), recorded as
`CaDocument.source_collection` (the `CaOpinionCollection` enum). Observed across
both sweeps:

| segment | meaning | SC | CA3 |
|---|---|---|---|
| `nonpub` | unpublished | 0 | 27,086 |
| `archive` | archived | 1,360 | 1,128 |
| `revnppub` | not published after review granted | 0 | 454 |
| `revpub` | published after review granted | 0 | 422 |
| `documents` | generic | 226 | 326 |

Two cautions. **`archive` is not SC-only** — the Third District uses it for
1,128 files. And **the segment is not a publication signal**: 88 CA3 dockets
whose disposition reads "Signed Published" have their file under `nonpub`, and
97 "Signed Unpublished" ones sit under `revpub`. Use
`CaAppDisposition.publication_status`. An unrecognised segment becomes
`UNKNOWN` rather than failing the scrape; the raw segment always remains in
`source_url`.

**The vocabulary is now confirmed complete.** It was written when only 2 of
the 9 courts had been swept. Across `cal-august` — all nine courts, 236,000
`CaDocument` records — **zero** fall through to `UNKNOWN`, so the five
members above cover every collection the site serves. `_missing_` stays as
the guard for future drift. Orders remain Supreme-Court-only (8 records,
0 in every Court of Appeal), as designed.

#### Published opinions the site will not serve (`CaUnavailableOpinion`)
courts.ca.gov only serves opinion files for a limited window, so the site
documents far more published opinions than it offers files for. When a
disposition shows a published opinion and the summary page links no document at
all, a `CaUnavailableOpinion` records that gap with everything needed to fetch
the text elsewhere: case name, citation, disposition description/date/type,
author, participants, docket dates, trial-court numbers, and the summary URL.

The evidence differs by court (`CaOpinionEvidence`), because the courts state it
differently:

| court | signal | records |
|---|---|---|
| Courts of Appeal | `publication_status` says published | 2,647 (CA3) |
| Supreme Court | disposition description starts "Opinion" | 2,864 |

The Supreme Court has **no** Publication Status field — null on all 298,163
dispositions — and its opinions are published as a matter of course, so the
disposition description is the signal there. It has to be the description: the
overwhelming majority of SC dispositions ("Petition for review denied",
145,440 of them) are not opinions at all.

Matching publication status needs care: `"published" in status` is true for both
"Unpublished" *and* "Depublished" (a publication later withdrawn). CA3's full
vocabulary, and how it splits:

| publication_status | dockets | counts as published |
|---|---|---|
| Signed Unpublished | 39,732 | no |
| Signed Published | 3,240 | **yes** |
| Signed Partial Published | 285 | **yes** |
| Ordered Published | 111 | **yes** |
| By the Court - Unpublished | 15 | no |
| By the Court - Published | 13 | **yes** |
| Depublished - Review Granted or By Order | 12 | no |
| By the Court - Partial Published | 6 | **yes** |

So 3,655 of CA3's 43,404 status-bearing dockets (8.4%) are published, but only
about 1,008 come with a downloadable file. These skew old — heaviest in
1986-1990, only a handful after 2020 — consistent with the serving window rather
than a scrape failure.

**That vocabulary is now confirmed exhaustive.** Swept across all seven Courts
of Appeal in `cal-august`, the set of distinct `publication_status` values is
exactly the eight above — no court contributes a ninth — and the Supreme Court
contributes none at all, confirming it has no such field. `_is_published`
classifies all eight correctly, and its `depublished` guard is load-bearing
rather than defensive: "Depublished - Review Granted or By Order" occurs 294
times across the districts, and plain substring matching would have counted
every one of them as published.

The check keys on "the summary page linked no document", not on "no `CaDocument`
exists": the archive requests are still in flight when the docket is assembled,
so their results cannot be consulted at that point.

#### The literal `none` citation
The Supreme Court summary prints `none` in the Case Citation slot when there is
no citation — on 294,221 of 296,617 dockets (99.2%). Stored verbatim that reads
as data, so `_common.clean_optional` maps the site's placeholders (`none`,
`no data found`, `n/a`) to None. The disposition parser already guarded this
ad hoc; the summary parser did not, which is where the 294,221 came from.

Host patterns: opinions live off-site on `courts.ca.gov`
(`/opinions/archive/{case_no}.PDF` for the Supreme Court,
`/opinions/nonpub/{case_no}.PDF` for unpublished CoA opinions), while orders are
served from the appellatecases host itself under `/documents/`. There is no
general document-download tab — everything is linked inline on the summary page.

## Email Notifications

**Available** at `/email.cfm?dist={dist}` and `/email.cfm?dist={dist}&doc_no={case_no}`.

URL pattern: `https://appellatecases.courtinfo.ca.gov/email.cfm?dist={dist}&doc_no={doc_no}`

### Supreme Court notification event types:
- Answer/Reply to Petition for Review Filed
- Record on Appeal Filed (death penalty auto-appeal)
- Briefs Filed on the Merits
- Orders Filed Granting Review
- Disposition Filed
- Request for Modification of Opinion or Petition for Rehearing Filed
- Remittitur Issued
- Oral Argument set
- Notice of Forthcoming Opinion posted
- Time Extended for Court to Consider Petition for Review
- Opinion Available Online
- Extension of Time
- Response or Briefing Requested
- Response or Opposition Filed

Court of Appeal notifications likely have a similar but different set of events (not yet verified).

## Oral Arguments Calendar

**Available** at `/calendar.cfm?dist={dist}`.

### Search modes:
1. **By Case Number** -- Enter appellate or trial court case number
2. **By Date** -- Start date (required, mm/dd/yyyy), end date (optional), division filter (optional, 1-8 for Supreme Court)
3. **By Case Caption** -- Text search

### Fields:
- Date/time of scheduled oral argument
- Case number, case caption
- Division

External link: https://www.courts.ca.gov/2116.htm (published OA calendars)

## Bot Protection Notes

- **Imperva/Incapsula** JS challenge on all pages. `curl` returns HTTP 200 with an obfuscated JavaScript payload (~199KB) instead of page HTML.
- No hidden form fields observed in the search forms.
- `request_token` parameter required in case detail page URLs. Generated server-side during search session. Attempting to navigate directly to a case URL with `request_token=auth` (the placeholder in search result links) redirects to an error page. Must go through the search flow to get a valid token.
- `doc_id` is an internal numeric ID assigned per case; required in all tab URLs alongside `doc_no` (the case number).
- Pagination uses `start` parameter (e.g., `start=26` for page 2 of 25-per-page results).
- Tab URLs follow consistent pattern: `case/{page}.cfm?dist={dist}&doc_id={id}&doc_no={no}&request_token={token}`

## Scraper Architecture

### Entry Points

One speculative entry, `dockets_by_number(docket_number: CaCourtRange)`,
probes `{prefix}{n:06d}` and the driver seeds/advances the range. Seed it
once per court (each seed gets its own speculation state); `CaCourtRange`
carries the CourtListener `court_id` and maps it to the prefix, and
`SEED_HINTS` in `scraper.py` lists each `highest_observed`
(largest_observed_gap was 100 for every court, 2026-04-03):

| Prefix | `dist` | Court ID | highest_observed |
|--------|--------|----------|------------------|
| S | 0 | `cal` | 295928 |
| A | 1 | `calctapp_1st` | 175975 |
| B | 2 | `calctapp_2nd` | 343601 |
| C | 3 | `calctapp_3rd` | 102353 |
| D | 41 | `calctapp_4th_div1` | 87818 |
| E | 42 | `calctapp_4th_div2` | 88098 |
| G | 43 | `calctapp_4th_div3` | 66312 |
| F | 5 | `calctapp_5th` | 91244 |
| H | 6 | `calctapp_6th` | 53901 |

Example seed: `{"dockets_by_number": {"docket_number": {"court_id": "cal",
"min": 295928, "soft_max": 295928, "gap": 100}}}`.

Optional future entry point for oral arguments by date range via Calendar page.

### Step Functions

Each entry returns a single search Request; the site redirects to the case
detail page. Step priorities descend by depth (downloads at 1):

```
entry → parse_case_summary     (8)  CaseSummaryParser; not-found → CaAppCaseUnavailable;
   │                                 multi-result → fan out; documents → archive_document (1)
   ├→ parse_docket             (7)  DocketEntriesParser
   ├→ parse_briefs             (6)  BriefsParser
   ├→ parse_disposition        (5)  DispositionParser (+ SC citation promotion)
   ├→ parse_parties            (4)  PartiesParser; branches on the a#actionTab anchor
   ├→ parse_scheduled_actions  (3)  ScheduledActionsParser — CoA only, skipped
   │                                 entirely when the a#actionTab anchor is absent
   └→ parse_trial_court        (2)  TrialCourtParser → _assemble_docket → ParsedData
```

Scheduled Actions sits *before* the Trial Court tab, not after it, so that
`parse_trial_court` stays the one place a docket is assembled. Put last, it
would have had to assemble too — two assembly sites, and a docket that
disappears whenever that one tab fails to load.

`is_supreme` (set in the entry from the `S` prefix) is threaded down
`accumulated_data` and selects the SC vs CoA branch in the summary,
disposition, and trial-court parsers. Dates are parsed to `date` objects in
the parsers and survive `accumulated_data` JSON round-trips as ISO strings,
re-parsed at confirm.

### Parsers (`parsers/`)
- `CaseSummaryParser(is_supreme)` — summary `<dl>`, cross-referenced cases,
  subscriptions (document links are the step's job, not the parser's)
- `DocketEntriesParser` — Register of Actions rows
- `BriefsParser` — brief rows
- `DispositionParser(is_supreme)` — SC table vs CoA key-value; `extract_case_citation`
- `PartiesParser` — party + attorney cells
- `TrialCourtParser(is_supreme)` — CoA trial court vs SC lower court
- `_common.definition_list_pairs` — the shared `<dl>` reader. Pairs each `<dt>`
  with the `<dd>` *immediately* following it instead of zipping two parallel
  lists, because the two are not always balanced. Zipping misaligned every
  caption in the cross-referenced-cases block on 9,881 SC pages (each caption
  landed on the previous case); measured zero difference on SC Lower Court tabs
  and on every Third District page, so no field a parser read was ever wrong —
  but correct pairing is a prerequisite for reading that block at all.

### Models (aligned to [`../../CL_MODELS.md`](../../CL_MODELS.md))
- `CaAppDocket` — main output (`docket_number`, `court`, `case_name`, `date_filed`,
  `date_terminated`, `date_argued`, …); maps to CL `Docket`
- `CaAppDocketEntry` — `DocketEntry` (date_filed, description, notes)
- `CaAppScheduledAction` — an outstanding deadline from the CoA Scheduled
  Actions tab (description, date_due, notes); deliberately not a
  `CaAppDocketEntry`, see that section
- `CaAppBrief` — brief record (type, date_filed, date_due, filed_by,
  notes_filed_by, notes)
- `CaAppBriefParty` — a party credited with filing a brief, plus its attorneys
- `CaAppBriefNotesCredit` — lower-fidelity party/attorney credit recovered from
  the Briefs `Notes` cell on older cases; deliberately not merged into
  `filed_by`
- `CaAppDisposition` — disposition info (varies by court type)
- `CaAppParty` / `CaAppAttorney` — `Party`/`PartyType` + `Attorney`
- `CaAppTrialCourtInfo` — CoA trial court → `OriginatingCourtInformation`
- `CaAppLowerCourtInfo` / `CaAppCoaCaseLink` / `CaAppTrialCourtRef` — SC
  lower court block; `CaAppTrialCourtRef` also carries the trial courts
  named on the SC *summary* page, for the ~46% of SC dockets whose Lower
  Court tab is empty
- `CaDocument` / `CaDocumentType` / `CaOpinionCollection` — archived opinion or
  order → `RECAPDocument`; the only representation of a case's documents
- `CaUnavailableOpinion` / `CaOpinionEvidence` — a published opinion the site
  records but serves no file for, with everything needed to fetch it elsewhere
- `CaAppCrossReferencedCase` — a related case from the SC "Cross Referenced
  Cases" block
- `CaAppCaseUnavailable` — yielded for "Case Not Found" probes


## Coverage ledger

Residual identifications live in [`residuals.yaml`](residuals.yaml) next to
this file, so they ride with the scraper. Against the `cal-complete` corpus
(11 run dbs, SC + all six CoA districts, cutoff 2026-08-07) the ledger is 63
entries, **all `chrome`** — no `pending`, no `out-of-scope`. Nothing this site
serves is left unclaimed, and nothing it serves was judged real-but-unwanted.

Twenty-two of the `chrome` entries are not site chrome at all but the
Cloudflare interstitial, captured in place of a real response on four pages
of a 1.8M-request Supreme Court sweep and one of a 217k Fifth District one.
They are identified so the ledger stays readable; the pages themselves are
worth re-fetching. A further two identify the site's own ColdFusion error
page, which `_check_application_error` now rejects as transient rather than
parsing (see "Partial pages" below).

The two items that were `pending` — the Scheduled Actions tab and
multi-result pagination — are both implemented now. Neither is exercised by
the `cal-complete` corpus, which predates them: no `scheduledActions.cfm` and
no `&start=26` response was ever fetched. Both were designed against live
pages instead, and both are described in full above.

### Re-verified against `cal-august` (2026-09-24)

A second corpus — `../juriscraper-runs/cal-august/`, 9 run dbs, one per
court, 7,934,526 requests, **0 errors**, 1,590,894 results, **0 validation
failures** — now covers all nine courts, and both previously-unexercised
items with it:

- **Scheduled Actions is exercised**: 695,839 `scheduledActions.cfm` pages
  across six of the seven Courts of Appeal. (The Third and Fifth District dbs
  predate the step and hold none — a corpus gap, not a scraper one.) Rows
  land on 1.9-3.5% of dockets, which is the expected shape: only an open case
  has outstanding deadlines. Residuals are clean both over a plain sample and
  over a sample restricted to pages that actually *have* a table — the latter
  matters, because ~97% of these pages are the empty "No information found."
  state and a plain slice can report "no residual" having never seen a
  populated one. The column set is `Description | Due Date | Notes` on every
  populated page checked, matching the live verification above.
- **Multi-result pagination is exercised**: 32 `&start=26` fetches and 27
  `multi_result_page` steps. Zero `multi_result_revisit` requests,
  so the stranded-`doc_id` hop has still never been needed — as predicted.

**Final state, after the fixes below** — `report.py` re-run full-width over
all nine dbs (4h26m, 2026-09-25):

| check | result |
|---|---|
| unidentified residual clusters | **0 on every one of the nine courts** |
| orphaned, intersected across all nine | **0 of 19** — every entry is exercised by at least one court |
| errors | 0, across 7,934,526 requests |
| `pending` / `out-of-scope` entries | none; the ledger is 19 entries, all `chrome` |

Per-court orphan counts still read 1-4. That is the sampling artifact again,
one level up: a court simply may not contain a given page state. The
intersection is what matters, and at zero it says no entry in the ledger is
dead weight. Each court still exits 1 on `--check`, for the selector-coverage
reason documented below — read the `unidentified` row, not the exit code.

Sampling said the ledger was clean. **The full-width sweep said otherwise**,
and it was right — see "What sampling missed" below. Two real defects and one
missing `chrome` entry came out of running `report.py` over all nine dbs
rather than over slices of them. Orphan counts reported against a *slice* are
still not meaningful (a 60-page sample flags the Cloudflare and
application-error entries simply because no page in the slice was one), but
"zero unidentified on a 60-page sample" turned out not to be meaningful
either.

### What sampling missed

Per-court samples of 40-150 pages reported zero unidentified clusters on
every step. The full-width run found 42 distinct clusters. They are
three things, and none of them could have shown up in a sample — the two page
states involved occur on **~34 pages out of 7.9M** (0.0004%):

| pages | courts | cluster | disposition |
|---|---|---|---|
| ~25 | all 9 | Cloudflare edge **502 "Bad gateway"** page | bug — see below |
| ~9 | 2 | Cloudflare **"Just a moment..."** challenge | bug — see below |
| 36 | 6 | multi-result **`<< previous`** control | `chrome`, now in the ledger |

The lesson for the next pass on this scraper: a page state that appears on a
handful of pages per million is invisible to any feasible sample, and the
ones that matter most here are exactly of that shape — they are *failure*
pages, which are rare by definition and damaging out of proportion to their
count, because each one silently truncates a docket.

### Cloudflare pages were being parsed as real content

`_check_502_bad_gateway` matched `//h1[contains(., '502 Bad Gateway')]` — the
*origin's* nginx error page. Cloudflare fronts this site, and when the origin
is unreachable Cloudflare serves its **own** page instead, which splits the
status across two spans:

```html
<h1><span>Bad gateway</span> <span class="code-label">Error code 502</span></h1>
```

That heading's text is `"Bad gateway Error code 502"` and never contains
`"502 Bad Gateway"`, so the detector never fired. Nothing else marked the page
as broken either — no `#centerColumn`, no tab strip, no spinner — so it was
parsed as content and each one emitted a docket with that tab silently empty.
The same held for the challenge page, whose wording has moved on from the
`Error 503` that `_check_503_challenge` looks for.

This is the mechanism behind the 404 dockets that carry **no parties at all**
(0.036% of 1.12M). Not all of those are Cloudflare — plenty of cases
genuinely have no parties listed — but this is where the unexplained ones
came from.

Two detectors now cover it: `_check_cloudflare_error` (matched on the
`Error code NNN` span, so it catches 520-524 as well as 502) and
`_check_cloudflare_challenge` (matched on the `<title>` and the `<noscript>`
notice, the two parts that have survived three rewordings).

### Every transient detector was raising `TypeError`

Found while fixing the above, and worse than it: `TransientException` takes a
**required keyword-only `kind`**, and not one of the five existing detectors
passed it. Any of them that fired would have raised `TypeError` from inside
the exception constructor instead of the transient it meant to raise — so a
502, a maintenance window or a stalled panel would have surfaced as an
unexplained crash rather than a retry.

It had never been observed because none of them ever fired: the corpus has
**0 errors**, the origin 502/503 and maintenance pages never occurred in it,
and the two page states that *did* occur were the Cloudflare ones the
selectors missed. The bug and the gap concealed each other. All seven raises
now pass `kind=` (`SITE_DEGRADED`, or `INTERSTITIAL` for the challenge).

Two vocabularies that were open questions are now closed: `CaOpinionCollection`
(0 `UNKNOWN` in 236,000 documents) and `publication_status` (exactly the eight
documented values). See those sections.

One thing the residual ledger cannot see, re-checked by hand per the warning
below: every `<dt>`/`<th>` label on every tab was scanned against the labels
the parsers actually *map*. The only unmapped label on the whole site is the
Supreme Court summary's "No Cross Referenced Cases Found" placeholder, which
is chrome — its absence is already representable as an empty list.

### Partial pages

`_check_application_error` raises a `TransientException` on
`<h1>We're sorry - An Error Occurred</h1>`. Unlike the 502/503 pages this one
does not *replace* the content, it interrupts it: on S297578's Lower Court
tab the site rendered the tab strip, the case banner, and the first two
fields of the trial-court block, then emitted the error where the rest
belonged. Nothing marked the page as broken, so the parser read the two
fields it got and produced a truncated `CaAppTrialCourtInfo` — worse than no
docket, because it reads as a case whose county the court simply never
recorded. Three pages in a 1.8M-request sweep, all surfaced by the residual
ledger rather than by any error.

Two further things worth knowing when reading a coverage report:

- The transient-page detectors (502, 503, `NOTICE: MAINTENANCE`,
  `An Error Occurred`, visible spinner) match ~0% of pages on a healthy corpus, which `report.py` counts as
  unmatched selectors. That is the detectors working, not a defect.
- `residuals` cannot see the definition-list gaps on this site: the parsers
  read every `<dt>`/`<dd>` into a dict, so a term the parser never *maps* is
  still marked consumed. The SC `Disposition Date` and `Trial Court Case`
  fields, and the CoA `Disposition Type` cell holding two fields, were all
  found by scanning the stored bodies for labels no parser maps -- worth
  redoing that scan after any template change here.
