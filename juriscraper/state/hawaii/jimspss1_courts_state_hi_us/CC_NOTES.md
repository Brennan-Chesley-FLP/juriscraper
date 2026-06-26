# Hawaiʻi eCourt Kōkua (jimspss1.courts.state.hi.us) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two appellate courts (`haw`, `hawapp`) on the Hawaiʻi Judiciary's JSF 2.0 /
> IceFaces 4 portal. **Requires Playwright** — every search submission is
> gated by invisible reCAPTCHA v2. Ships `status=IN_DEVELOPMENT` because
> kent's `RCAP_HANDLER` solves only the *visible* checkbox variant today (see
> Known Gaps). HTML extraction lives in the `parsers/` package (§9,
> `CaseDetailParser`); steps keep navigation (disclaimer acceptance, the
> search-form submit chain, the per-case fan-out). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `docket_number` (not `case_number`), `date_*` date naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `http://jimspss1.courts.state.hi.us:8080/eCourt/ECC/`
- **Public landing**: `CaseSearch.iface` (redirects to the disclaimer on
  fresh sessions).
- **Framework**: JavaServer Faces 2.0 / IceFaces 4 (`*.iface` endpoints,
  `JSESSIONID` cookie + `ice.window` / `ice.view` view tokens, persistent
  `javax.faces.ViewState`).
- **Transport**: server-rendered HTML form POSTs.
- **Requires Playwright**: **Yes** — every search submission is gated by
  invisible reCAPTCHA v2 (sitekey `6LcbZEkUAAAAAHMdU1qVQGmPdOI2g_70k1TJHK7v`).

## Courts Covered

| Site court code | Display name | CourtListener ID |
|-----------------|--------------|------------------|
| `SC` (type `SC`)  | Supreme Court of Hawaiʻi          | `haw`    |
| `CA` (type `ICA`) | Intermediate Court of Appeals     | `hawapp` |

The portal serves all Hawaiʻi state courts; this scraper targets only the two
appellate courts. The Filing Date Search `courtTypeSelect` exposes `SC` and
`ICA`; selecting either narrows `courtSelect` (`SC`/`CA`) and `locationSelect`.

## Search Capabilities

Two search modes; **both captcha-gated**.

### Filing Date Search (`FilingDateSearch.iface`)

- `frm:j_idt22:courtTypeSelect` — `SC` | `ICA`
- `frm:j_idt22:courtSelect` — `SC` | `CA`
- `frm:j_idt22:locationSelect` — same code as court (or `LL` for SC Law Library)
- `frm:beginDate` / `frm:endDate` — `DD-MMM-YYYY` (e.g. `01-APR-2026`);
  **60-day max range** per server-side validation.
- `frm:caseType` — optional per-court filter (SC: AD/AP/CQ/EC/FD/MF/OT/PR/PW/
  RQ/RU/WC; ICA: AP/OT/ST). Left blank.
- Invisible reCAPTCHA token expected on the same POST; `frm:searchButtonCaptcha=`
  is the image-submit flag. All hidden JSF state (`javax.faces.ViewState`,
  `ice.window`, `ice.view`, date partner fields) is preserved by
  `page.find_form().submit(...)`.

### Case ID Search (`CaseSearch.iface`)

- `frm:caseId` — full docket number, e.g. `SCAP-22-0000234`.
- Same captcha + JSF-state fields as Filing Date Search.

## Docket Number Format

Year-partitioned, court+type prefix, 2-digit year, 7-digit sequence:

```
SC{TT}-{YY}-{NNNNNNN}     e.g. SCAP-22-0000234
CA{TT}-{YY}-{NNNNNNN}     e.g. CAAP-23-0000123
```

Each (court, prefix) resets its sequence per calendar year, so the
speculative entry uses `HiCaseRange` (court + type code + year + sequence
`min`).

## Data Available

> Reconnaissance mapped the search-form schemas but could **not** capture a
> result page or a case-detail page — every search submission was gated by
> reCAPTCHA challenges that are not auto-solvable today (see Known Gaps).
> Result/detail XPaths are derived from JSF/IceFaces conventions and marked
> `# TODO(empirical)` in `parsers/case_detail.py` and the result step.

