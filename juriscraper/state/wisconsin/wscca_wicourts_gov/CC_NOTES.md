# Wisconsin Supreme Court & Court of Appeals (wscca.wicourts.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two courts (`wis`, `wisctapp`) sharing one case-number space; the API's
> `courtType` (`SC`/`CA`) routes each docket to its CourtListener id.
> **JSON-only** scraper — the steps decode the JSON body directly, so there
> is **no `parsers/` package** (§3.5; cf. arkansas/nevada). Runs entirely
> under Playwright (`driver_requirements = [JS_EVAL, FF_ALIKE,
> HCAP_HANDLER]`) because every `/api/...` endpoint 403s to non-browser
> clients. Model fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md):
> `court` (not `court_id`), `docket_number` (not `case_id`), `date_*` date
> naming, `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: https://wscca.wicourts.gov/case-search
- **Requires Playwright**: **Yes** — invisible hCaptcha gates the search,
  and every `/api/...` endpoint returns 403 to direct httpx clients
  (TLS-fingerprint + sec-fetch checks). All endpoints work cleanly from
  inside a Playwright Chromium/Firefox context.
- **Transport**: PureScript SPA on top of a JSON API. Search submits via
  the SPA form (captcha-gated); case detail and document downloads are
  plain JSON / PDF endpoints reachable by `page.goto(...)` inside the
  same browser context.
- **Welcome interstitial**: `/case-search` shows an "I agree" terms
  click-through. The acceptance is recorded in `localStorage`
  (`lastAgreed`) — no backend cookie. Click once on first navigation.

## Courts Covered

The site covers two court types via a single `/api/case-search` flow.
Court of Appeals additionally has four districts (mapped to a single
CourtListener ID).

| Site `courtType` | Site `districtNo` | Display Name | CourtListener ID |
|---|---|---|---|
| `SC` | n/a | Wisconsin Supreme Court | `wis` |
| `CA` | 1 | Wisconsin Court of Appeals, District 1 (Milwaukee) | `wisctapp` |
| `CA` | 2 | Wisconsin Court of Appeals, District 2 (Waukesha) | `wisctapp` |
| `CA` | 3 | Wisconsin Court of Appeals, District 3 (Wausau) | `wisctapp` |
| `CA` | 4 | Wisconsin Court of Appeals, District 4 (Madison) | `wisctapp` |

All four CA districts roll up to `wisctapp`; the district number is
preserved as case metadata (`filing_district` / `current_district`).

## Search Capabilities

The SPA search form (additional criteria expanded) supports party name,
attorney name, case number, county, case status, court type, district,
class codes, **filing date range**, and citation lookups.

**Decision-tree result**: a filing-date filter exists in the SPA, but the
search endpoint is invisible-hCaptcha-gated. The case-detail endpoint
(`/api/case/{caseNo}`) is *not* gated and returns 404 for unknown case
numbers — making speculative enumeration a clean fit without ever touching
the captcha.

**Approach (v1)**: `YearlySpeculativeRange` enumeration of the
`YYYYAP######` numbering. Wisconsin appellate cases share a single
sequence per (year, type-prefix) and `AP` (Appeal) is the dominant
prefix. Every Court-of-Appeals and Supreme-Court case threads through this
one space, so a single speculative entry covers both courts; the API's
`courtType` field tells us which CourtListener id (`wis` vs `wisctapp`)
the docket belongs to.

**Date-based search (deferred to v2).** The captcha gate plus the SPA's
lack of `name`-attributed form fields makes date-search an awkward fit for
kent's `find_form()` / `ViaFormSubmit` abstractions, and the SPA URL
parser ignores `filingDateBegin` / `filingDateEnd` deep-link params (only
`caseNumber` and `courtType` are honored).

## API Contract

- `GET /api/case/{sccaCaseNo}` (no captcha) — full case JSON; 404 for
  unknown numbers.
- `GET /api/case/{sccaCaseNo}/document/{docId}` (no captcha) — the PDF.
- The captcha-gated search endpoints (`/api/captcha/validate/search`,
  `/api/case-search/{uuid}/count`, `/api/case-search/{uuid}`) are not
  used by v1.

Date format throughout: `{"m": int, "d": int, "y": int}`. Names
throughout: `{nameL, nameF, nameM, suffix}` (any field nullable; for
businesses only `nameL` is populated).

