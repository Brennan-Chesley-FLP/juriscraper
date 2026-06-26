# Michigan Appellate Courts (courts.michigan.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two courts (`michctapp` Court of Appeals, `mich` Supreme Court). Pure-JSON
> Episerver SSR site: the listing endpoint returns `application/json` when
> called with `expand=*&currentPageUrl=%2Fcase-search%2F`. Runs plain HTTP
> (`driver_requirements = []`) — no captcha, no JS, on the listing/single-case
> paths. Because the site is JSON (not HTML), per-item extraction lives in the
> `parsers/` package as a JSON parser (`ListingItemParser`), not an HTML
> `JKentParser` (which only wraps lxml); steps keep navigation (pagination,
> per-court fan-out, single-case lookup). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `docket_number` (not `docket_id`), `date_*` date naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `https://www.courts.michigan.gov/case-search/`
- **Backend**: ASP.NET / Episerver SPA, fronted by Cloudflare, with hCaptcha
  (sitekey `9bf9cc63-9d2e-4f54-98f8-8d3063233b9c`) gating the case-detail JSON
  endpoints only.
- **Requires Playwright**: No, for what this scraper does:
  - **Listing / single-case endpoints** — plain HTTP works, no captcha.
  - **Per-case detail JSON endpoints** — require an hCaptcha JWT in the
    `captchatoken` header (out of scope, see below).
  - **Document downloads (PDFs)** — direct, no captcha.

The user-facing site terms ("Bulk data downloads … prohibited") apply to
redistribution; the JSON endpoints are publicly accessible.

## Courts Covered

| Site name           | CourtListener ID |
|---------------------|------------------|
| Michigan Court of Appeals | `michctapp` |
| Michigan Supreme Court    | `mich`      |

The site also exposes `Court Of Claims` (a trial-level court, **not** in
`courts-db`, skipped) and a `COA and MSC` combined-search convenience option.
A **Lower Court** facet lists every Michigan trial court (circuit, probate,
juvenile, district) plus admin agencies (MERC, MESC, PSC, LARA…); these surface
as the originating court of an appellate case but are not target courts.

## Search Capabilities

| Mode | Endpoint | Captcha | Used for |
|------|----------|---------|----------|
| Listing (cases) | `GET /case-search/?…&expand=*&currentPageUrl=%2Fcase-search%2F` | No | Date-ordered enumeration |
| Single-case lookup | `GET /api/CaseSearch/AdvancedSearchCaseDetails?aCaseId={id}` | No | Direct lookup by site case ID |
| Case detail (full) | `GET /c/courts/{coa,msc,coc}casedetaildata/{id}` | **Yes** (JWT) | Parties, dockets, attorneys, judges |
| Document download | `GET /4989b8/siteassets/...pdf` | No | Opinion/order PDFs |

### Listing API details

URL pattern (works directly):

```
https://www.courts.michigan.gov/case-search/
  ?page=1
  &resultType=cases            # or "opinions" / "orders"
  &sortOrder=Newest            # or A-Z, Z-A, Oldest, Relevance
  &pageSize=100                # max 100 (UI options 10/25/50/100)
  &aAppellateCourt=Court+Of+Appeals  # or "Supreme Court", "Court Of Claims", "COA and MSC"
  &expand=*
  &currentPageUrl=%2Fcase-search%2F
```

The response is a JSON Episerver page object whose `caseSearchResults` field
contains three result containers — `caseDetailResults`, `opinionResults`,
`orderResults` — each shaped:

```json
{ "currentPage": 1, "pageSize": 100, "totalPages": 49, "totalResults": 4848,
  "hasMoreResults": true, "selectedSortOption": "Newest", "searchItems": [...] }
```

**No date-range filter exists.** `aFilingDate*` / `dateFrom` etc. are silently
ignored. Date-bounded scraping walks `sortOrder=Newest` page-by-page and stops
when the oldest item on a page falls before the window start.

**Caps & quirks:**
- `pageSize` capped at 100 (larger values silently clamp to 10).
- The legacy `AdvancedSearchCaseDetails` endpoint does **not** honour
  `page=`/`pageSize=` — pagination must go through the SSR listing endpoint.
