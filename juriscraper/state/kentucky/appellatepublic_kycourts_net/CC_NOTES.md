# Kentucky Appellate Courts (appellatepublic.kycourts.net) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two courts (`ky` Supreme Court, `kyctapp` Court of Appeals). Plain-HTTP
> JSON API — **no `parsers/` package** (SCRAPER_STANDARDS §3.5: the site is
> JSON-only; extraction lives in the steps + small module helpers, like
> arkansas/nevada). Model fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md):
> `court` (not `court_id`), `docket_number`/`docket_number_raw`, `date_*`
> naming, `filepath_local` on the document model, and
> `CleanString`/`HarmonizedCaseName` cleaning on free-text fields.

## Site Overview

- **Base URL**: `https://appellatepublic.kycourts.net`
- **Product**: Thomson Reuters "C-Track Public Access" — the JSON-API
  variant (Tomcat / Vue.js SPA).
- **API root**: `/api/api/v1/`
- **Requires Playwright**: No. Plain `httpx` works once the request carries
  `x-ctrack-excludeselflinks: true` — without it the search endpoint
  returns an empty `resultItems` array. `driver_requirements = []`.

### Why this is *not* the other "C-Track" families

- `common/tr/` (TR Portal): newer REST product on a separate `*-api.*` host,
  Spring HATEOAS `_embedded.results` envelopes, court UUIDs. Different host,
  envelope, and routing.
- `common/ctrack/` (HTML-form C-Track, DC + SC): the *server-rendered HTML*
  variant — search forms + ColdFusion-style detail pages parsed with
  `JKentParser`. Kentucky is the JSON-API variant: bare JSON arrays, header
  pagination, no HTML. Neither mixin is reusable; implemented from scratch.

## Courts Covered

| Site court name           | Case # prefix | CourtListener ID |
|---------------------------|---------------|------------------|
| Kentucky Supreme Court    | `YYYY-SC-`    | `ky`             |
| Kentucky Court of Appeals | `YYYY-CA-`    | `kyctapp`        |

Court is identified per case via `/cases/{id}.court` (string) and is also
encoded in the case-number prefix. Both courts use `YYYY-{SC|CA}-####`
(four-digit zero-padded sequence, restarting each calendar year). Records go
back to at least 1990; sequences within a year are dense but not gap-free.

## Search Capabilities

**No date-based docket search exists.** Case-number prefix is the only
viable full-docket enumeration vector. Because case numbers are
year-partitioned, a `Starts With` search of `2026-SC` returns every Supreme
Court case filed in 2026 — so a date range maps onto a per-(court, year)
prefix crawl.

## API Endpoints

All on `/api/api/v1/`, all requiring `Accept: application/json` and
`x-ctrack-excludeselflinks: true`.

- `GET /cases/search?queryString=true&searchFields[0].searchType=Starts With
  &searchFields[0].operation==&searchFields[0].values[0]={prefix}
  &searchFields[0].indexFieldName=caseNumber`
  — paginated via request headers `x-ctrack-paging-startindex` (1-based),
  `x-ctrack-paging-maxresults`, `x-ctrack-paging-calculatetotalcount: true`;
  response headers `x-ctrack-paging-resultcount` / `-moreresults` /
  `-resultslimit: 10000` (hard per-query cap). Body: `{resultItems: [{id,
  rowMap: {caseNumber, caseID, ...}}]}`.
- `GET /cases/{caseID}` — case header.
- `GET /cases/{caseID}/docketentries` — JSON array.
- `GET /cases/{caseID}/parties` — JSON array (parties + nested `attorneys[]`).
- `GET /cases/{caseID}/lowercourts` — JSON array.
- `GET /publicaccessdocuments?filter=parentCategory=docketentries,parentID={deID}`
  — JSON array, one record per file (`documentID`, `mimeType`, parent meta).
- `GET /documents/{documentID}/download` — the actual PDF (keyed on
  `documentID`, *not* `dmsDocumentID`).

## Soft-404 handling (§10)

`actually_successful(response)` returns `False` when a `/cases/search`
response is HTTP 200 with an empty `resultItems` array (a missing case /
speculation miss). All other endpoints return real 404s. (The old
`fails_successfully` name was dead code from a pre-v0.1.0 jkent and was
ported to the real `actually_successful` hook.)

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_filing_date(court_ids, date_range)` | `set[str]`, `DateRange` | Per-(court, year) case-number prefix crawl; the date range drives the year loop (no server-side date search exists). |
| `dockets_by_number(docket_number)` | `KyCourtYearRange` | Speculative single-case probe. The target court + year ride in the param (§4 multi-court speculative); seed one template per (court, year). |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Direct lookup of one already-known case number via the search endpoint. |

`KyCourtYearRange(YearlySpeculativeRange)` carries `court_id`; `from_int`
preserves `court_id` + `year` via `model_copy` as the driver advances. This
consolidates what were two per-court speculative entries
(`fetch_sc_docket` / `fetch_ca_docket`) into one canonical entry.

### Step functions and priorities (§5)

```
search → parse_search_results (6)        (per-page pagination, dedup by caseID)
            → parse_case_detail (5)      (/cases/{caseID})
                → parse_docket_entries (4)
                    → parse_parties (3)
                        → parse_trial_courts (2)  → ParsedData(KyDocket)
                            → parse_documents_list (2) per entry w/ documents
                                → archive {documentID}/download (auto-1)
                                    → parse_document_download → ParsedData(KyDocument)
```

Priorities descend by depth so in-flight cases finish before new searches
start; the archive download auto-assigns priority 1.

### Deduplication keys (§6)

- `search:{prefix-or-case-number}` — first search page; page 2+ uses
  `SkipDeduplicationCheck()` (header-driven pagination of the same URL).
- `case_detail:{caseID}` — dedups a case surfaced by multiple prefixes.
- `documents_list:{docketEntryID}` — the per-entry documents fetch.
- `{docket_number}-{documentID}` — the archive download (no colons; used in
  the stored filename).

### Data types

`KyDocket` (main → CL `Docket`) with nested `KyDocketEntry` (→ `DocketEntry`),
`KyParty` (→ `Party`/`PartyType`) + `KyAttorney` (→ `Attorney`/`Role`), and
`KyTrialCourt` (→ `OriginatingCourtInformation`). `KyDocument`
(→ `RECAPDocument`) is emitted as a separate top-level record per archived
file, joining back via `case_id` / `docket_number`.

## Out of Scope

- Opinion-search (date-based but opinion-entries only), document/party/
  trial-court search modes — case-number prefix covers full dockets.
- Oral-argument calendars (published only as admin documents).
- Email notifications (not exposed to public users).
