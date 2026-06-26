# North Carolina Appellate Courts (ncappellatecourts.org) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two courts (`nc` Supreme Court, `ncctapp` Court of Appeals) share one
> docket-sheet layout. Plain-HTTP, server-rendered HTML on both endpoints
> (no JS / captcha / cookies → `driver_requirements = []`). HTML extraction
> lives in the `parsers/` package (§9); the steps keep navigation only
> (link follow, per-case fan-out, pagination, archive downloads). Model
> fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not
> `court_id`), `docket_number` (not `case_number`/`docket_id`), `date_*`
> date naming, `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

Two cooperating sites cover the NC appellate courts:

- `https://www.ncappellatecourts.org/search-results.php` — eFiling document
  library with date-range / docket-number / party / attorney search.
  Returns a *filings feed* (one row per e-filed document, grouped per
  case). Slow (~20–30 s per request) but stable.
- `https://appellate.nccourts.org/dockets.php` — docket-sheet portal for
  the Court of Appeals (`court=2`) and Supreme Court (`court=1`). With
  `pdf=1` it returns a richly structured HTML docket sheet (despite the
  name): case header, history, lower-court info, register of actions with
  rulings, parties and attorneys. The "PDF" name is a misnomer; the
  response is `text/html`.

- **Requires Playwright**: No — both endpoints serve full HTML over httpx
  with a browser-like User-Agent. No CloudFlare challenge, no JS gating.
- **Transport**: HTML form (GET) on both endpoints.

## Courts Covered

| Site `court=` | Display Name | CourtListener ID |
|---|---|---|
| `1` | Supreme Court of North Carolina | `nc` |
| `2` | North Carolina Court of Appeals | `ncctapp` |

`search-results.php` uses string codes for the same courts:
`court_name=sc` (Supreme Court) and `court_name=coa` (Court of Appeals).

## Search Capabilities

The date-range filter on `search-results.php` applies to *document* filing
date — it surfaces cases with any e-filed activity in the window, not cases
newly opened in the window.

### Date-search quirk

`search-results.php` only honours the date filter when `bSearchTypeAnd=0`
("Or" search-condition). With `bSearchTypeAnd=1` ("And") on a date-only
query the server silently ignores both dates and returns the entire
~400 000-row corpus. The scraper hard-codes `bSearchTypeAnd=0`.

### Docket-number lookup

Direct, exact lookup at
`dockets.php?court={1|2}&docket={USER}&submit=Search` returns an
intermediate page with the case title and a link to the rich docket-sheet
view (`dockets.php?court={N}&docket={INTERNAL}&pdf=1&a=0&dev=1`). The
scraper follows that link in a second request — more robust to the
trailing `-001` part than synthesising the internal id.

## Docket Number Formats

| Court | Format | Examples |
|---|---|---|
| COA appeal of right | `YY-NNNN` | `26-310`, `25-1111`, `24-506` |
| COA petition       | `PYY-NNN` | `P26-334`, `P25-974`           |
| Supreme Court      | `NNNNX{1,2}YY[-N]` | `15P26`, `1A26`, `1PA26`, `258A22-2` |

`docket_by_number` picks the site court from the supplied `court_id`
(`nc` → `court=1`, `ncctapp` → `court=2`); if an unknown id is supplied it
falls back to routing by the docket-number regex (`^P?\d{1,2}-\d+$` → COA,
`^\d+[A-Z]+\d{2}(-\d+)?$` → SC).

## Data Available

### Docket sheet (`dockets.php?…&pdf=1`)
Case header (Case Number, "As of" date, Case Closed, Case Close Date,
Case Type, Mediation, long-title caption, Docket Date, File Date/Time,
Acquire Date, Bond Collection, Docket Fee, Pauper, Print Deposit, State
Appeals); History (Venue, Heard In, Previous Venue, To SC, From SC);
Lower Court Number(s) (location/county, judge, trial-court docket number);
register of actions ("Documents" table + free-text expansion with
FOR/BY/order text); Parties + best-effort Attorneys.

