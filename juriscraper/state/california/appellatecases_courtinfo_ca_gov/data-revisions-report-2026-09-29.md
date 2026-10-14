# Data revisions report — appellatecases.courtinfo.ca.gov — 2026-09-29

First data audit of this scraper. `revise-scraper` asked whether everything on
the page is extracted; this asks whether what came off the page is sane.

## 1. Corpus

| | |
|---|---|
| Run dbs | 9, one per court, `../juriscraper-runs/cal-august/ca-*.2.db` (~250 GB) |
| Scraper commit | `79acbab16` (`personal-main`) |
| Sweep window | 2026-08-17 → 2026-09-11, one completed run per db |
| Results | 1,589,694 rows |
| Requests | 7,934,526 |

| result type | rows | invalid | `dict` rows |
|---|---:|---:|---:|
| `CaAppDocket` | 1,119,345 | 0 | 0 |
| `CaDocument` | 236,000 | 0 | 0 |
| `CaAppCaseUnavailable` | 209,257 | 0 | 0 |
| `CaUnavailableOpinion` | 25,092 | 0 | 0 |

**The corpus is exceptionally clean.** Zero `result_type='dict'` rows (no
payload failed `confirm()`), zero `is_valid=0`, and the `errors` table is empty
in all nine dbs. Every model-shaped view sees every row, so nothing in this
report is hidden behind a validation failure. `court` equals the run db on all
1,119,345 dockets, so `court` is a clean stratum.

Residual ledger: `residuals.yaml` is present and its entries are all
`disposition: chrome`. It carries uncommitted edits from other work; this audit
did not touch it. No `schemas.json` (this scraper parses HTML, not JSON).

Dockets per court: cal 296,776 · 1st 120,260 · 2nd 334,509 · 3rd 98,044 ·
4th/1 49,231 · 4th/2 83,116 · 4th/3 57,686 · 5th 28,677 · 6th 51,046.

## 2. Verdict rollup

103 declared paths over 4 root models. Every inventory path has a verdict and
every ledger entry names a live path — both set differences are empty.

| verdict | entries |
|---|---:|
| `ok` | 98 |
| `null-by-design` | 37 |
| `coded` | 3 |
| `null-unreachable` | 2 |
| `redundant` | 2 |
| `suspect` | 1 |

(Entries exceed 103 because a path carries one verdict per `when:` stratum.)

**No previous report**, so there is no cross-run diff. This is the baseline.
Ten `assert` blocks are recorded in `data_audit.yaml`; the next audit's job is
to diff their row counts.

**No path is null across the whole corpus.** The canonical failure this pass
hunts for — a selector that silently returns nothing everywhere — does not
occur. All 37 `null-by-design` verdicts were confirmed against stored markup,
not inferred from a docstring.

## 3. Actionable findings

Ranked by rows affected.

### 3.1 The Fifth District sweep is ~13 years stale — `null-unreachable`

**The single most consequential finding, and it is a corpus defect, not a
data defect.**

`calctapp_5th` stops at docket `F067752`, filed **2013-08-15**. Every other
court reaches July–September 2026.

| court | max `date_filed` | max docket | open cases | filed in 2026 |
|---|---|---|---:|---:|
| calctapp_5th | **2013-08-15** | **F067752** | **1** | **0** |
| others | 2026-07-16 … 2026-09-11 | — | 1,249–91,589 | 574–4,102 |

This is a truncated run, not a site limit: the speculative not-found probes
also stop, at `F066888`, so the scraper **never asked** for anything later. At
the other courts' rate of roughly 1,000–1,600 new dockets a year, **order
25,000–30,000 Fifth District dockets are missing** — the court's corpus is
roughly half the size it should be.

It also explains two findings that first looked like extraction bugs:
`calctapp_5th` has zero outstanding briefs (so `briefs[].date_due` is 0% —
that field is populated only on unfiled briefs), and only 4,210 archived
documents against 13,850–84,074 elsewhere.

