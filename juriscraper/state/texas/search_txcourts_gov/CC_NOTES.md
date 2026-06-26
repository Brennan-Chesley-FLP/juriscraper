# Texas Appellate Courts (TAMES) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Covers all 17 Texas appellate courts (`tex`, `texcrimapp`, `texapp`) via
> the single TAMES `/CaseSearch.aspx` Date-Filed search. Plain-HTTP ASP.NET
> WebForms + Telerik RadGrid site — no Cloudflare / captcha, but the search
> endpoint requires `__VIEWSTATE`/`__EVENTVALIDATION` hidden fields and
> per-input Telerik date `ClientState` blobs, and silently 302s on first GET
> (hence `driver_requirements = [FOLLOW_REDIRECTS]`). HTML extraction lives
> in the `parsers/` package (§9): `SearchResultsParser` for the result grid,
> `CaseDetailParser` for a single case page. `CaseDetailParser` routes on the
> docket-number format (or URL `coa=` param) to the proven per-court legacy
> parsers in `juriscraper.state.texas.*` (`court_of_appeals`,
> `supreme_court`, `court_of_criminal_appeals`) and adapts the result to a
> `TexasDocket`. The steps keep only navigation (the search POST, pagination,
> 1000-row window splitting, per-document archive fan-out). Model fields
> follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not `court_id`),
> `docket_number` (not `case_number`/`docket_id`), `date_*` naming,
> `CleanString`/`HarmonizedCaseName` cleaning.

## Site Overview

- **Base URL**: https://search.txcourts.gov/CaseSearch.aspx
- **Requires Playwright**: No — server-rendered HTML, no Cloudflare / no captcha
- **Transport**: ASP.NET WebForms POST with ViewState / EventValidation; case
  detail pages are plain GETs
- **Server framework**: ASP.NET WebForms + Telerik RadGrid + Telerik
  RadDatePicker

TAMES is the Texas Appellate Management and E-filing System. The same search
form covers all 17 Texas appellate courts — the Supreme Court, the Court of
Criminal Appeals, and the 15 Courts of Appeals — and this scraper covers all
of them in one sweep.

## Courts Covered

The scraper declares `court_ids = {"tex", "texcrimapp", "texapp"}`.
CourtListener rolls all 15 intermediate Courts of Appeals up under a single
`texapp` ID, so each COA docket additionally carries `coa_district` (1–15)
and `court_name` ("First Court of Appeals", etc.) for downstream
disambiguation.

| Site checkbox | TAMES coa= | Display name | CL court_id | coa_district |
|---|---|---|---|---|
| chkListCourts$0 | cossup | Texas Supreme Court | tex | — |
| chkListCourts$1 | coscca | Court of Criminal Appeals of Texas | texcrimapp | — |
| chkListCourts$2 | coa01 | First Court of Appeals | texapp | 1 |
| chkListCourts$3 | coa02 | Second Court of Appeals | texapp | 2 |
| chkListCourts$4 | coa03 | Third Court of Appeals | texapp | 3 |
| chkListCourts$5 | coa04 | Fourth Court of Appeals | texapp | 4 |
| chkListCourts$6 | coa05 | Fifth Court of Appeals | texapp | 5 |
| chkListCourts$7 | coa06 | Sixth Court of Appeals | texapp | 6 |
| chkListCourts$8 | coa07 | Seventh Court of Appeals | texapp | 7 |
| chkListCourts$9 | coa08 | Eighth Court of Appeals | texapp | 8 |
| chkListCourts$10 | coa09 | Ninth Court of Appeals | texapp | 9 |
| chkListCourts$11 | coa10 | Tenth Court of Appeals | texapp | 10 |
| chkListCourts$12 | coa11 | Eleventh Court of Appeals | texapp | 11 |
| chkListCourts$13 | coa12 | Twelfth Court of Appeals | texapp | 12 |
| chkListCourts$14 | coa13 | Thirteenth Court of Appeals | texapp | 13 |
| chkListCourts$15 | coa14 | Fourteenth Court of Appeals | texapp | 14 |
| chkListCourts$16 | coa15 | Fifteenth Court of Appeals | texapp | 15 |

## Per-court Parser Routing

TAMES normalises every `/Case.aspx?cn=…` URL by appending the right `coa=`
query parameter via a 302 (e.g. `cn=A-1186` → `cn=A-1186&coa=cossup`). The
`parse_case_detail` step reads `response.url`, extracts the `coa=` value,
and routes:

| `coa=` value | Legacy parser used | Emitted `court_id` |
|---|---|---|
| `cossup` | `TexasSupremeCourtScraper` | `tex` |
| `coscca` | `TexasCourtOfCriminalAppealsScraper` | `texcrimapp` |
| `coa01`..`coa15` | `TexasCourtOfAppealsScraper` | `texapp` |

Each per-court legacy parser extracts the fields it knows about; the
adapter falls back to `.get()` on per-court keys, so a `TexasDocket`
emitted from one court doesn't fail if it lacks fields specific to
another (COAs have `publication_service` / `transfer_from` /
`transfer_to`; SC and CCA have `appeals_court_ref` + `remarks` on SC
docket entries).

## Search Capabilities

TAMES exposes a single search form (`/CaseSearch.aspx`) that accepts:

- A "Date Filed" range (Telerik date pickers — `mm/dd/yyyy`)
- A multi-select of courts (`chkListCourts$N` checkboxes)
- Several other narrowing fields (case number, party name, attorney, trial
  court, county, etc.) — unused here

Results are returned in a Telerik RadGrid (`grdCases`) with 11 columns:

| # | Column |
|---|---|
| 0 | Case Number (with `Case.aspx?cn=…&coa=coaXX` link) |
| 1 | Date Filed |
| 2 | Style (left side of the v.) |
| 3 | v. (right side) |
| 4 | Case Type |
| 5 | COA Case Number |
| 6 | Trial Court Case Number |
| 7 | Trial Court County |
| 8 | Trial Court |
| 9 | Appellate Court |
| 10 | Court Code |

**Recommended approach: date-based search with recursive halving when the
1000-row cap is hit.**

### Date-search cap

TAMES caps every search at **1000 of the most recent rows**. When a date
window over all 15 COAs returns 1000 rows, the scraper splits the window in
half and re-issues two searches; this continues until each window returns
fewer than 1000 rows. Combined with grid pagination this enumerates every
case in the requested window.

(The legacy `juriscraper.state.texas.tames` scraper uses a different
strategy — overlap-by-one-day windows walking backwards in time, with the
oldest result date on each page becoming the new end. That approach was
designed for a generator that yields rows incrementally. The kent scraper's
fan-out shape makes recursive halving simpler.)

## Docket Number Formats

Each court has its own docket-number conventions; see
`DOCKET_NUMBER_REGEXES` in `juriscraper/state/texas/common.py` for the
canonical set:

| Court | Format | Example |
|---|---|---|
| Supreme Court (modern) | `NN[B]?-NNNN` | `25-1066`, `24B-0500` |
| Supreme Court (older writs) | `NNNNN` | `16219` |
| Supreme Court (older cases) | `[ABC]-NNNN+` | `A-1186`, `B-3981`, `C-2303` |
| Court of Criminal Appeals (petitions) | `WW-NNNN-NN` | `PD-0597-12` |
| Court of Criminal Appeals (writs) | `WR-NNNNN-NN` | `WR-82,097-03` |
| Court of Criminal Appeals (appeals) | `AP-NNNNN` | `AP-76,848` |
| Courts of Appeals (1st-15th) | `NN-NN-NNNNN-XX` | `01-25-00011-CV` |

For COA dockets the leading `NN` is the two-digit court ordinal
(`01`-`15`), `YY` is the two-digit year, the five digits are a
within-court sequence, and the suffix indicates case type (`-CV`
civil, `-CR` criminal, `-CL` etc.).

The `fetch_docket` entry point trusts whatever docket number it's given
and lets TAMES resolve the court via redirect; the `parse_case_detail`
step uses the resolved `coa=` parameter to pick a parser, so any of
these formats works as input.

## Data Available

### Case Summary (top "case info" panel)

| Field | Notes |
|---|---|
| Case number | The docket number (above) |
| Date Filed | `mm/dd/yyyy` |
| Case Type | Free text (e.g. `Civil Case`, `Original Proceeding`) |
| Style | Plaintiff/appellant side of the caption |
| v. | Defendant/appellee side of the caption |
| Court | Reachable from the page `<h1>` (e.g. "First Court of Appeals") |
| Publication Service | COA-specific; usually empty |
| Transfer From / Transfer In / Transfer Case | If the case was transferred in from another COA |
| Transfer To / Transfer Out | If the case was transferred out to another COA |

