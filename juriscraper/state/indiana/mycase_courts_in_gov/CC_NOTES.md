# Indiana MyCase (Appellate Courts) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Three appellate courts (`ind`, `indctapp`, `indtc`) on one host. **JSON
> API** — the public MyCase SPA is backed by a plain ASP.NET MVC REST
> endpoint, reachable directly with httpx (no Cloudflare, no JS challenge,
> no required cookies), so this scraper runs plain HTTP
> (`driver_requirements = []`) and has **no `parsers/` package** (JSON, not
> HTML — JKentParser/PageElement do not apply; extraction lives in the
> steps and module-level helpers, arkansas/nevada-style). Model fields
> follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not
> `court_id`), `date_*` date naming, `case_name` carries
> `HarmonizedCaseName`, party/attorney names carry `CleanString`.

## Site Overview

- **Base URL**: https://public.courts.in.gov/mycase/
- **Public app**: SPA at `https://public.courts.in.gov/mycase/#/vw/Search`
  (URL hash carries a base64-encoded JSON state; the SPA calls a plain JSON
  REST backend).
- **Backend stack**: ASP.NET MVC (`X-Powered-By: ASP.NET`,
  `X-AspNetMvc-Version: 5.2`).
- **Requires Playwright**: **No.** The JSON API is reachable directly with
  httpx — no CloudFlare, no JS challenge, no required cookies (status 200 +
  valid JSON for both search and case-detail endpoints).
- **Case management system**: Odyssey (Tyler Technologies). The same
  endpoints serve both Indiana trial courts and the appellate courts — this
  scraper restricts itself to the appellate `CourtItemID`s.

## Courts Covered

| Site `CourtItemID` | Display Name        | Case-number court letter | CourtListener ID |
|--------------------|---------------------|--------------------------|------------------|
| 95                 | Court of Appeals    | `A`                      | `indctapp`       |
| 96                 | Supreme Court       | `S`                      | `ind`            |
| 97                 | Tax Court           | `T`                      | `indtc`          |
| 94                 | All Appellate Courts (multiplexed search; not a real court) | — | — |
| 92                 | All Odyssey Courts (used by `docket_by_number`) | — | — |

Per-result `CourtCode` (`S`, `A`, `T`, returned with trailing spaces) is
mapped back to the proper CourtListener id at parse time.

## Search Capabilities

Single JSON search endpoint:

```
POST https://public.courts.in.gov/mycase/Search/SearchCases
Content-Type: application/json
X-Requested-With: XMLHttpRequest
```

Modes: `ByCase`, `ByParty`, `ByAttorney`. Date-range filtering works on
`ByParty` with `Advanced: true`.

- `Categories` must be set; the SPA always sends `["CR","CV","FAM","PR"]`.
  An empty list returns no results.
- Date format `MM/DD/YYYY`.
- Pagination: `Skip` + `Take` (default 20, 100 confirmed working).
- Result cap: **TotalResults caps at 1001**; the scraper bisects the date
  range when `TotalResults > 1000`.

Observed monthly volumes (2026): Court of Appeals (`A`) ~286/month (bisect
for >2-month windows); Supreme Court (`S`) ~35/month; Tax Court (`T`) ~2-3.

### By-case-number lookup

`Mode: ByCase`, `CaseNum: "26S-DI-00136"`, `CourtItemID: 92` (All Odyssey).
Returns 1 result on a hit, 0 on a miss. Trial-court hits resolve to
non-appellate records and are filtered out at parse time.

### Captcha

The body has a `CaptchaAnswer` field (always sent `null` from the SPA); the
trigger threshold appears high and was not hit during probing. Not handled
in code; if 403/captcha responses appear, port them into
`actually_successful` / `HTTP_CODE_TYPES` (§10) as transient.

## Docket Number Format

`YY C - TT - NNNNN`: two-digit filing year, court letter (`S`/`A`/`T`),
two-letter case-type prefix, 5-digit sequence (zero-padded, reset yearly,
shared across all case types within a court+year). Examples:
`26S-DI-00136`, `26A-CR-00794`, `26T-TA-00009`. Because the sequence is
shared across case types, sequential speculation would have huge gaps — so
there is no `*_by_number` speculative entry; use date-based discovery for
bulk and `docket_by_number` for verified single lookups.

## Documents

`EventDocuments[].DownUrl` is a relative path (`/Case/Document/?token=…`)
combined with the host before fetching. Tokens are signed and short-lived
(fetch in the same scrape pass). Files are PDFs; `CanDown` is reported
`false` even when downloadable — ignore it and try the URL.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_filing_date(court_ids, date_range)` | `set[str]`, `DateRange` | Fans out one date-range search per requested court (`ind`/`indctapp`/`indtc` → its `CourtItemID`). Unknown ids raise. |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Single-case lookup by exact docket number via CourtItemID 92. `court_id` is carried through for attribution. |

### Step functions and priorities (§5)

```
entry → parse_search_results (3) → parse_case_detail (2) → download_document (1, archive=True)
         (paginate / bisect)        └→ ParsedData(InDocket)   └→ ParsedData(InDocument)
```

Priorities descend by depth so in-flight cases finish before new searches
start; downloads ride the `archive=True` default (priority 1).

### Deduplication keys (§6)

- `docket_by_number:<docket_number>` — the single-case search POST.
- `case_detail:<docket_number>` — each CaseSummary fetch (dedups a case
  surfaced by multiple searches).
- `<docket_number>-<document_id>-<filename>` — each archived PDF
  (colon-free; used in filenames).
- Date-search seed POSTs and pagination POSTs use
  `SkipDeduplicationCheck()` (the body changes between pages / the same URL
  is re-posted).

### Data types

- `InDocket` (main, → CL `Docket`) carrying nested `InParty` (+ `InAttorney`,
  `InAddress`), `InDocketEntry` (+ `InEventDocument` manifest rows),
  `InCrossReference`, `InRelatedCase`, plus trial-court linkage fields.
- `InDocument` — separately-emitted record per archived PDF (with
  `local_path`); joins back to its docket via `docket_number` / `case_key`.

## Out of Scope

- Oral-argument calendar (the MyCase site doesn't expose one; the courts
  publish HTML schedules at separate URLs).
- Per-case email/RSS alerts (require authentication).
