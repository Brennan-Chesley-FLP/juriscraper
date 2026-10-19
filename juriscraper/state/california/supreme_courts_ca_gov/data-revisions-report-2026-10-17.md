# California Supreme Court briefs — data audit, 2026-10-17

`audit-data` over `../juriscraper-runs/ca-briefs/`. First audit of this
scraper; no prior report to diff against, so §2 is a baseline rather than a
delta.

## 1. Corpus

| | |
|---|---|
| Run dbs | 18, all `CalSupremeBriefsScraper`, all `completed` |
| Sweep | 2026-09-16 (requests), index cutoff 2026-09-10 |
| Scraper commit | `2c0d9aa24` + the uncommitted `revise-scraper` work of 2026-10-16 |
| Requests | 11,767 — 18 index, 193 session pages, 11,556 brief PDFs |
| Errors | **0**, of every type |
| Results | 193 `CalSupremeArgumentSession`, 1,290 `CalSupremeBriefCase`, 11,556 `CalSupremeDownloadedBrief` |
| `result_type='dict'` rows | **0** — no payload failed `confirm()` |
| `is_valid = 0` rows | **0** |

Two session pages (`august-24-2026`, `september-9-2026`) were fetched by two
shards each. After deduplicating on `source_url` the corpus is **191
sessions, 1,284 case listings (1,227 distinct case numbers), 11,506 brief
listings, 11,466 downloaded PDFs** — byte-for-byte the figures in CC_NOTES,
which is the first thing that had to agree before anything below is worth
reading.

**Residual ledger state**: clean. `residuals.yaml` carries 0 unidentified and
0 orphaned entries at full width (per the 2026-10-16 revision); its two live
entries are both dispositioned `chrome`. No JSON steps, so no `schemas.json`.
That matters here because it rules out the usual companion of a `null-bug` —
a null field that is also an unclaimed residual cluster. Every always-null
field below is null for a reason that is *not* "the parser never saw it".

**No court asymmetry.** 1,281 of 1,284 listings are `cal` and 3 are
`calctapp_3rd`, and every field behaves identically on both, so almost no
verdict in the ledger needs a `when:` predicate. This is the rare corpus
where that is true; it was checked, not assumed.

## 2. Verdict rollup

40 paths, all with a verdict; no ledger entry names a dead path.

| Verdict | Paths |
|---|---:|
| `ok` | 19 |
| `redundant` | 10 |
| `null-unreachable` | 5 |
| `suspect` | 3 |
| `coded` | 1 |
| `null-bug` | 1 |
| `null-by-design` | 1 |

Baseline. The next audit's diff is what says whether the fixes below held.

## 3. Actionable findings

Ranked by rows affected.

### 3.1 `filed_by` null on 226 titles — 78 of them wrongly (`null-bug`, **fixed**)

The comma-form split fires only when the title's leading chunk is a listed
party role, matched against a flat set of 18 strings. That set did not
contain the court's conjoined roles, its plurals, eight roles it genuinely
uses, or four of its own typos:

| Shape | Example | Titles |
|---|---|---:|
| conjoined roles | `Intervener and Respondent, …, Written Return` | 39 |
| unlisted role | `Pub/Depublication Requestor`, `Minor`, `Attorney General`, `Presiding Justice`, `Non-Party Movants`, `Interested Entities/Parties`, `Overview Parties` | 19 |
| plural | `Non-Title Respondents`, `Interveners` | 10 |
| dash form | `Real Parties in Interest - Preliminary Opposition` | 6 |
| the court's typos | `Real Pary in Interest`, `Applellant`, `Resps` | 5 |

The worst of these are not small: `Interveners and Appellants, <22 union
names>, Answer Brief on the Merits` landed its entire 876-character filer
list in `document_type`, a field documented as "the kind of document, with
the filer stripped off". 110 of the 226 unsplit titles were over 60
characters.

Example refs: `spectral-bird:result` on S232642 and S238309;
`crazy-skylark` on S215300.