### Docket Entries (`grdEvents` — Case Events table)

| Field | Notes |
|---|---|
| Date | `mm/dd/yyyy` |
| Event Type | Free text |
| Disposition | Free text (may be blank) |
| Document | Nested table of one or more document anchors |

### Appellate Briefs (`grdBriefs`)

| Field | Notes |
|---|---|
| Date | `mm/dd/yyyy` |
| Event Type | Free text |
| Description | Free text (e.g. "Appellant") |
| Document | Nested table of one or more document anchors |

### Parties & Attorneys (`grdParty`)

| Field | Notes |
|---|---|
| Party | Party name |
| PartyType | Role (e.g. "Appellant", "Appellee") |
| Representative | Newline-separated list of attorneys |

The "Representative" column is multi-line — each line is treated as an
individual attorney.

### Trial / Originating Court (`panelTrialCourtInfo`)

| Field | Notes |
|---|---|
| Court | Free text — normalized to one of: district, county, business, probate, justice, municipal, appellate, unknown |
| County | Free text |
| Court Judge | May be empty |
| Court Case | Trial court docket number |
| Reporter | May be empty |
| Punishment | Empty in civil cases |

For district trial courts the district number is parsed (e.g. "274th
District Court" → district=274). For appellate trial courts (rare — e.g.
remand from a COA) the originating CL court ID is also produced.

### Documents

Document anchors look like:

```
SearchMedia.aspx?MediaVersionID=<UUID>&coa=coaNN&DT=<DocType>&MediaID=<UUID>
```

Each link's anchor text contains a "[ PDF/123 KB ]" file-size hint that is
parsed into bytes. Document descriptions come from the cell adjacent to the
anchor.

## Email Notifications

Not available. The user-facing TAMES site has no "subscribe to this case"
affordance — only an emailing@txcourts.gov contact link in the page footer.

## Oral Arguments Calendar

Not modelled in this scraper. Each Court of Appeals publishes its oral
argument schedule on its own court website (e.g.
`https://www.txcourts.gov/14thcoa/`), not on TAMES. A separate per-court
oral-arguments scraper would be a future addition.

## Bot Protection Notes

None observed. Plain HTTP GETs/POSTs work; no Cloudflare / Akamai / hCaptcha.

What needs handling:

- **302 redirect from `/CaseSearch.aspx` to `/CaseSearch.aspx?coa=cossup`**
  on first GET — kent's persistent (httpx) driver does not follow redirects
  by default, so the scraper declares `DriverRequirement.FOLLOW_REDIRECTS`.

- **ASP.NET WebForms hidden fields** — every POST must include the
  `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`,
  `__EVENTTARGET`, and `__EVENTARGUMENT` values served by the most recent
  GET (or pagination POST response).

- **Telerik date picker ClientState fields** — the date inputs require
  parallel `_dateInput_ClientState` and `_ClientState` JSON blobs alongside
  the textual date strings or the server-side validator rejects the search
  silently (the page re-renders with no results and no error). See the
  `_make_date_client_state` helper carried over from the legacy scraper.

- **Pagination uses `__doPostBack` to `rgPageNext`** — to fetch the next
  page, POST back to `/CaseSearch.aspx` with the full form payload plus the
  next-button's `name` / `value` and *without* the `btnSearch` submit field
  (ASP.NET decides the server handler by the submitter; including both is
  invalid).

- **Rate limiting (HTTP 403)** — the search endpoint is more aggressively
  rate-limited than the per-case detail endpoint. A single per-scraper rate
  limit of 1 request/second is conservative for both.

- **Occasional empty-200 results** — TAMES sometimes returns 0 rows for a
  search that has results moments later. The legacy scraper retries up to 3
  times on this case; the kent scraper relies on the driver's transient
  retry instead.

## Document Archiving

Every document linked from a docket (from either the Case Events or
Appellate Briefs table) is fetched with `archive=True`. The flow:

1. `parse_case_detail` yields the `TexasDocket` with `TexasDocument`
   objects embedded under each entry's `documents` list. These embedded
   copies have `local_path=None` — they're the on-page snapshot.
2. For each document, `parse_case_detail` then emits an archive request
   to its `SearchMedia.aspx` URL.
