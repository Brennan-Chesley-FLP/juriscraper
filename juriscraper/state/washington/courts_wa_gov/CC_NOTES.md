# Washington Appellate Briefs (www.courts.wa.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Plain-HTTP, server-rendered HTML briefs index, organized by *scheduled
> hearing date*. HTML extraction lives in the `parsers/` package (§9,
> `BriefsPageParser`); the step keeps navigation (per-year fan-out,
> hearing-date window filter, PDF archive requests). `driver_requirements =
> []`. Model fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court`
> (not `court_id`), `date_*` naming.

## Site Overview

- **Base URL**: `https://www.courts.wa.gov/appellate_trial_courts/coaBriefs/`
- **Backend**: ColdFusion (`index.cfm?fa=coabriefs.briefsByHearingDate`),
  server-rendered HTML.
- **Requires Playwright**: No. The site does return a short error page to
  clients with no `User-Agent`, so the scraper sends a browser UA.

This is a separate data source from `acdocportal_courts_wa_gov` (per-case
document search) and `dw_courts_wa_gov` (case dockets) — it serves *briefs*
grouped by hearing date.

## Courts Covered

| Site division | CourtListener ID | Briefs `courtId` |
|---------------|------------------|------------------|
| Supreme Court | `wash` | `A08` |
| Court of Appeals, Division I | `washctappdiv1` | `A01` |
| Court of Appeals, Division II | `washctappdiv2` | `A02` |
| Court of Appeals, Division III | `washctappdiv3` | `A03` |

Each division has its own URL, so divisions are split into distinct CL ids
here even though CL lumps the CoA under `washctapp` for opinions.

## Search Capabilities

Paginated by year, one `courtId` per court. Earliest year served is 2006
(`MIN_YEAR`); Div III has no briefs before 2008 but still serves a clean
"No Court Briefs were found..." page for missing years, which the parser
detects and treats as empty.

## Page Structure / Parsing Quirk

The year page renders, per hearing date, an `<a name="aYYYYMMDD">` anchor,
then case `<li>` items (`"<docket> - <case name>"`, no links), then brief
`<li>` items (with `.pdf` `<a>` links). The HTML is mildly malformed —
`<a name>` anchors wrap block elements — so XPath sibling/ancestor relations
are unreliable; the cases/dates/briefs must be associated in **document
order**.

`BriefsPageParser` recovers document order from `td.mainPage`'s
`inner_html()` using a stdlib `HTMLParser` (NOT `._element` / raw lxml — §9).
It returns case groups `{hearing_date, docket, case_name, briefs:[{title,
url}]}`; the step resolves brief URLs against the page URL and applies the
hearing-date window.

## Scraper Architecture

### Entry point (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `briefs_by_hearing_date(court_ids, date_range)` | `set[str]`, `DateRange` | Briefs whose scheduled hearing date falls in `date_range`, for each requested court. Fans out one GET per (court, year). |

Record noun `briefs`; the searchable date the site exposes is the scheduled
hearing date, hence `*_by_hearing_date` (§4 swap rule).

### Steps & priorities (§5)

```
briefs_by_hearing_date → parse_briefs_page (2) → handle_brief_download (archive=1)
```

### Deduplication keys (§6)

- `briefs_page:<court>:<year>` — each year page GET.
- `<court>-<docket>-<hearing_date>-<pdf_basename>` — each archived brief
  PDF (colon-free; brief filenames are not globally unique, so the key folds
  in court/docket/date).

### Data types

- `WaBriefCase` (→ CL `Docket`) with nested `WaBrief` (→ `RECAPDocument`).
- `WaDownloadedBrief` (→ `RECAPDocument`) per archived PDF, joinable via
  `(court, docket_number, hearing_date, brief_url)`.
