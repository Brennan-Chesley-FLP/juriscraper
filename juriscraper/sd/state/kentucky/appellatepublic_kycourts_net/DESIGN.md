# Kentucky Appellate Courts Scraper Design

## Site Overview
- **Base URL**: https://appellatepublic.kycourts.net
- **Product**: Thomson Reuters "C-Track Public Access" (a different product
  from the "TR Portal" deployments handled by `common/tr/`).
- **Frontend**: Vue.js SPA. The HTML shell is empty; everything is rendered
  from a JSON API.
- **Backend**: Apache Tomcat. API root: `/api/api/v1/`.
- **Requires Playwright**: **No.** Plain `httpx` works once the request
  carries the `x-ctrack-excludeselflinks: true` header — without it the
  search endpoint returns an empty `resultItems` array.

### Why this is *not* the TR Portal infrastructure (`common/tr/`)

`common/tr/` targets the newer Thomson Reuters "TR Portal" / "Public Portal"
product (Alabama, Oregon, Alaska deployments) which uses:

- A separate `*-api.*.gov` host
- Endpoints like `/courts/{guid}/cms/cases/{uuid}` and Spring HATEOAS-style
  `_embedded.results` + `page` envelopes
- Court UUIDs and per-court routing

Kentucky's "C-Track Public Access" is the older (Tomcat / Vue) variant:

- Single host serves both UI and API at `/api/api/v1/...`
- Endpoints like `/cases/{caseID}` and `/cases/{caseID}/docketentries`
- Pagination via `x-ctrack-paging-*` HTTP **headers** (not query params)
- Bare JSON arrays for collection endpoints (no envelope)
- Court is a free-text field on each case, not a routing component

Different URL shape, different envelope, different pagination — the
`TRPortalMixin` cannot be reused. We implement Kentucky from scratch.

## Courts Covered

| Site Court Name           | Case # Prefix | CourtListener ID |
|---------------------------|---------------|------------------|
| Kentucky Supreme Court    | `YYYY-SC-`    | `ky`             |
| Kentucky Court of Appeals | `YYYY-CA-`    | `kyctapp`        |

Court is identified on each case via `caseHeader.court` (string:
`"Kentucky Supreme Court"` or `"Kentucky Court of Appeals"`) and is also
encoded in the case number prefix.

## Search Capabilities

| Search Mode      | Date Filter | Useful For                            |
|------------------|-------------|---------------------------------------|
| Case Search      | No          | Case-number lookup / prefix probing   |
| Document Search  | No*         | Document text — not relevant for dockets |
| Trial Court Search | No        | Lookup by lower-court case number     |
| Opinion Search   | **Yes**     | Date-based, but limited to opinion-type docket entries only |
| Party Search     | No          | Party-name lookup                     |

*Document Search has a date field but it filters parent-document dates.

**No date-based docket search exists.** Case-number prefix is the only
viable enumeration vector for full dockets. Fortunately, Kentucky case
numbers are year-partitioned (`YYYY-{SC,CA}-####`), so a prefix search of
`2026-SC` returns every Supreme Court case filed in 2026.

**Recommended approach**: prefix-by-year bulk search (default
`get_dockets()` flow) with optional speculative single-case entries
(`fetch_sc_docket` / `fetch_ca_docket`) for incremental probes by sequence.

## Docket Number Formats

Both courts use `YYYY-{SC|CA}-####` — four-digit zero-padded sequence,
restarting each calendar year.

| Court | Format        | Annual count | Examples                    |
|-------|---------------|--------------|-----------------------------|
| ky    | `YYYY-SC-####`| 500–1100/yr  | `2026-SC-0005`, `2024-SC-0423` |
| kyctapp | `YYYY-CA-####` | 1300–3500/yr | `2025-CA-1064`, `2024-CA-0134` |

Records go back to at least 1990. Sequence numbers within a year are dense
but not gap-free.

## API Endpoints

All endpoints are on `https://appellatepublic.kycourts.net/api/api/v1/`
and require headers `Accept: application/json` and
`x-ctrack-excludeselflinks: true`.

