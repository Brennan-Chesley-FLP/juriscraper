# Missouri Case.net Scraper Design

## Site Overview

- **Base URL**: https://www.courts.mo.gov/casenet/filingDateSearch.do
- **Requires Playwright**: Yes — Cloudflare managed challenge gates every
  request from a fresh client. Direct curl returns HTTP 403; the browser
  takes ~10s to clear "Just a moment..." before the form is reachable.
- **Transport**: hybrid. The filing-date search page is server-rendered
  HTML, but every results table and case-detail tab is delivered as
  JSON via DataTables-style POST endpoints (`searchResult.do`,
  `cases/newHeaderData.do`, `cases/party.do`,
  `cases/docketEntriesSearch.do`). After the Cloudflare cookie is set we
  drive everything as JSON-API calls inside the Playwright page context.

## Courts Covered

The filing-date search lets the user pick *any* court in the dropdown,
including all 46 judicial circuits' trial courts. This scraper limits
itself to the four appellate courts. Trial-court coverage would need a
separate scraper (different docket-number conventions, very different
volume, different consumer in CourtListener).

| Site `courtCode`  | Site `countyCode` | JSON `courtCode` | Display name                         | CourtListener ID |
|-------------------|-------------------|------------------|--------------------------------------|------------------|
| `OSCDB0024_SUP`   | `SUP`             | `SC`             | Supreme Court of Missouri            | `mo`             |
| `SMPDB0005_EAP`   | `EAP`             | `EA`             | Eastern District Court of Appeals    | `moctapped`      |
| `SMPDB0001_SAP`   | `SAP`             | `SO` (assumed)   | Southern District Court of Appeals   | `moctappsd`      |
| `SMPDB0001_WAP`   | `WAP`             | `WE` (assumed)   | Western District Court of Appeals    | `moctappwd`      |

The JSON `courtCode` (used to build document download URLs) comes back on
the `newHeaderData.do` response per case, so the scraper does not need to
hardcode the SAP/WAP values — they are read off the response at runtime.

## Search Capabilities

**Decision tree**: site has a usable date-range filter → date-based
search.

