# Arizona Appellate Courts (apps.azcourts.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Multi-court (`ariz` + `arizctapp`, Division One) on one AppellaDockets
> backend. Plain HTTP (`driver_requirements = []`) — static HTML, no bot
> protection. Every entry takes `court_ids: set[str]` and fans out per
> court/case-type (§4); dedup keys carry `court` because a single run spans
> two courts. HTML extraction lives in the `parsers/` package (§9); steps
> keep the fan-out, the `_update` cutoff early-stop, and PDF archive
> requests. Model fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md):
> `court` (not `court_id`), `date_*` naming, `CleanString`/
> `HarmonizedCaseName` cleaning.

## Site Overview

- **Public landings**:
  - `https://www.azcourts.gov/appellatecourtcases/ASC/Cases` (Supreme Court)
  - `https://www.azcourts.gov/appellatecourtcases/COA1/Cases` (CoA Div. 1)
- **Real data host**: `https://apps.azcourts.gov/aacc/appella/`
- **Requires Playwright**: No — server-rendered static HTML, no bot
  protection (Cloudflare for caching only, no challenge).

The user-facing pages are thin DNN portals embedding the data backend in
`<iframe>`s. All scraping targets `apps.azcourts.gov` directly — no session,
no JS, no cookies. The "Appella" / AppellaDockets backend publishes static
HTML regenerated nightly. Tables use auto-generated `htmldwXXXX` CSS classes
(hex changes per nightly build), so selectors rely on document structure
(column order, anchor text, hidden cells), never class names.

PDF hrefs use Windows-style backslashes (`ASC\CR\CR260127.PDF`). The IIS
server accepts backslashes, `%5C`, and forward slashes interchangeably; we
normalise to forward-slash absolute URLs.

## Courts Covered

| `court` (CourtListener) | site_id | Display Name |
|--------------------------|---------|--------------|
| `ariz`                   | `ASC`   | Arizona Supreme Court |
| `arizctapp`              | `1CA`   | Arizona Court of Appeals, Division One |

`courts-db` represents both Court-of-Appeals divisions under the single
`arizctapp` ID. This scraper covers Division One only — Division Two routes
to a separate `publicaccess` CMS scraped by `arizona/appeals2_az_gov`.

## Page Types

Each court publishes a set of static "case type" pages, one HTML table per
type, plus three flat indices. Case types per court:

- `ariz`: CR, CV, HC, M, R, SB, WC (7)
- `arizctapp`: CC, CR, CV, HC, IC, JV, MH, SA, TX, UB (10)

Each case-type page has three sort variants; this scraper uses two:

| Variant | Sorted by | Used by |
|---------|-----------|---------|
| `stage_<SITE>_<TYPE>.htm` | Case Number ASC | `dockets_by_bulk` |
| `stage_<SITE>_<TYPE>_update.htm` | **Last Updated DESC** | `dockets_by_updated_date` |

The `_update` variant carries a hidden timestamp cell (`M/D/YYYY HH:MM:SS`)
and rows are newest-first, which enables the incremental cutoff early-stop.

Three index pages per court:

| iframe URL | Parser → record |
|-----------|-----------------|
| `000_<SITE>_LOWERCOURT_INDEX.HTM` | `LowerCourtIndexParser` → `AzAppLowerCourtCase` |
| `000_<SITE>_party_index.HTM` | `PartyIndexParser` → `AzAppPartyCase` |
| `000_<SITE>_ATTY_INDEX.HTM` | `AttorneyIndexParser` → `AzAppAttorneyCase` |

The Lower Court index is segmented by lower-court name (heading rows with
`<a name>` anchors); category-marker rows (pure-digit anchors `150`/`200`/
`500`) are skipped. The Attorney index name cells carry a `[<JURIS>-<NUM>]`
bracket (bar jurisdiction + optional number), split out from the name.

### Critical lifecycle constraint

The pages state: *"updated nightly and only reflects current and active
cases, as well as cases closed within the last 15 days."* Closed-case docket
PDFs are deleted after that window — verified 404s for several closed cases.
There is no archive directory. **Historical docket PDFs are not preserved**;
a nightly run with cutoff ≈ 16 days ago is the practical horizon.

## Docket Number Format

| Court | Display form | PDF basename | Path |
|-------|--------------|--------------|------|
| ariz | `CR-26-0127-PR` | `CR260127.PDF` | `ASC/CR/CR260127.PDF` |
| arizctapp | `1 CA-CR 26-0210` | `CR260210.PDF` | `1CA/CR/CR260210.PDF` |

The basename is `<TYPE><YY><NNNN>.PDF` (suffix and court prefix dropped), so
the same PDF can be referenced from multiple indices that print different
suffixes for the same serial.

## Scraper Architecture

### Entry points (§4)

All take `court_ids: set[str]`; unsupported ids are dropped, and a run with
no supported court fails loudly.

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_updated_date(court_ids, date_range)` | `DateRange` | Walk `_update` pages per court; emit rows whose Last Updated is in `[start, end]`, breaking past the older edge. |
| `dockets_by_bulk(court_ids)` | — | Walk every case-type page per court end-to-end. |
| `lower_court_cases_by_bulk(court_ids)` | — | Lower Court Index per court. |
| `party_cases_by_bulk(court_ids)` | — | Party Index per court. |
| `attorney_cases_by_bulk(court_ids)` | — | Attorney Index per court. |

### Step functions and priorities (§5)

All parse steps run at priority **2**; PDF archive requests are downloads at
priority **1** (auto-assigned by `archive=True`); `handle_pdf_archive` is
their continuation.

```
dockets_by_updated_date → parse_case_list_update (2) ─┐
dockets_by_bulk         → parse_case_list_full   (2) ─┤
lower_court_cases_by_bulk → parse_lower_court_index (2) ┤→ PDF archive (1)
party_cases_by_bulk     → parse_party_index      (2) ─┤    → handle_pdf_archive
attorney_cases_by_bulk  → parse_attorney_index   (2) ─┘
```

### Deduplication keys (§6)

`court` is part of the identifying args because a single run spans two
courts (so the keys are not redundant scraper-scope prefixes):

- `case_list_update:<court>:<case_type>` / `case_list_full:<court>:<case_type>`
- `lower_court_index:<court>` / `party_index:<court>` / `attorney_index:<court>`
- PDF archives: `<court>-<pdf_basename>` (no colons — used in filenames),
  which dedups the same PDF across all four sources and across courts.

### Data types

- `AzAppDocket` (→ CL `Docket`) + `AzAppDocument` (→ `RECAPDocument`, one per
  archived PDF, URL-deduplicated across entry points).
- `AzAppLowerCourtCase` (→ `OriginatingCourtInformation`), `AzAppPartyCase`
  (→ `Party`), `AzAppAttorneyCase` (→ `Attorney`).

Every record carries `court` so a single store holds rows from both courts
side-by-side.

## Out of Scope

- Released-opinion PDFs (separate `/Portals/0/OpinionFiles/...` path) — this
  scraper captures the active-list **docket sheet** PDFs only.
- Oral-argument calendars (published elsewhere, e.g.
  `azcourts.gov/scheduling/Supreme-Court`).
- Email notifications — no subscription feature on either portal.
