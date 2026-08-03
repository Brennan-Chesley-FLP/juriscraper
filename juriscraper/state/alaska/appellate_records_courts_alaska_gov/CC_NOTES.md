# Alaska appellate courts (`appellate-records.courts.alaska.gov`)

Scrapes docket data from the Alaska appellate CMS for two CourtListener
courts:

- **`ak`** — Alaska Supreme Court, case numbers `S#####`
- **`akctapp`** — Alaska Court of Appeals, case numbers `A#####`

Plain HTTP (no JS, no auth). The `Search/CaseNumber` endpoint returns up to
**1000** matches per query with **all rows in the HTML** — pagination is
client-side only, so a single fetch yields every match.

## Entry points

| Entry | Addressing | Notes |
| --- | --- | --- |
| `dockets_by_number_prefix(court_ids, prefix)` | 3-digit case-number prefix | `prefix` is zero-padded to 3 digits per court (`12` → `S012`/`A012`). A 3-digit prefix matches ≤100 of the 5-digit numbers, well under the 1000 cap. Bulk enumeration. |
| `dockets_after_docket_number(court_id, docket_number)` | one court + a 5-digit watermark | Incremental sweep. Truncates the watermark to its 3-digit prefix and searches that prefix **and the next** (`10005` → `S100`, `S101`), covering the rest of the watermark's block plus the whole block after it. `parse_search_results` prunes rows numbered ≤ the watermark (S10000–S10005). Clamped at prefix `999`. |
| `dockets_by_number(court_ids, docket_number)` | `SpeculativeRange` | Probes sequential 5-digit numbers; the driver advances until `gap` consecutive soft-404s. One probe per court — seed a single court per speculation for clean gap tracking. |
| `docket_by_number(court_id, docket_number)` | one known case number | Accepts the number with or without the hyphen (`S-19019` / `S19019`). |

`dockets_after_docket_number` is the second §4 exception to "`court_ids`
first" (alongside the single-record `docket_by_number`): the Supreme Court
and Court of Appeals number their cases independently, so each has its own
watermark and a `court_ids` set would imply one shared cursor. Seed it once
per court.

All four converge on `parse_search_results`. The watermark rides down in
`accumulated_data["min_docket_number"]` (and is folded into the search
request's `deduplication_key`, so a pruned prefix search never dedupes
against an unpruned one). Filtering compares the numeric part of the case
number only — each search is already scoped to one court's letter — and
keeps any row with no digits rather than dropping it.

Only newly docketed cases are caught: new activity on a case at or below
the watermark isn't visible from the search page and needs
`docket_by_number`.

## Soft-404 detection

`actually_successful()` returns `False` for empty CaseNumber pages: the
endpoint answers 200 even for non-existent numbers, but the `No Results
Found` placeholder row lacks the `class="search-link"` anchor that real
result rows always carry. This drives speculative gap counting.

## Per-case flow

```
parse_search_results (9)
  └─ parse_case_general (8)        case summary + opinions/lower court/related
       └─ parse_case_parties (7)   participants & attorneys
            └─ parse_case_records (6)
                 └─ parse_case_docket (5)        docket entries (+ doc downloads)
                      └─ parse_case_motions (4)  motions list (+ doc downloads)
                           └─ parse_motion_detail (3)  one page per motion, sequential
                                └─ parse_case_briefs (3)   briefs list (+ doc downloads)
                                     └─ parse_brief_history (2)  one page per brief, sequential
                                          └─ emits AkDocket
```

Priorities descend with depth (shallower steps run later, so in-flight
cases finish before new ones start). Document downloads use `archive=True`
(auto priority 1); all flow steps stay ≥ 2.

The case-tab navigation is data-driven: `_extract_tab_urls` reads the
`cms-submenu` nav, and `_continue_chain` walks the tab order
(parties → records → docket → motions → briefs), skipping tabs the case
doesn't expose. Motion details and brief histories are sub-chains: each
page is fetched sequentially (one pending item handed forward at a time)
and merged back into its motion/brief by list index.

## Case-title block

Every case page repeats a case-title block: case number and name, case
status, an optional `[Cross Appeal: …]` reference (rendered twice — a
legacy `caseID` anchor and the `q`-token one we want), and one badge div
per special status (an `E` glyph with an `Expedited` tooltip).
`parse_case_title` in `_common.py` reads it, and only the Case Summary
page's copy is kept — onto `case_status`, `cross_appeal_*` and
`special_status_flags`. On the other tabs the block is chrome (see
`residuals.yaml`).

## Data model

A single `AkDocket` is accumulated across all tab requests via a plain
dict threaded through `accumulated_data["docket_data"]` (`_json_safe`
keeps it JSON-serializable; dates round-trip as ISO strings and
`AkDocket.raw` re-coerces them at confirm). Each archived file is emitted
as a separate `AkDocument`, joined back to the docket by `docket_number`
and to its originating row by `entry_number` + `source`.

Documents the CMS no longer holds (most pre-2012 opinions) 302-redirect to
the search page; `handle_document_download` flags these
`missing_redirected=True` via the final `Content-Type`.

## Parsers

Each page-type has a `JKentParser` under `parsers/`
(`search_results`, `case_general`, `parties`, `records`, `docket`,
`motions`, `motion_detail`, `briefs`, `brief_history`); `_common.py` holds
shared extraction helpers (date parsing, `q`-token extraction, attorney
blocks, motion-flag glyphicons). Steps are thin adapters that call a parser
and keep navigation/download concerns to themselves. Parsers can be
exercised offline with `JKentParser.from_string` / `from_file`.

Several helpers route text through `text_lines` (a `.//text()` query)
rather than `text_content()`. Both yield the same string, but only the
query is visible to jkent's `SelectorObserver`, so `jent residuals` can
tell "the scraper read this" from "the scraper never looked".

## Coverage

`residuals.yaml` is the residual-identification sidecar for
`jent residuals`: every DOM text cluster the parsers leave unconsumed,
with why it is chrome. Regenerate stubs for new clusters with

```
jent --db-dir <runs> --repo . '<selection>' residuals \
    --record juriscraper/state/alaska/appellate_records_courts_alaska_gov/residuals.yaml
```

There is no `schemas.json`: every continuation serves HTML.

## Verified

`last_verified` / `version` 2026-06-24 against run `AK-app-p-114.db`
(199 cases, 0 errors) via `jent replay`.

Revised 2026-07-28 against the 198-db `juriscraper-runs/alaska` corpus
(396 searches, 22,234 case-tab pages per tab, 169k motion details,
101k document fetches, 3 errors — all truncated PDF downloads).