### Search
```
GET /cases/search?queryString=true
    &searchFields[0].searchType=Starts With
    &searchFields[0].operation==
    &searchFields[0].values[0]={prefix or full case number}
    &searchFields[0].indexFieldName=caseNumber
```

Pagination via headers:
- Request:  `x-ctrack-paging-startindex` (1-based), `x-ctrack-paging-maxresults`,
  `x-ctrack-paging-calculatetotalcount: true` (request total on first page)
- Response: `x-ctrack-paging-totalcount`, `x-ctrack-paging-resultcount`,
  `x-ctrack-paging-moreresults`, `x-ctrack-paging-resultslimit: 10000`
  (server-imposed cap on total enumerable results per query)

Response body:
```json
{
  "resultItems": [
    {
      "id": "<caseID hash>",
      "indexID": "150000",
      "rowMap": {
        "caseNumber": "2026-SC-0005",
        "caseID": "<caseID hash>",
        "closed": true,
        "shortTitle": "IN RE: ...",
        "caseType": "REGULATION"
      },
      "score": 5.0
    },
    ...
  ],
  "headers": [...],
  "facets": [
    {"searchFacetName": "Court", "searchFacetItems": [{"value": "...", "count": 162, ...}]},
    {"searchFacetName": "Case Final", ...}
  ]
}
```

### Case Detail
```
GET /cases/{caseID}
```
Returns the case header (full record, not embedded):
`caseID, caseNumber, caseStatus, caseStatusDate, closed, shortTitle,
fullTitle, caseType, caseClassification, filedDate, court, courtLevel,
caseCategory`.

### Docket Entries
```
GET /cases/{caseID}/docketentries
```
Returns a JSON array. Each entry:
`docketEntryID, docketEntryType, docketEntrySubtype, docketEntryDescription,
submittedBy, submittedDate, filedDate, hasDocuments, customFields.Comments,
opinion`. The `caseHeader` is duplicated on every entry (we ignore that copy).

### Parties
```
GET /cases/{caseID}/parties
```
Returns a JSON array. Each party has `partyName.{firstName, lastName,
displayName, role}`, `address`, `partyStatus`, `proSe`, and `attorneys[]`
(each with `attorneyName.displayName`, `address`, `barNumber`).

### Trial Courts (lower courts)
```
GET /cases/{caseID}/lowercourts
```
Returns a JSON array. Each: `lowerCourtID, lowerCourtName,
lowerCourtCaseNumber, lowerCourtCaseTitle`.

### Documents (per docket entry)
```
GET /publicaccessdocuments?filter=parentCategory=docketentries,parentID={docketEntryID}
```
Returns a JSON array. Each document:
`dmsDocumentID, documentID, documentName, documentDescription,
documentText (an array of extracted text strings, sometimes large),
mimeType, parentSourceID, parentID, parentCategory, parentType,
parentSubtype, parentDate, documentAvailable`.

### Document Download
```
GET /documents/{documentID}/download
```
Returns the actual PDF. `documentID` is the hash from the documents list,
*not* `dmsDocumentID`.

## Data Available

### Case Summary (`/cases/{caseID}`)
- `caseID` (hash)
- `caseNumber`
- `caseStatus` ("FINAL", "PENDING", etc.)
- `caseStatusDate`
- `closed` (bool — case finality)
- `shortTitle` (case caption)
- `fullTitle` (sometimes null)
- `caseType` (e.g., "REGULATION", "CIVIL", "WRIT", "FAMILY")
- `caseClassification` (e.g., "LAWYERS - REGULATION - SCR OTHER (PUBLIC)")
- `filedDate`
- `court` ("Kentucky Supreme Court" / "Kentucky Court of Appeals")
- `courtLevel` ("Supreme Court" / "Court of Appeals")
- `caseCategory` ("Appellate")

