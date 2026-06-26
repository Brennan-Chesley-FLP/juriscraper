# Rhode Island Judiciary Public Portal (publicportal.courts.ri.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Single court (`ri`, Supreme Court of Rhode Island). Tyler Odyssey Public
> Portal, reCAPTCHA-gated and DataDome-shielded — runs under Playwright
> (`JS_EVAL` + `CHROME_ALIKE` + `RCAP_HANDLER`). HTML extraction lives in
> the `parsers/` package (§9, `SearchResultsParser`); steps keep navigation
> (the GET that renders the form, the reCAPTCHA-solving `form.submit()`,
> absolutising each result row's case-detail URL). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `docket_number` (not `case_number`), `date_*` date naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: <https://publicportal.courts.ri.gov/PublicPortal/Home/Dashboard/29>
- **Vendor**: Tyler Technologies — *Odyssey Public Portal* (footer:
  "© Tyler Technologies, Inc. … Version: 2017.1.53.9"). Distinct from
  - Thomson Reuters C-Track / "TR Portal" (`juriscraper.state.common/tr/`)
  - Tyler MyCase (`indiana/mycase_courts_in_gov/`).
  The shared Tyler-Odyssey form layout (single "Smart Search" box +
  reCAPTCHA + advanced filters) is consistent across many state installs.
- **Backend**: ASP.NET MVC. The form posts URL-encoded values to
  `/PublicPortal/SmartSearch/SmartSearch/SmartSearch` and the server
  renders the results inline (no JSON API surfaced).
- **Requires Playwright**: **Yes** — two layers:
  1. **DataDome** bot protection at the edge — direct curl returns HTTP
     403 for *every* path under `/PublicPortal/`, any User-Agent. Plain
     httpx is blocked.
  2. **reCAPTCHA v2** (sitekey `6LfqmHkUAAAAAAKhHRHuxUy6LOMRZSG2LvSwWPO9`)
     on the search form — submission requires a `g-recaptcha-response`
     token.

  Driver requirements: `JS_EVAL`, `CHROME_ALIKE`, `RCAP_HANDLER`.
  `RCAP_HANDLER` solves the reCAPTCHA before the POST is dispatched.

## Courts Covered

Rhode Island has no intermediate appellate court; the Supreme Court is the
only court of last resort. The portal exposes ten "court location" options
in its dropdown — only one is appellate:

| Site `CourtLocation` value | Display Name                  | CourtListener ID |
|----------------------------|-------------------------------|------------------|
| `Supreme Court Search`     | Supreme Court of Rhode Island | `ri`             |

Other dropdown values cover trial courts (Superior, District, Family,
Workers' Comp, Traffic Tribunal) and are out of scope. The
`Supreme-ALC Search` value designates an administrative-law container that
does not map cleanly to a CourtListener appellate ID — left out of v1.

## Search Capabilities

The dashboard form posts to
`/PublicPortal/SmartSearch/SmartSearch/SmartSearch` with these fields:

| Field                                    | Purpose                            |
|------------------------------------------|------------------------------------|
| `caseCriteria.SearchCriteria`            | Single-input "Smart Search" box — record number or `Last, First Middle Suffix` |
| `caseCriteria.CourtLocation`             | Court dropdown (display string verbatim, e.g. `Supreme Court Search`) |
| `caseCriteria.SearchBy`                  | `SmartSearch` (default) |
| `caseCriteria.FileDateStart` / `FileDateEnd` | Date range filter (mm/dd/yyyy) — advanced |
| `Settings.CaptchaEnabled`                | `True` — preserved hidden field    |
| `g-recaptcha-response`                   | Filled by `RCAP_HANDLER` at submit |

Hidden form fields are preserved via `page.find_form().submit()` rather
than enumerated, so a Tyler rename of any `Settings.*` flag doesn't break
the submit. There is no JSON / REST endpoint; the backend renders the
results HTML directly in the form-POST response.

## Docket Number Formats

The form box is free-text and the result page is captcha-gated, so the
formats aren't directly observable. Historical RI Supreme Court forms:

- `YYYY-NNN-Appeal.` / `YYYY-NNN-A.` (e.g. `2018-298-Appeal.`)
- `YYYY-NNN-M.P.` (miscellaneous petitions)
- `YYYY-NNN-C.A.` (certified appeals)
- `SU-YYYY-NNNN-Appeal` and similar Tyler-internal forms.

The speculative entry passes the seeded number through verbatim and lets
the server resolve any reasonable variant.

## Data Available

**Status (2026-05-04): unverified.** All result and detail pages are behind
reCAPTCHA + DataDome and could not be reached during recon. The structure
below is the typical Tyler Odyssey Public Portal shape; the v1 parser is
written against that template (see Known Gaps).

### Search-results table (typical Tyler Odyssey shape)

| Field        | Type                                                       |
|--------------|------------------------------------------------------------|
| docket number| str — the public docket number (first cell, a link)        |
| style        | str — case caption                                         |
| file date    | `mm/dd/yyyy`                                               |
| case status  | str                                                        |
| case type    | str                                                        |
| detail link  | `/PublicPortal/Case/CaseDetail?caseId={encrypted-id}` (typical Tyler URL — verify post-deploy) |

### Case detail page (typical Tyler Odyssey shape; reserved for v2)

- Case header (number, style, type, court, status, filing date, judge).
- Parties + attorneys (name, role, address, attorney bar number).
- Events / "Register of Actions" (date, type, description, documents).
- Linked documents (PDFs).

## Out of Scope

- **Case-detail / register-of-actions parse** (`RIDocketEntry`, `RIParty`)
  — gated behind reCAPTCHA, not verifiable in v1 recon.
- **Date-range entry mode** (`FileDateStart`/`FileDateEnd`) — preferred
  long-term shape for incremental scraping; deferred until the result-table
  HTML is confirmed via a captcha-solving deploy.
- **Document downloads** — not implemented in v1.
- **Email notifications** — requires "My Account" sign-in.
- **Oral-argument calendar** — published as static PDFs on a separate site
  (`courts.ri.gov`); candidate for a future per-court-calendar scraper.

## Known Gaps (v1)

1. **Result-page parser is unverified.** `SearchResultsParser` follows the
   typical Tyler Odyssey result-table layout but was not observed against
   the live RI deploy because of the captcha gate. The XPath queries use
   `min_count=0` so a speculative miss (or a layout change) yields no rows
   rather than raising. The first post-deploy run should validate the
   selectors and tighten the count assertions.
2. **Case-detail follow-up is not wired.** v1 yields the lightweight
   `RIDocket` from the search-result row only.

These gaps are why this scraper ships as `IN_DEVELOPMENT`.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_number(docket_number)` | `SpeculativeRange` | Speculative single-case lookup at the Supreme Court. Single court (`ri`), so a plain `SpeculativeRange` with a fixed court id — no `court_ids` arg (a speculative entry is dispatched with only its speculative param; §4). |

### Step functions and priorities (§5)

```
entry → submit_search_form (3) → parse_search_results (2) → ParsedData
```

Priorities descend by depth so in-flight lookups finish before new ones
start. No downloads in v1, so nothing at priority 0–1.

### Deduplication keys (§6)

- `submit_search_form:<number>` — the GET that renders the search form.
- `parse_search_results:<number>` — the reCAPTCHA-solving form POST.

### Data types

- `RIDocket` (main, → CL `Docket`) — search-result fields (docket number,
  court, case name, filing date, status, type, case-detail URL).
- `RIDocketEntry` (→ CL `DocketEntry`) and `RIParty` (→ CL `Party`) —
  declared for forward compatibility; populated in v2.
