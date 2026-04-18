# Nevada Appellate Courts Scraper Design

Scrapes docket data from the Nevada Supreme Court and Nevada Court of Appeals
C-Track CMS at caseinfo.nvsupremecourt.us.

## Site Overview

- **Base URL**: https://caseinfo.nvsupremecourt.us/
- **Case view URL**: `/public/caseView.do?csIID=<internal_id>`
- **Combined case view URL**: `/public/caseView.do?csIID=<internal_id>&combined=true`
- **Case search URL**: `/public/caseSearch.do`
- **Platform**: Thomson Reuters C-Track (server-rendered HTML, no SPA)
- **Requires Playwright**: No — pages return full server-rendered HTML.

## Courts Covered

| Site Court Name | Docket Number Format | CourtListener ID |
|-----------------|----------------------|-----------------|
| Supreme Court | `#####` (5 digits, e.g., `92415`) | `nev` |
| Court of Appeals | `#####-COA` (e.g., `92415-COA`) | `nevapp` |

The courts share one CMS and one internal ID sequence (`csIID`). A case
transferred between courts produces a new `csIID`-keyed record linked via the
"Related Case(s)" row.

## Internal ID (csIID) Observations

Observed csIIDs are continuous sequential integers across both courts:

| Site docket # | csIID  | Filed      |
|---------------|--------|-----------|
| 91318         | 72978  | 2025-09-18 |
| 91334         | 72994  | 2025-09-22 |
| 91778         | 73619  | 2025-12-16 |
| 91995         | 73904  | 2026-01-23 |
| 92145         | 74124  | 2026-02-20 |
| 92398         | 74469  | 2026-04-01 |
| 92415 (SC)    | 74486  | 2026-04-03 |
| 92415-COA     | 74544  | 2026-04-13 |
| 92470         | 74595  | 2026-04-15 |

