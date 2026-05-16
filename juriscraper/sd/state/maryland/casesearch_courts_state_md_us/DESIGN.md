# Maryland Judiciary Case Search & Record Portal Scraper Design

## Site Overview

- **Base URL**: https://casesearch.courts.state.md.us/casesearch/inquiry-search
- **Backend APIs** (JSON):
  - Search list: `POST /api-caselist/v1/cases`
  - Case detail: `GET /api-casedetails/v1/public/cases/{caseId}`
- **Requires Playwright**: **Yes** — DataDome bot protection (`api-js.datadome.co`).
  Direct curl returns HTTP 403 with a captcha-delivery URL. Playwright handles
  the DataDome JS challenge transparently.

The portal also serves Circuit Court, District Court, and Appellate Court
records, but this scraper only covers the appellate courts:

- Appellate Court of Maryland (formerly Court of Special Appeals of Maryland)
- Supreme Court of Maryland (formerly Court of Appeals of Maryland)

## Courts Covered

| Site ID prefix | Display Name                   | CourtListener ID |
|----------------|--------------------------------|------------------|
| ACM            | Appellate Court of Maryland    | `mdctspecapp`    |
| SCM            | Supreme Court of Maryland      | `md`             |

The two courts were renamed by constitutional amendment in 2022.
CourtListener still uses the historical names in its IDs.

## Search Capabilities

The portal has three search forms in the UI:

| Rank | Mode                 | Notes                                       |
|------|----------------------|---------------------------------------------|
| 1    | Case Number Search   | Direct lookup, redirects to detail page.    |
| 2    | Party Name Search    | Last Name required.                         |
| 3    | Advanced Search      | Last Name required + filters.               |

### Date-based search

The Advanced Search has a `Filing Date` range, but **Last Name is required**,
so it cannot be used to enumerate all cases for a date window without
iterating through name probes. The list API (`/api-caselist/v1/cases`)
mirrors this requirement.

### Case Number search

Hitting `inquiry-search` with a case number redirects to
`/casesearch/case-detail-page?caseId={ID}`. The page calls
`GET /api-casedetails/v1/public/cases/{caseId}` and gets a clean JSON document
containing all the case data (parties, attorneys, hearings, docket entries,
judgment events, cross-references). Invalid case IDs return **HTTP 400** with
a JSON body explaining the case is unavailable.

**Recommended approach**: speculative entry by case ID. Each (court, type, year)
gets its own `SpeculativeRange` entry so the driver advances each prefix
independently.

## Docket Number Formats

Site uses pattern: `{COURT3}-{TYPE3}-{NNNN}-{YYYY}`. The case-detail URL
strips the dashes: `caseId={COURT3}{TYPE3}{NNNN}{YYYY}`.

Observed prefixes (from a Smith search across 2025):

| Prefix    | Court | Type description                       | ~Volume/yr (2024) |
|-----------|-------|----------------------------------------|-------------------|
| ACM-REG   | ACM   | Regular appeal                         | ~2520             |
| ACM-ALA   | ACM   | Application for Leave to Appeal        | ~1100+            |
| SCM-PET   | SCM   | Petition for Writ of Certiorari        | ~450              |
| SCM-MISC  | SCM   | Miscellaneous                          | low (~50?)        |
| SCM-REG   | SCM   | Regular Supreme Court matter           | low (~20?)        |

Numbers reset every year and are sequential. ACM-REG-2024 confirmed up to
2520 (2550 returns 400). 2025 numbers were observed up to 2254 (filed
12/19/2025), so the year-end max is around 2270–2350.

## Data Available

### Case Summary (`caseDetail`)

| Field         | Source                                        |
|---------------|-----------------------------------------------|
| case_number   | `caseNumber` (e.g. "ACM-REG-2487-2024")       |
| internal_id   | `internalId` (numeric)                        |
| court_system  | `courtSystem`                                 |
| case_category | `caseCategory` ("AP", "CV", etc.)             |
| case_title    | `caseTitle`                                   |
| case_type     | `caseType` ("Appeal of Criminal Case", etc.)  |
| filed_date    | `filedDate` (MM/DD/YYYY)                      |
| case_status   | `caseStatus.caseStatusType` + `caseStatus.date` |

### Docket Entries (`caseEventInfo[]`)

