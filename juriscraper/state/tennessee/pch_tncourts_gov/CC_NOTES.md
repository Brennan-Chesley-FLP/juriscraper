# Tennessee Public Case History (pch.tncourts.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Three appellate courts (`tenn`, `tennctapp`, `tenncrimapp`) behind one
> ASP.NET WebForms C-Track deployment. Plain-HTTP, server-rendered HTML
> (`driver_requirements = []`); document downloads and pagination are
> `__doPostBack` form re-POSTs of the same URL with preserved `__VIEWSTATE`
> hidden state. A single sequence-number search returns rows from all three
> courts at once, so this is a **multi-court speculative** scraper (§4): one
> `dockets_by_number` entry taking only its `SpeculativeRange`; the court is
> derived from the docket-number suffix at parse time. HTML extraction lives
> in the `parsers/` package (§9: `SearchResultsParser`, `CaseDetailParser`);
> the steps keep navigation (the search GET, pagination postbacks, the
> per-case fan-out, the PDF download postbacks). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `docket_number` (not `case_number`), `date_*` naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Not the `common/ctrack` package

This is **not** the Thomson Reuters/Travelers C-Track in
`juriscraper.state.common.ctrack` (which addresses `/public/caseSearch.do`
+ `/public/caseView.do?csIID=N` with DWR document links). Tennessee PCH is a
distinct ASP.NET WebForms variant: `SearchResults.aspx` / `CaseDetails.aspx`
with `__doPostBack` / `__VIEWSTATE` / `__EVENTVALIDATION`. None of the
`common/ctrack` helpers apply, so this scraper is self-contained.

## Site Overview

- **Base URL**: https://pch.tncourts.gov
- **Backend**: ASP.NET WebForms (IIS), hosted by the Tennessee
  Administrative Office of the Courts.
- **Requires Playwright**: No — server-rendered HTML for both search and
  case detail; document downloads are `__doPostBack` form submissions that
  re-POST the same URL with preserved hidden state.

### Bot protection / quirks

1. **Referer check on `/SearchResults.aspx`.** Both the speculative GET and
   the pagination POST 302 to `/Index.aspx` when the Referer is missing or
   off-site. We attach `Referer: https://pch.tncourts.gov/index.aspx` to
   both. Every other endpoint (`CaseDetails.aspx`, the PDF postback) is open.
2. **MAC-protected `__VIEWSTATE` / `__VIEWSTATEGENERATOR` /
   `__EVENTVALIDATION`** on every form-submitting page — transmitted
   verbatim from the page that rendered them.
3. No session cookies, no captcha, no JS challenge.

### `__doPostBack` quirk — do **not** use `form.submit()`

Both the PDF download and the page-2 pagination are ASP.NET LinkButton
postbacks. `form.submit()` fails: kent's form parser harvests every named
submit button as a default field, and IIS treats the *presence* of a
submit-button name in the body (even empty) as a real button click, ignores
`__EVENTTARGET`, and short-circuits to `/SearchResults.aspx`.
`_build_postback_data(page)` harvests only the hidden state + `txtSearch` +
the checked `SearchTerm` radio, deliberately omitting every submit `<input>`.
The only button name allowed in the body is `next1=Next` for pagination.

## Courts Covered

| Site code (3rd docket segment) | Display name | CourtListener ID |
|--------------------------------|--------------|------------------|
| `SC`  | Tennessee Supreme Court            | `tenn`         |
| `COA` | Tennessee Court of Appeals         | `tennctapp`    |
| `CCA` | Tennessee Court of Criminal Appeals | `tenncrimapp` |

The court is encoded in the docket-number suffix, not in any URL or form
field. A single sequence-number search returns rows from all three courts
simultaneously; `SearchResultsParser` derives `court` from the suffix.

## Docket Number Format

```
[E|M|W]YYYY-NNNNN-[SC|COA|CCA]-{appeal-type}-{case-type}
```

`NNNNN` is the 5-digit zero-padded sequence we speculate over. The search
performs a substring match against this segment across all years (back to
2006), all three grand divisions (E/M/W), and all three courts. Sequences in
the wild run 1 → ~5000.

## Search / speculation