### Docket Entries
- `docketEntryID` (hash)
- `filedDate`
- `docketEntryType`, `docketEntrySubtype`, `docketEntryDescription`
- `submittedBy`, `submittedDate`
- `hasDocuments` (bool — gates whether a documents fetch is worthwhile)
- `customFields.Comments`
- `opinion` (bool)

### Parties
- `partyID`, `displayName`, `role`, `partyStatus`, `proSe`, `address`
- `attorneys[]` with `displayName`, `address`, `barNumber`

### Trial Courts
- `lowerCourtName`, `lowerCourtCaseNumber`, `lowerCourtCaseTitle`

### Documents
- `documentID` (used for download URL)
- `documentName`, `documentDescription`
- `mimeType` (typically `application/pdf`)
- `parentID` (docket entry it belongs to), `parentCategory`,
  `parentType`, `parentSubtype`, `parentDate`
- `documentText[]` — extracted PDF text (kept out of our model;
  treat the PDF as the canonical artifact)

## Email Notifications
Not visible to public users. There is a "User menu" but the public-user
flow does not expose a subscription endpoint.

## Oral Arguments Calendar
Not exposed in the appellate-public C-Track UI as a discrete entry. Oral
argument calendars are published as administrative documents
(`SC ADMIN - ORAL ...` / `CA ADMIN - ORAL ...` case numbers searchable
via Document Search). Out of scope for the docket scraper.

## Bot Protection Notes
- `x-ctrack-excludeselflinks: true` is mandatory on search/list calls;
  the server treats its absence as an unauthenticated UI navigation and
  silently returns empty results.
- A `SESSION` cookie is issued on first call (`Path=/api/`) but is not
  required for subsequent calls — the server is stateless for read-only
  public access. We do not need cookies.
- No CSRF tokens, no JS challenges.

## Scraper Architecture

### Entry Points
- `get_dockets()` — default flow. For each court (filtered by
  `KyDocket.court_id` if set in params) and each year (filtered by
  `KyDocket.date_filed` if set in params, defaulting to current year only),
  yields a paginated `cases/search?...&caseNumber starts with YYYY-{SC|CA}`.
- `fetch_sc_docket(rid: YearlySpeculativeRange)` — speculative single-case
  fetch for Kentucky Supreme Court. Builds `YYYY-SC-####` and looks up
  the caseID via the search endpoint, then walks the case detail.
- `fetch_ca_docket(rid: YearlySpeculativeRange)` — same, for the Court
  of Appeals.

### Step Functions (flow)
```
search → parse_search_results          (per-page pagination, dedup by caseID)
            → parse_case_detail        (fetch /cases/{caseID})
                → parse_docket_entries (fetch /cases/{caseID}/docketentries)
                    → parse_parties    (fetch /cases/{caseID}/parties)
                        → parse_trial_courts (fetch /cases/{caseID}/lowercourts)
                            → fan out documents per docket entry → ParsedData(KyDocket)
                                ↓
                                parse_document_list per entry-with-hasDocuments
                                    → archive {documentID}/download
                                        → parse_document_download → ParsedData(KyDocument)
```

The main `KyDocket` is yielded once `parse_trial_courts` finishes. Each
`KyDocument` is yielded as a separate top-level record (joinable to the
parent docket via `case_id`).

### Models
- `KyDocketEntry` — single docket entry row
- `KyParty` (embedded as dict on the docket; mirrors site shape)
- `KyAttorney` (embedded inside party dict)
- `KyTrialCourt` (embedded as dict on the docket)
- `KyDocket` — top-level docket record
- `KyDocument` — top-level document record (one per archived file)

## Ingest Knobs / Operational Notes
- `x-ctrack-paging-resultslimit: 10000` is a hard cap per search query.
  Annual case counts top out around ~3500 (CA, late 1990s), well below
  the cap, so a single year-prefix search is always safe.
- Search returns up to ~25 results in the resultItems if no paging
  headers are sent; with paging headers we use `maxresults=200` per page
  and walk via `startindex`.
- The opinion search endpoint (date-based) is intentionally NOT used —
  it only surfaces opinion-type docket entries, not full dockets.
