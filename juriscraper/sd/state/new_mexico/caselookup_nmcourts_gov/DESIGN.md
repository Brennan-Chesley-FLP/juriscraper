# New Mexico Case Lookup Scraper Design

## Site Overview
- **Base URL**: https://caselookup.nmcourts.gov/caselookup/
- **Framework**: Apache Tapestry 4.1.3 (server-rendered HTML, JSP-style)
- **Requires Playwright**: No — pure httpx works once the disclaimer flow is followed
- **Transport**: HTML form (POST) — single endpoint `/caselookup/app` with
  `component`/`page` body params dispatching to different handlers

## Courts Covered

This scraper targets the two appellate courts. The same site also covers
District / Magistrate / Metropolitan / Municipal trial courts but they are
out of scope here.

| Site Court Type | Court Location | Case Category | Display Name | CourtListener ID |
|---|---|---|---|---|
| `S` | `1` | `SC` | New Mexico Supreme Court | `nm` |
| `A` | `1` | `CA` | New Mexico Court of Appeals | `nmctapp` |

The `Court Type` dropdown on the site's Name Search form *only* offers
trial-court types (D / M / T / U) — the Supreme Court and Court of Appeals
are reachable solely via the Case Number Search.

## Search Capabilities

The Case Number Search form posts four components — `courtType`,
`courtLocation`, `caseCategory`, `caseNumber` — to `/caselookup/app`.
There is no date-range filter, no party-name filter that covers the
appellate courts, and no listing endpoint that enumerates appellate
cases. Searches by exact case number return either the case detail page
(if the case exists) or a "No results found" page.

**Decision-tree result**: no date filter → no usable listing → speculative
entry on case numbers is the only viable path.

**Recommended approach**: speculative entry (`SpeculativeRange`) per court.

## Docket Number Formats

Both appellate courts use the format `{TYPE}-{LOC}-{CATEGORY}-{N}` where
the trailing `N` is a continuous, monotonically-increasing integer.

| Court | Pattern | Padding | Observed range |
|---|---|---|---|
| NMSC | `S-1-SC-{N}` | None — raw integer; `1`, `100`, `39473` all accepted | low ~1 to ~41000+ |
| NMCA | `A-1-CA-{N}` | None — raw integer | low ~1 to ~41500+ |

**Padding** is *not* used by the form. Probing confirmed that
`caseNumber=1`, `caseNumber=100`, and `caseNumber=39473` all return their
respective case detail pages without any zero-padding. The user-supplied
guess of "left-padded to 5 digits" is incorrect; the form accepts the
raw integer.

The numbering is not year-partitioned (a single global sequence per
court, not reset annually), so `SpeculativeRange` (continuous integer)
is the appropriate parameter type — *not* `YearlySpeculativeRange`.

The unified `S-1-SC-N` / `A-1-CA-N` format appears to have been
introduced after the modern case-management system rollout. Cases from
the 1990s (e.g. NMSC docket `23,321` from 1995) use a comma-formatted
single-integer docket number that doesn't fit this format and likely
isn't reachable via this scraper. nmonesource.com's older entries also
display only the trailing-N portion. Coverage of pre-format-rollout
cases is out of scope.

## Data Available

### Case Summary (top of detail page)
- `case_number` — full docket id, e.g. `S-1-SC-39473`
- `current_judge` — current assigned judge (often blank for appellate)
- `date_filed` — filing date (`MM/DD/YYYY`)
- `court` — uppercase court name (e.g. `NEW MEXICO SUPREME COURT`)
- `case_name` — page heading (e.g. `State v. Houidobre`)

### Parties
- `party_type` — coded role (`PAPT` = Plaintiff-Appellant, `DAPE` =
  Defendant-Appellee, `PETN` = Petitioner, `RESP` = Respondent, etc.)
- `party_description` — human-readable role label
- `party_number` — sequence within type
- `party_name` — `LAST FIRST MIDDLE` for individuals or org name

### Hearings
- `hearing_date`, `hearing_time`
- `hearing_type` — e.g. `Oral Argument`
- `hearing_judge`
- `court`, `court_room`

Both past and future hearings appear in this section. Per the kent
convention (see CLAUDE.md / feedback memory), future-calendar items are
modelled as `DocketEntry`-equivalent rows on the docket — so I roll
hearings into the `entries` list rather than declaring a parallel
`Hearing` model.

### Register of Actions Activity
- `event_date`
- `event_description` — e.g. `MTN: Motion for Extension of Time`,
  `ORD: Order Granting Motion`, `Brief In Chief`
