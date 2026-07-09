# Michigan Appellate Courts (courts.michigan.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two courts (`michctapp` Court of Appeals, `mich` Supreme Court). Episerver
> SSR SPA fronted by Cloudflare. The full per-case detail JSON is gated by an
> *invisible* hCaptcha the SPA mints per page-load, so the scraper runs under
> **Camoufox** (`driver_requirements = [JS_EVAL, FF_ALIKE, HCAP_HANDLER]`) and
> lets the page mint the token: it navigates to a page and **promotes** the
> JSON the page fetches in the background via the driver's `Request.incidental`
> mechanism (`Singular(...)` matches the captured request; its response is
> pre-resolved into a follow-up request with no second round-trip). Because the
> transport is binary (a browser requirement makes the whole scraper
> browser-bound) and the server serves the HTML shell to any top-level
> navigation (keying on `Sec-Fetch-Dest: document`, not `Accept`), even the
> listing JSON is obtained this way: navigate to the listing URL, then promote
> the SPA's own client-side listing `fetch` (`resource_type="fetch"`
> disambiguates it from the same-URL HTML document). Case-detail extraction
> lives in `parsers/` as a JSON parser (`CaseDetailParser`), not an HTML
> `JKentParser` (lxml-only); steps keep navigation (pagination, per-court
> fan-out, the navigate→promote handshake, and reading the case number +
> filing date off each listing item to window and fan out). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `docket_number` (not `docket_id`), `date_*` date naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `https://www.courts.michigan.gov/case-search/`
- **Backend**: ASP.NET / Episerver SPA, fronted by Cloudflare, with hCaptcha
  (sitekey `9bf9cc63-9d2e-4f54-98f8-8d3063233b9c`) gating the case-detail JSON
  endpoints.
- **Requires a browser**: **Yes** (Camoufox). The case-detail JSON needs the
  invisible-hCaptcha `captchatoken` the SPA mints per page-load; we navigate
  and promote the resulting XHR rather than forge it. Since the transport is
  binary, the whole scraper is browser-bound — the listing is obtained by
  promoting the SPA's client-side `fetch` (a top-level navigation always
  returns the HTML shell, and the SSR HTML does **not** embed results). The
  passive hCaptcha resolves without interaction in practice; `HCAP_HANDLER` is
  belt-and-suspenders for a visible-challenge escalation.
  - **Document downloads (PDFs)** — direct, no captcha (not yet implemented).

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

### Case summary (listing `fetch`) — used to discover + window cases
docket number, caption, filing date, originating trial court(s), has-opinions
/ has-orders flags, COA/MSC/COC status & cross references. Drives pagination
and the per-case fan-out; the detail record supersedes it as the output.

### Case detail (full — captcha-gated, now collected)
All summary fields plus parties + attorneys of record, register-of-actions
docket entries, judges, trial-court judgments, case-type codes, and related
COA/MSC case numbers — parsed by `CaseDetailParser` from the promoted
`get*casedetaildata` JSON.

## Out of Scope

- **Opinions / orders result types** (`resultType=opinions|orders`) and the
  **document PDFs** linked under docket entries: the has-opinions/has-orders
  flags and document metadata are captured; PDF download/archive is not yet
  implemented.
- **Email notifications / oral-argument calendar**: no per-case alerts or
  date-searchable OA calendar exposed in the public case-search UI.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_filing_date(court_ids, date_range)` | `DateRange` | Walk each requested court's `Newest` listing, fan out a detail fetch per in-window case; stop when filing date < `start`. |
| `dockets_by_number(docket_number)` | `MichCourtRange` | Speculative single-case lookup: navigate straight to the case page and promote its detail XHR. Court rides on the range (§4 multi-court speculative). |

`dockets_by_number` takes a `MichCourtRange` (subclass of the shared
`CourtRange`) because the driver dispatches a speculative entry with **only**
its speculative param — the target court rides on the range. Seed one per court.

### Step functions and priorities (§5)

Every JSON payload is reached by a **navigate → promote** handshake: a browser
navigation captures the page's background request as an incidental, and a
follow-up `incidental=Singular(...)` request promotes that captured response
(pre-resolved at enqueue — no second network round-trip).

```
dockets_by_filing_date → (listing nav) → promote_listing (4)
    → parse_listing_page (3) ──(per in-window case)→ (detail nav) → promote_detail (2)
    │                        └─(next page)→ promote_listing (4)
    └ (detail nav) → promote_detail (2) → parse_case_detail (1) → ParsedData

dockets_by_number → (detail nav) → promote_detail (2) → parse_case_detail (1)
```

`promote_listing` pins `resource_type="fetch"` to select the SPA's JSON
listing fetch over the same-URL HTML document. `promote_detail` matches
`*casedetaildata*`. No PDF downloads yet, so nothing at priority 0.

### Deduplication keys (§6)

- Listing navs + their promote use `SkipDeduplicationCheck()` (pagination
  depends on the live Newest ordering; non-idempotent).
- `detail_nav:<court>:<n>` — each detail-page navigation.
- `detail:<court>:<n>` — each detail promote (one docket per case).

### Data types

`MichDocket` (main, → CL `Docket`) with nested `MichTrialCourtRef`
(→ CL `OriginatingCourtInformation`), `MichParty` (→ `Party`) carrying
`MichAttorney` (→ `Attorney`), `MichDocketEntry` (→ `DocketEntry`) carrying
`MichDocument`, and `MichJudgment` (originating-court detail). Summary fields
come from the listing; the detail collections are filled by `CaseDetailParser`
from the promoted `get*casedetaildata` JSON (`has_detail=True`).