- `csIID=1` returns a real case (case #34599) — sequence starts at 1.
- Highest observed as of 2026-04-16: `74595`.
- Adjacent csIIDs observed: 74116 → 74124 (gap of 8). Gaps appear small.
- Invalid/out-of-range csIIDs return a "Security Error" page with the text
  "You do not have rights to view this case" (HTTP 200 soft-404).

## Search Capabilities

The site offers:

1. **Case search** (`/public/caseSearch.do`): fields for Case No., Caption
   Contains, Court (All / Court of Appeals / Supreme Court), Exclude Closed
   checkbox. No date-range search.
2. **Participant search** (`/public/publicActorSearch.do`): by party/attorney
   name.

**Recommended approach**: Speculative enumeration on `csIID` via
`fetch_by_internal_id`. The URL `caseView.do?csIID=<N>` is the most stable
entry, and csIIDs increment sequentially across both courts.

## Two-Page Fetch Pattern

Each case has two views:

1. **Original view** (`caseView.do?csIID=<N>`) — shows only the docket entries
   that occurred while this csIID owned the case (entries marked with this
   court's suffix, e.g. `(COA)` or `(SC)`).
2. **Combined Case View** (`caseView.do?csIID=<N>&combined=true`) — adds the
   docket entries from the related case (the other court's proceedings).
   Visible via the "Combined Case View" link at the bottom of the original
   page, or "Original Case View" link from the combined page.

Only cases with a "Related Case(s)" row have combined entries to fetch; for
single-court cases the combined link still works but yields the same entries.

Each docket entry scraped from the combined-only page is tagged with
`combined_only=True` to mark entries that do not appear in the primary case's
docket.

## Data Available — Case View Page

### Case Information Header (key/value rows)

| Field | Notes |
|-------|-------|
| Case Number | Shown as `92415-COA` in header; parsed from URL or `<h2>`-equivalent. |
| Short Caption | e.g., `ESPARZA VS. DIST. CT. (SUPERIOR BUILDERS, INC) (CIVIL)` |
| Court | `Supreme Court`, `Court of Appeals`, or combined form (`Court of Appeals & Supreme Court`) |
| Related Case(s) | Zero or more `<a>` links with the related case number (e.g., `92415`) linking to `/public/caseView.do?csIID=<related_csIID>`. |
| Lower Court Case(s) | Free-text; often `Clark Co. - Eighth Judicial District - A912263`. |
| Classification | e.g., `Original Proceeding - Civil - Mandamus/Prohibition` |
| Disqualifications | Free-text; may be blank. |
| Case Status | e.g., `Transferred from Supreme Court`, `Briefing in Progress`. |
| Replacement | Free-text; may be blank. |
| Panel Assigned | e.g., `Panel`, or blank. |
| To SP/Judge | Free-text; may be blank. |
| SP Status | Free-text; may be blank. |
| Oral Argument | Free-text; may be blank. |
| Oral Argument Location | Free-text; may be blank. |
| Submission Date | Free-text; may be blank. |
| How Submitted | Free-text; may be blank. |

### Party Information (collapsed table; always present in HTML)

Rows with columns: Role | Party Name | Represented By.

- **Role**: e.g., `Petitioner`, `Respondent`, `Real Party in Interest`.
- **Party Name**: free-text.
- **Represented By**: one or more attorney-with-firm entries like
  `Troy Domina (Peel Brimley LLP/Henderson)`, separated by line breaks.

### Docket Entries

Table columns: Date | Type | Description | Pending? | Document.

- **Date**: `MM/DD/YYYY`.
- **Type**: e.g., `Petition/Writ`, `Appendix`, `Case Status Update`,
  `Filing Fee`, `Notice/Outgoing`.
- **Description**: free-text. Suffix `(SC)` or `(COA)` tags which court the
  entry was filed in.
- **Pending?**: `Y` or blank.
- **Document**: optional link cell; displays an OnBase document number like
  `26-16662` linking to `/document/view.do?csNameID=<N>&csIID=<N>&deLinkID=<D>&onBaseDocumentNumber=<doc#>`.

## Bot Protection

None observed. Pages load without JS, forms use standard POST, no hidden
tokens, no CloudFlare challenges.

## Oral Arguments Calendar

No separate calendar URL was located during reconnaissance. Oral arguments
are surfaced as per-case fields only.

## Email Notifications

Not observed on case pages.

## Scraper Architecture

### Entry Point

```python
# highest_observed=74595, largest_observed_gap=20 (2026-04-16)
@entry(NvDocket)
def fetch_by_internal_id(self, rid: SpeculativeRange) -> Request:
    """Fetch a Nevada appellate docket by internal csIID."""
```

Uses `SpeculativeRange` (Speculative protocol) so the driver drives the
`rid.number` enumeration. Seed via `seed_params`, e.g.:

```json
{"fetch_by_internal_id": {"rid": {"number": 1, "gap": 20}}}
```

One entry covers both courts because the site indexes Supreme Court and Court
of Appeals dockets by a single shared csIID sequence. The court is derived
from the docket number suffix (`-COA` → `nevapp`; otherwise `nev`) at parse
time.

### Step Flow

```
fetch_by_internal_id
  → parse_case_view              (original view: header + parties + docket)
    → download_document (archive, once per entry with a doc link)
    → parse_combined_view        (combined=true: merges related case entries)
      → download_document (archive, once per new combined-only entry)
      → yields ParsedData(NvDocket)
```

`parse_case_view`:
- Extracts header fields, parties, and docket entries (`combined_only=False`).
- Yields an archive Request for each entry with a document URL; continuation
  is `download_document`.
- Collects the set of (date, type, description) triples observed on the
  original page to dedupe against combined-view entries.
- Always yields a follow-on request for the `&combined=true` URL.

`parse_combined_view`:
- Extracts the docket-entries table again.
- For each entry not in the set captured on the original view, marks it as
  `combined_only=True`, appends to the same docket, and yields an archive
  Request for its document if present.
- Yields `ParsedData(docket)`.

`download_document`:
- Reads csIID, document number, URL, date, type, and description from
  `accumulated_data`.
- Yields `ParsedData(NvDocument)` with `local_path` set by the driver.

### Document Archives

Each docket-entry document (OnBase link like `26-16662`) is archived as a PDF
via `Request(archive=True, expected_type="pdf", ...)`. The dedup key is
`nv-doc-<document_number>` so the same document is never downloaded twice,
even when two related cases surface it through their combined views.

The parent csIID is carried in `accumulated_data["internal_id"]` so the
resulting `NvDocument` records can be joined back to their `NvDocket`
downstream.

### Soft-404 and Unavailable Cases

`caseView.do?csIID=<id>` renders page title `Security Error` and body text
`You do not have rights to view this case` for two overlapping cases:

- **Sealed / non-public cases** — csIIDs that exist but are not publicly
  viewable (e.g. `csIID=278`).
- **Truly-invalid csIIDs** — out-of-range values.

The site response is identical in both cases, so the scraper cannot
distinguish them. Behavior:

- `fails_successfully()` returns `False` on this marker — the driver's
  speculation tracker counts it as a miss and terminates trailing-edge
  extension after `gap` consecutive failures.
- `parse_case_view` yields a single `NvUnavailableCase(internal_id=csIID)`
  for every such page and returns without fetching the combined view.
  IDs below the current `highest_successful_id` capture real sealed
  cases; truly-invalid trailing IDs are bounded by the gap window.

### Deduplication

Each entry Request uses `deduplication_key=str(csIID)` so that the same csIID
is not visited twice when overlapping speculation runs.

### Document Downloads

Docket entry document links are captured as URL strings on each
`NvDocketEntry.document_url`. Archiving is intentionally deferred — the
current scope is metadata only.

## Models

- `NvParty` — role, name, representation (list of attorneys).
- `NvAttorney` — name, firm (if extractable).
- `NvDocketEntry` — date, type, description, pending flag, document fields,
  `combined_only: bool`.
- `NvRelatedCase` — docket number, csIID link.
- `NvDocket` — main docket output, aggregates everything above.
- `NvDocument` — separate top-level record per archived document; carries
  `internal_id` (csIID) for joining back to the parent docket.
- `NvUnavailableCase` — separate top-level record emitted whenever the site
  renders the "rights to view" error for a csIID; carries `internal_id`
  so downstream jobs can track non-viewable cases. (Sealed/non-public
  cases and truly-invalid csIIDs are indistinguishable on this site.)
