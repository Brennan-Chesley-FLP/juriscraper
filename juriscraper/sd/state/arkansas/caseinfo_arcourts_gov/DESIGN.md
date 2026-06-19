# Arkansas Appellate Courts Scraper Design

## Site Overview

- **Base URL**: https://caseinfo.arcourts.gov/opad
- **Backend**: Plain JSON REST API powering a Next.js frontend.
- **Requires Playwright**: No. `httpx` (the kent default) works directly. The
  API is gzip-encoded JSON; no bot protection, no session cookies, no CSRF
  tokens. `curl --compressed` confirms unauthenticated access.

The `/opad` path covers both Arkansas appellate courts (Supreme Court and
Court of Appeals); the same API filters between them via the `CourtName`
field.

## Courts Covered

| Site Court Name                       | CourtListener ID | Notes |
|---------------------------------------|------------------|-------|
| `STATE OF ARKANSAS SUPREME COURT`     | `ark`            | Arkansas Supreme Court |
| `STATE OF ARKANSAS COURT OF APPEALS`  | `arkctapp`       | Arkansas Court of Appeals |

The site also lists ~200 trial-court locations under the same dropdown. Those
are out of scope for this scraper — we filter strictly to the two appellate
court names above.

## Search Capabilities

| Rank | Mode | Status |
|------|------|--------|
| 1    | Date-based search (`startDate` / `endDate` on filing date) | **Used** |
| 2    | Case number lookup (`CaseId` filter on the search endpoint) | Available — not currently wired up |
| 3    | Participant / attorney / county filters                    | Out of scope |

**Recommended approach**: date-based via `get_dockets_by_date(date_range)`.
The search endpoint is paginated, never caps total results below the true
count, and supports filing-date filtering directly. No speculative
enumeration is needed.

### Search endpoint: `POST /opad/api/cases/search`

Request body (only the fields the scraper sets are listed; everything else
defaults on the server side):

```json
{
  "caseSearchRequest": {
    "searchCriteria": {
      "filterBy": [[
        {"fieldName": "CourtName", "operator": "EQUALS",
         "fieldValue": "STATE OF ARKANSAS SUPREME COURT"}
      ]],
      "paging": {"pageSize": 500, "pageNumber": 1}
    },
    "startDate": "2026-04-01T05:00:00.000Z",
    "endDate":   "2026-05-02T04:59:59.999Z",
    "caseType": "",
    "docketDesc": ""
  }
}
```

Notes:

- `pageSize` accepts up to 500 (1000 returns HTTP 500). The scraper uses 500.
- `paging.totalRecords` and `paging.totalPages` drive pagination.
- The site UI uses `T05:00:00.000Z` / `T04:59:59.999Z` as day boundaries,
  i.e. midnight Central Time expressed in UTC. The scraper follows the same
  convention so that "filed on date X" matches the UI.
- An empty `filterBy` (no `CourtName`) returns the union of every court in
  Arkansas. We always restrict to one of the two appellate names.

Response (excerpt):

```json
{
  "items": [
    {
      "caseId": "CV-26-294",
      "caseTitle": "COLE JESTER V LEAGUE OF WOMEN VOTERS OF ARK NON-TRIAL",
      "caseDesc":  "COLE JESTER V LEAGUE OF WOMEN VOTERS OF ARK",
      "caseFilingDate": "2026-04-30T16:53:46.000Z",
      "courtName": "STATE OF ARKANSAS SUPREME COURT",
      "courtLocation": "SUPREME COURT",
      "caseType": "CIVIL APPEAL CIRCUIT",
      "caseTrialDesc": "NON-TRIAL",
      "statusDesc": "ACTIVE",
      ...
    }
  ],
  "paging": {"pageSize": 500, "pageNumber": 1,
             "totalRecords": 26, "totalPages": 1}
}
```

