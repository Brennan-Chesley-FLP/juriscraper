# Supreme Court of Ohio (ECMS) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Single court (`ohio`). Pure JSON API spoken directly over HTTP
> (`driver_requirements = []`) — every UI action is a single
> `POST .../clerk/ecms/Ajax.ashx` form-encoded request returning JSON, so
> there is **no `parsers/` package** (no HTML to parse, per Step 3.5 /
> arkansas-nevada convention); the small payload-shaping helpers live at
> module level in `scraper.py`. Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `docket_number` (not `case_number`/`docket_id`), `date_*` date naming,
> `role` for a party's role; `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: <https://www.supremecourt.ohio.gov/clerk/ecms/#/search>
- **Backend**: Ember/AngularJS SPA over an action-dispatched JSON endpoint
  (`POST /clerk/ecms/Ajax.ashx`).
- **Requires Playwright**: **No** — the JSON API works over plain HTTP once a
  static CSRF token + `Referer` are supplied.

The visible UI renders returned JSON client-side. The API is open: no auth,
no captcha, no session cookie required (so long as the right headers are
present).

## Courts Covered

| Site name | CourtListener ID |
|-----------|------------------|
| Supreme Court of Ohio | `ohio` |

Single court. The site also serves docket data for prior-court appeals (12
intermediate Districts of Appeals, Board of Tax Appeals, Public Utilities
Commission, etc.) but those are referenced as **prior-jurisdiction**
metadata on Supreme Court cases (→ `OhioSupremeCourtPriorCourt`, CL
`OriginatingCourtInformation`) — they are not separately searchable docket
sources here. The Ohio appellate districts have their own scrapers.

## Search Capabilities

The portal exposes three search modes through the same Ajax endpoint:

1. `action=GetCaseDetails` — fetch a single case's full record by
   `paramCaseYear` + `paramCaseNumber`. Returns the entire case file
   (CaseInfo, Parties, DocketItems, DecisionItems, CaseIssues) in one call.
   **This is the only mode the scraper uses.**
2. `action=CaseSearch` — multi-criteria search, capped at 1000 results/call.
3. `action=GetRecentFilings` — last-N-day filings index.

**Bulk strategy**: case numbers are year-sequential and continuous
(`YYYY-NNNN`, 4-digit, from `0001`), so a `YearlySpeculativeRange`
enumeration is the cleanest bulk approach — one `@entry` invocation per
`(year, n)` — and gives full per-case detail in a single API call.

## Docket Number Format

Single format: `YYYY-NNNN` (4-digit year, hyphen, 4-digit zero-padded
sequential number, reset each calendar year). Examples: `1985-0001`
(earliest in the system), `2024-1234`, `2026-0561`. The API treats
`paramCaseYear` and `paramCaseNumber` as separate fields; non-existent
numbers return the sentinel string `"Too many results"` (see soft-404).

## Data Available

`GetCaseDetails` returns one JSON object: `CaseInfo` (ID, CaseNumber,
Caption, DateFiled, Status, CaseType), `CaseJurisdiction` (prior court:
Name, County, PriorDecisionDate, PriorCaseNumbers), `DocketItems` (register
of actions), `DecisionItems` (dispositions/orders, descriptions may carry
HTML anchors), `Parties` (with nested `Attorneys`, including ARNumber /
CounselOfRecord), and `CaseIssues` (free-text issue list, usually empty).

### PDF download URL pattern

```
https://www.supremecourt.ohio.gov/pdf_viewer/pdf_viewer.aspx
    ?pdf={DocumentName}
    &subdirectory={CaseNumber}\{DocketItems|DecisionItems}
    &source=DL_Clerk
```

The `\` is a literal backslash and must be URL-encoded as `%5C`.

## Bot Protection / Soft-404

- **CSRF token** — the API rejects requests without
  `X-CSRF-TOKEN: hP3ZyrdvKmaPk4kVjgko7xxNUob`. Hard-coded in the JS bundle
  and shared by every visitor; update the constant if it ever rotates.
- **Referer required** — the API returns an empty 200 if `Referer` is
  missing. A browser-shaped `User-Agent` is also required.
- **Soft-404** — the API returns HTTP 200 with the literal JSON string
  `"Too many results"` for any no-match or multi-match prefix. Real matches
  return a JSON object with `CaseInfo.ID > 0`. `actually_successful()`
  checks for the sentinel so the driver treats a miss as a speculation soft
  failure.

## Out of Scope

- Email/activity notifications (gated behind a separate public-portal
  login — we fetch data directly).
- Oral-argument calendars (published at a separate site).

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `docket_by_number(court_id, docket_number)` | `str`, `str` (`YYYY-NNNN`) | Ad-hoc single-case lookup. |
| `dockets_by_number(docket_number)` | `YearlySpeculativeRange` | Speculative bulk enumeration over a year's case sequence. Speculative entry — takes only its speculative param (§4); the single court `ohio` is a constant. |

Both produce the same `POST .../Ajax.ashx` (`action=GetCaseDetails`) request
and dispatch to the same `parse_case_detail` step.

### Step functions and priorities (§5)

```
docket_by_number / dockets_by_number
    → POST Ajax.ashx (action=GetCaseDetails)
    → parse_case_detail (priority 2)
        → ParsedData(OhioSupremeCourtDocket)
        → per item with a DocumentName:
            archive=True request (auto priority 1)
                → handle_document_download
                    → ParsedData(OhioSupremeCourtDocument)
```

`parse_case_detail` sits at priority 2 (flow step ≥ 2); the document
downloads ride `archive=True` (auto priority 1).

### Deduplication keys (§6)

- `docket_by_number:{docket_number}` — the case-detail POST (dedups a case
  reached via either entry).
- `{docket_number}-{document_id}-{section}` — each PDF download
  (colon-free; used as a filename component).

### Data types

`OhioSupremeCourtDocket` (main, → CL `Docket`) with nested
`OhioSupremeCourtParty` (+ `OhioSupremeCourtAttorney`),
`OhioSupremeCourtDocketEntry`, `OhioSupremeCourtDecision`,
`OhioSupremeCourtPriorCourt` (→ CL `OriginatingCourtInformation`), and a
free-text `issues` list. `OhioSupremeCourtDocument` (→ CL `RECAPDocument`)
is emitted once per archived PDF, joinable to its docket via
`docket_number`.