**Fix applied** — `_role_phrase_matches()` in `parsers/_common.py` splits the
leading chunk on ` and `, depluralises each conjunct, maps the four typos,
and requires *every* conjunct to be a listed role. Strictness is the
deliberate half: `Declaration of Charles H. Bell, Jr., Regarding …`,
`Response to June 15, 2016 Order` and `Service Employees International Union,
Local 1021, Brief` also open with a comma chunk and must keep coming back
unsplit. `filed_by` 11,280 → **11,358**; the 148 that remain are genuinely
bare (`Order`, `Case Summary`, `General Docket`).

### 3.2 `document_type` is a vocabulary, not free text (`coded`, **fixed**)

954 distinct values over 11,506 listings — but the shape is a vocabulary with
a tail, not free text. After the 3.1 fix, 894 distinct; 37 types account for
90.15%.

The compaction pass found the court's spelling variance, and nothing deeper:

- a trailing `Filed` on 20 otherwise-identical titles (`Opening Brief on the
  Merits` / `Opening Brief on the Merits Filed`)
- `Authority` for `Authorities` in 26 letters
- casing (`Reply brief`, `Answer to Petition For Review`)

It also found what *is not* compositional, which is the more useful result:
stripping leading modifiers (`Amended`, `Supplemental`, `Second
Supplemental`) collapses 894 distinct values to 859 and raises coverage by
0.3 points. The 9.8% tail is genuinely open — 692 singletons, `P(unseen) =
0.060` — one-off titles the court wrote for the occasion. A bigger enum does
not help: going from 37 members to 202 buys 4 points.

**Fix applied** — `vocabularies.py` adds `CaBriefDocumentType`, a 37-member
`CourtVocabulary` on the sibling CA scraper's pattern: `(value, code, label)`,
codes 0 and 999 reserved, `parse()` normalising the three variance classes
above, and a `BeforeValidator` that degrades to `None` instead of raising —
so an uncovered title costs a code, never a record. Three derived properties
(`is_amicus`, `is_letter`, `is_review_stage`) expose the questions a consumer
actually has.

`CalSupremeBrief.document_type_raw` is new and holds the verbatim split
(always populated); `document_type` holds the coded member. Per `CL_MODELS.md`:
raw into `*_raw`, the usable value in the base name.

### 3.3 Thirteen titles are double-encoded (`suspect`, **fixed**)

`Amicus Curiae Brief of George GascÃ³n`, `… Death Penalty â€“ No on Prop. 62`.

The question that decides the verdict is whose fault it is, and the stored
bytes answer it: `private-hummingbird:request:9` holds
`b"Gasc\xc3\x83\xc2\xb3n"` under `content-type: text/html; charset=UTF-8`.
That is valid UTF-8 spelling out the mojibake — the court encoded the text
twice before writing it. Nothing in the fetch or the decode is wrong.

**Fix applied** — `fix_mojibake()` in `parsers/_common.py`, called from
`collapse_ws` so every value passes one point. The cp1252→UTF-8 round trip is
its own filter: correctly spelled accented text fails to re-decode and comes
back untouched. Verified on both directions, including the six near misses in
the corpus (`San José`, `Hernández v. Muñoz`, `George Gascón` spelled right).

Corpus-wide: 13 → **0**.

### 3.4 Thirty-three briefs are filed under the wrong case (`suspect`, **proposed**)

Where a PDF's filename names a case number, it should be the case it is filed
under. 33 briefs across 10 cases disagree, and they are two different things:

**(a) 7 single-row filename typos** — `s152394` under S152934, `s197387`
under S198387, `s090449` under S090499, plus `s053328`, `s045969`, `s107556`.
Every other file on those cases agrees. Harmless.

**(b) 26 rows of real misattribution.** On `may-3-4-and-5-2016`, **S213468**
(PERRIS v. STAMPER, an eminent-domain case) carries S097886's 9 briefs, and
**S215914** (PEOPLE v. MORAN) carries S228030's 5. Each is an exact duplicate
of that same page's listing for the real case — proven *byte-identical* by
the download archive's content hash, since the court's `_0` re-uploads share
a `local_path` with the originals. Neither pair is in CC_NOTES; both were
found by the assertion and then read on the page.

