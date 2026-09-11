# California Supreme Court Briefs (supreme.courts.ca.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> Plain-HTTP, server-rendered Drupal pages; briefs organized by *oral
> argument session*. HTML extraction lives in the `parsers/` package (§9);
> the steps keep navigation (index date filter, per-session fan-out, PDF
> archive requests). `driver_requirements = []`. Model fields follow
> [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (a CourtListener id),
> `docket_number`, `date_*` naming.

## Site Overview

- **Base URL**: `https://supreme.courts.ca.gov/case-information/briefs-argued-cases`
- **Backend**: Drupal 10 (USWDS "jcc" theme), fully server-rendered.
- **Requires Playwright**: No. No JS gate, no bot protection, no cookies, no
  form. `curl` gets the same bytes the browser does.
- **Scope, in the court's words**: "Briefs filed in cases argued since 2010
  are available for download. When new cases are set for oral argument,
  briefs are posted here the same day." So the listing is *forward*-looking
  too: as of 2026-09-10 the index carried sessions through September 2026.
- **404s are real 404s.** A bad session slug returns HTTP 404, so there is no
  soft-404 to detect and `actually_successful` is not overridden.

Corpus figures below are from a full sweep of the index on **2026-09-10**:
191 sessions, 1,284 case listings (1,227 distinct case numbers), 11,506
briefs.

## Courts Covered

| Case-number prefix | CourtListener ID | Listings |
|--------------------|------------------|----------|
| `S` | `cal` | 1,281 |
| `C` | `calctapp_3rd` | 3 |

The site is the Supreme Court's, but the September 7–8 2010 session lists
three Third District (`C0610xx`) cases whose briefs the court incorporated
into S183411 by order of June 9 2010. `court` is therefore derived per record
from the number's prefix (`DOCKET_PREFIX_COURTS`), never assumed. `court_ids`
filters emitted records — the index is not per-court, so it selects nothing.

The same `docket_number` + `court` joins to the sibling
`appellatecases_courtinfo_ca_gov` scraper, which has the docket (parties,
disposition, register of actions, and a Briefs *tab* naming each brief) but
links **no brief files**. This scraper is where the PDFs come from.

## Search Capabilities

| Rank | Mode | Available |
|---|---|---|
| 1 | Date-based search | **No server-side search of any kind.** The index states each session's dates in the link text, which is what makes date addressing possible client-side. |
| 2 | Case number search | No — no per-case URL on this host. |
| 3 | Party name search | No. |

**Recommended approach**: fetch the one index page, read the date span out of
every session link, and fetch only the session pages whose span overlaps the
window. That is what `briefs_by_argument_date` does, and the filter is per
*session*, not per year — a window inside 2026 never fetches a 2025 page.

Cost is one index fetch plus one session page per overlapping session:

| Window | Page fetches |
|---|---|
| 2026 Q1 | 1 + 3 |
| calendar 2026 | 1 + 9 |
| every session since 2010 | 1 + 191 |

The last row is the one-off backfill ceiling, not what a run costs; a routine
incremental run is the first row or smaller.

The index fetch itself is unavoidable. There is no per-year URL to narrow it
with: `?year=2026` and `?page=1` both return the identical 423 KB document,
and the page carries no views-AJAX plumbing at all. The year accordion is
client-side CSS over one fully-rendered page, so its year headings could only
restate dates that are already in each session link.

## Session Title Date Grammar

The dates live only in the session title, and the court writes the span a
dozen ways. All 191 titles parse with `parse_session_title`, which reads the
title as a token stream (month names latch until the next one) rather than
matching formats:

```
January 27, 2010                 May 25 – 27, 2010      May 6 & 7, 2026
June 2 and 3, 2026               February 7 - 10, 2011  May 31 - June 3, 2011
November 8, 9, and 10, 2011      May 3, 4, and 5, 2016  January 5, 2016,
October 6, 2015 Outreach Session Oral Argument Cases (Morning Session)
```

Trailers (`Oral Argument Cases` / `Oral Arguments Cases` / `Oral Argument
Briefs`), a trailing parenthetical naming half-day sessions, and the two
session kinds (`Special Session` — 3, `Outreach Session` — 2) are stripped;
only the first and last day are kept.

### `date_argued` is only set for single-day sessions

103 of the 191 sessions ran one day; the other 88 span two to four. The page
groups every case under the session as a whole and **never says which day a
given case was called**, so `date_argued` is populated only when the session
is one day (462 of 1,284 listings). `date_session_start` /
`date_session_end` always carry the span.

The per-case day *does* exist — in the oral argument calendar PDF linked from
`/case-information/oral-arguments/oral-arguments-calendar`, one per session,
which also carries the argument order and the courtroom. That is the obvious
next data source if per-case argument dates matter; it is not scraped here.

## Page Structure

### Index (`/case-information/briefs-argued-cases`)

One USWDS accordion, one panel per year ("Current Year", then 2025 → 2010),
each holding a link per session. The panel headings are ignored: they restate
the year already in each link, and the first reads "Current Year". Session
links are matched by href prefix
(`/case-information/briefs-argued-cases/<slug>`).

### Session page (`/case-information/briefs-argued-cases/<slug>`)

Two shapes, both parsed:

1. **The Drupal view** (1,281 of 1,284 listings). One flat run of siblings
   inside `div.views-element-container` → `div.jcc-section__inner`:
   `<h2>` case heading, zero or more `<p>` notes, `<div class="jcc-list">`
   with an `<ol>` of brief links. **Nothing is nested**, so the parser walks
   the container's children in document order; which note and which list
   belong to which heading is document order and nothing else.
2. **Hand-authored body blocks** (6 pages). A `div.jcc-body__main` holding
   `header.jcc-section-heading > h2`, a `div.jcc-section-heading__lead` note,
   and a `div.jcc-body__main-text` list. Three are genuine cases the editor
   added by hand (S105876, S130263, S198132 — each the last case on its
   page); the other three hold a `Special Note:` heading naming the venue of
   a special session, which carries no case and is skipped.

Each brief `<li>` is `<a href=...>Title</a> Filed on <Month D, YYYY>`.

## Data Available

### `CalSupremeArgumentSession` (one per session fetched)

`court`, `session_title`, `date_session_start`, `date_session_end`,
`session_type` (regular / special / outreach), `source_url`.

### `CalSupremeBriefCase` (one per case *listing*, → CL `Docket`)

`court`, `docket_number`, `case_name`, `heading_raw`, `date_argued`,
`date_session_start`, `date_session_end`, `session_title`, `session_type`,
`notes`, `consolidated_with`, `briefs[]`, `source_url`,
`source_entry_point`.

This is **not** a full docket — the page states only the number, the caption,
an occasional note, and the briefs.

A record is one *listing*, not one case: a case continued to a later calendar
is listed again under the new session with the briefs filed since appended.
52 of the 1,227 distinct case numbers appear under more than one session, and
49 of those have a different brief set each time. `(court, docket_number,
source_url)` identifies a listing.

### `CalSupremeBrief` (nested, → CL `RECAPDocument`)

`document_number`, `description`, `document_type`, `filed_by`, `date_filed`,
`url`, `filename`.

`document_number` is the **list position**, not the leading number in the
filename: 420 of the 11,478 linked files disagree with their position because
multi-volume exhibits are numbered `8a`/`8b`/`8c`.

### `CalSupremeDownloadedBrief` (one per downloaded PDF)

`court`, `docket_number`, `document_number`, `description`, `date_filed`,
`brief_url`, `local_path`. Joins to the case on
`(court, docket_number, brief_url)`.

## Brief Title Grammar

`split_brief_title` splits the link text into (filer, document type) along
the three forms the court uses:

| Form | Example | Count |
|---|---|---|
| possessive | `Appellant's Opening Brief on the Merits` | ~8,000 |
| amicus | `Amicus Curiae Brief of Consumer Attorneys of California` | ~1,300 |
| comma | `Real Party in Interest, The People, Answer Brief on the Merits` | ~200 |
| bare | `Petition for Review`, `Order` (mostly pre-2011) | 226 |

The verbatim `description` always stands; the split is a convenience.
Two quirks are handled: the possessive filer may not contain a comma (so
`Respondent, Workers' Compensation Appeals Board, …` is read as the comma
form, not split on the apostrophe in "Workers'"), and the pre-2013 listings
misplace the apostrophe in `Real Party's in Interest <document>`, which is
put back together rather than filed under a filer of "Real Party".

Both `'` (U+2019) and `'` occur; the regexes accept either.

## Known Site Defects (all handled, none repaired silently)

- **`NO CASE ASSIGNED`** — one September 2019 heading, over five files all
  named for S198132 (a duplicate of that page's own S198132 listing, with
  `_0`-suffixed filenames). The case number is recovered from the filenames;
  `case_name` is `None` and `heading_raw` keeps the heading verbatim.
- **A brief with no link** — the May 7–8 2019 session lists "Respondent,
  L.A. Truck Centers, LLC, Opening Brief on the Merits" with no anchor. The
  listing is kept with `url = None`; that the court named a brief it did not
  post is itself the datum.
- **Staging-host links** — 27 links in the hand-authored blocks point at
  `live-jcc-supremecourt.pantheonsite.io`. Both hosts serve the identical
  file; `canonical_brief_url` rewrites the host (only the host) to
  `supreme.courts.ca.gov`.
- **Link text disagreeing with the file** — e.g. S105876's list labels
  `7-s105876-app-focus-issues-ltr-052220.pdf` as "Appellant's Opening
  Brief". Both are recorded (`description` and `filename`); neither is
  corrected from the other.
- **Heading separators vary** — `-`, `–`, or nothing at all (`S198387
  VANDERMOST v. BOWEN`).
- **Duplicate files across listings** — 23 URLs appear under two cases
  (consolidated pairs). The download dedup key is
  `<docket_number>-<filename>`, so a file shared by two *dockets* is fetched
  once per docket and a case listed under two *sessions* is fetched once.

## Bot Protection Notes

None. No hidden fields, no session tokens, no cookies, no user-agent gate.
Rate limit is set to 2 req/s out of politeness, not necessity.

## Email Notifications

Not available on this host. The sibling
`appellatecases.courtinfo.ca.gov` case pages carry the court's email
notification signup; see that scraper's notes.

## Scraper Architecture

### Entry point (§4)

```python
briefs_by_argument_date(court_ids: set[str], date_range: InferrableDateRange)
```

Named for the date it addresses (the same shape as Washington's
`briefs_by_hearing_date`) because the index genuinely *is* a date index —
only one the client reads rather than the server. The window and
`court_ids` both filter in-scraper, so they ride down the chain in
`accumulated_data` (`start_date` / `end_date` / `target_courts`) rather than
being re-read from params (JKENT_REFERENCE §2).

A session that straddles the edge of the window is fetched whole: the court
lists its cases as one group and never says which day a case was called, so
there is no honest way to drop half of it.

A window ending before 2010 (`MIN_YEAR`) yields no request at all.

### Flow

```
briefs_by_argument_date  -> GET the briefs index
parse_briefs_index  (3)  -> BriefsIndexParser: every session link's date span;
                            emit CalSupremeArgumentSession for the sessions
                            inside the window, GET each session page
parse_session_page  (2)  -> SessionPageParser: one CalSupremeBriefCase per
                            case, one archive request per brief PDF
handle_brief_download(1) -> emit CalSupremeDownloadedBrief
```

Priorities descend by depth (§5); downloads are `archive=True` (auto
priority 1).

### Dedup keys (§6)

| Request | Key |
|---|---|
| index | `briefs_index:<start>:<end>` |
| session page | `session_page:<slug>` |
| brief PDF | `<docket_number>-<filename>` |

The session key is the URL's own slug, so the same session dedups across
runs whatever window asked for it.

### Parsers (§9)

| Module | Class | Page |
|---|---|---|
| `parsers/briefs_index.py` | `BriefsIndexParser` | the index |
| `parsers/session_page.py` | `SessionPageParser` | one session page |
| `parsers/_common.py` | — | title/date/brief-title helpers |

Both are exercisable offline with `JKentParser.from_file(path, url=...)`.

Headings and notes are read through a `.//text()` `query_strings` call rather
than `text_content()`. That is not stylistic: an element the parser also
*queries on* counts as a scoping container to the selector observer, and a
container's own text is never marked consumed — so reading a heading with
`text_content()` left the case captions showing up as unclaimed residual.

## Verification (2026-09-10)

- Offline: both parsers run over all 191 archived session pages — 1,284
  cases and 11,506 briefs, every record validating against its model, every
  `court` resolved, every `date_filed` parsed.
- Live: `jent run` over 2026-01-01 → 2026-03-31 — 3 sessions, 15 cases, 255
  PDFs (445 MB), 259/259 requests HTTP 200, 273/273 records valid.
- `tests/local/test_cal_supreme_briefs_scraper.py` — offline parser tests
  over compact fixtures covering the title date grammar, both page shapes,
  multi-note cases, `NO CASE ASSIGNED`, the unlinked brief, and the staging
  host rewrite.
- `jent residuals --clusters` over the session pages leaves 2 clusters, both
  restatements of the session title (`<title>` and the breadcrumb). Nothing
  the page states about a case is unclaimed.

## Next Steps

- Sweep the full 2010–2026 history and hand off to **revise-scraper** to
  record `residuals.yaml` dispositions for the two title-restatement
  clusters.
- **audit-data** should look at `document_type` (954 distinct values, a long
  amicus tail) and `filed_by` (1,664) — both are candidates for a coded
  vocabulary with a raw fallback.
- The oral argument calendar PDFs are the source for per-case argument dates
  and argument order, if `date_argued` needs filling in for multi-day
  sessions.