```
GET https://pch.tncourts.gov/SearchResults.aspx?k=<seq>&Number=True
Referer: https://pch.tncourts.gov/index.aspx
```

- `k`: 5-digit zero-padded sequence number.
- `Number=True`: case-number search mode.

Empty / 0-result searches **302 to `/Index.aspx?count=0`**. Without
`FOLLOW_REDIRECTS` the driver sees the 302 (a non-2xx miss for speculation);
`actually_successful` additionally treats a 200 results page with no
`redirectToCase(` row handlers as a miss.

Recommended seed: `{"min": 1, "gap": 50}`.

### Pagination

Each results page shows up to 20 rows. When a sequence has more matches, the
page shows a `name="next1" value="Next"` submit button. Pagination is a
postback: re-POST `SearchResults.aspx` with all hidden fields preserved plus
`next1=Next` and `__EVENTTARGET=btnAdvanceSearch`. In practice only sequences
crossing 20 results paginate; most yield one page.

## Data Available

### Case Detail (`CaseDetails.aspx?id=<MastCastID>&Number=True`)

`CaseDetailParser` extracts:

- **Header** (`<h1 class="case-title">`): caption (→ `case_name`).
- **Case Overview** (`<div id="case-overview2">`): `intermediate_docket_number`,
  `trial_court`, `assigned_to_str` (trial judge), `trial_court_docket_number`.
- **Case Milestones** (`<table id="milestones">`): one `TnMilestone` per row,
  plus folded scalars — `date_filed` (Application Filed / Record Filed),
  `date_closed` (Closed Date), `date_decision` (Decision Date),
  `disposition`, `decision_type`, `panel_str`.
- **Parties** (`<div id="case-parties">`): `TnParty` rows (name, role, counsel).
- **Case History** (`<div id="case-history">`): `TnDocketEntry` rows
  (`date_filed`, `event`, `filer`, `postback_target`) — the docket / register
  of actions. Rows with a PDF link carry the `__doPostBack` target.
- **Record Information** (`<div id="record-information">`): `TnRecordEntry`
  rows (`volume_type`, `volumes`, `record_type`).

### Documents

PDF availability is **per docket-history row**. The link text is
`__doPostBack('ListView10$ctrl<N>$ListView12$ctrl0$LinkButton1','')`. Issuing
the postback (re-POST the detail URL with that as `__EVENTTARGET`) returns
`Content-Type: Application/pdf` directly — no intermediate redirect. Yielded
as a separate top-level `TnDocument` (CL `RECAPDocument`), joined back to the
docket via `docket_number` + `entry_index`.

### Out of scope

Oral-argument schedules/videos live on the marketing domain
(`tncourts.gov`), not on this case-search domain — a separate scraper. No
email-notification links.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_number(docket_number)` | `SpeculativeRange` | Speculative walk of the 5-digit sequence segment. Multi-court speculative — takes **only** the `SpeculativeRange` (no `court_ids`); court derived from the docket-number suffix. |

### Step functions and priorities (§5)

```
dockets_by_number → parse_search_results (4)
                      ├→ (per row)  parse_case_detail (2) → ParsedData(TnDocket)
                      │                 └→ (per PDF) handle_document_download (archive=True → priority 1)
                      └→ (next page) parse_search_results (4)
```

Priorities descend by depth so in-flight cases finish before new searches
advance. PDF downloads use `archive=True` (auto priority 1).

### Deduplication keys (§6)

- `dockets_by_number:<seq>` — the speculative search GET.
- `docket_detail:<MastCastID>` — each case-detail fetch (dedups a case
  surfaced by multiple overlapping sequence searches).
- `pdf-<MastCastID>-<postback-target>` — each PDF download (colon-free; the
  key feeds the archived filename).
- pagination POST uses `SkipDeduplicationCheck()` (non-idempotent postback).

### Data types

`TnDocket` (main, → CL `Docket` + `OriginatingCourtInformation`) with nested
`TnMilestone`, `TnParty`, `TnDocketEntry` (→ `DocketEntry`), `TnRecordEntry`.
`TnDocument` (→ `RECAPDocument`) is a separate top-level record per archived
PDF.
