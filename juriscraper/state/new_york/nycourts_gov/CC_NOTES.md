# New York Court of Appeals — Court-PASS (courtpass.nycourts.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md). This
> is the **reference scraper** the standards doc points to for flow/parsers.
> Single court (`ny`, NY Court of Appeals). The site is behind a Cloudflare
> managed challenge and is an ASP.NET WebForms app with ViewState-driven
> postback navigation, so it runs under Playwright
> (`driver_requirements = [JS_EVAL, FF_ALIKE, STRICTLY_SERIAL, CFCAP_HANDLER]`).
> HTML extraction lives in the `parsers/` package (§9); the steps keep the
> navigation concerns (form fills, postbacks, pagination, file downloads).
> Model fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not
> `court_id`), `date_*` date naming, `CleanString`/`HarmonizedCaseName`
> cleaning from `juriscraper.state.common_models`.

## Site Overview

- **Base URL**: `https://courtpass.nycourts.gov`
- **Backend**: ASP.NET WebForms (ViewState postbacks), Cloudflare edge.
- **Requires Playwright**: Yes — Cloudflare managed challenge + JS-driven
  postback navigation. `STRICTLY_SERIAL` because each interaction depends on
  the prior page's ViewState.

Every flow starts at `Docket.aspx`. Two pages carry the data: the
docket-detail span (`cphMain_lbDetails`) gives the caption, argument date,
FILINGS table, and ATTORNEY DETAILS; the filing-detail span
(`cphMain_lbDetails2`, loaded via the hidden `bttnDetails` postback) gives the
decision date, issues, opinion author, official citation, and the `gvFiles`
file list. Docket-detail fields ride forward in
`accumulated_data["deferred_docket"]` so one merged `NYCourtPassDocket` is
emitted only after both pages are seen.

## Courts Covered

| Site name | CourtListener ID |
|-----------|------------------|
| New York Court of Appeals | `ny` |

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Single-record direct lookup by APL/CTQ/JCR number (e.g. `APL-2024-00177`). |
| `dockets_by_bulk(court_ids, argument_date, decision_date)` | `set[str]`, `DateRange`, `DateRange` | The site only exposes the whole undecided-docket set (no server-side date search). Walks the full result grid; the optional `argument_date` / `decision_date` windows are applied **client-side** as the chain descends — hence the `*_by_bulk` name (§4 "Bulk + client-side filtering"). |

The `argument_date` filter is enforced in `parse_docket_results` (date is in
the grid); the `decision_date` filter is enforced in
`parse_docket_filing_detail` because the decision date is only on the
filing-detail page. Filter values travel via `accumulated_data`, never
re-read from params.

### Step functions and priorities (§5)

```
dockets_by_bulk     → fill_docket_search (6) → parse_docket_results (5)
                        ├→ (per row) parse_docket_detail (4)
                        │       → parse_docket_filing_detail (3) → ParsedData + downloads (0)
                        └→ (pagination) parse_docket_results (5)

docket_by_number    → parse_docket_page → parse_docket_number_results
                        → parse_docket_detail_for_entry
                        → parse_filing_detail_from_docket → ParsedData + downloads
```

Enumeration priorities descend by depth (6 → 5 → 4 → 3) so in-flight cases
finish before new ones start. File downloads use `priority=0` / `archive=True`.

### Parsers (§9)

- `DocketResultsParser` — one record per `gvResults` grid row
  (`case_short_name`, `argument_date`, `aria_case_info`, `search_row`).
- `DocketDetailParser` — caption, argument date, FILINGS (docket_entries),
  ATTORNEY DETAILS (attorneys) from `cphMain_lbDetails`.
- `FilingDetailParser` — decision date, opinion_by, official_citation,
  issues, `no_files_for_case`, and `gvFiles` file rows from
  `cphMain_lbDetails2`.

`_common.py` holds `_parse_date_mdy`, `repair_pdffont_leakage` (strips the
unclosed `<style pdffontname>` markers Court-PASS emits, which otherwise
swallow the file table), and `page_from_text` (lets the filing-detail steps
repair the raw `text` before handing a clean `PageElement` to the parser).

### Deduplication keys (§6)

`<continuation-or-record>:<args>` format, no court-id prefix:
`parse_docket_page:<dn>`, `fill_docket_search:<arg>:<dec>`,
`docket_detail:<page>:<row>`, `docket_filing_detail:<dn>:<page>-<row>`,
`docket_number_results:<dn>`, `docket_detail_for_entry:<dn>`,
`filing_detail_from_docket:<dn>`, `parse_docket_results:<page>`. File
downloads use a colon-free sha1 of the case/file identifiers.

### Data types

`NYCourtPassDocket` (main, → CL `Docket` + `NYCoADocketMetadata`) with nested
`NYCourtPassDocketEntry` (→ `DocketEntry`), `NYCourtPassAttorney` (→
`Attorney`/`Role`), and `NYCourtPassFile` (→ `RECAPDocument`). File binaries
are emitted separately via `handle_file_download` and joined back by
`docket_number`.