On the three hand-authored blocks the defect is worse: the link text and the
`href` are a **permutation** of each other. S130263's block labels
`11-s130263-dept-corr-rehab-resp-brief-…pdf` as "Petitioner's Traverse", and
five of its fifteen `href`s point at S251333 and S252057 — different dockets
entirely. S198132's block mixes in four files from S249495 and S249397.

This is the court's HTML, and the scraper records it faithfully — which is
the standing convention here ("Both are recorded; neither is corrected from
the other"). But a consumer joining on `(court, docket_number)` will file 26
PDFs under the wrong case, and nothing in the record warns it.

**Proposed, not applied** — a `CalSupremeBrief.filename_docket_number` field,
populated only when `docket_number_from_filename()` disagrees with the
listing's `docket_number`. That states the disagreement without resolving it,
which is the only honest option: on the hand-authored blocks there is no way
to tell from the page whether the text or the `href` is the error. Held back
because it changes what the scraper stores.

Assertion `filename-names-the-listing-case` in the ledger selects all 33 with
refs.

### 3.5 Eleven filing dates carry an impossible year (`suspect`, **proposed**)

`0005-11-07`, `0010-…`, `0021-…` (×4), `0022-…` (×2), `0025-…`, `2222-05-20`,
`5017-09-05`. All are the court's typos, read verbatim off `Filed on <Month
D, YYYY>`, and CC_NOTES already names them. The 1997–2008 dates are genuine,
from long-running capital cases.

Reading them verbatim is right; *storing* them as a date is not. A
`date_filed` of 5017 sorts to the end of every index that touches it, and
`CalSupremeDownloadedBrief` copies it too.

**Proposed, not applied** — null `date_filed` when the year falls outside
1990–(current year + 1), and add `date_filed_raw` carrying the court's text,
so nothing is lost and the date column stays usable. Held back for the same
reason as 3.4, and because dropping 11 data points silently is exactly the
change that is cheap to make and expensive to discover was wrong.

### 3.6 `session_note` and `documents` null on all 191 sessions (`null-unreachable`)

Not a bug, and worth stating because the fill census makes it look like the
worst finding in the corpus. Both fields were added by `revise-scraper` on
2026-10-16; the corpus was swept on 2026-09-16. The stored *pages* carry the
data, the stored *results* predate the parser that reads it.

Confirmed by replay against those same pages:

- `masterful-baboon:request:4` (October 7 2014 outreach) → the full note,
  including the three cases called that afternoon in argument order
- `spectral-bird:request:5` (September 29 2016 special) → the note **and**
  both session documents

Resolved by the re-sweep, not by a code change.

## 4. Changes made

| File | Change | Verified by |
|---|---|---|
| `parsers/_common.py` | `fix_mojibake()`, called from `collapse_ws` | replay `private-hummingbird:9` — `George Gascón` in both `description` and `filed_by`; 0/11,506 mojibake corpus-wide on re-parse |
| `parsers/_common.py` | `_singular_role()` / `_role_phrase_matches()`; `_COMMA_FORM_ROLES` cut to singulars + 8 new roles; `_ROLE_TYPOS`; dash form | re-parse of all 191 pages: `filed_by` 11,280 → 11,358, and the four non-role control titles still unsplit |
| `vocabularies.py` *(new)* | `CaBriefDocumentType` (37 members), `CodedBriefDocumentType` | replay ×5 sessions, 0 invalid; coded 10,373/11,506 = 90.15% |
| `models.py` | `CalSupremeBrief.document_type_raw` added; `document_type` retyped to the coded vocabulary | 1,284/1,284 cases validate on a full re-parse |
| `parsers/session_page.py` | emits the raw split into both fields | as above |
| `tests/local/test_cal_supreme_briefs_scraper.py` | +8 tests, 4 subtest groups | 30 passed, 30 subtests |
| `CC_NOTES.md` | three new sections; two new Known Site Defects; Next Steps replaced | — |
| `data_audit.yaml` *(new)* | 40 paths, 4 assertions | every inventory path has a verdict; every entry names a live path |

**Replay verification, per changed behaviour** (`'request:<id>' replay`):

| Request | Session | Results | Invalid | `document_type` coded | `filed_by` | note / docs |
|---|---|---:|---:|---|---:|---|
| `spectral-bird:9` | May 3–5 2016 | 191 | 0 | 138/172 | 162/172 | — |
| `spectral-bird:5` | Sep 29 2016 special | 47 | 0 | 40/42 | 42/42 | **note + 2 docs** |
| `masterful-baboon:4` | Oct 7 2014 outreach | 49 | 0 | 39/42 | 42/42 | **note** |
| `famous-puma:5` | Sep 3–4 2019 | 87 | 0 | 77/77 | 77/77 | — |
| `private-hummingbird:9` | Apr 4–5 2017 | 129 | 0 | 107/117 | 117/117 | mojibake repaired |

Corpus-wide counts in §3 stay at their pre-fix values; the re-sweep is what
moves them.

## 5. Derived value sets

`CaBriefDocumentType`, as shipped — counts from the re-parse of all 191 pages
with the 3.1 fix applied, so they are what the next sweep should produce.

| Code | Member value | n | Merged variants |
|---:|---|---:|---|
| 1 | Amicus Curiae Brief | 1,323 | |
| 2 | Answer Brief on the Merits | 977 | `… Filed` |
| 3 | Opening Brief on the Merits | 973 | `… Filed` |
| 4 | Reply Brief on the Merits | 959 | `… Filed` |
| 5 | Petition for Review | 959 | `… Filed` |
| 6 | Supplemental Brief | 763 | `… Filed` |
| 7 | Request for Judicial Notice | 649 | `… Filed` |
| 8 | Answer to Petition for Review | 464 | `… For Review`, `… Filed` |
| 9 | Response to Amicus Curiae Brief | 430 | `… Filed` |
| 10 | Focus Issues Letter | 416 | `… Filed` |
| 11 | Reply to Answer to Petition for Review | 379 | `… Filed` |
| 12 | Reply Brief | 324 | `Reply brief`, `… Filed` |
| 13 | Brief | 324 | `… Filed` |
| 14 | Opening Brief | 302 | `Opening brief`, `… Filed` |
| 15 | Additional Authorities Letter | 205 | `Additional Authority Letter` |
| 16 | Opposition | 177 | `… Filed` |
| 17 | Notice of Errata | 104 | |
| 18 | Letter Brief | 100 | |
| 19 | Reply to Supplemental Brief | 85 | |
| 20 | Supplemental Reply Brief | 68 | `… Filed` |
| 21 | Supplemental Letter Brief | 51 | |
| 22 | Request to Answer Question of State Law | 41 | `… State law` |
| 23 | Written Return | 40 | `… Filed` |
| 24 | New Authorities Letter | 30 | `New Authority Letter` |
| 25 | Supplemental Opening Brief | 27 | `… Filed` |
| 26 | Motion | 24 | |
| 27 | Traverse | 23 | |
| 28 | Letter | 23 | |
| 29 | Joinder to Brief on the Merits | 17 | |
| 30 | Petition for Writ of Habeas Corpus | 16 | `… Filed` |
| 31 | Joinder to Petition | 16 | |
| 32 | Informal Response | 16 | |
| 33 | Response Brief re Referee's Report | 15 | |
| 34 | Reply to Informal Response | 15 | |
| 35 | Exhibits | 15 | |
| 36 | Supplemental Authorities Letter | 13 | `Supplemental Authority Letter` |
| 37 | Order | 10 | `Order Filed` |

**10,373 / 11,506 = 90.15%.** Uncovered head of the tail, as a sense of what
a future member would have to be: `Supplemental Reply Letter Brief` (9),
`Preliminary Opposition to Writ Petition` (9), `Request for Depublication`
(9), `Reply Letter Brief` (8), `Expanded Background Summary` (8),
`Exceptions/Briefing Filed re Referee's Report` (7), `Petition for Writ of
Mandate` (7), `General Docket` (7), `Errata Letter` (7).

`filed_by` was **not** coded. 1,693 distinct values with `P(unseen) = 0.096`,
and the overwhelming majority are amicus organisation names — the filer *is*
the datum, not a category. Verdict `ok`, not `coded`.

## 6. Coverage arithmetic

**Extraction completeness** — every `.pdf` href on every stored page, against
every brief link extracted:

| | |
|---|---:|
| Distinct `.pdf` hrefs across the 191 pages | 11,507 |
| Brief links extracted | 11,505 |
| Unexplained | **0** |

The 2-link gap is one page, `september-29-2016-special-session`, and the two
links are its session-level documents (`SSEP2916A.pdf`, the expanded case
summaries) — correctly not briefs. Every other page matches exactly.

**Download reconciliation:**

| | |
|---|---:|
| Brief listings | 11,506 |
| … with a URL | 11,505 |
| Distinct `(court, docket_number, url)` | 11,467 |
| Download records (deduped) | 11,466 |
| … with a `local_path` | 11,466 |
| Downloaded but never listed | 0 |
| **Listed but never downloaded** | **1** |

The one is named rather than rounded away: S211645's
`11-s211645-resp-hartford-reply-brief-merits-031114.pdf`. The case is listed
under two sessions, and the court serves that file from two paths —
`/documents/` and `/2022-05/`. The download dedup key is
`<docket_number>-<filename>`, i.e. the **basename**, so the two URLs collapse
to one fetch. That is correct behaviour — it is one file — but it means
`CalSupremeBrief.url → CalSupremeDownloadedBrief.brief_url` is not a total
join. **Join on `(court, docket_number, filename)` instead.** No code change
proposed; the dedup key is right.

**`local_path` collisions** are a result, not a defect: 30 pairs share a
content hash, which is what established the court's `_0` re-uploads as
byte-identical duplicates, and in turn what settled finding 3.4(b).

## 7. Blocked / awaiting a decision

Nothing is corpus-unreachable except `session_note` / `documents`, which the
re-sweep resolves. Four decisions are the user's:

1. **`filename_docket_number`** (3.4) — add the field, or accept that 26 PDFs
   are attributed to the wrong docket with no flag. *Recommend: add it.*
2. **`date_filed` out-of-range years** (3.5) — null + `date_filed_raw`, or
   keep carrying `5017-09-05`. *Recommend: null + raw.*
3. **`date_argued`** — fully derivable (`date_session_start` when the session
   is one day, else null; 462 filled, 0 disagreements). The skill says propose
   the drop. *Recommend: keep it.* It is the field CL's `Docket.date_argued`
   wants, and the derivation rule — "only when the session ran one day,
   because the page never says which day" — is the scraper's knowledge, not
   the consumer's to re-derive.
4. **The 37-member cut-off** at n≥10 / 90.15%. Dropping to n≥5 adds 27
   members for 1 point; n≥2 adds 165 for 4. *Recommend: leave it at 37.*

Also noted, no action: `heading_raw`, `court`, and the four denormalized
session fields on `CalSupremeBriefCase` are all `redundant` and all kept on
purpose — reasons in the ledger.

## 8. Re-sweep

Re-run the full backfill (`briefs_by_argument_date`, 2010 → present: 1 index
fetch + 191 session pages; PDFs are already archived and will dedup).

The next audit should confirm:

| Measure | Now | Expected |
|---|---:|---:|
| `session_note` filled | 0 / 191 | 6 / 191 |
| sessions with `documents` | 0 / 191 | 1 (2 documents) |
| `filed_by` filled | 11,280 | 11,358 |
| `document_type` coded | n/a | 10,373 / 11,506 (90.15%) |
| `document_type_raw` filled | n/a | 11,506 |
| mojibake in `description` | 13 | 0 |
| `document-type-tail-is-growing` | n/a | 1,133 — rising means new members |
| `filename-names-the-listing-case` | 33 | 33 (site defect; a change means the court edited a page) |
| `date-filed-year-is-plausible` | 11 | 11, unless decision 2 is taken |

Case and brief counts must stay at 1,284 / 11,506. Any movement there is the
site changing, not the fixes.