The summary objects always come back with empty
`caseDocuments` / `caseDockets` / `caseEvents` / `caseParticipants` /
`caseMilestones` / `caseOffenses` / `caseSentences`. Those are populated
only on the case-detail endpoint.

### Case detail endpoint: `GET /opad/api/cases/{caseId}`

Returns one fully-populated case object. Same schema as a search-result
item, except the seven nested arrays are filled in. **Soft-404 behavior**:
this endpoint returns HTTP 500 with body
`{"message":"Response returned an error code"}` for unknown `caseId`s. The
scraper does not exercise this path speculatively — every `caseId` it
fetches comes from the search endpoint, which is deterministic.

### Document download: 2-step

`caseDockets[*].docketDocuments[*].documentFileId` (e.g.
`QUTQ38LVSXCTQ9FSKR15JILCZC3SLV`) cannot be downloaded directly. Instead:

1. `GET /opad/api/documents/{documentFileId}` returns
   `{"url": "<presigned S3 URL>"}`. The presigned URL is valid for 600
   seconds.
2. `GET <presigned S3 URL>` returns the PDF bytes.

The scraper schedules the API call as a normal step (parsed for the URL),
then schedules an `archive=True` request against the presigned URL with
`expected_type="pdf"`.

## Docket Number Formats

Single shared format across both appellate courts:

```
{TYPE_PREFIX}-{YY}-{SEQ}
```

| Prefix | Meaning                                                          |
|--------|------------------------------------------------------------------|
| `CR`   | Criminal appeal                                                  |
| `CV`   | Civil appeal                                                     |
| `D`    | Disciplinary / bar-related (Supreme Court only)                  |
| `E`    | (Historical) appears in archived court-of-appeals records         |

`{YY}` is the 2-digit year of filing; `{SEQ}` is the sequential filing
number for that year (no leading zeros — `CR-26-1`, `CV-26-294`,
`D-26-259`). Sequence numbers within a year are *not* shared between the
two appellate courts; the same `CR-26-228` may exist in both. Date-based
search returns one entry per (court, caseId) pair, and the scraper carries
`courtName` from the search result through into the `court_id` field, so
this overlap is handled correctly without ambiguity.

Speculative enumeration would require independent year-keyed sequences per
(court × prefix) combination. We do not implement it because the date
endpoint is sufficient.

## Data Available

### Case Summary
| Field          | Type                               |
|----------------|------------------------------------|
| `caseId`       | str (e.g. `CV-26-294`)             |
| `caseTitle`    | str — long-form title              |
| `caseDesc`     | str — short title                  |
| `caseFilingDate` | ISO timestamp                    |
| `courtName`    | str                                |
| `courtLocation`| str (e.g. `SUPREME COURT`)         |
| `caseType`     | str (e.g. `INCARCERATED CIVIL APPEAL`) |
| `caseTrialDesc`| str | None (e.g. `NON-TRIAL`)     |
| `caseSealed`   | str (`"0"` / `"1"`) — meaning unclear; cases with `"1"` still expose dockets and parties so this is *not* a "no public access" signal |
| `caseSecurity` | int                                 |
| `statusDesc`   | str (e.g. `ACTIVE`)                |

### Docket Entries (`caseDockets[]`)
| Field              | Notes                                                |
|--------------------|------------------------------------------------------|
| `docketSeqNo`      | int — entry sequence within the case                 |
| `docketType`       | site-internal code (e.g. `AC17$`, `ACCV`, `ACF49`, `ACG17`, `PA90`) |
| `docketDesc`       | human-readable description                           |
| `docketText`       | freeform notes                                       |
| `docketFilingDate` | ISO timestamp                                        |
| `entityId` / `entityName` | filer identifier + name (often counsel or "—") |
| `docketDocuments[]`| nested PDF references                                |

