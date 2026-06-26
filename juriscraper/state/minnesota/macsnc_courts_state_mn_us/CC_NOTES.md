# Minnesota P-MACS (macsnc.courts.state.mn.us) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two appellate courts (`minn`, `minnctapp`) on one P-MACS C-Track
> install. Volterra/F5-protected Java/JSP site → requires Playwright
> (`JS_EVAL` + `FF_ALIKE`). HTML extraction lives in the `parsers/`
> package (§9); steps keep navigation (disclaimer handshake, pagination,
> the 1000-row cap date-bisection, the ORCA fetch, the per-entry document
> walk, and the archive fan-out). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `docket_number` (not
> `case_number`), `court` (not `court_id`), `date_*` naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `https://macsnc.courts.state.mn.us/ctrack/`
- **Backend**: Java/JSP C-Track deployment — the older sibling of the
  HTML-form C-Track sites (SC/DC) in
  `juriscraper.state.common.ctrack`, but under a `/ctrack/` path prefix
  and with a different search-form field set, so it carries its own
  form/parser logic rather than reusing that shared module.
- **Bot protection**: F5/Volterra WAF returns 403 to plain `curl` and
  serves a JS challenge to browser-UA requests. A real browser executing
  the JS unlocks access → `DriverRequirement.JS_EVAL` + `FF_ALIKE`.
- **Requires Playwright**: yes.

## Disclaimer Handshake

The first request to the search endpoint redirects to
`/ctrack/publicLogin.jsp` ("Accept" button). The button POSTs to
`/ctrack/publicLogin.do` with `submitValue=Accept` and sets a session
cookie authorising the rest of the session. Every run performs this
handshake first (`_begin_session` → `after_disclaimer`).

## Courts Covered

| Jurisdiction text on results | CourtListener ID |
|------------------------------|------------------|
| Court of Appeals             | `minnctapp`      |
| Supreme Court                | `minn`           |
| Commitment Appeal Panel      | (skipped — not an appellate court in CL) |

The search is run all-jurisdiction; the listing parser maps each row's
jurisdiction text to a CL id and drops anything outside the two
appellate courts. The step further filters listing rows to the seeded
`court_ids` (carried via `accumulated_data["target_courts"]`, §2).

## Search Capabilities

`publicCaseSearch.do` (POST). Fields used: `fromDt` / `toDt`
(`MM/DD/YYYY` date-range), `csNumber` (case-number lookup), and the
hidden skeleton (`startRow`, `displayRows=50`, `orderBy=SQLFileDt`,
`orderDir=ASC`, `submitValue`, `button`, `hrefName`). We sort
`SQLFileDt ASC` so paginating to the last page reveals the latest
filed-date in the result set — the resume boundary on cap hits.
`displayRows` is capped at 50 server-side.

### 1000-Row Cap

Every search returns at most 1000 rows. On a cap hit we date-bisect:
walk every page in the interval, track min/max filed dates seen, then
resume with `fromDt = max_filed_date_seen` (boundary inclusive — the
`docket_detail:<docket_number>` dedup key filters the overlap). If the
cap is hit on a single-day window, the scraper raises
`SearchVolumeAssumptionError` (a `ScraperAssumptionException` subclass
defined in `scraper.py`).

## Data Available

### Case Detail (`publicCaseMaintenance.do`) — `CaseDetailParser`

A label/value Case Information block, then Party Information and Docket
Information tables.

- **Case Information**: docket_number (Case Number), date_filed,
  jurisdiction, status, ORCA, hearing_type, classification, short_title,
  full_title, summary, citation; `csNameID`/`csInstanceID` from hidden
  inputs (or the URL).
- **Party Information** → `MnParty` (macs_id, role, name, attorneys).
  Attorneys are `<br>`-separated; reconstructed from `inner_html()`
  (`cell_lines`), "Pro Se" filtered out.
- **Docket Information** → `MnDocketEntry` (date_filed, description,
  docket_entry_type, filing_type, status, jurisdiction, `deID`,
  entry_url).

### ORCA Info (`publicLowerCourtSummary.jsp`) — `OrcaInfoParser`

Originating-court summary linked from the case sidebar → `MnOrcaInfo`
(appeal_from_str, court_agency, other, orig_case_number,
orig_case_title, related_case_numbers, decisionmakers). Fetched with
`Referer: {case_url}` (top-level navigation is rejected). Attached to
the docket before the entry walk. Returns no record for an empty page.

### Docket Entry Detail (`docketEntry.do`) — `DocketEntryParser`

Per docket entry exposing an `entry_url`, fetched sequentially. The page
repeats case info up top (`class="label"`, lowercase) then renders the
entry section (`class="Label"`, uppercase) — we scope to the uppercase
labels. Value cells render as `<option selected>` (joined on ` || `),
checked `<input type=radio>` (visible label = the input's tail text,
read via `query_strings`), or plain text. `parse_detail_fields` returns
the full label/value map → `entry.details`;
`populate_entry_typed_fields` promotes the well-known labels into typed
`MnDocketEntry` fields. Every `document.do?document={hash}` anchor →
`MnDocument` + an `archive=True` Request.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_filing_date(court_ids, date_range)` | `DateRange` | POST the date-range search; the server searches by filing date. Paginates + cap-bisects. |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Look up one docket by appellate case number (e.g. `A26-0748`). |

For a full backfill, run `dockets_by_filing_date` over a wide window.

### Step functions and priorities (§5)

```
entry → (POST publicLogin.do Accept)
      → after_disclaimer (6) → parse_search_results (5)
          ├─ (per row) parse_case_detail (4)
          │     → parse_orca_info (3)
          │         → parse_docket_entry_page (2)  [sequential entry walk]
          │             ├─ ParsedData(MnDocket)    [after the walk completes]
          │             └─ (per doc) archive document.do (1)
          │                   → handle_document_download → ParsedData(MnDocument)
          └─ pagination / cap re-POST → parse_search_results
```

Priorities descend by depth so in-flight cases finish before new
searches start; downloads land at the auto-assigned `archive` priority
(1). Entry walks are sequential (so the emitted `MnDocket` captures every
document URL + detail field); the file downloads run in parallel.

### Deduplication keys (§6)

- `session_seed:filing_date:<start>:<end>` / `session_seed:number:<n>` — the disclaimer POST.
- `search:number:<n>` — the case-number search POST. (Date-range searches
  use `SkipDeduplicationCheck` because pagination re-POSTs the same form.)
- `docket_detail:<docket_number>` — each case-detail fetch (dedups the
  overlap day on cap-bisection resume).
- `orca:<docket_number>` — the ORCA fetch.
- `docket_entry:<docket_number>:<deID>` — each entry-detail fetch.
- `<docket_number>-<deID>-<hash[:16]>` — file downloads (no colons; used
  in filenames).

### Data types

`MnDocket` (main → CL `Docket`) with nested `MnParty` (+ attorney
strings), `MnDocketEntry` (→ `DocketEntry`) and its `MnDocument`
attachments (→ `RECAPDocument`), and `MnOrcaInfo` (→
`OriginatingCourtInformation`). `MnDocument` is also emitted as a
top-level record from `handle_document_download` (join key
`docket_number` + `doc_entry_id`).

## HTTP status handling (§10)

No per-site soft-404 / status oddities have been observed that need an
`actually_successful` / `HTTP_CODE_TYPES` override; the Volterra
challenge is handled by the Playwright driver.
