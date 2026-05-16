# Arizona Appellate Courts (apps.azcourts.gov) Scraper Design

## Site Overview

- **Public landings**:
  - `https://www.azcourts.gov/appellatecourtcases/ASC/Cases` (Supreme Court)
  - `https://www.azcourts.gov/appellatecourtcases/COA1/Cases` (Court of
    Appeals, Division One)
- **Real data host**: `https://apps.azcourts.gov/aacc/appella/`
- **Requires Playwright**: No — server-rendered HTML, no bot protection.

The user-facing pages are thin DNN portals that embed the data backend in
`<iframe>`s. The iframe URLs are
`STAGE_<SITE>_MAIN.HTM` on `apps.azcourts.gov`. All scraping targets the
`apps.azcourts.gov` host directly — no session, no JS, no cookies.

The backend is an "Appella" / AppellaDockets product that publishes static
HTML files regenerated nightly. Each file has a
`<META http-equiv="refresh" content="600">` so a browser auto-reloads every
10 minutes. Tables use auto-generated `htmldwXXXX` CSS classes (the leading
hex changes between nightly builds), so XPath selectors must rely on
document structure (column order, anchor text, hidden cells) rather than
class names.

PDF hrefs use Windows-style backslashes (`ASC\CR\CR260127.PDF`,
`1CA\CR\CR260210.PDF`). The IIS server accepts the literal backslashes,
percent-encoded `%5C`, and forward slashes interchangeably (the whole
filesystem is case-insensitive too). We normalise to forward slashes when
building URLs.

## Courts Covered

| court_id (CourtListener) | site_id | Display Name |
|--------------------------|---------|--------------|
| `ariz`                   | `ASC`   | Arizona Supreme Court |
| `arizctapp`              | `1CA`   | Arizona Court of Appeals, Division One |

`courts-db` represents both Court-of-Appeals divisions under the single
`arizctapp` ID. This scraper covers Division One only — Division Two
(`/appellatecourtcases/COA2/Cases`) routes to a separate `publicaccess`
CMS at `https://apps.azcourts.gov/publicaccess/` and would need a
separate scraper.

## Search Capabilities

The site has no traditional search form. Each court publishes a
court-specific set of static "case type" pages, one HTML table per type.
Case types and case counts vary per court:

### `ariz` (Arizona Supreme Court) — 7 case types

| Code | Description |
|------|-------------|
| CR | Active Criminal cases |
| CV | Active Civil cases |
| HC | Active Habeas Corpus cases |
| M  | Active Miscellaneous Special Action cases |
| R  | Active Rule 28 Petition cases |
| SB | Active State Bar cases |
| WC | Active Water Case cases |

### `arizctapp` (CoA, Division One) — 10 case types

| Code | Description |
|------|-------------|
| CC | Active Corporation Commission cases |
| CR | Active Criminal cases |
| CV | Active Civil cases |
| HC | Active Habeas Corpus cases |
| IC | Active Industrial Commission cases |
| JV | Active Juvenile cases |
| MH | Active Mental Health cases |
| SA | Active Special Action cases |
| TX | Active Tax Appeal cases |
| UB | Active Unemployment Board cases |

Each case-type page also has three sort variants:

| Variant | Sorted by | Direction |
|---------|-----------|-----------|
| `stage_<SITE>_<TYPE>.htm` | Case Number | ascending |
| `stage_<SITE>_<TYPE>_caption.htm` | Caption | ascending |
| `stage_<SITE>_<TYPE>_update.htm` | **Last Updated** | **descending** |

The `_update` variant is what enables incremental scraping: each row carries
a hidden timestamp cell (`M/D/YYYY HH:MM:SS`) and rows are ordered newest
first, so we walk the table top-down and stop when we hit a row older than
the cutoff.

**Recommended approach**: walk all `_update` pages for the requested
court, early-stopping at the cutoff per page.

### Critical lifecycle constraint

The case-type pages explicitly say:

> This page is updated nightly and only reflects current and active cases,
> as well as cases closed within the last **15 days**.

Closed-case PDFs are deleted from the public filesystem after that window.
Verified for ASC: `CR-24-0064-PR` (decided 2025-12-12) and
`CR-24-0143-PR` (decided 2025-10-07) both 404 at every plausible path.
There is no archive directory. Implication: a nightly run with cutoff =
16 days ago is the practical horizon. Anything older has to come from
the Wayback Machine or a private backfill.

