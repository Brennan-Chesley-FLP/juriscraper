# NYSCEF appellate cases (iapps.courts.state.ny.us/nyscef) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Migrated from the pre-v0.1.0 pattern (inline parsing + an `xsds/`
> xsd-validation directory) to the current standard: HTML extraction now lives
> in the `parsers/` package (§9, three `JKentParser` subclasses), and the
> `xsds/` directory was **deleted** — its page-structure intent is now carried
> by `min_count`/`max_count` count assertions in the parsers and by the
> pydantic models. The site returns 403 to plain HTTP and presents an
> hCaptcha challenge, so it runs under Playwright
> (`driver_requirements = [JS_EVAL, FF_ALIKE, HCAP_HANDLER]`). Model fields
> follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` is the CL court id
> (the display name is kept in `court_name_raw`), `docket_number` (not
> `case_number`), `date_*` date naming, `CleanString`/`HarmonizedCaseName`
> cleaning from `juriscraper.state.common_models`.

## Site Overview

- **Base URL**: `https://iapps.courts.state.ny.us/nyscef`
- **Requires Playwright**: Yes — 403 for non-browser requests + hCaptcha.

Three pages per case: Search Results (`table.NewSearchResults`) → Case Detail
(`CaseDetails?docketId=...`) → Document List
(`DocumentList?docketId=...&display=all`). Cases are addressed internally by an
opaque base64 `docketId`; documents by a base64 `docIndex` (`ViewDocument`) or
`docId` (`ConfirmationNotice`).

## Courts Covered

| Site name | CourtListener ID | `txtCounty` value |
|-----------|------------------|-------------------|
| Appellate Division - 1st Dept | `nyappd1` | 95 |
| Appellate Division - 2nd Dept | `nyappd2` | 96 |
| Appellate Division - 3rd Dept | `nyappd3` | 97 |
| Appellate Division - 4th Dept | `nyappd4` | 98 |
| NYS Court of Claims | `nysctcl` | 99 |

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Single-record direct lookup by the `YYYY-NNNNN` case number. |
| `dockets_by_filing_date(court_ids, date_range)` | `set[str]`, `DateRange` | For each requested court, search by filing-date window. The site searches one county at a time with no "all case numbers" option, so each (court, window) is covered by 9 searches — one per leading digit 1-9 — because every non-zero case number contains a digit 1-9. |

The filing-date entry loops over `court_ids`, mapping each CL id to its
`txtCounty` value (`COURT_TO_COUNTY`) and carrying the CL `court` id forward
in `accumulated_data` (never re-read from params, §2).

### Step functions and priorities (§5)

```
docket_by_number        → parse_search_page (5) → parse_search_results (4)
                              → parse_case_detail (3) → parse_document_list (2)
                                  → ParsedData + downloads (1)

dockets_by_filing_date  → (9× per court) fill_date_search_form (5)
                              → parse_date_search_results (4)  ──(pagination)──┐
                              │      └→ parse_case_detail (3) (shared)         │
                              └──────────────────────────────────────────────┘
```

Priorities descend by depth (5 → 4 → 3 → 2) so in-flight cases finish before
new searches start; `archive=True` downloads auto-assign priority 1.

### Parsers (§9)

- `SearchResultsParser` — one partial `NYSCEFCase` per `NewSearchResults`
  row (docket_number, court, `docketId`, short caption, case type, eFiling
  status, received date). Used by both the case-number and date results steps.
- `CaseDetailParser` — full caption, the court-of-original-instance block
  (index, court name, judge, the appeal/notice dates, requested argument
  time), and the Petitioners/Respondents party tables with attorney reps.
- `DocumentListParser` — one `NYSCEFDocketEntry` per documents-table row
  (entry number, type, description, filer, filed/received dates, status,
  `ViewDocument` / `ConfirmationNotice` URLs).

`_common.py` holds `parse_date_mdy`, `extract_query_param` (docketId /
docIndex / docId), `split_party_name_role`, `parse_attorney_reps`, and
`parse_filed_by_cell`.

### Deduplication keys (§6)

`<continuation-or-record>:<args>` format, no court-id prefix:
`parse_search_page:<dn>`, `search_results:<dn>`, `case_detail:<docketId>`,
`document_list:<docketId>`, and `document:<docketId>:<entry_number>:<docIndex>`
for each archive download (colon-free index segment is the opaque base64 id).
The date-search seeds and pagination follows use `SkipDeduplicationCheck()`
(non-idempotent search posts / page walks); per-case dedup is enforced by the
`case_detail:<docketId>` key so overlapping digit searches visit each case
once.

### Data types

`NYSCEFCase` (main, → CL `Docket` + `OriginatingCourtInformation`) with nested
`NYSCEFParty` (→ `Party`/`PartyType`) carrying `NYSCEFAttorneyRep`
(→ `Attorney`/`Role`), and `NYSCEFDocketEntry` (→ `DocketEntry`). Downloaded
files are emitted as `NYSCEFDownloadedDocument` (→ `RECAPDocument`), joined
back to the case by `iapps_internal_docket_id`.

## Notes / human review

- `court` resolution: the filing-date flow pins the CL court id from the
  entry; the docket-number flow resolves it from the result-row court name via
  `COURT_NAME_TO_ID`. If the site renders a court name not in that map,
  `court` falls back to the raw name (kept verbatim in `court_name_raw`) —
  worth re-checking the exact strings against a live page.
- `case_name` uses `HarmonizedCaseName`; the site's full caption is fed
  through `harmonize`. Spot-check a few captions if exact fidelity matters.