Corroboration from the run itself: the 5th's 28,677 parties pages were all
fetched inside **13 minutes** (2026-08-17 22:48 → 23:01), where every other
court's equivalent step ran for days (the 2nd's from 2026-08-17 to 2026-09-24).
The run did not fail — it ran out of case numbers to ask for.

**Action: re-sweep `calctapp_5th` from F067752 forward.** No code change.

### 3.2 Party name truncated into `role` — `null-bug`, **fixed**

`_parse_party_cell` split the site's `"Name : Role"` line on the **first**
`" : "`. A party name that itself contains the separator lost everything after
it. B247344's cell reads, verbatim in the stored markup:

```
In the Matter of : The Rael Family 1993 Inter Vivos Trust, Dated February 2, 1993 : Overview party
```

which came out as `name="In the Matter of"`, `role="The Rael Family 1993 Inter
Vivos Trust, Dated February 2, 1993 : Overview party"`.

**Blast radius is exactly 2 rows** (B247344, B317107) — and that is a complete
count, not a sample: `rpartition` differs from `partition` only on lines with
two or more separators, which is precisely the set `role LIKE '%:%'` measures.

Fixed in `parsers/parties.py`. Verified below.

### 3.3 `subscription_urls` and `source_entry_point` are redundant — **proposed, not applied**

- **`subscription_urls`** — exactly one URL on every one of 1,119,345 dockets,
  and fully derivable: `email.cfm?dist={dist}&doc_no={docket_number}`, with
  `dist` already in `COURT_CONFIG`. Zero dockets have none, zero have more
  than one. The field stores 1.1 M strings that carry no information.
- **`source_entry_point`** — constant `'dockets_by_number'` on all 1,119,345
  rows. It records the only entry point the sweep used, so it distinguishes
  nothing. Worth keeping only if a future sweep adds a second entry point.

Both are cheap to drop and expensive to discover were wrong, so neither is
applied. **Your call.**

### 3.4 `parties[].role` — 250,795 rows whose role is not a role

7.8% of all 3,207,077 party rows have a `role` that names no party position:

| value | rows |
|---|---:|
| `Overview party` | 99,472 |
| `Other` | 88,052 |
| `Unknown` | 45,387 |
| `Information only` | 17,884 |

These are the site's own labels, heaviest on the 2nd District (150,543 rows,
13.2% of its parties) and lightest on the 5th (0.39%). Not a scraper defect —
but a consumer reading `role` as a party position is wrong on one row in
thirteen. They need real vocabulary members or an explicit null. Recorded as
assertion `role-is-a-party-role`.

Also: **1,050 rows carry a site-truncated role** — `Plaintiff-appellant-x/respond`
(1,040) and `Intervenor, appellant and cross-respond` (10). The full text is
not in the markup, so this is unrecoverable; recorded as `role-not-truncated`.

### 3.5 Three court-asymmetric nulls that are the *court's* omission, not ours

Each looked like an extraction bug from the fill census and was resolved
against stored pages. All three are now documented on the fields themselves.

- **`scheduled_actions` empty on cal, 3rd and 5th** (423,497 dockets). The
  `parse_scheduled_actions` step has **zero** requests on those three courts
  and exactly one per docket on the other six. Their pages carry no
  `a#actionTab` — verified on C106762 (3rd) and a 5th-District parties page,
  both listing six tab anchors, not seven. The scraper's gate reads the site's
  own signal and is correct.

  > **This corrects the `revise-scraper` note of 2026-09-24**, which recorded
  > that the `calctapp_3rd` and `calctapp_5th` dbs "predate the Scheduled
  > Actions step and hold none of those pages". The request timestamps say
  > otherwise: all nine courts' parties pages were fetched in the same window,
  > the 3rd's starting 2026-08-17 20:59 and the 2nd's 2026-08-17 19:06 — and
  > the 2nd's, fetched the same evening, **do** carry `actionTab`. The step
  > existed and ran in that run; it is the 3rd's and 5th's pages that lack the
  > anchor. Sampled five 3rd-District and four 5th-District stored pages across
  > each court's full request-id range: `actionTab` appears in none of them.
