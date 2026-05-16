# Supreme Court of Ohio (ECMS) Scraper Design

## Site Overview
- **Base URL**: <https://www.supremecourt.ohio.gov/clerk/ecms/#/search>
- **Requires Playwright**: **No** — pure JSON API over httpx works once a static
  CSRF token is supplied.
- **Transport**: JSON API (`POST .../clerk/ecms/Ajax.ashx`, action-dispatched)

The visible UI is an Ember/AngularJS SPA, but every UI action dispatches a
single `POST /clerk/ecms/Ajax.ashx` form-encoded request and renders the
returned JSON client-side. The API is open: no auth, no captcha, no session
cookie required (so long as the right headers are present).

## Courts Covered

| Site ID | Display Name | CourtListener ID |
|---------|--------------|------------------|
| —       | Supreme Court of Ohio | `ohio` |

Single court. The site also serves docket data for prior-court appeals (12
intermediate Districts of Appeals, Board of Tax Appeals, Public Utilities
Commission, etc.) but those are referenced as **prior-jurisdiction** metadata
on Supreme Court cases — they are not separately searchable docket data
sources. The Ohio appellate districts have their own scrapers / sites.

## Search Capabilities

The portal exposes three search modes through the same Ajax endpoint:

1. `action=GetCaseDetails` — fetch a single case's full record by
   `paramCaseYear` + `paramCaseNumber`. Returns the entire case file
   (CaseInfo, Parties, DocketItems, DecisionItems, CaseIssues) in one call.
2. `action=CaseSearch` — multi-criteria search (caption, party, attorney,
   date range, case type, prior court). **Capped at 1000 results per call.**
   No server-side pagination beyond that cap; the operator must split a
   filter that exceeds 1000 hits.
3. `action=GetRecentFilings` — last-N-day filings index (used only by the
   "Recent Filings" tab; not a full case search).

**Decision-tree result for bulk scraping**: case numbers are year-sequential
and continuous (`YYYY-NNNN` 4-digit, starting at `0001`), so
`YearlySpeculativeRange` enumeration is the cleanest bulk strategy —
one `@entry` invocation per `(year, n)` — and gives full per-case detail
in a single API call. Date-range search is also viable but requires
splitting any window with >1000 hits.

**Recommended approach**: speculative entry on `(year, number)` for bulk;
a second entry point lets a user request a single docket by `YYYY-NNNN`
docket-id string for ad-hoc fetches.

## Docket Number Formats

Single format: `YYYY-NNNN` (4-digit year, hyphen, 4-digit zero-padded
sequential number, reset each calendar year).

Examples:
- `1985-0001` — earliest in the system (database starts 1985-01-01)
- `2024-1234`
- `2026-0561` — current peak (as of 2026-05-06)

The API treats `paramCaseYear` and `paramCaseNumber` as separate fields.
Empty/short numbers are accepted but appear to use a prefix-LIKE match;
non-existent numbers return the sentinel string `"Too many results"` (see
soft-404 below).

## Data Available

`GetCaseDetails` returns one JSON object with the following top-level keys.
All fields are present on every response (empty lists / `null` when absent).

### CaseInfo (object)
| Field | Type | Notes |
|---|---|---|
| `ID` | int | Internal numeric case id |
| `CaseNumber` | str | `YYYY-NNNN` |
| `Caption` | str | Multi-line case caption (`A\nv.\nB`) |
| `DateFiled` | str (ISO 8601) | e.g. `"2026-02-17T05:00:00"` |
| `Status` | str | `"Open"` / `"Closed"` |
| `CaseType` | str | One of ~70 case-type strings (e.g. `"Jurisdictional Appeal"`) |
| `PriorJurisdiction` | str \| null | Mirrors `CaseJurisdiction.Name` |

### CaseJurisdiction (prior court)
| Field | Type | Notes |
|---|---|---|
| `Name` | str \| null | e.g. `"11th District Court of Appeals"` |
| `County` | str \| null | e.g. `"Lake"` |
| `PriorDecisionDate` | str (ISO 8601) \| null | |
| `PriorCaseNumbers` | list of `{Number: str}` | Trial-court / lower-appellate case numbers |

### DocketItems (list of docket entries)
| Field | Type | Notes |
|---|---|---|
| `ID` | int | Used as the PDF filename (`{ID}.pdf`) |
| `Description` | str | Filing description |
| `Code` | str | Numeric internal action code |
| `Type` | str | `"DOCKET"` (always, on this list) |
| `DateFiled` | str (ISO 8601) \| null | Some scheduling/system entries lack a date |
| `DocumentName` | str \| null | `"{ID}.pdf"` if a PDF is attached |
| `FilingParties` | str \| null | Free-text filer label, e.g. `"Appellant"`, `"Appellee"` |