### `/api/case/{caseNo}` JSON shape (keys consumed)

- `caseData` (object): `sccaCaseNo`, `shortCaption`, `longCaption`,
  `statusCode`, `statusDescr`, `wcisClsCode`, `wcisClsCodeDescr`,
  `dispoCode`, `dispoCodeDescr`, `dispoDate`, `filingDate`, `courtType`,
  `districtNo`, `filingDistrictNo`, `caseSuffix`, `casePanelSize`,
  `countyName`, `countyNo`, `isConfidential`.
- `parties` (list): each `{name, partyTypes, partySeqNo, attorneys}`.
- `pastEvents` / `upcomingEvents` (lists): the docket / register of
  actions; both folded into `WiDocket.entries` as `WiDocketEntry` rows
  (per the kent convention — future-calendar items are docket entries,
  distinguished by `is_future`, not a separate `ScheduledHearing` type).
- `documents` (list): each `{docId, docName, eventDescr, eventCode,
  eventSeqNo, sccaCaseNo, pages, docStampDate}`.
- `ccCaseData` (list): related circuit-court cases.
- `citnData` (list): reporter citations.

## Docket Number Format

`YYYY` + 2-letter court-type code + 6-digit sequence, e.g.
`2022AP000001`. The display form (`22AP1`) is normalized server-side; we
always pass the canonical form to `/api/case/{caseNo}`.

## Scraper Architecture

### Driver

`driver_requirements = [JS_EVAL, FF_ALIKE, HCAP_HANDLER]`. The whole
scraper is Playwright; per-step driver requirements are not used.

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_number(docket_number)` | `YearlySpeculativeRange` | Speculative enumeration of `YYYYAP######`. **Multi-court speculative**: takes ONLY the speculative param (§4) — the owning court is read per-response from `courtType`, never seeded. One seed per active year. |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Direct fetch of one known canonical case number. |

`dockets_by_number` seed shape::

    [{"dockets_by_number": {"docket_number":
        {"year": 2025, "min": 1, "soft_max": 4000, "gap": 20}}}]

The seed_params author owns year rollover (one seed per active year).

#### Other type prefixes (deferred)

The site exposes additional 2-letter prefixes (`XX`, `BC`, `AD`, `AM`,
`OK`, `PM`, `WW`, `ZZ`, ...) for non-standard case types. Volume is low
and they share the same `/api/case/{caseNo}` endpoint, so they can be
added as additional entries (each delegating to `_build_case_request`).

### Step functions and priorities (§5)

```
docket_by_number / dockets_by_number
  → parse_case_detail (2)   # GET /api/case/{caseNo} (JSON in body)
                            # 4xx → speculation miss (auto-handled);
                            # 200 → parse JSON, build WiDocket, yield
                            #   ParsedData + archive Requests per doc
  → handle_document         # archive=True (auto priority 1) → emits
                            #   WiDownloadedDocument with local_path
```

Priorities descend by depth; downloads ride at the auto-assigned 1.

### Deduplication keys (§6)

- `docket_by_number:<docket_number>` — the case-detail fetch (dedups the
  same canonical number across direct and speculative entries).
- `<docket_number>-<doc_id>-<doc_name>` — each archive download
  (colon-free, since this becomes part of a filename).

### Soft-404 handling

`/api/case/{caseNo}` returns HTTP 404 for unknown numbers. The
speculation driver auto-converts 4xx into miss outcomes; no
`actually_successful` override is needed.

### Models (see `models.py`)

`WiDocket` (main → CL `Docket`) with nested `WiParty` (+ `WiAttorney`),
`WiDocketEntry`, `WiDocument`, `WiCircuitCourtCase`, `WiCitation`; plus a
separate `WiDownloadedDocument` for archived files (join back via
`court` + `docket_number` + `doc_id`). `WiDocket.entries` carries both
past and upcoming events (no separate hearing type).

### Known gaps

- Briefs/petitions for confidential case types are not exposed by the
  site (the JSON `documents` array omits them). No scraper-side workaround.
- Pre-2009 non-eFiled briefs are scanned and added over time; coverage is
  incomplete by design.
- `court_id` on `docket_by_number` is a vestigial display hint only — the
  authoritative court is read from the API's `courtType`. **Needs human
  review** if the single-record entry should instead drop the arg (the
  §4 single-record shape mandates `court_id: str`, so it is kept).
