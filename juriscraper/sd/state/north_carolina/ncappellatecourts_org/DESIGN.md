# North Carolina Appellate Courts Scraper Design

## Site Overview

Two cooperating sites cover the NC appellate courts:

- `https://www.ncappellatecourts.org/search-results.php` — eFiling document
  library with date-range / docket-number / party / attorney search.
  Returns a *filings feed* (one row per e-filed document, grouped per
  case). Slow (~20–30 s per request) but stable.
- `https://appellate.nccourts.org/dockets.php` — docket-sheet portal for
  the Court of Appeals (`court=2`) and Supreme Court (`court=1`). With
  `pdf=1` it returns a richly structured HTML docket sheet (despite the
  name) — case header, history, lower-court info, register of actions
  with rulings, parties and attorneys. The "PDF" name is a misnomer; the
  response is `text/html`.

- **Requires Playwright**: No — both endpoints serve full HTML over
  httpx with a browser-like User-Agent. No CloudFlare challenge, no JS
  gating.
- **Transport**: HTML form (GET) on both endpoints.

## Courts Covered

| Site `court=` | Display Name | CourtListener ID |
|---|---|---|
| `1` | Supreme Court of North Carolina | `nc` |
| `2` | North Carolina Court of Appeals | `ncctapp` |

`search-results.php` uses string codes for the same courts:
`court_name=sc` (Supreme Court) and `court_name=coa` (Court of Appeals).

## Search Capabilities

Decision tree for bulk strategy (from design-scraper Phase 2):

1. Site has a usable date-range filter? → **Yes**, on
   `search-results.php`. The `start_date` / `end_date` filter applies to
   *document* filing date (i.e. it surfaces cases with any e-filed
   activity in the window, not cases newly opened in the window).

**Recommended approach**: date-based listing search. Walk
`search-results.php`, extract unique cases per page, and fetch each
case's docket sheet from `dockets.php?…&pdf=1`.

### Date-search quirk worth recording

`search-results.php` only honours the date filter when
`bSearchTypeAnd=0` ("Or" search-condition). With `bSearchTypeAnd=1`
("And") on a date-only query the server silently ignores both dates and
returns the entire 400 000-row corpus. The scraper hard-codes
`bSearchTypeAnd=0` for date-range entries.

### Docket-number lookup

Direct, exact lookup at `dockets.php?court={1|2}&docket={USER}&submit=Search`
returns an intermediate page with the case title and a link to the rich
docket-sheet view (`dockets.php?court={N}&docket={INTERNAL}&pdf=1&a=0&dev=1`).
The scraper follows that link in a second request.

## Docket Number Formats

| Court | Format | Examples |
|---|---|---|
| COA appeal of right | `YY-NNNN` | `26-310`, `25-1111`, `24-506` |
| COA petition       | `PYY-NNN` | `P26-334`, `P25-974`           |
| Supreme Court      | `NNNNX{1,2}YY[-N]` | `15P26`, `1A26`, `1PA26`, `258A22-2` |

The internal ID embedded in the rich docket-sheet URL has the form
`{court}-{Y4}-{NNNN}-{NNN}` (or `{court}-P{Y4}-{NNNN}-{NNN}` for COA
petitions). The scraper does **not** synthesise this — it parses the
intermediate search page and follows the link, which is more robust to
format variations and the trailing `-001` part.

The scraper picks the court from a regex on the user-facing format:

- `^P?\d{1,2}-\d+$` → COA (`court=2`)
- `^\d+[A-Z]+\d{2}(-\d+)?$` → SC (`court=1`)

## Data Available

### Case header (from `dockets.php?…&pdf=1`)
Case Number; "As of" date; Case Closed (Y/N); Case Close Date; Case
Type (e.g. "Criminal (Felony Other)"); Mediation; long title (caption);
Docket Date; File Date + Time; Acquire Date; Bond Collection; Docket
Fee; Pauper; Print Deposit; State Appeals.

### History
Venue (county), Heard In (e.g. "Superior Court"), Previous Venue (SC
only), To SC, From SC.

### Lower Court Number(s)
Location (county), Judge, Case # (trial-court docket).

### Register of actions ("Documents" table)
Per row: ordinal index, document type, Date Recvd, Cert of Service,
Rec/Brf Due, Resp. Due, Resp. Recvd, Mailed Out, Ruling, Ruling Date.
Below the table is a free-text expansion per row with "FOR: <party>"
and "BY: <attorney> / <firm>" plus the order text inside `<blockquote>`
when the row was ruled on.

### Parties
Two-column table: Party Name, Role
(e.g. "Plaintiff-Appellee" / "Defendant-Appellant").

### Attorneys (free-text by party)
Each `<strong>Attorney for {role} - {party}</strong>` block lists one
or more attorneys with their title, then a shared firm address /
phone block. Email is obfuscated by Cloudflare's `cfemail` widget.
**Parsed into a structured list in v1 best-effort; expect noise.**

### E-filed documents (from `search-results.php?sDocketSearch=…&exact=1`)
Per filing: type (Record / Motion / Petition / Response / Brief /
Notice), sub-type (e.g. `m-ext-pr`, `record (printed)`), filer name,
filed date, document URL (`show-file.php?document_id=…`). Sealed
filings appear with a `(Sealed)` marker and no download link.

