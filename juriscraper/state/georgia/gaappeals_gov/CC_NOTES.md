# Court of Appeals of Georgia (gaappeals.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Single court (`gactapp`). **HTML** scraper over the WordPress/PHP docket and
> opinion endpoints — extraction lives in the `parsers/` package (§9:
> `CaseDetailParser`, `OpinionSearchParser`); steps keep navigation (per-row
> fan-out, PDF downloads). Plain HTTP (`driver_requirements = []`), no
> auth/bot-protection. Soft-404 handled via `actually_successful` (§10). Model
> fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not
> `court_id`), `date_*` date naming, `CleanString`/`HarmonizedCaseName`
> cleaning.

## Site Overview

- **Base URL**: https://www.gaappeals.gov/
- **Docket search**: https://www.gaappeals.gov/docket-search/
- **Opinion search**: https://www.gaappeals.gov/opinion-search/
- **Backend**: a small WordPress + PHP setup. Both searches submit to PHP
  scripts under `/wp-content/themes/benjamin/docket/` that render
  server-side HTML tables.
- **Requires Playwright**: **No** — straight `httpx`/curl works. No bot
  protection, cookies, CSRF tokens, or session state.
- **Coverage**: docket back to **January 2003** (per the search-page copy).

## Courts Covered

| Site ID | Display Name | CourtListener ID |
|---------|-------------|-----------------|
| (single court) | Court of Appeals of the State of Georgia | `gactapp` |

## Search Capabilities

### Docket search

`GET /wp-content/themes/benjamin/docket/results_all.php?searchterm=<term>`

The single-text-input form is multi-purpose: the same `searchterm` parameter
matches case number, trial-court case number, or case style/name. Behaviour
observed by probing:

- **Exact case number** (`A26A1234`) → exactly 1 result row.
- **Year+letter prefix** (`A26A`) → every `A26A*` case in one response
  (~2,000 rows for `A26A`), no pagination, sorted ascending by sequence
  number. Useful for bulk discovery.
- **Year-only prefix** (`A26`) → mixed: matches both `A26*` cases *and*
  cases whose trial-court number happens to contain `A26`. Less clean than
  year+letter.
- **Case-style words** (`smith`) → substring match against the style.
- **Invalid case number** (`A26A99999`) → 0 results page.

There is no pagination on this endpoint — it dumps the full match set into
one HTML page, regardless of size. The `A26A` query returns ~1.7MB.

### Direct case detail

`GET /wp-content/themes/benjamin/docket/results_one_record.php?docr_case_num=<N>`

This is the per-case detail page. It always returns HTTP 200; **for invalid
case numbers it returns a soft-404** with an empty heading
(`<h2>Case Number: </h2>`). The scraper detects this via
`fails_successfully`.

### Opinion search

`GET /wp-content/themes/benjamin/docket/docketdate/results_all.php?OPstartDate=<MM/DD/YYYY>&OPendDate=<MM/DD/YYYY>`

Date-range search returning **decided** cases only (those with a judgment
within the window). The result table per row carries:

| Column | Notes |
|--------|-------|
| Case Number | e.g. `A26A0274` |
| Style | full caption |
| Judgment Date | e.g. `April 15, 2026` |
| COA Judgment/Ruling | e.g. `AFFIRMED`, `DISCRETIONARY APPLICATION DENIED`, `EMERGENCY MOTION DENIED`, `DISMISSED` |
| Web Docket | link to the per-case detail page |
| Opinion/Order | direct link to a PDF at `https://efast.gaappeals.gov/download?filingId=<uuid>` |

Date-format quirks:

- Both `MM/DD/YYYY` (e.g. `04/15/2026`) and `YYYY-MM-DD` (e.g. `2026-04-15`)
  parse correctly.
- The browser form quietly emits `M-D-YYYY` (`2-5-2026`) when using "Show
  Today's Opinions"; that format is **not** accepted server-side via curl —
  it silently parses to epoch `01-01-1970` and returns 0 results. The
  scraper avoids that ambiguity by always sending `MM/DD/YYYY`.
- Server echoes the parsed dates back as `MM-DD-YYYY` in the response
  heading (`57 Results for dates 04-15-2026 thru 04-22-2026`), useful for
  sanity-checking.

The endpoint returns the entire matched range in one response without
pagination. A full-year window (~2,500 opinions, ~1.2MB) returns fine in a
single request.

## Docket Number Formats

Format: `A` + two-digit year + one letter (case type) + four-digit sequence.
Sequence numbers reset annually.

| Letter | Meaning | Approx max/yr (2024-2026) |
|--------|---------|----------------------------|
| A      | Direct appeal                       | ~2,200 |
| D      | Discretionary application           | ~600   |
| E      | Emergency motion                    | ~250   |
| I      | Interlocutory application           | ~300   |
| O      | Original proceeding (rare)          | ~30    |

Other letters (`B`, `C`, `F`–`H`, `J`–`N`, `P`–`Z`) returned **no** results
across the years probed (2003–2026). Should new categories appear, the
scraper will need a new speculative entry per letter.

