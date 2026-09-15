# Pennsylvania Appellate Courts JSON API (`services.pacourts.us`) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Three appellate courts (`pa`, `pasuperct`, `pacommwct`) behind a public
> JSON REST API. Plain HTTP (`driver_requirements = []`) — no HTML, no
> JavaScript, no captcha, no session state. The two operational quirks are a
> **mandatory browser `User-Agent`** (the API 401s without one) and an
> **aggressive, long-lived rate limit**. Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md).

## Relationship to `ujsportal_pacourts_us`

Both scrapers cover the same three courts; they are **complementary, not
redundant**, and both should run.

| | `ujsportal_pacourts_us` (HTML portal) | `service_pacourts_us` (this one) |
|---|---|---|
| Case metadata | One results-grid row (19 columns) | Full structured case document |
| Register of actions | Only inside an unparsed PDF | Structured, with filers + service |
| Parties / attorneys | Not exposed | Structured, with bar numbers + addresses |
| Briefing schedule | Not exposed | Structured deadline ledger |
| Lower-court history | Not exposed | Structured originations + related dockets |
| **Documents (PDFs)** | **Docket-sheet PDF, archived** | **None — API exposes no document URLs** |
| Date-range search | Yes (server-side, cap 500 + split) | **Borrowed from the portal** — see below |

Net: this API is the source of truth for **structured case data**; the portal
remains the only source for **document files** — *and* for the filing-date
search, which this scraper now reaches across the domain boundary to use.

## Site Overview

