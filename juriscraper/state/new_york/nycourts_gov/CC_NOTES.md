# New York Court of Appeals — Court-PASS (courtpass.nycourts.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md). This
> is the **reference scraper** the standards doc points to for flow/parsers.
> Single court (`ny`, NY Court of Appeals). The site is behind a Cloudflare
> managed challenge and is an ASP.NET WebForms app with ViewState-driven
> postback navigation, so it runs under Playwright
> (`driver_requirements = [JS_EVAL, FF_ALIKE, STRICTLY_SERIAL, CFCAP_HANDLER]`).
> HTML extraction lives in the `parsers/` package (§9); the steps keep the
> navigation concerns (form fills, postbacks, pagination, file downloads).
> Model fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not
> `court_id`), `date_*` date naming, `CleanString`/`HarmonizedCaseName`
> cleaning from `juriscraper.state.common_models`.

## Site Overview

- **Base URL**: `https://courtpass.nycourts.gov`
- **Backend**: ASP.NET WebForms (ViewState postbacks), Cloudflare edge.
- **Requires Playwright**: Yes — Cloudflare managed challenge + JS-driven
  postback navigation. `STRICTLY_SERIAL` because each interaction depends on
  the prior page's ViewState.

Every flow starts at `Docket.aspx`. Two pages carry the data: the
docket-detail span (`cphMain_lbDetails`) gives the caption, argument date,
FILINGS table, and ATTORNEY DETAILS; the filing-detail span
(`cphMain_lbDetails2`, loaded via the hidden `bttnDetails` postback) gives the
decision date, issues, official citation, 'Reported Below' lower-court
citation, and the `gvFiles` file list. Docket-detail fields ride forward in
`accumulated_data["deferred_docket"]` so one merged `NYCourtPassDocket` is
emitted only after both pages are seen.

## Courts Covered

| Site name | CourtListener ID |
|-----------|------------------|
| New York Court of Appeals | `ny` |

## Scraper Architecture

### Entry points (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `docket_by_number(court_id, docket_number)` | `str`, `str` | Single-record direct lookup by APL/CTQ/JCR number (e.g. `APL-2024-00177`). |
| `dockets_by_bulk(court_ids, argument_date, decision_date)` | `set[str]`, `DateRange`, `DateRange` | The site only exposes the whole undecided-docket set (no server-side date search). Walks the full result grid; the optional `argument_date` / `decision_date` windows are applied **client-side** as the chain descends — hence the `*_by_bulk` name (§4 "Bulk + client-side filtering"). |

The `argument_date` filter is enforced in `parse_docket_results` (date is in
the grid); the `decision_date` filter is enforced in
`parse_docket_filing_detail` because the decision date is only on the
filing-detail page. Filter values travel via `accumulated_data`, never
re-read from params.

### Step functions and priorities (§5)

```
dockets_by_bulk     → fill_docket_search (6) → parse_docket_results (5)
                        ├→ (per row) parse_docket_detail (4)
                        │       → parse_docket_filing_detail (3) → ParsedData + downloads (0)
                        └→ (pagination) parse_docket_results (5)

docket_by_number    → parse_docket_page → parse_docket_number_results
                        → parse_docket_detail_for_entry
                        → parse_filing_detail_from_docket → ParsedData + downloads
```

Enumeration priorities descend by depth (6 → 5 → 4 → 3) so in-flight cases
finish before new ones start. File downloads use `priority=0` / `archive=True`.

### Parsers (§9)

- `DocketResultsParser` — one record per `gvResults` grid row
  (`case_short_name`, `argument_date`, `aria_case_info`, `search_row`).
- `DocketDetailParser` — caption, argument date, FILINGS (docket_entries),
  ATTORNEY DETAILS (attorneys) from `cphMain_lbDetails`.
- `FilingDetailParser` — decision date, official_citation,
  lower_court_citation ('Reported Below'), issues, `no_files_for_case`,
  and `gvFiles` file rows from `cphMain_lbDetails2`. The case-details
  `dl` only ever carries four labels on real pages (Argument Date,
  Decision Date, Official Citation, Reported Below);

### File-name convention and the gvFiles → FILINGS join

`filename_convention.py` (package root, not a page parser — it reads no HTML)
implements the Court's published PDF naming convention,
[techspecs.htm](https://www.nycourts.gov/ctapps/techspecs.htm) (effective
2/1/13):

```
title of action-role-name-doctype[-volN].pdf
SmithvJones-app-Smith-brf.pdf
SmithvJones-app-Smith-Rec-vol1.pdf
```

This matters because the two pages carry disjoint halves of one fact: the
FILINGS table has `date_received` / `date_due` but no document, and `gvFiles`
has the document but no dates. The file name encodes role, party, and document
type — the same three fields a FILINGS row keys on — so the two can be joined.
`reconcile_files_and_entries` is called from `_stamp_and_reconcile` at both
filing-detail merge sites and returns **both** collections annotated.

On each `NYCourtPassFile`:

- `doc_role`, `doc_party`, `doc_type`, `volume`, `part` — parsed components.
- `document_group` — which logical document the file belongs to; volumes and
  parts of one record share it, and each group maps to exactly one entry.
- `docket_entry_index` — the `entry_index` of its entry.
- `link_status` — `matched` (a real FILINGS row) / `inferred` (a synthesized
  entry) / `court_generated` (no entry).
- `match_confidence` — for `matched` only: `exact` (type + role + party agree)
  / `strong` (type plus one of role/party) / `weak` (compatible type, resolved
  by elimination).