### E-filed documents (`search-results.php?sDocketSearch=…&exact=1`)
Per filing: type, sub-type, filer name, filed date, document URL
(`show-file.php?document_id=…`). Sealed filings appear with a `(Sealed)`
marker and no download link. Each filing is emitted as an
`NCAppealsDocument`, parallel to the docket; downloadable PDFs are also
archived (`archive=True`). The two record streams share `docket_number`
and a `date_filed` + `document_type` pair, so a downstream join can stitch
them — left to the consumer (lossy when a case has multiple same-day
filings of the same type).

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Single-case lookup by visible docket number. |
| `dockets_by_filing_date(court_ids, date_range)` | `DateRange` | Every case with any e-filing in the window. |

### Step functions and priorities (§5)

```
docket_by_number       ──▶ parse_docket_search_result (4) ──▶ parse_docket_sheet (3) ──▶ NCAppealsDocket
                                                            ▲                          │
dockets_by_filing_date ──▶ parse_filings_listing (4) ───────┘                          ▼
                                │                                              parse_case_filings (2)
                                └─▶ (next page) parse_filings_listing                  │
                                                                       ┌───────────────┤
                                                  archive (1) → handle_document_download → NCAppealsDocument
                                                                       └─▶ (sealed) ParsedData(NCAppealsDocument)
```

Priorities descend by depth so in-flight cases finish before new listings
start; the archive download is priority 1, the download handler priority 1.

### Deduplication keys (§6)

- `docket_by_number:<docket_number>` — the intermediate search.
- `docket_sheet:<docket_number>` — the rich docket-sheet fetch (dedups a
  case surfaced by both the lookup and a listing page).
- `case_filings:<docket_number>` — the per-case filings fetch.
- `<docket_number>-<document_id>.pdf` — each archived PDF (no colons, used
  as a filename).
- `SkipDeduplicationCheck()` — pagination postbacks only.

### HTTP success handling (§10)

`actually_successful` flags `dockets.php?…&submit=Search` results with 0
cases as a miss (the site returns HTTP 200 on a miss, signalled only by
the body text `Your search returned a total of …>0 cases`). Every other
200 (empty listings, the docket-sheet detail page) passes through as a
success. (The pre-migration code used a `fails_successfully` hook — dead
code in jkent v0.1.0 — now ported to `actually_successful` with the
boolean inverted.)

### Models

- `NCAppealsDocket` — top-level docket record (→ CL `Docket`).
- `NCAppealsDocketEntry` — one register-of-actions row (→ `DocketEntry`).
- `NCAppealsDocument` — one e-filed document, parallel record (→
  `RECAPDocument`).
- `NCAppealsParty` (+ `NCAppealsAttorney`) — parties & attorneys (→
  `Party`/`PartyType`, `Attorney`/`AttorneyOrganization`).
- `NCAppealsLowerCourt` — lower-court info block (→
  `OriginatingCourtInformation`/`TrialCourtData`).

## Known Gaps

- Per-row document URLs are emitted as parallel `NCAppealsDocument`
  records but **not** stitched into the docket's register-of-actions rows
  (the only join keys — `docket_number`, `date_filed`, `document_type` —
  are not unique for multiple same-day same-type filings).
- Attorney parsing is structured but best-effort; firm/address/phone are
  shared-block, not per-attorney.
- No Appeal Information Statement (`/ais-view.php`), order-text scraping
  (`orders.php`), or oral-argument calendar (`calendar.php`).
- `search-results.php` regularly takes 20–30 s; relies on the driver's
  default request timeout (≥ 60 s).

## Verified Examples

- COA appeal `26-310` → `dockets.php?court=2&docket=2-2026-0310-001&pdf=1`
  → `State v. Sings`.
- COA petition `P26-334` → `dockets.php?court=2&docket=2-P2026-0334-001&pdf=1`.
- Supreme Court `15P26` → `dockets.php?court=1&docket=1-2026-0015-001&pdf=1`
  → `Justice v Carriage Hill …`, with a `Previous Venue: N.C. Court of
  Appeals (200)` row surfacing the cross-court lineage.
```
