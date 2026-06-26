# Montana Supreme Court (supremecourtdocket.mt.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Single court (`mont`). **JSON API scraper** — the public site is an
> Angular SPA over a plain REST backend, so the scraper speaks the JSON API
> directly and has **no `parsers/` package** (SCRAPER_STANDARDS §3.5;
> cf. arkansas, nevada). Runs plain HTTP (`driver_requirements = []`).
> Model fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court`
> (not `court_id`), `docket_number`, `date_*` naming, and
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Search UI**: https://supremecourtdocket.mt.gov/search
- **Search API**: `POST /api/docket/search`
- **Case detail (modern)**: `GET /api/docket/case-info?caseId=<caseId>`
- **Case detail (pre-2006)**: `GET /api/docket/case-info-pre-2006?caseNumber=<num>`
- **Document (modern)**: `GET /api/filenet/get-content-by-ctrack-id?ctrackId=<docId>&filename=<name>`
- **Document (pre-2006)**: `GET /api/filenet/get-content?objectId={GUID}&filename=<name>`
- **Requires Playwright**: No — the REST API returns JSON directly; the
  Angular SPA is just for display.

### JSON-body workaround

kent's persistent driver does not propagate `HTTPRequestParams.json`
through serialize → DB → dispatch (only `data` is forwarded to httpx). The
search POST body is therefore encoded by `_encode_json_body()` and passed
via `data=` as bytes, with a leading UTF-8 BOM so the rebuild path keeps it
as bytes rather than round-tripping back to a dict (which httpx would
form-encode). The Montana API ignores the BOM.

## Courts Covered

| Site Category | Display Name | CourtListener ID |
|---------------|-------------|-----------------|
| All categories | Montana Supreme Court | `mont` |

Montana has no intermediate appellate court; everything in this system is the
Supreme Court. Cases are split across three site categories keyed by
`caseStatus`:

| caseStatus | UI label | Detail endpoint | Has numeric caseId? |
|-----------|----------|-----------------|---------------------|
| 0 | Active Dockets | `case-info?caseId=` | Yes |
| 1 | Closed Dockets (2006-Present) | `case-info?caseId=` | Yes |
| 2 | Closed Dockets (1979-2005) | `case-info-pre-2006?caseNumber=` | **No** |

## Search API

`POST /api/docket/search`, `Content-Type: application/json`:

```json
{
  "caseStatus": 0 | 1 | 2,
  "caseNumber": null | "<str>",
  "partyName": null | "<str>",
  "attorneyName": null | "<str>",
  "dateFrom": null | "YYYY-MM-DDTHH:MM:SS.sssZ",
  "dateTo":   null | "YYYY-MM-DDTHH:MM:SS.sssZ",
  "page": 0,
  "pageSize": 100,
  "sortDirection": "asc",
  "sortColumn": "caseNumber"
}
```

Response:

```json
{
  "content": [
    {"caseId": int | null, "caseNumber": "DA 26-0218", "caseTitle": "...", "attorneys": ["..."]}
  ],
  "page": {"size": 100, "number": 0, "totalElements": 20, "totalPages": 2}
}
```

Notes on each `caseStatus`:

- **0 / Active** and **1 / Closed post-2006** filter by `caseFilingDate`
  server-side.
- **2 / Archive (1979-2005)** returns `500` if the body contains ONLY
  `dateFrom`/`dateTo` (no text filters). When text + date are both set, it
  accepts the call but returns 0 rows because archived records have
  `caseFilingDate: null` on the detail payload — date filtering is
  effectively a no-op for the archive. The scraper still submits date-
  filtered archive requests so that if the upstream fixes this, results
  will start flowing; today they will just be empty.

Pagination: zero-indexed `page`. Follow-up requests bump `page` until
`number + 1 >= totalPages`. The scraper uses `pageSize=100` to reduce
round-trips.

## Docket Number Formats

- Active / recent cases use a prefixed form: `DA 26-0218`, `OP 26-0012`,
  `AF 26-0005`, etc. The prefix (`DA`, `OP`, `AF`, ...) encodes the case
  type.
- Older closed cases drop the prefix: `04-164`, `99-565`, `99-0012`, etc.
- The first two digits are the 2-digit year of filing.

The `caseNumber` search field accepts prefix substrings and matches
case-insensitively.

## Data Available

### Case detail (modern — caseStatus 0 or 1)

`GET /api/docket/case-info?caseId=<N>` → `caseId`, `caseNumber`, `court`
(always "Supreme Court"), `originalCourt`, `caseType`, `shortTitle`,
`fullTitle`, `summary`, `caseFilingDate`, `originalCaseNumber`,
`caseStatus`, `citation`, `parties[]`, `dockets[]`, `extraCaseInfo`.

Party object: `{appellateRole, partyName, comment, attorney, attorneys}` —
`attorney` is a comma-joined string for legacy display; `attorneys` is
usually `null`. Docket-entry object: `{documentDescription, filingDate,
documents: [{documentId, documentLocation, filenetObjectId}]}`.

### Case detail (pre-2006 — caseStatus 2)

Same shape but `caseId` is `null` (primary key is `caseNumber`), `parties`
is `null` (use `extraCaseInfo.partysList`), `extraCaseInfo.trialCourtJudge`
is populated, and documents use `filenetObjectId` GUIDs (`documentId` is
empty).

### Documents

Sealed / non-public documents carry this signature in either schema:

- `documentLocation == "Unavailable.pdf"`
- `documentId == "0"`
- `filenetObjectId == "{0}"`

The scraper emits these as `MtSealedDocument` records — no download is
attempted. Modern downloadable documents use the numeric ctrack-id
endpoint; archived documents use the filenet object-id endpoint. Both
stream PDF content via `archive=True`.

### Out of scope

- Oral arguments / calendar: not present in this API.
- Email notifications: not present in this API.

## Scraper Architecture

### Entry points (§4)

| Entry | Params | caseStatus | Notes |
|-------|--------|------------|-------|
| `active_dockets_by_filing_date(court_ids, date_range)` | `set[str]`, `DateRange` | 0 | Pages the Active search endpoint. |
| `closed_dockets_by_filing_date(court_ids, date_range)` | `set[str]`, `DateRange` | 1 | Pages Closed (2006+) by filing date. |
| `archived_dockets_by_filing_date(court_ids, date_range)` | `set[str]`, `DateRange` | 2 | Pages Archive (1979-2005). Server ignores dates today — see notes above. |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | auto | Searches across all three categories; the pre-2006 hits fall back to the `case-info-pre-2006` endpoint. |

For a full backfill, run the three `*_dockets_by_filing_date` entries over
a wide window (1979 → current). `court_ids` is validated to `{mont}` — the
court is constant for this single-court system.

### Step functions and priorities (§5)

```
*_dockets_by_filing_date / docket_by_number
  → parse_search_results (4)
    → (per hit) parse_case_detail (3)
        → yield ParsedData(MtDocket)
        → (per sealed doc) yield ParsedData(MtSealedDocument)
        → (per downloadable doc) Request(archive=True) → download_document (1)
            → yield ParsedData(MtDocument)
    → paginate with SkipDeduplicationCheck until number + 1 >= totalPages
