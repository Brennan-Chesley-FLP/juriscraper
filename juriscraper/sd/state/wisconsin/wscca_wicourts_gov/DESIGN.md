# WSCCA (Wisconsin Supreme Court & Court of Appeals Access) Scraper Design

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
preserved as case metadata.

## Search Capabilities

The search form (additional criteria expanded) supports:

- Party name (last/first/middle), business name
- Attorney name (last/first)
- Case number (auto-normalized: `22AP1` → `2022AP000001`)
- County (Statewide + 72 Wisconsin counties)
- Case status: Open, Closed, Pending Remit, Pending Petition for Review,
  Remanded, Reopened
- Court type: `CA` or `SC`
- Current district: 1–4 (CA only)
- Class codes (offense/case-class taxonomy)
- **Filing date range** (MM-DD-YYYY)
- Public-domain citation (year + court type + seq)
- Citation of official publishers (volume + publisher + page)

**Decision-tree result**: a filing-date filter exists in the SPA, but
the search endpoint is invisible-hCaptcha-gated. The case-detail
endpoint (`/api/case/{caseNo}`) is *not* gated and returns 404 for
unknown case numbers — making speculative enumeration a clean fit
without ever touching the captcha.

**Recommended approach (v1)**: **`YearlySpeculativeRange` enumeration
of the `YYYYAP######` numbering** — Wisconsin appellate cases share a
single sequence per (year, type-prefix) and `AP` (Appeal) is the
dominant prefix. Every Court-of-Appeals and Supreme-Court case
threads through this one space, so a single speculative entry covers
both courts; the API's `courtType` field tells us which CourtListener
id (`wis` vs `wisctapp`) the docket belongs to.

**Date-based search (deferred to v2).** The captcha gate plus the
PureScript SPA's lack of `name`-attributed form fields makes
date-search an awkward fit for kent's `find_form()` /
`ViaFormSubmit` abstractions: there's no stable named form to bind
to, and the SPA URL parser ignores `filingDateBegin` /
`filingDateEnd` deep-link params (only `caseNumber` and `courtType`
are honored). Recording the gap here so the next iteration can plumb
through a captcha-aware SPA-form driver if/when needed.

## API Contract (captured from the SPA)

The SPA exposes a captcha-gated session model:

1. `POST /api/captcha/validate/search`
   - Body: a quoted JSON-string containing the hCaptcha JWT token
     (`"P1_eyJ..."`)
   - Returns a UUID-shaped session token used in subsequent calls.
2. `POST /api/case-search/{session-uuid}/count`
   - Body: `SearchParams` JSON.
   - Returns the matching record count.
3. `POST /api/case-search/{session-uuid}`
   - Body: `{pageInfo: {startIndex, size}, params: SearchParams,
     sorts: [{columnName, direction}]}`
   - Returns paginated rows.
4. `GET /api/case/{sccaCaseNo}` (no captcha)
   - Returns the full case JSON.
5. `GET /api/case/{sccaCaseNo}/document/{docId}` (no captcha)
   - Returns the document PDF (`application/pdf`).
6. Metadata reference endpoints (no captcha): `/api/counties`,
   `/api/case-statuses`, `/api/court-type-codes`, `/api/class-codes`,
   `/api/captcha/config`.

`SearchParams` shape (all fields optional except where noted):

```json
{
  "caseNumber": null,
  "caseStatus": [],
  "ccCountyNo": null,
  "courtType": "CA" | "SC" | null,
  "districtNo": 1-4 | null,
  "filingDate": {"from": {"m":int,"d":int,"y":int}|null,
                 "to":   {"m":int,"d":int,"y":int}|null},
  "includeMissingPartyNameM": true,
  "searchSimilarPartyName": false,
  "partyNameF": null, "partyNameL": null, "partyNameM": null,
  "businessName": null,
  "attyNameF": null, "attyNameL": null,
  "classCode": [],
  "pdcYear": null, "pdcCourtType": null, "pdcSeqNo": null,
  "citeVolume": null, "citePublisher": null, "citePage": null
}
```

Date format is `{"m": int, "d": int, "y": int}` everywhere in the API.

