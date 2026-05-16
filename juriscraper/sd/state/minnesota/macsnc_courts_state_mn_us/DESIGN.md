# P-MACS (macsnc.courts.state.mn.us) Scraper Design

## Site Overview
- **Base URL**: https://macsnc.courts.state.mn.us/ctrack/
- **Stack**: Java/JSP C-Track deployment (older sibling of the Thomson
  Reuters TR-Portal used in OR/WY/ND/AL).
- **Bot protection**: F5/Volterra WAF returns a 403 to plain `curl`
  and serves a JavaScript challenge to browser-UA `curl` requests.
  A real browser executing the JS unlocks normal access.
- **Requires Playwright**: yes — `DriverRequirement.JS_EVAL` plus
  `FF_ALIKE` so the Volterra challenge resolves.

## Disclaimer Flow

The very first request to `/ctrack/search/publicCaseSearch.do` redirects
to `/ctrack/publicLogin.jsp`, which displays an "Accept" button. The
button posts to `/ctrack/publicLogin.do` with `submitValue=Accept` and
sets a session cookie that authorises the rest of the session. The
scraper performs this handshake as the first Request of every run.

## Courts Covered

| Jurisdiction text on results | jurisdictionID | CourtListener ID |
|------------------------------|---------------|------------------|
| Court of Appeals             | 1             | `minnctapp`      |
| Supreme Court                | 2             | `minn`           |
| Commitment Appeal Panel      | (other)       | (skip — not an appellate court in CL) |

The search form's `jurisdictionID` field can scope queries; we leave it
unset (search-all) and map jurisdictions per-row, skipping rows whose
jurisdiction text isn't one of the two appellate courts we model.

## Search Capabilities

The case-search form (`publicCaseSearch.do`) exposes:
- `csNumber`, `shortTitle`
- `csGroupID` — Standard / Abbreviated Adversarial / Admin / Prof Reg / Other
- `jurisdictionID` — 1 or 2 (above)
- `csStatusVal` — A / B / C / CH / D / O / PAH / P / PFR / PD / PA …
- `csTypeID`, `csSubTypeID`
- **`fromDt`, `toDt`** — date-range search (mm/dd/yyyy)
- `excludeArchived` checkbox
- Hidden: `startRow=1`, `displayRows=50`, `orderBy=SQLFileDt`,
  `orderDir=DESC`, `hrefName=/ctrack/cases/caseMaintenance.do?`,
  `submitValue=Search`

For our purposes we always set:
- `orderBy=SQLFileDt`, **`orderDir=ASC`** — so paginating to the last
  page reveals the latest filed-date in the result set, which we use as
  the resume boundary on cap hits.
- `displayRows=50` — the server caps page size; even
  `displayRows=1000` returns 50 in practice.

## Result Page Structure

- Result rows: `<tr class="OddRow|EvenRow">`, columns:
  case-number anchor, jurisdiction, short title, status, type, subtype,
  filing date.
- Case-detail link:
  `/ctrack/view/publicCaseMaintenance.do?csNameID=N&csInstanceID=N`.
- Page-count text: `"X to Y of Z records are displayed."` immediately
  preceding the results table.
- Pagination: form-resubmit via `postPaging(startRow, displayRows)`
  helper that flips `submitValue` to `Sort` and increments `startRow`.

## 1000-Row Cap

Every search response returns at most 1000 records (the page count
text shows e.g. `"1 to 50 of 1000 records are displayed."`). When the
total reaches the cap we use the same date-bisection strategy as the
OSCN scraper: walk every page in the current interval, collect the
filed dates seen, and after the final page resume the scan with
`fromDt = max_filed_date_seen` (boundary day inclusive — case-instance
dedup filters the overlap).

If the cap is hit and every record in the cap shares the same filing
date, date bisection cannot subdivide further; the scraper raises
`SearchVolumeAssumptionError` (a `ScraperAssumptionException`
subclass defined in this module).

## ORCA Info Page (`publicLowerCourtSummary.jsp`)

A second-tab page accessible via the "ORCA Info" link in the case-page
sidebar. Carries originating-court / agency information for the
appellate case. Captured into `MnOrcaInfo` and attached to the
docket before the entry walk starts. Fields:

- **Appeal From** — e.g. `District Court`
- **Court/Agency** — e.g. `Commitment Appeal Panel - CAP` or a
  Minnesota district / county court name
- **Other** — free-text
- **Orig. Case Number** / **Orig. Case Title** — the trial-court
  case identifiers
- **Related Case Number(s)** — split on commas
- **Decisionmaker(s)** — list of trial-court judge names, parsed by
  anchoring on the `Decisionmaker(s)` subheading and collecting every
  leaf `<td>` that follows in document order

Note on access: the URL returns `Request Rejected` if you try to
top-level-navigate to it without first hitting the parent case page in
the same session. The scraper sends `Referer: {case_url}` and relies
on the existing JSESSIONID + Volterra cookies; in-session fetches
succeed.

## Case Detail Page (`publicCaseMaintenance.do`)

Layout: a label/value table giving Case Information, then a
`Party Information` table, then a `Docket Information` table.

### Case Information (label/value pairs)
- Case Number, Filing Date, Jurisdiction, Status
- ORCA (origin / hearing context), Hearing Type
- Classification (group · type · subtype)
- Short Title, Full Title, Summary, Citation

### Party Information
Columns: MACS ID, Appellate Role, Party Name, Attorney(s) — multiple
attorneys are `<br>`-separated.