## Index Pages

Three additional flat indices are published per court, each as an
iframe-embedded HTML page on `apps.azcourts.gov`:

| Public URL | iframe URL |
|------------|-----------|
| `/appellatecourtcases/<COURT>/LowerCaseIndex` | `000_<SITE>_LOWERCOURT_INDEX.HTM` |
| `/appellatecourtcases/<COURT>/PartyIndex` | `000_<SITE>_party_index.HTM` |
| `/appellatecourtcases/<COURT>/AttorneyIndex` | `000_<SITE>_ATTY_INDEX.HTM` |

The Lower Court index is segmented by lower-court name. Each segment
begins with a `<TH>` row carrying the court name and an `<a name="...">`
anchor (e.g. `<a name="1 CA">` for Court of Appeals Division One,
`<a name="MAR">` for Maricopa County Superior Court). Following rows
belong to that segment until the next segment header.

ASC's Lower Court index also has *category-marker rows* whose anchor
names are pure digits — `150` ("Appellate Court"), `200` ("Superior
Court"), `500` ("Other Court, Board, or Commission"). These precede
the specific courts in their group; we skip them so that data rows
under e.g. "MARICOPA COUNTY SUPERIOR COURT" are not attributed to the
generic "Superior Court" parent. COA1's index has fewer category
markers but the rule is the same.

The Party and Attorney indices are segmented by first letter (anchors
`#A`, `#B`, …, `#0`). Letter sections are not data we need to track.

The Attorney index includes a bracket suffix on each name:

```html
<TD ...>ABNEY, DAVID <SMALL STYLE="COLOR:BROWN">[AZ-9001]</small></TD>
<TD ...>ALT, ROBERT <SMALL ...>[OH]</small></TD>
<TD ...>ANTHONY, DAVID <SMALL ...>[NV-7978]</small></TD>
```

The bracket holds a 2-letter jurisdiction code and an optional bar
number. We capture both. Cells without a number are typically out-of-state
counsel admitted pro hac vice (or AZ counsel whose number isn't recorded).

There is also a 5th cell on each attorney row containing a stale
`/court/0001/case/CV260051`-style link. **All such links return 404** —
the CMS they pointed to is decommissioned. We ignore these.

## Docket Number Format

| Court | Display form | PDF basename | Path |
|-------|--------------|--------------|------|
| ariz | `CR-26-0127-PR` | `CR260127.PDF` | `ASC/CR/CR260127.PDF` |
| arizctapp | `1 CA-CR 26-0210` | `CR260210.PDF` | `1CA/CR/CR260210.PDF` |

The basename is `<TYPE><YY><NNNN>.PDF` regardless of court (suffix and
court prefix dropped). Two-letter case types are catenated as-is
(e.g. `SB260030.PDF`).

Suffixes observed on the display form: `PR`, `AP`, `PC`, `T/AP`, `SA`,
`R`, `RS`, `M`, etc. The suffix is not part of the file path, so the
same PDF can be referenced from multiple indices that print different
suffixes for the same underlying serial.

State Bar (SB) anchors include a `<small> [Ending]</small>` status
badge inside the anchor text — we extract only the leading text node
so the badge doesn't end up in the docket number.

## Released Opinions / Closed-Case Docket PDFs

The opinion-search page at
`/opinions/Memorandum-Decisions/Search-Opinions-Memo-Decs?...` links
to *opinion* PDFs at `/Portals/0/OpinionFiles/Supreme/<year>/<file>.pdf`
— not to the docket sheet. The docket sheet PDF (the one this scraper
captures from the active list) is purged 15 days after the case closes.
Spot-checks of three closed cases (`CR-24-0064-PR`, `CR-24-0143-PR`,
`CR-24-0281-PR`) all 404 at every plausible docket-PDF location on
`apps.azcourts.gov`. **Historical docket PDFs are not preserved**;
nightly incremental scraping is the only way to capture them before
they expire.

## Data Available

### From case-type list rows

| Field | Source |
|-------|--------|
| `docket_number` | Cell 0 anchor's leading text node |
| `case_type` (`CR`, `CV`, …) | Carried in `accumulated_data` |
| `case_name` / short caption | Cell 1 |
| `last_updated` | Hidden cell — `M/D/YYYY HH:MM:SS\<COURT>\<TYPE>\<FILE>.PDF` (timestamp portion) |
| `pdf_url` | Cell 0 anchor href |

### From Lower Court Index rows

| Field | Source |
|-------|--------|
| `lower_court_name` | Section heading `<TH>` text |
| `lower_court_anchor` | Section heading anchor `name` attribute |
| `lower_court_case_number` | Cell 0 |
| `our_docket_number` | Cell 1 anchor's leading text node |
| `our_case_pdf_url` | Cell 1 anchor href |
| `case_title` | Cell 2 |

### From Party Index rows

| Field | Source |
|-------|--------|
| `party_name` | Cell 0 |
| `docket_number` | Cell 1 anchor's leading text node |
| `case_pdf_url` | Cell 1 anchor href |
| `case_title` | Cell 2 |

### From Attorney Index rows

| Field | Source |
|-------|--------|
| `attorney_name` | Cell 0 with bracket suffix stripped |
| `bar_number` | Digits inside the `[<JURIS>-<NUM>]` bracket; `None` if no digits |
| `bar_jurisdiction` | 2-letter code from the bracket |
| `docket_number` | Cell 1 anchor's leading text node |
| `case_pdf_url` | Cell 1 anchor href |
| `case_title` | Cell 2 |

## Bot Protection / Email Notifications / Oral Arguments

- **Bot protection**: none observed. The site sits behind Cloudflare for
  caching but issues no challenge.
- **Email notifications**: not available — no subscription feature on
  either court's portal.
- **Oral arguments calendar**: not on `apps.azcourts.gov`. Each court
  publishes its argument calendar elsewhere (e.g.
  `https://www.azcourts.gov/scheduling/Supreme-Court`); a separate
  scraper would be needed.

## Scraper Architecture

### Top-level data types

- `AzAppDocket` — one per active case row.
- `AzAppDocument` — one per archived PDF (URL-deduplicated across all
  entry points).
- `AzAppLowerCourtCase` — one per row in the Lower Court Index.
- `AzAppPartyCase` — one per row in the Party Index.
- `AzAppAttorneyCase` — one per row in the Attorney Index.

Every record carries a `court_id` field so a single store can hold rows
from both courts side-by-side.

### Entry points

All entries take a typed param model carrying `court_id` (and
`cutoff` on `active_updated_after`):

| Entry | Param | Purpose |
|-------|-------|---------|
| `active_updated_after` | `CourtCutoff(court_id, cutoff)` | Walk the `_update` pages for this court top-down; emit rows newer than `cutoff`. |
| `active_all` | `CourtParam(court_id)` | Walk every case-type page for this court end-to-end. |
| `lower_court_index` | `CourtParam(court_id)` | Fetch the Lower Court Index. |
| `party_index` | `CourtParam(court_id)` | Fetch the Party Index. |
| `attorney_index` | `CourtParam(court_id)` | Fetch the Attorney Index. |

Per-court URL dispatch is handled inside the scraper via a `COURTS` dict
that maps `court_id → {site_id, case_types, display_name}`. The two
helpers `_case_list_url(court_id, type, by_update)` and
`_index_url(court_id, kind)` are the only places site-id is referenced.

### Step functions

- `parse_case_list_update` — used by `active_updated_after`. Walks rows in
  order and short-circuits when `last_updated <= cutoff`. Yields
  `AzAppDocket` for each in-range row and an archive `Request` for the PDF.
- `parse_case_list_full` — used by `active_all`. Walks every row.
- `parse_lower_court_index` — tracks current section heading; emits one
  `AzAppLowerCourtCase` per row.
- `parse_party_index` — emits one `AzAppPartyCase` per row.
- `parse_attorney_index` — extracts attorney name + bar number +
  jurisdiction; emits one `AzAppAttorneyCase` per row.
- `handle_pdf_archive` — receives the archived PDF path and emits an
  `AzAppDocument`.

### Dedup

Archive requests use kent's default URL-based dedup. The same PDF URL
referenced from multiple sources (case-list, lower-court, party,
attorney) is fetched once. Because each PDF URL embeds its `site_id`
(`ASC/...` vs `1CA/...`), the URL alone is enough to keep
cross-court collisions from happening.
