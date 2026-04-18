# Montana Supreme Court Scraper Design

Scrapes docket data from the Montana Supreme Court at
supremecourtdocket.mt.gov via its JSON API (no HTML scraping; the public
site is an Angular SPA that calls a plain REST backend).

## Site Overview

- **Search UI**: https://supremecourtdocket.mt.gov/search
- **Search API**: `POST /api/docket/search`
- **Case detail (modern)**: `GET /api/docket/case-info?caseId=<caseId>`
- **Case detail (pre-2006)**: `GET /api/docket/case-info-pre-2006?caseNumber=<num>`
- **Document (modern)**: `GET /api/filenet/get-content-by-ctrack-id?ctrackId=<docId>&filename=<name>`
- **Document (pre-2006)**: `GET /api/filenet/get-content?objectId={GUID}&filename=<name>`
- **Requires Playwright**: No — the REST API returns JSON directly; the
  Angular SPA is just for display.

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
  "pageSize": 10,
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
  "page": {"size": 10, "number": 0, "totalElements": 20, "totalPages": 2}
}
```

Notes on each `caseStatus`:

- **0 / Active** and **1 / Closed post-2006** filter by `caseFilingDate`
  server-side; verified by cross-checking returned cases' `caseFilingDate`.
- **2 / Archive (1979-2005)** returns `500` if the body contains ONLY
  `dateFrom`/`dateTo` (no text filters). When text + date are both set, it
  accepts the call but returns 0 rows because archived records have
  `caseFilingDate: null` on the detail payload — date filtering is
  effectively a no-op for the archive. The scraper still submits date-
  filtered archive requests so that if the upstream fixes this, results
  will start flowing; today they will just be empty.

Pagination: zero-indexed `page`, standard `pageSize`. Follow-up requests
bump `page` until `number >= totalPages - 1`.

Default `pageSize=100` is used by the scraper to reduce round-trips.

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

Field map of `GET /api/docket/case-info?caseId=<N>`:

| Field | Type | Notes |
|-------|------|-------|
| `caseId` | int | Montana's internal case id (e.g., `27483`). |
| `caseNumber` | str | Public docket number. |
| `court` | str | Always "Supreme Court" for this system. |
| `originalCourt` | str \| null | Trial court name. |
| `caseType` | str \| null | e.g., "Direct Appeal - Domestic Relations". |
| `shortTitle` | str \| null | Short caption. |
| `fullTitle` | str \| null | Full caption (CRLF-delimited). |
| `summary` | str \| null | Rare. |
| `caseFilingDate` | date (`YYYY-MM-DD`) \| null | Filing date. |
| `originalCaseNumber` | str \| null | Trial-court docket id. |
| `caseStatus` | str \| null | Short code: `PB`, `C`, etc. |
| `citation` | str \| null | E.g., "2002 MT 40N" for decided cases. |
| `parties` | list\<Party\> | See below. |
| `dockets` | list\<DocketEntry\> | See below. |
| `extraCaseInfo` | object \| null | Usually `null` for modern cases. |

Party object: `{appellateRole, partyName, comment, attorney, attorneys}` —
`attorney` is a comma-joined string for legacy display; `attorneys` is
usually `null`.

Docket-entry object: `{documentDescription, filingDate, documents: [...]}`
with each document `{documentId, documentLocation, filenetObjectId}`.

### Case detail (pre-2006 — caseStatus 2)

Same shape but:

- `caseId` is always `null`. Primary key is `caseNumber`.
- `parties` is `null`. Use `extraCaseInfo.partysList` and
  `extraCaseInfo.attorneysList` (comma-joined strings).
- `extraCaseInfo.trialCourtJudge` is populated.
- Documents use `filenetObjectId` GUIDs; `documentId` is empty string.

### Documents

Sealed / non-public documents carry this signature in either schema:

- `documentLocation == "Unavailable.pdf"`
- `documentId == "0"`
- `filenetObjectId == "{0}"`

Scraper treats those as `MtSealedDocument` records — no download is
attempted.

Modern downloadable documents use the numeric `ctrack id` endpoint; archived
documents use the `filenet object id` endpoint. Both stream PDF content.

### Oral Arguments / Calendar

Not present in this API. The SPA shows no calendar view.

### Email Notifications

Not present in this API.

## Scraper Architecture

### Entry Points

| Entry | Parameter | caseStatus | Notes |
|-------|-----------|------------|-------|
| `active_dockets_by_date` | `DateRange` | 0 | Pages the Active search endpoint. |
| `closed_dockets_by_date` | `DateRange` | 1 | Pages Closed (2006+) by filing date. |
| `archived_dockets_by_date` | `DateRange` | 2 | Pages Archive (1979-2005). Server ignores dates today — see notes above. |
| `fetch_docket_by_number` | `caseNumber: str` | auto | Searches across all three categories, falls back to the pre-2006 endpoint. |

### Step Flow

```
{*}_dockets_by_date
  → paginate_search_results
    → for each hit: fetch_case_detail_by_id   (modern)
                    fetch_case_detail_by_number (pre-2006)
      → parse_case_detail
        → yield ParsedData(MtDocket)
        → for each docket entry:
            for each document:
              if sealed → yield ParsedData(MtSealedDocument)
              else       → yield Request(archive=True) → download_document
                            → yield ParsedData(MtDocument)
      → paginate with SkipDeduplicationCheck until page.number+1 >= totalPages

fetch_docket_by_number
  → try search with caseStatus=0,1,2 in sequence OR one combined call
  → on hit with caseId: fetch_case_detail_by_id
  → on hit without caseId: fetch_case_detail_by_number
```

### Deduplication

Pagination uses `SkipDeduplicationCheck()` so each page always fires.
Case-detail requests use `mt-case-<caseId>` or `mt-case-<caseNumber>` as
`deduplication_key` so overlapping date windows don't re-fetch cases.
Document archive requests use `mt-doc-<ctrackId>` or `mt-doc-<guid>` as
their dedup key.

### Yielded Types

- `MtDocket` — one per case.
- `MtDocument` — one per archived file (includes `local_path`, `case_id`,
  `docket_number` for joining).
- `MtSealedDocument` — one per "Unavailable.pdf" reference; carries
  `docket_number`, `case_id` (may be None for archive cases), and the
  entry's `filing_date` + `description` for context. No download is
  scheduled for these.

## Bot Protection

None observed. No hidden tokens, no CloudFlare, no cookies required for the
REST API. A short-lived TS cookie is set by the WAF but isn't enforced.

## Pagination Caps

No hard cap observed in tests. Using `pageSize=100`. If a future response
caps at some threshold, add date-window splitting (halve `dateFrom`→`dateTo`
on overflow).
