# Vermont Judiciary Public Portal (portal.vtcourts.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Single court (`vt`, Supreme Court of Vermont). Tyler Odyssey Public
> Portal, **without** reCAPTCHA or DataDome, so it runs under plain HTTP
> (`driver_requirements = [FOLLOW_REDIRECTS]`). Hybrid transport: the
> Smart-Search results grid and the Document-Viewer landing page are HTML
> (parsed in the `parsers/` package, §9); per-case detail is a JSON OData
> service (`/app/RegisterOfActionsService/`), parsed inline in the steps
> (JKentParser/PageElement are HTML-only — SCRAPER_STANDARDS §3.5). Model
> fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not
> `court_id`), `docket_number` (not `case_number`), `date_*` naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: <https://portal.vtcourts.gov/Portal/Home/>
- **Vendor**: Tyler Technologies — *Odyssey Public Portal* (footer
  "Version: 2017.1.61.2"). Same product as
  [`rhode_island/publicportal_courts_ri_gov`](../../rhode_island/publicportal_courts_ri_gov/),
  but with two differences that materially simplify the Vermont scraper:
  1. **No reCAPTCHA.** The form's `Settings.CaptchaEnabled` hidden field
     is `False`. RI ships with `True` and gates every submit on a
     reCAPTCHA solve.
  2. **No DataDome.** Plain `httpx` with a Chrome `User-Agent` returns
     HTTP 200 from `/Portal/*`. RI returns 403 to non-browser clients at
     the edge.

  Together these make Vermont a **pure HTTP scraper** while RI needs
  Playwright.
- **Backend**: ASP.NET MVC. The form posts URL-encoded values to
  `/Portal/SmartSearch/SmartSearch/SmartSearch` (302 → empty
  `WorkspaceMode`). The actual search-result grid is rendered by a
  separate AJAX GET to `/Portal/SmartSearch/SmartSearchResults?_=<n>`.
  Per-case detail is a separate Tyler *Register of Actions* SPA at
  `/app/RegisterOfActions/` backed by a JSON OData service at
  `/app/RegisterOfActionsService/`.
- **Requires Playwright**: No. `FOLLOW_REDIRECTS` is required (the search
  POST and the `DisplayDoc` URL both 302).

## Courts Covered

Vermont has **no intermediate appellate court**; the Supreme Court is the
only court of last resort.

| Site `CourtLocation` value | Display Name             | CourtListener ID |
|----------------------------|--------------------------|------------------|
| `Vermont Supreme Court`    | Supreme Court of Vermont | `vt`             |

The other dropdown values cover trial-level units, the Environmental
Division, and the Judicial Bureau — out of scope for this appellate
scraper.

## Search Capabilities (probed 2026-05-05)

The Smart-Search dashboard form (`#frmSS`) posts to
`/Portal/SmartSearch/SmartSearch/SmartSearch`. `find_form().submit()`
preserves all hidden defaults; the scraper overrides only
`caseCriteria.SearchCriteria` (the docket number) and
`caseCriteria.CourtLocation` (`Vermont Supreme Court`).

- **Party-name search at the Supreme Court** returns "No cases match" for
  common surnames — the appellate court is gated to record-number lookup
  for anonymous users.
- **Date-range alone** does not submit (`SearchCriteria` is required).
- **Wildcard / partial searches** (`AP-`, `2024`) return no matches.
- **Exact docket-number lookup works** (verified `24-AP-121`, `26-AP-140`).

So the only viable addressing mode is **speculative by docket number**.

## Docket Number Format

Vermont Supreme Court dockets follow `YY-AP-NNN`:

- `YY` = two-digit year, `AP` = literal appellate prefix, `NNN` =
  sequential, **unpadded** (`24-AP-121`, `25-AP-324`, `26-AP-140`). The
  scraper formats `:03d`, but leading zeros are insignificant — the
  SmartSearch box accepts `26-AP-1` and `26-AP-001` interchangeably.
- Year-partitioned, hence `YearlySpeculativeRange`. `AP` is the only
  appellate prefix observed.

## Data Available

### Search-results grid (HTML)

Each row carries a `<a class="caseLink" data-url="…?id=<key>…">`; the
`id=` query param is the opaque ROA key the JSON service expects (the
shorter `data-caseid` addresses different, non-working endpoints). The
parser also lifts the visible columns (docket number, style, type,
status). `SearchResultsParser` returns one `VtSearchRow` per matching
row (at most one for an exact docket query).

### Register-of-Actions JSON service

`/app/RegisterOfActionsService/` endpoints used:

| Endpoint | What it returns |
|---------|------------------|
| `CaseSummariesSlim?key={key}&mode=portalembed` | Header (Style, FiledOn, NodeId), CaseInformation (Type, Status), DispositionInformation. Gives `CaseId`/`NodeId` needed for document URLs. |
| `CombinedEvents('{key}')?mode=portalembed&$top=N&$skip=N` | Register-of-actions events incl. document fragment IDs. v1 fetches `$top=200` (no paging). |
| `Parties('{key}')?mode=portalembed&$top=50&$skip=0` | Parties + attorneys. |

### Documents

Documents are accessible to anonymous users for Supreme Court cases. The
download is a 2-hop chase (under `FOLLOW_REDIRECTS`):

1. `GET …/DocumentViewer/DisplayDoc?…` → 302 → `DocumentViewer/Index`
   HTML (a `Download Document` link; lifted by `extract_download_href`).
2. `GET …/DownloadDocumentFile/Download?…` → the PDF (archived).

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_number(docket_number)` | `YearlySpeculativeRange` | Speculative `YY-AP-NNN` lookup at the Vermont Supreme Court. Single-court, so per §4 the speculative entry carries **no** `court_ids` arg; the court is always `vt`. Operators seed one template per calendar year. |

### Step functions and priorities (§5)

```
entry → submit_search_form (8) → fetch_results_grid (7) → parse_search_results (6)
      → parse_case_summary (5) → parse_combined_events (4) → parse_parties (3)
              ├→ ParsedData(VtDocket)
              └→ (per doc) fetch_document_download (2) → archive(1) →
                 handle_document_download (2) → ParsedData(VtDocument)
```

Priorities descend by depth so in-flight cases finish before new probes
start; the archive download auto-assigns priority 1.

### Deduplication keys (§6)

- `dockets_by_number:<docket_number>` — the session-seeding GET.
- `<docket_number>-<document_id>` — each document chase (no colon, since
  the key is used in filenames).
- The grid/JSON hops use default keys.

### Data types

`VtDocket` (main, → CL `Docket`) with nested `VtDocketEntry`
(→ `DocketEntry`), `VtParty` (+ `VtAttorney`, → `Party`/`Attorney`), and
slim `VtDocument` references. Archived files are emitted as separate
`VtDocument` (→ `RECAPDocument`) `ParsedData` records. `VtSearchRow` is a
non-emitted carrier between the grid parser and the JSON flow.

## Known Gaps (v1)

1. **Speculative-only entry** — no date-range/party/wildcard mode returns
   appellate cases for anonymous users. Operators manage `seed_params`
   per year.
2. **Pagination on `CombinedEvents`** — v1 fetches `$top=200` in one
   request; cases with >200 events would need `$skip` follow-up. Largest
   case observed (`24-AP-121`) has 75 events.
3. **PartyNames / Charges / FinancialSummary / OtherDocuments** not
   parsed in v1.
4. **Oral-argument calendar** is not on the portal (Vermont publishes PDF
   calendars on `vtcourts.gov`) — candidate for a future scraper.