- `date_received`, `date_due` — inherited from the linked entry.

On each `NYCourtPassDocketEntry`:

- `entry_index` — so `(docket_number, entry_index)` is the composite key
  `NYCourtPassFile.docket_entry_index` joins against. Real FILINGS rows keep
  table order and come first; inferred entries are appended, so these are
  stable.
- `raw_filing_type`, `entry_role`, `entry_doctype`, `filing_type_recognized` —
  the verbatim table string plus its `(role, doctype)` reading.
- `file_indexes` — the `file_index` of its zero or more files.
- `inferred_from_file` — see below.

Matching is a greedy best-first assignment over (entry, logical-document)
pairs, so a docket with two `Respondent Brief` rows distributes its two
respondent briefs by party name rather than piling both onto the first row.

### Entries synthesized from file names

The FILINGS table is a merits-filing register, so a large class of real filings
never appears in it. Rather than drop them, `reconcile_files_and_entries`
**synthesizes** a `NYCourtPassDocketEntry` per unclaimed document group, with
`inferred_from_file=True`, `raw_filing_type=None` (no table row said it), a
`filing_type` composed by `describe_filing()` (e.g. `Appellant Motion for Leave
to Appeal`), and `date_received`/`date_due` left None — `gvFiles` carries no
dates. Every filer-submitted file therefore hangs off exactly one entry.

Court-generated files are the deliberate exception: a decision, transcript, or
webcast is the court's own output, not a filing, so it gets no entry and
`link_status='court_generated'`. Reverse that here if downstream would rather
see them as entries.

Each of the reconciliation questions is then a group-by, no re-derivation:

| Question | Query |
|---|---|
| FILINGS rows with no document | `file_indexes == []` |
| …and whether the files are fetchable | join to `NYCourtPassFile.available` |
| documents with no FILINGS row | `inferred_from_file is True` |
| …several files sharing one such entry | `len(file_indexes) > 1` |
| …whether that absence is expected | `entry_doctype in NOT_ON_FILINGS_TABLE` |
| FILINGS vocabulary drift | `not filing_type_recognized and not inferred_from_file` |

Note the last one: `filing_type_recognized=False` means two different things.
On a real row it is the drift signal — Court-PASS used a filing kind
`FILING_TYPE_MAP` predates (**zero** across the historical corpus). On an
inferred entry it just means the file name's doctype token was unreadable,
which is common. Always pair it with `inferred_from_file`.

### Measured behaviour

Over a 4,811-docket corpus (3,272 with at least one of the two lists; all
invariants below hold on every one):

- **93% of FILINGS rows resolve to a document**, 72% of those at `exact`
  confidence.
- 14,647 real entries + **3,725 inferred** (2,446 of expected type, 1,279 not).
  146 inferred entries span more than one file — mostly multi-volume `adrec`.
- Files: 11,276 `matched` (70% available) · 4,093 `inferred` (57%) · 3,980
  `court_generated` (99%).
- Real entries with no document: 699 on dockets that do have files, plus 4,202
  on dockets where nothing was posted at all. Resolution runs 90–97% for
  2012–2025 and ~49% for the current term, which is pending-case lag, not
  breakage.
- ~8% of file names have an unreadable doctype token (pre-2013 filings,
  `JurRsp`, `PSI`, typos). These get `doc_type=None`, an
  `Unclassified Filing` inferred entry, and still match on role + party when
  possible.

Order in `_DOCTYPE_PATTERNS` is load-bearing: the Appellate Division variants
must precede their Court of Appeals counterparts, or `ADreplybrf` matches the
plain `replybrf` pattern and AD material gets mis-linked to the COA reply-brief
entry.

`file_indexes` holds `file_index` values (the `gvFiles` row number), **not**
list positions — `FilingDetailParser` skips malformed rows, so the two diverge.

`document_number` is **not** usable for this join — it is exactly
`len(files) - file_index` on every docket observed (a reverse display index),
and `gvFiles` is ordered alphabetically by file name, so neither field carries
chronology.

Offline coverage: `tests/local/test_StateNewYorkCourtPassTest.py`.

`_common.py` holds `_parse_date_mdy`, `repair_pdffont_leakage` (strips the
unclosed `<style pdffontname>` markers Court-PASS emits, which otherwise
swallow the file table), and `page_from_text` (lets the filing-detail steps
repair the raw `text` before handing a clean `PageElement` to the parser).

### Deduplication keys (§6)

`<continuation-or-record>:<args>` format, no court-id prefix:
`parse_docket_page:<dn>`, `fill_docket_search:<arg>:<dec>`,
`docket_detail:<page>:<row>`, `docket_filing_detail:<dn>:<page>-<row>`,
`docket_number_results:<dn>`, `docket_detail_for_entry:<dn>`,
`filing_detail_from_docket:<dn>`, `parse_docket_results:<page>`. File
downloads use a colon-free sha1 of the case/file identifiers.

### Data types

`NYCourtPassDocket` (main, → CL `Docket` + `NYCoADocketMetadata`) with nested
`NYCourtPassDocketEntry` (→ `DocketEntry`), `NYCourtPassAttorney` (→
`Attorney`/`Role`), and `NYCourtPassFile` (→ `RECAPDocument`). File binaries
are emitted separately via `handle_file_download` and joined back by
`docket_number`.

The `DocketEntry ──*── RECAPDocument` edge CL expects is resolved in-scraper by
`NYCourtPassFile.docket_entry_index` (see the file-name convention section
above); Court-PASS itself never states which file belongs to which filing.