- `event_result` — e.g. `Granted In Part` (often blank)
- `party_type`, `party_number` — which party filed (often blank for
  court-issued orders)
- `amount` — fees (typically blank)

A subset of rows are 2-column "sub-rows" carrying free-text supplemental
text like the title of a brief or the disposition of a motion. These
are attached to the preceding event by the parser.

### Judge Assignment History
- `assignment_date`
- `judge_name`
- `sequence_number`
- `assignment_event_description`

### Documents
**None.** The Register of Actions lists every filing's metadata (date,
type, party) but does *not* provide download links. The site is a
docket-information service only. The `entries` model still has a
`document_url` field for forward-compatibility but it will always be
`None`.

## Email Notifications
Not available. The site does not offer per-case subscription.

## Oral Arguments Calendar
No standalone calendar page. Oral arguments are visible only as rows in
the per-case "Hearings" section, so they're captured by the docket
scrape (one `entries` item per hearing) without needing a separate
`OralArgument` data type or entry point.

## Bot Protection / Session Notes

- **Disclaimer gate**: every fresh `JSESSIONID` must `POST` the
  `disclaimerForm` (with `If=T`, `If_0=F`, `If_1=T`, `Submit=I Accept`)
  before any other endpoint will respond. Direct GETs to the search
  form on a non-accepted session return a "Stale Session" page (~2860
  bytes, contains the literal text `Stale Session`).
- **CSRF token**: the case-number search form embeds a hidden
  `csrfToken` field. The token is *session-bound and reusable* across
  many submissions in the same session — it does NOT have to be
  re-fetched per request. (Confirmed via curl: same token used for two
  different case lookups in sequence.)
- **Session timeout**: the server-side session expires after a period
  of inactivity, after which all pages return a 5050-byte "Your session
  has timed out" page. The scraper detects this and treats it as a
  miss; the next entry call's bootstrap chain creates a fresh session.
- **Rate limiting**: the site enforces a server-side rate limit. When
  exceeded, the response is a tiny (~150 byte) plain-text page reading
  "You submitted too many requests. Please try again later... Blocked
  for 60 seconds." This was triggered during initial probing at roughly
  one request per 0.5–1 seconds. The scraper uses a 1-request-per-3-
  seconds rate limit to stay well clear.
- **Terms of Service**: the disclaimer page text states that "attempts
  to download multiple records per transaction are strictly
  prohibited," citing NMSA 1978 § 14-3-15.1. Operator should review
  before running large-scale bulk collection.

## Soft-404 Detection

The case-number search returns HTTP 200 in three failure modes plus the
success mode:

| Body marker | Meaning | `fails_successfully` |
|---|---|---|
| `No results found.` | Case ID does not exist | `False` (miss) |
| `Your session has timed out` | Session expired | `False` (treat as miss; next call rebootstraps) |
| `Stale Session` | Disclaimer not yet accepted in session | `False` (same — next call bootstraps) |
| (case detail tables present) | Hit | `True` |

## Scraper Architecture

### Entry Points
- `fetch_supreme_court_docket(rid: SpeculativeRange)` — yields
  `S-1-SC-{rid.min}` per call, court_id `nm`.
- `fetch_court_of_appeals_docket(rid: SpeculativeRange)` — yields
  `A-1-CA-{rid.min}` per call, court_id `nmctapp`.

Each entry returns a Request to GET `/caselookup/` (the disclaimer
landing) and routes through a small bootstrap chain.

### Step Functions (per case)
```
GET /caselookup/
  └─ bootstrap_session
       ├── (disclaimer page) → form.submit() → fetch_search_form
       │                                         └─ GET search-form-url
       │                                              └─ parse_search_form
       │                                                   └─ form.submit({...})
       │                                                        └─ parse_case_detail
       │                                                             └─ ParsedData
       └── (welcome page — already accepted) → GET search-form-url → ...
```

Best case (after first call's disclaimer is cached in the session): 3
round-trips per case (`/`, search-form GET, search POST). First call: 4
round-trips.

### Models
- `NmDocket` — top-level docket
- `NmDocketEntry` — register-of-actions row (and hearing rows folded in)
- `NmParty` — party row
- `NmJudgeAssignment` — judge assignment history row

No `NmDocument` (site has no downloadable documents).

## Known Gaps
- No documents — confirmed; site is metadata-only.
- Pre-2010-ish cases using the older comma-formatted docket numbers
  (e.g. `23,321`) cannot be reached through this form and are out of
  scope. Modern case numbers (`S-1-SC-N`, `A-1-CA-N`) are fully covered.
- Operator should respect the site's bulk-download prohibition and the
  60-second rate-limit block on overuse.
