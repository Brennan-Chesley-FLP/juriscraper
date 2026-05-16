# Tennessee Public Case History Scraper Design

## Site Overview

- **Base URL**: https://pch.tncourts.gov
- **Site name**: Public Case History (C-Track case management system, hosted by
  the Tennessee Administrative Office of the Courts)
- **Marketing landing page**:
  https://www.tncourts.gov/courts/supreme-court/public-case-history (the live
  search is a one-click hop to `pch.tncourts.gov`)
- **Requires Playwright**: No — server-rendered ASP.NET WebForms, returns
  HTML for both search and case detail. Document downloads are
  ASP.NET `__doPostBack` form submissions that re-POST the same URL with
  preserved hidden state — `page.find_form().submit()` handles this.
- **Transport**: HTML form / WebForms postback

## Bot Protection Notes

The lightweight gates are:

1. **Referer check on `/SearchResults.aspx`.** Both the speculative GET
   *and* the pagination POST 302 to `/Index.aspx` when the Referer is
   missing or off-site. We attach
   `Referer: https://pch.tncourts.gov/index.aspx` to both. Every other
   endpoint (`CaseDetails.aspx`, the PDF postback) is open.
2. **Standard ASP.NET MAC-protected `__VIEWSTATE` / `__VIEWSTATEGENERATOR`
   / `__EVENTVALIDATION`** on every form-submitting page. They aren't
   cookies, but they must be transmitted verbatim from the same page that
   rendered them.
3. No session cookies, no captcha, no JS challenge.

### `__doPostBack` quirk: do **not** use `page.find_form().submit()`

Both the PDF download and the page-2 pagination are ASP.NET LinkButton
postbacks. The naïve approach — `page.find_form().submit(data={"__EVENTTARGET": ..., "btnAdvanceSearch": ""})`
— fails: kent's form parser harvests every named submit button as a
default field, and IIS treats the *presence* of a submit-button name in
the body (even with an empty value) as a real button click, ignores
`__EVENTTARGET`, and short-circuits the request to `/SearchResults.aspx`.

Our `_build_postback_data(page)` helper harvests only:

- All `<input type="hidden">` fields (including
  `CurrentPages` / `TotalPages` / `searchText` / `searchType` /
  `MobileDevice` on the results page, and `hdMastId` / `hdPDF` /
  `hdOpen` on the detail page).
- The visible search textbox (`txtSearch`).
- The currently checked `SearchTerm` radio.

It deliberately omits every submit `<input>` (`btnAdvanceSearch`,
`btnSearch`, `pagecount*`, `previous1`, `btn1`, `btn2`). The *only*
button name that should appear in the postback body is `next1=Next` for
pagination — everything else uses `__EVENTTARGET` alone.

## Courts Covered

One site, three appellate courts. The court is encoded in the case-number
suffix, not in any URL or form field. A single sequence-number search
returns rows from all three courts simultaneously.

| Site code | Display Name | CourtListener ID |
|-----------|-------------|------------------|
| `SC` | Tennessee Supreme Court | `tenn` |
| `COA` | Tennessee Court of Appeals | `tennctapp` |
| `CCA` | Tennessee Court of Criminal Appeals | `tenncrimapp` |

## Search Capabilities

Decision-tree result:

1. Date filter? **No** — the form has no date field.
2. Newest-sorted listing walk? **No** — there is no listing endpoint that
   exposes filing dates.
3. **Speculative entry on case numbers** ✓

The site lets you submit a **partial** sequence number. The search performs
a substring match against the `NNNNN` segment of every appellate case
number. A query for `02744` returns every case whose sequence segment
contains `02744`, across all years (back to 2006), all districts, and all
three courts. There is no per-court parameter — the same query hits Supreme,
Court of Appeals, and Court of Criminal Appeals.

**Recommended approach**: speculative `SpeculativeRange` over the 5-digit
sequence number. One entry yields multi-court results; we infer
`court_id` from the case-number suffix at parse time.

### Search request shape

```
GET https://pch.tncourts.gov/SearchResults.aspx?k=<seq>&Number=True
Referer: https://pch.tncourts.gov/index.aspx
```

