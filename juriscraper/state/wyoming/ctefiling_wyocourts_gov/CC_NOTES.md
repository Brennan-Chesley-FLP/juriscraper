# Wyoming Supreme Court (`ctefiling.wyocourts.gov`)

Wyoming Supreme Court (`wyo`) — the Appellate C-Track Electronic Filing Portal
(CTEF), a Thomson Reuters **C-Track** deployment. Pure JSON REST API — no
browser required (`driver_requirements = []`).

Shared infrastructure lives in [`common/tr`](../../common/tr/) (`TRPortalMixin`
+ the `TR*` base models); this scraper is a thin subclass that supplies the
API/portal URLs, the court config, and the per-page step priorities.

## Hosts

- API: `https://ctefiling-api.wyocourts.gov`
- Portal: `https://ctefiling.wyocourts.gov`

## Entry points

The driver seeds `court_ids` and the date range.

| Entry | Returns | Addressing |
| --- | --- | --- |
| `dockets_by_filing_date(court_ids, date_range)` | `WyoDocket` | server-side filed-date search over `cms/cases` |
| `oral_arguments_by_argument_date(court_ids, date_range)` | `WyoOralArgument` | server-side start-date search over `cms/events` |

## Flows

**Dockets** (`parse_dockets_search` 6 → `parse_case_detail` 5 →
`parse_case_parties` 4 → `parse_docket_entries` 3 → `parse_documents_list` 2 →
archive downloads → `parse_document_download` 2): the search splits its date
window whenever a window hits the 10,000-result API cap. Each case fans out
detail → parties → entries → documents; documents are emitted as separate
`WyoDocument` records joined back to the `WyoDocket` by `case_instance_uuid`.

**Oral arguments** (`parse_events_list` 3 → `parse_event_hearings` 2): the
events feed is all-courts, so `parse_events_list` filters down to `court_ids`
(carried in `accumulated_data["target_courts"]`) and the requested date window.

## Quirks

- The portal exposes no public calendar UI, but the underlying C-Track events
  API responds normally, so the oral-arguments flow works the same as the other
  TR scrapers.
- Single court (`wyo`); the court config and event-abbreviation map are trivial
  but kept uniform with the multi-court TR scrapers.