| Field             | Source                            |
|-------------------|-----------------------------------|
| file_date         | `fileDate` (MM/DD/YYYY)           |
| created_date      | `createdDate` (ISO timestamp)     |
| document_name     | `documentName`                    |
| internal_event_id | `internalEventID`                 |
| documents         | `eventDocuments[]` (always empty) |

### Hearings (`hearing[]`)

| Field             | Source                         |
|-------------------|--------------------------------|
| event_type        | `eventType`                    |
| event_date        | `eventDate`                    |
| event_time        | `eventTime`                    |
| location          | `location`                     |
| result            | `result` (optional, e.g. "Cancelled - Reason: ...") |
| hearing_documents | `hearingDocuments[]` (empty)   |

### Judgments (`judgmentEventInfo[]`)

| Field           | Source                                |
|-----------------|---------------------------------------|
| judgment_event  | `judgmentEventType` (e.g. "Denied")   |
| issue_date      | `issueDate`                           |
| comments        | `comment[]` (list of strings)         |

### Parties & Attorneys (`involvedParties[]`)

Each party has:
- `partyType` ("Appellant", "Appellee", "Petitioner", etc.)
- `partyTypeCode`
- `partyName`
- `involvedPartyAddresses[]` (optional)
- `attorneyInfo[]` — name, appearance/removal date, address

### Related Cases / Cross-References

- `relatedCases[]`: linked case numbers and reasons
- `caseCrossReferences[]`: appellate / circuit / district court cross-refs
  with the original case number from the trial court

### Documents

The JSON exposes `eventDocuments[]` and `hearingDocuments[]` arrays, but in
every case sampled (REG, PET, ALA) they were empty. Document download links
are not surfaced through this portal — the public site is metadata-only. We
retain the structure for future-compat but omit a `Document` data class until
populated examples are seen.

## Email Notifications

Not visible to anonymous users. The "Sign In / Register" flow is required to
configure case alerts; out of scope here.

## Oral Arguments Calendar

There is no public oral-arguments calendar on this portal. Hearings are
exposed only on individual case pages (`hearing[]`). Hearings will be
captured as part of the docket payload, not as a separate entry.

## Bot Protection Notes

- **DataDome** challenge served from `api-js.datadome.co`. A successful page
  load executes JS that posts to the DataDome endpoint and gets a
  `datadome` cookie. After that, the site's REST APIs become callable.
- Playwright handles this transparently as long as the browser fingerprint
  looks real (FF_ALIKE / CHROME_ALIKE both work in our tests).
- The detail API returns **HTTP 400** for non-existent case numbers (with a
  JSON error body) — not a soft-404 page. We add `400` to
  `SUCCESSFUL_HTTP_CODES` and override `fails_successfully` so that 400 is
  treated as a clean speculative miss instead of a fail-fast error.

## Scraper Architecture

### Entry Points

One speculative entry per `(court, type)` combination — the driver advances
each independently. We use `YearlySpeculativeRange` (year + sequential
number) because case numbers reset each calendar year.

| Method                  | Param type              | Court ID    | Prefix    |
|-------------------------|-------------------------|-------------|-----------|
| fetch_acm_reg_docket    | YearlySpeculativeRange  | mdctspecapp | ACM-REG   |
| fetch_acm_ala_docket    | YearlySpeculativeRange  | mdctspecapp | ACM-ALA   |
| fetch_scm_pet_docket    | YearlySpeculativeRange  | md          | SCM-PET   |
| fetch_scm_misc_docket   | YearlySpeculativeRange  | md          | SCM-MISC  |
| fetch_scm_reg_docket    | YearlySpeculativeRange  | md          | SCM-REG   |

Each builds the case ID `{COURT3}{TYPE3}{NNNN}{YYYY}` and yields a single
`GET /api-casedetails/v1/public/cases/{caseId}` request.

### Step Functions

```
fetch_*_docket → parse_case_detail (yields ParsedData)
```

The detail API returns the entire docket in one JSON payload, so the flow
is just two functions per case.

### Models (see models.py)

- `MdAppellateDocketEntry` — one row of `caseEventInfo`
- `MdAppellateHearing` — one row of `hearing`
- `MdAppellateJudgment` — one row of `judgmentEventInfo`
- `MdAppellateAttorney` — one attorney record
- `MdAppellateParty` — one party + nested attorneys
- `MdAppellateRelatedCase` — one row of `relatedCases` / `caseCrossReferences`
- `MdAppellateDocket` — top-level result
