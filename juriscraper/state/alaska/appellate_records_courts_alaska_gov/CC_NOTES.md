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
| `dockets_by_number(court_ids, docket_number)` | `SpeculativeRange` | Probes sequential 5-digit numbers; the driver advances until `gap` consecutive soft-404s. One probe per court — seed a single court per speculation for clean gap tracking. |
| `docket_by_number(court_id, docket_number)` | one known case number | Accepts the number with or without the hyphen (`S-19019` / `S19019`). |

All three converge on `parse_search_results`.

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

## Verified

`last_verified` / `version` 2026-06-24 against run `AK-app-p-114.db`
(199 cases, 0 errors) via `jent replay`.