- **`date_argued` 0% on 4th Div 2** (83,116 dockets, 22,259 of which have an
  oral-argument *docket entry*). Division 2 never emits the `Oral Argument
  Date/Time:` row; checked against six random closed-and-argued Division 2
  pages plus a recent one. Other CoA courts fill it on 7–23%.
- **`division` empty on six courts.** The site renders the label with an empty
  `<dd>`. Verified on E088908.

### 3.6 `division` carries the court's own legacy junk — `suspect`, not fixable

33,143 dockets have a non-numeric division: `p` (30,121, 2nd District), `a`
(2,491, 2nd), `v` (522, 1st), plus `d`/`Y`/`R`. Verified faithful against
B004324's stored markup — `<dt>Division:</dt><dd>p</dd>`. The site says `p`.

Separately, **`division` means two different things**: the Supreme Court's
values are sitting locations (SF 235,205 · LA 56,606 · SD 4,318 · FR 403 ·
SA 240), not divisions. Now documented on the field.

### 3.7 `disposition_type` — 39 rows of order prose

807,937 of 807,976 CoA dispositions (99.995%) are `Final` / `Vacated` /
`Partial`. The other 39 are 1980s–90s records where the court typed prose into
the field: `DISMISSED & REMANDED PER ORDER MAY 13, 1993`, or a participants
list, `(A) SMITH, J. (C) KLINE, P. J., PETERSON, J.`

`disposition_notes` is null on most of them, so the cell holds **only** the
prose — there is no type to recover and the parser is reporting the cell
faithfully. **No fix applied**; a rule tuned to 39 legacy rows would be
over-fitted. Recorded as assertion `dispo-type-is-a-type`.

### 3.8 Small site data errors, recorded not fixed

| assertion | rows | of |
|---|---:|---|
| `docket-dates-ordered` (`date_terminated < date_filed`) | 77 | 1,119,345 |
| `judgment-date-plausible` | 58 | 535,138 |
| `entry-date-plausible` (e.g. an entry dated 2088-07-06) | 41 | 17,140,681 |
| `attorney-address-not-sentinel` | 30 | 3,231,386 |
| `docket-date-plausible` (S154973 filed `7007-07-18`, closed 2007) | 2 | 1,119,345 |

**Two clean negatives worth stating**, because they are where this pass usually
pays off: the corpus has **no** `CONFIDENTIAL ADDRESS` sentinel cluster (the 30
address placeholders are 5 distinct spellings, too few to justify a
`clean_optional` rule), and **not one** attorney name parses as an address or
an organisation. The marker-based cell parsing is holding.

## 4. Changes made

All verified without touching the network.

| file | change |
|---|---|
| `parsers/parties.py` | `partition(" : ")` → `rpartition(" : ")` (§3.2) |
| `vocabularies.py` | **new** — `CourtVocabulary` base + `CaPublicationStatus` |
| `models.py` | `publication_status` typed to the enum; `publication_status_raw` added on `CaAppDisposition` and `CaUnavailableOpinion`; 3 docstrings corrected from measurement |
| `vocabularies.py` | `CodedPublicationStatus` — a `BeforeValidator` so an unrecognised value can never raise |
| `parsers/disposition.py` | populates coded + raw |
| `scraper.py` | `_is_published` reads the coded value, falls back to the raw string |
| `data_audit.yaml` | **new** — the ledger, 103 paths, 10 assertions |

**Verification.** `jent replay` is unusable in this environment — it fails with
`TypeError: Request.__init__() got an unexpected keyword argument
'continuation'`, a jkent version skew inside jent's venv, unrelated to these
changes (see the tool-gap note). Each change was instead verified by running
the real parser against the real stored page, in the scraper's own venv:

- **Party fix**, on B247344's stored parties page: name and role now split
  correctly, and the two other parties on the same page
  (`David M. Davis`/`Appellant`, `Mark Real`/`Objector and Respondent`) are
  byte-identical to before — no regression on single-separator cells.
- **Publication status**, on C106762's stored disposition page:
  `publication_status` → `CaPublicationStatus.SIGNED_PUBLISHED`,
  `publication_status_raw` → `'Signed Published'`, `disposition_type` → `'Final'`.