- Result count is uncapped (COA total exceeds 290k).

### `searchItem` schema (cases)

| Field | Type | Notes |
|-------|------|-------|
| `caseUrl` | `str` | e.g. `/c/courts/coa/case/380502` |
| `courtOfAppealsCaseNumber` | `int` | Numeric COA case ID |
| `supremeCourtCaseNumber` | `int` | Numeric MSC case ID |
| `courtOfClaimsCaseNumber` | `str` | `YY-NNNNNN-XX` form |
| `title` | `str` | Case caption |
| `filingDate` | ISO string | UTC offset present |
| `courts` | `list[str]` | Originating trial court(s) |
| `hasOpinions`, `hasOrders` | `bool` | Whether the case has linked docs |
| `courtOfAppealsCaseStatus` / `supremeCourtCaseStatus` | `str` | Open / Concluded |

The single-case lookup returns the same `searchItem` shape under
`caseDetailResults.searchItems`.

## Docket Number Formats

| Court | Format | Example | Highest observed (2026-05) |
|-------|--------|---------|----------------------------|
| Court of Appeals (`michctapp`) | bare integer, ~6 digits | `380502` | 380549 |
| Supreme Court (`mich`)         | bare integer, ~6 digits | `170011` | 170011 |
| Court of Claims (excluded)     | `YY-NNNNNN-XX`          | `26-000087-MZ` | — |

Numbers are continuous (not yearly): COA ~1–380k, MSC ~1–170k. This continuous
integer space is what `dockets_by_number` speculates over.

## Data Available

### Case summary (listing API; no captcha) — what this scraper collects
docket number, caption (`case_name`), filing date, originating trial court(s),
source URL, has-opinions / has-orders flags, COA/MSC/COC status & cross
references.

### Case detail (full — captcha-gated, NOT collected)
All summary fields plus dockets, parties, attorneys, judges, judgments,
opinion/order/brief docket subsets, consolidations, related cases.

## Out of Scope

- **Full case detail** (`/c/courts/get*casedetaildata/{id}`): gated by an
  *invisible* execute-mode hCaptcha (JWT in a `captchatoken` header, issued
  per page-load by the SPA). kent's `HCAP_HANDLER` covers visible challenge
  widgets; this invisible flow needs a tailored Playwright step, deferred.
- **Opinions / orders result types** (`resultType=opinions|orders`): the
  listing's has-opinions/has-orders flags are captured; the PDF-document
  enumeration is not yet implemented.
- **Email notifications / oral-argument calendar**: no per-case alerts or
  date-searchable OA calendar exposed in the public case-search UI.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_filing_date(court_ids, date_range)` | `DateRange` | Walk each requested court's `Newest` listing; stop when filing date < `start`. |
| `dockets_by_number(docket_number)` | `MichCourtRange` | Speculative single-case lookup by site case number; court carried on the range (§4 multi-court speculative). |

`dockets_by_number` takes a `MichCourtRange` (subclass of the shared
`CourtRange`) because the driver dispatches a speculative entry with **only**
its speculative param — the target court rides on the range and `search_key()`
translates the CL id to the site's `aAppellateCourt` value. Seed one per court.

### Step functions and priorities (§5)

```
dockets_by_filing_date → parse_listing_page (3) ──→ ParsedData (per in-window item)
                                           └─(next page)→ parse_listing_page (3)
dockets_by_number ───────────────────────→ parse_single_case (2) → ParsedData
```

No downloads in this version, so nothing at priority 0–1.

### Deduplication keys (§6)

- Listing pages use `SkipDeduplicationCheck()` (pagination postbacks are
  non-idempotent: page N depends on the live Newest ordering).
- `single_case:<court>:<n>` — each single-case lookup.

### Data types

`MichDocket` (main, → CL `Docket`) with nested `MichTrialCourtRef`
(→ CL `OriginatingCourtInformation`). The captcha-gated party/attorney/
register-of-actions models are reserved for a future detail step.
