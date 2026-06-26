# Washington Appellate Courts — ACDocPortal (acdocportal.courts.wa.gov) — CC Notes

> Conforms to [`../../SCRAPER_STANDARDS.md`](../../SCRAPER_STANDARDS.md).
> JSON API consumer (per §3.5: no `parsers/` package — wire-format pydantic
> models in `api/responses.py`, reshaping in a module helper). Plain HTTP
> (`driver_requirements = []`). Two appellate courts (`wash`, `washctapp`),
> addressed by a single speculative `dockets_by_number` entry whose
> `CourtRange` carries the target `court_id` (§4 multi-court speculative).
> Model fields follow [`../../CL_MODELS.md`](../../CL_MODELS.md): `court` (not
> `court_id`), `docket_number` (not `docket_id`), `date_*` date naming.

## Site Overview

- **Base URL**: `https://acdocportal.courts.wa.gov/PublicAccess/`
- **Backend**: JSON KeywordSearch API. The HTML search pages
  (`search_sc.html` / `search_ca.html`) are reCAPTCHA-gated in a browser, but
  the underlying API endpoints are open to direct HTTP clients — no captcha,
  no session cookies.
- **Requires Playwright**: No — pure JSON over plain HTTP.

The API: `POST /PublicAccess/api/CustomQuery/KeywordSearch` returns every
public document filed on a case in one response; document bytes are fetched
from `GET /PublicAccess/api/Document/<id>/?OverlayMode=View`.

## Courts Covered

| Site | CourtListener ID | Case-number width |
|------|------------------|-------------------|
| Washington Supreme Court | `wash` | 7 digits |
| Washington Court of Appeals (all divisions) | `washctapp` | 6 digits |

The portal does not split the Court of Appeals by division on this search;
all three divisions resolve under `washctapp`.

## Search Capabilities

Each court has a `(QueryID, KeywordID)` pair (see `COURT_QUERY_PARAMS`). The
search keyword is the zero-padded case number; `QueryLimit: 0` returns all
documents for the case. A no-match returns `Data: []` (speculative miss).

## Scraper Architecture

### Entry point (§4)

| Entry | Param | Purpose |
|-------|-------|---------|
| `dockets_by_number(docket_number)` | `CourtRange` | Speculative case-number probe; `docket_number.court_id` selects the court. Seed once per court. |

This is a multi-court speculative scraper, so the entry takes ONLY the
speculative `CourtRange` (no `court_ids` arg) and the court rides on the
param (§4). `CourtRange.court_id` is used directly as the CL court id.

### Steps & priorities (§5)

```
dockets_by_number → parse_search_response (2) → handle_document_download (archive=1)
```

`parse_search_response` is at priority 2 (flow ≥ 2); document downloads are
`archive=True` (auto priority 1).

### Deduplication keys (§6)

- `search_response:<court>:<docket_number>` — the KeywordSearch POST.
- `<court>-<docket_number>-<safe_doc_id>` — each archived PDF (no colons; the
  opaque document id is sanitized to filename-safe characters).

### Data types

- `WaDocket` (→ CL `Docket`) with nested `WaDocketEntry` (→ `DocketEntry`).
- `WaDownloadedDocument` (→ `RECAPDocument`) emitted per archived file,
  joinable back via `(court, docket_number, document_id)`.

### Wire-format models

`api/responses.py` validates the raw KeywordSearch JSON verbatim
(`extra="forbid"`) so upstream schema drift fails loudly. The display columns
are positional (stable across SC/CA); only headings differ.
