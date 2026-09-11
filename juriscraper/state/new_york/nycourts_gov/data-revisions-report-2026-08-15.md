# Court-PASS data audit — 2026-08-15

First data audit of this scraper. Ledger: `data_audit.yaml` (75 paths, all with
a verdict; no stale entries). Decisions on the proposals are in §7.

## 1. Corpus

| | |
|---|---|
| db | `../juriscraper-runs/new_york/nycoa/complete/2026-08-08.cc-guided.db` |
| swept | 2026-08-08, entry point `dockets_by_bulk`, court `ny` only |
| scraper commit | `c99dff073` |
| `NYCourtPassDocket` | 5,088 rows (4,832 distinct docket numbers) |
| `NYCourtPassFile` | 14,206 rows |
| nested `files[]` / `docket_entries[]` / `attorneys[]` / `issues[]` | 21,331 / 24,516 / 13,281 / 4,503 |
| `result_type='dict'` rows | **0** |
| `is_valid=0` rows | **0** |
| errors | **0** |

Nothing failed `confirm()` and nothing errored, so no scraped data is hiding
outside the model-shaped view. No `residuals.yaml` or `schemas.json` sidecar
exists for this scraper, so the "is this null field also an unidentified
residual cluster" cross-check was unavailable — see the tool-gap note.

## 2. Verdict rollup

75 verdicts over 74 live paths, plus the dropped `aria_case_info` (kept in the
ledger until a post-fix sweep replaces the corpus).

| verdict | verdicts |
|---|---|
| `ok` | 43 |
| `null-bug` | 13 (11 of them the one root-file defect) |
| `coded` | 10 |
| `suspect` | 7 |
| `redundant` | 1 |
| `null-by-design` | 1 |
| `null-unreachable` | 1 (a field added by this audit) |

No previous report, so no diff. Everything below is newly found.

## 3. Actionable findings, by rows affected

### 3.1 The emitted `NYCourtPassFile` was missing 11 of its 18 fields — 14,206 rows *(fixed)*

`handle_file_download` rebuilt the record from four `accumulated_data` keys, so
`doc_role`, `doc_party`, `doc_type`, `volume`, `part`, `document_group`,
`docket_entry_index`, `link_status`, `match_confidence`, `date_received` and
`date_due` were **null on every one of the 14,206 rows** — while the nested copy
of the same file on the docket had all of them. The record that carries the
downloaded binary was the one with no classification on it, so a consumer had to
re-join to the docket to read any of it.

Found exactly where the skill says to look: the same path filled at 100% under
`NYCourtPassDocket.files[]` and 0% under the root `NYCourtPassFile`, visible only
because both were censused side by side.

### 3.2 Doubled internal whitespace on names — 12,606 values *(fixed)*

Court-PASS renders names from fixed slots and leaves the run of spaces behind
when one is blank (`Frank  Brady Esq.`, `Mei Lin  Kwan-Gett Esq.`). Every parser
used `.strip()`, which only trims the ends.

| path | offending rows |
|---|---|
| `docket_entries[].party` | 5,513 |
| `attorneys[].party_name` | 3,738 |
| `attorneys[].attorney_name` | 3,170 |
| `issues[].detail` | 69 |
| `attorneys[].firm` | 64 |
| `attorneys[].address` | 52 |

### 3.3 `attorneys[].party_role` is a vocabulary stored as free text — 13,281 rows *(coded)*

27 distinct values, one singleton, Good–Turing `P(unseen) ≈ 0.000075`. See §5.

### 3.4 `aria_case_info` carried raw HTML entities — 2,057 rows *(field dropped)*

Court-PASS **double-escapes** the attribute: the source reads
`O&amp;#39;Connor` and `Argument date &amp;nbsp;.`, so the HTML parse leaves one
layer behind. Verified against the stored source of request 9018. This is also
why 167 rows appeared not to contain their own `case_short_name`.

Initially fixed by unescaping a second time; superseded on 2026-08-16 by
dropping the field outright (§7.3), since it restated `case_short_name` +
`argument_date` and nothing else.

