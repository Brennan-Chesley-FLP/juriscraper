# DC Court of Appeals Scraper Design

## Site Overview

- **Base URL**: https://efile.dcappeals.gov/
- **Search URL**: https://efile.dcappeals.gov/public/caseSearch.do
- **Case detail URL**: https://efile.dcappeals.gov/public/caseView.do?csIID=N
- **Document download URL**: https://efile.dcappeals.gov/document/view.do?documentID=N&csIID=N
- **Platform**: Thomson Reuters / Travelers C-Track HTML-form Public Access portal
- **Requires Playwright**: No — server-rendered HTML, no bot protection.

DC runs the same older HTML-form C-Track variant as South Carolina and
Nevada. The shared mechanics (search-form skeleton, DWR-driven document
link resolution, label/value case-info table, soft-404 marker) live in
[`juriscraper.state.common/ctrack`](../../common/ctrack/__init__.py).

## Courts Covered

| Site Court Name | CourtListener ID |
|-----------------|------------------|
| District of Columbia Court of Appeals | `dc` |

DC has a single appellate court (the local court of last resort). Unlike
SC and NV, the search form has no `courtID` selector.

## Search Capabilities

The case-search form (POST `/public/caseSearch.do`, name `caseSearchForm`)
exposes:

- `csNumber` — Appellate Case No. (e.g. `26-PR-0263`).
- `shortTitle` — Appellate Case Caption (party-name / caption substring).
- `lcCsNumber` — Superior Court or Agency Case Number (DC-specific:
  e.g. `2014-INT-000378`, `BZA19387`).
- `fromDt` / `toDt` — `MM/DD/YYYY`. Filed-date range, inclusive.
- `exclude` — Open Cases Only checkbox (omit → include closed).
- Hidden: `submitValue=Search`, `startRow=1`, `displayRows=50`,
  `orderBy=CsNumber` (DC default — note this differs from SC's
  `FileDt`), `orderDir=DESC`, `href=/public/caseView.do`,
  `action=` (empty).

The site respects `displayRows` values larger than the in-page default;
we send 200 to cut round trips, matching SC.

A 16-day April 2026 window returned 64 cases — about 4/day, well under
any volume cap. Annual volume is on the order of 1500 cases, so the
SC-style "split a too-large window" fallback is unlikely to fire.

**Recommended approach**: date-range listing walk for bulk ingest;
direct case-number lookup for single-case fetches.

### Date-range search response

- HTTP 200, server-rendered HTML.
- Listing rows: `<tr>` containing a case-number cell with an
  `<a href="/public/caseView.do?csIID={internalId}">26-XX-NNNN</a>`.
- 8 columns: Case No., Short Caption, Group, Type, Subtype, Status,
  Superior Court or Agency Case Number.
- Pagination: page footer `"1 to 50 of N rows are displayed."` plus a
  `Next` link wired to `javascript:postPaging(startRow, displayRows)`.
  We re-POST the form with an advanced `startRow` to fetch each page.

### Case-number search response

- Single match → 302 to `caseView.do;jsessionid=...?csIID={id}` (URL
  rewritten with the JSESSIONID prefix). Following redirects lands on
  the case-detail page directly.
- No match → 200 with the `<span class="NoRecords">No records were
  found.</span>` sentinel.

### Party / participant search

`/public/publicActorSearch.do` exists but is not a primary entry point.
Date-range search covers all bulk needs.

## Docket Number Formats

DC dockets use **`YY-XX-NNNN`** — 2-digit year, 2-letter case-type
code, 4-digit zero-padded sequence. The case-type prefix segments the
caseload into independent sequences, so direct speculation on a single
prefix would miss cross-prefix activity.

Observed prefixes in an April 2026 window:

| Prefix | Group | Type/Subtype example |
|--------|-------|----------------------|
| `CV`   | Appeals | Civil — Other Civil, Landlord and Tenant, Torts, Real Property |
| `CF`   | Appeals | Criminal Felony |
| `CO`   | Appeals | Criminal Other |
| `CM`   | Appeals | Criminal Misdemeanor |
| `FM`   | Appeals | Family — Domestic Relations |
| `PR`   | Appeals | Probate — Intervention (INT) |
| `OA`   | Original Jurisdiction | Original Actions — Mandamus |
| `DA`   | Discretionary | Discretionary — Small Claims |
| `AA`   | Agency | Administrative Agency (older sample, e.g. `17-AA-0066`) |

Other prefixes used by the court but not seen in the sample window
include `BG` (bar / discipline) and `SP` (special). The scraper emits
whatever the site renders; no prefix whitelist is enforced.

## Internal `csIID` Observations

`csIID` is C-Track's internal continuous integer key, used in
`/public/caseView.do?csIID=N` URLs. Observed values in late April 2026
ran roughly 71068–71143 (76 csIIDs over 16 days). One April case
(`26-PR-0273`, csIID 71088) had a smaller csIID than other cases filed
the same day, so csIID order ≠ docket-number order — the appellate
docket number is allocated against a per-prefix-per-year sequence
independent of the global csIID counter.