3. `handle_document_download` yields a standalone `TexasDocument` with
   `local_path` set by the driver, plus `docket_id`,
   `docket_entry_kind`, and `docket_entry_number` so consumers can join
   the archived blob back to the parent docket entry.

The `MediaID` query parameter is the durable identifier for a document;
`MediaVersionID` changes when the file is revised. Deduplication keys
combine both: `tames-doc:{MediaID}:{MediaVersionID}` — same revision
won't re-download within a run, but a new revision will.

## Docket Entry Ordering

TAMES sorts both tables (Case Events and Appellate Briefs)
**newest-first** on the page. Per kind, the scraper re-numbers
bottom-to-top: the **oldest** row in each table is `entry_number=1`,
and the most recent is `entry_number=N`. Events and briefs are numbered
independently because they are physically separate tables on the page.

## Known Gaps

- The 1000-row cap edge case where a single day has >1000 filings across
  all 15 COAs is treated as a structural failure — splitting cannot
  resolve it. The legacy scraper raises `InsanityException` in that case;
  the kent scraper logs and yields what it has. This has not been observed
  in production.

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_filing_date(court_ids, date_range)` | `set[str]`, `DateRange` | Walk the Date-Filed search for the window (all 17 court checkboxes ticked, server-enforced across courts). |
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Single-case direct lookup via `Case.aspx?cn={docket_number}`. TAMES resolves the court from the docket-number prefix server-side and 302s to the canonical `coa=` URL, so we don't pre-compute it. |

Both entries converge on `parse_case_detail`.

### Step functions and priorities (§5)

```
dockets_by_filing_date (date_range)
  → fetch_search_form (4)      GET /CaseSearch.aspx; harvest hidden fields
                               then POST with hidden fields + date range + all
                               17 checkboxes
  → parse_search_results (3)   SearchResultsParser: walk rgRow / rgAltRow rows
      ├─ (count >= 1000 cap)  → split window in half; fan out two new searches
      ├─ (next page exists)   → POST __EVENTTARGET=rgPageNext → parse_search_results
      └─ (each row)           → GET Case.aspx?cn=...&coa=... → parse_case_detail
  → parse_case_detail (2)      CaseDetailParser: route on docket-number format
                               (fallback URL coa=) to legacy SC/CCA/COA parser,
                               emit ParsedData(TexasDocket) + one archive=True
                               Request per attached document
  → handle_document_download (0)  emit ParsedData(TexasDocument), local_path set

docket_by_number (docket_number) ───────────────────────→ parse_case_detail (2)
```

Priorities descend by depth so in-flight cases finish before new searches
start; document downloads sit at the reserved 0–1 band (`archive=True`
auto-assigns 1; `handle_document_download` is pinned to 0).

### Deduplication keys (§6)

- `search_form:{start}:{end}` — the session-seeding GET.
- `search_results:{start}:{end}` — the first search POST per window.
- pagination POSTs use `SkipDeduplicationCheck()` (URL collides across pages).
- `case_detail:{docket_number}` — each case-detail fetch (dedups a case
  surfaced by overlapping date-window splits).
- `doc-{MediaID}-{MediaVersionID}` (colon-free, becomes a filename) — each
  document archive; falls back to a URL hash when MediaID is absent.

### Models

Field names align to [`../../CL_MODELS.md`](../../CL_MODELS.md): `court`,
`docket_number`, `date_*`, `assigned_to_str`, `origin_docket_number`.

- `TexasDocket` — top-level docket (one model covers all three court
  flavors; per-court fields are nullable)
- `TexasDocketEntry` — one row from the Case Events or Appellate Briefs
  table, disambiguated by `kind`. Carries optional `remarks` for SC
- `TexasParty` — one party + their attorneys
- `TexasDocument` — a single document link (PDF); emitted both embedded
  in the docket (snapshot) and standalone with `local_path` after archiving
- `TexasOriginatingCourt` — trial court info embedded in the docket
- `TexasTransfer` — transfer-from / transfer-to record (COA-only)
- `TexasAppealsCourtRef` — reference to the COA that previously heard
  the case (SC / CCA-only)

Sibling exemplars referenced: `new_york/nycourts_gov` for ASP.NET WebForms
+ DateRange + paginated grid; `michigan/courts_michigan_gov` for
recursive date-window splitting on result-count cap.