### DecisionItems (list of disposition / order entries)
| Field | Type | Notes |
|---|---|---|
| `Description` | str | Disposition text; may contain HTML anchors to opinion PDFs |
| `ReleaseDate` | str (ISO 8601) | |
| `DisposesCase` | bool | Whether this disposition closes the case |
| `DocumentName` | str \| null | `"{ID}.pdf"` if a PDF is attached |

### Parties (list)
| Field | Type | Notes |
|---|---|---|
| `Name` | str | |
| `ProSe` | bool | |
| `Type` | str | `"Appellant"`, `"Appellee"`, `"Relator"`, ... |
| `Attorneys` | list | See below |

#### Attorney
| Field | Type | Notes |
|---|---|---|
| `Name` | str | `"Last, First Middle"` |
| `ARNumber` | str | Ohio attorney registration number |
| `CounselOfRecord` | bool | |

### CaseIssues (list)
Empty in most cases. Used only for cases on the "Issues Accepted" list (a
small curated list of cases the court has accepted to hear on the merits).
We collect any free-text strings that appear and store them on the docket.

### PDF download URL pattern

Docket items:
```
https://www.supremecourt.ohio.gov/pdf_viewer/pdf_viewer.aspx
    ?pdf={DocumentName}
    &subdirectory={CaseNumber}\DocketItems
    &source=DL_Clerk
```

Decision items: same, but `subdirectory={CaseNumber}\DecisionItems`.

(The `\` is an actual backslash, not a forward slash; it must be
URL-encoded as `%5C`.)

## Email Notifications

Available. The case-detail page advertises a "Case Activity Notification:
Login" link (top right of the case header). It is gated behind a separate
public-portal login (the Clerk's "Account Login" flow at `/clerk/ecms/`)
so we are **not** wiring the scraper into it; scrapers should fetch the
data directly rather than subscribe to events.

## Oral Arguments Calendar

The Supreme Court of Ohio publishes oral-argument calendars at a separate
site (`www.supremecourt.ohio.gov/SCO/sources/oralArguments/...`), not
through this docket portal. **Out of scope** for this scraper.

## Bot Protection Notes

- **CSRF token** — the API rejects requests without an
  `X-CSRF-TOKEN: hP3ZyrdvKmaPk4kVjgko7xxNUob` header. The token is hard-coded
  into the JS bundle (`scripts/dist/site.min.js?ver=3`) and is the same for
  every visitor; the scraper extracts it on startup with a regex against
  the bundle so we don't drift if it ever rotates.
- **Referer required** — the API silently returns an empty body (HTTP 200,
  zero bytes) if the `Referer` header is missing. Sending
  `Referer: https://www.supremecourt.ohio.gov/clerk/ecms/` is sufficient.
- No session cookies, no captcha, no rate limiting we hit during probing.

## Soft-404 Detection

The API returns HTTP 200 and the literal JSON string `"Too many results"`
when `paramCaseYear`/`paramCaseNumber` does not match exactly one open
case (covers both "no match" and "multiple prefix matches"). All real
matches return a JSON object with `CaseInfo.ID > 0`.

`fails_successfully` checks for the sentinel string in the body.

## Scraper Architecture

### Entry Points

| Method | Param type | Purpose |
|---|---|---|
| `fetch_docket(docket_id: str)` | `str` (`YYYY-NNNN`) | Ad-hoc lookup — user knows the docket number |
| `fetch_docket_speculative(case_id: YearlySpeculativeRange)` | speculative | Bulk enumeration over a year's case sequence |

Both entry points produce the same `POST .../Ajax.ashx` request with
`action=GetCaseDetails` and dispatch to the same parser.

### Step Functions

Single-step flow — `GetCaseDetails` returns the entire case record in one
call, so there's no tab chain:

```
fetch_docket / fetch_docket_speculative
    -> POST Ajax.ashx (action=GetCaseDetails)
    -> parse_case_detail
        -> ParsedData(OhioSupremeCourtDocket)
        -> for each item with a DocumentName:
            archive=True request -> handle_document_download
                                  -> ParsedData(OhioSupremeCourtDocument)
```

### Models

- `OhioSupremeCourtDocket` (top-level) — case metadata + nested entries,
  decisions, parties, prior-court info, issues, document references
- `OhioSupremeCourtDocketEntry` — a single docket-item row
- `OhioSupremeCourtDecision` — a single decision/order row
- `OhioSupremeCourtParty` — party with embedded attorneys
- `OhioSupremeCourtAttorney` — attorney with AR number
- `OhioSupremeCourtPriorCourt` — prior jurisdiction / county / lower-court case numbers
- `OhioSupremeCourtDocument` — archive output record (one per downloaded PDF)
