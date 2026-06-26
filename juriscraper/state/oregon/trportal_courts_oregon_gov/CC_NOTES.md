# Oregon appellate courts (`trportal.courts.oregon.gov`)

Oregon Supreme Court (`or`) and Court of Appeals (`orctapp`), served by the
Thomson Reuters **C-Track Public Portal**. Pure JSON REST API — no browser
required (`driver_requirements = []`).

Shared infrastructure lives in
[`common/tr`](../../common/tr/) (`TRPortalMixin` + the `TR*` base models); this
scraper is a thin subclass that supplies the API/portal URLs, the court config,
and the per-page step priorities. See the mixin for the request-building and
parsing logic.

## Hosts

- API: `https://trportal-api.courts.oregon.gov`
- Portal: `https://trportal.courts.oregon.gov`

## Entry points

The driver seeds `court_ids` and the date range.

| Entry | Returns | Addressing |
| --- | --- | --- |
| `dockets_by_filing_date(court_ids, date_range)` | `OreDocket` | server-side filed-date search over `cms/cases` |
| `oral_arguments_by_argument_date(court_ids, date_range)` | `OreOralArgument` | server-side start-date search over `cms/events` |

## Flows

**Dockets** (`parse_dockets_search` 6 → `parse_case_detail` 5 →
`parse_case_parties` 4 → `parse_docket_entries` 3 → `parse_documents_list` 2 →
archive downloads → `parse_document_download` 2): the search splits its date
window whenever a window hits the 10,000-result API cap, and drops detail
requests for courts outside `court_ids`. Each case fans out detail → parties →
entries → documents; documents are emitted as separate `OreDocument` records
joined back to the `OreDocket` by `case_instance_uuid`.

**Oral arguments** (`parse_events_list` 3 → `parse_event_hearings` 2): the
events feed is all-courts, so `parse_events_list` filters down to `court_ids`
(carried in `accumulated_data["target_courts"]`) and the requested date window.

## Quirks

- Many Oregon appellate documents are paywalled; anonymous archive requests
  fail and the resulting `OreDocument` has `local_path=None` (metadata is still
  captured).
- Oregon's portal has no publications endpoint; dispositional opinions surface
  as docket entries of type "Case Dispositional Decision", not as a separate
  opinions flow.
