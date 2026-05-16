# Rhode Island Judiciary Public Portal Scraper Design

Scraper for the Supreme Court of Rhode Island, served via the
[Rhode Island Judiciary Public Portal](https://publicportal.courts.ri.gov/PublicPortal/Home/Dashboard/29).

## Site Overview

- **Base URL**: <https://publicportal.courts.ri.gov/PublicPortal/Home/Dashboard/29>
- **Vendor**: Tyler Technologies — *Odyssey Public Portal* (footer:
  "© Tyler Technologies, Inc. … Version: 2017.1.53.9"). This is a
  different product from
  - Thomson Reuters C-Track / "TR Portal" (Oregon, Alabama — see
    `juriscraper/sd/state/common/tr/`)
  - Tyler MyCase (Indiana, see
    `indiana/mycase_courts_in_gov/`).
  The shared common Tyler-Odyssey form layout (single "Smart Search" box
  + reCAPTCHA + advanced filters) is consistent across many other state
  installations of this product.
- **Backend**: ASP.NET MVC. The form posts URL-encoded values to
  `/PublicPortal/SmartSearch/SmartSearch/SmartSearch` and the server
  renders the results inline (no JSON API surfaced).
- **Requires Playwright**: **Yes** — two layers:
  1. **DataDome** bot protection at the edge — direct curl returns
     HTTP 403 for *every* path tested under `/PublicPortal/`, regardless
     of User-Agent. Plain httpx is blocked.
  2. **reCAPTCHA v2** (sitekey
     `6LfqmHkUAAAAAAKhHRHuxUy6LOMRZSG2LvSwWPO9`) on the search form
     itself — submission requires a `g-recaptcha-response` token.

  Driver requirements: `JS_EVAL`, `CHROME_ALIKE`, `RCAP_HANDLER`. The
  `RCAP_HANDLER` driver requirement causes the framework to solve the
  reCAPTCHA before the POST is dispatched (same pattern as
  `washington/dw_courts_wa_gov`).

## Courts Covered

Rhode Island has no intermediate appellate court; the Supreme Court is
the only court of last resort. The portal exposes ten "court location"
options in its dropdown — only one is appellate:

| Site `CourtLocation` value     | Display Name                       | CourtListener ID |
|--------------------------------|------------------------------------|------------------|
| `Supreme Court Search`         | Supreme Court of Rhode Island      | `ri`             |

Other dropdown values cover trial courts (Superior, District, Family,
Workers' Comp, Traffic Tribunal) and are out of scope.

The `Supreme-ALC Search` value also appears in the dropdown but
designates an administrative-law container that does not map cleanly to
a CourtListener appellate ID — left out of v1.

## Search Capabilities

The dashboard form (`#smartSearchForm`) posts to
`/PublicPortal/SmartSearch/SmartSearch/SmartSearch` with these fields:

| Field                                    | Purpose                            |
|------------------------------------------|------------------------------------|
| `caseCriteria.SearchCriteria`            | Single-input "Smart Search" box — accepts a record number or `Last, First Middle Suffix` |
| `caseCriteria.CourtLocation`             | Court dropdown (sent as the display string verbatim, e.g. `Supreme Court Search`) |
| `caseCriteria.SearchBy`                  | `SmartSearch` (default; alternatives: `CaseSearch`, `PartySearch`) |
| `caseCriteria.SearchCases`               | `true`                             |
| `caseCriteria.SearchWarrants`            | `false`                            |
| `caseCriteria.SearchByPartyName`         | `true` (party-name search enabled) |
| `caseCriteria.SearchByNickName` / `…ByBusinessName` / `…UseSoundex` | `false` (defaults) |
| `caseCriteria.AdvancedSearchOptionsOpen` | `true` to enable filter fields below |
| `caseCriteria.NameLast` / `NameFirst` / `NameMiddle` / `NameSuffix` | Party name fields |
| `caseCriteria.CaseType` / `CaseStatus` / `JudicialOfficer` | Filter selectors |
| `caseCriteria.FileDateStart`             | Date range filter (mm/dd/yyyy)     |
| `caseCriteria.FileDateEnd`               | Date range filter (mm/dd/yyyy)     |
| `Settings.CaptchaEnabled`                | `True` — preserved hidden field    |
| `g-recaptcha-response`                   | Filled by `RCAP_HANDLER` at submit |

There is no JSON / REST endpoint exposed; the SmartSearch backend
renders a server-side HTML results page directly in the response to the
form POST.

**Recommended approach**: speculative entry by case number, one
`@entry` for the Supreme Court. The operator seeds the speculative
range; the search box accepts a free-text docket number (or fragment
that the server resolves to the canonical case).

A date-range mode is available via `FileDateStart`/`FileDateEnd` on
"Advanced" filters, and would be the preferred long-term entry shape
for incremental scraping. Listing-by-date is left for v2 once the
result-page HTML structure has been verified through a captcha-solving
deploy.

## Docket Number Formats

Not directly observable from the public dashboard — the form box is
free-text and the result page is captcha-gated. Historically the
Rhode Island Supreme Court has used several formats:

- `YYYY-NNN-Appeal.` / `YYYY-NNN-A.` (e.g. `2018-298-Appeal.`)
- `YYYY-NNN-M.P.` for miscellaneous petitions
- `YYYY-NNN-C.A.` for certified appeals
- `SU-YYYY-NNNN-Appeal` and similar Tyler-internal formats are also
  expected since Tyler Odyssey retrofits its own case-number scheme.

The scraper accepts the seed-driven case number verbatim and lets the
server resolve any reasonable variant.

## Data Available

**Status (2026-05-04): unverified.** All result and detail pages are
behind reCAPTCHA + DataDome and could not be reached during recon. The
structure documented here is the typical Tyler Odyssey Public Portal
shape and the v1 parsers are written against that template.

### Search-results table (typical Tyler Odyssey shape)

| Field        | Type                                                       |
|--------------|------------------------------------------------------------|
| `CaseNumber` | str — the public docket number                             |
| `Style`      | str — case caption                                         |
| `Court`      | str — court display name                                   |
| `FileDate`   | `mm/dd/yyyy`                                               |
| `CaseStatus` | str                                                        |
| `CaseType`   | str                                                        |
| Detail link  | `/PublicPortal/Case/CaseDetail?caseId={encrypted-id}` (typical Tyler URL — to be verified post-deploy) |

### Case detail page (typical Tyler Odyssey shape)

- Case header (number, style, type, court, status, filing date, judge).
- Parties + attorneys (name, role, address, attorney bar number).
- Events / "Register of Actions" (date, type, description, documents).
- Linked documents (PDFs).

The parsers in `scraper.py` are skeletons that will be filled in once
the captcha-solving deploy returns a real results page.

## Email Notifications

Tyler Odyssey Public Portal supports per-case email subscription, but
this requires authentication ("My Account" sign-in). Out of scope for
v1.

## Oral Arguments Calendar

Not exposed on this portal. The Rhode Island Judiciary publishes
oral-argument schedules as static PDF calendars on a separate site
(`courts.ri.gov`) — out of scope for this scraper, candidate for a
future per-court-calendar scraper.

## Bot Protection Notes

- **DataDome** at the edge — every `/PublicPortal/*` path returns HTTP
  403 to plain curl, even with a Chrome User-Agent. The Playwright
  driver gets through because DataDome's checks pass for a real
  browser session with JS evaluation enabled.
- **reCAPTCHA v2** — invoked at form submit. Sitekey
  `6LfqmHkUAAAAAAKhHRHuxUy6LOMRZSG2LvSwWPO9`. `RCAP_HANDLER` solves it
  before the POST is dispatched.
- **Session timeout** — the portal pops a "I'm still here" prompt
  (`#timeoutContinueBtn`) after a few minutes idle. Each scraper run
  starts a fresh dashboard fetch, so this is not a concern in practice.
- **Hidden form fields** are preserved via `page.find_form().submit()`
  rather than enumerated — this avoids drift if Tyler renames any of
  the `Settings.*` flags.

## Known Gaps (v1)

1. **Result-page parser is unverified.** The XPaths in
   `parse_search_results` follow the typical Tyler Odyssey result-table
   layout but were not observed against the live RI deploy because of
   the captcha gate. First post-deploy run should validate, and any
   adjustments be made then.
2. **Case-detail parser is a placeholder.** Same caveat — fields and
   selectors mirror the Tyler Odyssey defaults but need a live capture
   to lock down. v1 yields the lightweight `RIDocket` record from the
   search-result row only; the case-detail follow-up Request is wired
   up but its parser intentionally yields nothing until verified.
3. **Date-range entry mode** (`get_dockets_by_date`) is not implemented
   in v1. The form fields are documented above so it can be added once
   the result-table shape is confirmed.
4. **Document downloads** are not implemented in v1.

These gaps are why this scraper ships as `IN_DEVELOPMENT`.

## Scraper Architecture

### Entry Points

| Entry                                       | Param              | Purpose                                            |
|---------------------------------------------|--------------------|----------------------------------------------------|
| `fetch_supreme_docket(rid: SpeculativeRange)` | speculative number | Speculative single-case lookup at the Supreme Court |

### Step Functions

```
entry → load_search_page          (GET /PublicPortal/Home/Dashboard/29)
       ↓
       submit_search_form         (POST /PublicPortal/SmartSearch/SmartSearch/SmartSearch
                                    via page.find_form().submit() so RCAP_HANDLER
                                    solves the reCAPTCHA before POST)
       ↓
       parse_search_results       (extract case rows; emit lightweight RIDocket
                                    plus a request for the case-detail page)
       ↓
       parse_case_detail          (placeholder — yields nothing in v1)
```

### Models

- `RIDocket` — the main per-case record. v1 carries the search-result
  fields (case number, court id, case name, filing date, status,
  case-detail URL). Nested entries / parties stay empty until the
  detail parser is filled in.
- `RIDocketEntry` — declared for forward compatibility; populated in v2.