`CaseDetailParser` extracts (off the case-detail HTML):

- **Case summary** (label→value `<td>` pairs): `case_name`, `case_status`,
  `date_filed`, `date_terminated`, `panel_str`, `appeal_from_str`
  (trial-court case number), `assigned_to_str` (trial-court judge).
- **Register of actions** (`table.iceDatTbl`): `HiAppDocketEntry` rows
  (`date_filed`, `description`, `notes`).
- **Parties**: `HiAppParty` (name, role) + nested `HiAppAttorney`.
- **Documents**: `HiAppDocument` (opinions/briefs); metadata only — the
  actual file is paywalled behind `Subscriptions.iface`. Relative hrefs are
  resolved against the page URL by the step.

The step stamps `docket_number`, `court`, `case_type_code`, `case_type`,
`source_url`, `source_entry_point` onto the parser's `raw_data`.

## Out of Scope

- `Subscriptions.iface` (paywalled document purchase / notifications).
- `CourtHearingCaseIdSearch.iface` is a per-case upcoming-hearing lookup, not
  a per-court oral-argument calendar — no `oral_arguments` data type. The
  public courts.state.hi.us appellate OA calendars live on a different site
  and belong in a separate scraper.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_filing_date(court_ids, date_range)` | `set[str]`, `DateRange` | Filing Date Search; one search per requested court per <=60-day window. |
| `dockets_by_number(docket_number)` | `HiCaseRange` | Speculative Case ID Search; range carries court + case-type prefix + year. |

`dockets_by_number` is speculative, so per §4 it takes **only** its
speculative param — the court/prefix/year ride inside `HiCaseRange` (a
`CourtRange` subclass). Seed one range per (court, prefix, year).

### Step functions and priorities (§5)

```
entry (date)        → ensure_disclaimer (6) → navigate_to_search (5)
                      → fill_date_search_form (4) → parse_search_results (3)
                      → parse_case_detail (2)   [per result]

entry (speculative) → ensure_disclaimer (6) → navigate_to_search (5)
                      → fill_caseid_search_form (4) → parse_search_results (3)
                      → parse_case_detail (2)
```

Priorities descend by depth so in-flight cases finish before new searches
start. No downloads (paywalled documents recorded as metadata only), so
nothing at priority 0–1.

### Deduplication keys (§6)

- Disclaimer / navigate / search-submit GETs+POSTs use
  `SkipDeduplicationCheck()` — they are session/ViewState warmups and
  non-idempotent postbacks.
- `dockets_by_number:<docket_number>` — the speculative seed.
- `parse_case_detail:<docket_number>` — each case-detail fetch (dedups a case
  surfaced by both a date search and a number search).

### Soft-404 detection

A Case ID Search miss re-renders the search view with a "no records found"
message instead of an HTTP error. `actually_successful()` returns `False`
when that sentinel is present, which the driver treats as a speculation miss.
**TODO(empirical)**: confirm the exact sentinel once a real run is possible.

### Data types

`HiAppDocket` (main, → CL `Docket`) with nested `HiAppDocketEntry`,
`HiAppParty` (+ `HiAppAttorney`), and `HiAppDocument`.

## Known Gaps

**Captcha gap (blocking).** As of 2026-05-06, kent's `RCAP_HANDLER`
implements only **visible** reCAPTCHA v2 (locates `div.g-recaptcha`, clicks
`#recaptcha-anchor`, solves the audio challenge). Hawaiʻi's disclaimer and
search forms use **invisible** reCAPTCHA v2 (`data-size="invisible"`, invoked
via `grecaptcha.execute(widgetId)` with no checkbox), so the visible-only
handler times out. This scraper ships `status=IN_DEVELOPMENT` and declares
`RCAP_HANDLER` to signal intent; it becomes operational once kent gains an
invisible-reCAPTCHA handler (intercept `grecaptcha.execute()` → solver
service) or an equivalent driver requirement. The structure here (entry
points, submit chain, parse skeleton) is intended to be wire-compatible —
only the captcha handler swap should be needed.

**Result / case-detail layouts unverified.** See Data Available. First
operational run should validate the `# TODO(empirical)` XPaths.
