# Washington DW Courts (dw.courts.wa.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> JS-rendered case-search portal behind a reCAPTCHA — requires Playwright
> (`JS_EVAL` + `CHROME_ALIKE` + `RCAP_HANDLER`). HTML extraction lives in the
> `parsers/` package (§9, `SearchResultsParser`, `CaseDetailDomParser`); steps
> keep navigation (form submit/reCAPTCHA, single case-link follow, inline-JS
> docket-array parse off `response.text`). Multi-court speculative: one
> `dockets_by_number` entry whose `DwCourtRange` carries the `court_id` and
> translates it to the DW court code (§4). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `docket_number` (not `case_number`), `date_filed` (not `event_date`).

## Site Overview

- **Base URL**: `https://dw.courts.wa.gov/`
- **Backend**: ColdFusion case search; Material Design Components search form;
  client-side Tabulator table for docket entries; reCAPTCHA before each
  search.
- **Requires Playwright**: Yes — JS rendering + reCAPTCHA solving.

## Courts Covered

| Site | CourtListener ID | DW `CRT_ITL_NU` |
|------|------------------|-----------------|
| Supreme Court | `wash` | `A08` |
| Court of Appeals, Division I | `washctappdiv1` | `A01` |
| Court of Appeals, Division II | `washctappdiv2` | `A02` |
| Court of Appeals, Division III | `washctappdiv3` | `A03` |

## Search / Page Structure

The "Appellate Courts → Search by case number" form posts
`courtType=C`, `searchType=2`, `CRT_ITL_NU_appellate=<code>`,
`caseNumber=<n>`. Results render one `.dw-search-result` card per
participant (all sharing one case-detail link with `casekey`/`courtname`
query params). The case-detail page embeds docket rows as an inline JS
`data = [ { eventDate, eventDescription, action }, ... ]` array.

`SearchResultsParser` extracts participants + the case-link metadata;
`CaseDetailDomParser` is the DOM fallback for the docket table when the
inline JS array is absent. The primary docket parse (regex on
`response.text`) stays in the step because it reads raw page text, not the
`PageElement` tree.

## Scraper Architecture

### Entry point (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_number(docket_number)` | `DwCourtRange` | Speculative case-number probe; `docket_number.court_id` selects the court. Seed once per court. |

This is multi-court speculative, so the entry takes ONLY the speculative
`DwCourtRange` (no `court_ids` arg); the court rides on the param (§4).
`DwCourtRange.search_key()` maps the CL court id → DW court code.

### Steps & priorities (§5)

```
dockets_by_number → fill_search_form (4) → parse_search_results (3) → parse_case_detail (2)
```

Descending by depth so in-flight cases finish before new searches start. No
downloads (text dockets, no PDFs), so nothing at priority 0–1.

### Deduplication keys (§6)

- `search_page:<court>:<case_number>` — the initial search-page GET.
- `case_detail:<case_key>` — the case-detail follow (case_key is the
  DW-internal stable key).

### Data types

- `DWWADocket` (→ CL `Docket`) with nested `DWWAParticipant` (→ `Party` /
  `PartyType`) and `DWWADocketEntry` (→ `DocketEntry`).

No document downloads are exposed on the case-detail page.