- **`_is_published` parity**: the coded path and the raw-string fallback agree
  on **all 8** members, so the enum cannot shift which dockets become
  `CaUnavailableOpinion`. The coverage arithmetic in §6 is unchanged by it.
- **An unrecognised value cannot fail validation.** This was worth making
  structural rather than trusting the parser to be the only caller: a pydantic
  error would make jkent store the whole docket as an unvalidated `dict` row,
  losing every other field on it — strictly worse than a flag. The annotated
  type coerces an unknown string to `None` and leaves `publication_status_raw`
  populated, so a value the site adds later surfaces as coded-null beside a
  non-null raw. Confirmed: `'Brand New Status'` → `None` + raw preserved, on
  both `CaAppDisposition` and `CaUnavailableOpinion`.

Corpus-wide counts in this report are pre-fix throughout.

## 5. Derived value sets

### 5.1 `CaPublicationStatus` — applied

8 members, complete over 350,258 CoA dispositions, **P(unseen) = 0** (every
value occurs ≥ 39 times; no singleton tail).

| value | rows | code |
|---|---:|---:|
| Signed Unpublished | 306,459 | 1 |
| Signed Published | 28,705 | 2 |
| By the Court - Unpublished | 12,193 | 3 |
| Signed Partial Published | 1,408 | 4 |
| Ordered Published | 878 | 5 |
| Depublished - Review Granted or By Order | 306 | 6 |
| By the Court - Published | 270 | 7 |
| By the Court - Partial Published | 39 | 8 |

Compositional on two axes — *who issued it* (Signed / By the Court / Ordered /
Depublished) × *what became of it* (Published / Unpublished / Partial) — so the
members carry `.published`, `.partial` and `.by_the_court` properties rather
than making a consumer match eight strings. `.published` is false for
`DEPUBLISHED`, which is the trap the old substring heuristic existed to avoid.

Codes 0 and 999 are reserved, per the NY `CourtVocabulary` convention.

### 5.2 `parties[].role` — the compaction case, **not applied**

96 distinct strings over 3,207,077 rows, P(unseen) 1.3e-06. Minting a 96-member
enum would be wrong: tokenizing shows ~25 tokens on two axes.

*Party position* — plaintiff (712,682) · defendant (839,715) · petitioner
(494,019) · respondent · real party in interest (286,628) · cross-complainant
(14,727) · cross-defendant · intervener (5,205) · objector (6,151) · claimant
(842) · movant (417) · contestant · amicus curiae (15,942) · third-party
claimant · accused (4,878) · mediator (3,551).

*Appellate posture* — appellant (888,585) · respondent (1,226,636) ·
cross-appellant · cross-respondent.

*Not roles at all* — the four values in §3.4 (250,795 rows).

Two small enums plus an explicit "not a role" null, rather than one of 96.
**Not applied — the split is a modelling decision, and it is yours.** The token
counts above come from a deliberately crude splitter (it breaks `non-title` and
`pub/depublication`), so treat them as evidence of compositionality, not as a
member list.

### 5.3 Ready but not applied

- **`case_type`** — 36 values, 1,047,275 rows, P(unseen) 9.5e-07. Two disjoint
  vocabularies in one field, as the docstring says: the CoA uses two-letter
  codes (`CR` 395,958, `CV` 354,545), the SC uses descriptive phrases
  (`Review - Criminal Appeal` 97,103, `Original Proceeding - Habeas` 76,264, …).
  A clean enum, but it wants the court split made explicit.
- **`case_status`** — 35 values, 296,772 rows (SC only), P(unseen) 1.0e-05.
  Coding it would also merge `closed; remittitur issued` (3,356) and
  `remittitur issued; case closed` (2), which are one fact in two word orders.
- **`disposition_type`** — 3 real values (§3.7); nearly a boolean.
- **`lower_court_info.coa_cases[].district_division`** — 25 values,
  P(unseen) 5.6e-06. Maps 1:1 onto `COURT_IDS`.