Each `docketDocuments[*]` carries:
- `documentSeqNo` (int)
- `documentDesc` (e.g. `BRIEFING SCHEDULE`, `LETTER`, `OPINION`)
- `documentFileId` (opaque token used in the document API)
- `documentName` (`<fileId>.pdf` typically)
- `documentUploadDate` (ISO timestamp)

### Participants (`caseParticipants[]`)
| Field      | Notes                                          |
|------------|------------------------------------------------|
| `seqNo`    | int                                            |
| `partyType`| `APPELLANT`, `APPELLEE`, `APPELLANT COUNSEL`, `APPELLEE COUNSEL`, `LOWER COURT JUDGE`, `LOWER COURT CLERK`, `RECUSED JUDGE`, etc. |
| `entityId` | int — site-wide participant id                 |
| `name`     | str                                            |
| `aliases`  | str | None — comma-separated alternate names  |

The scraper folds participants into a flat `parties` list with an attached
`role`; it does not try to reconstruct attorney-of-record relationships
because the API does not encode them (counsel is just another row with
type `APPELLANT COUNSEL` or `APPELLEE COUNSEL`).

### Milestones (`caseMilestones[]`)
Briefing schedule rows like `BRIEFING COMMENCED`, `APPELLANT'S BRIEF`,
`APPELLEE'S BRIEF`, `REPLY BRIEF`, with `dueDate`, `changedDueDate`, and
`filingDate` — all ISO timestamps that may be omitted.

### Documents
Yielded as a separate top-level model after archival, joinable to the
parent docket via `caseId` and `documentFileId`.

### Other arrays
`caseEvents`, `caseOffenses`, `caseSentences` are empty in every appellate
case observed (criminal sentencing data lives at the trial court level).
The scraper preserves them as raw JSON in the docket model so we don't
silently drop data if the site starts populating them.

## Email Notifications

Not available. The site has a per-case notification feature (the
"subscribe" affordance on each case detail page) but it is gated behind a
user account on `arcourts.gov`. The public `/opad` API does not expose it.

## Oral Arguments Calendar

Not surfaced through `/opad`. The Arkansas Judiciary publishes an oral
argument calendar separately at `arcourts.gov/courts/supreme-court`; that
is out of scope for this scraper.

## Bot Protection Notes

None observed. No CSRF token, no session cookies, no rate-limit headers.
The scraper rate-limits itself at 3 req/s as a courtesy.

## Scraper Architecture

### Entry Points

- `get_dockets()` — default (no-arg) entry; consults
  `self._get_date_params()` if scraper params include a date range,
  otherwise falls through to a 7-day default ending at "now".
- `get_dockets_by_date(date_range: DateRange)` — explicit date range.

Both run a search request per appellate court (two parallel sub-trees),
because the API takes one `CourtName` per search.

### Step Functions

```
entry → parse_search_results → parse_case_detail → fetch_document_url
                                                 → archive_document → ParsedData(ArDocument)
                                ↓
                                ParsedData(ArDocket)
```

- `parse_search_results` — paginates, dispatches one case-detail request
  per `caseId`. Pagination requests use `SkipDeduplicationCheck()`.
- `parse_case_detail` — builds the `ArDocket`, yields it, and schedules a
  document-URL fetch for every nested `documentFileId` we have not seen
  before. Dedup key is the `documentFileId`.
- `fetch_document_url` — reads `json_content["url"]`, schedules an
  `archive=True` request to the presigned S3 URL with
  `expected_type="pdf"`.
- `archive_document` — receives `local_filepath`, yields the
  `ArDocument` model.

### Models

- `ArDocket` — one per case, with nested `entries`, `parties`,
  `milestones`, plus passthrough lists for `events`, `offenses`,
  `sentences`.
- `ArDocketEntry`
- `ArParty`
- `ArMilestone`
- `ArDocument` — top-level, yielded post-archive. Carries its own
  document + docket metadata (pulled from `caseDockets` and threaded
  through `accumulated_data`); joins back to `ArDocket` via
  `docket_number`.