## Docket Number Format

Wisconsin appellate cases have a uniform format. The display form
(`22AP1`) is normalized server-side to a 12-character canonical form
`YYYY` + 2-letter court-type code + 6-digit sequence:

- `2022AP000001` (Court of Appeals, year 2022, seq 1)
- `2023AP002543` (Court of Appeals)
- `2024XX000XXX` for SC variants

We always pass the canonical form through to `/api/case/{caseNo}`.

## Data Available — `/api/case/{caseNo}` JSON Shape

Top-level keys (every case):

- `caseData` (object): `sccaCaseNo`, `shortCaption`, `longCaption`,
  `statusCode`, `statusDescr`, `wcisClsCode`, `wcisClsCodeDescr`,
  `dispoCode`, `dispoCodeDescr`, `dispoDate`, `filingDate`, `courtType`,
  `districtNo`, `filingDistrictNo`, `caseSuffix`, `casePanelSize`,
  `countyName`, `countyNo`, `maintCode`, `maintCodeDescr`,
  `sccaConsolidationSeqNo`, `isConfidential`.
- `parties` (list): each `{name: {nameL, nameF, nameM, suffix},
  partyTypes: [...], partySeqNo, attorneys: [...], addresses: [...]}`.
  - `attorneys` (list): each `{name: {...}, enteredDate, withdrewDate,
    attySeqNo, partySeqNo}`.
- `pastEvents` (list): each `{eventSeqNo, eventStatusCode (e.g. OCCD),
  courtTypeCode, descr, filingDate, subEventText, dueDate,
  additionalText}`. **This is the docket / register of actions.**
- `upcomingEvents` (list): same shape as `pastEvents`. Items here are
  scheduled future events for the case (e.g. due dates, oral
  arguments). Per the kent convention, modeled as additional
  `WiDocketEntry` rows (not a separate `ScheduledHearing` type).
- `documents` (list): each `{docId, docName, eventDescr, eventCode,
  eventSeqNo, sccaCaseNo, pages, docStampDate}`. PDF URL is
  `/api/case/{sccaCaseNo}/document/{docId}`.
- `opinionDecisionDocuments` (list): cross-reference linking specific
  past events to opinion documents (`{eventSeqNo, descr, courtTypeCode,
  noticeTypeCode}`).
- `ccCaseData` (list): related circuit court cases —
  `{ccCaseNo, ccCounty, ccCountyNo, ctofcName, respCtofcName,
  legacyCaseLink}`. The `legacyCaseLink` points at WCCA
  (`https://wcca.wicourts.gov/caseDetail.html?caseNo=...`).
- `citnData` (list): citations — `{volume, publisher, page,
  courtTypeCode, docSeqNo}`.
- `pubCitnData` (list): publisher citation cross-reference — usually
  empty.
- `consolCaseData` (list): consolidated cases — usually empty.
- `interestedParties` (list): rare; usually empty.

Date format throughout: `{"m": int, "d": int, "y": int}`. Names
throughout: `{nameL, nameF, nameM, suffix}` (any field nullable; for
businesses only `nameL` is populated).

## Documents

Every downloadable filing is listed under `documents`. The download
URL is `GET /api/case/{sccaCaseNo}/document/{docId}` and returns a PDF
(`application/pdf`). Briefs and opinions are present from 2009-07
onward; older non-eFiled briefs are scanned and added over time.

Some opinion-event past entries also expose external WI Courts URLs
(e.g. `wicourts.gov/other/appeals/caopin.jsp?docket_number=...`) but
those are not persistent download endpoints — prefer the
`/api/case/.../document/{docId}` endpoint for stable archival.

## Email Notifications

The site exposes an RSS feed per case at `/rss/case/{sccaCaseNo}`
(linked from the case detail page header). No email-subscription form
is exposed publicly — the RSS is the supported subscription mechanism.

## Oral Arguments Calendar

The case JSON's `upcomingEvents` array surfaces per-case scheduled
hearings, but there is **no** separate per-court calendar page exposed
in WSCCA. (The Wisconsin Supreme Court publishes a separate oral-
argument schedule on `wicourts.gov`; that is a different scraper if
desired.) Per-case future events are modeled as `WiDocketEntry` rows
on the docket — no separate `OralArgument` type for this site.