- **Base URL**: `https://services.pacourts.us/public/v1`
- **Backend**: JSON REST API serving the AOPC "PAeDocket" mobile app.
- **Requires Playwright**: No.
- **Case systems**: the API fronts both **PACMS** (the three appellate
  courts) and **CPCMS**/**MDJS** (trial courts and magisterial district
  courts). This scraper is scoped to PACMS only; trial-court rows that
  surface in search results are filtered out.

### How the API was discovered

The API is undocumented, but the mobile app's remote config is public and
advertises it. `GET https://mobileconfig.pacourts.us` returns a one-element
index; following its `href` yields the app config document, whose `services`
array names both endpoints outright:

```json
"services": [
  {"name": "CaseRetrieval", "href": "https://services.pacourts.us/public/v1/cases"},
  {"name": "CaseSearch",    "href": "https://services.pacourts.us/public/v1/cases/search"}
]
```

`MOBILE_CONFIG_URL` is kept in `models.py` as provenance; the scraper does
not fetch it at runtime. A bare `GET` on the search endpoint returns an empty
criteria template, which is how the full searchable-field list below was
enumerated without guesswork.

## Courts Covered

| Docket type prefixes | `courtName` facet value | CourtListener ID |
|---|---|---|
| `MAP` `EAP` `WAP` `MAL` `EAL` `WAL` `MM` `EM` `WM` | Supreme Court of Pennsylvania | `pa` |
| `EDA` `MDA` `WDA` `EDM` `MDM` `WDM` | Superior Court of Pennsylvania | `pasuperct` |
| `CD` `MD` | Commonwealth Court of Pennsylvania | `pacommwct` |

The leading letter encodes the district (**M**iddle / **E**astern /
**W**estern) and the trailing letters the case category (`AP` appeal, `AL`
allocatur, `M`/`MM` miscellaneous, `DA` Superior appeal, `DM` Superior
miscellaneous, `CD` Commonwealth appellate, `MD` Commonwealth original
jurisdiction). Districts are internal to each court and **do not** map to
separate CourtListener IDs.

All 17 prefixes were verified by probing `GET /cases/{n} {TYPE} {year}` and
reading back `courtOffice.court.displayName` + `caseCategory.name`. The
Eastern/Western analogues of Commonwealth Court's `MD` (`ED`, `WD`) do not
exist — Commonwealth Court is statewide with a single original-jurisdiction
space.

## Endpoints

### `GET /public/v1/cases/{docketNumber}` — case retrieval

Docket number percent-encoded (`1 MAP 2024` → `1%20MAP%202024`). Returns the
**entire case** in one response (~85 KB for a moderately active docket; 631
distinct leaf paths on the sample used to build the models). Returns a **hard
404** for a nonexistent docket — no soft-404 handling is needed, and this is
what makes speculative enumeration viable.

### `POST /public/v1/cases/search` — case search

Accepts the criteria object a bare `GET` on the same URL returns as a
template:

```
caseStatusName · searchBy · organizationName · docketNumber
participantFirstName · participantLastName · offenseTrackingNumber
policeIncidentNumber · stateIdentificationNumber · courtName
courtOfficeName · docketTypeName · dateFiledRangeBegin · dateFiledRangeEnd
dateOfBirth
```

Response envelope: `results` plus the facet lists `caseStatusNameOptions`,
`courtNameOptions`, `courtOfficeNameOptions`, `docketTypeNameOptions`, and
`maxIndex` / `startIndex` / `endIndex`.

## Search Capabilities

Ranked by scraping utility — and the ranking is unusual here, because the
normally-best mode is unavailable:

1. **Date-range search — NOT AVAILABLE.** `dateFiledRangeBegin` /
   `dateFiledRangeEnd` exist as fields but are only *filters*; the endpoint
   rejects a search anchored on them alone:

   > `Invalid search criteria. Must provide a minimum of organization name,
   > participant last name, offense tracking number, police incident number
   > or state identification number.`

   Note that **docket-number search is also not in that list** — a docket
   number alone is accepted by the retrieval endpoint, not as a search
   anchor. So there is no way to enumerate "everything filed last week".
2. **Docket-number retrieval** — the direct `GET`. Hard 404 on a miss, which
   makes speculative enumeration clean. **This is the bulk strategy.**
3. **Participant/organization name search** — works, but is a targeted
   lookup, not an enumerator (see the cap below).

### The 150-row cap is not paginable

A name search returns at most **150 rows**. The response echoes
`startIndex`/`endIndex`, but **sending them in the request body does not
page** — the server ignores them and returns the same first window every
time (verified: `startIndex: 150` returned rows identical to `startIndex: 0`).
A search that comes back at the cap is silently truncated, so
`parse_search_results` logs a warning when it sees the cap.

Applying `courtName` server-side both scopes results to one appellate court
and materially reduces truncation risk (unfiltered "Smith" → 150 rows, 100 of
them trial-court noise; `courtName`-filtered → 50 real appellate rows).

**Primary approach: cross-domain docket discovery** via
`dockets_by_filing_date` (below). Speculative docket-number enumeration
(`dockets_by_number`, seeded per `(docket_type, year)`) remains available as a
fallback and a cross-check.

## Cross-domain docket discovery

This scraper's bulk entry point issues requests to **`ujsportal.pacourts.us`**,
not just `services.pacourts.us`. That is deliberate, and it is the one place in
this scraper where the domain boundary is crossed.

**Why.** The one search mode that matters for ongoing collection — "what was
filed in this window" — is the one this API refuses to serve (above).
Speculative enumeration was the only alternative, and it is a poor one:

- it can never distinguish *"this sequence number doesn't exist"* from *"the
  sequence numbers stop here"*, so coverage is a guess parameterized by `gap`;
- the sequence space is sparse and does not reliably start at 1, so the guess
  has to be a loose one (25+ consecutive misses before stopping);
- under the aggressive rate limit, a 429 is indistinguishable from a 404 to the
  walk, so throttling silently truncates ranges (see "Rate limiting");
- and it costs one request per *candidate*, most of which are misses, against
  an API that permits roughly one request per 10 seconds.

The UJS portal answers the same question directly: same operator (AOPC), same
three appellate courts, same PACMS backend, server-side filing-date search, one
court per POST. One portal search enumerates a window exactly, and every row it
returns is a docket number this API can then retrieve. That was compelling
enough to accept the cross-domain dependency.

**How.** `dockets_by_filing_date` GETs the portal's `/CaseSearch` form, POSTs
the appellate date-range search for one court, and reads **only the docket
numbers** out of `#caseSearchResultGrid`; each one becomes a
`GET /public/v1/cases/{docketNumber}` against this API. Nothing is emitted from
the portal rows themselves — the sibling scraper already emits those (plus
their docket-sheet PDFs), so emitting them here would duplicate records.

**What is shared, and what is not.** The portal's form contract (`SEARCH_URL`,
`SEARCH_FORM_XPATH`, the `AppellateCourtName` ↔ court-id map, `RESULT_ROW_CAP`,
`MIN_SPLIT_WINDOW`, `BROWSER_HEADERS`) and its `ResultsGridParser` are
**imported** from `ujsportal_pacourts_us.models` / `.parsers`, not copied — the
two scrapers cannot drift apart on the portal's contract, and a portal
selector fix lands in both at once. Those constants were moved out of the
sibling's `scraper.py` into its `models.py` for exactly this reason. The two
scrapers stay otherwise independent: no shared steps, no shared records.

**Consequences to keep in mind:**

- The portal's **500-row cap and the halve-the-window split** apply here too;
  `parse_portal_results` implements the same split, down to the same 1-day
  floor (a single day at the cap is accepted and logged rather than split
  forever).
- **`HTTP_CODE_TYPES = {400: TRANSIENT}`** is set for the portal leg — the
  portal intermittently 400s (~1%) on well-formed POSTs, and the default
  persistent classification would drop a whole window's rows. The JSON API
  itself never uses 400 (missing docket = 404; bad search = 200 + error body),
  so nothing else is affected.
- The **rate limit is run-global, not per-host**, so portal searches spend the
  same 1-per-10s budget as API fetches. Both hosts are AOPC and the portal's
  own scraper uses a *slower* 15s ceiling, so this errs safe — but a window's
  searches and its case fetches are competing for the same slots.
- A portal outage or selector change breaks this scraper's bulk path even
  though the API is fine. The speculative walk is the fallback, which is one
  reason to keep it.

## Docket Number Format

`"<seq> <TYPE> <year>"`, space-delimited, e.g. `1 MAP 2024`. `<seq>` restarts
at 1 each calendar year within each `<TYPE>`, so the ID space is partitioned
by **both** type and year — which is why the speculative param
(`PaDocketRange`) carries `court_id`, `docket_type` **and** `year`.

### Sequence density — set `gap` generously

Sequences are **sparse and do not reliably start at 1**:

- Within `1..30` of a given 2024 prefix, only ~⅓–½ of numbers resolve
  (e.g. `MAP` 10/30, `EAP` 13/30, `MM` 3/30).
- `1 EAL 2024` is a 404 while `3 EAL 2024` exists — the space can start above 1.
- Interior gaps of 5+ consecutive misses were observed (`EDA` 2024: 12–16).

A tight `gap` would stop the walk inside an ordinary run of misses. **`gap`
of at least 25** is recommended. Observed upper bounds for 2024 (sequential
probing, before rate limiting cut the survey short): `MAP` ~106, `EAP` ~72,
`WAP` ~35, `MAL` ~671 — so allocatur spaces run an order of magnitude larger
than merits-appeal spaces, and `soft_max` should not be assumed uniform
across prefixes.

## Rate limiting — the dominant operational constraint

**This is the single most important thing to know about this API.**

- Bursts trigger **HTTP 429** with body `Unauthorized request` and **no
  `Retry-After` header**.
- The penalty is **long-lived and IP-wide**: a single burst of ~10 concurrent
  requests produced sustained 429s that were still returning 429 **more than
  an hour later**, including for lone requests spaced 8+ seconds apart and
  after multiple multi-minute idle periods. The block did not lift within the
  design session, so its true duration is a lower bound, not a measurement.
- While throttled, the API returns 429 for **valid** dockets, so a throttled
  run manufactures false 404-like misses. During recon this briefly made real
  prefixes (`MDA`, `WDA`, `EDM`, `MDM`, `WDM`) look nonexistent. **A
  speculative walk that gets throttled will read the throttle as a gap and
  terminate the range early** — the most important failure mode to watch for
  in the first real run.

Mitigations in the scraper:

- `rate_limits = [Rate(1, Duration.SECOND * 10)]`.
- 429 is **TRANSIENT** in the framework's default code map, so throttled
  requests retry rather than drop; no `HTTP_CODE_TYPES` override is needed.

> **The 10-second figure is a conservative guess, not a measured sustainable
> rate.** Recon triggered the block before a safe rate was ever established,
> and the block then outlasted the session, so no throughput could be probed
> afterwards. It is borrowed from the ceiling the sibling `ujsportal` scraper
> settled on for the same operator (AOPC). **Validate it on the first real
> run**, from a fresh IP, starting slower rather than faster — and treat any
> 429 in that run as a signal to back the rate off further, not as noise.

### Sequencing the first run

Because a throttled probe reads 429s as misses and can truncate a range
early (above), do **not** start with a broad speculative sweep. Seed a single
`(docket_type, year)` range first, confirm it walks without a 429, and only
then widen. A run that ends with 429s in the log should have its speculative
results treated as incomplete regardless of how many records it produced.

## Bot protection

- **Mandatory browser `User-Agent`.** The API returns **401 Unauthorized** to
  a default Python/httpx/urllib UA and serves normally to a browser-like one
  (verified both directions). Sent on every request via `Request.permanent`
  so it cascades down the chain. Same quirk the `ujsportal` scraper documents
  for its PDF endpoint.
- No cookies, tokens, anti-forgery fields, or session state of any kind.
- `Access-Control-Allow-Origin: *` — the API is intentionally public.

## Data Available

All of the following comes from the **single** case-retrieval response.

### Case (→ `PACMSDocket`, CL `Docket`)

Docket number, court + district + docket type, short and long caption, filing
/ docketed / disposition dates, status, processing status, case category and
subject-matter case types, case flags, sealed and Nebbia flags, claim amount,
order type, initiating document, lower-tribunal category, court office
(name/code/type), assigned judge, originating docket numbers, root
originating docket/authority/organization, OTN/LTN/police-incident numbers,
next scheduled event, and the internal PACMS case id.

### Register of actions (→ `PACMSDocketEntry`, CL `DocketEntry`)

Per entry: filed date **and time**, sequence number, registry entry code,
document title/number, sealed flag, order-exited date, comment lines (for
orders, frequently the full operative text), the participants it applies to,
**filers**, and **service records** (method, recipient, status, dates).

The API also surfaces four singleton entries as dedicated top-level objects
(`finalDispositionRegistryEntry`, `remittalRegistryEntry`,
`reArgumentPetitionRegistryEntry`, `reArgumentDispositionRegistryEntry`).
These are the same shape as register rows and duplicate one of them, so they
are folded into `docket_entries` tagged with `entry_role` rather than
modelled separately. Unused slots arrive as fully-null placeholder objects
(and, for dates, a **year-1 sentinel** `0001-01-01T00:00:00-05:00` rather
than `null`) — both are normalized away in `parsers/_common.py`.

### Parties & attorneys (→ `PACMSParty` / `PACMSAttorney`)

Parties with role, sort order, pro-se flag, aliases, and (criminal cases)
demographic fields. Attorneys carry **PA bar number**, active flag, entry /
withdrawal of appearance dates, firm name, full mailing address, phone, fax
and service preferences.

Attorneys arrive as a **flat top-level list**, joined to participants by the
participant's numeric id (`caseParticipantName.id.id` ↔
`participantName.id.id`) — not by name, since two parties on one caption can
share a `documentName`. An appearance whose participant is missing from
`caseParticipants` is attached to a party-less `PACMSParty` rather than
dropped.

### Dispositions (→ `PACMSDisposition`)

Disposition, category, dates (disposition / filed / judgment), finality flag,
journal number, disposing authority, filer names (**the authoring justice**,
or `Per Curiam`), and the operative comment lines.

### Briefing schedule (→ `PACMSBriefingScheduleItem`)

A **deadline ledger** — paper-book type, current due date, filed date (null
while outstanding), and the owing party + role. Modelled as its own type
rather than folded into docket entries, because these are obligations, not
events that happened.

### Lower court & related cases

`PACMSOriginatingCourt` (CL `OriginatingCourtInformation`): lower-court docket
number, tribunal name, office, judge, OTN/LTN.
`PACMSRelatedCase`: `caseHistory` (the same matter's other PACMS dockets) and
`crossCourtCaseHistory` (its dockets in other PA courts), each with a
directly-fetchable `href`.

### Supreme Court metadata (→ `PACMSSupremeCourtInfo`)

Allocatur docket number, grant date (→ CL `date_cert_granted`) and grant-order
text, appeal-jurisdiction-noted date, the "appeal of" recital, intermediate
court/docket/disposition, reargument denial date and disposition, and panel
member names (→ CL `panel_str`).

## Documents

**The API exposes no document URLs.** A sweep of all 631 leaf paths for
`http`/`.pdf`/`url`/`link`/`file` fields found only `href` values, and every
one points at another *case* resource, never a file. `documentTitle` and
`documentNumber` name documents but do not link them.

Consequently this scraper makes **no `archive=True` requests** and emits no
document model. PDF acquisition stays with `ujsportal_pacourts_us`, whose
docket-sheet endpoint requires a per-docket `dnh` hash only obtainable from
that portal's HTML.

## Deliberate omissions & open gaps

Recorded so `revise-scraper` dispositions them rather than re-discovering
them:

- **Fee ledger (partially captured).** `assessmentGrandTotals` carries a
  full transaction-level ledger
  (`assessmentCategoryTotals[].assessments[].transactions[]`). Only the
  category rollups are captured (`PACMSAssessmentTotals`): appellate
  filing-fee transactions are bulky and low-value, and CourtListener has
  nowhere to put them.
- **`caseCalendarEvents` / `caseSessionAssignments` — UNVERIFIED.** Both were
  **empty** on every case observed during recon, so their element shape is
  unknown and neither is mapped yet. These are the likely home of oral-argument
  scheduling. Per project convention, future-calendar entries belong in
  `docket_entries` (as `DocketEntry`s), **not** a separate hearing type — so
  when a populated sample turns up, map them into `PACMSDocketEntry` rather
  than introducing a new model. `latestCaseEvent` *is* mapped
  (`next_event` / `date_next_event_due`).
- **Other collections empty in the sample** and therefore unverified:
  `caseAssociations`, `caseBails`, `civilDispositions`, `civilJudgments`,
  `confinements`, `localNumbers`, `offenses`, `paymentPlans`, `sentenceLinks`.
  These are criminal/trial-court-oriented and are expected to stay empty on
  appellate dockets, but that is an inference, not a verified fact.
- **API misspelling.** The case document ships the lower-court appeal date
  under **both** `lowerCourtApplealFilingDate` (sic) and
  `lowerCourtAppealFilingDate`. The parser prefers the corrected spelling and
  falls back to the misspelled one, so the field survives either being
  dropped.
- **Single-sample modelling.** The models were built against one fully-mapped
  Supreme Court case (`1 MAP 2024`) plus search summaries; a
  Superior/Commonwealth case has not been mapped field-by-field. Rate
  limiting cut the sampling short. **First action after the initial run:
  `revise-scraper` with `jent schema-match` over the run corpus** — the whole
  point of that tool is closing exactly this gap, and a JSON API is the best
  possible case for it.

## Oral Arguments Calendar

No dedicated calendar endpoint is exposed by the mobile config (which
advertises only `CaseRetrieval` and `CaseSearch`). Argument scheduling most
likely lives in the unverified `caseCalendarEvents` above.

## Email Notifications

Not available. The API is read-only and anonymous; there is no subscribe or
notification affordance, and the mobile config advertises no such service.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|---|---|---|
| `dockets_by_filing_date(court_ids, date_range)` | `set[str]`, `InferrableDateRange` | **Primary.** Docket numbers from the UJS portal's filing-date search (cross-domain), fetched in full here. |
| `dockets_by_number(docket_number)` | `PaDocketRange` | Speculative walk of one `(court, docket type, year)` space. Fallback / cross-check. |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Single known docket. |
| `dockets_by_participant_name(court_ids, last_name)` | `set[str]`, `str` | Name search, court-filtered server-side. |

For ongoing collection, run `dockets_by_filing_date` over the window wanted —
it enumerates exactly, where the speculative walk estimates. Keep the
speculative walk for backfilling years the portal search struggles with (very
wide windows split into many searches) and as an independent check that the
portal is not hiding rows.

`dockets_by_number` is the §4 multi-court speculative exception: the driver
binds **only** the speculative param, so the court, docket type and year ride
inside `PaDocketRange` (a `CourtRange` subclass). `search_key()` returns the
docket-type prefix. `from_int` advances via `model_copy`, so all three
discriminators survive the walk (verified).

Seed one range per `(docket_type, year)` — 17 prefixes × the years wanted:

```python
seed_params = [
    {
        "dockets_by_number": {
            "docket_number": {
                "court_id": "pa",
                "docket_type": "MAP",
                "year": 2024,
                "min": 1,
                "soft_max": 1,
                "gap": 25,
            }
        }
    },
    # ... one per (docket_type, year); DOCKET_TYPES_BY_COURT lists the prefixes
]
```

### Step functions and priorities (§5)

```
dockets_by_filing_date → submit_portal_search (5) → parse_portal_results (4)
                            ├→ (per row) parse_case (3) → ParsedData
                            └→ (cap hit) split window & resubmit → (4)
dockets_by_number / docket_by_number → parse_case (3) → ParsedData
dockets_by_participant_name → parse_search_results (4)
                                └→ (per appellate row) parse_case (3) → ParsedData
```

Priorities descend by depth so in-flight searches finish before new ones
start. There are no downloads, so nothing occupies priorities 0–1.

`parse_portal_results` is a thin wrapper over the plain generator
`_portal_results_to_requests(page, accumulated_data)`; the logic lives there so
it is unit-testable (a `@step` can only be driven through a real `Response`).
`test_portal_discovery.py` exercises it offline: the fan-out, the trial-court
row filter, the cap split, and the single-day-at-cap exception.

Because the whole case arrives in one response, `parse_case` is a single
terminal step — there is no tab walk, and no `accumulated_data` merging
across pages beyond carrying the requested court/docket number as a fallback.

### Deduplication keys (§6)

- `case:<docket_number>` — the case fetch. Dedups a docket reached by any
  combination of the portal walk, the speculative walk and a name search.
- `participant_search:<court_id>:<last_name>` — the API search POST.
- `portal_search_seed:<court_id>:<start>:<end>` — the portal form GET.
- `portal_search:<court_id>:<start>:<end>` — the portal search POST (the split
  halves key on their own sub-window, so a re-split is idempotent).

### HTTP status handling (§10)

API-side, the defaults are correct as-is: **404** (nonexistent docket) is
persistent — which is what terminates a speculative probe — and **429** is
transient, so throttled requests retry.

`HTTP_CODE_TYPES = {400: HTTPCodeType.TRANSIENT}` exists **only** for the
cross-domain portal leg (see "Cross-domain docket discovery"). It cannot
misfire on the API, which never answers 400.

`actually_successful` is **not** overridden: the retrieval endpoint uses real
status codes rather than soft-404s. The one 200-with-an-error case is the
search endpoint's `{"errorMessages": [...]}` body, which
`parse_search_results` detects and raises `ScraperAssumptionException` on —
the entry always sends criteria the API documents as sufficient, so a
rejection means the contract changed.

### Parsers (`parsers/`)

Because this is a JSON API, the parsers are **plain callables over the
decoded body**, not `JKentParser` subclasses — that base class is bound to
lxml/`PageElement` (`from_string` builds an `LxmlPageElement`), so it cannot
wrap a JSON document. They stay fully offline-testable: pass a saved response
dict straight in.

- `case_detail.CaseDetailParser` — the case document → `PACMSDocket` fields.
  Returns a plain `dict` rather than a `DeferredValidation`, because
  `DeferredValidation` instances cannot nest; the step owns the single
  top-level `PACMSDocket.raw()` call.
- `search_results.SearchResultsParser` — the search envelope → summary rows,
  plus `error_messages()` and `hit_result_cap()` helpers.
- `_common.py` — date/time normalization (including the year-1 null
  sentinel and the midnight-means-date-only rule), name flattening, and
  null-safe traversal for the API's fully-null placeholder objects.

### Data types

`PACMSDocket` only — one record per case, with all children nested.
