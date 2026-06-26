# Massachusetts Appellate Courts (ma-appellatecourts.org) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two courts (`mass` = SJC, `massappct` = Appeals Court) across seven
> case-type categories. RSI "Public Access" (Laravel) site behind a
> Cloudflare managed challenge, so it runs under a real browser
> (`driver_requirements = [JS_EVAL, FF_ALIKE]`). Addressing is speculative
> case-number enumeration: every case is reachable at `/docket/{docket_id}`
> regardless of search path. HTML extraction lives in the `parsers/`
> package (§9, `CaseDetailParser`/`CalendarParser`); steps keep only the
> per-PDF archive fan-out. Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `docket_number` (not
> `docket_id`), `court` (not `court_id`), `date_*` date naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `https://www.ma-appellatecourts.org`
- **Vendor**: RSI (River Software Inc) "Public Access" platform — Laravel
  backend (CSRF token field is `_token`).
- **Requires Playwright**: **Yes** — fronted by Cloudflare's managed
  challenge. Plain `curl` returns HTTP 403 with a "Just a moment..." page;
  only after the JS challenge runs do subsequent requests succeed.
- **Bot protection**: Cloudflare managed challenge + a per-form Laravel CSRF
  token (`<input name="_token" ...>`). Speculative per-case GETs sidestep
  the form/token/session flow entirely.

## Courts Covered

| Site `doc_doctp` | Display Name | CourtListener ID | Notes |
|------------------|--------------|------------------|-------|
| `fc` | SJC Full Court Cases | `mass` | Court-of-last-resort merits docket |
| `sj` | SJC Single Justice Cases | `mass` | Single-justice motions |
| `oe` | SJC Original Entry Cases | `mass` | Original-jurisdiction cases |
| `ar` | SJC DAR and FAR Applications | `mass` | Direct & Further Appellate Review |
| `bd` | SJC Bar Docket Cases | `mass` | Attorney discipline / bar admission |
| `ac` | Appeals Court Panel Cases | `massappct` | Intermediate appellate merits docket |
| `aj` | Appeals Court Single Justice Cases | `massappct` | Single-justice motions in the Appeals Court |

The SJC (`mass`) and Appeals Court (`massappct`) are the only two courts.
All seven categories share a single case-detail page layout, distinguished
only by docket-number prefix.

## Search Capabilities

- **Date-based search**: No. The advanced form filters only by *Year Filed*
  (calendar year), never a date range.
- **Case number**: Yes. `GET /docket/{docket_id}` resolves directly to the
  case docket page; this is the primary harvest surface.
- **Party / attorney / lower-court searches**: exist but are unsuitable as
  primary entries (Last-Name-only, capped at ~3 pages). Useful only for
  discovering each sequence's current high-water mark during development.
- **Oral arguments**: no date search; `/calendar/{fc,sj,ac,aj}` shows the
  *current month* only, with no month picker (`/calendar/{type}/{year}/{month}`
  redirects to `/`).

## Docket Number Formats

| Site type | Format | Yearly? | Example | Approx. high seed (2026) |
|-----------|--------|---------|---------|--------------------------|
| `fc` | `SJC-NNNNN` | No | `SJC-13927` | ~13950 |
| `oe` | `OE-NNNN` | No | `OE-0157` | ~160 |
| `ar` | `FAR-NNNNN` | No | `FAR-30715` | ~30750 |
| `sj` | `SJ-YYYY-NNNN` | Yes | `SJ-2025-0518` | ~600/yr |
| `bd` | `BD-YYYY-NNN` | Yes | `BD-2025-004` | ~10/yr |
| `ac` | `YYYY-P-NNNN` | Yes | `2025-P-1489` | ~1700/yr |
| `aj` | `YYYY-J-NNNN` | Yes | `2025-J-0972` | ~1100/yr |

A `B` suffix sometimes appears on FAR/DAR numbers (companion applications);
the speculative driver does not enumerate them.

## Data Available

All case data lives on a single page at `GET /docket/{docket_id}` — no tabs,
AJAX sub-resources, or accordions. `CaseDetailParser` extracts:

- **Case Header** (`flex_span`/`flex_rt` label/value spans): entry date
  (→ `date_filed`), case type, nature, appellant/applicant, status +
  status date, brief status/due, argued/decision/response dates, panel,
  quorum, citation, the cross-reference numbers (SJC/AC/SJ/FAR/Full Court),
  route to SJC, and lower-court fields (→ `appeal_from_str`,
  `lower_court_number`, `lower_court_judge`, `date_lower_court_entry`).
- **Additional Information** free-text block (when present).
- **Involved Party / Attorney Appearance**: one `MaParty` per party (name,
  role, brief status, enlargement summary) + nested `MaAttorney` (name,
  title, withdrawn flag, `/attorney/{id}` link).
- **Docket Entries** table → `MaDocketEntry` rows (`date_filed`,
  `paper_number`, `description`).
- **Future Calendar** block (when scheduled) → `MaScheduledHearing` rows.
- **Documents** block: `<a href="/pdf/{docket_id}/{filename}.pdf">` links;
  each is archived as a separate `MaDocument`.

The site does **not** advertise an email-notification subscription. Not
implemented.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_number(docket_number)` | `MaCourtRange` | Speculative `GET /docket/{id}`. One canonical entry across all seven categories; `MaCourtRange` carries `court_id` + `case_category` (+ `year` for the year-partitioned formats). Seed once per category (and per year). |
| `oral_arguments_by_bulk(court_ids)` | `set[str]` | Scrape the current-month calendars for each calendar type whose court is in `court_ids`. Bulk addressing (current month only, no date picker). |

`MaCourtRange` is the §4 multi-court speculative shape: a speculative entry
is dispatched with **only** its speculative param, so the court +
discriminator ride on the param rather than as a `court_ids` arg. A single
CL court id spans several number-spaces (`mass` → 5, `massappct` → 2), so
`case_category` is the extra discriminator field; `from_int` preserves it
via `model_copy`.

### Step functions and priorities (§5)

```
dockets_by_number ─────────→ parse_case_detail (2) → ParsedData(MaDocket)
                                                   └→ (per PDF) archive (1)
                                                        → handle_document_download
                                                            → ParsedData(MaDocument)
oral_arguments_by_bulk ────→ parse_calendar (2) → ParsedData(MaOralArgument)
```

PDF downloads use `archive=True` (auto priority 1); flow steps stay at 2.

### Deduplication keys (§6)

- `parse_case_detail:<docket_id>` — each case-detail fetch.
- `parse_calendar:<calendar_type>` — each calendar page.
- `<docket_id>-<filename>` — each archived PDF (no colon, file-safe).

### Soft-404 detection (§10)

Invalid docket IDs **redirect** to the bare `/docket` search landing rather
than returning 404. `actually_successful` returns `False` when a
`/docket/...` request lands somewhere without `/docket/` in the final URL
(and lets `/calendar/` URLs through).

### Data types

`MaDocket` (main, → CL `Docket` + `OriginatingCourtInformation`) with nested
`MaParty` (+ `MaAttorney`), `MaDocketEntry`, `MaScheduledHearing`, and a
`document_urls` list. `MaDocument` (→ CL `RECAPDocument`) is a separate
top-level archive record joined back by `docket_number` + `court`.
`MaOralArgument` (+ nested `MaOralArgumentCase`) is the calendar output.
