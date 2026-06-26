# Maryland Judiciary Case Search (casesearch.courts.state.md.us) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two courts (`md` Supreme, `mdctspecapp` Appellate) on one portal.
> JSON-only public API behind DataDome bot protection, so the scraper runs
> under a browser (`JS_EVAL` + `FF_ALIKE`). Addressing is speculative
> case-number enumeration against the case-detail JSON API. JSON extraction
> lives in the `parsers/` package (§9, `CaseDetailParser`); steps keep
> navigation (request building, the entry-point stamp). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `docket_number` (+ `docket_number_raw`), `date_*` naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `https://casesearch.courts.state.md.us/casesearch/inquiry-search`
- **Backend** (JSON):
  - Case detail: `GET /api-casedetails/v1/public/cases/{caseId}`
  - Search list: `POST /api-caselist/v1/cases` (requires Last Name; unused)
- **Requires Playwright**: **Yes** — DataDome (`api-js.datadome.co`). Direct
  curl returns HTTP 403 with a captcha-delivery URL; Playwright handles the
  DataDome JS challenge transparently as long as the fingerprint looks real.

The portal also serves Circuit, District, and Appellate Court records; this
scraper covers only the two appellate courts.

## Courts Covered

| Site prefix | Display name                | CourtListener ID |
|-------------|-----------------------------|------------------|
| ACM         | Appellate Court of Maryland | `mdctspecapp`    |
| SCM         | Supreme Court of Maryland   | `md`             |

Both courts were renamed by constitutional amendment in 2022 (formerly the
Court of Special Appeals / Court of Appeals of Maryland); CourtListener still
keys them by the historical IDs.

## Search Capabilities

The portal's UI has Case Number, Party Name, and Advanced search forms. Party
Name and Advanced both **require a Last Name**, and the Advanced "Filing Date"
range can't be used to enumerate a date window without iterating name probes.
The list API mirrors that requirement. So there is no clean date-addressed
enumeration; we speculate by case number instead.

Hitting `inquiry-search` with a case number redirects to
`case-detail-page?caseId={ID}`, which calls
`GET /api-casedetails/v1/public/cases/{caseId}` and returns the full case as
JSON. Invalid case IDs return **HTTP 400** with a JSON error body (not a
soft-404 page).

## Docket Number Format

`{COURT3}-{TYPE3}-{NNNN}-{YYYY}`; the detail URL strips the dashes:
`caseId={COURT3}{TYPE3}{NNNN}{YYYY}`. Numbers reset each calendar year and are
sequential.

Observed prefixes (from a name search across 2025):

| Prefix    | Court | Type description                | ~Volume/yr (2024) |
|-----------|-------|---------------------------------|-------------------|
| ACM-REG   | ACM   | Regular appeal                  | ~2520             |
| ACM-ALA   | ACM   | Application for Leave to Appeal  | ~1100+            |
| SCM-PET   | SCM   | Petition for Writ of Certiorari | ~450              |
| SCM-MISC  | SCM   | Miscellaneous                   | low (~50?)        |
| SCM-REG   | SCM   | Regular Supreme Court matter    | low (~20?)        |

ACM-REG-2024 confirmed up to 2520 (2550 → 400). 2025 observed to ~2254
(filed 12/19/2025), so year-end max is around 2270–2350.

## Data Available

The detail payload (`caseDetail`) carries the whole docket:

- **Header scalars**: `caseNumber` → `docket_number`(+`_raw`), `caseTitle` →
  `case_name`, `filedDate` → `date_filed`, `internalId`, `courtSystem`,
  `caseCategory`, `caseType`, `caseStatus.caseStatusType`/`.date`.
- **`caseEventInfo[]`** → `MdAppellateDocketEntry` (register of actions →
  CL `DocketEntry`).
- **`hearing[]`** → `MdAppellateHearing` (scheduled/past hearings; modelled
  in the docket payload, not as a separate record type).
- **`judgmentEventInfo[]`** → `MdAppellateJudgment`.
- **`involvedParties[]`** → `MdAppellateParty` (+ `MdAppellateAttorney`,
  `MdAppellateAddress`).
- **`relatedCases[]`** / **`caseCrossReferences[]`** →
  `MdAppellateRelatedCase`.

### Documents

The payload exposes `eventDocuments[]` and `hearingDocuments[]` arrays, but in
every sampled case (REG, PET, ALA) they were empty — the public portal is
metadata-only. No `Document`/archive model is implemented until populated
examples appear.

## Out of Scope

- No public oral-arguments calendar; hearings are captured per-case via
  `hearing[]`.
- Email/case-alert notifications require sign-in; anonymous-only here.

## Scraper Architecture

### Entry point (§4)

One speculative `@entry`, `dockets_by_number(case_id: MdCaseRange)`, covers
every `(court, case-type)` prefix. A speculative entry is dispatched with only
its speculative param, so the prefix+year ride on `MdCaseRange` (a
`YearlySpeculativeRange` subclass carrying `court3`/`type3`); seed one range
per `(court3, type3, year)`. This replaces the five per-prefix `fetch_*`
entries of the pre-migration scraper (§4 "court carried in the speculative
param" shape). The CL `court` id is derived from the prefix.

For a full backfill, seed each prefix across every year of interest.

### Step functions & priorities (§5)

```
dockets_by_number → parse_case_detail (default priority) → ParsedData
```

The detail API returns the whole docket in one payload, so it's a single step.
No downloads (metadata-only site), so nothing at priority 0–1.

### Deduplication keys (§6)

- `case_detail:<case_id_param>` — each case-detail fetch.

### HTTP 400 = speculative miss (§10)

`HTTP_CODE_TYPES = {400: SUCCESSFUL}` reclassifies the detail API's
"case not found" 400 from the default PERSISTENT (fail-fast) to SUCCESSFUL, so
the body reaches `parse_case_detail`. `actually_successful` returns `True`, and
`parse_case_detail` yields nothing when the payload has no `caseDetail` block —
which the speculation driver records as a normal miss.

### Data types

`MdAppellateDocket` (→ CL `Docket`) with nested `MdAppellateDocketEntry`,
`MdAppellateHearing`, `MdAppellateJudgment`, `MdAppellateParty` (+
`MdAppellateAttorney`, `MdAppellateAddress`), and `MdAppellateRelatedCase`
(used for both `relatedCases` and `caseCrossReferences`).

### Parsers note

The site is JSON-only, so `CaseDetailParser` operates on the decoded `dict`
rather than a `PageElement`. `JKentParser[T]` (§9) is bound to the HTML
`PageElement` API, so it doesn't fit a JSON feed; the parser still satisfies
the parts of §9 that matter — it lives under `parsers/`, keeps extraction out
of the steps, returns `DeferredValidation` records, and is exercisable offline
via `CaseDetailParser.from_json(payload)`.
