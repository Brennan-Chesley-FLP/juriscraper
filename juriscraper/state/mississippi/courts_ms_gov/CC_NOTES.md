# Mississippi Appellate Courts (courts.ms.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> One unified backend serves **both** the Supreme Court of Mississippi
> (`miss`) and the Court of Appeals of Mississippi (`missctapp`); the court
> is decided per-case from the docket-number suffix (`-SCT` / `-COA`). Plain
> HTTP (`driver_requirements = []`) — the four detail endpoints respond to
> form-encoded `XMLHttpRequest` POSTs; the reCAPTCHA widget gates the e-file
> flow only, not public docket reads. HTML extraction lives in the
> `parsers/` package (§9); steps keep navigation (the build_docket.php
> sub-fetches and per-PDF archive fan-out). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `date_*` date naming, `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `https://courts.ms.gov/index.php`
- **Detail URL pattern**: `https://courts.ms.gov/index.php?cn={case_num}#dispArea`
  where `case_num` is an internal sequential integer ID.
- **Backend**: ASP-style PHP on Microsoft-IIS/10.0. Returns
  `application/json` (autocomplete) or HTML fragments (case detail).
- **Requires Playwright**: No — all detail endpoints respond to plain
  `httpx` POSTs with `Content-Type: application/x-www-form-urlencoded` and
  `X-Requested-With: XMLHttpRequest`.

## Courts Covered

| Site suffix | Display Name                    | CourtListener ID |
|-------------|---------------------------------|------------------|
| `SCT`       | Supreme Court of Mississippi    | `miss`           |
| `COA`       | Court of Appeals of Mississippi | `missctapp`      |

Pre-1997 cases use a 2-digit-year format with no court suffix (e.g.
`91-CA-00169`) and are mapped to `miss` by default (the site does not
distinguish; all appellate filings routed through the Supreme Court before
the Court of Appeals was created in 1995).

## Search Capabilities

There is **no date-based search** in the public UI. The only inputs are an
autocomplete search (`phpdocket.php`, capped at 7 results — not useful for
bulk) and direct lookup by the internal sequential `case_num`. Every detail
endpoint accepts the `case_num` directly:

```
POST https://courts.ms.gov/appellatecourts/docket/build_docket.php
docket_type=docket&sortdir=desc&case_num=98638&limit=true
```

`case_num` is a single sequential integer assigned at filing time, shared
across both courts and all case types. Observed range: roughly **1 –
110 000**, leading edge near 100 500 in Q2 2025, growing ~10 000/year.

### Why internal `case_num`, not the public docket number?

The autocomplete API treats the docket number as a fuzzy substring; it
cannot enumerate. The internal `case_num` is a flat integer space we can
walk speculatively, so the scraper uses one speculative entry over it.

### Soft-404

When no public case exists for a `case_num`, the body says *"No public
results were found for your search..."* (small ~928-byte body). The scraper
overrides `actually_successful` (§10) to return `False` on that needle so
the speculation driver treats it as a soft failure.

## API Endpoints

All POST with form-encoded bodies under
`https://courts.ms.gov/appellatecourts/docket/`. Required headers:
`Content-Type: application/x-www-form-urlencoded; charset=UTF-8` and
`X-Requested-With: XMLHttpRequest`.

| Endpoint           | Body params                                             | Response | Purpose                              |
|--------------------|--------------------------------------------------------|----------|--------------------------------------|
| `build_docket.php` | `docket_type=docket&sortdir=desc&case_num=N&limit=true`| HTML     | Case header + docket entries (+ PDFs)|
| `build_docket.php` | `docket_type=apinfo&case_num=N&listby=pty`             | HTML     | Parties grouped by role, w/ attorneys|
| `build_docket.php` | `docket_type=lcinfo&case_num=N`                        | HTML     | Trial-court info block               |
| `build_docket.php` | `docket_type=oralarg&case_num=N`                       | HTML     | Oral argument links (Vimeo)          |
| `sendPDF.php`      | `?f={file}.pdf&c={case_num}&a=N&s=2` (GET)             | PDF      | Document download                    |

## Data Available

- **Case header** (`docket_type=docket`): `casenum` (public docket number),
  caption. No filing-date field — `date_filed` is inferred as the earliest
  docket-entry date.
- **Docket entries** (`docket_type=docket`): one `<tr class="entry">` each —
  `<td class="DATE">` (`M/D/YYYY`), `<td class="DESCRIPTION" id="desc-N">`,
  and an optional sibling `<tr class="dockpdf-N">` with one `sendPDF.php`
  anchor. PDFs join to their parent entry by the shared `N` index.
- **Parties & attorneys** (`listby=pty`): `<TABLE BGCOLOR="#003366">` blocks
  with a `laptcell` role label, a name cell, and child `liaptcell` attorney
  rows. Attorney HTML is malformed (unclosed tables); we bucket attorneys to
  the nearest preceding party header via `count(preceding::table[...])`.
  Attorneys are *names only*.
- **Trial court** (`docket_type=lcinfo`): `tccell` rows — court name, trial
  case #, judge, ruling date. Cases consolidating multiple trial courts
  repeat the block; each becomes one `MsAppTrialCourt`.
- **Oral arguments** (`docket_type=oralarg`): `<a>` links (Vimeo) under
  `#archList`.
- **Documents**: every referenced PDF is archived → `MsAppDocument`.

## Scraper Architecture

### Entry point (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_internal_id(internal_id)` | `SpeculativeRange` | Speculative walk of the unified `case_num` space; both courts emerge, `court` decided from the docket suffix at parse time. |

A speculative entry takes **only** its speculative param (§4). The court is
*derived* from the response, not addressed, so this is a plain
`SpeculativeRange` rather than a per-court `CourtRange`. Seed e.g.
`{"dockets_by_internal_id": {"internal_id": {"min": 100500, "gap": 20}}}`.

### Step functions and priorities (§5)

```
dockets_by_internal_id
    └→ parse_docket_page (4)        build_docket.php?docket_type=docket
        ├→ parse_parties (3)        apinfo, listby=pty
        │   └→ parse_trial_court (2) lcinfo
        │       └→ parse_oral_arguments (2)  oralarg → ParsedData(MsAppDocket)
        └→ (per PDF) download_document (archive=True, priority 1)
                                    → ParsedData(MsAppDocument)
```

Priorities descend by depth so in-flight cases finish before new ones
start; PDF downloads ride at the archive priority (1).

### Deduplication keys (§6)

- `docket_page:<cn>` — the initial docket fetch.
- `parse_parties:<cn>` / `parse_trial_court:<cn>` / `parse_oral_arguments:<cn>`
  — the chained sub-fetches.
- `<cn>-<file_name>` — each archived PDF (colon-free, used in filenames).

### Data types

`MsAppDocket` (main, → CL `Docket`) with nested `MsAppDocketEntry` (→
`DocketEntry`), `MsAppParty` (+ `MsAppAttorney`, → `Party`/`Attorney`),
`MsAppTrialCourt` (→ `OriginatingCourtInformation`/`TrialCourtData`),
`MsAppOralArgument`. Each archived PDF is a separate top-level
`MsAppDocument` (→ `RECAPDocument`) linked back by `case_num` + `docket_number`.

## Out of Scope

- `getHanddown.php` (hand-down opinion lists) — opinions only, not full
  docket coverage; not wired.
- `listby=att` (attorney-keyed inverse of `listby=pty`) — redundant.
- Oral-argument *calendar* pages (`sc/scoa.php`, `coa/coaoa.php`) — per-case
  oral-arg links are already captured via the detail flow.
- No public email-notification subscription for anonymous users.
