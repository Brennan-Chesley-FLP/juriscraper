# Hawaii eCourt Kōkua Appellate Scraper Design

## Site Overview

- **Base URL**: `http://jimspss1.courts.state.hi.us:8080/eCourt/ECC/`
- **Public landing**: `CaseSearch.iface` (auto-redirects to disclaimer on
  fresh sessions).
- **Framework**: JavaServer Faces 2.0 / IceFaces 4 (`*.iface` endpoints,
  `JSESSIONID` cookie + `ice.window` / `ice.view` view tokens, persistent
  `javax.faces.ViewState`).
- **Transport**: Server-rendered HTML form POSTs.
- **Requires Playwright**: **Yes** — every search submission is gated by
  invisible reCAPTCHA v2 (sitekey `6LcbZEkUAAAAAHMdU1qVQGmPdOI2g_70k1TJHK7v`).

## Courts Covered

The portal serves all Hawaii state courts. This scraper targets only the
two appellate courts.

| Site Court Code | Display Name                       | CourtListener ID |
|-----------------|------------------------------------|------------------|
| `SC`            | Supreme Court of Hawaiʻi           | `haw`            |
| `CA`            | Intermediate Court of Appeals      | `hawapp`         |

The Filing Date Search form exposes a `courtTypeSelect` with values
`SC` (Supreme Court) and `ICA` (Intermediate Court of Appeals); selecting
either narrows `courtSelect` to the single matching value (`SC` or `CA`)
and `locationSelect` to one or two locations (`SC`, `LL` for the SC Law
Library; `CA` for the ICA).

## Search Capabilities

Two search modes; both captcha-gated.

### Filing Date Search (`FilingDateSearch.iface`)

Form fields:

- `frm:j_idt22:courtTypeSelect` — `SC` | `ICA` (others not used by us)
- `frm:j_idt22:courtSelect` — `SC` | `CA`
- `frm:j_idt22:locationSelect` — same code as court (or `LL` for SC)
- `frm:beginDate` / `frm:endDate` — `DD-MMM-YYYY`
  (e.g. `01-APR-2026`); **60-day max range** per server-side validation
- `frm:caseType` — optional filter; per-court vocabulary discovered via
  IceFaces partial postback after `courtTypeSelect` change:
  - **SC types**: AD, AP, CQ, EC, FD, MF, OT, PR, PW, RQ, RU, WC
  - **ICA types**: AP, OT, ST
- Captcha token expected on the same POST (invisible reCAPTCHA v2;
  `frm:siteKey` is `6LcbZEkUAAAAAHMdU1qVQGmPdOI2g_70k1TJHK7v`).
- Hidden JSF state preserved by `page.find_form().submit(...)`:
  `frm`, `javax.faces.ViewState`, `ice.window`, `ice.view`,
  `icefacesCssUpdates`, `frm:displayReCaptcha`, `frm:siteKey`,
  the date partner fields (`frm:beginDate_cc`, `frm:beginDatesp`, etc.),
  and the form-bound flag `frm:searchButtonCaptcha=` (image submit).

### Case ID Search (`CaseSearch.iface`)

Form fields (all optional, but at least one required):

- `frm:caseId` — full docket ID, e.g. `SCAP-22-0000234`
- `frm:applicationNumber`, `frm:arrestNumber`, `frm:tctNumber`,
  `frm:obtsNumber`, `frm:SID` — non-appellate handles, unused here
- `frm:beginDate` / `frm:endDate` — optional filter
- Same captcha + JSF-state fields as Filing Date Search.

### Bulk strategy decision

The 60-day cap on Filing Date Search makes it the natural date-window entry
point. We **also** declare per-prefix speculative entries against
`CaseSearch.iface` so operators have an unattended-friendly path once a
captcha solver is wired up (the gating is per-submission, identical
between the two endpoints). Recommended deployment ordering:

1. Filing Date Search (`get_*_dockets_by_date`) — preferred when known.
2. Speculative case-ID search — fallback for fills.

## Docket Number Formats

Year-partitioned with court+type prefix, 2-digit year, 7-digit sequence:

```
SC{TT}-{YY}-{NNNNNNN}     e.g. SCAP-22-0000234
CA{TT}-{YY}-{NNNNNNN}     e.g. CAAP-23-0000123
```

Both courts reset their per-prefix sequence at the start of each calendar
year, so the speculative entries take a `YearlySpeculativeRange` (year +
sequence min) — same shape as Maryland.

Selected high-volume prefixes per court (the ones we ship `@entry` methods
for; the rest are documented above):

- **`SCAP`** — Supreme Court Appeal (transfer / cert grant)
- **`SCWC`** — Supreme Court Application for Writ of Certiorari
- **`SCPW`** — Supreme Court Petition for Writ
- **`CAAP`** — ICA Appeal

## Data Available

Reconnaissance completed search-form mapping but did **not** complete a
search submission (every attempt was gated by reCAPTCHA challenges that
are not auto-solvable today — see "Bot Protection / Known Gaps").
Field lists below are **derived from the form schema and standard JSF
court-portal conventions**, not from a parsed result page.

### Search Result Row (Filing Date Search)

Standard JSF/IceFaces result table (`table.iceDatTbl`). Expected columns
based on the form's index fields:

- Case ID — the docket number, also the link to `CaseSearchView.iface?caseId=…`
- Caption / Case Title
- Filing Date
- Case Type
- Court / Location

### Case Detail (per case)

The eCourt Kōkua portal is known (from sibling court systems built on the
same JIMS / Tyler IceFaces stack and from public PDF copies of opinions
that cite docket layouts) to render a single case detail page split into
sub-sections. We model the conventional set:

- **Case Summary**: caption, case type, filing date, status,
  panel / division
