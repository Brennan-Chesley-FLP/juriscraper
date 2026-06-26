# Alabama appellate courts (`publicportal.alappeals.gov`)

Alabama Supreme Court (`ala`), Court of Civil Appeals (`alactapp`), and Court of
Criminal Appeals (`alacrimapp`). Current data comes from the Thomson Reuters
**C-Track Public Portal** JSON API; pre-May-2023 opinions come from plain-HTML
release-list pages on judicial.alabama.gov / acis.alabama.gov. No browser/JS
needed (`driver_requirements = []`).

The docket and oral-argument flows delegate to the shared
[`common/tr`](../../common/tr/) `TRPortalMixin`; the publications (opinions) and
historical flows are Alabama-specific (publications also reuse the mixin's
list/pagination helpers, with an Alabama-specific `parse_publication_detail`).

## Courts

| court_id | Name | C-Track GUID | Clerk |
| --- | --- | --- | --- |
| `ala` | Alabama Supreme Court | `68f021c4-6a44-4735-9a76-5360b2e8af13` | Megan B. Rhodebeck |
| `alactapp` | Court of Civil Appeals | `1da1a297-c391-4e4f-9480-1bc68b46f21a` | Seth Rhodebeck |
| `alacrimapp` | Court of Criminal Appeals | `b82b30d5-bd3c-46d7-9451-1cb05e470873` | D. Scott Mitchell |

## Hosts

- API: `https://publicportal-api.alappeals.gov`
- Portal: `https://publicportal.alappeals.gov`
- Historical: `https://judicial.alabama.gov/decision/*` → PDFs on
  `https://acis.alabama.gov/displaydocs2.cfm`

## Entry points

The driver seeds `court_ids` and the date range.

| Entry | Returns | Addressing |
| --- | --- | --- |
| `opinions_by_bulk(court_ids, date_range)` | `AlaOpinionCluster` / `AlaOrder` | bulk publications pull, client-side date filter |
| `historical_opinions_by_bulk(court_ids, date_range)` | `AlaHistoricalReleaseList` | bulk HTML release-list pages, client-side date filter |
| `oral_arguments_by_argument_date(court_ids, date_range)` | `AlaOralArgument` | server-side start-date search over `cms/events` |
| `dockets_by_filing_date(court_ids, date_range)` | `AlaDocket` | server-side filed-date search over `cms/cases` |

## Flows

**Opinions** (`parse_publications_list` 4 → `parse_publication_detail` 3 →
archive → `handle_opinion_download` / `handle_order_download` 2): the
publications endpoint has no server-side date filter, so the mixin pulls each
court's list, paginates, and filters client-side (results sorted by publication
date descending). `parse_publication_detail` splits each item by `documentName`
— Opinion/Decision → `AlaOpinionCluster`, everything else → `AlaOrder` — extracts
lower-court info and "In re:" names from the title, and archives the PDF.

**Historical opinions** (`parse_historical_decisions_list` 3 → archive →
`handle_historical_pdf_download` 2): the pre-May-2023 weekly release-list PDFs.
`verify=False` on the acis.alabama.gov download — its cert is issued to
`www.acis.alabama.gov` with no SAN for the bare domain.

**Dockets** (`parse_dockets_search` 6 → `parse_case_detail` 5 →
`parse_case_parties` 4 → `parse_docket_entries` 3 → `parse_documents_list` 2 →
archive → `parse_document_download` 2): standard TR docket flow. Splits the date
window on the 10,000-result cap and drops courts outside `court_ids`.

**Oral arguments** (`parse_events_list` 3 → `parse_event_hearings` 2): standard
TR events flow, filtered to `court_ids` and the date window.

## Quirks

- Documents are filed from ~March 2022 onward; viewing requires registration, so
  anonymous archive requests typically fail and `AlaDocument.local_path` is
  `None` (metadata still captured).
- May 19, 2023 is the cutover: before it, opinions live on judicial.alabama.gov /
  acis.alabama.gov (the historical flow); on/after, on the Public Portal.
- `caseHeader.courtID` is `1`=Supreme, `2`=Criminal, `3`=Civil; case-detail
  responses return a different numeric (68/69/70) that the scraper ignores.
- YouTube oral-argument video URLs are not exposed by the API
  (`AlaOralArgument.youtube_url` stays unset).

## Known standards deviation

`parse_historical_decisions_list` does its (single-selector) HTML extraction
inline rather than in a `JKentParser` under a `parsers/` package (§9). It is a
single `find_links` + a date regex, tightly coupled to per-row archive-request
yielding, so it was left inline; promote it to a parser if the historical page
grows more structure.