## Bot Protection Notes

- **Search is hCaptcha-gated.** The widget is `data-size="invisible"`
  but falls back to a visible image challenge ("Tap on all clear
  liquids") when bot scoring is low. kent's `HCAP_HANDLER` clicks the
  invisible widget and lets it self-validate; in our manual probes the
  challenge passed silently after the first interaction.
- **Every `/api/...` endpoint 403s outside a real browser.** Even with
  full cookie jar, real Chrome User-Agent, all `sec-fetch-*` headers,
  HTTP/2, and a JSESSIONID established by hitting the page first, plain
  curl gets 403 from `/api/case/...`. Inside Playwright the same fetch
  returns 200. We treat the whole scraper as Playwright-only.
- The site issues three HttpOnly cookies on first contact:
  `wscca-prod_sr`, `wscca-prod-app-central1_sr`,
  `JSESSIONID_wscca-d000050-i01-prod-app-central1`. These are sticky-
  routing tokens for the clustered backend and are managed by Playwright
  automatically.
- The "I agree" terms-of-use click is gated only by a localStorage
  flag (`lastAgreed`); no server-side acceptance state.

## Scraper Architecture

### Driver

`driver_requirements = [JS_EVAL, FF_ALIKE, HCAP_HANDLER]`. The whole
scraper is Playwright; per-step driver requirements are not used.

### Entry Points

```python
@entry(WiDocket) fetch_docket(case_id: str)
@entry(WiDocket) fetch_appeal_docket(case_id: YearlySpeculativeRange)
```

- `fetch_docket(case_id)` — direct lookup by canonical
  `YYYYAP######`-form case number. Used for ad-hoc queries and for
  re-fetching dockets that earlier failed.
- `fetch_appeal_docket(case_id)` — speculative enumeration of the
  `YYYYAP######` numbering. One seed per year, sequence resets at 1
  each year. `case_id.year` and `case_id.min` come from the kent
  speculation driver; `case_id.gap` controls when the driver decides
  to stop after consecutive misses. Single seed shape::

      [{"fetch_appeal_docket": {"case_id":
          {"year": 2025, "min": 1, "soft_max": 4000, "gap": 20}}}]

  The seed_params author owns year rollover (one seed per active year).

### Other type prefixes (deferred)

The site exposes additional 2-letter prefixes (`XX`, `BC`, `AD`,
`AM`, `OK`, `PM`, `WW`, `ZZ`, `GG`, `HH`, `LL`, `MM`) for
non-standard case types. Volume on these is low and they share the
same `/api/case/{caseNo}` endpoint, so they can be added as
additional `@entry` methods when the data is wanted — each delegates
to the same `_build_case_request(case_id)` helper.

### Step Functions

```
fetch_docket / fetch_appeal_docket
  → parse_case_detail   # GET /api/case/{caseNo} (JSON in body)
                         # 4xx → speculation miss (auto-handled);
                         # 200 → parse JSON, build WiDocket, yield
                         #   ParsedData and archive Requests for docs
  → handle_document     # yields WiDownloadedDocument with local_path
```

### Soft-404 handling

`/api/case/{caseNo}` returns HTTP 404 for unknown numbers. The
speculation driver auto-converts 4xx into miss outcomes via
`SpeculationHTTPFailure`; no `fails_successfully` override is needed.

### Models (see `models.py`)

- `WiDocketEntry`, `WiParty`, `WiAttorney`, `WiDocument`,
  `WiCircuitCourtCase`, `WiCitation`, `WiDocket`,
  `WiDownloadedDocument`.
- `WiDocket.entries` includes both past and upcoming events (per the
  kent convention; no separate `WiHearing` type).

### Known gaps

- Briefs/petitions for confidential case types are not exposed by the
  site itself — the JSON `documents` array simply omits them. No
  scraper-side workaround.
- For older non-eFiled briefs the site notes they "will continue to be
  added over time" — coverage of pre-2009 cases is incomplete by design.
