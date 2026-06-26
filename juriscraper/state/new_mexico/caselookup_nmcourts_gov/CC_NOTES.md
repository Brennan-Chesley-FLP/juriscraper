# New Mexico Case Lookup (caselookup.nmcourts.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Two appellate courts (`nm`, `nmctapp`). Plain-HTTP Apache Tapestry site
> gated by a disclaimer form: a per-case lookup is GET `/caselookup/` (seed
> session, get disclaimer-or-welcome) → POST disclaimer accept (first call
> only) → GET search form → POST case-number search → case-detail page. The
> `JSESSIONID` cookie carries the disclaimer-accepted state across the run,
> so all calls after the first skip the disclaimer POST. Runs plain HTTP
> (`driver_requirements = []`). HTML extraction lives in the `parsers/`
> package (§9, `CaseDetailParser`); steps keep navigation (disclaimer,
> search-form fetch, search POST). Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (CL court-id string,
> not `court_id`), `docket_number` (not `case_number`/`docket_id`), `date_*`
> date naming, `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: `https://caselookup.nmcourts.gov/caselookup/`
- **Backend**: Apache Tapestry 4.1.3 (server-rendered HTML, JSP-style).
- **Requires Playwright**: No — pure httpx works once the disclaimer flow is
  followed.
- **Transport**: HTML form (POST) — single endpoint `/caselookup/app` with
  `component`/`page` body params dispatching to different handlers.

## Courts Covered

This scraper targets the two appellate courts. The same site also covers
District / Magistrate / Metropolitan / Municipal trial courts but they are
out of scope here.

| Site Court Type | Court Location | Case Category | Display Name | CourtListener ID |
|---|---|---|---|---|
| `S` | `1` | `SC` | New Mexico Supreme Court | `nm` |
| `A` | `1` | `CA` | New Mexico Court of Appeals | `nmctapp` |

The `Court Type` dropdown on the site's Name Search form *only* offers
trial-court types (D / M / T / U) — the Supreme Court and Court of Appeals
are reachable solely via the Case Number Search.

## Search Capabilities

The Case Number Search form posts four components — `courtType`,
`courtLocation`, `caseCategory`, `caseNumber` — to `/caselookup/app`. There
is no date-range filter, no party-name filter covering the appellate courts,
and no listing endpoint that enumerates appellate cases. Searches by exact
case number return either the case-detail page (if the case exists) or a "No
results found" page.

**Decision-tree result**: no date filter → no usable listing → speculative
entry on case numbers is the only viable path.

## Docket Number Formats

Both appellate courts use `{TYPE}-{LOC}-{CATEGORY}-{N}` where the trailing
`N` is a continuous, monotonically-increasing integer.

| Court | Pattern | Padding | Observed range |
|---|---|---|---|
| NMSC | `S-1-SC-{N}` | None — raw integer; `1`, `100`, `39473` all accepted | low ~1 to ~41000+ |
| NMCA | `A-1-CA-{N}` | None — raw integer | low ~1 to ~41500+ |

**Padding** is *not* used by the form (`caseNumber=1` / `100` / `39473` all
return their case detail without zero-padding). The numbering is **not**
year-partitioned (one global sequence per court), so `SpeculativeRange`
(continuous integer), carried inside `NmCourtRange`, is the appropriate
parameter type — *not* `YearlySpeculativeRange`.

Pre-format-rollout cases (1990s comma-formatted numbers like `23,321`) don't
fit this format and are out of scope.

## Data Available

The case-detail page renders the register of actions in plain HTML tables;
each section is its own `<table>` whose first `<tr>` is a single-cell
heading. `CaseDetailParser` extracts:

- **Case Detail** (summary row): `docket_number`, `current_judge`,
  `date_filed`, `court_name` (uppercase court name), plus `case_name` from
  the page `<h2>` heading.
- **Parties to this Case**: one `NmParty` per row (party_type,
  party_description, party_number, name).
- **Hearings for this Case**: folded into `entries` with
  `entry_kind="hearing"` (date_filed, hearing_time, description,
  hearing_judge, court, court_room). Per project convention,
  future-calendar / scheduled-hearing items are docket entries, not a
  parallel data type.
- **Register of Actions Activity**: folded into `entries` with
  `entry_kind="action"` (date_filed, description, event_result, party_type,
  party_number, amount). 2-cell sub-rows carrying free text (brief/motion
  title) are appended to the preceding entry's `notes`.
- **Judge Assignment History**: `NmJudgeAssignment` rows.

### Documents

**None.** The Register of Actions lists every filing's metadata but provides
no download links. `NmDocketEntry.document_url` exists for forward
compatibility but is always `None`.

## Bot Protection / Session Notes

- **Disclaimer gate**: every fresh `JSESSIONID` must POST the
  `disclaimerForm` (`If=T`, `If_0=F`, `If_1=T`, `Submit=I Accept`) before
  any other endpoint responds. Direct GETs on a non-accepted session return
  a "Stale Session" page.
- **Session timeout**: the server-side session expires after inactivity;
  pages then return a "Your session has timed out" page. Treated as a miss;
  the next entry call rebootstraps.
- **Rate limiting**: a server-side limit (~1 req/sec during probing)
  triggers a 60-second block. The scraper uses 1 request / 3 seconds.
- **Terms of Service**: the disclaimer states "attempts to download multiple
  records per transaction are strictly prohibited" (NMSA 1978 § 14-3-15.1).
  Operator should review before large-scale collection.

## Soft-404 Detection

`fails_successfully` returns `False` (miss) for HTTP-200 bodies containing
`No results found`, `Your session has timed out`, or `Stale Session`;
otherwise `True`.

## Scraper Architecture

### Entry point (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_number(docket_number: NmCourtRange)` | `NmCourtRange` | Speculative per-court case-number probe. `docket_number.court_id` selects the court; the `(court_type, court_location, case_category)` triple is derived from it via `COURT_CONFIG`. Seed once per court (each seed gets its own speculation state); `from_int` preserves `court_id` via `model_copy`. |

Multi-court speculative shape (SCRAPER_STANDARDS §4): the driver dispatches a
speculative entry with **only** its speculative param, so the court can't be
a separate `court_ids` arg — it rides inside `NmCourtRange`.

### Step functions and priorities (§5)

```
dockets_by_number → bootstrap_session (4) ─┬─ (disclaimer) form.submit → fetch_search_form (3)
                                           │        └─ GET search form → parse_search_form (3)
                                           │             └─ form.submit → parse_case_detail (2) → ParsedData
                                           └─ (welcome) GET search form → parse_search_form (3) → …
```

Priorities descend by depth so in-flight cases finish before new ones start.
No downloads (text-only site), so nothing at priority 0–1.

### Deduplication keys (§6)

- `docket_by_number:<docket_number>` — the per-case bootstrap GET. No
  court-id prefix; the docket number already encodes the court.

### Data types

`NmDocket` (main, → CL `Docket`) with nested `NmDocketEntry`
(register-of-actions rows + hearings, → CL `DocketEntry`), `NmParty` (→ CL
`Party` + `PartyType`), and `NmJudgeAssignment`. No `NmDocument` (site has no
downloadable documents).

## Known Gaps

- No documents — confirmed; site is metadata-only.
- Pre-rollout comma-formatted docket numbers (e.g. `23,321`) are unreachable
  via this form and out of scope.
- Operator should respect the bulk-download prohibition and the 60-second
  rate-limit block.
```
