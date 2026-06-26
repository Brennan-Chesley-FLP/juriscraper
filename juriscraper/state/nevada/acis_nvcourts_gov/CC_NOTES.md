# Nevada appellate courts (`acis.nvcourts.gov`)

Nevada Supreme Court (`nev`) and Court of Appeals (`nevapp`) — the Appellate
Case Information System (ACIS), a Thomson Reuters **C-Track Public Portal**
deployment. Pure JSON REST API — no browser required (`driver_requirements =
[]`).

Shared infrastructure lives in [`common/tr`](../../common/tr/) (`TRPortalMixin`
+ the `TR*` base models); this scraper is a thin subclass that supplies the
API/portal URLs, the court config, and the per-page step priorities.

## Courts

| court_id | Name | C-Track GUID | courtID | abbreviation |
| --- | --- | --- | --- | --- |
| `nev` | Nevada Supreme Court | `dc01122c-a19d-4eb7-bfe9-5b96e93c26fd` | `1` | `Supreme Court` |
| `nevapp` | Nevada Court of Appeals | `74764f58-a87f-4ec5-8233-7a1255e410b3` | `2` | `Court of Appeals` |

Pulled live from `https://acis-api.nvcourts.gov/courts` (the `resourceID`,
`externalIdentifier`, and `displayName` fields); `courtAbbreviation` on the
case-search and events feeds matches `displayName`.

## Hosts

- API: `https://acis-api.nvcourts.gov`
- Portal: `https://acis.nvcourts.gov`

## Entry points

The driver seeds `court_ids` and the date range.

| Entry | Returns | Addressing |
| --- | --- | --- |
| `dockets_by_filing_date(court_ids, date_range)` | `NevDocket` | server-side filed-date search over `cms/cases` |
| `oral_arguments_by_argument_date(court_ids, date_range)` | `NevOralArgument` | server-side start-date search over `cms/events` |

## Flows

**Dockets** (`parse_dockets_search` 6 → `parse_case_detail` 5 →
`parse_case_parties` 4 → `parse_docket_entries` 3 → `parse_documents_list` 2 →
archive downloads → `parse_document_download` 2): the search splits its date
window whenever a window hits the 10,000-result API cap, and drops detail
requests for courts outside `court_ids`. Each case fans out detail → parties →
entries → documents; documents are emitted as separate `NevDocument` records
joined back to the `NevDocket` by `case_instance_uuid`.

**Oral arguments** (`parse_events_list` 3 → `parse_event_hearings` 2): the
events feed is all-courts, so `parse_events_list` filters down to `court_ids`
(carried in `accumulated_data["target_courts"]`) and the requested date window.

## Quirks

- No publications/opinions feed: `cms/publications` returns zero results for
  both courts, so there is no opinions flow (dispositions surface as docket
  entries) — unlike Alabama, which does use publications.
- Replaces the older `caseinfo.nvsupremecourt.us` scraper
  (`nevada/caseinfo_nvsupremecourt_us/`); Nevada migrated to this C-Track ACIS
  portal.