The scraper yields each filing as an `NCAppealsDocument` row, parallel
to the docket. Downloadable PDFs are also archived (`archive=True`)
and the local path lands on the model. The docket-sheet pages on
`appellate.nccourts.org` carry the structured register-of-actions
columns (rulings, dates) but no URLs; the per-case e-filing page
carries the URLs but not the structured columns. Both records share
`docket_id` and a `date_filed` + `document_type` pair, so a downstream
join can stitch them together (intentionally left to the consumer —
the join is lossy when a case has multiple same-day filings of the
same type, and the scraper has no better signal).

## Email Notifications

`ncappellatecourts.org` has a "Register" link to create an account that
can subscribe to per-case email alerts on filings. **Out of scope for
v1** (would require account auth).

## Oral Arguments Calendar

`https://appellate.nccourts.org/calendar.php?court={1|2}` lists oral
argument sittings. **Out of scope for v1** — the user asked only for
docket entry points.

## Bot Protection Notes

None observed. Both endpoints respond to a normal GET with a real
User-Agent. The scraper does not need cookies, CSRF tokens, or
JavaScript execution. The dockets.php response embeds Cloudflare's
email-decoder script, which is harmless for our purposes (it only
decodes already-rendered `[email protected]` placeholders).

## Known Gaps (v1 → v2)

- Per-row document URLs are emitted as parallel `NCAppealsDocument`
  records but **not** stitched into the docket's register-of-actions
  rows; that join is left to a downstream pipeline because the only
  available join keys (`docket_id`, `date_filed`, `document_type`)
  are not unique when a case has multiple same-day filings of the
  same type.
- Attorney parsing is structured but best-effort; firm/address/phone
  attribution to individual attorneys is shared-block, not per-attorney.
- No Appeal Information Statement (`/ais-view.php`) parsing.
- No order-text scraping from `orders.php`.
- No oral-argument calendar entry point.

## Scraper Architecture

### Entry Points

- `get_docket(docket_number: str)` — fetch one docket. Routes to SC or
  COA by regex. Yields a Request to
  `dockets.php?court={N}&docket={USER}&submit=Search`.
- `get_dockets_by_date(date_range: DateRange)` — fetch all cases that
  had any e-filing in the window. Yields a Request to
  `search-results.php?start_date=…&end_date=…&bSearchTypeAnd=0`.

### Step Functions

```
get_docket           ──▶ parse_docket_search_result ──▶ parse_docket_sheet ──▶ NCAppealsDocket
                                                       ▲                       │
get_dockets_by_date  ──▶ parse_filings_listing ───────-┘                       │
                              │                                                ▼
                              └─▶ (next page) parse_filings_listing      parse_case_filings
                                                                               │
                                                                               ├─▶ archive Request → handle_document_download → NCAppealsDocument
                                                                               └─▶ (sealed)  ParsedData(NCAppealsDocument)
```

`parse_filings_listing` extracts unique
(docket_number, court_id, case_name, internal_docket_url) tuples from
the page's repeating `div.docket-{N}` blocks and yields one
`parse_docket_sheet` request per case (with `deduplication_key=docket_id`
so an overlapping date range doesn't refetch). It also yields a
pagination request (with `SkipDeduplicationCheck()`) for each remaining
`iStart` offset listed in the page-select dropdown.

`parse_docket_sheet` yields the `NCAppealsDocket` and *also* fans out
to `parse_case_filings` (a per-case fetch of
`search-results.php?sDocketSearch={docket}&exact=1`).
`parse_case_filings` walks the filing rows, archives every
downloadable PDF via `archive=True`, and yields sealed-filing rows
directly (no download).

### Models

- `NCAppealsDocket` — top-level docket record
- `NCAppealsDocketEntry` — one register-of-actions row
- `NCAppealsDocument` — one e-filed document (parallel record;
  archived PDF + metadata)
- `NCAppealsParty` — party row
- `NCAppealsAttorney` — attorney appearance (may share firm with peers)
- `NCAppealsLowerCourt` — lower-court info block

### Soft-404 Detection

For docket-number lookups the intermediate page always returns HTTP
200; misses are detected by the literal string
`Your search returned a total of <strong…>0 cases</strong>` on the
result page. We override `fails_successfully` to flag this as a miss
when `entry_point=='get_docket'` is set in `accumulated_data`. (Other
flows — date-range listing pages and the rich docket-sheet detail page
— are passed through as successes; an empty listing is just a valid
empty response and the detail page is reached only via a link known to
exist.)

### Generous timeout

`search-results.php` regularly takes 20–30 s to return. The scraper
relies on the kent default request timeout (≥ 60 s). If the operator's
configured timeout is below that, this scraper will need it bumped.

### Rate limiting

`Rate(1, Duration.SECOND)` — conservative. The site is small and
slow, and unlikely to want hammering.

## Verified Examples

- COA appeal `26-310` → `dockets.php?court=2&docket=2-2026-0310-001&pdf=1` →
  `State v. Sings`, 4 register rows, 2 parties, 2 attorney blocks.
- COA petition `P26-334` → `dockets.php?court=2&docket=2-P2026-0334-001&pdf=1`.
- Supreme Court `15P26` → `dockets.php?court=1&docket=1-2026-0015-001&pdf=1` →
  `Justice v Carriage Hill of Carthage Homeowner's Assoc. Inc.`, with
  a `Previous Venue: N.C. Court of Appeals (200)` row that surfaces
  the cross-court lineage.