### 3.5 256 duplicate docket emissions — 240 docket numbers *(left as-is)*

The Docket.aspx grid lists one case on several consecutive rows. Verified on
request 9018, where `JCR-2019-00006` occupies rows 0–4 with byte-identical
aria-labels. The scraper follows every row and emits a full, identical docket
for each: same `case_name`, `argument_date`, `source_url`, file count — only
`search_row` differs. Up to 5 copies (`JCR-2018-00002`, `JCR-2019-00006`).

Deduping grid rows before following would drop ~5% of docket work and all of
the downstream inflation, but it changes what the scraper *requests* rather
than how it reads a page. **Decided 2026-08-16: leave it.** The downloads are
already unaffected — `deduplication_key` collapses them, which is why the file
coverage in §6 reconciles exactly — so this costs requests, not correctness.

### 3.6 `lower_court_citation` stored the site's placeholder — 11 rows *(fixed)*

`N/A` ×10 (padded: `'N/A                      '`) and `NA` ×1, verified on the
page for result 3171. Now `None` via a shared `clean_optional`.

### 3.7 `attorneys[].firm` holds `person, office` — 4,317 rows (35%) *(left as-is)*

`Hon. Eric T. Schneiderman, New York State Attorney General`; `Robert S. Dean,
Esq., Center for Appellate Litigation`. This is Court-PASS's attorney-of-record
line — the named principal plus the office. `attorney_name` holds a *different*
person (the lawyer who actually appeared: `Marcus J. Mastracco Esq.` under
Schneiderman), so the two are not duplicates and nothing is lost today; the
field is just wider than its name for a third of its values.

**Decided 2026-08-16: not split.** CL's `Attorney`/`Role` has nowhere to put
the named principal, so a split field would have no destination downstream.

### 3.8 `issues[].recognized` false — 1 row *(fixed)*

`Corporations--Not-For-Profit Corporation` (result 10543, APL-2026-00100). One
unrecognized issue in 4,503 — the vocabulary is in very good shape. Added as
`IssueSubcategory.NOT_FOR_PROFIT_CORPORATION`, code 690.

### 3.9 Court-side anomalies — kept verbatim, not fixed

* **`official_citation` = `Withdrawn`** (APL-2016-00240, result 9838). Verified
  on the page. An affirmative statement about the case, not a placeholder, so
  `clean_optional` deliberately keeps it. If `official_citation` is ever coded,
  this earns a real member.
* **9 malformed citations**, all the Court's own typos: `32NY3d 1010`,
  `17 NYed 118`, `15 NY3D 391`, `40 Ny3d 417`, `93 NY2d 01`, `19 NYS3d 463`, and
  three 2013-era appeals reported as `NY2d`.
* **13 dockets decided before argument.** Verified on result 12
  (APL-2023-00146): the page prints argued 09/10/2024, decided 08/21/2024. All
  13 have a null `official_citation`, so the "decision" is likely a dismissal.

Each is an assertion in the ledger, measuring the Court's data quality rather
than ours.

### 3.10 What the audit *confirmed* rather than broke

The reconciliation machinery holds up under every structural check:

* 0 orphan files (every `docket_entry_id` resolves), nested and root alike
* 0 duplicate `docket_entry_id`s within a docket
* 0 `link_status='unlinked'` — the bug signal the docstring names
* 0 vocabulary drift (`filing_type_recognized=false AND inferred_from_file=false`)
* all 5,269 file-less entries are real FILINGS rows; **zero** inferred entries
  have an empty `file_indexes`, which the docstring says is impossible
* `doc_type` unreadable on 6.9% of files, against a docstring claiming ~6%
* `attorneys[].address` filled on all 13,281 rows, every one containing a digit
  — **no sentinel addresses at all** (no `CONFIDENTIAL`, no `Unknown`), unlike
  the California corpus
* `attorneys[].phone` matches `(NNN) NNN-NNNN` on every filled value
* all dates within 1998-02-02 … 2026-11-20

## 4. Changes made

