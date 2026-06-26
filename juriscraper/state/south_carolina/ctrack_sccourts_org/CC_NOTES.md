# South Carolina C-Track Scraper Design

## Site Overview
- **Base URL**: https://ctrack.sccourts.org/public/caseSearch.do
- **Requires Playwright**: No — server-rendered HTML, no bot protection.
- **Transport**: HTML form POST. Java-EE/Struts-style endpoints (`*.do`).
  Action URL contains a `;jsessionid=...` URL-rewrite suffix on rendered
  pages, but a fresh POST to the bare URL works without any session
  bootstrap. No cookies required.
- **Engine**: Travelers / Justice Systems C-Track ("the browser based CMS
  for Appellate Courts"). Single C-Track install hosts both SC appellate
  courts. The same patterns likely apply to other states using C-Track
  (e.g. NM, NV, etc.) and may be a useful template later.

## Courts Covered

| Site ID | Display Name | CourtListener ID |
|---------|-----------------|------------------|
| 10001 | Supreme Court | sc |
| 10002 | Court of Appeals | scctapp |

Both courts share a single search and detail interface. Listing rows
identify the court via the "Court" column text; the case-detail page's
"Court:" field carries the same string.

## Search Capabilities

The case search form (`caseSearchForm`, POST `/public/caseSearch.do`)
accepts:

- `courtID` — `10001` (Supreme Court), `10002` (Court of Appeals), `-1`
  (both).
- `shortTitle` — party-name / case-title substring.
- `csNumber` — exact appellate case number (e.g. `2026-000911`).
- `fromDt` / `toDt` — `MM/DD/YYYY`. Filed-date range, inclusive.
- `csGroupID` — case-type-group select. Per-court populated dynamically.
- `csTypeID` — case-type select (always empty in observed UI).
- `exclude` — checkbox; when present, hides closed cases.
- Hidden: `submitValue=Search`, `startRow=1`, `displayRows=50`,
  `orderBy=FileDt`, `orderDir=DESC`, `href=/public/caseView.do`,
  `action=` (empty).

Pagination is reflected in the response as a "Next" link plus
`postPaging(startRow, displayRows)` JS that just re-submits the form
with adjusted `startRow` / `displayRows`. The server respects
`displayRows=200` and returns all rows under the cap in one response.

Decision tree: **a usable filed-date filter exists → date-based search
is the bulk strategy.** Direct case-number lookup is a separate entry
point.

**Recommended approach**: date-range listing walk for bulk; direct case#
search for single-case lookups.

### Date-range search response
- `200` HTML.
- Listing in a `<table>` with header row "Court / Appellate Case No. /
  Short Title / Group / Type / Subtype / Filed Date / Status".
- Each result row's appellate-case-number cell contains an `<a>` to
  `/public/caseView.do?csIID={internalId}`. The internal `csIID` is the
  primary key for case-detail lookups; the public docket number
  (`YYYY-NNNNNN`) is the human-facing identifier.

### Case-number search response
- Single match → `302` redirect to
  `/public/caseView.do;jsessionid=...?csIID={id}`. With redirect
  following, the scraper lands directly on the case-detail page.
- No match → `200` with sentinel `<span class="NoRecords">No records
  were found.</span>`.

### Party-name search response
- `200` HTML — same listing format as date search. Useful for
  discovering docket-number formats and probing the data shape, but not
  a bulk strategy here.

## Docket Number Formats

Both courts use the same canonical format: **`YYYY-NNNNNN`** (4-digit
filing year + 6-digit zero-padded sequence number, hyphen-separated).

Examples observed: `2026-000823` … `2026-001056` (Apr 2026 window).

Numbers do not appear strictly sequential by date — the sequence
advances faster than the day-by-day filings, suggesting a shared
counter incremented at intake. Speculative-range scraping by
case-number alone is therefore noisy; date-range search is preferred.

The docket number is stable across both courts (each year's sequence is
shared) — the court is determined by the "Court" column / field.

## Data Available

### Case Information (from `/public/caseView.do?csIID=N`)
Top section, key/value pairs in a `class="FormTable"` table with
`class="Label"` cells holding labels.

- `Court` — string ("Court of Appeals" or "Supreme Court").
- `Classification` — combined `Group - Type - Subtype`, e.g.
  `Appeal - Common Pleas - Other`.
- `Short Title` — case caption short form.
- `Case Status` — e.g. `Pending`, `Awaiting Transcript`,
  `Decision Filed`, `Remittitur`, `Ended`.
- `Consolidated` — possibly empty; multi-line list of consolidated
  case numbers when present.
- `Filed Date` — `MM/DD/YYYY`.
- `Oral Argument Date` — `MM/DD/YYYY` or empty.
- `Disposition Date` — `MM/DD/YYYY` or empty.
- `Disposition Type` — e.g. `Order`, `Opinion`, or empty.
- `Remittitur Date` — `MM/DD/YYYY` or empty.
- `Lower Court or Tribunal` — string with embedded county / tribunal
  case number, e.g. `Spartanburg (2022CP4200573)`.
- `View Full Title` — link `href="#"`. The expanded full title is
  inline in a hidden `<div id="fullTitle" style="display:none;">…</div>`
  block immediately after the case-info table — no extra fetch needed.

### Party Information (`<table id="partyInfo">`)
Per row:

- `Appellate Role` — e.g. `Appellant`, `Respondent`, `Petitioner`.
- `Party Name`.
- `Former` — `Y` / `N`.
- `Attorney(s)` — single cell that may contain multiple attorney names
  separated by line breaks, or `Self Represented`.

### Event Information / Docket entries (last `class="FormTable"`)
Per row:

- `Filed Date` — `MM/DD/YYYY`.
- `Event Information` — description, e.g.
  `Notice of Appeal (Civil) - Initial`,
  `Correspondence - Outgoing (Initial Letter)`,
  `Deficiency - Deficiency Letter Sent`.
- `Doc` — empty cell, **or** `<img class="documentLink"
  name="deID:{eventId}" src="…document.png|document_multi.png">`. The
  icon variant indicates single (`document.png`) vs multi
  (`document_multi.png`) attached document. The numeric `deID` (docket
  event ID) is the key into the document link API.

### Document URLs
Documents are resolved via a DWR (Direct Web Remoting) endpoint:

```
POST /public/dwr/call/plaincall/AJAX.getViewDocumentLinks.dwr
Body (text/plain):
  callCount=1
  page=/public/caseView.do?csIID={csIID}
  httpSessionId=
  scriptSessionId={any-string}
  c0-scriptName=AJAX
  c0-methodName=getViewDocumentLinks
  c0-id=0
  c0-param0=string:{deID}
  batchId=0
```

Response body includes a `dwr.engine._remoteHandleCallback('0','0', "<a
href=\"/public/document/view.do?documentID=N\" class=\"first-row last-row\">{label}</a>…")`
fragment. Each `<a>` is one document with a stable URL
`/public/document/view.do?documentID={N}` (`application/octet-stream`
PDF download).

## Email Notifications
Not visible in the public C-Track app. (Subscribers may exist in the
court's separate FAS / e-Filing portal, not exposed here.)

## Oral Arguments Calendar
Not exposed as a separate calendar/listing page in this app. The
per-case `Oral Argument Date` field is the only oral-argument signal
visible. No calendar entry point implemented.

## Bot Protection Notes
None. No CSRF tokens, no captcha, no rate-limit response. The form has
a hidden `submitValue` field set to `Search` by the JS button handler;
the scraper sends it directly. URL rewriting (`;jsessionid=…`) is
present on rendered links but optional for fresh POSTs.

## Known Gaps

- **`csGroupID` / `csTypeID` filters not used.** The driver always
  searches across all groups/types within a date range. The dropdowns
  exist for narrowing UI use but bulk scraping wants the unconstrained
  set.

## Scraper Architecture

Conforms to `juriscraper/sd/state/SCRAPER_STANDARDS.md`: §4 entry naming
(`court_ids`-first), §5 step priorities, §6 stable `deduplication_key`s,
§9 `parsers/` package.

### Entry Points
- `@entry dockets_by_filing_date(court_ids: set[str], date_range: DateRange)`
  — bulk filed-date range. A single seeded court narrows the form's
  `courtID` (10001 / 10002); the both-courts default sends `-1` and
  post-filters listing rows to the seeded set (carried as
  `accumulated_data["target_courts"]`).
- `@entry docket_by_number(court_id: str, docket_number: str)` — direct
  lookup. POSTs `csNumber=…` and follows the 302 to the case detail.

(The old no-arg `get_dockets()` 30-day convenience entry was dropped per
§4 — the driver seeds the `DateRange`, so a recent-window run is just a
narrow range.)

### Step Functions (priorities descend by depth; archive downloads = 1)
```
dockets_by_filing_date
   └─ POST caseSearch.do
        └─ parse_search_listing                      (priority 4)
             ├─ for each row: GET caseView.do?csIID=N → parse_case_detail (3)
             │     ├─ ParsedData(SCAppDocket)
             │     └─ for each entry with documents:
             │            POST DWR getViewDocumentLinks
             │              └─ fetch_event_document_links            (2)
             │                   └─ for each documentID:
             │                          archive Request → handle_document_download
             │                            └─ ParsedData(SCAppDocument)
             └─ if "Next" present: POST caseSearch.do (paginate) → parse_search_listing

docket_by_number(court_id, docket_number)
   └─ POST caseSearch.do (csNumber=…) follows 302
        └─ parse_case_or_miss                         (priority 3)
             ├─ "No records were found" → done
             └─ landed on caseView.do → emit SCAppDocket → (same fan-out)
```

### Parsers (`parsers/` package, §9)
- `SearchListingParser` — one `DeferredValidation[SCAppDocket]` per
  result row (`court`, `docket_number`, `site_case_id`).
- `CaseDetailParser` — one `SCAppDocket` per case-detail page (case-info
  label/value table, parties, events). `site_case_id` / `source_url`
  are filled by the step (the case#-search path hides the final URL).
- `parsers/_common.py` — the court-name map, the `csIID`/`deID` regexes,
  and whitespace normalization.
- Exercised offline in `tests/local/test_ctrack_scrapers.py` via
  `JKentParser.from_string`.

### Models
Field names track CourtListener (see `CL_MODELS.md`): `docket_number`,
`court` (court-id string), `date_*` for dates. Top-level records are
`SCAppDocket` and `SCAppDocument`; documents join back to the parent via
`(docket_number, event_id)`.

- `SCAppDocket` — top-level case record. Embeds `parties` +
  `docket_entries`. (`court`, `docket_number`, `case_name_full`,
  `date_argued`, `date_disposed`, `date_remittitur`, `appeal_from_str`.)
- `SCAppDocketEntry` — one row of the Event Information table. Records
  `event_id` (`deID`) so a downstream join can attach documents.
- `SCAppParty` — one row of the Party Information table.
- `SCAppDocument` — top-level. One per linked PDF (`document_number`,
  `url`, `description`, `filepath_local`).
