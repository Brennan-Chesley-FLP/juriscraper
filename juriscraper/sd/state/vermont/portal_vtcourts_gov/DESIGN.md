# Vermont Judiciary Public Portal Scraper Design

Scraper for the Supreme Court of Vermont, served via the
[Vermont Judiciary Public Portal](https://portal.vtcourts.gov/Portal/Home/).

## Site Overview

- **Base URL**: <https://portal.vtcourts.gov/Portal/Home/>
- **Vendor**: Tyler Technologies — *Odyssey Public Portal* (footer:
  "© Tyler Technologies, Inc. … Version: 2017.1.61.2"). This is the
  same product that powers
  [`rhode_island/publicportal_courts_ri_gov`](../../rhode_island/publicportal_courts_ri_gov/),
  but with two differences that materially simplify the Vermont scraper:
  1. **No reCAPTCHA.** The form's `Settings.CaptchaEnabled` hidden field
     is `False`. RI ships with `True` and gates every submit on a
     reCAPTCHA solve.
  2. **No DataDome.** Plain `httpx` with a Chrome `User-Agent` returns
     HTTP 200 from `/Portal/*`. RI returns 403 to non-browser clients
     at the edge.

  The two factors together mean Vermont is a **pure httpx scraper**
  while RI must run under Playwright.
- **Backend**: ASP.NET MVC. The form posts URL-encoded values to
  `/Portal/SmartSearch/SmartSearch/SmartSearch` (302 → empty
  `WorkspaceMode`). The actual search-result grid is rendered by a
  separate AJAX GET to
  `/Portal/SmartSearch/SmartSearchResults?_=<n>` driven by JavaScript
  in the workspace shell. Per-case detail pages are a separate Tyler
  *Register of Actions* SPA at `/app/RegisterOfActions/` backed by a
  JSON OData service at `/app/RegisterOfActionsService/`.
- **Requires Playwright**: **No.** Plain httpx with a real-browser
  `User-Agent`; the framework's default `User-Agent` may need overriding
  if the deploy default is too clearly a bot string.
- **Transport**: hybrid — search is HTML, per-case detail is JSON.

## Courts Covered

Vermont has **no intermediate appellate court**; the Supreme Court is
the only court of last resort. The portal covers all Vermont courts but
only one location is appellate:

| Site `CourtLocation` value | Display Name             | CourtListener ID |
|----------------------------|--------------------------|------------------|
| `Vermont Supreme Court`    | Supreme Court of Vermont | `vt`             |

The other 17 dropdown values cover trial-level units (Addison Unit,
Bennington Unit, Chittenden Unit, …) plus the Environmental Division and
Judicial Bureau. They are out of scope for this appellate scraper.

## Search Capabilities

The Smart-Search dashboard form (`#frmSS`) posts to
`/Portal/SmartSearch/SmartSearch/SmartSearch` with these fields:

| Field                                    | Purpose |
|------------------------------------------|---------|
| `caseCriteria.SearchCriteria`            | **Required** — single-input "Smart Search" box. Accepts a record number or `Last, First Middle Suffix`. |
| `caseCriteria.CourtLocation`             | Court dropdown value. We send `Vermont Supreme Court`. |
| `caseCriteria.SearchBy`                  | `SmartSearch` (default; alternatives: `CaseSearch`, `PartySearch`) |
| `caseCriteria.SearchCases`               | `true` |
| `caseCriteria.SearchByPartyName`         | `true` |
| `caseCriteria.SearchByNickName` / `…ByBusinessName` / `…UseSoundex` | `false` (defaults) |
| `caseCriteria.AdvancedSearchOptionsOpen` | `true` to enable filter fields below |
| `caseCriteria.NameLast` / `NameFirst` / `NameMiddle` / `NameSuffix` | Party name fields (advanced) |
| `caseCriteria.CaseType` / `CaseStatus` / `JudicialOfficer` | Filter selectors (advanced) |
| `caseCriteria.FileDateStart` / `FileDateEnd` | `mm/dd/yyyy` date range (advanced) |
| `Settings.CaptchaEnabled`                | `False` — preserved hidden field (no captcha here) |

### Search-mode constraints (probed 2026-05-05)

- **Party-name search at the Supreme Court** returns `No cases match
  your search` for common surnames (`smith`, `state`). The portal
  appears to suppress party-name lookups for the appellate court even
  when `SearchByPartyName=true`. The welcome-page text confirms the
  default-public-access tier is limited to "Civil Division and Judicial
  Bureau" — appellate cases are gated to a record-number lookup for
  anonymous users.
- **Date-range alone** does not submit: `caseCriteria.SearchCriteria`
  is required (the form is `*Required`). No date-only listing is
  possible.
- **Wildcard / partial searches** (`AP-`, `2024`) return `No cases
  match your search`.
- **Exact docket-number lookup works** for valid Supreme Court numbers
  (verified with `24-AP-121`, `26-AP-140`).

**Recommended approach**: speculative entry by case number for the
single appellate court. One `@entry` taking
`YearlySpeculativeRange`, since Vermont docket numbers are
year-partitioned (see below). Operators seed
`{"year": 2026, "min": 1, "soft_max": 200, "gap": 0}` (one entry per
calendar year being scraped); the scraper formats `YY-AP-NNN` and
issues one POST per probe.

## Docket Number Format

Vermont Supreme Court dockets follow `YY-AP-NNN`:

- `YY` = two-digit year (e.g. `24` for 2024, `26` for 2026)
- `AP` = literal, identifies the appellate-case prefix
- `NNN` = sequential, **unpadded** (1-3+ digits). Examples:
  `24-AP-121`, `26-AP-140`, `25-AP-160`, `25-AP-324`, `26-AP-121`.

The largest 2025 number observed (via the Vermont Judiciary public
website's recent-decisions list, 2026-05-05) is `25-AP-324`. The
scraper formats with `:03d` width since most observed cases have ≥3
digits, but leading zeros are not significant — the SmartSearch box
accepts `26-AP-1` and `26-AP-001` interchangeably.

`AP` is the only appellate prefix observed; there is no separate
prefix for petitions, certified questions, or original-jurisdiction
matters.

## Data Available

### Search-results grid (HTML)

Rendered into a Kendo data-grid at
`/Portal/SmartSearch/SmartSearchResults`. Each row carries:

| Field            | Source                                   |
|------------------|------------------------------------------|
| `CaseNumber`     | `<a class="caseLink">` text             |
| `EncryptedCaseId`| `data-caseid` attribute (32-hex)        |
| `CaseLoadUrl`    | `data-url` attribute — query string carries the longer `id=` token used to address the Register-of-Actions JSON service |
| `Style`          | row cell — case caption                  |
| `FileDate` / `FileDateText` | `mm/dd/yyyy`                  |
| `CaseTypeId.Description` | e.g. `Misdemeanor Appeal`, `Civil Appeal` |
| `CaseStatusId.Description` | e.g. `Active`, `Closed`         |
| `LocationName`   | `Supreme Court`                          |

The full grid payload is also serialised inline as JSON in a Kendo
`dataSource.data.Data[]` block, so we can extract structured fields
without parsing the table. Extracting the Register-of-Actions key from
`data-url` is the only piece we strictly need from the grid.

### Register-of-Actions JSON service

`/app/RegisterOfActionsService/` exposes one endpoint per section:

| Endpoint | What it returns |
|---------|------------------|
| `CaseSummariesSlim?key={key}&mode=portalembed` | Header (CaseNumber, Style, FiledOn, NodeId, location), CaseInformation (Type, Status), Assignments, DispositionInformation. Driver of every other JSON call: gives `CaseId` and `NodeId` (LocationId) needed for document URLs. |
| `Parties('{key}')?mode=portalembed&$top=50&$skip=0` | Parties + their attorneys (name, role, retained/appointed). |
| `Charges('{key}')?mode=portalembed` | Criminal charges (empty for civil). |
| `CombinedEvents('{key}')?mode=portalembed&$top=N&$skip=N` | Register-of-actions events. Includes `DocumentVersions[].DocumentFragments[].DocumentViewerIntents[].URI` — the integer DocumentFragmentID needed for document URLs. Paginates via `$top` / `$skip`; default UI uses 50 per page. |
| `OtherDocuments('{key}')?mode=portalembed&$top=50&$skip=0` | Documents not attached to an event. |
| `FinancialSummary('{key}')?mode=portalembed` | Fees / payments. |
| `PartyNames('{key}')?mode=portalembed` | Slim party listing for the header. |

The encrypted `key` is opaque to the scraper — we lift it from the
search-grid `data-url`'s `id=` query parameter and pass it through
unchanged. (Note the grid also exposes a *shorter* `EncryptedCaseId`
on `data-caseid`; that one addresses a different family of legacy
endpoints and **does not work** against the JSON service.)

### Documents

Documents are accessible to anonymous users for Supreme Court cases
(unlike most other Vermont divisions per the welcome-page notice).
Each `CombinedEvents.Events[i].Event.Documents[j]` carries:

- `DocumentID`, `DocumentName`, `DocumentTypeID.Description`
  (e.g. *Appellate Order Final Decision*, *Appellant's Brief*).
- `DocumentVersions[0].DocumentFragments[0].DocumentViewerIntents[0].URI`
  — the **integer DocumentFragmentID** that addresses the document.

The download is a 2-hop chain (under FOLLOW_REDIRECTS):

1. `GET /Portal//DocumentViewer/DisplayDoc?documentID={fragId}&caseNum={number}&locationId={nodeId}&caseId={caseId}&docTypeId={typeId}&isVersionId=false&docType=...&docName=...&eventName=...`
   → 302 → `GET /Portal/DocumentViewer/Index/{encryptedDocId}?...` →
   200 HTML with a `Download Document` link.
2. `GET /Portal/DocumentViewer/DownloadDocumentFile/Download?d=...&c=...&l=...&cn=...&fileName=...&docTypeId=...` → PDF.

(The double slash `Portal//DocumentViewer` is what the SPA sends; it
works either way.)

## Email Notifications

Tyler Odyssey supports per-case email subscription via *My Account*,
but anonymous users cannot register. Out of scope for this scraper.

## Oral Arguments Calendar

Not exposed on the portal. Vermont publishes oral-argument schedules
as PDF calendars on `vtcourts.gov`. Out of scope for this scraper —
candidate for a future per-court-calendar scraper.

## Bot Protection Notes

- **Server-rendered welcome page** has no captcha widget; the form's
  `Settings.CaptchaEnabled` is `False`. No reCAPTCHA, no hCaptcha.
- **No edge bot-protection layer.** curl with a Chrome User-Agent
  returns HTTP 200 from every endpoint tested (dashboard, SmartSearch
  POST, SmartSearchResults, JSON service). The default Chrome UA
  string is sufficient.
- **Session state** lives in `ASP.NET_SessionId`; the GET
  Dashboard primes it before the POST. kent's persistent httpx driver
  carries cookies across the request chain automatically.
- The POST returns `302 Found` redirecting to `/Portal/Home/WorkspaceMode`
  (an empty workspace shell) — under `FOLLOW_REDIRECTS` we'll see the
  empty workspace as the response, which is fine; the next step
  ignores it and fetches `SmartSearchResults` directly. The workspace
  is what populates the search context in the session cookie.

## Known Gaps (v1)

1. **Speculative-only entry** — there is no date-range, party-name,
   or wildcard mode that returns appellate cases for anonymous users.
   Operators must manage `seed_params` per year. This is the same
   constraint as the RI sibling.
2. **Date filed on the search result row is unreliable for
   incremental cutoffs** — the grid shows `FileDate` per row, but the
   speculative driver only sees one row at a time and cannot use the
   date as a stop signal. Year partitioning via
   `YearlySpeculativeRange` is the natural shape.
3. **Pagination on `CombinedEvents`** — v1 fetches `$top=200` in one
   request; cases with >200 events would need follow-up paging
   (`$skip=200`). The largest case observed during recon (`24-AP-121`)
   has 75 events.
4. **Document content-type** — the second hop of the document chase
   returns HTML (the *Document Viewer* shell). v1 parses out the
   `Download Document` href and follows it; the PDF is the third hop.
5. **PartyNames / Charges / FinancialSummary** are not parsed in v1.
   Charges are empty for non-criminal cases anyway; `Parties` covers
   the same data more completely than `PartyNames`.

## Scraper Architecture

### Entry Points

| Entry                                                  | Param                    | Purpose |
|--------------------------------------------------------|--------------------------|---------|
| `fetch_supreme_docket(case_id: YearlySpeculativeRange)` | year + sequence number  | Speculative `YY-AP-NNN` lookup at the Vermont Supreme Court. |

### Step Functions

```
entry → submit_search_form     (GET /Portal/Home/Dashboard/29 → form.submit())
       ↓
       fetch_results_grid      (GET /Portal/SmartSearch/SmartSearchResults)
       ↓
       parse_search_results    (extract case row + Register-of-Actions key;
                                yield request to CaseSummariesSlim)
       ↓
       parse_case_summary      (JSON — fold header into accumulated_data;
                                yield request to CombinedEvents)
       ↓
       parse_combined_events   (JSON — build VtDocketEntry list, collect
                                document descriptors; yield request to Parties)
       ↓
       parse_parties           (JSON — build VtParty list; yield ParsedData
                                with the assembled VtDocket; yield one document
                                fetch per archived document)
       ↓
       fetch_document_download (GET DisplayDoc → follow → parse Download
                                Document href; yield archive request for PDF)
       ↓
       handle_document_download (yield ParsedData with VtDocument)
```

### Models

- `VtDocket` — main per-case record. Carries header fields from the
  search row + `CaseSummariesSlim`, nested `entries` from
  `CombinedEvents`, nested `parties` from `Parties`, and
  `documents` listing every available archived document.
- `VtDocketEntry` — one register-of-actions row.
- `VtParty` — one party + their attorneys.
- `VtAttorney` — name + role (Retained / Court Appointed / …).
- `VtDocument` — one downloadable document (yielded as a separate
  `ParsedData` after each download completes).