| file | change | verification |
|---|---|---|
| `parsers/_common.py` | new `clean_optional`, `collapse_ws`, `collapse_ws_lines` | unit-checked on the observed pathological values |
| `parsers/filing_detail.py` | `clean_optional` on both citations; `collapse_ws` on issue text | replay `request:3998` — `lower_court_citation` `'N/A'` → `None`, `official_citation` `'21 NY3d 289'` preserved, 11 files / 12 entries unchanged, **0 errors** |
| `parsers/docket_detail.py` | `collapse_ws` on filing type, party, and every attorney value; `collapse_ws_lines` on address; classify `party_role` | replay `request:143` — `'Mei Lin  Kwan-Gett Esq.'` → `'Mei Lin Kwan-Gett Esq.'`, `party_role='Defendant'` with `party_role_raw` intact, address newlines preserved, counts identical to result 108 (0 entries / 3 attorneys / 0 files) |
| `parsers/docket_results.py` | drop `aria_case_info` entirely (2026-08-16) | the entity defect verified against the stored source of request 9018 before the field was removed |
| `vocabularies.py` | new `PartyRole` (27 members) + `party_role_from_value`; `IssueSubcategory.NOT_FOR_PROFIT_CORPORATION` | codes unique, 0 collisions; `classify_issue` now returns `recognized=True` for the one holdout |
| `models.py` | `party_role: PartyRole \| None` + `party_role_raw: str`; drop `aria_case_info`; document the `local_path` join | — |
| `scraper.py` | `_archive_keys` returns the reconciled file row; `handle_file_download` builds from it; drop `aria_case_info` plumbing | replay `request:3998` — all 18 fields populated on the emitted files, **0 errors** |

`tests/local/test_StateNewYorkCourtPassTest.py`: 82 passed, 76 subtests passed.
`ruff check` and `ruff format` clean.

Corpus-wide counts in this report and in the ledger stay at their **pre-fix**
values; the re-sweep is what moves them.

## 5. Derived value set — `PartyRole`

13,281 rows, 27 distinct, 1 singleton, `P(unseen) ≈ 0.000075`. Deliberately
**not** merged into `FilingRole`: that is the role a *filing* belongs to, read
off a filing type or a file name. This is the party's posture, and it is a wider
set — it names the posture in the action below (`Defendant`, `Third-Party
Defendant`) as well as on the appeal, and covers roles that never file anything
(`Child`, `Certifying Court`).

| value | n | | value | n |
|---|---|---|---|---|
| Respondent | 6,154 | | Nonparty | 21 |
| Appellant | 4,019 | | Intervenor-Appellant | 22 |
| Amicus Curiae | 1,658 | | Respondent in Original Proceeding | 22 |
| Defendant | 603 | | Third-Party Respondent | 23 |
| Petitioner | 147 | | Nonparty-Respondent | 15 |
| Child | 125 | | Claimant | 9 |
| Appellant-Respondent | 104 | | Third-Party Appellant | 9 |
| Respondent-Appellant | 86 | | Nonparty-Appellant | 8 |
| Plaintiff | 63 | | Certifying Court | 4 |
| Interested Party | 57 | | Law Guardian | 4 |
| Third-Party Defendant | 57 | | Incapacitated Person | 3 |
| Intervenor-Respondent | 38 | | Intervenor-Defendant | 3 |
| Intervenor | 24 | | Guardian Ad Litem | 2 |
| | | | Fourth-Party Defendant | 1 |

A compaction pass on the tokens (`third-party`/`fourth-party`/`nonparty` ×
`appellant`/`respondent`/`defendant`) would give two smaller axes, but the
cross-product is sparse — 27 of the ~40 combinations never occur — so a flat
enum is the honest shape. No junk tokens: unlike California's party roles, every
value here is a real role.

Other closed sets, left as `str` (see §7): `link_status` (3 values,
`P(unseen)=0`) and `match_confidence` (3 values, `P(unseen)=0`).

## 6. Coverage arithmetic

Deduplicating the 256 duplicate docket emissions first:

```
distinct nested files                    19,399
  available                              14,206
  sealed / not available                  5,193
distinct downloaded NYCourtPassFile      14,206
available but not downloaded                  0
downloaded but not marked available           0
```