- `k`: 5-digit zero-padded sequence number (e.g. `00001`, `02744`).
- `Number=True`: select the case-number search mode (other modes:
  `Name=True`, `Party=True`, `Business=True`, but they're not used here).

### Soft-404 detection

Empty / 0-result searches **302 to `/Index.aspx?count=0`**. With a
non-redirect-following httpx driver, a successful search returns HTTP 200
and an HTML page containing `redirectToCase(...)` JavaScript onclick
handlers; an unsuccessful one returns HTTP 302. Without
`FOLLOW_REDIRECTS`, the driver treats 302 as the response, and the
default kent behaviour treats it as a non-2xx (a miss for speculation).
We override `fails_successfully` to also treat empty result tables (200
with no `redirectToCase` rows) as a miss, in case the server ever
returns 200-with-empty-table in the future.

### Pagination

Each results page shows up to 20 rows. When a sequence has more matches,
the form shows "Page N of M" and a `name="next1" value="Next"` submit
button. Pagination is a postback — we re-POST `SearchResults.aspx` with
all hidden fields preserved plus `next1=Next`. `page.find_form()` plus
`form.submit(data={"next1": "Next"})` handles it.

In practice, only sequence numbers ≤ ~3000 cross 20 results; most
yield 0–20 (one page).

## Docket Number Formats

Case numbers follow a single, stable schema across all three courts:

```
[E|M|W]YYYY-NNNNN-[SC|COA|CCA]-{appeal-type}-{case-type}
```

| Segment | Meaning | Examples |
|---------|---------|----------|
| `E` / `M` / `W` | Grand division (East/Middle/West) | `E`, `M`, `W` |
| `YYYY` | 4-digit year case was filed | `1996`–`2025` |
| `NNNNN` | 5-digit zero-padded sequence | `00001`–~`05000` |
| `SC` / `COA` / `CCA` | Court | `SC`, `COA`, `CCA` |
| Appeal type | Tennessee Rule of Appellate Procedure | `R3` (appeal as of right), `R9` (interlocutory by permission), `R10` (extraordinary appeal), `R11` (Tenn. S. Ct. discretionary review), `R28` (post-conviction), `WR` (writ), `T10B` (Tenn. Rule 10B recusal motion), `BAR` (bar admission/discipline matters; SC only) |
| Case type | Subject matter | `CV` (civil), `CD` (criminal), `PC` (post-conviction), `HC` (habeas corpus), `PT` (parental termination), `CO` (other), `SUR` (bar surrender) |

Examples observed in the wild:

```
M2013-02744-SC-R11-CD     → Supreme Court
M2013-02744-CCA-R3-CD     → Court of Criminal Appeals
E2008-02744-COA-R3-CV     → Court of Appeals
E2015-00001-CCA-R3-PC     → Court of Criminal Appeals (post-conviction)
E2014-00001-CCA-R28-PC    → Court of Criminal Appeals (Rule 28)
W2017-01000-CCA-T10B-CO   → Court of Criminal Appeals (Rule 10B recusal)
M2018-01000-SC-BAR-SUR    → Supreme Court (bar surrender)
M2025-01000-COA-R3-PT     → Court of Appeals (parental termination)
```

`court_id` is derived from the third dash-separated segment:

```python
{"SC": "tenn", "COA": "tennctapp", "CCA": "tenncrimapp"}[suffix]
```

## Data Available

### Result row (from `SearchResults.aspx`)

- `Case Number` — full appeal number (e.g. `M2013-02744-SC-R11-CD`)
- `Case Name / Style` — caption
- (each row has `onclick="redirectToCase('<id>', 'Number', 'False')"` —
  the `<id>` is the C-Track internal MastCastID used for the detail URL)

### Case Detail (`CaseDetails.aspx?id=<id>&Number=True`)

Single page, five `<h3>` sections:

#### Case header
- `<h1 class="case-title">` — case style/caption
- `<h2 class="case-number">` — full case number

#### Case Overview (id=`case-overview`)
- Inter. Case No. — intermediate-court case number (when the master is at
  SC, this points to the COA/CCA case being reviewed)
- Style
- Trial Court — e.g. "Rutherford County Circuit Court (CIVIL)"
- Trial Court Judge — e.g. "Bragg, David M."
- Trial Court No. — e.g. "F70116"

#### Case Milestones (id=`case-milestones`, table id=`milestones`)
Two-column table (Description, Date). Standard rows:
- Application Filed
- Application Disposition
- Record Filed
- Appellant(s) Briefing Complete
- Appellee(s) Briefing Complete
- Oral Argument/Submission
- Decision Date
- Decision Type
- Disposition
- Panel
- Closed Date

#### Parties (id=`case-parties`)
Three-column table (Names, Role, Counsel). One row per party.

#### Case History (id=`case-history`)
Four-column table (Date, Event, Filer, PDF). This is the docket / register
of actions. Each row is one event; rows with a "PDF" link have an inline
`__doPostBack('ListView10$ctrlN$ListView12$ctrl0$LinkButton1','')`
download trigger.

#### Record Information
Three-column table (Volume Type, Volumes, Record Type). Examples:
"Technical Record / 1 / Original", "Transcript of Evidence / 1 / Original",
"Exhibits / 3 / Original".

### Documents

PDF availability is **per docket-history row**. When a row has a `PDF` link,
the link text is `__doPostBack('ListView10$ctrl<N>$ListView12$ctrl0$LinkButton1','')`.

Issuing the `__doPostBack` returns `Content-Type: Application/pdf` with
`Content-Disposition: attachment; filename=<doc_id>.pdf` directly — no
intermediate redirect to a download URL.

To replay the postback over HTTP:
1. GET the case detail page.
2. `page.find_form()` to capture all hidden fields (including `__VIEWSTATE`,
   `__EVENTVALIDATION`, `txtSearch`, `SearchTerm`, `hdPDF`, `hdOpen`,
   `hdMastId`).
3. `form.submit(data={"__EVENTTARGET": "<linkbutton path>", "__EVENTARGUMENT": ""})`.
4. The `archive=True` request handles the PDF body.

Postback paths look like `ListView10$ctrl<N>$ListView12$ctrl0$LinkButton1`
where `<N>` is the docket-history row index. The driver can extract this
from each row's `<a href="javascript:__doPostBack('...')">` tag.

## Email Notifications

Not available on this site.

## Oral Arguments Calendar

Not available on this site. Oral argument schedules and videos live on the
*marketing* domain (`tncourts.gov`), not on the case-search domain. They
would be a separate scraper, out of scope here.

## Scraper Architecture

### Entry point

```python
@entry(TnDocket)
def fetch_case_by_sequence(self, rid: SpeculativeRange) -> Request:
    """One speculative request per sequence number."""
```

Single entry, one `SpeculativeRange` parameter (continuous integer). The
driver enumerates `rid.min` from the seed value upward and stops after
`gap` consecutive misses. Sequences in the wild range from 1 to ~3000 per
year; we recommend seeding `{"number": 1, "gap": 50}`.

A **single** sequence search returns 0-N rows spanning all three courts,
all years, all three grand divisions. We do not iterate per-court or
per-year; the search engine covers all of them.

### Step Functions

```
fetch_case_by_sequence (entry)
    → SearchResults.aspx?k=<seq>&Number=True
    ↓
parse_search_results
    → for each row, yield Request to CaseDetails.aspx?id=<id>&Number=True
    → if "Next" button present, yield form.submit(data={"next1": "Next"}) for next page
    ↓
parse_case_detail
    → parse case header, overview, milestones, parties, docket history, record info
    → for each PDF link in docket history, yield archive=True postback Request
    → yield ParsedData(data=docket)
    ↓
handle_document_download
    → yield ParsedData(data=TnDocument with local_path)
```

### Soft-404 detection

```python
def fails_successfully(self, response: Response) -> bool:
    # 302 → /Index.aspx?count=0 means no results found.
    # Without FOLLOW_REDIRECTS, the driver sees the 302 itself.
    if response.status_code in (301, 302, 303, 307, 308):
        return False
    # 200 with no result-row JS = empty table; treat as miss.
    if "/SearchResults.aspx" in response.url:
        return "redirectToCase(" in response.text
    return True
```

### Models

- `TnDocket` — main output
- `TnDocketEntry` — Case History row
- `TnMilestone` — Case Milestones row
- `TnParty` — Parties row
- `TnRecordEntry` — Record Information row
- `TnDocument` — archived PDF (separate top-level type so files can be joined back to the docket)

### Court-ID mapping

Inferred from the case-number suffix at parse time:

```python
SUFFIX_TO_COURT = {"SC": "tenn", "COA": "tennctapp", "CCA": "tenncrimapp"}
```