The form (`filingDateSearch.do`) requires a court selection and a single
"Start date of 7-day search". The server enforces a fixed 7-day window
(documented in the form's heading and confirmed by the response banner:
"Displaying records returned for dates of April 20, 2026 to April 26,
2026"). There is no way to widen the window from the UI. The scraper
must therefore split any larger user-supplied date range into 7-day
chunks and submit one request per (court, chunk) pair.

Optional filters that we leave at their permissive defaults:

- `caseStatus` — All / Pending / Disposed (we send `A`)
- `caseType` — All / Civil / Criminal / Family / Infraction / Probate /
  Traffic (we send `All`)

**Recommended approach**: chunked date-based search. One `@entry` accepts
a `DateRange`, splits it into 7-day windows, and emits 4 (courts) × N
(chunks) initial search requests.

## Search Result Pagination

The visible HTML page renders only the first 10 rows; the rest are
fetched by DataTables via POSTs to the same `searchResult.do` URL with a
JSON body of the standard DataTables protocol
(`{draw, columns, order, start, length, search}`). The server honours
arbitrarily large `length` values — verified that `length=100` returns
all 13 rows for a sample window in a single response. The scraper sends
`length=1000` and treats the response as one page (well above any
realistic 7-day appellate-filing volume).

The search context (court, date, caseStatus, caseType) is read from the
**query string of the POST**, not from session state. This means the
scraper can skip the HTML page entirely once the Cloudflare cookie is
set: just POST `searchResult.do?countyCode=...&courtCode=...&startDate=...`
with the DataTables JSON body, get JSON back.

## Docket Number Formats

| Court | Prefix | Example      | Width                |
|-------|--------|--------------|----------------------|
| SC    | `SC`   | `SC101613`   | 6 digits             |
| ED    | `ED`   | `ED114465`   | 6 digits             |
| SD    | `SD`   | `SD38704`    | 5 digits (observed)  |
| WD    | `WD`   | (not probed) | 6 digits (assumed)   |

Numbers are continuous (not year-partitioned). Speculative entry would
work in principle, but date-based search is strictly better for this
site and we don't ship a speculative entry.

## Data Available

### Case Header (`cases/newHeaderData.do`)

| Field | Type | Notes |
|---|---|---|
| `caseNumber` | str | Docket number, e.g. `SC101613` |
| `caseDesc` | str | Style of case |
| `courtId` | str | Site internal court id (e.g. `OSCDB0024_SUP`) |
| `courtDesc` | str | Display name |
| `location` | str | Court name |
| `filingDate` | str | `MM/DD/YYYY` |
| `caseType` | str | Disposition-bearing type label, e.g. `AP Tran to SC- Post Opinion` |
| `caseTypeCode` | str | Short code |
| `caseSecurity` | str | "1" = public |
| `courtCode` | str | Short code used in document URLs (`SC`, `EA`, …) |
| `locnCode` | str | Internal location code |
| `caseDispositionDetail.dispositionDescription` | str | "Not Disposed" / disposition text |
| `appellateOriginNo` | obj | `{caseValue}` describing the underlying trial-court case |
| `appellateCaseNo` | obj | `{caseValue, courtId}` of the parallel appellate case (cross-court linkage) |
| `circuitCaseNo` | list | Trial-court refs — list of `{caseValue, courtId}` |
| `disposed` | bool | |
| `dismissed` | str | "F" / "T" |

### Parties (`cases/party.do`)

`partyDetailsList` array. Each party has:

- `formattedPartyName`, `desc` (e.g. "Appellant", "Respondent"),
  `descCode`, `formattedPartyAddress`, `formattedTelePhone`, `startDate`
- `attorneyList`: nested list of attorneys with the same field shape
  but `partyType: "attorney"` and `desc` like "Attorney for Appellant".

### Docket Entries (`cases/docketEntriesSearch.do`)

`docketTabModelList` array. Each entry has:

- `filingDate`, `docketDesc`, `docketText` (free-text; not always set),
  `sequenceNumber`, `docketCode`, `filingPartyFullName`,
  `behalfOfPartiesNames`, `eventDesc`, `confidential`
- `document`: list of attached PDFs (`recordId`, `documentId`,
  `documentTitle`, `documentExtension`). Documents may have a nested
  `documentModels` tree of supplementary attachments (e.g. a
  Transfer-to-SC filing may carry the underlying Court of Appeals
  opinion + motion + proof of notice).

### Documents

PDFs are fetched directly via:

```
https://www.courts.mo.gov/fv/c/{document_title}.PDF?courtCode={short_court_code}&di={document_id}
```

`{short_court_code}` is the `courtCode` field from the case header
response (`SC` for Supreme, `EA` for Eastern, etc). `{document_id}` is
the `documentId` (a.k.a. `cebdmsdId`) on each document model.

Some documents are confidential (`canSeeCaseDocuments: false` on the
docket entry); the scraper skips those.

## Email Notifications

"Track This Case" exists at
`/casenet/trackThisCaseLanding.do?caseNumber=…&courtId=…` but the
landing page is just a sign-up funnel for "Manage My Case", which is a
logged-in service. There is no public/anonymous email-subscription
endpoint. **Not implemented.**

## Oral Arguments Calendar

Not exposed via Case.net. Missouri publishes oral-argument calendars on
each appellate court's main site (e.g. `courts.mo.gov/courts/sup/...`)
as static PDFs. **Out of scope** for this scraper — would warrant a
separate per-court HTML/PDF scraper.

## Bot Protection Notes

- **Cloudflare**: every endpoint under `courts.mo.gov` is gated by a
  Cloudflare managed challenge for cold clients. A fresh navigation to
  `/casenet/filingDateSearch.do` shows the "Just a moment…" interstitial
  for ~5–10 seconds before clearing.
- After the cookie is set, both the HTML page and the JSON APIs work
  fine in the same Playwright context.
- The first request the scraper makes is a GET to the search form. That
  navigation lets the Playwright driver clear the challenge. All
  subsequent requests are non-navigating POSTs to the JSON APIs.
- No CSRF/anti-XSRF token on any endpoint. The `X-Requested-With:
  XMLHttpRequest` header is sent by the in-page DataTables but does not
  appear to be required.

## Scraper Architecture

### Entry Points

| Name | Param | Behaviour |
|---|---|---|
| `get_dockets_by_date(date_range: DateRange)` | explicit range | Splits `[start, end]` into ≤7-day chunks and emits a CF-warmup GET, with the chunked POSTs scheduled in the warmup continuation. |
| `get_dockets()` | none | Reads `date_filed` GTE/LTE from scraper params (default lookback = 7 days) then defers to the same chunking helper. |
| `get_docket(docket_id, court_id)` | explicit docket | Direct case-detail fetch; bypasses the search step. |

### Step Functions

```
entry → warmup_search (GET filingDateSearch.do)
      → for each (court, week) chunk:
          → fetch_search_results (POST searchResult.do, length=1000)
              → for each search hit:
                  → fetch_case_header (POST cases/newHeaderData.do)
                      → fetch_case_parties (POST cases/party.do)
                          → fetch_case_docket (POST cases/docketEntriesSearch.do)
                              → emit MoDocket; for each non-confidential
                                document: archive=True request to /fv/c/...
                                  → handle_document_download → emit MoDocument
```

Pagination: not needed — `length=1000` returns all rows for a 7-day
window in one response.

Deduplication: the case-header request uses `deduplication_key=docket_id`
so overlapping windows or repeated runs do not re-fetch case detail.

### Models

- `MoDocketEntry` — one row from the docket tab (no separate hearing type)
- `MoAttorney` — name, role, firm, address, phone
- `MoParty` — name, role, attorneys[], address, phone
- `MoDocument` — download_url, document_type, date_filed, description,
  local_path, document_id, parent_document_id (for nested
  `documentModels` attachments)
- `MoTrialCourtInfo` — embedded record of the originating circuit court
  ref (multiple are possible)
- `MoDocket` — top-level model
