# Missouri Case.net (courts.mo.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Four appellate courts (`mo`, `moctapped`, `moctappsd`, `moctappwd`) on one
> Cloudflare-gated Case.net backend. **JSON-API scraper** — the user-facing
> search form is HTML, but every results table and case-detail tab is a JSON
> endpoint, so there is **no `parsers/` package** (JKentParser/PageElement are
> HTML-only); extraction lives in small static builders on the scraper
> (`_build_parties`, `_build_entries_and_documents`, `_collect_document_tree`).
> Runs under Playwright (`JS_EVAL`, `FF_ALIKE`) only to clear the Cloudflare
> managed challenge once; thereafter all data flows through `nonnavigating`
> JSON POSTs in the same browser context. Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `docket_number` (not `case_number`), `date_*` naming, `filepath_local`,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `https://www.courts.mo.gov/casenet/filingDateSearch.do`
- **Requires Playwright**: Yes — a Cloudflare managed challenge gates every
  request from a fresh client (cold `curl` → HTTP 403; the browser takes
  ~5–10s to clear "Just a moment…" before the form is reachable).
- **Transport**: hybrid. The filing-date search page is server-rendered HTML,
  but every results table and case-detail tab is delivered as JSON via
  DataTables-style POST endpoints (`searchResult.do`, `cases/newHeaderData.do`,
  `cases/party.do`, `cases/docketEntriesSearch.do`). After the Cloudflare
  cookie is set we drive everything as JSON-API calls inside the Playwright
  page context.

## Courts Covered

The filing-date search lets the user pick *any* court, including all 46
judicial circuits' trial courts. This scraper limits itself to the four
appellate courts.

| Site `courtCode`  | Site `countyCode` | Display name                         | CourtListener ID |
|-------------------|-------------------|--------------------------------------|------------------|
| `OSCDB0024_SUP`   | `SUP`             | Supreme Court of Missouri            | `mo`             |
| `SMPDB0005_EAP`   | `EAP`             | Eastern District Court of Appeals    | `moctapped`      |
| `SMPDB0001_SAP`   | `SAP`             | Southern District Court of Appeals   | `moctappsd`      |
| `SMPDB0001_WAP`   | `WAP`             | Western District Court of Appeals    | `moctappwd`      |

The short JSON `courtCode` (used to build document download URLs) comes back on
the `newHeaderData.do` response per case, so the scraper does not hardcode it.

## Search Capabilities

The form (`filingDateSearch.do`) requires a court and a single "Start date of
7-day search". The server enforces a fixed 7-day window with no way to widen
it, so the scraper splits any larger seeded range into 7-day chunks and submits
one search per (court, chunk). `length=1000` returns every row for a 7-day
appellate window in one response, so there is no pagination. The search context
(court, date) is read from the **query string of the POST**, not session state,
so the scraper skips the HTML page once the Cloudflare cookie is set.

## Data Available

- **Case header** (`cases/newHeaderData.do`): `caseNumber`, `caseDesc`,
  `courtId`, `courtCode`, `location`, `filingDate`, `caseType`/`caseTypeCode`,
  `caseDispositionDetail`, `disposed`, `dismissed`, `appellateOriginNo`,
  `appellateCaseNo`, `circuitCaseNo` (trial-court refs).
- **Parties** (`cases/party.do`): `partyDetailsList[]` — each party with a
  nested `attorneyList[]`.
- **Docket entries** (`cases/docketEntriesSearch.do`): `docketTabModelList[]` —
  `filingDate`, `docketDesc`, `docketText`, `sequenceNumber`, `confidential`,
  and a `document[]` list whose entries may carry a nested `documentModels`
  tree of supplementary attachments.
- **Documents**: fetched directly via
  `https://www.courts.mo.gov/fv/c/{title}.PDF?courtCode={short}&di={documentId}`.
  Confidential entries (`canSeeCaseDocuments: false`) are skipped.

## Out of Scope

- **Trial courts** — different docket conventions/volume/consumer.
- **"Track This Case"** email subscription — funnels to a logged-in service;
  no anonymous endpoint.
- **Oral-argument calendars** — published as static PDFs on each court's main
  site, not via Case.net.

## Bot Protection

Every endpoint under `courts.mo.gov` is gated by a Cloudflare managed challenge
for cold clients. The scraper's first request is a GET to the search form,
which lets the Playwright driver clear the challenge; all subsequent requests
are `nonnavigating` POSTs to the JSON APIs in the same context. There is no
CSRF token. `actually_successful` rejects a 200 that still carries the
"Just a moment…" challenge body so a slipped-through interstitial isn't treated
as a valid (empty) page.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Behaviour |
|-------|-------|-----------|
| `dockets_by_filing_date(court_ids, date_range)` | `set[str]`, `DateRange` | CF-warmup GET, then chunked (court × 7-day) search POSTs. Searches only the requested courts (carried via `accumulated_data["target_courts"]`). |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Direct case-detail fetch; bypasses search. |

### Step functions and priorities (§5)

```
entry → _dispatch_search_chunks (6) → parse_search_results (5)
          → parse_case_header (4) → parse_case_parties (3)
              → parse_case_docket (2)
                  ├→ emit MoDocket
                  └→ (per document) archive=True → handle_document_download (0) → emit MoDocument
docket_by_number → _dispatch_single_case (6) → parse_case_header (4) → …
```

Priorities descend by depth so in-flight cases finish before new searches
start; document downloads run at priority 0.

### Deduplication keys (§6)

- warmup GET / search POST — `SkipDeduplicationCheck()` (session warmup; POST
  body/query carries the search context).
- `case_detail:{docket_number}` — dedups a case surfaced by overlapping
  windows or a re-run with a wider range.
- `{docket_number}-{docket_sequence}-{document_id}.{ext}` — file download
  (colon-free; used in the archived filename).

### Data types

`MoDocket` (main, → CL `Docket`) with nested `MoParty` (+ `MoAttorney`),
`MoDocketEntry`, `MoTrialCourtInfo` (→ `OriginatingCourtInformation` /
`TrialCourtData`), and a flat `MoDocument` list (→ `RECAPDocument`).
`MoDocument` is also yielded as a separate top-level record once archived,
joinable back via `docket_number`.