```

Priorities descend by depth (4 → 3) so in-flight cases finish before new
search pages start; `archive=True` downloads auto-assign priority 1.

### Deduplication keys (§6)

- Search seed/pagination POSTs: `SkipDeduplicationCheck()` (same URL,
  body varies per page; must always fire).
- `docket_by_number` search POSTs: `search_results:<category>:num:<docket>`.
- Case detail: `case_detail:id:<caseId>` (modern) /
  `case_detail:num:<docket_number>` (pre-2006) — dedups a case surfaced by
  more than one category.
- Document downloads: `document-<identifier>` — colon-free since the key
  feeds the archived filename.

### Data types

- `MtDocket` — one per case (→ CL `Docket`), with nested `MtParty`
  (+ `MtAttorney`) and `MtDocketEntry`.
- `MtDocument` — one per archived file (→ CL `RECAPDocument`); carries
  `local_path`, `case_id`, `docket_number` for joining back.
- `MtSealedDocument` — one per `Unavailable.pdf` reference; no download
  scheduled.

## Bot Protection

None observed. No hidden tokens, no Cloudflare challenge, no cookies
required for the REST API. A short-lived TS cookie is set by the WAF but
isn't enforced.

## Pagination Caps

No hard cap observed in tests. Using `pageSize=100`. If a future response
caps at some threshold, add date-window splitting (halve `dateFrom`→`dateTo`
on overflow).