## Data Available

### Case Information (`<td class="label">` key/value rows)

The case-info table lives at the top of `caseView.do?csIID=N`. Note
the **lowercase** `class="label"` — SC uses capital `"Label"`; the
shared ``parse_label_value_table`` helper takes the class as a
parameter.

Fields observed (every case carries the row even when empty):

- `Short Caption` — case caption short form.
- `Classification` — combined `Group - Type - Subtype`,
  e.g. `Appeals - Civil - Other Civil`.
- `Superior Court or Agency Case Number` — lower-court / agency case#.
- `Filed Date` — `MM/DD/YYYY`.
- `Opening Event Date` — usually equals filed date.
- `Case Status` — `Pending`, `Under Advisement`, `Decided/Dismissed`,
  `Awaiting Completion of Record`, `Ready for Quality Review`, etc.
- `Record Completed` — `MM/DD/YYYY` or empty.
- `Post-Decision Matter Pending` — free-text or empty.
- `Briefs Completed` — `MM/DD/YYYY` or empty.
- `Argued/Submitted` — `MM/DD/YYYY` or empty.
- `Disposition` — free-text or empty.
- `Next Scheduled Action` — free-text or empty.
- `Mandate Issued` — `MM/DD/YYYY` or empty.
- `Costs Waived` — flag-style row (label-only column with no following
  value cell when set).

### Party Information

Six-column table (vs SC's 4-column):

| Appellate Role | Party Name | IFP | Attorney(s) | Arguing Attorney | E-Filer |
|----------------|-----------|-----|-------------|------------------|---------|

- **Appellate Role**: `Appellant`, `Appellee`, `Petitioner`,
  `Respondent`, `Intervenor`, `Real Party in Interest`.
- **IFP**: `Y` / `N` — *in forma pauperis* status for that party.
- **Attorney(s)**: free-text cell. May be `Pro Se` or one or more
  attorney names; multiple attorneys are split across nested rows
  (the cell sometimes contains an inner `<table>` with one row per
  attorney + the IFP/E-Filer flags for that attorney).
- **Arguing Attorney**: usually empty until argument is scheduled.
- **E-Filer**: `Y` / `N`.

### Events table (= docket entries)

Five-column table:

| Event Date | Status | Description | Result | PDF |
|-----------|--------|-------------|--------|-----|

- **Event Date**: `MM/DD/YYYY`.
- **Status**: typically `Filed`. Other observed values include
  `Dismissed`.
- **Description**: free-text, e.g. `Notice Of Appeal`,
  `Briefing Order`, `Order Sua Sponte Dismissing Appeal`.
- **Result**: usually empty; populated for terminal events on some
  cases.
- **PDF**: optional `<img class="documentLink" name="{flag}:{deID}:{csIID}">`.
  The `name` attribute encodes three values separated by colons —
  these are the three positional arguments to the DWR call below.

### Document URLs (DWR-resolved)

DC uses the same DWR `getViewDocumentLinks` endpoint as SC, but with a
different parameter shape:

```
POST /dwr/call/plaincall/AJAX.getViewDocumentLinks.dwr
Content-Type: text/plain

callCount=1
page=/public/caseView.do?csIID={csIID}
httpSessionId=
scriptSessionId={any-string}
c0-scriptName=AJAX
c0-methodName=getViewDocumentLinks
c0-id=0
c0-param0=string:{flag}        # e.g. "50"
c0-param1=string:{deID}        # docket-event ID
c0-param2=string:{csIID}
batchId=0
```

Note: SC sends a single `c0-param0=string:{deID}` — DC splits into
three. The shared ``build_dwr_doc_links_body`` helper takes a
``params`` list to accommodate both.

The reply is a `dwr.engine._remoteHandleCallback('0','0', "<a …>")`
callback whose third argument is an HTML fragment of one or more
`<a href="/document/view.do?documentID=N&csIID=N">{label}</a>`
anchors. Documents download as `application/octet-stream` PDFs; no
authentication is required.

DWR endpoint sits at `/dwr/...` (no `/public/` prefix on this site;
the SC install uses `/public/dwr/...`).

## Bot Protection Notes

None observed. No CSRF tokens, no captcha, no rate-limit response. URL
rewriting (`;jsessionid=…`) appears on links rendered by the server
but is optional for fresh POSTs.

## Soft-404 Behavior

Invalid or out-of-range `csIID` returns **HTTP 500** with the body
text `"Security Error"` / `"You do not have rights to view this case"`.
This is the same marker Nevada uses (Nevada serves it as HTTP 200).

The scraper's `actually_successful` override (jkent v0.1.0; replaced the
old `fails_successfully` name) checks for the marker substring and
returns `False`, so the driver counts the response as a miss.