- **`CaDocument.source_collection`** — already an enum; `UNKNOWN` has **zero**
  rows across all 236,000 documents, so the vocabulary is complete as written.
  Observed: nonpub 212,798 · archive 12,196 · revnppub 4,324 · revpub 3,524 ·
  documents 3,150.

## 6. Coverage arithmetic

Published opinions against files served and unavailability recorded:

| court | published | has file | recorded unavailable | **unexplained** |
|---|---:|---:|---:|---:|
| cal | 3,560 | 791 | 2,769 | **0** |
| calctapp_1st | 6,188 | 2,006 | 4,182 | **0** |
| calctapp_2nd | 11,940 | 2,939 | 9,001 | **0** |
| calctapp_3rd | 3,655 | 1,008 | 2,647 | **0** |
| calctapp_4th_div1 | 2,315 | 1,206 | 1,109 | **0** |
| calctapp_4th_div2 | 1,908 | 586 | 1,322 | **0** |
| calctapp_4th_div3 | 2,530 | 739 | 1,791 | **0** |
| calctapp_5th | 692 | 52 | 640 | **0** |
| calctapp_6th | 2,072 | 536 | 1,536 | **0** |

**`published = has_file + recorded_unavailable` exactly, in all nine courts.**
Nothing is rounded away — the residual is genuinely zero. The 3rd District's
row (3,655 / 1,008 / 2,647) reproduces `CC_NOTES.md`'s existing figures
exactly, which is an independent check that the corpus and this methodology
agree.

`CaUnavailableOpinion` is doing precisely the job it was designed for.

## 7. Blocked / awaiting a decision

1. **Proposed drops** — `subscription_urls`, `source_entry_point` (§3.3).
2. **`parties[].role` two-axis split** (§5.2) — needs your modelling call.
3. **Corpus-unreachable** — everything the Fifth District has filed since
   2013-08-15 (§3.1). No amount of parser work reaches it.
4. **Unclaimed data, out of scope for this pass.** The Supreme Court's briefs
   table has a `Party and Attorney` column whose cell is `&nbsp;` on every one
   of its 22,178 brief rows; the filing credit is instead prose in `Notes`
   (`by respondent Commission on State Mandates`, `By Apps, Lucia Mar Unified
   School Dist. (Perm) SF`) — populated on 17,142 of them.
   `notes_filed_by` only lifts labelled `Party:`/`Attorney:` credits, which the
   SC does not use, so it is empty for the whole Supreme Court. Extracting that
   prose is a `revise-scraper` job, not a data-audit fix. Verified on S000064.

### Proposed `CC_NOTES.md` delta

Not applied — `CC_NOTES.md` carries uncommitted edits from other work, and
these are standing measurements that belong there rather than in a parallel
document. Suggested additions:

- The step-coverage table from §3.5 (`parse_scheduled_actions`: 0 requests on
  cal/3rd/5th, one per docket on the other six).
- The Fifth District staleness row from §3.1.
- The corpus-wide coverage table from §6, which generalises the existing
  Third-District-only figures to all nine courts.
- The `division` semantics note from §3.6.

## 8. Re-sweep

1. **Re-sweep `calctapp_5th` in full** — the one change that materially grows
   the corpus (§3.1).
2. **Re-sweep enough of any CoA court** to repopulate `publication_status` /
   `publication_status_raw` under the new enum.

The next audit should confirm:

- `role-has-no-name-leak` → **0** (from 2).
- `publication_status` is non-null wherever `publication_status_raw` is, and
  the 8-member set is still complete — a new value showing up as coded-null
  with a non-null raw is the signal to add a member.
- The §6 coverage identity still closes at zero after the enum swap.
- `calctapp_5th` max `date_filed` moves from 2013-08-15 to the sweep date, and
  its `scheduled_actions`, `date_due` and document counts are re-judged
  afterwards — those verdicts are conditional on the stale sweep.
- `role-is-a-party-role` (250,795) and `dispo-type-is-a-type` (39) should be
  **unchanged**; they track the site, not the scraper. Movement means the site
  changed.
