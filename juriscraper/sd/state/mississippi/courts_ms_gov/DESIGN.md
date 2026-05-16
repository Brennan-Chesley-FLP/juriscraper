# courts.ms.gov Scraper Design

Scraper for the Mississippi Supreme Court (SCT) and Court of Appeals (COA),
covered by the unified appellate-courts portal at <https://courts.ms.gov>.

## Site Overview

- **Base URL**: <https://courts.ms.gov/index.php>
- **Detail URL pattern**: `https://courts.ms.gov/index.php?cn={case_num}#dispArea`
  where `case_num` is an internal sequential integer ID.
- **Requires Playwright**: **No.** All four detail endpoints respond to plain
  `httpx`/`curl` POSTs with `Content-Type: application/x-www-form-urlencoded`
  and `X-Requested-With: XMLHttpRequest`. There is a reCAPTCHA widget loaded
  for the e-file flow, but it does not gate the public docket data.
- **Stack**: ASP-style PHP backend on Microsoft-IIS/10.0. Returns either
  `application/json` (for autocomplete) or HTML fragments (for case detail).

## Courts Covered

The portal indexes both the Supreme Court of Mississippi and the Court of
Appeals of Mississippi from a single cases table. The court is encoded in
the docket-number suffix (`-SCT` or `-COA`).

| Site suffix | Display Name                       | CourtListener ID |
|-------------|------------------------------------|------------------|
| `SCT`       | Supreme Court of Mississippi       | `miss`           |
| `COA`       | Court of Appeals of Mississippi    | `missctapp`      |

(Some pre-1997 cases use a 2-digit-year format with no court suffix at all,
e.g. `91-CA-00169` — see "Docket Number Formats" below. These are still
served from the same backend and are mapped to `miss` by default; the site
does not distinguish.)

## Search Capabilities

There is **no date-based search** in the public UI. The only inputs are:

1. **Autocomplete search** (`phpdocket.php`) — accepts a partial docket number
   or case caption. Always **capped at 7 results**, used to drive the home-
   page "Case Search…" autocomplete dropdown. Not useful for bulk scraping.
2. **Direct case lookup by internal `case_num`** — `index.php?cn=…#dispArea`
   loads the case page for any internal numeric ID. The detail-fetch APIs
   (`build_docket.php`, etc.) take this same `case_num` directly.
3. **Hand-Down Lists** — `getHanddown.php` returns the per-week opinion
   release sheet for a chosen `(year, court)` combination. Useful for
   opinions only, not full docket coverage. Not yet implemented in this
   scraper.

There is no party-name, attorney-name, or judge-name search.

**Recommended approach**: speculative entry over the internal
`case_num` integer space.

### Why internal `case_num`, not the public docket number?

The autocomplete API treats the docket number as a fuzzy substring; it cannot
be used to enumerate. But every detail endpoint accepts the internal
`case_num` directly:

```
POST https://courts.ms.gov/appellatecourts/docket/build_docket.php
docket_type=docket&sortdir=desc&case_num=98638&limit=true
```

`case_num` is a single sequential integer assigned at filing time, shared
across both courts and all case types. Currently observed range: roughly
**1 – 110 000**, with the leading edge near 100 500 in Q2 2025 and growing
~10 000/year.

Soft-404 detection: when no public case exists for a given `case_num` the
response body says

```
No public results were found for your search. Please note that all cases
are not currently available to the public...
```

(small ~928-byte body). The scraper checks for this string in
`fails_successfully`.

## Docket Number Formats

Two variants observed:

- **Modern** (1996+): `YYYY-{TYPE}-{NNNNN}-{COURT}` (e.g.
  `2024-KA-01178-SCT`, `2025-WC-01288-COA`). Sequence number `NNNNN` is
  per-(year, type), commonly running 0 – ~01500 for an active type.
- **Legacy** (pre-1997 archive): `YY-{TYPE}-{NNNNN}` (e.g. `91-CA-00169`).
  No court suffix.

Observed `TYPE` codes (non-exhaustive): `KA`, `KP`, `KM` (criminal),
`CA`, `CT`, `CC`, `CP` (civil / certiorari / pro-se civil), `IA`
(interlocutory appeal), `WC` (workers' comp), `BD`/`BR` (bar /
disciplinary), `SA` (state agency), `EC` (election contest), `DR` (rule
challenge), `TS` (transfer), and others.

The scraper does not parse or rely on the `TYPE` semantics — it just
captures the docket number string verbatim from the case-header HTML.

## API Endpoints

All endpoints are POST with form-encoded bodies under
`https://courts.ms.gov/appellatecourts/docket/`. Required headers:
`Content-Type: application/x-www-form-urlencoded; charset=UTF-8` and
`X-Requested-With: XMLHttpRequest`.

| Endpoint              | Body params                                        | Response  | Purpose                                  |
|-----------------------|----------------------------------------------------|-----------|------------------------------------------|
| `phpdocket.php`       | `search_terms=…&reset_search=Y`                    | JSON      | Autocomplete (capped at 7).              |
| `build_docket.php`    | `docket_type=docket&sortdir=desc&case_num=N&limit=true` | HTML | Case header + docket entries (+ PDF refs) |
| `build_docket.php`    | `docket_type=apinfo&case_num=N&listby=pty`         | HTML      | Parties grouped by role, with attorneys  |
| `build_docket.php`    | `docket_type=apinfo&case_num=N&listby=att`         | HTML      | Same data inverted: attorneys → parties  |
| `build_docket.php`    | `docket_type=lcinfo&case_num=N`                    | HTML      | Trial-court info block                   |
| `build_docket.php`    | `docket_type=oralarg&case_num=N`                   | HTML      | Oral argument links (Vimeo)              |
| `sendPDF.php`         | `?f={file}.pdf&c={case_num}&a=N&s=2` (GET)         | PDF       | Document download                        |
| `getHanddown.php`     | `?yr=YYYY&ct={SCT,COA}` (POST)                     | HTML      | Hand-down opinion list (not yet wired)   |