For the case-number search, no-match responses arrive as HTTP 200 with
the SC-style `<span class="NoRecords">No records were found.</span>`
sentinel.

## Email Notifications

Not exposed in the public app. (E-filer subscribers exist but are
behind the Login wall.)

## Oral Arguments Calendar

No public per-court calendar URL was found. The per-case `Argued/Submitted`
field is the only oral-argument signal and is set after argument has
happened. We do not implement a separate `OralArgument` data type for
this site.

## Known Gaps

- **Sealed/non-public cases vs invalid IDs are indistinguishable** when
  the soft-404 marker is encountered. Direct csIID enumeration is not
  the chosen entry strategy here, so this only matters if a future
  consumer reaches a sealed case via a related-case link — the same
  marker will surface and the case will be treated as a miss.

## Scraper Architecture

Conforms to `juriscraper/sd/state/SCRAPER_STANDARDS.md`: §4 entry naming
(`court_ids`-first), §5 step priorities, §6 stable `deduplication_key`s,
§9 `parsers/` package, §10 `actually_successful`.

### Entry Points

- `@entry dockets_by_filing_date(court_ids: set[str], date_range: DateRange)`
  — bulk scrape across an explicit filed-date window. DC has a single
  court (`dc`), so `court_ids` only seeds the entry.
- `@entry docket_by_number(court_id: str, docket_number: str)` — direct
  lookup by appellate case number (e.g. `26-CV-0339`). Posts the
  case-number search; the site 302s on a single match straight to the
  detail page.

No speculative entry — date-search is the primary bulk strategy and
covers the same ground without the prefix-matrix complexity. (The old
no-arg `get_dockets()` 30-day convenience entry was dropped per §4 — the
driver seeds the `DateRange`.)

### Step Functions (priorities descend by depth; archive downloads = 1)

```
dockets_by_filing_date
   └─ POST caseSearch.do
        └─ parse_search_listing                      (priority 4)
             ├─ for each row: GET caseView.do?csIID=N → parse_case_detail (3)
             │     ├─ ParsedData(DCAppDocket)
             │     └─ for each entry with documents:
             │            POST DWR getViewDocumentLinks
             │              └─ fetch_event_document_links            (2)
             │                   └─ for each documentID:
             │                          archive Request → handle_document_download
             │                            └─ ParsedData(DCAppDocument)
             └─ if "Next" present: POST caseSearch.do (paginate) → parse_search_listing

docket_by_number(court_id, docket_number)
   └─ POST caseSearch.do (csNumber=…) follows 302
        └─ parse_case_or_miss                         (priority 3)
             ├─ "No records were found" → done
             └─ title is "<docket>: Case View" → emit DCAppDocket → (same fan-out)
```

`parse_case_or_miss` detects the detail page by its title (kent's HTTP
driver reports the original POST URL even after the 302) and reads
`csIID` from the page's hidden input.

### Parsers (`parsers/` package, §9)

- `SearchListingParser` — one `DeferredValidation[DCAppDocket]` per
  result row (`court`, `docket_number`, `site_case_id`).
- `CaseDetailParser` — one `DCAppDocket` per case-detail page (lowercase
  `class="label"` case-info table, the 6-column Party Information table
  incl. the nested-attorney sub-table, the 5-column Events table, and
  the label-only Costs Waived flag). `site_case_id` / `source_url` are
  filled by the step. Exposes `read_hidden_csiid(page)` for the
  case#-search path.
- `parsers/_common.py` — the `csIID` / documentLink-`name` regexes, the
  `Y`/`N` flag parser, and whitespace normalization.
- Exercised offline in `tests/local/test_ctrack_scrapers.py` via
  `JKentParser.from_string`.

### Models

Field names track CourtListener (see `CL_MODELS.md`): `docket_number`,
`court` (court-id string), `date_*` for dates.

- `DCAppDocket` — top-level case record. Embeds `parties` +
  `docket_entries`. (`court`, `docket_number`, `date_argued`,
  `date_opening_event`, `date_record_completed`, `date_briefs_completed`,
  `date_mandate_issued`.)
- `DCAppDocketEntry` — one row of the Events table; records `event_id`
  (the C-Track `deID`) + `document_link_flag` for the DWR call.
- `DCAppParty` — one row of the Party Information table, capturing the
  6-column shape (incl. IFP, arguing attorney, e-filer flags).
- `DCAppDocument` — top-level. One per archived PDF, joined back to the
  parent docket via `(docket_number, event_id)`. (`document_number`,
  `url`, `description`, `filepath_local`.)

### Shared Code

The DC scraper consumes
[`juriscraper.state.common.ctrack`](../../common/ctrack/__init__.py)
for the search-form skeleton, DWR body builder, DWR response parser,
the `<td class="label">` key/value extractor, the `MM/DD/YYYY` date
parser, and the soft-404 marker. SC consumes the same helpers.