- **Register of Actions / Docket Entries**: date, description, doc link
- **Parties**: name, role, attorney
- **Documents**: opinions, briefs (where publicly viewable / purchasable
  via Subscriptions.iface)

The actual XPaths are documented as `# TODO(empirical)` in the scraper
because we could not validate them this pass.

## Email Notifications

Not directly available on the appellate search pages. The site has a
`Subscriptions.iface` link that handles purchase of documents and may
also handle notifications, but it is paywall-adjacent and not in scope
for v1.

## Oral Arguments Calendar

`CourtHearingCaseIdSearch.iface` exists in the top nav but is a **per-case
upcoming-hearing search** (input: a case ID, output: that case's
hearings). It is not a per-court calendar listing, so the scraper does
not declare an `oral_arguments` data type.

The Hawaii Judiciary publishes appellate oral-argument calendars on the
public courts.state.hi.us site (separate from JIMS / eCourt Kōkua); a
separate scraper targeting that site would be the right home for an
oral-arguments data type.

## Bot Protection Notes

- **Invisible reCAPTCHA v2 on every submission.** The disclaimer
  (`ECCDisclaimer.iface`) accept button and **every** search button (both
  `CaseSearch.iface` and `FilingDateSearch.iface`) trigger
  `executeCaptcha()` → `grecaptcha.execute()` before the JSF postback.
  The hidden `frm:displayReCaptcha=true` field signals this server-side.
- **Session pinning**: `JSESSIONID` cookie is required for all `*.iface`
  endpoints; first request to `/eCourt/` issues one and 302s to
  `ECCDisclaimer.iface;jsessionid=…`. The disclaimer must be accepted
  before any search page renders its form — otherwise the search
  endpoints 302 back through `/eCourt/`.
- **JSF view state**: every form ships `javax.faces.ViewState` plus
  `ice.window` / `ice.view` view tokens that change per page render.
  `page.find_form().submit(...)` preserves all hidden fields, so we never
  enumerate them by hand.

## Known Gaps

**Captcha gap (blocking)**. As of 2026-05-06, kent's
`DriverRequirement.RCAP_HANDLER` (`kent/driver/interstitials.py`)
implements only **visible reCAPTCHA v2** — it locates `div.g-recaptcha`,
clicks `#recaptcha-anchor`, and solves the audio challenge. Hawaii's
disclaimer and search forms use **invisible** reCAPTCHA v2
(`data-size="invisible"`) which has no checkbox to click and is invoked
via JS (`grecaptcha.execute(widgetId)`); the visible-only handler will
time out waiting for an anchor that never renders.

This scraper ships `status=IN_DEVELOPMENT` and declares
`RCAP_HANDLER` in `driver_requirements` to signal intent. The scraper
will become operational once kent gains either:

1. An invisible-reCAPTCHA handler that intercepts `grecaptcha.execute()`
   and routes the resulting token through a solver service (2captcha /
   anticaptcha), or
2. A more general "solve the captcha service-side, inject token" feature
   surfacing as a new `DriverRequirement` value.

The structure here (entry points, form-submit chain, parse skeleton) is
intended to be wire-compatible — only the captcha handler swap should be
needed.

**Search-result and case-detail layouts are unverified**. Reconnaissance
mapped the form schemas but did not capture a result page or case detail
because we could not get past the captcha challenge unattended. Result
parsers are written from JSF/IceFaces conventions and marked
`# TODO(empirical)`; first operational run should validate XPaths and
update accordingly.

## Scraper Architecture

### Entry Points

- `get_supreme_court_dockets_by_date(date_range: DateRange)` — Filing
  Date Search, `courtTypeSelect=SC`. Driver chunks the requested window
  into 60-day max sub-ranges before calling.
- `get_ica_dockets_by_date(date_range: DateRange)` — same, with
  `courtTypeSelect=ICA`.
- Speculative case-ID searches (one `@entry` per high-volume prefix):
  - `fetch_scap_docket(case_id: YearlySpeculativeRange)` — `SCAP-YY-NNNNNNN`
  - `fetch_scwc_docket(case_id: YearlySpeculativeRange)` — `SCWC-YY-NNNNNNN`
  - `fetch_scpw_docket(case_id: YearlySpeculativeRange)` — `SCPW-YY-NNNNNNN`
  - `fetch_caap_docket(case_id: YearlySpeculativeRange)` — `CAAP-YY-NNNNNNN`

Additional prefixes (SCAD, SCEC, SCFD, SCMF, SCOT, SCPR, SCCQ, SCRQ, SCRU,
CAOT, CAST) are deliberately not declared in v1 — operators rarely need
them, and adding more `@entry` methods is mechanical once one is proven.

### Step Functions

```
entry (date)        → fill_date_search_form    → parse_search_results
                                                  → parse_case_detail (per result)

entry (speculative) → fill_caseid_search_form  → parse_search_results
                                                  → parse_case_detail (single result)
```

Both flows funnel into the same `parse_search_results` and
`parse_case_detail` continuations; per-mode context (court ID, requested
docket ID, etc.) rides in `accumulated_data`.

### Soft-404 detection

Speculative case-ID misses surface as a "no records found" message in the
result panel rather than an HTTP error (JSF re-renders the form view).
`fails_successfully` will check for the absence of the result table or
the presence of the no-records sentinel. **TODO(empirical)** to
substitute the exact sentinel string once a real run is possible.

### Models

- `HiAppDocket` — top-level case
- `HiAppDocketEntry` — register of actions row
- `HiAppParty` / `HiAppAttorney`
- `HiAppDocument` — opinions / briefs (link out to viewer; the actual
  PDF retrieval is paywalled via Subscriptions.iface, so we record the
  metadata only)