### Docket Information
Columns: Document Description (anchor →
`/ctrack/docket/docketEntry.do?action=edit&deID={deID}&csNameID&csInstanceID&csIID`),
Jurisdiction, Filing Date, Docket Entry Type, Filing Type, Status, PDF.

The case page's PDF cell holds an icon with
`onmouseover="dropdownmenu(this, event, 352, {deID}, 250)"` that
triggers a DWR-driven popup menu (`AJAX.getViewDocumentLinks`) listing
the document URLs. We sidestep DWR entirely: the docket-entry detail
page rendered at the `entry_url` already contains plain
`<a href="/ctrack/document.do?document={hash}">` anchors for every
attachment, so the scraper fetches that page per entry to enumerate
documents.

## Docket Entry Detail Page (`docketEntry.do`)

For every docket entry that exposes an `entry_url`, the scraper
fetches the detail page and harvests both the per-entry metadata
fields and the document attachments.

### Page layout

The page repeats the parent case info up top, then renders an
entry-specific section. The two sections use **distinct CSS class
names** for label cells, which is the hook we use to scope parsing:

| Section | Label class | Skipped? |
|---------|-------------|----------|
| Case info repeat | `class="label"` (lowercase) | yes — duplicates docket fields |
| Entry section | `class="Label"` (uppercase) | parsed |

The entry-specific table contains label / value pairs; values can
render in three shapes:

| Cell shape | Extraction |
|------------|------------|
| `<select>` with one or more `<option selected>` | join selected option text on `" || "` |
| `<input type="radio" checked>` | the input's tail text (the visible label after the radio) |
| Plain text | `text_content()` |

The scraper's `_parse_entry_detail_fields` produces a
`dict[str, str]` of every label / value pair on the entry section.
`_populate_entry_typed_fields` then promotes the well-known labels
into typed `MnDocketEntry` fields:

| Label | Typed field |
|-------|-------------|
| Status | `entry_status` |
| Thread to | `thread_to` |
| Method of Receipt | `method_of_receipt` |
| Method of Service | `method_of_service` |
| Method of Payment | `method_of_payment` |
| Indicate Service | `indicate_service` |
| Filing Fee | `filing_fee` |
| Postmark Date (if by mail) | `postmark_date` (parsed `date`) |
| Filing Date | `filing_date_time` (string with timestamp) |
| Docket Entry Date | `docket_entry_date_time` |
| Filed By | `filed_by` (split on `MULTI_VALUE_SEP`) |
| Signed By | `signed_by` (split on `MULTI_VALUE_SEP`) |
| Order Disposition Type | `disposition_type` |
| Disposition Details | `disposition_details` |
| Other Signatures | `other_signatures` |
| Reporter(s) | `reporters` |
| Date of Hearing(s) | `date_of_hearings` |
| Comments | `comments` |
| Other Deficiencies | `other_deficiencies` |

Anything else (Statement-type selects, future fields, entry-type-
specific extras) lives in `entry.details` so a consumer can grep
without a schema change.

### Document Archiving

The same step extracts each `document.do?document={hash}` anchor
(label = anchor text, e.g. `Order - Other`) and:

- Records an `MnDocument(label, document_url, doc_entry_id)` on the
  parent entry. `doc_entry_id` mirrors the entry's `deID` so consumers
  can correlate documents to entries directly without traversing the
  nested `entries` list.
- Yields a `Request(archive=True, expected_type="pdf")` for the URL,
  with deduplication key
  `doc:{case_number}:{deID}:{hash[:16]}`.

The download endpoint returns the binary directly with
`Content-Disposition: attachment; filename="{label}.pdf"` so the
file extension is reliable.

Some entries expose multiple document anchors (e.g. a Notice of
Appeal entry typically attaches the notice itself plus the decision
being appealed, proof of service, and an envelope) — every anchor
becomes its own `MnDocument` and `archive=True` Request.

### Walk semantics

Per-entry walks happen sequentially (so the populated `MnDocket`
emitted at the end captures every document URL and detail field);
the actual file downloads run in parallel via `archive=True`
Requests. Sealed entries return a detail page with no `document.do`
anchors and contribute an empty `documents: []` list with no archive
Requests, but their detail metadata still populates `entry.details`
and the typed fields.

## Scraper Architecture

### Models
- `MnDocketEntry` — date_filed, description, docket_entry_type,
  filing_type, status, jurisdiction, doc_entry_id (deID), entry_url
- `MnParty` — macs_id, role, name, attorneys (list of strings)
- `MnDocket` — case_number, court_id, date_filed, case_name, status,
  classification, jurisdiction, full_title, short_title, summary,
  citation, parties, entries, source_url, ns_name_id, ns_instance_id

### Entry → step pipeline
```
get_dockets_by_date(date_range)
  -> POST publicLogin.do {submitValue: Accept}
     -> _after_disclaimer
        -> POST publicCaseSearch.do {fromDt, toDt, ...}
           -> parse_search_results
              ↓
              for each row: GET publicCaseMaintenance.do
                            -> parse_case_detail -> ParsedData(MnDocket)
              ↓
              if has_next_page: POST next-page form -> parse_search_results
              ↓
              else if cap_hit and min_date < max_date:
                  POST publicCaseSearch.do {fromDt: max_date_seen}
                  -> parse_search_results
              else if cap_hit and min_date == max_date:
                  raise SearchVolumeAssumptionError
```

`accumulated_data` carries `from_dt`, `to_dt`, `start_row`,
`min_date_seen`, `max_date_seen`, and `total_records` between
pagination steps.