## Data Available

### Case Header (`docket_type=docket`)
- `casenum` — public docket number (`<td class="casenum">`)
- Caption — second `<tr>` of the header table
- (No filing date, disposition, or status field on the header itself —
  these must be inferred from docket entries.)

### Docket Entries (`docket_type=docket`)
Each entry is a `<tr class="entry">` containing:
- `<td class="DATE">` — `M/D/YYYY` filing date (no zero-padding)
- `<td class="DESCRIPTION" id="desc-N">` — entry text
- An optional sibling `<tr class="dockpdf-N">` with one
  `<a href="/appellatecourts/docket/sendPDF.php?f={file}.pdf&c=…">…</a>`

The entries form is sorted; `numDocketRows` hidden input gives the count.

### Documents
Every PDF link uses `sendPDF.php?f={file}.pdf&c={case_num}&a=N&s=2`. The
`f` param embeds two hyphen-joined integers: a category code prefix
(e.g., `400_`, `500_`, `730_`) and a global file ID. Documents are
attached to docket entries via DOM proximity — the `dockpdf-N` row
immediately follows its parent `entry-N`. Description text on the link
itself echoes the entry description.

The scraper grabs **every** referenced PDF and yields it as an archive
Request → `MsAppDocument`.

### Parties & Attorneys (`listby=pty`)
Layout: groups of `<TABLE BGCOLOR="#003366">` blocks, each headed by a
`laptcell` cell holding the role label (`Appellant`, `Appellee`, `Cross-
Appellant`, etc., or empty for amici / interested parties), a `Name`
cell, and a child table listing `liaptcell` rows for each attorney.
Attorneys are *names only* — the site does not expose firms, addresses,
phone, or bar numbers via this endpoint.

The `listby=att` view is the inverse of the same data and we do not
fetch it; `listby=pty` is sufficient.

### Trial Court (`docket_type=lcinfo`)
A small `<TABLE>` with `tccell` rows in this order:
1. Public docket number (re-stated)
2. Caption (re-stated)
3. Trial court name (e.g. "Rankin Circuit Court")
4. `Trial Court Case # …`
5. `The Honorable …` — judge
6. `Ruling Date: MM/DD/YYYY`

Some cases have rulings from **multiple** trial courts; the table can
repeat rows 3-6 for each. The scraper parses each repeating block into
its own `MsAppTrialCourt` and attaches them as a list.

### Oral Arguments (`docket_type=oralarg`)
Either an empty pane or one or more `<a>` links (Vimeo URLs) under a
`#archList` table. Each link is captured as an `MsAppOralArgument`.

## Email Notifications

No public email-notification subscription is exposed to anonymous users.
Registered MEC users get filing notifications, but this requires a
subscriber account and is out of scope for this scraper.

## Oral Arguments Calendar

`https://courts.ms.gov/appellatecourts/sc/scoa.php` and `…/coa/coaoa.php`
list upcoming oral arguments with date/time, case number, caption, and a
Vimeo livestream URL. This scraper attaches per-case oral-argument
records via the case-detail flow above; a future iteration could add a
calendar entry-point for forward-looking event scraping.

## Bot Protection Notes

- Site loads `recaptcha_key2`/`recaptcha_key3` for the e-file flow only.
  Public docket reads are not gated.
- The session-cookie endpoint `session_check.php` returns 400 to
  unauthenticated POSTs and is not required for read access.
- A custom `User-Agent` (browser-like) is sent by default; `httpx`'s
  default UA also works in testing.

## Scraper Architecture

### Entry Points

- `@entry(MsAppDocket) fetch_docket(case_num: SpeculativeRange) -> Request`
  Single speculative entry for the unified case-num space. Both SCT and
  COA cases come out of it; `court_id` is decided at parse time from the
  docket-number suffix. Seed at `min=100500, gap=20`.

### Step Functions

```
fetch_docket
    └── parse_docket_page (build_docket.php?docket_type=docket)
        ├── parse_parties (apinfo, listby=pty)
        │   └── parse_trial_court (lcinfo)
        │       └── parse_oral_arguments (oralarg)
        │           └── ParsedData(MsAppDocket)
        └── ⤳ for each PDF: download_document (archive=True)
```

Each step accumulates state in `accumulated_data` and yields the next
sub-fetch. The final `parse_oral_arguments` step constructs the full
`MsAppDocket` and yields `ParsedData`. PDF archive requests are yielded
from `parse_docket_page` (where the references live) and resolved
independently into `MsAppDocument` records.

### Soft-404

`fails_successfully` checks for `"No public results were found"` in the
docket-page HTML.

### Models

- `MsAppDocket` — main type, court_id `miss` or `missctapp`.
- `MsAppDocketEntry` — one per `<tr class="entry">`.
- `MsAppDocument` — one per archived PDF.
- `MsAppParty` — name + role + attorneys.
- `MsAppAttorney` — just a name (the site doesn't expose more).
- `MsAppTrialCourt` — court name, case #, judge, ruling date.
- `MsAppOralArgument` — Vimeo URL + display label.