## Data Available

### Per-case detail page sections

The detail HTML is a sequence of tables, each preceded by an `<h3>` header.
Sections seen (some may be present-but-empty with `None`/`None` rows):

1. **Court of Appeals Information** — Case Number, Style, Status,
   Docket/Notice Date, Remittitur Date, Term, Supreme Court Transfer,
   Calendar Date.
2. **Trial Court Information** — Case Number, Clerk, Judge, County, Court,
   Appealed Order (date), Notice of Appeal (date).
3. **Filings, Motions, and Court Actions** — pairs of rows per filing:
   `Filing Date` / `Filing` (the filing description). No order or document
   download here.
4. **Court Initiated Actions** — same pair format as #3, often empty.
5. **Attorney Information** — two tables back-to-back (one for Appellant
   side, one for Appellee side). Each row carries a side label and a
   single attorney name (e.g. `Mr. Brent J. Savage`).
6. **Supreme Court Information** — populated when the case has been
   transferred or is on cert review at GA Supreme Court.

### Opinion search row

In addition to the detail page, the opinion-search row contributes:

- `judgment_date` (the disposition date)
- `judgment_ruling` (`AFFIRMED`, `REVERSED`, `DISMISSED`, …)
- `opinion_pdf_url` — direct link to the order/opinion PDF on
  `efast.gaappeals.gov`. **This is the only document available** — the
  detail page does not link to filings, only to summary descriptions.

## Email Notifications

Not available — the public site does not expose any subscribe/notify UI.

## Oral Arguments Calendar

The court publishes an oral-arguments page at
https://www.gaappeals.gov/oral-arguments/ but it is unrelated to the
docket-search backend and out of scope for this scraper.

## Bot Protection Notes

None. The endpoints accept anonymous GET requests with no cookies, no
referrer checks, and no rate limiting that we hit during recon.

## Scraper Architecture

### Entry Points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `opinions_by_decision_date(court_ids, date_range)` | `set[str]`, `DateRange` | Date-range opinion search; yields one detail fetch + one PDF archive per row |
| `dockets_by_number(docket_number)` | `GaCoaCaseNumberRange` | Speculative `A{YY}{LETTER}{NNNN}` lookup; seed once per (year, letter) bucket |

Kent's speculation walks a single integer axis per seed, but the Georgia case
number `A{YY}{LETTER}{NNNN}` partitions by both year and case-type letter
(A/D/E/I/O). Rather than one `@entry` per letter, a single speculative
`dockets_by_number` carries the discriminators inside a
`GaCoaCaseNumberRange(YearlySpeculativeRange)` (which adds a `letter` field).
A speculative entry is dispatched with ONLY its speculative param
(SCRAPER_STANDARDS §4, "Multi-court speculative entries"), so the year+letter
ride in the param; seed once per (year, letter) bucket. `from_int` copies via
`model_copy`, preserving `year`/`letter` across driver advancement.

### Step Functions (§5)

```
opinions_by_decision_date ──▶ parse_opinion_search (3) ──┬─▶ parse_case_detail (2) ──▶ ParsedData(GaCoaDocket)
                                                         └─▶ handle_opinion_download (0) ──▶ ParsedData(GaCoaOpinion)

dockets_by_number ─────────────────────────────────────────▶ parse_case_detail (2) ──▶ ParsedData(GaCoaDocket)
```

- `parse_opinion_search` (priority 3) runs `OpinionSearchParser` over the table
  on `docketdate/results_all.php` and dispatches: (a) a detail fetch for each
  case (deduped on case number), and (b) an archive request for each opinion
  PDF (priority 1 via `archive=True`, completed at priority 0).
- `parse_case_detail` (priority 2) runs `CaseDetailParser` over the per-case
  HTML — extracting the six sections above into a `GaCoaDocket` with nested
  entries / attorneys / trial-court info.
- `handle_opinion_download` (priority 0) finalises the archived PDF as a
  `GaCoaOpinion`.

### Deduplication keys (§6)

- `opinion_search:<start>:<end>` — the date-range opinion search.
- `case_detail:<case_number>` — each case-detail fetch.
- `opinion-<case_number>` — each opinion-PDF download (colon-free; used in the
  stored filename).

### Soft-404 (§10)

`actually_successful` returns `False` when the detail HTML contains
`<h2>Case Number: </h2>` (empty heading) — the universal soft-404 marker for
`results_one_record.php`. (Ported from the old `fails_successfully` hook, which
was dead code in jkent v0.1.0.)

### Models

- `GaCoaDocket` — top-level case record
- `GaCoaDocketEntry` — one row of "Filings, Motions, and Court Actions"
  (also reused for "Court Initiated Actions" with a flag)
- `GaCoaAttorney` — one attorney row, tagged with side
- `GaCoaTrialCourtInfo` — embedded trial-court block
- `GaCoaSupremeCourtInfo` — embedded Supreme Court block (when populated)
- `GaCoaOpinion` — the archived opinion/order PDF (yielded as a separate
  top-level record so it can join back to the docket via `docket_number`)