**Exact.** No unexplained residual. The apparent 21,331 → 14,206 gap is entirely
the 5,193 sealed files plus the 1,932 rows the duplicate dockets add.

## 7. Decisions taken (2026-08-16)

| # | Proposal | Decision |
|---|---|---|
| 1 | Dedupe the 256 duplicate grid rows (§3.5) | **No.** Left as the site states it. Downloads already collapse via `deduplication_key`, so it costs requests, not correctness. |
| 2 | Split `attorneys[].firm` into principal + office (§3.7) | **No.** CL's `Attorney`/`Role` has nowhere to put the named principal, so the split field would have no destination. The whole line is stored, so nothing is lost. |
| 3 | Drop `aria_case_info` | **Yes — done.** Removed from the model, `DocketResultsParser`, and the scraper's `accumulated_data`. The §3.4 unescape fix went with it: dropping the field is the stronger repair. |
| 4 | Drop `local_path` from the nested `files[]` | **No — kept.** The merge SQL joins the docket's files to the emitted `NYCourtPassFile` on `(docket_number, file_index)` to pick the path up, so the field is that join's landing site rather than dead weight. Recorded in the field's docstring. |
| 5 | Promote `link_status` / `match_confidence` to enums | **No.** They are our provenance labels, not the Court's vocabulary, and the 3-value sets are self-describing as strings. |

Still open, not yet decidable:

* **The `docket_by_number` stratum is corpus-unreachable.** `case_short_name`,
  `search_page` and `search_row` are all null-by-design on that entry point,
  and this sweep never ran it, so those verdicts carry no `when:` predicate
  yet.

## 8. Re-sweep

Re-run the full `dockets_by_bulk` sweep, then re-audit. The next report should
confirm:

| assertion | expected |
|---|---|
| `aria_case_info` present at all | 5,088 → **0** (field dropped) |
| `party-whitespace-collapsed` | 5,513 → **0** |
| `party-name-whitespace-collapsed` | 3,738 → **0** |
| `attorney-name-whitespace-collapsed` | 3,170 → **0** |
| `lower-court-citation-not-a-sentinel` | 11 → **0** |
| `every-issue-recognized` | 1 → **0** |
| `NYCourtPassFile.doc_type` etc. filled | 0 → ~**13,200** (matching the nested copies) |
| `party_role_raw` filled | unreachable → **13,281**, agreeing with the pre-fix `party_role` string |
| `party_role` unclassified with nonempty raw | **0** (a nonzero count is new-role drift) |
| `docket-number-emitted-once` | 496 (unchanged unless §7.1 is taken) |
| `official-citation-is-a-citation` | 10 (court-side; unchanged) |
| `decision-not-before-argument` | 13 (court-side; unchanged) |

Also worth watching after the re-sweep: `firm LIKE 'Hon.%'` at 4,317, to see
whether the whitespace fix moved it (it should not — that count is about
content, not spacing).

## Proposed `CC_NOTES.md` delta

Add under a new "Data quality" heading, rather than a parallel document:

> * The emitted `NYCourtPassFile` and the copy nested on the docket are the
>   same file. Before 2026-08-15 only the nested copy carried the
>   reconciliation output; both do now, so a consumer can read a file's role,
>   doctype and entry link without re-joining. `local_path` is still only on
>   the emitted record; `available=false` files exist only on the nested one.
> * The Docket.aspx grid lists one case on several consecutive rows: 240
>   numbers appear more than once in the 2026-08-08 sweep, 256 extra dockets in
>   all, up to 5 copies of one JCR number. Copies are identical but for
>   `search_row`. File downloads are unaffected — `deduplication_key` collapses
>   them, and available-vs-downloaded reconciles to zero on both sides.
> * Court-PASS double-escapes the grid's `aria-label`, so it needs a second
>   `html.unescape` after the HTML parse.
> * `attorneys[].firm` is the attorney-of-record line, not a firm name: 35% of
>   values are `person, office` (`Hon. Letitia James, New York State Attorney
>   General`). `attorney_name` is a different person.
